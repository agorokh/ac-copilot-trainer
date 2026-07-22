"""Plan and analyze the operator-gated init-perturber A/B experiment (#625).

This module never changes Steam or NVIDIA settings.  It gives the operator-owned
experiment a seeded, counterbalanced, interleaved launch schedule and analyzes the
single-trial JSON reports emitted by :mod:`tools.ac_harness.resilient_launch`.

Protocol: obtain explicit operator sign-off, reboot once immediately before the run,
apply both overlay settings shown for each planned trial, execute its printed command,
then restore both settings after the final trial.  ``never_live`` is reported but excluded
from the freeze endpoint, so it cannot masquerade as a successful non-freeze; any such
trial leaves fewer than the required 20 analyzable observations in that arm.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shlex
import subprocess
import sys
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

PLAN_SCHEMA = "init-perturber-ab-plan/v1"
ANALYSIS_SCHEMA = "init-perturber-ab-analysis/v1"
CONDITIONS = ("overlays_on", "overlays_off")
DEFAULT_ALPHA = 0.05
DEFAULT_RANDOMIZATION_SEED = 625
DEFAULT_CAR = "ks_porsche_911_gt3_r_2016"
DEFAULT_TRACK = "spa"
DEFAULT_STABILITY_WINDOW = 140.0
MIN_TRIALS_PER_ARM = 20
_Z_95 = 1.959963984540054


@dataclass(frozen=True)
class PlannedTrial:
    trial: int
    condition: str
    report: str


@dataclass(frozen=True)
class Observation:
    trial: int
    condition: str
    verdict: str
    started_at_utc: str
    elapsed_s: float
    uptime_h: float


@dataclass(frozen=True)
class ArmSummary:
    condition: str
    total: int
    analyzable_total: int
    stable: int
    froze: int
    wedged_init: int
    never_live: int
    freeze_count: int
    freeze_rate: float
    ci95_low: float
    ci95_high: float


def counterbalanced_sequence(
    trials_per_arm: int,
    *,
    randomization_seed: int = DEFAULT_RANDOMIZATION_SEED,
) -> tuple[str, ...]:
    """Return seeded AB/BA pairs so every adjacent pair contains one trial per arm.

    Pair directions are balanced (equal AB and BA counts when ``trials_per_arm`` is even;
    differ by at most one when odd), then shuffled under the persisted seed so neither
    condition is systematically scheduled earlier in the run.
    """
    if trials_per_arm <= 0:
        raise ValueError("trials_per_arm must be > 0")
    ab_pairs = trials_per_arm // 2
    ba_pairs = trials_per_arm - ab_pairs
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
    trials_per_arm: int = MIN_TRIALS_PER_ARM,
    *,
    randomization_seed: int = DEFAULT_RANDOMIZATION_SEED,
    car: str = DEFAULT_CAR,
    track: str = DEFAULT_TRACK,
    layout: str | None = None,
    stability_window: float = DEFAULT_STABILITY_WINDOW,
    go_live_timeout: float = DEFAULT_GO_LIVE_TIMEOUT,
    generated_at_utc: str | None = None,
    allow_undersized: bool = False,
) -> dict[str, Any]:
    """Build a reproducible experiment plan; settings remain operator-owned.

    ``trials_per_arm`` is the scheduled launch count (may exceed the analyzable floor so
    ``never_live`` replacements can still reach :data:`MIN_TRIALS_PER_ARM` analyzable trials).
    """
    if not car.strip() or not track.strip():
        raise ValueError("car and track must not be blank")
    if layout is not None and not layout.strip():
        raise ValueError("layout must not be blank when provided")
    if not math.isfinite(stability_window) or stability_window <= 0:
        raise ValueError("stability_window must be finite and > 0")
    if not math.isfinite(go_live_timeout) or go_live_timeout <= 0:
        raise ValueError("go_live_timeout must be finite and > 0")
    if trials_per_arm < MIN_TRIALS_PER_ARM and not allow_undersized:
        raise ValueError(
            f"trials_per_arm must be >= {MIN_TRIALS_PER_ARM} "
            "(undersized plans cannot satisfy the experiment endpoint)"
        )
    sequence = counterbalanced_sequence(
        trials_per_arm,
        randomization_seed=randomization_seed,
    )
    stamp = generated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    trials = [
        asdict(
            PlannedTrial(
                trial=index,
                condition=condition,
                report=f"trial-{index:03d}-{condition}.json",
            )
        )
        for index, condition in enumerate(sequence, start=1)
    ]
    return {
        "schema": PLAN_SCHEMA,
        "issue": 625,
        "generated_at_utc": stamp,
        "trials_per_arm": trials_per_arm,
        "analyzable_minimum_per_arm": MIN_TRIALS_PER_ARM,
        "randomization_seed": randomization_seed,
        "launch": {
            "car": car,
            "track": track,
            "layout": layout,
            "stability_window": stability_window,
            "go_live_timeout": go_live_timeout,
            "trials_per_invocation": 1,
        },
        "operator_owned_settings": True,
        "protocol": {
            "fresh_reboot_before_run": True,
            "restore_settings_after_run": True,
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
            "never_live_policy": "report separately; exclude from freeze endpoint",
        },
        "freeze_verdicts": sorted(FREEZE_VERDICTS),
        "trials": trials,
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
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"plan schema must be {PLAN_SCHEMA!r}")
    trials_per_arm = plan.get("trials_per_arm")
    if not isinstance(trials_per_arm, int) or trials_per_arm <= 0:
        raise ValueError("plan trials_per_arm must be a positive integer")
    seed = plan.get("randomization_seed")
    if not isinstance(seed, int):
        raise ValueError("plan randomization_seed must be an integer")
    trials = plan.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("plan trials must be a non-empty list")
    expected = list(range(1, len(trials) + 1))
    observed: list[int] = []
    conditions: list[str] = []
    for index, raw in enumerate(trials, start=1):
        trial = _require_mapping(raw, where=f"plan trials[{index - 1}]")
        number = trial.get("trial")
        condition = trial.get("condition")
        report = trial.get("report")
        if not isinstance(number, int):
            raise ValueError(f"plan trial {index} has a non-integer trial number")
        if condition not in CONDITIONS:
            raise ValueError(f"plan trial {index} has invalid condition {condition!r}")
        if not isinstance(report, str) or Path(report).name != report:
            raise ValueError(f"plan trial {index} report must be a plain filename")
        observed.append(number)
        conditions.append(condition)
    if observed != expected:
        raise ValueError("plan trial numbers must be contiguous and ordered from 1")
    if len(conditions) != trials_per_arm * 2:
        raise ValueError("plan must contain exactly two trials per requested arm trial")
    if any(conditions.count(condition) != trials_per_arm for condition in CONDITIONS):
        raise ValueError("plan must contain trials_per_arm observations for each condition")
    expected_sequence = counterbalanced_sequence(trials_per_arm, randomization_seed=seed)
    if tuple(conditions) != expected_sequence:
        raise ValueError("plan trial conditions do not match the persisted randomization_seed")
    ab_first = 0
    ba_first = 0
    for offset in range(0, len(conditions), 2):
        pair = conditions[offset : offset + 2]
        if set(pair) != set(CONDITIONS):
            raise ValueError("plan must interleave one trial from each arm in every adjacent pair")
        if pair[0] == "overlays_on":
            ab_first += 1
        else:
            ba_first += 1
    if trials_per_arm % 2 == 0 and ab_first != ba_first:
        raise ValueError("plan pair directions must be balanced (equal AB and BA counts)")
    if abs(ab_first - ba_first) > 1:
        raise ValueError("plan pair directions must differ by at most one")
    return plan


def _parse_report(path: Path, trial: PlannedTrial, plan_launch: dict[str, Any]) -> Observation:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read report {path}: {exc}") from exc
    report = _require_mapping(payload, where=f"report {path}")
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError(f"report {path} schema must be {REPORT_SCHEMA!r}")
    attempts = report.get("attempts")
    attempts_log = report.get("attempts_log")
    if attempts != 1 or not isinstance(attempts_log, list) or len(attempts_log) != 1:
        raise ValueError(f"report {path} must contain exactly one launch attempt")
    record = _require_mapping(attempts_log[0], where=f"report {path} attempts_log[0]")
    verdict = record.get("verdict")
    started_at_utc = record.get("started_at_utc")
    elapsed_s = record.get("elapsed_s")
    uptime_h = record.get("uptime_h")
    if verdict not in TERMINAL_VERDICTS:
        raise ValueError(f"report {path} has invalid verdict {verdict!r}")
    expected_counts = {name: int(name == verdict) for name in TERMINAL_VERDICTS}
    if report.get("verdict") != verdict or report.get("counts") != expected_counts:
        raise ValueError(f"report {path} summary does not match its attempt verdict")
    if record.get("attempt") != 1:
        raise ValueError(f"report {path} attempt number must be 1")
    launch = report.get("launch")
    if not isinstance(launch, dict):
        raise ValueError(f"report {path} must record launch configuration")
    for key in ("car", "track", "layout", "stability_window", "go_live_timeout"):
        if launch.get(key) != plan_launch.get(key):
            raise ValueError(f"report {path} launch.{key}={launch.get(key)!r} does not match plan")
    if not isinstance(started_at_utc, str):
        raise ValueError(f"report {path} is missing started_at_utc")
    try:
        datetime.strptime(started_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"report {path} has invalid started_at_utc") from exc
    if not isinstance(elapsed_s, (int, float)) or not math.isfinite(elapsed_s) or elapsed_s < 0:
        raise ValueError(f"report {path} has invalid elapsed_s")
    if not isinstance(uptime_h, (int, float)) or not math.isfinite(uptime_h) or uptime_h < 0:
        raise ValueError(f"report {path} must record finite non-negative uptime_h")
    return Observation(
        trial=trial.trial,
        condition=trial.condition,
        verdict=verdict,
        started_at_utc=started_at_utc,
        elapsed_s=float(elapsed_s),
        uptime_h=float(uptime_h),
    )


def load_observations(
    plan: dict[str, Any], reports_dir: Path, *, require_complete: bool = True
) -> tuple[Observation, ...]:
    """Load one immutable report per planned trial and verify actual run order."""
    plan_launch = _require_mapping(plan.get("launch"), where="plan launch")
    observations: list[Observation] = []
    missing: list[str] = []
    for raw in plan["trials"]:
        trial = PlannedTrial(trial=raw["trial"], condition=raw["condition"], report=raw["report"])
        report_path = reports_dir / trial.report
        if not report_path.is_file():
            missing.append(trial.report)
            continue
        observations.append(_parse_report(report_path, trial, plan_launch))
    if require_complete and missing:
        preview = ", ".join(missing[:3])
        suffix = "" if len(missing) <= 3 else f" (+{len(missing) - 3} more)"
        raise ValueError(f"experiment is incomplete; missing {preview}{suffix}")
    stamps = [item.started_at_utc for item in observations]
    if stamps != sorted(stamps):
        raise ValueError("report timestamps must increase in planned trial order")
    uptimes = [item.uptime_h for item in observations]
    if any(later < earlier for earlier, later in zip(uptimes, uptimes[1:], strict=False)):
        raise ValueError(
            "uptime_h must be nondecreasing across the run "
            "(a mid-experiment reboot confounds the freeze endpoint)"
        )
    # Second-resolution stamps may collide on fast never_live failures; require strictly
    # increasing uptime only for the adjacent pairs that share a stamp.
    for earlier_stamp, later_stamp, earlier_up, later_up in zip(
        stamps, stamps[1:], uptimes, uptimes[1:], strict=False
    ):
        if earlier_stamp == later_stamp and later_up <= earlier_up:
            raise ValueError(
                "duplicate adjacent report timestamps require strictly increasing uptime_h"
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
    """Exact two-sided sign test over discordant adjacent A/B pairs."""
    if helped < 0 or harmed < 0:
        raise ValueError("discordant-pair counts must be non-negative")
    discordant = helped + harmed
    if discordant == 0:
        return 1.0
    tail = min(helped, harmed)
    one_sided_mass = Fraction(sum(math.comb(discordant, k) for k in range(tail + 1)), 2**discordant)
    return float(min(Fraction(1, 1), 2 * one_sided_mass))


def _paired_sensitivity(observations: Sequence[Observation]) -> dict[str, object]:
    helped = harmed = concordant = excluded = 0
    ordered = sorted(observations, key=lambda item: item.trial)
    if len(ordered) % 2:
        raise ValueError("paired sensitivity requires an even number of observations")
    for offset in range(0, len(ordered), 2):
        pair = ordered[offset : offset + 2]
        if {item.condition for item in pair} != set(CONDITIONS):
            raise ValueError("each adjacent trial pair must contain one observation per arm")
        by_condition = {item.condition: item for item in pair}
        on = by_condition["overlays_on"].verdict
        off = by_condition["overlays_off"].verdict
        if "never_live" in (on, off):
            excluded += 1
            continue
        on_froze = on in FREEZE_VERDICTS
        off_froze = off in FREEZE_VERDICTS
        if on_froze and not off_froze:
            helped += 1
        elif off_froze and not on_froze:
            harmed += 1
        else:
            concordant += 1
    return {
        "overlays_off_helped_pairs": helped,
        "overlays_off_harmed_pairs": harmed,
        "concordant_pairs": concordant,
        "excluded_never_live_pairs": excluded,
        "exact_two_sided_p": paired_exact_two_sided(helped, harmed),
    }


def _summarize(condition: str, observations: Sequence[Observation]) -> ArmSummary:
    arm = [item for item in observations if item.condition == condition]
    if not arm:
        raise ValueError(f"no observations for {condition}")
    counts = {
        verdict: sum(item.verdict == verdict for item in arm) for verdict in TERMINAL_VERDICTS
    }
    freeze_count = counts["froze"] + counts["wedged_init"]
    analyzable_total = len(arm) - counts["never_live"]
    if analyzable_total <= 0:
        # Plausible primary outcome when one overlay setting systematically prevents launch.
        return ArmSummary(
            condition=condition,
            total=len(arm),
            analyzable_total=0,
            stable=counts["stable"],
            froze=counts["froze"],
            wedged_init=counts["wedged_init"],
            never_live=counts["never_live"],
            freeze_count=freeze_count,
            freeze_rate=0.0,
            ci95_low=0.0,
            ci95_high=1.0,
        )
    low, high = wilson_interval(freeze_count, analyzable_total)
    return ArmSummary(
        condition=condition,
        total=len(arm),
        analyzable_total=analyzable_total,
        stable=counts["stable"],
        froze=counts["froze"],
        wedged_init=counts["wedged_init"],
        never_live=counts["never_live"],
        freeze_count=freeze_count,
        freeze_rate=freeze_count / analyzable_total,
        ci95_low=low,
        ci95_high=high,
    )


def analyze(
    observations: Sequence[Observation],
    *,
    minimum_per_arm: int = MIN_TRIALS_PER_ARM,
    alpha: float = DEFAULT_ALPHA,
) -> dict[str, Any]:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    # Never allow a dry-run / undersized plan to claim the experiment endpoint.
    endpoint_floor = max(MIN_TRIALS_PER_ARM, minimum_per_arm)
    summaries = {condition: _summarize(condition, observations) for condition in CONDITIONS}
    on = summaries["overlays_on"]
    off = summaries["overlays_off"]
    if on.analyzable_total == 0 or off.analyzable_total == 0:
        p_value = 1.0
        risk_difference = 0.0
        conclusion = "insufficient_sample"
    else:
        p_value = fisher_exact_two_sided(
            on.freeze_count, on.analyzable_total, off.freeze_count, off.analyzable_total
        )
        risk_difference = off.freeze_rate - on.freeze_rate
        if min(on.analyzable_total, off.analyzable_total) < endpoint_floor:
            conclusion = "insufficient_sample"
        elif p_value >= alpha:
            conclusion = "no_measurable_effect"
        elif risk_difference < 0:
            conclusion = "overlays_off_lower_freeze_rate"
        elif risk_difference > 0:
            conclusion = "overlays_off_higher_freeze_rate"
        else:
            conclusion = "no_measurable_effect"
    uptimes = [item.uptime_h for item in observations]
    return {
        "schema": ANALYSIS_SCHEMA,
        "issue": 625,
        "primary_endpoint": "froze + wedged_init among stable/freeze-classified attempts",
        "alpha": alpha,
        "minimum_per_arm": endpoint_floor,
        "arms": {condition: asdict(summary) for condition, summary in summaries.items()},
        "risk_difference_off_minus_on": risk_difference,
        "fisher_exact_two_sided_p": p_value,
        "paired_sensitivity": _paired_sensitivity(observations),
        "conclusion": conclusion,
        "uptime_h": {"first": uptimes[0], "last": uptimes[-1]},
        "observations": [asdict(item) for item in observations],
    }


def render_markdown(analysis: dict[str, Any]) -> str:
    arms = analysis["arms"]
    lines = [
        "| condition | attempts | analyzable n | stable | froze | wedged_init | never_live | "
        "freeze rate (95% Wilson CI) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition in CONDITIONS:
        arm = arms[condition]
        lines.append(
            f"| {condition} | {arm['total']} | {arm['analyzable_total']} | "
            f"{arm['stable']} | {arm['froze']} | "
            f"{arm['wedged_init']} | {arm['never_live']} | {arm['freeze_rate']:.1%} "
            f"({arm['ci95_low']:.1%}-{arm['ci95_high']:.1%}) |"
        )
    lines.extend(
        [
            "",
            f"Fisher exact (two-sided): p={analysis['fisher_exact_two_sided_p']:.6g}",
            "Paired exact sensitivity (two-sided): "
            f"p={analysis['paired_sensitivity']['exact_two_sided_p']:.6g}",
            f"Risk difference (off - on): {analysis['risk_difference_off_minus_on']:+.1%}",
            f"Conclusion: `{analysis['conclusion']}`",
            "Uptime window: "
            f"{analysis['uptime_h']['first']:.3f}h-{analysis['uptime_h']['last']:.3f}h",
        ]
    )
    return "\n".join(lines)


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite existing artifact {path}") from exc


def _output_path(raw: Path) -> Path:
    return resolve_report_path(raw, approved_roots=(repo_checkout_root() / ".scratch",))


def _shell_quote(token: str) -> str:
    """Quote one argv token for paste onto the operator's launch host shell."""
    if sys.platform == "win32":
        return subprocess.list2cmdline([token])
    return shlex.quote(token)


def _checkout_relative_report_path(plan_path: Path, report_name: str) -> str:
    """Return a checkout-relative report path so commands stay runnable from the repo root."""
    checkout = repo_checkout_root().resolve(strict=False)
    report_path = (plan_path.parent / report_name).resolve(strict=False)
    try:
        return report_path.relative_to(checkout).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"trial report {report_path} must stay under the checkout (.scratch)"
        ) from exc


def _format_trial_command(
    *,
    car: str,
    track: str,
    layout: str | None,
    stability_window: float,
    go_live_timeout: float,
    report_path: str,
) -> str:
    """Build a pasteable launch line rooted at the checkout (so ``tools`` imports)."""
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
            "1",
            "--json",
            report_path,
        ]
    )
    return " ".join(_shell_quote(part) for part in parts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="write an interleaved A/B launch plan")
    plan_parser.add_argument("--out", required=True, type=Path)
    plan_parser.add_argument(
        "--trials-per-arm",
        type=int,
        default=MIN_TRIALS_PER_ARM,
        help=f"analyzable-floor target per arm (minimum {MIN_TRIALS_PER_ARM})",
    )
    plan_parser.add_argument("--seed", type=int, default=DEFAULT_RANDOMIZATION_SEED)
    plan_parser.add_argument("--car", default=DEFAULT_CAR)
    plan_parser.add_argument("--track", default=DEFAULT_TRACK)
    plan_parser.add_argument("--layout", default=None)
    plan_parser.add_argument("--stability-window", type=float, default=DEFAULT_STABILITY_WINDOW)
    plan_parser.add_argument("--go-live-timeout", type=float, default=DEFAULT_GO_LIVE_TIMEOUT)
    analyze_parser = subparsers.add_parser("analyze", help="analyze completed one-trial reports")
    analyze_parser.add_argument("--plan", required=True, type=Path)
    analyze_parser.add_argument("--reports-dir", required=True, type=Path)
    analyze_parser.add_argument("--json", type=Path, default=None, dest="json_path")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan = build_plan(
                args.trials_per_arm,
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
                "OPERATOR GATE: explicitly approve and apply both Steam overlay and NVIDIA "
                "ShadowPlay settings; reboot once before trial 001 and restore both after the run."
            )
            print(
                f"Endpoint floor is {MIN_TRIALS_PER_ARM} analyzable trials/arm "
                f"(scheduled {args.trials_per_arm}/arm); over-schedule to absorb never_live."
            )
            checkout = repo_checkout_root()
            print(
                "Paste each command on the rig after "
                f"cd {_shell_quote(str(checkout))} "
                "(keeps ``tools`` importable; report paths are checkout-relative under .scratch)."
            )
            print(
                "If two adjacent trials are never_live, cold-restart Content Manager before "
                "continuing — each printed command is a one-attempt process, so the in-process "
                "stale-CM streak cannot accumulate across overlay changes."
            )
            for trial in plan["trials"]:
                report_path = _checkout_relative_report_path(destination, trial["report"])
                print(f"\n{trial['trial']:03d} {trial['condition']}")
                print(
                    _format_trial_command(
                        car=args.car,
                        track=args.track,
                        layout=args.layout,
                        stability_window=args.stability_window,
                        go_live_timeout=args.go_live_timeout,
                        report_path=report_path,
                    )
                )
            return 0
        plan = load_plan(args.plan)
        observations = load_observations(plan, args.reports_dir)
        # Analyzable floor is fixed at MIN_TRIALS_PER_ARM so over-scheduling can absorb never_live.
        result = analyze(observations, minimum_per_arm=MIN_TRIALS_PER_ARM)
        if args.json_path is not None:
            destination = _output_path(args.json_path)
            _write_new_json(destination, result)
            print(f"analysis -> {destination}")
        print(render_markdown(result))
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
