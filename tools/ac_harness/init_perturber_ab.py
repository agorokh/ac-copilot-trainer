"""Plan and analyze the operator-gated init-perturber A/B experiment (#625).

This module never changes Steam or NVIDIA settings.  It gives the operator-owned
experiment a **boot-scoped** schedule and analyzes the multi-launch JSON reports emitted
by ``tools.ac_harness.resilient_launch --trials N``.

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

So: **one boot per arm-replicate**, settings applied from boot, graceful-first teardown
(PR #669) in both arms so the comparison lands against the graceful baseline.  Endpoints are

1. **primary** -- onset launch-index (the first freeze within the boot), right-censored at the
   boot's launch budget when no freeze occurs, compared with an exact rank-sum permutation
   test; and
2. **secondary** -- the pooled post-onset burst rate, compared with Fisher's exact test.

The paired exact sign test survives from v1 as a **sensitivity** check, re-pointed onto the
counterbalanced boot pairs (each adjacent pair holds one boot per arm).

Protocol: obtain explicit operator sign-off, then for **each** planned boot -- apply that
boot's two overlay settings, reboot, run its single printed command, and only then move to the
next boot.  Restore both settings after the final boot.  ``never_live`` launches still consume
an accumulator cycle, so they keep their launch index but are excluded from the freeze/stable
classification; a boot that is mostly ``never_live`` is marked unusable rather than scored.
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

#: Smallest replicate count per arm at which the exact rank-sum test *can* reach alpha=0.05.
#: With 4 boots per arm the most extreme attainable two-sided p is 2/C(8,4) = 0.0286; at 3 per
#: arm it is 2/C(6,3) = 0.1, so a 3-boot run cannot produce a significant result no matter how
#: cleanly the arms separate.  Refusing to conclude below this floor is the v1 discipline
#: (``MIN_TRIALS_PER_ARM``) re-derived for the boot-scoped endpoint.
MIN_BOOTS_PER_ARM = 4
DEFAULT_BOOTS_PER_ARM = 4
#: A boot must out-run the pre-registered graceful onset (~14) by a real margin, or a censored
#: observation carries no information: at 14 launches "no freeze" is unremarkable in both arms.
MIN_LAUNCHES_PER_BOOT = 20
DEFAULT_LAUNCHES_PER_BOOT = 24
#: Pre-registered baselines from the #668 graceful battery + #627 hard-kill dataset.
BASELINE_ONSET_INDEX_GRACEFUL = 14
BASELINE_ONSET_INDEX_HARD_KILL = 8
BASELINE_POST_ONSET_BURST_RATE = 0.44
#: Above this share of ``never_live`` launches the boot measured Content Manager's delivery
#: failures, not the accumulator; it is reported and excluded rather than silently scored.
MAX_NEVER_LIVE_FRACTION = 0.2
#: Enumeration guard for the exact permutation test (C(20,10) = 184756 is comfortably inside).
MAX_EXACT_PERMUTATIONS = 1_000_000
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
    onset_value: int
    post_onset_launches: int
    post_onset_freezes: int
    post_onset_burst_rate: float | None
    usable: bool
    unusable_reason: str | None
    first_uptime_h: float
    last_uptime_h: float


@dataclass(frozen=True)
class ArmSummary:
    condition: str
    boots: int
    usable_boots: int
    observed_onsets: tuple[int, ...]
    censored_boots: int
    median_onset_value: float | None
    post_onset_launches: int
    post_onset_freezes: int
    post_onset_burst_rate: float | None
    burst_ci95_low: float
    burst_ci95_high: float


def counterbalanced_sequence(
    replicates_per_arm: int,
    *,
    randomization_seed: int = DEFAULT_RANDOMIZATION_SEED,
) -> tuple[str, ...]:
    """Return seeded AB/BA pairs so every adjacent pair contains one replicate per arm.

    Under the boot-scoped design a "replicate" is a whole boot, so this counterbalances **boot
    order** rather than launch order: neither arm is systematically scheduled into the earlier
    (fresher machine, cooler hardware, earlier in the operator's session) boots.  Pair
    directions are balanced (equal AB and BA counts when ``replicates_per_arm`` is even; differ
    by at most one when odd), then shuffled under the persisted seed.
    """
    if replicates_per_arm <= 0:
        raise ValueError("replicates_per_arm must be > 0")
    ab_pairs = replicates_per_arm // 2
    ba_pairs = replicates_per_arm - ab_pairs
    pairs: list[tuple[str, str]] = [CONDITIONS] * ab_pairs + [
        tuple(reversed(CONDITIONS))
    ] * ba_pairs
    rng = random.Random(randomization_seed)
    rng.shuffle(pairs)
    sequence: list[str] = []
    for pair in pairs:
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
    if boots_per_arm < MIN_BOOTS_PER_ARM and not allow_undersized:
        raise ValueError(
            f"boots_per_arm must be >= {MIN_BOOTS_PER_ARM} "
            "(below that the exact rank-sum test cannot reach alpha even under perfect "
            "separation, so the run cannot answer the question)"
        )
    if launches_per_boot < MIN_LAUNCHES_PER_BOOT and not allow_undersized:
        raise ValueError(
            f"launches_per_boot must be >= {MIN_LAUNCHES_PER_BOOT} "
            f"(the pre-registered graceful onset is ~{BASELINE_ONSET_INDEX_GRACEFUL}; a shorter "
            "boot censors both arms and measures nothing)"
        )
    if launches_per_boot <= 0 or boots_per_arm <= 0:
        raise ValueError("boots_per_arm and launches_per_boot must be > 0")
    sequence = counterbalanced_sequence(boots_per_arm, randomization_seed=randomization_seed)
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
        "design": "boot-scoped arms (one boot per replicate); onset launch-index endpoint",
        "boots_per_arm": boots_per_arm,
        "launches_per_boot": launches_per_boot,
        "minimum_boots_per_arm": MIN_BOOTS_PER_ARM,
        "randomization_seed": randomization_seed,
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
            "never_live_policy": (
                "counts as a consumed accumulator cycle (keeps its launch index) but is "
                "excluded from the freeze/stable classification and the burst denominator; a "
                f"boot above {MAX_NEVER_LIVE_FRACTION:.0%} never_live is unusable"
            ),
        },
        "endpoints": {
            "primary": "onset launch-index (first freeze within the boot), right-censored",
            "secondary": "post-onset burst rate (freezes / classified launches from onset)",
            "sensitivity": "exact sign test over counterbalanced boot pairs on onset",
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
    expected_sequence = counterbalanced_sequence(boots_per_arm, randomization_seed=seed)
    if tuple(conditions) != expected_sequence:
        raise ValueError("plan boot conditions do not match the persisted randomization_seed")
    ab_first = 0
    ba_first = 0
    for offset in range(0, len(conditions), 2):
        pair = conditions[offset : offset + 2]
        if set(pair) != set(CONDITIONS):
            raise ValueError("plan must schedule one boot from each arm in every adjacent pair")
        if pair[0] == "overlays_on":
            ab_first += 1
        else:
            ba_first += 1
    if boots_per_arm % 2 == 0 and ab_first != ba_first:
        raise ValueError("plan pair directions must be balanced (equal AB and BA counts)")
    if abs(ab_first - ba_first) > 1:
        raise ValueError("plan pair directions must differ by at most one")
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
        # boundary REQUIRES a reboot, so machine uptime must drop. Nondecreasing uptime across
        # the boundary means the operator kept running launches on the same boot, which pools
        # two arms onto one accumulator and destroys the onset endpoint.
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


def fisher_exact_two_sided(
    arm_a_freeze: int, arm_a_total: int, arm_b_freeze: int, arm_b_total: int
) -> float:
    """Dependency-free two-sided Fisher exact p-value for a 2x2 table."""
    if min(arm_a_freeze, arm_b_freeze) < 0:
        raise ValueError("freeze counts must be non-negative")
    if arm_a_total <= 0 or arm_b_total <= 0:
        raise ValueError("arm totals must be positive")
    if arm_a_freeze > arm_a_total or arm_b_freeze > arm_b_total:
        raise ValueError("freeze counts must not exceed arm totals")
    frozen_total = arm_a_freeze + arm_b_freeze
    total = arm_a_total + arm_b_total
    denominator = math.comb(total, frozen_total)

    def probability(freeze_a: int) -> Fraction:
        return Fraction(
            math.comb(arm_a_total, freeze_a) * math.comb(arm_b_total, frozen_total - freeze_a),
            denominator,
        )

    observed = probability(arm_a_freeze)
    lower = max(0, frozen_total - arm_b_total)
    upper = min(arm_a_total, frozen_total)
    p_value = Fraction(0, 1)
    for freeze_a in range(lower, upper + 1):
        candidate = probability(freeze_a)
        if candidate <= observed:
            p_value += candidate
    return float(min(p_value, Fraction(1, 1)))


def paired_exact_two_sided(helped: int, harmed: int) -> float:
    """Exact two-sided sign test over discordant pairs."""
    if helped < 0 or harmed < 0:
        raise ValueError("discordant-pair counts must be non-negative")
    discordant = helped + harmed
    if discordant == 0:
        return 1.0
    tail = min(helped, harmed)
    one_sided_mass = Fraction(sum(math.comb(discordant, k) for k in range(tail + 1)), 2**discordant)
    return float(min(Fraction(1, 1), 2 * one_sided_mass))


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

    Enumerating every assignment of the pooled mid-ranks keeps this exact **with ties**, which
    matters because onset launch-indices are small integers that tie often and because
    right-censored boots all share the same surrogate value.  Dependency-free by design (the
    harness has no SciPy).
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
    observed = sum(ranks[:size_a])
    mean = size_a * sum(ranks) / total
    deviation = abs(observed - mean)
    tolerance = 1e-9
    extreme = sum(
        1
        for subset in itertools.combinations(range(total), size_a)
        if abs(sum(ranks[index] for index in subset) - mean) >= deviation - tolerance
    )
    return extreme / combinations


def summarize_boot(observation: BootObservation) -> BootSummary:
    """Reduce one boot to its onset index and post-onset burst counts."""
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
    # A censored boot is "onset later than the budget"; the surrogate must exceed every
    # observable onset so the rank test orders it correctly, and the report flags the bound.
    onset_value = len(launches) + 1 if onset_index is None else onset_index
    # The post-onset window STARTS AT the onset launch, matching how #668 reported the burst
    # (battery launches 14-16 plus the 6 probe launches = 4 froze / 9 launches, ~44%).
    window = () if onset_index is None else launches[onset_index - 1 :]
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
        onset_value=onset_value,
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


def _summarize_arm(condition: str, boots: Sequence[BootSummary]) -> ArmSummary:
    arm = [boot for boot in boots if boot.condition == condition]
    if not arm:
        raise ValueError(f"no boots for {condition}")
    usable = [boot for boot in arm if boot.usable]
    observed = tuple(boot.onset_index for boot in usable if boot.onset_index is not None)
    post_onset_launches = sum(boot.post_onset_launches for boot in usable)
    post_onset_freezes = sum(boot.post_onset_freezes for boot in usable)
    if post_onset_launches > 0:
        low, high = wilson_interval(post_onset_freezes, post_onset_launches)
        burst: float | None = post_onset_freezes / post_onset_launches
    else:
        low, high = 0.0, 1.0
        burst = None
    return ArmSummary(
        condition=condition,
        boots=len(arm),
        usable_boots=len(usable),
        observed_onsets=observed,
        censored_boots=sum(boot.onset_censored for boot in usable),
        median_onset_value=(
            statistics.median(boot.onset_value for boot in usable) if usable else None
        ),
        post_onset_launches=post_onset_launches,
        post_onset_freezes=post_onset_freezes,
        post_onset_burst_rate=burst,
        burst_ci95_low=low,
        burst_ci95_high=high,
    )


def _paired_sensitivity(boots: Sequence[BootSummary]) -> dict[str, object]:
    """Exact sign test over the counterbalanced adjacent boot pairs, on onset index."""
    helped = harmed = concordant = excluded = 0
    ordered = sorted(boots, key=lambda boot: boot.boot)
    if len(ordered) % 2:
        raise ValueError("paired sensitivity requires an even number of boots")
    for offset in range(0, len(ordered), 2):
        pair = ordered[offset : offset + 2]
        if {boot.condition for boot in pair} != set(CONDITIONS):
            raise ValueError("each adjacent boot pair must contain one boot per arm")
        by_condition = {boot.condition: boot for boot in pair}
        if not all(boot.usable for boot in pair):
            excluded += 1
            continue
        on = by_condition["overlays_on"].onset_value
        off = by_condition["overlays_off"].onset_value
        if off > on:
            helped += 1
        elif off < on:
            harmed += 1
        else:
            concordant += 1
    return {
        "overlays_off_later_onset_pairs": helped,
        "overlays_off_earlier_onset_pairs": harmed,
        "tied_pairs": concordant,
        "excluded_unusable_pairs": excluded,
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
    on = arms["overlays_on"]
    off = arms["overlays_off"]
    usable_on = [boot for boot in boots if boot.condition == "overlays_on" and boot.usable]
    usable_off = [boot for boot in boots if boot.condition == "overlays_off" and boot.usable]
    onset_p: float | None = None
    onset_difference: float | None = None
    if (
        usable_on
        and usable_off
        and on.median_onset_value is not None
        and off.median_onset_value is not None
    ):
        onset_p = exact_rank_sum_two_sided(
            [boot.onset_value for boot in usable_on],
            [boot.onset_value for boot in usable_off],
        )
        onset_difference = off.median_onset_value - on.median_onset_value
    if on.post_onset_launches > 0 and off.post_onset_launches > 0:
        burst_p: float | None = fisher_exact_two_sided(
            on.post_onset_freezes,
            on.post_onset_launches,
            off.post_onset_freezes,
            off.post_onset_launches,
        )
    else:
        burst_p = None
    censored_total = on.censored_boots + off.censored_boots
    if (
        min(on.usable_boots, off.usable_boots) < endpoint_floor
        or onset_p is None
        or onset_difference is None
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
    return {
        "schema": ANALYSIS_SCHEMA,
        "issue": 625,
        "design": "boot-scoped arms (one boot per replicate)",
        "primary_endpoint": "onset launch-index (first froze/wedged_init launch in the boot)",
        "secondary_endpoint": "post-onset burst rate (freezes / classified launches from onset)",
        "alpha": alpha,
        "minimum_boots_per_arm": endpoint_floor,
        "arms": {condition: asdict(summary) for condition, summary in arms.items()},
        "median_onset_difference_off_minus_on": onset_difference,
        "onset_exact_rank_sum_two_sided_p": onset_p,
        "onset_p_is_bound": censored_total > 0,
        "censored_boots": censored_total,
        "post_onset_burst_fisher_two_sided_p": burst_p,
        "paired_sensitivity": _paired_sensitivity(boots),
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
        "| condition | boots | usable | observed onsets | censored | median onset | "
        "post-onset burst (95% Wilson CI) |",
        "|---|---:|---:|---|---:|---:|---:|",
    ]
    for condition in CONDITIONS:
        arm = arms[condition]
        onsets = ", ".join(str(value) for value in arm["observed_onsets"]) or "—"
        burst = _format_optional(arm["post_onset_burst_rate"], ".1%")
        lines.append(
            f"| {condition} | {arm['boots']} | {arm['usable_boots']} | {onsets} | "
            f"{arm['censored_boots']} | "
            f"{_format_optional(arm['median_onset_value'], '.1f')} | "
            f"{burst} ({arm['burst_ci95_low']:.1%}-{arm['burst_ci95_high']:.1%}) |"
        )
    sensitivity = analysis["paired_sensitivity"]
    lines.extend(
        [
            "",
            "Onset exact rank-sum (two-sided): "
            f"p={_format_optional(analysis['onset_exact_rank_sum_two_sided_p'], '.6g')}"
            + (
                f" (BOUND — {analysis['censored_boots']} censored boot(s))"
                if analysis["onset_p_is_bound"]
                else ""
            ),
            "Post-onset burst Fisher exact (two-sided): "
            f"p={_format_optional(analysis['post_onset_burst_fisher_two_sided_p'], '.6g')}",
            f"Paired boot-pair sign test (two-sided): p={sensitivity['exact_two_sided_p']:.6g}",
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
        help=f"boots (replicates) per arm; minimum {MIN_BOOTS_PER_ARM}",
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
                f"Endpoint floor is {MIN_BOOTS_PER_ARM} usable boots/arm "
                f"(scheduled {args.boots_per_arm}/arm, {args.launches_per_boot} launches each); "
                f"pre-registered graceful onset is ~{BASELINE_ONSET_INDEX_GRACEFUL} launches, "
                f"post-onset burst ~{BASELINE_POST_ONSET_BURST_RATE:.0%}."
            )
            print(
                "Paste each command on the Windows rig from that checkout's root "
                "(cd to the rig's ac-copilot-trainer clone first; report paths are "
                "checkout-relative under .scratch — never the planner host's absolute path)."
            )
            for boot in plan["boots"]:
                report_path = _checkout_relative_report_path(destination, boot["report"])
                print(f"\n{boot['boot']:03d} {boot['condition']} — apply settings, REBOOT, then:")
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
