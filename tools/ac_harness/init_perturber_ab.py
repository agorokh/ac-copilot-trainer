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

The accumulator counts launch **cycles**, not report rows, and those differ: a ``never_live``
record can mean "Content Manager was absent / ``actuator.launch()`` raised, so nothing was ever
spawned" (no cycle) or "acs.exe appeared and exited during load" (a real cycle).  Since #710 the
report states which, per attempt, in ``attempts_log[].cycle_delivered``, so onset is scored at
its position in the **delivered-cycle** count rather than its raw launch index — an undelivered
attempt shifts the mapping instead of poisoning the boot.  ``onset_ambiguous`` therefore narrows
to reports that genuinely do not know (``cycle_delivered: null``), which a rig run never emits.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import secrets
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

from tools.ac_harness.remote_launcher import RemoteLaunchError, validate_wrapper_token
from tools.ac_harness.resilient_launch import (
    DEFAULT_GO_LIVE_TIMEOUT,
    FREEZE_VERDICTS,
    REPORT_SCHEMA,
    TERMINAL_VERDICTS,
    repo_checkout_root,
    resolve_report_path,
)

#: v3 registers the endpoints in DELIVERED CYCLES (#710). The plan file IS the pre-registration,
#: so this had to move with the analysis: a v2 plan's stored ``endpoints`` still say raw
#: launch-index and a launch-counted burst window, and silently analyzing it under cycle-counted
#: rules would score it against an endpoint it never registered.
PLAN_SCHEMA = "init-perturber-ab-plan/v3"
#: v3 scores onset on delivered cycles and reports the delivery split per boot (#710).
ANALYSIS_SCHEMA = "init-perturber-ab-analysis/v3"
#: the interleaved single-boot design this module used to emit; refuted 2026-07-24 and
#: rejected by :func:`load_plan` so a stale plan file cannot be analyzed as if it were valid.
WITHDRAWN_PLAN_SCHEMA = "init-perturber-ab-plan/v1"
#: the raw-launch-index pre-registration superseded by #710; rejected for the same reason.
SUPERSEDED_PLAN_SCHEMA = "init-perturber-ab-plan/v2"
CONDITIONS = ("overlays_on", "overlays_off")
DEFAULT_ALPHA = 0.05
#: Seed used only when a caller explicitly asks to reproduce a plan. A REAL plan draws a fresh
#: seed (see :func:`build_plan`): the design-based claim rests on the schedule having actually
#: been drawn from the 2**blocks reference set, and a constant seed emits one fixed schedule.
DEFAULT_RANDOMIZATION_SEED = 625
#: Upper bound for a drawn seed; wide enough that a collision is irrelevant, small enough to
#: stay readable in the persisted plan.
_SEED_SPACE = 2**31
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
#: Default deliberately ABOVE the floor. Only blocks with a nonzero onset difference carry
#: information, and onset ties between arms are entirely expected (onsets are small integers,
#: and under the null the arms agree by construction) — a run scheduled at exactly the floor
#: therefore reports ``insufficient_sample`` as soon as one block ties. Two blocks of headroom
#: costs four extra boots and is far cheaper than re-running the whole experiment.
DEFAULT_BOOTS_PER_ARM = 8
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
#: Above this share of **undelivered** launches the boot measured Content Manager's delivery
#: failures, not the accumulator; it is reported and excluded rather than silently scored.
#: Scoped to undelivered attempts since #710: a ``never_live`` that DID start acs.exe consumed a
#: real cycle and is ordinary accumulator data, not a plumbing failure.
MAX_UNDELIVERED_FRACTION = 0.2
#: Slack when testing whether machine uptime tracked the wall clock across a boot boundary.
#: Timestamps are second-resolution and ``uptime_h`` is rounded to 4 decimals (~0.36 s), so 36 s
#: is generous for rounding while far below any real reboot's discontinuity.
_UPTIME_CONTINUITY_TOLERANCE_H = 0.01


def _parse_stamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _run_id(**fields: object) -> str:
    """Short, reproducible identifier for one generated plan.

    A pure function of the plan's inputs, so regenerating the same plan yields the same id
    (tests pin ``generated_at_utc``), while any change — including a different generation
    timestamp — yields a different one.
    """
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def _boot_epoch_h(launch: LaunchObservation) -> float:
    """When this launch's machine booted, in hours since the epoch.

    ``started_at_utc - uptime_h``. Two launches from the same boot agree on this value;
    a reboot moves it forward. This is what distinguishes "the operator rebooted" from "the
    operator kept going on the same boot", independently of how long they waited.
    """
    return _parse_stamp(launch.started_at_utc).timestamp() / 3600.0 - launch.uptime_h


@dataclass(frozen=True)
class PlannedBoot:
    boot: int
    condition: str
    report: str


@dataclass(frozen=True)
class LaunchObservation:
    """One launch inside a boot, in the order the accumulator saw it.

    ``cycle_delivered`` is the #710 report field: ``True`` when this attempt actually started an
    ``acs.exe`` (and therefore advanced the accumulator), ``False`` when it never reached AC, and
    ``None`` only when the report did not know.
    """

    launch: int
    verdict: str
    started_at_utc: str
    elapsed_s: float
    uptime_h: float
    cycle_delivered: bool | None = None


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
    #: #710 delivery split. ``delivered_cycles`` is the accumulator's own denominator for this
    #: boot; ``undelivered`` never reached AC; ``undetermined`` is a report that did not say.
    delivered_cycles: int
    undelivered_launches: int
    undetermined_launches: int
    #: Raw report row of the onset launch (1-based over ALL attempts), kept for traceability.
    onset_index: int | None
    onset_censored: bool
    onset_ambiguous: bool
    undetermined_before_onset: int
    #: Onset expressed in DELIVERED cycles — the position the accumulator actually saw. This is
    #: what the endpoints compare; ``onset_index`` can exceed it when attempts never reached AC.
    onset_cycle: int | None
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
    #: Range the TRUE ``off - on`` onset difference can occupy given right-censoring.
    #: ``None`` means unbounded on that side (a censored boot's onset is only known to exceed
    #: its launch budget). Both ``None`` = a doubly-censored block, which constrains nothing.
    onset_difference_lower: float | None
    onset_difference_upper: float | None
    #: Whether the bounds establish the SIGN of this block's difference. False means censoring
    #: leaves the ordering open, so ``onset_difference`` was zeroed rather than fed the surrogate
    #: into the permutation statistic (#710). A zero with this False is uninformative, not a tie.
    onset_sign_established: bool
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
    burst_rate_min: float | None
    burst_rate_max: float | None


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
    randomization_seed: int | None = None,
    car: str = DEFAULT_CAR,
    track: str = DEFAULT_TRACK,
    layout: str | None = None,
    stability_window: float = DEFAULT_STABILITY_WINDOW,
    go_live_timeout: float = DEFAULT_GO_LIVE_TIMEOUT,
    generated_at_utc: str | None = None,
    run_nonce: str | None = None,
    allow_undersized: bool = False,
) -> dict[str, Any]:
    """Build a boot-scoped experiment plan; settings remain operator-owned.

    ``randomization_seed=None`` (the default, and what a real run must use) **draws** a fresh
    seed and persists it in the plan. That draw is the randomization the primary test claims to
    enumerate: with a constant seed the planner emits one fixed schedule, no assignment was ever
    randomized, and enumerating the ``2**blocks`` alternative orientations would not be justified
    — a boot-slot or time effect could align with the fixed treatment order and there would be no
    randomization distribution to appeal to. Pass an explicit seed only to reproduce a known plan.
    """
    if not car.strip() or not track.strip():
        raise ValueError("car and track must not be blank")
    if layout is not None and not layout.strip():
        raise ValueError("layout must not be blank when provided")
    # Fail BEFORE the plan artifact is written: these values are pasted into cmd.exe on the rig,
    # so a metacharacter in one of them must not reach a saved plan (see :func:`_shell_quote`).
    for label, value in (("car", car), ("track", track), ("layout", layout)):
        if value is None:
            continue
        try:
            validate_wrapper_token(value)
        except RemoteLaunchError as exc:
            raise ValueError(
                f"unsafe {label} {value!r} for a pasted cmd.exe command: {exc}"
            ) from exc
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
    if randomization_seed is None:
        randomization_seed = secrets.randbelow(_SEED_SPACE)
    sequence = randomized_block_sequence(boots_per_arm, randomization_seed=randomization_seed)
    stamp = generated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Report filenames used to be a pure function of (index, condition), so two plans sharing a
    # seed and launch config produced IDENTICAL names. Dropped in one reports directory, the
    # second run's `analyze` would silently consume the FIRST experiment's reports and return a
    # stale conclusion — on an experiment that costs a dozen reboots. Namespace every report to
    # its own plan. The id is a pure function of the plan inputs, so it stays reproducible.
    # Every plan input feeds the namespace, plus a nonce. ``generated_at_utc`` is only
    # second-resolution, so two plans generated in the same tick with identical inputs would
    # otherwise collide — and a collision is expensive: the second physical run spends a whole
    # boot's launch budget before the exclusive report write fails on the existing filename.
    # When the caller pins the timestamp (tests, reproducible regeneration) the nonce defaults
    # to empty so the id stays deterministic; a real run gets fresh entropy.
    if run_nonce is None:
        run_nonce = "" if generated_at_utc is not None else secrets.token_hex(8)
    run_id = _run_id(
        generated_at_utc=stamp,
        randomization_seed=randomization_seed,
        boots_per_arm=boots_per_arm,
        launches_per_boot=launches_per_boot,
        car=car,
        track=track,
        layout=layout,
        stability_window=stability_window,
        go_live_timeout=go_live_timeout,
        run_nonce=run_nonce,
    )
    boots = [
        asdict(
            PlannedBoot(
                boot=index,
                condition=condition,
                report=f"boot-{index:03d}-{run_id}-{condition}.json",
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
        "run_id": run_id,
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
            # Documentation for the operator; `load_plan` does not read it, so a plan generated
            # before #710 still loads and analyzes under the current rules.
            "delivery_policy": (
                "every attempt records cycle_delivered (#710): onset is scored at its position "
                "in the DELIVERED-cycle count, so an attempt that never reached AC (Content "
                "Manager absent or launch() raised) shifts the mapping instead of discarding the "
                "boot. Only a report that does not know (cycle_delivered null) makes an onset "
                f"AMBIGUOUS and excludes it from the primary endpoint; above "
                f"{MAX_UNDELIVERED_FRACTION:.0%} undelivered the boot measured Content Manager, "
                "not the accumulator, and is unusable"
            ),
        },
        "endpoints": {
            "primary": (
                "onset DELIVERED-CYCLE index (first freeze in the boot, counted in launch cycles "
                "that actually reached AC), right-censored at the boot's delivered-cycle count; "
                "exact block permutation test over the 2**blocks randomization reference set. A "
                "censoring surrogate enters the statistic only when its bound establishes the "
                "sign of the block's difference (#710)"
            ),
            "secondary": (
                f"post-onset burst rate over a fixed {POST_ONSET_WINDOW}-DELIVERED-CYCLE window "
                "from onset, one rate per boot, same block permutation test"
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


#: Sentinel so an ABSENT ``cycle_delivered`` key is rejected while an explicit ``null`` (the
#: report saying "I do not know") is accepted and carried through as ambiguity.
_MISSING = object()


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
    if schema == SUPERSEDED_PLAN_SCHEMA:
        raise ValueError(
            f"plan schema {SUPERSEDED_PLAN_SCHEMA!r} pre-registered the endpoints in RAW LAUNCH "
            "INDEX; #710 moved onset and the burst window to DELIVERED CYCLES, so analyzing it "
            "now would score it against an endpoint it never registered — regenerate the plan. "
            "No data is lost: pre-#710 boot reports use the withdrawn "
            "'resilient-launch-report/v1' schema and are rejected regardless"
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
    if report.get("schema") == "resilient-launch-report/v1":
        raise ValueError(
            f"report {path} uses the withdrawn {'resilient-launch-report/v1'!r} schema, which "
            "records no per-attempt cycle_delivered flag (#710) — its never_live rows cannot be "
            "mapped onto accumulator positions. Re-run the boot on the current launcher"
        )
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
        delivered = record.get("cycle_delivered", _MISSING)
        started_at_utc = record.get("started_at_utc")
        elapsed_s = record.get("elapsed_s")
        uptime_h = record.get("uptime_h")
        if record.get("attempt") != index:
            raise ValueError(f"report {path} attempt numbers must be contiguous and ordered from 1")
        if verdict not in TERMINAL_VERDICTS:
            raise ValueError(f"report {path} launch {index} has invalid verdict {verdict!r}")
        if delivered is _MISSING:
            raise ValueError(
                f"report {path} launch {index} is missing cycle_delivered; the {REPORT_SCHEMA!r} "
                "schema records it for every attempt (#710)"
            )
        if delivered is not None and not isinstance(delivered, bool):
            raise ValueError(
                f"report {path} launch {index} has non-boolean cycle_delivered {delivered!r}"
            )
        if verdict != "never_live" and delivered is not True:
            # Every other terminal verdict requires an observation of a live acs.exe, so a report
            # claiming otherwise is internally inconsistent and must not be scored.
            raise ValueError(
                f"report {path} launch {index} records verdict {verdict!r} with "
                f"cycle_delivered={delivered!r}; only never_live may lack a delivered cycle"
            )
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
                cycle_delivered=delivered,
            )
        )
    expected_counts = {
        name: sum(item.verdict == name for item in observations) for name in TERMINAL_VERDICTS
    }
    if report.get("counts") != expected_counts:
        raise ValueError(f"report {path} counts do not match its attempts_log")
    expected_cycles = {
        "delivered": sum(item.cycle_delivered is True for item in observations),
        "undelivered": sum(item.cycle_delivered is False for item in observations),
        "undetermined": sum(item.cycle_delivered is None for item in observations),
    }
    if report.get("cycles") != expected_cycles:
        raise ValueError(f"report {path} cycles block does not match its attempts_log")
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
        # A boot boundary REQUIRES a reboot: two arms sharing one boot pool the accumulator and
        # destroy the onset endpoint. Detect it by CONTINUITY, not by magnitude. An earlier cut
        # demanded the later boot's uptime be numerically smaller, which false-rejects a real
        # reboot whenever the operator waits longer before the next boot than the previous boot
        # ran (leave it overnight, come back, uptime is legitimately higher) — and that would
        # make an already-completed, 12-reboot experiment un-analyzable.
        #
        # Each launch implies when its machine booted: ``started_at_utc - uptime_h``. Two
        # launches from the SAME boot agree on that epoch; a reboot moves it forward. Comparing
        # boot epochs states the invariant directly and is robust to how long the operator
        # waited between boots.
        earlier_epoch = _boot_epoch_h(earlier.launches[-1])
        later_epoch = _boot_epoch_h(later.launches[0])
        if later_epoch - earlier_epoch < _UPTIME_CONTINUITY_TOLERANCE_H:
            raise ValueError(
                f"boots {earlier.boot} and {later.boot} share a machine boot epoch "
                f"(implied boot times differ by only {later_epoch - earlier_epoch:.4f}h), so "
                "the machine did not reboot between them — each arm requires its own boot"
            )
    return tuple(observations)


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
    """Reduce one boot to its onset cycle and its fixed-window post-onset burst rate.

    Everything is counted in **delivered launch cycles** (#710), because that is what the #625
    accumulator arms on. An attempt that never reached AC advanced nothing, so it is skipped
    rather than either counted (which would overstate how long the arm stayed clean) or used to
    discard the boot (which was the pre-#710 conservative fallback, at one physical reboot each).
    """
    launches = observation.launches
    if not launches:
        raise ValueError(f"boot {observation.boot} recorded no launches")
    never_live = sum(item.verdict == "never_live" for item in launches)
    classified = len(launches) - never_live
    delivered_cycles = sum(item.cycle_delivered is True for item in launches)
    undelivered = sum(item.cycle_delivered is False for item in launches)
    undetermined = sum(item.cycle_delivered is None for item in launches)
    onset_index: int | None = None
    onset_cycle: int | None = None
    cycles_seen = 0
    for item in launches:
        if item.cycle_delivered is True:
            cycles_seen += 1
        if item.verdict in FREEZE_VERDICTS:
            onset_index = item.launch
            # A freeze verdict is always a delivered cycle (validated in ``_parse_report``), so
            # ``cycles_seen`` already includes this launch: the onset IS this cycle's position.
            onset_cycle = cycles_seen
            break
    censored = onset_index is None
    # Only a launch whose delivery is UNKNOWN can still shift the onset's accumulator position.
    # A known-undelivered attempt advanced nothing and is simply not counted; a known-delivered
    # one is counted. A censored boot is the same question one step further out — "no freeze in
    # N delivered cycles" is only a bound if N itself is known — so any undetermined launch
    # anywhere in the boot makes its censoring bound ambiguous too.
    if onset_index is None:
        undetermined_before_onset = undetermined
    else:
        undetermined_before_onset = sum(
            item.cycle_delivered is None for item in launches if item.launch < onset_index
        )
    ambiguous = undetermined_before_onset > 0
    # A censored boot is "onset later than the budget"; the surrogate must exceed every
    # observable onset so the tests order it correctly, and the report flags the bound. The
    # budget is the DELIVERED cycle count, not the raw launch count.
    onset_value = delivered_cycles + 1 if onset_cycle is None else onset_cycle
    # Fixed-length follow-up so a boot that armed early does not get a longer exposure window
    # than one that armed late — unequal windows alone can manufacture a burst-rate difference.
    # Measured in delivered cycles for the same reason the onset is: an undelivered attempt is
    # not exposure, and counting it would shorten the real follow-up of whichever arm suffers
    # more delivery failures.
    # An UNKNOWN row inside the span is fatal to the window, not skippable: if it really did
    # deliver, it belongs in the window and the later row that took its slot does not, so the
    # rate would be computed over the wrong six cycles (#710 Codex P2). Stop at the first one.
    window: list[LaunchObservation] = []
    window_unknown = False
    if onset_index is not None:
        for item in launches:
            if item.launch < onset_index:
                continue
            if item.cycle_delivered is None:
                window_unknown = True
                break
            if item.cycle_delivered is True:
                window.append(item)
                if len(window) == POST_ONSET_WINDOW:
                    break
    window_fits = len(window) == POST_ONSET_WINDOW
    post_onset_launches = len(window)
    post_onset_freezes = sum(item.verdict in FREEZE_VERDICTS for item in window)
    # The window must deliver the FULL pre-registered exposure to count — the boot has to have
    # run enough cycles past onset, not merely enough report rows. And an ambiguous onset makes
    # the window's own starting point untrustworthy, so it cannot anchor a rate either.
    window_complete = window_fits and not ambiguous and not window_unknown
    if not window_complete:
        post_onset_launches = 0
        post_onset_freezes = 0
    unusable_reason: str | None = None
    # "Did this boot observe the accumulator at all?" is now answered by DELIVERY, not by whether
    # some other verdict happened to occur. The old ``classified == 0`` guard discarded a boot of
    # 20 delivered never_live cycles — a perfectly good censored observation — while scoring 19
    # of the same cycles plus one stable row (#710 Codex P2).
    if delivered_cycles == 0:
        unusable_reason = "no_delivered_cycles"
    elif undelivered > MAX_UNDELIVERED_FRACTION * len(launches):
        unusable_reason = "undelivered_fraction_exceeded"
    return BootSummary(
        boot=observation.boot,
        condition=observation.condition,
        launches=len(launches),
        never_live=never_live,
        classified=classified,
        delivered_cycles=delivered_cycles,
        undelivered_launches=undelivered,
        undetermined_launches=undetermined,
        onset_index=onset_index,
        onset_censored=censored,
        onset_ambiguous=ambiguous,
        undetermined_before_onset=undetermined_before_onset,
        onset_cycle=onset_cycle,
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
    # Onsets are reported in DELIVERED cycles (#710) — the accumulator's own coordinate, and the
    # one ``onset_value`` and the endpoints are expressed in.
    observed = tuple(boot.onset_cycle for boot in scoring if boot.onset_cycle is not None)
    # Same gate as the block-level burst difference: a boot that cannot score the onset cannot
    # contribute a burst rate either, so the arm aggregate never includes one.
    rates = tuple(
        boot.post_onset_burst_rate
        for boot in arm
        if _scores_onset(boot) and boot.post_onset_burst_rate is not None
    )
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
        # Spread ACROSS BOOTS, not a pooled binomial interval. Pooling post-onset launches and
        # applying Wilson would assume independent Bernoulli draws, which the accumulator model
        # explicitly contradicts, and would overstate precision next to a per-boot median.
        # Inference on this endpoint comes from the block permutation test, not from a CI.
        burst_rate_min=min(rates) if rates else None,
        burst_rate_max=max(rates) if rates else None,
    )


def _summarize_blocks(boots: Sequence[BootSummary]) -> list[BlockSummary]:
    """Pair adjacent boots into blocks and compute the within-block off-minus-on differences."""
    # Group by the PLANNED block number, never by adjacency. `load_observations(...,
    # require_complete=False)` can drop one boot from each of two different blocks and leave an
    # even count, and slicing pairs would then fabricate a pair out of two different randomized
    # blocks — which the condition check would happily accept and the exact test would score.
    grouped: dict[int, dict[str, BootSummary]] = {}
    for boot in sorted(boots, key=lambda item: item.boot):
        block_number = (boot.boot + 1) // 2
        slot = grouped.setdefault(block_number, {})
        if boot.condition in slot:
            raise ValueError(
                f"block {block_number} holds two {boot.condition} boots; a block must contain "
                "one boot per arm"
            )
        slot[boot.condition] = boot
    blocks: list[BlockSummary] = []
    for index in sorted(grouped):
        slot = grouped[index]
        reason: str | None = None
        if set(slot) != set(CONDITIONS):
            missing = sorted(set(CONDITIONS) - set(slot))
            blocks.append(
                BlockSummary(
                    block=index,
                    overlays_on_boot=slot["overlays_on"].boot if "overlays_on" in slot else -1,
                    overlays_off_boot=slot["overlays_off"].boot if "overlays_off" in slot else -1,
                    onset_difference=None,
                    onset_difference_lower=None,
                    onset_difference_upper=None,
                    onset_sign_established=False,
                    burst_difference=None,
                    usable=False,
                    unusable_reason=f"missing_{missing[0]}_boot",
                )
            )
            continue
        on = slot["overlays_on"]
        off = slot["overlays_off"]
        if not (on.usable and off.usable):
            reason = "unusable_boot"
        elif not (_scores_onset(on) and _scores_onset(off)):
            reason = "ambiguous_onset"
        lower, upper = (None, None) if reason else _onset_difference_bounds(on, off)
        # A censoring surrogate may only enter the permutation statistic when the BOUNDS
        # establish its sign. Before #710 every boot shared the same ``launches + 1`` surrogate,
        # which made that automatic: a censored boot's surrogate strictly exceeded any onset
        # observable in the same plan, so a singly-censored block's sign was guaranteed and a
        # doubly-censored block cancelled to zero by construction. Delivered-cycle surrogates are
        # PER BOOT, so both guarantees are gone and each must now be checked (#710 Codex P1,
        # rounds 1 and 2):
        #
        #   * both observed        -> a real observation, always usable.
        #   * one censored         -> usable only if its one-sided bound excludes zero. With a
        #                             24-launch budget, ``on`` observed at 24 against ``off``
        #                             censored after 20 delivered cycles yields 21-24 = -3 while
        #                             the true difference may be zero or positive.
        #   * both censored        -> two unrelated lower bounds; nothing is established.
        #
        # Otherwise the block contributes 0.0 — the honest "carries no signed evidence". Flipping
        # a zero under permutation changes nothing, which is precisely what "no information"
        # means, and ``informative_blocks`` already excludes zeros. The bounds are retained
        # either way, so the direction machinery still sees the real constraint.
        surrogate = None if reason else float(off.onset_value - on.onset_value)
        sign_established = surrogate is not None and (
            (lower is not None and upper is not None)
            or (lower is not None and lower > 0)
            or (upper is not None and upper < 0)
        )
        if surrogate is None:
            onset_difference = None
        elif sign_established:
            onset_difference = surrogate
        else:
            onset_difference = 0.0
        # A block excluded from the primary endpoint is excluded from the secondary too: an
        # unusable or ambiguous-onset boot cannot anchor a trustworthy post-onset window either.
        burst_difference = (
            off.post_onset_burst_rate - on.post_onset_burst_rate
            if reason is None
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
                onset_difference_lower=lower,
                onset_difference_upper=upper,
                onset_sign_established=sign_established,
                burst_difference=burst_difference,
                usable=reason is None,
                unusable_reason=reason,
            )
        )
    return blocks


def _onset_difference_bounds(
    on: BootSummary, off: BootSummary
) -> tuple[float | None, float | None]:
    """Range the TRUE ``off - on`` onset difference can occupy, given right-censoring.

    A censored boot only tells us its onset **exceeds** the cycles it actually delivered, so its
    ``onset_value`` surrogate (``delivered_cycles + 1``) is a lower bound on that arm's onset,
    not an observation. Where exactly one boot in the block is censored the substitution still
    gets the *sign* right (the censored arm is provably the later one), so the direction is safe.
    Where **both** are censored the true difference is unconstrained in either direction, and a
    summed statistic built from those substitutions can point the wrong way.
    """
    on_censored, off_censored = on.onset_censored, off.onset_censored
    # Both arms are already expressed in delivered cycles, so one subtraction serves every case;
    # only which SIDE the result bounds changes (#710 — the surrogate lives in ``onset_value``
    # rather than being re-derived from the raw launch count here).
    difference = float(off.onset_value - on.onset_value)
    if not on_censored and not off_censored:
        return difference, difference
    if off_censored and not on_censored:
        # off's true onset exceeds its surrogate and on's is known: at least this much, and
        # unbounded above.
        return difference, None
    if on_censored and not off_censored:
        return None, difference
    return None, None


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
    expected_blocks: int | None = None,
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
    # Descriptive only: the marginal (unpaired) arm medians. NEVER the direction source — with
    # block-slot baselines they can carry the opposite sign to the blocked statistic the test
    # actually evaluates, which would let the tool report the reverse of its own p-value.
    median_onset_difference = (
        off.median_onset_value - on.median_onset_value
        if on.median_onset_value is not None and off.median_onset_value is not None
        else None
    )
    # The direction MUST come from the same within-block effect the permutation test evaluates.
    blocked_effect = math.fsum(onset_differences) if onset_differences else None
    usable_blocks = len(onset_differences)
    # Only blocks with a NONZERO difference carry information: flipping a zero block's sign
    # leaves the permutation sum unchanged, so it doubles both the extreme count and the
    # reference set and cancels. The attainable floor is therefore 2/2**informative, not
    # 2/2**usable — quoting the latter lets an underpowered run pass the floor check and then
    # report `no_measurable_effect` for a p it could never have driven under alpha, which is the
    # exact false-negative path this redesign exists to prevent.
    informative_blocks = sum(1 for value in onset_differences if abs(value) > 1e-9)
    smallest_attainable = 2 / 2**informative_blocks if informative_blocks else None
    # A zero difference means two different things. Both onsets OBSERVED and equal is a real
    # tie — evidence of no effect in that block. A zero produced because CENSORING left the sign
    # open is not: the true onsets are unconstrained, so such a block is uninformative rather
    # than null. Without this distinction a run where nothing at all was learned would report
    # `no_measurable_effect` with p=1.
    # Scoped by ``onset_sign_established`` rather than by "both bounds are None" since #710: a
    # SINGLY censored block whose one-sided bound fails to exclude zero also contributes an
    # uninformative zero, but it has a real (non-None) lower or upper bound, so the old test
    # would have missed it and an all-sign-ambiguous run would report ``no_measurable_effect``
    # with p=1 — the same false null this guard exists to prevent (#710 Codex P1, round 2).
    censoring_uninformative_blocks = sum(
        1
        for block in blocks
        if block.usable and block.onset_difference == 0 and not block.onset_sign_established
    )
    # Blocks that actually carry an OBSERVATION — a nonzero difference, or a zero that is a real
    # observed tie. A block whose zero came from censoring is not one of these. The endpoint floor
    # is checked against THIS count, not against `usable_blocks`, so that a run cannot satisfy the
    # floor on blocks that learned nothing: 2 observed ties plus 5 censoring-uninformative blocks
    # is not 7 blocks' worth of evidence. Conversely — and this is the bug it replaces — the old
    # `censoring_uninformative_blocks and informative_blocks == 0` veto downgraded an otherwise
    # eligible `no_measurable_effect` the moment a single uninformative block was appended to six
    # fully observed ties, which is exactly backwards (#710 Qodo, round 3).
    observing_blocks = sum(1 for block in blocks if block.usable and block.onset_sign_established)
    # Smallest informative-block count that could reach alpha, so a short run says what it needs
    # instead of just refusing. 2/2**k <= alpha  <=>  k >= log2(2/alpha).
    informative_required = math.ceil(math.log2(2.0 / alpha))
    scoring_boots = [boot for boot in boots if _scores_onset(boot)]
    # A hand-edited or allow_undersized plan can hold enough blocks while each boot ends before
    # the pre-registered graceful onset plus burst window. Blocks alone are not eligibility.
    # Measured in DELIVERED cycles since #710: the floor exists so a boot can cover the
    # pre-registered graceful onset plus the full follow-up window, and both are now counted in
    # cycles. A 20-attempt plan may carry up to 4 undelivered attempts without tripping the
    # exclusion threshold, leaving only 16 cycles — enough report rows, but not enough
    # accumulator to observe an onset at 14 plus a 6-cycle window (#710 Codex P2).
    #
    # Scoped to boots that actually REACH the test. Block eligibility is paired, so a boot whose
    # partner is unusable or ambiguous never contributes an onset difference; letting such a boot
    # force `insufficient_sample` would override a correct result computed from an otherwise
    # eligible population. Before #710 this was mostly theoretical (a short boot required a
    # hand-edited plan); with the floor now counting delivered cycles, ordinary delivery failures
    # reach it, so the scoping has to be explicit (#710 Qodo, round 2).
    tested_boot_numbers = {
        number
        for block in blocks
        if block.usable
        for number in (block.overlays_on_boot, block.overlays_off_boot)
    }
    short_boots = [
        boot
        for boot in scoring_boots
        if boot.boot in tested_boot_numbers and boot.delivered_cycles < MIN_LAUNCHES_PER_BOOT
    ]
    # Censoring bounds: substituting N+1 for a censored onset is a BOUND, not an observation.
    # Where exactly one boot per block is censored the sign still holds; where both are, the
    # true difference is unconstrained, so the summed statistic can point either way. Only claim
    # a direction when the achievable range of the true effect excludes zero.
    usable_blocks_list = [block for block in blocks if block.usable]
    lower_sum = (
        None
        if any(block.onset_difference_lower is None for block in usable_blocks_list)
        else math.fsum(block.onset_difference_lower or 0.0 for block in usable_blocks_list)
    )
    upper_sum = (
        None
        if any(block.onset_difference_upper is None for block in usable_blocks_list)
        else math.fsum(block.onset_difference_upper or 0.0 for block in usable_blocks_list)
    )
    direction_determined = (lower_sum is not None and lower_sum > 0) or (
        upper_sum is not None and upper_sum < 0
    )
    # Exclusion must not depend on the treatment. The block permutation test is exact for the
    # SHARP null (no effect on anything) — under it each boot's outcome, and therefore whether
    # it is excluded, is fixed regardless of labels. But every exclusion here is decided from a
    # POST-TREATMENT outcome (undelivered-launch counts, ambiguous onsets), so if an overlay
    # setting changes those rates the surviving block set is a function of the assignment while
    # the test holds it fixed, and the fixed-set p-value no longer justifies a causal claim.
    #
    # An earlier cut gated on the arm counts being EQUAL. That is not enough, and both reviewers
    # said so: equal marginal counts are consistent with treatment-dependent missingness landing
    # in different blocks. Since the mechanism cannot be modelled from the reports, take the
    # conservative rule — ANY post-treatment exclusion withholds the causal conclusion. The
    # p-value is still reported; it simply stops carrying a claim it cannot support.
    excluded = {
        condition: sum(
            1 for boot in boots if boot.condition == condition and not _scores_onset(boot)
        )
        for condition in CONDITIONS
    }
    # A MISSING report is an exclusion too, and a more worrying one — the reason it is absent is
    # unobservable, so it could easily be outcome- or treatment-dependent. `analyze` only sees
    # loaded boots, so a partially-loaded block would otherwise slip past the gate entirely, and
    # a block with BOTH reports absent would not appear at all. Count incomplete blocks, and let
    # the caller declare how many blocks were planned so a vanished block is still caught.
    incomplete_blocks = sum(
        1
        for block in blocks
        if block.unusable_reason and block.unusable_reason.startswith("missing_")
    )
    missing_blocks = max(0, (expected_blocks or 0) - len(blocks))
    exclusions_present = sum(excluded.values()) > 0 or incomplete_blocks > 0 or missing_blocks > 0
    if (
        usable_blocks < endpoint_floor
        # Blocks that learned nothing cannot fill the floor. This subsumes the old
        # "all zeros came from censoring" veto — an all-uninformative run has zero observing
        # blocks — without vetoing a run whose ties were genuinely observed.
        or observing_blocks < endpoint_floor
        or onset_p is None
        or blocked_effect is None
        or short_boots
    ):
        conclusion = "insufficient_sample"
    elif smallest_attainable is not None and smallest_attainable > alpha:
        # Enough usable blocks, but too few of them carry a nonzero difference for any result
        # to reach alpha. Saying `no_measurable_effect` here would be a false negative.
        conclusion = "insufficient_sample"
    elif exclusions_present:
        # Report the p-value, but do not let it carry a causal claim it cannot support.
        conclusion = "post_treatment_exclusions_present"
    elif onset_p >= alpha:
        conclusion = "no_measurable_effect"
    elif blocked_effect == 0:
        conclusion = "no_measurable_effect"
    elif not direction_determined:
        # The p-value stays valid (the statistic is a function of the observed data, so the
        # randomization null is exact), but censoring leaves the sign of the true effect open.
        conclusion = "effect_direction_indeterminate_under_censoring"
    elif blocked_effect > 0:
        conclusion = "overlays_off_delays_onset"
    else:
        conclusion = "overlays_off_accelerates_onset"
    # Arm-level censored counts describe every scoring boot, but a censored boot whose PARTNER
    # was ambiguous or unusable had its whole block dropped and never reached the test. Label
    # the p-value a BOUND only when censoring actually entered it.
    by_number = {boot.boot: boot for boot in boots}
    censored_in_test = sum(
        1
        for block in blocks
        if block.usable
        for number in (block.overlays_on_boot, block.overlays_off_boot)
        if number in by_number and by_number[number].onset_censored
    )
    censored_total = on.censored_boots + off.censored_boots
    return {
        "schema": ANALYSIS_SCHEMA,
        "issue": 625,
        "design": "randomized block (two boots per block, one per arm)",
        "primary_endpoint": (
            "onset DELIVERED-CYCLE index (first froze/wedged_init launch in the boot, counted "
            "in launch cycles that actually reached AC)"
        ),
        "secondary_endpoint": (
            f"post-onset burst rate over a fixed {POST_ONSET_WINDOW}-delivered-cycle window from "
            "onset, one rate per boot"
        ),
        "alpha": alpha,
        "minimum_boots_per_arm": endpoint_floor,
        "usable_blocks": usable_blocks,
        "informative_blocks": informative_blocks,
        "informative_blocks_required": informative_required,
        "randomization_reference_set": 2**usable_blocks if usable_blocks else None,
        "smallest_attainable_two_sided_p": smallest_attainable,
        "arms": {condition: asdict(summary) for condition, summary in arms.items()},
        "blocks": [asdict(block) for block in blocks],
        # Descriptive marginal figure. The CONCLUSION direction comes from blocked_effect.
        "median_onset_difference_off_minus_on": median_onset_difference,
        "blocked_onset_effect_off_minus_on": blocked_effect,
        "onset_block_permutation_two_sided_p": onset_p,
        "onset_p_is_bound": censored_in_test > 0,
        "censored_boots": censored_total,
        "censored_boots_in_test": censored_in_test,
        "effect_direction_determined": direction_determined,
        "blocked_onset_effect_lower_bound": lower_sum,
        "blocked_onset_effect_upper_bound": upper_sum,
        "ambiguous_onset_boots": on.ambiguous_boots + off.ambiguous_boots,
        # #710 delivery accounting, pooled across arms: how much of the raw attempt count the
        # accumulator actually saw, and how much never reached AC at all.
        "delivered_cycles": sum(boot.delivered_cycles for boot in boots),
        "undelivered_launches": sum(boot.undelivered_launches for boot in boots),
        "undetermined_launches": sum(boot.undetermined_launches for boot in boots),
        "excluded_boots_by_arm": excluded,
        "exclusions_present": exclusions_present,
        "incomplete_blocks": incomplete_blocks,
        "missing_blocks": missing_blocks,
        "censoring_uninformative_blocks": censoring_uninformative_blocks,
        "observing_blocks": observing_blocks,
        "burst_blocks": len(burst_differences),
        "short_boots_below_launch_floor": len(short_boots),
        "minimum_launches_per_boot": MIN_LAUNCHES_PER_BOOT,
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
        "median onset | median boot burst (across-boot range) |",
        "|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for condition in CONDITIONS:
        arm = arms[condition]
        onsets = ", ".join(str(value) for value in arm["observed_onsets"]) or "—"
        spread = (
            f"({arm['burst_rate_min']:.1%}-{arm['burst_rate_max']:.1%})"
            if arm["burst_rate_min"] is not None and arm["burst_rate_max"] is not None
            else "(—)"
        )
        lines.append(
            f"| {condition} | {arm['boots']} | {arm['usable_boots']} | {onsets} | "
            f"{arm['censored_boots']} | {arm['ambiguous_boots']} | "
            f"{_format_optional(arm['median_onset_value'], '.1f')} | "
            f"{_format_optional(arm['median_burst_rate'], '.1%')} {spread} |"
        )
    sensitivity = analysis["sensitivity"]
    lines.extend(
        [
            "",
            f"Usable blocks: {analysis['usable_blocks']} "
            f"({analysis['informative_blocks']} with a nonzero difference; "
            "smallest attainable two-sided p "
            f"{_format_optional(analysis['smallest_attainable_two_sided_p'], '.4g')})"
            + (
                f"  [NEEDS {analysis['informative_blocks_required']} informative blocks to reach "
                f"alpha={analysis['alpha']:g} — tied blocks carry no information]"
                if analysis["informative_blocks"]
                and analysis["informative_blocks"] < analysis["informative_blocks_required"]
                else ""
            ),
            # Onsets are cycle positions, so say how many cycles were actually delivered — a
            # large undelivered count means the raw launch numbering and the accumulator's own
            # count diverged a lot, which is exactly what #710 made visible.
            f"Launch cycles delivered: {analysis['delivered_cycles']} "
            f"({analysis['undelivered_launches']} attempt(s) never reached AC; "
            f"{analysis['undetermined_launches']} of unknown delivery)",
            "PRIMARY — onset, exact block permutation (two-sided): "
            f"p={_format_optional(analysis['onset_block_permutation_two_sided_p'], '.6g')}"
            + (
                f" (BOUND — {analysis['censored_boots_in_test']} censored boot(s) in the test)"
                if analysis["onset_p_is_bound"]
                else ""
            ),
            # The secondary endpoint drops blocks whose burst window did not fit, so it can rest
            # on far fewer blocks than the primary. Say which, right next to the p-value.
            "SECONDARY — post-onset burst, exact block permutation (two-sided): "
            f"p={_format_optional(analysis['burst_block_permutation_two_sided_p'], '.6g')} "
            f"(from {analysis['burst_blocks']} block(s)"
            + (
                f" — FEWER than the {analysis['usable_blocks']} the primary used, because a "
                "block whose burst window did not fit contributes no rate)"
                if analysis["burst_blocks"] != analysis["usable_blocks"]
                else ")"
            ),
            "Sensitivity — sign test (two-sided): "
            f"p={sensitivity['sign_test']['exact_two_sided_p']:.6g}; "
            "rank-sum (assumption-dependent, non-gating): "
            f"p={_format_optional(sensitivity['onset_rank_sum_two_sided_p'], '.6g')}",
            "Blocked onset effect (off - on, the tested statistic): "
            f"{_format_optional(analysis['blocked_onset_effect_off_minus_on'], '+.1f')} cycles"
            + (
                ""
                if analysis["effect_direction_determined"]
                else "  [DIRECTION INDETERMINATE — censoring leaves the true sign open]"
            ),
            "Marginal median onset difference (descriptive, not the direction source): "
            f"{_format_optional(analysis['median_onset_difference_off_minus_on'], '+.1f')}"
            " cycles",
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

    ``list2cmdline`` implements **CRT argv** quoting, which is not the same thing as ``cmd.exe``
    escaping: it leaves ``&``, ``|``, ``^``, ``<``, ``>`` untouched, and ``%VAR%`` expands even
    inside double quotes. Since these lines are pasted straight into ``cmd.exe``, a car/track/
    layout or a checkout path containing one of those characters could split the command. So
    validate first with the transport's existing allowlist — ``remote_launcher`` already solved
    this for the same shell, and a second escaping scheme here would be a competing source of
    truth for one rule.
    """
    try:
        validate_wrapper_token(token)
    except RemoteLaunchError as exc:
        raise ValueError(
            f"refusing to print a pasteable command containing {token!r}: {exc}"
        ) from exc
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
    plan_parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=(
            "omit for a real run — the schedule must be DRAWN for the design-based test to "
            "be exact, and the drawn seed is persisted in the plan. Pass one only to "
            "reproduce a known plan."
        ),
    )
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
            # Render every command BEFORE publishing the plan. The artifact write is exclusive,
            # so a rendering failure after the write (e.g. a `.scratch` directory containing a
            # cmd.exe metacharacter, which `_output_path` accepts but `_shell_quote` rejects)
            # would leave an unusable plan on disk that the retry then refuses to overwrite.
            rendered = [
                (
                    boot,
                    _format_boot_command(
                        car=args.car,
                        track=args.track,
                        layout=args.layout,
                        stability_window=args.stability_window,
                        go_live_timeout=args.go_live_timeout,
                        launches_per_boot=args.launches_per_boot,
                        report_path=_checkout_relative_report_path(destination, boot["report"]),
                    ),
                )
                for boot in plan["boots"]
            ]
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
                "POWER NOTE: only blocks whose two arms differ carry information — a block "
                "where both onsets tie contributes nothing to the test. Every tie effectively "
                f"costs one block, so a run scheduled at exactly {MIN_BOOTS_PER_ARM}/arm "
                "reports insufficient_sample as soon as one block ties. Schedule headroom "
                f"(the default is {DEFAULT_BOOTS_PER_ARM}/arm) rather than re-running."
            )
            print(
                "Paste each command on the Windows rig from that checkout's root "
                "(cd to the rig's ac-copilot-trainer clone first; report paths are "
                "checkout-relative under .scratch — never the planner host's absolute path)."
            )
            for boot, command in rendered:
                block = (boot["boot"] + 1) // 2
                print(
                    f"\n{boot['boot']:03d} (block {block}) {boot['condition']} "
                    "— apply settings, REBOOT, then:"
                )
                print(command)
            return 0
        plan = load_plan(args.plan)
        observations = load_observations(plan, args.reports_dir)
        # Floor is fixed at MIN_BOOTS_PER_ARM so over-scheduling can absorb unusable boots.
        result = analyze(
            observations,
            minimum_boots_per_arm=MIN_BOOTS_PER_ARM,
            expected_blocks=plan["boots_per_arm"],
        )
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
