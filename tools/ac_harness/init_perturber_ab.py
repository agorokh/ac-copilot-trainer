"""Plan and analyze the operator-gated init-perturber A/B experiment (#625).

This module never changes Steam or NVIDIA settings.  It gives the operator-owned
experiment a **boot-scoped randomized-block** schedule and analyzes the multi-launch JSON
reports emitted by ``tools.ac_harness.resilient_launch --trials N``.

Design (2026-07-24 redesign, issue #625 "REDESIGN REQUIRED")
------------------------------------------------------------
The v1 plan this module used to emit is **withdrawn**.  It interleaved single launches
inside one boot and compared a pooled per-launch freeze rate, which assumes the #619 freeze
is an i.i.d. coin flip per launch.  The #627/#668 evidence refuted that: the freeze is a
**per-boot launch-cycle accumulator**.  Launch cycles arm it over roughly 8-14 launches per
boot (hard kills only accelerate onset ~2x: ~8 hard-teardown vs ~14 graceful); once armed the
post-onset burst rate is teardown-independent (~44% in both arms) and decays spontaneously.

Under that model the first ~8-14 launches of a boot are near-deterministically clean in
**both** arms, so the withdrawn design would have returned "no measurable effect" as a near
certain false negative and permanently ruled the overlays out.  Its power rationale
(distinguish 50% vs 80% i.i.d. rates at n>=20/arm) no longer holds, and interleaving inside a
boot is confounded by spontaneous burst decay (#668 results, methodology caveat 5).

So: **one boot per experimental unit**, settings applied from boot, graceful-first teardown
(PR #669) in both arms so the comparison lands against the graceful baseline.  Boots are
paired into **blocks** of two (one boot per arm); the arm order inside each block is
randomized independently under the persisted seed, which is the textbook randomized-block
randomization and the thing that makes the primary test exact.

Endpoints
---------
1. **primary** -- onset launch-index (the first freeze within the boot), right-censored at the
   boot's launch budget when no freeze occurs.  Compared with an exact **block permutation**
   test over the 2**blocks within-block arm swaps the randomization could actually have
   produced.  This is a *design-based* test: it assumes nothing about the boots beyond the
   randomization we performed.
2. **secondary** -- post-onset burst rate over a **fixed-length window** starting at onset,
   summarized to one rate per boot and compared with the same block permutation test.  Both
   the fixed window and the per-boot summary are deliberate: unequal follow-up lengths make
   earlier-onset boots look different for purely mechanical reasons, and pooling raw launches
   would treat within-boot launches as independent when the accumulator makes them correlated.
3. **sensitivity** -- an exact sign test over the same blocks, and a rank-sum permutation test
   over onset values.  The rank-sum figure is **assumption-dependent** (it enumerates all
   labelings, i.e. it assumes boots are exchangeable under the null) and is reported for
   information only; it never drives the conclusion.

Protocol: obtain explicit operator sign-off, then for **each** planned boot -- apply that
boot's two overlay settings, reboot, run its single printed command, and only then move to the
next boot.  Restore both settings after the final boot.  If a boot's command aborts before it
writes its report, that boot's accumulator has already advanced: **reboot again** before
re-running it, or the retry's launch indices are offset from the accumulator's.

``never_live`` is a launch-delivery failure whose record does **not** prove an AC launch cycle
occurred (Content Manager absent, or ``actuator.launch()`` raised, means nothing was spawned),
and the report schema cannot tell those apart from "acs.exe appeared then exited".  So a boot
whose onset is preceded by any ``never_live`` has an **ambiguous** onset index and is excluded
from the primary endpoint rather than scored on an assumption.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import random
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from tools.ac_harness.resilient_launch import (
    DEFAULT_GO_LIVE_TIMEOUT,
    FREEZE_VERDICTS,
    REPORT_SCHEMA,
    TERMINAL_VERDICTS,
    repo_checkout_root,
    resolve_report_path,
)

PLAN_SCHEMA = "init-perturber-ab-plan/v2"
ANALYSIS_SCHEMA = "init-perturber-ab-analysis/v2"
#: the interleaved single-boot design this module used to emit; refuted 2026-07-24 and
#: rejected by :func:`load_plan` so a stale plan file cannot be analyzed as if it were valid.
WITHDRAWN_PLAN_SCHEMA = "init-perturber-ab-plan/v1"
CONDITIONS = ("overlays_on", "overlays_off")
DEFAULT_ALPHA = 0.05
DEFAULT_RANDOMIZATION_SEED = 625
DEFAULT_CAR = "ks_porsche_911_gt3_r_2016"
DEFAULT_TRACK = "spa"
DEFAULT_STABILITY_WINDOW = 140.0

#: Smallest block count at which the design-based block permutation test *can* reach
#: alpha=0.05.  The randomization draws one of ``2**blocks`` arm orders, so the most extreme
#: attainable two-sided p is ``2/2**blocks``: 0.125 at 4 blocks, 0.0625 at 5, **0.03125 at 6**.
#: Below this floor no amount of separation can produce a significant result, so the analysis
#: refuses to conclude.  (An earlier draft used balanced AB/BA counterbalancing and quoted
#: 2/C(8,4)=0.0286 at 4 blocks; that figure came from enumerating *all* labelings rather than
#: the ones the randomization can emit.  Balanced counterbalancing actually shrinks the
#: reference set — 6 schedules at 4 blocks, min p=0.33 — so it was dropped in favour of the
#: textbook independent per-block randomization below.)
MIN_BOOTS_PER_ARM = 6
DEFAULT_BOOTS_PER_ARM = 6
#: Enumeration guard for the exact tests, and therefore the largest plan that stays analyzable.
#: ``build_plan`` refuses anything beyond it so a costly reboot run can never be un-analyzable.
#: The binding constraint is the PRIMARY (gating) test: it enumerates ``2**blocks``, and
#: ``2**19 = 524288`` fits while ``2**20`` does not. The rank-sum sensitivity grows far faster
#: (``C(2n, n)``, over the limit past 11 blocks) but is explicitly non-gating, so it degrades to
#: ``None`` rather than capping how large an experiment the operator may run.
MAX_EXACT_PERMUTATIONS = 1_000_000
MAX_BOOTS_PER_ARM = 19
#: Launches counted from onset (inclusive) for the burst endpoint. Fixed so every boot
#: contributes the same follow-up length regardless of when it armed.
POST_ONSET_WINDOW = 6
#: Pre-registered baselines from the #668 graceful battery + #627 hard-kill dataset.
BASELINE_ONSET_INDEX_GRACEFUL = 14
BASELINE_ONSET_INDEX_HARD_KILL = 8
BASELINE_POST_ONSET_BURST_RATE = 0.44
#: A boot must out-run the graceful onset AND leave room for the full burst window, or a
#: baseline-onset boot contributes no secondary observation at all.
MIN_LAUNCHES_PER_BOOT = BASELINE_ONSET_INDEX_GRACEFUL + POST_ONSET_WINDOW
DEFAULT_LAUNCHES_PER_BOOT = 24
#: Above this share of ``never_live`` launches the boot measured Content Manager's delivery
#: failures, not the accumulator; it is reported and excluded rather than silently scored.
MAX_NEVER_LIVE_FRACTION = 0.2
_Z_95 = 1.959963984540054


@dataclass(frozen=True)
class PlannedBoot:
    boot: int
    condition: str
    report: str


@dataclass(frozen=True)
class LaunchObservation:
    """One launch inside a boot, in the order the accumulator saw it."""

    launch: int
    verdict: str
    started_at_utc: str
    elapsed_s: float
    uptime_h: float


@dataclass(frozen=True)
class BootObservation:
    boot: int
    condition: str
    launches: tuple[LaunchObservation, ...]


@dataclass(frozen=True)
class BootSummary:
    boot: int
    condition: str
    launches: int
    never_live: int
    classified: int
    onset_index: int | None
    onset_censored: bool
    onset_ambiguous: bool
    never_live_before_onset: int
    onset_value: int
    burst_window: int
    burst_window_complete: bool
    post_onset_launches: int
    post_onset_freezes: int
    post_onset_burst_rate: float | None
    usable: bool
    unusable_reason: str | None
    first_uptime_h: float
    last_uptime_h: float


@dataclass(frozen=True)
class BlockSummary:
    block: int
    overlays_on_boot: int
    overlays_off_boot: int
    onset_difference: float | None
    burst_difference: float | None
    usable: bool
    unusable_reason: str | None


@dataclass(frozen=True)
class ArmSummary:
    condition: str
    boots: int
    usable_boots: int
    observed_onsets: tuple[int, ...]
    censored_boots: int
    ambiguous_boots: int
    median_onset_value: float | None
    boot_burst_rates: tuple[float, ...]
    median_burst_rate: float | None
    burst_ci95_low: float
    burst_ci95_high: float


def randomized_block_sequence(
    blocks: int,
    *,
    randomization_seed: int = DEFAULT_RANDOMIZATION_SEED,
) -> tuple[str, ...]:
    """Return the arm order for ``blocks`` blocks of two boots, one boot per arm per block.

    Each block's orientation is drawn **independently** under the persisted seed. That is the
    textbook randomized-block randomization, and it is what makes
    :func:`exact_block_permutation_two_sided` exact: the reference set of the primary test is
    exactly the ``2**blocks`` orders this function could have produced.

    Balanced AB/BA counterbalancing (the earlier draft) is deliberately **not** used: fixing
    the counts restricts the randomization to ``blocks!/((blocks//2)!*(blocks-blocks//2)!)``
    orders — only 6 at 4 blocks — which caps the attainable p-value at 0.33 and makes the
    experiment unable to reach significance regardless of effect size.
    """
    if blocks <= 0:
        raise ValueError("blocks must be > 0")
    rng = random.Random(randomization_seed)
    sequence: list[str] = []
    for _ in range(blocks):
        pair = list(CONDITIONS)
        if rng.random() < 0.5:
            pair.reverse()
        sequence.extend(pair)
    return tuple(sequence)


def build_plan(
    boots_per_arm: int = DEFAULT_BOOTS_PER_ARM,
    *,
    launches_per_boot: int = DEFAULT_LAUNCHES_PER_BOOT,
    randomization_seed: int = DEFAULT_RANDOMIZATION_SEED,
    car: str = DEFAULT_CAR,
    track: str = DEFAULT_TRACK,
    layout: str | None = None,
    stability_window: float = DEFAULT_STABILITY_WINDOW,
    go_live_timeout: float = DEFAULT_GO_LIVE_TIMEOUT,
    generated_at_utc: str | None = None,
    allow_undersized: bool = False,
) -> dict[str, Any]:
    """Build a reproducible boot-scoped experiment plan; settings remain operator-owned."""
    if not car.strip() or not track.strip():
        raise ValueError("car and track must not be blank")
    if layout is not None and not layout.strip():
        raise ValueError("layout must not be blank when provided")
    if not math.isfinite(stability_window) or stability_window <= 0:
        raise ValueError("stability_window must be finite and > 0")
    if not math.isfinite(go_live_timeout) or go_live_timeout <= 0:
        raise ValueError("go_live_timeout must be finite and > 0")
    if boots_per_arm <= 0 or launches_per_boot <= 0:
        raise ValueError("boots_per_arm and launches_per_boot must be > 0")
    if boots_per_arm < MIN_BOOTS_PER_ARM and not allow_undersized:
        raise ValueError(
            f"boots_per_arm must be >= {MIN_BOOTS_PER_ARM} "
            f"(the design-based test draws from 2**blocks orders, so its smallest attainable "
            f"two-sided p is 2/2**{boots_per_arm} = "
            f"{2 / 2**boots_per_arm:.4g} — it cannot reach alpha even under perfect separation)"
        )
    if launches_per_boot < MIN_LAUNCHES_PER_BOOT and not allow_undersized:
        raise ValueError(
            f"launches_per_boot must be >= {MIN_LAUNCHES_PER_BOOT} "
            f"(pre-registered graceful onset ~{BASELINE_ONSET_INDEX_GRACEFUL} plus the "
            f"{POST_ONSET_WINDOW}-launch burst window; a shorter boot censors both arms and "
            "contributes no secondary observation)"
        )
    # Refuse at PLAN time anything the analysis could not score — a reboot run is far too
    # expensive to discover un-analyzability only after the operator has finished it.
    if boots_per_arm > MAX_BOOTS_PER_ARM:
        raise ValueError(
            f"boots_per_arm must be <= {MAX_BOOTS_PER_ARM}: the exact tests enumerate "
            f"2**{boots_per_arm} = {2**boots_per_arm} assignments, past the "
            f"{MAX_EXACT_PERMUTATIONS} enumeration limit, so the completed run would not be "
            "analyzable"
        )
    sequence = randomized_block_sequence(boots_per_arm, randomization_seed=randomization_seed)
    stamp = generated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    boots = [
        asdict(
            PlannedBoot(
                boot=index,
                condition=condition,
                report=f"boot-{index:03d}-{condition}.json",
            )
        )
        for index, condition in enumerate(sequence, start=1)
    ]
    return {
        "schema": PLAN_SCHEMA,
        "supersedes": WITHDRAWN_PLAN_SCHEMA,
        "issue": 625,
        "generated_at_utc": stamp,
        "design": "randomized block; one boot per unit, two boots (one per arm) per block",
        "boots_per_arm": boots_per_arm,
        "blocks": boots_per_arm,
        "launches_per_boot": launches_per_boot,
        "minimum_boots_per_arm": MIN_BOOTS_PER_ARM,
        "randomization_seed": randomization_seed,
        "randomization_reference_set": 2**boots_per_arm,
        "smallest_attainable_two_sided_p": 2 / 2**boots_per_arm,
        "launch": {
            "car": car,
            "track": track,
            "layout": layout,
            "stability_window": stability_window,
            "go_live_timeout": go_live_timeout,
            "trials_per_invocation": launches_per_boot,
        },
        "operator_owned_settings": True,
        "protocol": {
            "reboot_before_every_boot": True,
            "apply_settings_before_boot": True,
            "restore_settings_after_run": True,
            "graceful_first_teardown_both_arms": True,
            "one_invocation_per_boot": True,
            "retry_after_abort_requires_reboot": True,
            "condition_definitions": {
                "overlays_on": {
                    "steam_overlay_enabled": True,
                    "nvidia_shadowplay_enabled": True,
                },
                "overlays_off": {
                    "steam_overlay_enabled": False,
                    "nvidia_shadowplay_enabled": False,
                },
            },
            "abort_policy": (
                "resilient_launch writes its report only after the whole trial loop completes, "
                "so an aborted boot leaves no artifact while its launch cycles HAVE already "
                "advanced the accumulator. Reboot again before re-running that boot; a plain "
                "retry restarts launch numbering at 1 and silently offsets the onset index."
            ),
            "never_live_policy": (
                "a never_live record does not prove an AC launch cycle occurred (Content "
                "Manager absent or launch() raised means nothing was spawned) and the report "
                "schema cannot distinguish that from acs.exe appearing then exiting, so a boot "
                "whose onset is preceded by any never_live has an AMBIGUOUS onset and is "
                f"excluded from the primary endpoint; above {MAX_NEVER_LIVE_FRACTION:.0%} "
                "never_live the whole boot is unusable"
            ),
        },
        "endpoints": {
            "primary": (
                "onset launch-index (first freeze in the boot), right-censored; exact block "
                "permutation test over the 2**blocks randomization reference set"
            ),
            "secondary": (
                f"post-onset burst rate over a fixed {POST_ONSET_WINDOW}-launch window from "
                "onset, one rate per boot, same block permutation test"
            ),
            "sensitivity": (
                "exact sign test over blocks; plus an assumption-dependent rank-sum "
                "permutation test on onset, reported for information and never gating"
            ),
        },
        "prereg_baselines": {
            "onset_index_graceful": BASELINE_ONSET_INDEX_GRACEFUL,
            "onset_index_hard_kill": BASELINE_ONSET_INDEX_HARD_KILL,
            "post_onset_burst_rate": BASELINE_POST_ONSET_BURST_RATE,
            "source": "#668 graceful battery 2026-07-23; #627 hard-kill dataset",
        },
        "withdrawn_design_note": (
            "v1 interleaved single launches inside one boot and pooled a per-launch freeze "
            "rate. The #627/#668 accumulator evidence refuted the i.i.d. per-launch model: "
            "the first ~8-14 launches of any boot are near-deterministically clean in BOTH "
            "arms, so that plan would have produced a false negative. Do not run it."
        ),
        "freeze_verdicts": sorted(FREEZE_VERDICTS),
        "boots": boots,
    }


def _require_mapping(value: object, *, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a JSON object")
    return value


def load_plan(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read plan {path}: {exc}") from exc
    plan = _require_mapping(payload, where="plan")
    schema = plan.get("schema")
    if schema == WITHDRAWN_PLAN_SCHEMA:
        raise ValueError(
            f"plan schema {WITHDRAWN_PLAN_SCHEMA!r} is the withdrawn interleaved single-boot "
            "design (#625 redesign 2026-07-24) — regenerate the plan; its per-launch endpoint "
            "cannot answer the question under the accumulator model"
        )
    if schema != PLAN_SCHEMA:
        raise ValueError(f"plan schema must be {PLAN_SCHEMA!r}")
    boots_per_arm = plan.get("boots_per_arm")
    if not isinstance(boots_per_arm, int) or boots_per_arm <= 0:
        raise ValueError("plan boots_per_arm must be a positive integer")
    launches_per_boot = plan.get("launches_per_boot")
    if not isinstance(launches_per_boot, int) or launches_per_boot <= 0:
        raise ValueError("plan launches_per_boot must be a positive integer")
    seed = plan.get("randomization_seed")
    if not isinstance(seed, int):
        raise ValueError("plan randomization_seed must be an integer")
    boots = plan.get("boots")
    if not isinstance(boots, list) or not boots:
        raise ValueError("plan boots must be a non-empty list")
    expected = list(range(1, len(boots) + 1))
    observed: list[int] = []
    conditions: list[str] = []
    for index, raw in enumerate(boots, start=1):
        boot = _require_mapping(raw, where=f"plan boots[{index - 1}]")
        number = boot.get("boot")
        condition = boot.get("condition")
        report = boot.get("report")
        if not isinstance(number, int):
            raise ValueError(f"plan boot {index} has a non-integer boot number")
        if condition not in CONDITIONS:
            raise ValueError(f"plan boot {index} has invalid condition {condition!r}")
        if not isinstance(report, str) or Path(report).name != report:
            raise ValueError(f"plan boot {index} report must be a plain filename")
        observed.append(number)
        conditions.append(condition)
    if observed != expected:
        raise ValueError("plan boot numbers must be contiguous and ordered from 1")
    if len(conditions) != boots_per_arm * 2:
        raise ValueError("plan must contain exactly two boots per requested arm replicate")
    if any(conditions.count(condition) != boots_per_arm for condition in CONDITIONS):
        raise ValueError("plan must contain boots_per_arm boots for each condition")
    expected_sequence = randomized_block_sequence(boots_per_arm, randomization_seed=seed)
    if tuple(conditions) != expected_sequence:
        raise ValueError("plan boot conditions do not match the persisted randomization_seed")
    for offset in range(0, len(conditions), 2):
        if set(conditions[offset : offset + 2]) != set(CONDITIONS):
            raise ValueError("every block must hold one boot from each arm")
    return plan


def _parse_report(
    path: Path,
    boot: PlannedBoot,
    plan_launch: dict[str, Any],
    launches_per_boot: int,
) -> BootObservation:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read report {path}: {exc}") from exc
    report = _require_mapping(payload, where=f"report {path}")
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError(f"report {path} schema must be {REPORT_SCHEMA!r}")
    attempts = report.get("attempts")
    attempts_log = report.get("attempts_log")
    if attempts != launches_per_boot:
        raise ValueError(
            f"report {path} recorded {attempts!r} attempts; the plan requires exactly "
            f"{launches_per_boot} launches in this boot (run one --trials "
            f"{launches_per_boot} invocation per boot)"
        )
    if not isinstance(attempts_log, list) or len(attempts_log) != launches_per_boot:
        raise ValueError(f"report {path} must log all {launches_per_boot} launches")
    launch = report.get("launch")
    if not isinstance(launch, dict):
        raise ValueError(f"report {path} must record launch configuration")
    for key in (
        "car",
        "track",
        "layout",
        "stability_window",
        "go_live_timeout",
        "trials_per_invocation",
    ):
        if launch.get(key) != plan_launch.get(key):
            raise ValueError(f"report {path} launch.{key}={launch.get(key)!r} does not match plan")
    observations: list[LaunchObservation] = []
    for index, raw in enumerate(attempts_log, start=1):
        record = _require_mapping(raw, where=f"report {path} attempts_log[{index - 1}]")
        verdict = record.get("verdict")
        started_at_utc = record.get("started_at_utc")
        elapsed_s = record.get("elapsed_s")
        uptime_h = record.get("uptime_h")
        if record.get("attempt") != index:
            raise ValueError(f"report {path} attempt numbers must be contiguous and ordered from 1")
        if verdict not in TERMINAL_VERDICTS:
            raise ValueError(f"report {path} launch {index} has invalid verdict {verdict!r}")
        if not isinstance(started_at_utc, str):
            raise ValueError(f"report {path} launch {index} is missing started_at_utc")
        try:
            datetime.strptime(started_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError as exc:
            raise ValueError(f"report {path} launch {index} has invalid started_at_utc") from exc
        if not isinstance(elapsed_s, (int, float)) or not math.isfinite(elapsed_s) or elapsed_s < 0:
            raise ValueError(f"report {path} launch {index} has invalid elapsed_s")
        if not isinstance(uptime_h, (int, float)) or not math.isfinite(uptime_h) or uptime_h < 0:
            raise ValueError(
                f"report {path} launch {index} must record finite non-negative uptime_h "
                "(the onset endpoint is meaningless without the boot's own clock)"
            )
        observations.append(
            LaunchObservation(
                launch=index,
                verdict=verdict,
                started_at_utc=started_at_utc,
                elapsed_s=float(elapsed_s),
                uptime_h=float(uptime_h),
            )
        )
    expected_counts = {
        name: sum(item.verdict == name for item in observations) for name in TERMINAL_VERDICTS
    }
    if report.get("counts") != expected_counts:
        raise ValueError(f"report {path} counts do not match its attempts_log")
    if report.get("verdict") != observations[-1].verdict:
        raise ValueError(f"report {path} summary verdict does not match its final launch")
    stamps = [item.started_at_utc for item in observations]
    if stamps != sorted(stamps):
        raise ValueError(f"report {path} launch timestamps must not go backwards within the boot")
    uptimes = [item.uptime_h for item in observations]
    if any(later < earlier for earlier, later in zip(uptimes, uptimes[1:], strict=False)):
        raise ValueError(
            f"report {path} uptime_h must be nondecreasing within a boot "
            "(a mid-boot reboot resets the accumulator and voids the onset index)"
        )
    return BootObservation(boot=boot.boot, condition=boot.condition, launches=tuple(observations))


def load_observations(
    plan: dict[str, Any], reports_dir: Path, *, require_complete: bool = True
) -> tuple[BootObservation, ...]:
    """Load one immutable multi-launch report per planned boot and verify boot boundaries."""
    plan_launch = _require_mapping(plan.get("launch"), where="plan launch")
    launches_per_boot = plan["launches_per_boot"]
    observations: list[BootObservation] = []
    missing: list[str] = []
    for raw in plan["boots"]:
        boot = PlannedBoot(boot=raw["boot"], condition=raw["condition"], report=raw["report"])
        report_path = reports_dir / boot.report
        if not report_path.is_file():
            missing.append(boot.report)
            continue
        observations.append(_parse_report(report_path, boot, plan_launch, launches_per_boot))
    if require_complete and missing:
        preview = ", ".join(missing[:3])
        suffix = "" if len(missing) <= 3 else f" (+{len(missing) - 3} more)"
        raise ValueError(f"experiment is incomplete; missing {preview}{suffix}")
    for earlier, later in zip(observations, observations[1:], strict=False):
        if later.launches[0].started_at_utc < earlier.launches[-1].started_at_utc:
            raise ValueError(
                f"boot {later.boot} started before boot {earlier.boot} finished; "
                "boots must run in planned order"
            )
        # The inverse of the v1 check, and the sharpest guard in the boot-scoped design: a boot
        # boundary REQUIRES a reboot, so machine uptime must drop. Nondecreasing uptime means
        # the operator kept running launches on the same boot, which pools two arms onto one
        # accumulator and destroys the onset endpoint.
        if later.launches[0].uptime_h >= earlier.launches[-1].uptime_h:
            raise ValueError(
                f"uptime_h did not reset between boot {earlier.boot} "
                f"({earlier.launches[-1].uptime_h:.4f}h) and boot {later.boot} "
                f"({later.launches[0].uptime_h:.4f}h) — each arm requires its own boot"
            )
    return tuple(observations)


def wilson_interval(successes: int, total: int, *, z: float = _Z_95) -> tuple[float, float]:
    """Wilson score interval for one binomial rate."""
    if total <= 0 or successes < 0 or successes > total:
        raise ValueError("successes and total must satisfy 0 <= successes <= total and total > 0")
    proportion = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    center = (proportion + z2 / (2.0 * total)) / denominator
    spread = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z2 / (4.0 * total * total))
        / denominator
    )
    return max(0.0, center - spread), min(1.0, center + spread)


def paired_exact_two_sided(helped: int, harmed: int) -> float:
    """Exact two-sided sign test over discordant blocks."""
    if helped < 0 or harmed < 0:
        raise ValueError("discordant-pair counts must be non-negative")
    discordant = helped + harmed
    if discordant == 0:
        return 1.0
    tail = min(helped, harmed)
    one_sided_mass = Fraction(sum(math.comb(discordant, k) for k in range(tail + 1)), 2**discordant)
    return float(min(Fraction(1, 1), 2 * one_sided_mass))


def exact_block_permutation_two_sided(
    differences: Sequence[float],
    *,
    max_permutations: int = MAX_EXACT_PERMUTATIONS,
) -> float:
    """Exact two-sided randomization p-value for a randomized-block design.

    ``differences[i]`` is ``off - on`` within block ``i``. The randomization assigned each
    block's arm order independently, so under the null (the overlay settings changed nothing)
    swapping a block's arms would have flipped the sign of its difference and left the data
    otherwise identical. Enumerating all ``2**blocks`` sign vectors therefore reproduces the
    exact null distribution of the summed difference — **assuming nothing about the boots**
    beyond the randomization we actually performed. That is why this, and not the rank-sum
    figure, drives the conclusion.
    """
    blocks = len(differences)
    if blocks == 0:
        raise ValueError("at least one block is required")
    total = 2**blocks
    if total > max_permutations:
        raise ValueError(
            f"exact block permutation needs {total} assignments (limit {max_permutations})"
        )
    observed = abs(math.fsum(differences))
    tolerance = 1e-9
    extreme = sum(
        1
        for signs in itertools.product((1.0, -1.0), repeat=blocks)
        if abs(math.fsum(sign * value for sign, value in zip(signs, differences, strict=True)))
        >= observed - tolerance
    )
    return extreme / total


def _midranks(values: Sequence[float]) -> list[float]:
    """Average ranks (1-based), ties sharing their mean rank."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        stop = start
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[start]]:
            stop += 1
        shared = (start + stop) / 2.0 + 1.0
        for position in range(start, stop + 1):
            ranks[order[position]] = shared
        start = stop + 1
    return ranks


def exact_rank_sum_two_sided(
    group_a: Sequence[float],
    group_b: Sequence[float],
    *,
    max_permutations: int = MAX_EXACT_PERMUTATIONS,
) -> float:
    """Exact two-sided permutation p-value for the rank-sum statistic.

    **Assumption-dependent and non-gating.** It enumerates every labeling of the pooled values,
    which is the correct null only if the boots are exchangeable — i.e. only if boot *slot*
    (early vs late in the operator's multi-day run, machine thermal state, operator fatigue)
    carries no effect. The blocked design exists precisely because that may not hold, so this
    figure is reported for information while
    :func:`exact_block_permutation_two_sided` drives the conclusion.

    Enumerating mid-ranks keeps it exact **with ties**, which matters because onset indices are
    small integers that tie often and every censored boot shares one surrogate value.
    """
    size_a, size_b = len(group_a), len(group_b)
    if size_a == 0 or size_b == 0:
        raise ValueError("both groups must be non-empty")
    total = size_a + size_b
    combinations = math.comb(total, size_a)
    if combinations > max_permutations:
        raise ValueError(
            f"exact rank-sum enumeration needs {combinations} permutations "
            f"(limit {max_permutations})"
        )
    ranks = _midranks([*group_a, *group_b])
    observed = math.fsum(ranks[:size_a])
    mean = size_a * math.fsum(ranks) / total
    deviation = abs(observed - mean)
    tolerance = 1e-9
    extreme = sum(
        1
        for subset in itertools.combinations(range(total), size_a)
        if abs(math.fsum(ranks[index] for index in subset) - mean) >= deviation - tolerance
    )
    return extreme / combinations


def summarize_boot(observation: BootObservation) -> BootSummary:
    """Reduce one boot to its onset index and its fixed-window post-onset burst rate."""
    launches = observation.launches
    if not launches:
        raise ValueError(f"boot {observation.boot} recorded no launches")
    never_live = sum(item.verdict == "never_live" for item in launches)
    classified = len(launches) - never_live
    onset_index: int | None = None
    for item in launches:
        if item.verdict in FREEZE_VERDICTS:
            onset_index = item.launch
            break
    censored = onset_index is None
    # A never_live record does NOT prove a launch cycle reached AC (see the module docstring),
    # and the report schema cannot tell the two apart. If any precedes the onset, the onset's
    # position in the accumulator's own count is unknown by up to that many launches.
    never_live_before_onset = sum(
        item.verdict == "never_live"
        for item in launches
        if onset_index is not None and item.launch < onset_index
    )
    ambiguous = never_live_before_onset > 0
    # A censored boot is "onset later than the budget"; the surrogate must exceed every
    # observable onset so the tests order it correctly, and the report flags the bound.
    onset_value = len(launches) + 1 if onset_index is None else onset_index
    # Fixed-length follow-up so a boot that armed early does not get a longer exposure window
    # than one that armed late — unequal windows alone can manufacture a burst-rate difference.
    window_end = None if onset_index is None else onset_index + POST_ONSET_WINDOW - 1
    window_complete = window_end is not None and window_end <= len(launches)
    window = () if not window_complete else launches[onset_index - 1 : window_end]
    post_onset_launches = sum(item.verdict != "never_live" for item in window)
    post_onset_freezes = sum(item.verdict in FREEZE_VERDICTS for item in window)
    unusable_reason: str | None = None
    if classified == 0:
        unusable_reason = "no_classified_launches"
    elif never_live > MAX_NEVER_LIVE_FRACTION * len(launches):
        unusable_reason = "never_live_fraction_exceeded"
    return BootSummary(
        boot=observation.boot,
        condition=observation.condition,
        launches=len(launches),
        never_live=never_live,
        classified=classified,
        onset_index=onset_index,
        onset_censored=censored,
        onset_ambiguous=ambiguous,
        never_live_before_onset=never_live_before_onset,
        onset_value=onset_value,
        burst_window=POST_ONSET_WINDOW,
        burst_window_complete=window_complete,
        post_onset_launches=post_onset_launches,
        post_onset_freezes=post_onset_freezes,
        post_onset_burst_rate=(
            None if post_onset_launches == 0 else post_onset_freezes / post_onset_launches
        ),
        usable=unusable_reason is None,
        unusable_reason=unusable_reason,
        first_uptime_h=launches[0].uptime_h,
        last_uptime_h=launches[-1].uptime_h,
    )


def _scores_onset(boot: BootSummary) -> bool:
    """A boot contributes to the primary endpoint only with an unambiguous onset position."""
    return boot.usable and not boot.onset_ambiguous


def _summarize_arm(condition: str, boots: Sequence[BootSummary]) -> ArmSummary:
    arm = [boot for boot in boots if boot.condition == condition]
    if not arm:
        raise ValueError(f"no boots for {condition}")
    scoring = [boot for boot in arm if _scores_onset(boot)]
    observed = tuple(boot.onset_index for boot in scoring if boot.onset_index is not None)
    rates = tuple(
        boot.post_onset_burst_rate
        for boot in arm
        if boot.usable and boot.post_onset_burst_rate is not None
    )
    freezes = sum(
        boot.post_onset_freezes for boot in arm if boot.usable and boot.burst_window_complete
    )
    exposure = sum(
        boot.post_onset_launches for boot in arm if boot.usable and boot.burst_window_complete
    )
    low, high = wilson_interval(freezes, exposure) if exposure > 0 else (0.0, 1.0)
    return ArmSummary(
        condition=condition,
        boots=len(arm),
        usable_boots=len(scoring),
        observed_onsets=observed,
        censored_boots=sum(boot.onset_censored for boot in scoring),
        ambiguous_boots=sum(boot.onset_ambiguous for boot in arm if boot.usable),
        median_onset_value=(
            statistics.median(boot.onset_value for boot in scoring) if scoring else None
        ),
        boot_burst_rates=rates,
        median_burst_rate=statistics.median(rates) if rates else None,
        burst_ci95_low=low,
        burst_ci95_high=high,
    )


def _summarize_blocks(boots: Sequence[BootSummary]) -> list[BlockSummary]:
    """Pair adjacent boots into blocks and compute the within-block off-minus-on differences."""
    ordered = sorted(boots, key=lambda boot: boot.boot)
    if len(ordered) % 2:
        raise ValueError("a randomized-block analysis requires an even number of boots")
    blocks: list[BlockSummary] = []
    for index, offset in enumerate(range(0, len(ordered), 2), start=1):
        pair = ordered[offset : offset + 2]
        if {boot.condition for boot in pair} != set(CONDITIONS):
            raise ValueError("each block must contain one boot per arm")
        by_condition = {boot.condition: boot for boot in pair}
        on = by_condition["overlays_on"]
        off = by_condition["overlays_off"]
        reason: str | None = None
        if not (on.usable and off.usable):
            reason = "unusable_boot"
        elif not (_scores_onset(on) and _scores_onset(off)):
            reason = "ambiguous_onset"
        onset_difference = None if reason else float(off.onset_value - on.onset_value)
        burst_difference = (
            off.post_onset_burst_rate - on.post_onset_burst_rate
            if on.usable
            and off.usable
            and on.post_onset_burst_rate is not None
            and off.post_onset_burst_rate is not None
            else None
        )
        blocks.append(
            BlockSummary(
                block=index,
                overlays_on_boot=on.boot,
                overlays_off_boot=off.boot,
                onset_difference=onset_difference,
                burst_difference=burst_difference,
                usable=reason is None,
                unusable_reason=reason,
            )
        )
    return blocks


def _sign_test(differences: Sequence[float]) -> dict[str, object]:
    helped = sum(1 for value in differences if value > 0)
    harmed = sum(1 for value in differences if value < 0)
    return {
        "overlays_off_later_onset_blocks": helped,
        "overlays_off_earlier_onset_blocks": harmed,
        "tied_blocks": sum(1 for value in differences if value == 0),
        "exact_two_sided_p": paired_exact_two_sided(helped, harmed),
    }


def analyze(
    observations: Sequence[BootObservation],
    *,
    minimum_boots_per_arm: int = MIN_BOOTS_PER_ARM,
    alpha: float = DEFAULT_ALPHA,
) -> dict[str, Any]:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    if not observations:
        raise ValueError("analysis requires at least one boot")
    # Never allow a pilot / undersized run to claim the experiment endpoint.
    endpoint_floor = max(MIN_BOOTS_PER_ARM, minimum_boots_per_arm)
    boots = [summarize_boot(observation) for observation in observations]
    arms = {condition: _summarize_arm(condition, boots) for condition in CONDITIONS}
    blocks = _summarize_blocks(boots)
    onset_differences = [
        block.onset_difference for block in blocks if block.onset_difference is not None
    ]
    burst_differences = [
        block.burst_difference for block in blocks if block.burst_difference is not None
    ]
    onset_p = exact_block_permutation_two_sided(onset_differences) if onset_differences else None
    burst_p = exact_block_permutation_two_sided(burst_differences) if burst_differences else None
    on = arms["overlays_on"]
    off = arms["overlays_off"]
    rank_sum_p: float | None = None
    scoring_on = [
        boot.onset_value
        for boot in boots
        if boot.condition == "overlays_on" and _scores_onset(boot)
    ]
    scoring_off = [
        boot.onset_value
        for boot in boots
        if boot.condition == "overlays_off" and _scores_onset(boot)
    ]
    if scoring_on and scoring_off:
        try:
            rank_sum_p = exact_rank_sum_two_sided(scoring_on, scoring_off)
        except ValueError:
            # C(2n, n) outgrows the enumeration limit long before the primary test does. This
            # figure is explicitly non-gating, so a large-but-valid experiment degrades to
            # "not computed" instead of failing an analysis the operator paid many reboots for.
            rank_sum_p = None
    onset_difference = (
        off.median_onset_value - on.median_onset_value
        if on.median_onset_value is not None and off.median_onset_value is not None
        else None
    )
    usable_blocks = len(onset_differences)
    smallest_attainable = 2 / 2**usable_blocks if usable_blocks else None
    if (
        usable_blocks < endpoint_floor
        or onset_p is None
        or onset_difference is None
        or smallest_attainable is None
        or smallest_attainable > alpha
    ):
        conclusion = "insufficient_sample"
    elif onset_p >= alpha:
        conclusion = "no_measurable_effect"
    elif onset_difference > 0:
        conclusion = "overlays_off_delays_onset"
    elif onset_difference < 0:
        conclusion = "overlays_off_accelerates_onset"
    else:
        conclusion = "no_measurable_effect"
    censored_total = on.censored_boots + off.censored_boots
    return {
        "schema": ANALYSIS_SCHEMA,
        "issue": 625,
        "design": "randomized block (two boots per block, one per arm)",
        "primary_endpoint": "onset launch-index (first froze/wedged_init launch in the boot)",
        "secondary_endpoint": (
            f"post-onset burst rate over a fixed {POST_ONSET_WINDOW}-launch window from onset, "
            "one rate per boot"
        ),
        "alpha": alpha,
        "minimum_boots_per_arm": endpoint_floor,
        "usable_blocks": usable_blocks,
        "randomization_reference_set": 2**usable_blocks if usable_blocks else None,
        "smallest_attainable_two_sided_p": smallest_attainable,
        "arms": {condition: asdict(summary) for condition, summary in arms.items()},
        "blocks": [asdict(block) for block in blocks],
        "median_onset_difference_off_minus_on": onset_difference,
        "onset_block_permutation_two_sided_p": onset_p,
        "onset_p_is_bound": censored_total > 0,
        "censored_boots": censored_total,
        "ambiguous_onset_boots": on.ambiguous_boots + off.ambiguous_boots,
        "burst_block_permutation_two_sided_p": burst_p,
        "sensitivity": {
            "sign_test": _sign_test(onset_differences),
            "onset_rank_sum_two_sided_p": rank_sum_p,
            "rank_sum_note": (
                "assumption-dependent (requires exchangeable boots — i.e. no boot-slot "
                "effect); reported for information and never gating"
            ),
        },
        "prereg_baselines": {
            "onset_index_graceful": BASELINE_ONSET_INDEX_GRACEFUL,
            "onset_index_hard_kill": BASELINE_ONSET_INDEX_HARD_KILL,
            "post_onset_burst_rate": BASELINE_POST_ONSET_BURST_RATE,
        },
        "conclusion": conclusion,
        "boots": [asdict(boot) for boot in boots],
    }


def _format_optional(value: float | None, spec: str) -> str:
    return "n/a" if value is None else format(value, spec)


def render_markdown(analysis: dict[str, Any]) -> str:
    arms = analysis["arms"]
    lines = [
        "| condition | boots | scoring | observed onsets | censored | ambiguous | "
        "median onset | median boot burst (pooled 95% Wilson CI) |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for condition in CONDITIONS:
        arm = arms[condition]
        onsets = ", ".join(str(value) for value in arm["observed_onsets"]) or "—"
        lines.append(
            f"| {condition} | {arm['boots']} | {arm['usable_boots']} | {onsets} | "
            f"{arm['censored_boots']} | {arm['ambiguous_boots']} | "
            f"{_format_optional(arm['median_onset_value'], '.1f')} | "
            f"{_format_optional(arm['median_burst_rate'], '.1%')} "
            f"({arm['burst_ci95_low']:.1%}-{arm['burst_ci95_high']:.1%}) |"
        )
    sensitivity = analysis["sensitivity"]
    lines.extend(
        [
            "",
            f"Usable blocks: {analysis['usable_blocks']} "
            f"(randomization reference set {analysis['randomization_reference_set']}; "
            "smallest attainable two-sided p "
            f"{_format_optional(analysis['smallest_attainable_two_sided_p'], '.4g')})",
            "PRIMARY — onset, exact block permutation (two-sided): "
            f"p={_format_optional(analysis['onset_block_permutation_two_sided_p'], '.6g')}"
            + (
                f" (BOUND — {analysis['censored_boots']} censored boot(s))"
                if analysis["onset_p_is_bound"]
                else ""
            ),
            "SECONDARY — post-onset burst, exact block permutation (two-sided): "
            f"p={_format_optional(analysis['burst_block_permutation_two_sided_p'], '.6g')}",
            "Sensitivity — sign test (two-sided): "
            f"p={sensitivity['sign_test']['exact_two_sided_p']:.6g}; "
            "rank-sum (assumption-dependent, non-gating): "
            f"p={_format_optional(sensitivity['onset_rank_sum_two_sided_p'], '.6g')}",
            "Median onset difference (off - on): "
            f"{_format_optional(analysis['median_onset_difference_off_minus_on'], '+.1f')}"
            " launches",
            "Pre-registered baseline onset (graceful): "
            f"{analysis['prereg_baselines']['onset_index_graceful']}; "
            f"burst {analysis['prereg_baselines']['post_onset_burst_rate']:.0%}",
            f"Conclusion: `{analysis['conclusion']}`",
        ]
    )
    return "\n".join(lines)


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    """Create a new JSON artifact exclusively; map filesystem errors to ``ValueError``.

    Publishes via a complete temp file + exclusive hardlink (Windows: exclusive rename) so a
    mid-write crash cannot leave a truncated destination that blocks retries (#657 Qodo).
    """
    text = json.dumps(payload, indent=2) + "\n"
    tmp: Path | None = None
    fd: int | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        tmp = Path(tmp_name)
        handle = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
        fd = None
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError as exc:
            raise ValueError(f"refusing to overwrite existing artifact {path}") from exc
        except OSError as link_exc:
            if sys.platform != "win32":
                raise ValueError(f"could not write artifact {path}: {link_exc}") from link_exc
            try:
                os.rename(tmp, path)
            except FileExistsError as exc:
                raise ValueError(f"refusing to overwrite existing artifact {path}") from exc
            tmp = None
        else:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            tmp = None
    except OSError as exc:
        raise ValueError(f"could not write artifact {path}: {exc}") from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _output_path(raw: Path) -> Path:
    return resolve_report_path(raw, approved_roots=(repo_checkout_root() / ".scratch",))


def _shell_quote(token: str) -> str:
    """Quote one argv token for Windows cmd.exe paste (AC / the rig are Windows-only).

    Plan generation often runs on a Mac/dev host; the printed lines are pasted onto ``pc``, so
    host-local ``shlex.quote`` / absolute ``cd`` paths are wrong (#657 daemon).
    """
    return subprocess.list2cmdline([token])


def _checkout_relative_report_path(plan_path: Path, report_name: str) -> str:
    """Return a checkout-relative report path so commands stay runnable from the repo root."""
    checkout = repo_checkout_root().resolve(strict=False)
    report_path = (plan_path.parent / report_name).resolve(strict=False)
    try:
        return report_path.relative_to(checkout).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"boot report {report_path} must stay under the checkout (.scratch)"
        ) from exc


def _format_boot_command(
    *,
    car: str,
    track: str,
    layout: str | None,
    stability_window: float,
    go_live_timeout: float,
    launches_per_boot: int,
    report_path: str,
) -> str:
    """Build a pasteable per-boot launch line rooted at the checkout (so ``tools`` imports)."""
    parts = [
        "python",
        "-m",
        "tools.ac_harness.resilient_launch",
        "--car",
        car,
        "--track",
        track,
    ]
    if layout is not None:
        parts.extend(["--layout", layout])
    parts.extend(
        [
            "--stability-window",
            f"{stability_window:g}",
            "--go-live-timeout",
            f"{go_live_timeout:g}",
            "--trials",
            str(launches_per_boot),
            "--json",
            report_path,
        ]
    )
    return " ".join(_shell_quote(part) for part in parts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="write a boot-scoped A/B launch plan")
    plan_parser.add_argument("--out", required=True, type=Path)
    plan_parser.add_argument(
        "--boots-per-arm",
        type=int,
        default=DEFAULT_BOOTS_PER_ARM,
        help=(
            f"boots per arm (= blocks); minimum {MIN_BOOTS_PER_ARM}, maximum {MAX_BOOTS_PER_ARM}"
        ),
    )
    plan_parser.add_argument(
        "--launches-per-boot",
        type=int,
        default=DEFAULT_LAUNCHES_PER_BOOT,
        help=f"launches inside each boot; minimum {MIN_LAUNCHES_PER_BOOT}",
    )
    plan_parser.add_argument("--seed", type=int, default=DEFAULT_RANDOMIZATION_SEED)
    plan_parser.add_argument("--car", default=DEFAULT_CAR)
    plan_parser.add_argument("--track", default=DEFAULT_TRACK)
    plan_parser.add_argument("--layout", default=None)
    plan_parser.add_argument("--stability-window", type=float, default=DEFAULT_STABILITY_WINDOW)
    plan_parser.add_argument("--go-live-timeout", type=float, default=DEFAULT_GO_LIVE_TIMEOUT)
    analyze_parser = subparsers.add_parser("analyze", help="analyze completed per-boot reports")
    analyze_parser.add_argument("--plan", required=True, type=Path)
    analyze_parser.add_argument("--reports-dir", required=True, type=Path)
    analyze_parser.add_argument("--json", type=Path, default=None, dest="json_path")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan = build_plan(
                args.boots_per_arm,
                launches_per_boot=args.launches_per_boot,
                randomization_seed=args.seed,
                car=args.car,
                track=args.track,
                layout=args.layout,
                stability_window=args.stability_window,
                go_live_timeout=args.go_live_timeout,
            )
            destination = _output_path(args.out)
            _write_new_json(destination, plan)
            print(f"plan -> {destination}")
            print(
                "OPERATOR GATE: explicitly approve the Steam overlay and NVIDIA ShadowPlay "
                "settings changes; restore both after the final boot."
            )
            print(
                "BOOT-SCOPED: apply that boot's two settings, REBOOT, then run its one command. "
                "Never run two arms on the same boot — the freeze accumulator is per-boot, so "
                "sharing a boot pools the arms and voids the onset endpoint (#627/#668)."
            )
            print(
                "IF A BOOT'S COMMAND ABORTS before it writes its JSON, that boot's launch "
                "cycles have ALREADY advanced the accumulator and no artifact exists to show "
                "it. REBOOT AGAIN before re-running that boot — a plain retry restarts launch "
                "numbering at 1 and silently offsets the onset index."
            )
            print(
                f"Endpoint floor is {MIN_BOOTS_PER_ARM} usable blocks "
                f"(scheduled {args.boots_per_arm}/arm = {2 * args.boots_per_arm} boots and "
                f"reboots, {args.launches_per_boot} launches each). The randomization draws "
                f"1 of {2**args.boots_per_arm} arm orders, so the smallest two-sided p this "
                f"run can attain is {2 / 2**args.boots_per_arm:.4g}. Pre-registered graceful "
                f"onset ~{BASELINE_ONSET_INDEX_GRACEFUL}, post-onset burst "
                f"~{BASELINE_POST_ONSET_BURST_RATE:.0%}."
            )
            print(
                "Paste each command on the Windows rig from that checkout's root "
                "(cd to the rig's ac-copilot-trainer clone first; report paths are "
                "checkout-relative under .scratch — never the planner host's absolute path)."
            )
            for boot in plan["boots"]:
                report_path = _checkout_relative_report_path(destination, boot["report"])
                block = (boot["boot"] + 1) // 2
                print(
                    f"\n{boot['boot']:03d} (block {block}) {boot['condition']} "
                    "— apply settings, REBOOT, then:"
                )
                print(
                    _format_boot_command(
                        car=args.car,
                        track=args.track,
                        layout=args.layout,
                        stability_window=args.stability_window,
                        go_live_timeout=args.go_live_timeout,
                        launches_per_boot=args.launches_per_boot,
                        report_path=report_path,
                    )
                )
            return 0
        plan = load_plan(args.plan)
        observations = load_observations(plan, args.reports_dir)
        # Floor is fixed at MIN_BOOTS_PER_ARM so over-scheduling can absorb unusable boots.
        result = analyze(observations, minimum_boots_per_arm=MIN_BOOTS_PER_ARM)
        if args.json_path is not None:
            destination = _output_path(args.json_path)
            _write_new_json(destination, result)
            print(f"analysis -> {destination}")
        print(render_markdown(result))
        return 0
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
