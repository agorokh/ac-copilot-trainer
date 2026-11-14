"""Stage 0 feasibility analysis for the coaching-effect trial (issue #989).

Input: cue-exposure journals written by :mod:`tools.ai_sidecar.coaching_trial`. Output: how
many ARMED approaches a session yields per lap, how much the targeted-error magnitude varies
from pass to pass, and the smallest cue effect one 90-minute session could detect under
pass-level randomization analysed by randomization inference.

This module estimates no coaching effect. Stage 0 journals carry no randomized assignment
(every approach is ``as_delivered``), so the effect is *simulated* on top of the observed
pass-to-pass variation. Every assumption behind that simulation is written into the report.

    python -m tools.coaching_lake.coaching_effect --journal-dir <dir> --out report.json

Pure stdlib. Deterministic for a given seed.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections.abc import Mapping, Sequence
from itertools import compress
from pathlib import Path
from typing import Any

from tools.ai_sidecar.coaching_trial import assemble_approaches, read_journal

REPORT_SCHEMA = "coaching_effect_feasibility_v1"

# Fixed by issue #989. Do not tune these to a result.
MIN_SESSIONS = 3
PROCEED_MIN_APPROACHES = 40
PROCEED_MAX_EFFECT = 0.25
STOP_ABOVE_EFFECT = 0.50
SESSION_MINUTES = 90.0
UNCUED_LAPS = 10  # 5 before and 5 after the randomized block
POWER = 0.80
ALPHA = 0.05
ASSIGN_P = 0.5
CORNER_TIME_GUARDRAIL_S = 0.05

EFFECT_GRID = tuple(round(0.05 * step, 2) for step in range(0, 21))  # 0.00 .. 1.00


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def load_session(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One journal -> session identity, laps and one record per ARMED approach."""
    headers = [e for e in events if e.get("event") == "session"]
    if len(headers) != 1:
        raise ValueError("journal_must_have_exactly_one_session_header")
    header = headers[0]
    session = header.get("session")
    if not isinstance(session, str) or not session:
        raise ValueError("journal_session_identity_missing")
    if any(e.get("session") != session for e in events):
        raise ValueError("journal_mixes_sessions")
    laps = [e for e in events if e.get("event") == "lap"]
    lap_ids = [e.get("lap_uuid") for e in laps]
    if len(set(lap_ids)) != len(lap_ids):
        raise ValueError("duplicate_lap_identity")
    replayed = [e for e in laps if e.get("replayed") is True]
    durations = [_finite(e.get("lap_ms")) for e in replayed]
    if any(d is None or d <= 0 for d in durations):
        raise ValueError("non_finite_or_non_positive_lap_duration")
    ledger = header.get("ledger") if isinstance(header.get("ledger"), Mapping) else {}
    context = header.get("context") if isinstance(header.get("context"), Mapping) else {}
    return {
        "session": session,
        "combo": context.get("combo"),
        "assess_laps": int(ledger.get("assess_laps") or 0),
        "laps_replayed": len(replayed),
        "laps_skipped": len(laps) - len(replayed),
        "lap_ms": durations,
        "approaches": assemble_approaches(events),
    }


def is_usable(approach: Mapping[str, Any]) -> bool:
    """An approach stage 1 could randomize and score: the ledger committed a cue for it and the
    pass that followed has a measured, finite targeted-error magnitude.
    """
    outcome = approach.get("outcome")
    return (
        approach.get("committed") is True
        and isinstance(outcome, Mapping)
        and outcome.get("pass_measured") is True
        and _finite(outcome.get("targeted_error")) is not None
    )


def armed_rates(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    for s in sessions:
        coached = max(0, s["laps_replayed"] - s["assess_laps"])
        armed = len(s["approaches"])
        usable = sum(1 for a in s["approaches"] if is_usable(a))
        rows.append(
            {
                "session": s["session"],
                "combo": s["combo"],
                "laps_replayed": s["laps_replayed"],
                "laps_skipped": s["laps_skipped"],
                "coached_laps": coached,
                "mean_lap_s": statistics.fmean(s["lap_ms"]) / 1000.0 if s["lap_ms"] else None,
                "armed_approaches": armed,
                "committed": sum(1 for a in s["approaches"] if a["committed"]),
                "emitted": sum(1 for a in s["approaches"] if a["emitted"]),
                "usable_approaches": usable,
                "no_outcome": sum(1 for a in s["approaches"] if a["outcome"] is None),
                "armed_per_lap": armed / s["laps_replayed"] if s["laps_replayed"] else None,
                "armed_per_coached_lap": armed / coached if coached else None,
                "usable_per_coached_lap": usable / coached if coached else None,
            }
        )
    laps = sum(r["laps_replayed"] for r in rows)
    coached = sum(r["coached_laps"] for r in rows)
    armed = sum(r["armed_approaches"] for r in rows)
    usable = sum(r["usable_approaches"] for r in rows)
    lap_ms = [ms for s in sessions for ms in s["lap_ms"]]
    return {
        "sessions": rows,
        "pooled": {
            "laps_replayed": laps,
            "coached_laps": coached,
            "armed_approaches": armed,
            "usable_approaches": usable,
            "armed_per_lap": armed / laps if laps else None,
            "armed_per_coached_lap": armed / coached if coached else None,
            "usable_per_coached_lap": usable / coached if coached else None,
            "mean_lap_s": statistics.fmean(lap_ms) / 1000.0 if lap_ms else None,
        },
    }


def project_session(
    rates: Mapping[str, Any], *, minutes: float = SESSION_MINUTES, track_time_fraction: float = 1.0
) -> dict[str, Any]:
    """Usable randomized approaches expected in one session of ``minutes``."""
    pooled = rates["pooled"]
    lap_s, rate = pooled["mean_lap_s"], pooled["usable_per_coached_lap"]
    if not lap_s or rate is None:
        return {"laps": 0, "randomized_laps": 0, "usable_approaches": 0.0}
    laps = math.floor(minutes * 60.0 * track_time_fraction / lap_s)
    randomized = max(0, laps - UNCUED_LAPS)
    return {
        "laps": laps,
        "randomized_laps": randomized,
        "usable_approaches": randomized * rate,
        "track_time_fraction": track_time_fraction,
    }


def _strata(sessions: Sequence[Mapping[str, Any]]) -> dict[tuple[str, int, str], list[dict]]:
    strata: dict[tuple[str, int, str], list[dict]] = {}
    for s in sessions:
        for a in s["approaches"]:
            if is_usable(a):
                strata.setdefault((s["session"], a["corner"], a["root"]), []).append(a)
    return strata


def variance_by_root(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pass-to-pass variation of targeted-error magnitude, per root.

    ``sd_within`` pools deviations from each (session, corner, root) mean, which is the noise a
    within-session comparison of passes through the same corner actually faces.
    """
    by_root: dict[str, dict[str, Any]] = {}
    for (_, _, root), rows in _strata(sessions).items():
        values = [float(a["outcome"]["targeted_error"]) for a in rows]
        times = [t for a in rows if (t := _finite(a["outcome"].get("corner_time_s"))) is not None]
        entry = by_root.setdefault(
            root,
            {"values": [], "ss": 0.0, "df": 0, "t_ss": 0.0, "t_df": 0, "strata": 0, "unit": None},
        )
        entry["values"].extend(values)
        entry["strata"] += 1
        entry["unit"] = rows[0]["outcome"].get("targeted_error_unit")
        if len(values) >= 2:
            mean = statistics.fmean(values)
            entry["ss"] += sum((v - mean) ** 2 for v in values)
            entry["df"] += len(values) - 1
        if len(times) >= 2:
            t_mean = statistics.fmean(times)
            entry["t_ss"] += sum((t - t_mean) ** 2 for t in times)
            entry["t_df"] += len(times) - 1
    out: dict[str, Any] = {}
    for root, entry in sorted(by_root.items()):
        values = entry["values"]
        mean = statistics.fmean(values)
        sd_within = math.sqrt(entry["ss"] / entry["df"]) if entry["df"] else None
        out[root] = {
            "unit": entry["unit"],
            "n": len(values),
            "strata": entry["strata"],
            "mean": mean,
            "sd": statistics.stdev(values) if len(values) >= 2 else None,
            "variance": statistics.variance(values) if len(values) >= 2 else None,
            "sd_within": sd_within,
            "variance_within": sd_within**2 if sd_within is not None else None,
            "cv_within": sd_within / mean if sd_within is not None and mean > 0 else None,
            "share_zero": sum(1 for v in values if v == 0.0) / len(values),
            "corner_time_sd_within_s": (
                math.sqrt(entry["t_ss"] / entry["t_df"]) if entry["t_df"] else None
            ),
        }
    return out


def relative_error_pool(sessions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Targeted-error magnitudes rescaled so each (session, corner, root) stratum has mean 1.

    Roots have different units; relative magnitude is what a "percent lower error" effect acts
    on. A stratum with one pass or a zero mean has no scale and is excluded, and counted.
    """
    pool: list[float] = []
    excluded = 0
    for rows in _strata(sessions).values():
        values = [float(a["outcome"]["targeted_error"]) for a in rows]
        mean = statistics.fmean(values)
        if len(values) < 2 or mean <= 0.0:
            excluded += len(values)
            continue
        pool.extend(v / mean for v in values)
    return {"values": pool, "excluded_passes": excluded}


def _relative_reduction(total: float, n: int, cued_sum: float, cued_n: int) -> float:
    """1 - mean(cued)/mean(withheld). An undefined statistic counts against rejection."""
    withheld_n, withheld_sum = n - cued_n, total - cued_sum
    if cued_n == 0 or withheld_n == 0 or withheld_sum <= 0.0:
        return math.inf
    return 1.0 - (cued_sum / cued_n) / (withheld_sum / withheld_n)


def simulate_power(
    pool: Sequence[float], n: int, effect: float, *, sims: int, perms: int, seed: int
) -> float:
    """Share of simulated sessions in which a one-sided randomization test rejects at ALPHA.

    Each simulated session draws ``n`` passes from ``pool`` with replacement, assigns each to
    speak or withhold with probability 0.5, multiplies cued magnitudes by ``1 - effect``, then
    tests ``1 - mean(cued)/mean(withheld)`` against its re-randomization distribution. The seed
    does not depend on ``effect``, so the same sessions are compared across effect sizes.
    """
    if n < 2 or not pool:
        return 0.0
    rng = random.Random(seed)
    bits = (0, 1)
    rejections = 0
    for _ in range(sims):
        baseline = rng.choices(pool, k=n)
        assign = rng.choices(bits, k=n)
        outcome = [v * (1.0 - effect) if a else v for v, a in zip(baseline, assign, strict=True)]
        total = math.fsum(outcome)
        cued_n = sum(assign)
        if cued_n in (0, n):
            continue  # no comparison possible: counted as a non-rejection
        observed = _relative_reduction(total, n, math.fsum(compress(outcome, assign)), cued_n)
        if not math.isfinite(observed):
            continue
        at_least = 1
        for _ in range(perms):
            draw = rng.choices(bits, k=n)
            stat = _relative_reduction(total, n, math.fsum(compress(outcome, draw)), sum(draw))
            if stat >= observed:
                at_least += 1
        if at_least / (perms + 1) <= ALPHA:
            rejections += 1
    return rejections / sims


def minimum_detectable_effect(
    pool: Sequence[float], n: int, *, sims: int, perms: int, seed: int
) -> dict[str, Any]:
    """Smallest proportional reduction detected with at least POWER, on EFFECT_GRID.

    ``effect`` is ``None`` when even a 100% reduction is not detected at POWER.
    """
    curve = [
        {"effect": e, "power": simulate_power(pool, n, e, sims=sims, perms=perms, seed=seed)}
        for e in EFFECT_GRID
    ]
    effect: float | None = None
    for index, point in enumerate(curve):
        if point["effect"] > 0.0 and point["power"] >= POWER:
            low = curve[index - 1]
            if low["power"] >= POWER or point["power"] == low["power"]:
                effect = point["effect"]
            else:  # linear interpolation between the bracketing grid points
                share = (POWER - low["power"]) / (point["power"] - low["power"])
                effect = low["effect"] + share * (point["effect"] - low["effect"])
            break
    return {
        "n": n,
        "effect": effect,
        "power_curve": curve,
        "false_positive_rate": curve[0]["power"],
        "power_standard_error_at_target": math.sqrt(POWER * (1 - POWER) / sims),
        "sims": sims,
        "perms": perms,
        "seed": seed,
    }


def decide(*, sessions: int, projected_approaches: float, effect: float | None) -> dict[str, str]:
    """Apply the fixed thresholds of issue #989."""
    if sessions < MIN_SESSIONS:
        return {
            "verdict": "blocked",
            "reason": f"{sessions} replayed session(s); stage 0 requires at least {MIN_SESSIONS}",
        }
    if effect is None:
        return {
            "verdict": "stop",
            "reason": "no effect up to a 100% reduction is detectable at 80% power",
        }
    if effect > STOP_ABOVE_EFFECT:
        return {
            "verdict": "stop",
            "reason": f"detectable effect {effect:.0%} exceeds {STOP_ABOVE_EFFECT:.0%}",
        }
    if projected_approaches >= PROCEED_MIN_APPROACHES and effect <= PROCEED_MAX_EFFECT:
        return {
            "verdict": "proceed",
            "reason": (
                f"{projected_approaches:.0f} projected approaches (>= {PROCEED_MIN_APPROACHES}) "
                f"and detectable effect {effect:.0%} (<= {PROCEED_MAX_EFFECT:.0%})"
            ),
        }
    return {
        "verdict": "inconclusive",
        "reason": (
            f"{projected_approaches:.0f} projected approaches (proceed needs "
            f">= {PROCEED_MIN_APPROACHES}) and detectable effect {effect:.0%} (proceed needs "
            f"<= {PROCEED_MAX_EFFECT:.0%}, stop needs > {STOP_ABOVE_EFFECT:.0%})"
        ),
    }


def feasibility_report(
    journals: Sequence[Sequence[Mapping[str, Any]]],
    *,
    sims: int = 400,
    perms: int = 399,
    seed: int = 989,
) -> dict[str, Any]:
    sessions = [load_session(events) for events in journals]
    names = [s["session"] for s in sessions]
    if len(set(names)) != len(names):
        raise ValueError("duplicate_session_identity")
    rates = armed_rates(sessions)
    projection = project_session(rates)
    pool = relative_error_pool(sessions)
    n = math.floor(projection["usable_approaches"])
    detectable = minimum_detectable_effect(pool["values"], n, sims=sims, perms=perms, seed=seed)
    at_minimum = minimum_detectable_effect(
        pool["values"], PROCEED_MIN_APPROACHES, sims=sims, perms=perms, seed=seed
    )
    variance = variance_by_root(sessions)
    time_sds = [
        (v["corner_time_sd_within_s"], v["n"])
        for v in variance.values()
        if v["corner_time_sd_within_s"] is not None
    ]
    time_sd = (
        math.sqrt(sum(sd**2 * k for sd, k in time_sds) / sum(k for _, k in time_sds))
        if time_sds
        else None
    )
    combos = sorted({json.dumps(s["combo"]) for s in sessions})
    return {
        "schema": REPORT_SCHEMA,
        "sessions_replayed": len(sessions),
        "combos": [json.loads(c) for c in combos],
        "armed_approaches": rates,
        "projection_90_min": projection,
        "projection_90_min_at_75pct_track_time": project_session(rates, track_time_fraction=0.75),
        "targeted_error_by_root": variance,
        "relative_error_pool": {
            "n": len(pool["values"]),
            "excluded_passes": pool["excluded_passes"],
            "cv": (
                statistics.stdev(pool["values"]) / statistics.fmean(pool["values"])
                if len(pool["values"]) >= 2
                else None
            ),
        },
        "minimum_detectable_effect": detectable,
        "minimum_detectable_effect_at_40": at_minimum,
        "corner_time_guardrail": {
            "sd_within_s": time_sd,
            "difference_standard_error_s": (
                time_sd * math.sqrt(4.0 / n) if time_sd is not None and n > 0 else None
            ),
            "guardrail_s": CORNER_TIME_GUARDRAIL_S,
        },
        "decision": decide(
            sessions=len(sessions),
            projected_approaches=projection["usable_approaches"],
            effect=detectable["effect"],
        ),
        "thresholds": {
            "min_sessions": MIN_SESSIONS,
            "proceed_min_approaches": PROCEED_MIN_APPROACHES,
            "proceed_max_effect": PROCEED_MAX_EFFECT,
            "stop_above_effect": STOP_ABOVE_EFFECT,
            "power": POWER,
            "alpha_one_sided": ALPHA,
        },
        "assumptions": ASSUMPTIONS,
    }


ASSUMPTIONS = [
    "No effect is estimated. Journals are 'as delivered': every committed approach was cued, "
    "so the effect is simulated on top of observed variation.",
    "Unit of randomization is one usable ARMED approach: the ledger committed a cue and the "
    "following pass has a measured targeted-error magnitude. Assignment is independent "
    "speak/withhold at p = 0.5.",
    "The observed pass-to-pass distribution of targeted error, which comes from cued passes, "
    "stands in for the withheld distribution.",
    "Magnitudes are rescaled to mean 1 within each (session, corner, root); single-pass and "
    "zero-mean strata are excluded. A simulated session resamples the pooled relative "
    "magnitudes with replacement, so passes are treated as exchangeable: no trend, learning, "
    "tyre or fuel drift, and no dependence between passes on one lap.",
    "The simulated effect is a constant proportional reduction applied to every cued pass. "
    "Detectable effect is expressed as a share of the withheld (baseline) mean error.",
    "No carryover: a cue changes only the pass it precedes. If a share c of the effect leaks "
    "into later withheld passes, the detectable effect grows by about 1 / (1 - c).",
    "Test: one-sided randomization test of 1 - mean(cued)/mean(withheld) at alpha 0.05, "
    "re-drawing assignments by the same mechanism; power target 0.80.",
    "Projection: 90 minutes of continuous lapping at the replayed sessions' mean lap time, "
    "minus 10 uncued laps, times the pooled usable approaches per coached lap. Pit time, "
    "out-laps and invalid laps would reduce it; the 75% track-time line shows the sensitivity.",
    "The ARMED rate is the as-delivered rate. Under withholding the ledger leaves a withheld "
    "corner ARMED and spends no lap budget, so the rate in a randomized session may differ.",
    "Replayed laps are analysis-eligible archives, not attested human laps (#988 has not "
    "passed). The result is about feasibility only.",
]


def render_markdown(report: Mapping[str, Any]) -> str:
    pooled = report["armed_approaches"]["pooled"]
    projection = report["projection_90_min"]
    mde = report["minimum_detectable_effect"]
    decision = report["decision"]

    def num(value: Any, spec: str = ".2f") -> str:
        return "n/a" if value is None else format(value, spec)

    lines = [
        f"**Verdict: {decision['verdict'].upper()}** ({decision['reason']})",
        "",
        f"- Sessions replayed: {report['sessions_replayed']}; combos: {report['combos']}",
        f"- Laps replayed: {pooled['laps_replayed']} ({pooled['coached_laps']} after assess laps)",
        f"- ARMED approaches: {pooled['armed_approaches']} "
        f"({num(pooled['armed_per_lap'])} per lap, "
        f"{num(pooled['armed_per_coached_lap'])} per coached lap); "
        f"usable: {pooled['usable_approaches']} "
        f"({num(pooled['usable_per_coached_lap'])} per coached lap)",
        f"- 90-minute projection: {projection['laps']} laps, "
        f"{projection['randomized_laps']} randomized, "
        f"{num(projection['usable_approaches'], '.1f')} usable approaches "
        f"({num(report['projection_90_min_at_75pct_track_time']['usable_approaches'], '.1f')} "
        "at 75% track time)",
        f"- Minimum detectable effect at n = {mde['n']}: "
        f"{'not reached at 100%' if mde['effect'] is None else format(mde['effect'], '.0%')} "
        f"of baseline error (80% power, one-sided alpha 0.05; "
        f"false-positive rate {num(mde['false_positive_rate'])}; "
        f"{mde['sims']} sims x {mde['perms']} re-randomizations, seed {mde['seed']})",
        "- At n = 40: "
        + (
            "not reached at 100%"
            if report["minimum_detectable_effect_at_40"]["effect"] is None
            else format(report["minimum_detectable_effect_at_40"]["effect"], ".0%")
        ),
        "",
        "| Root | Unit | n | Mean | SD | SD within corner | CV within | Share zero |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for root, row in report["targeted_error_by_root"].items():
        lines.append(
            f"| {root} | {row['unit']} | {row['n']} | {num(row['mean'], '.4g')} | "
            f"{num(row['sd'], '.4g')} | {num(row['sd_within'], '.4g')} | "
            f"{num(row['cv_within'])} | {num(row['share_zero'])} |"
        )
    lines += ["", "Power curve (effect: power): "]
    lines.append(", ".join(f"{p['effect']:.0%}: {p['power']:.2f}" for p in mde["power_curve"][::2]))
    lines += ["", "Assumptions:"] + [f"- {text}" for text in report["assumptions"]]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="new JSON report file")
    parser.add_argument("--markdown", type=Path, help="new Markdown summary file")
    parser.add_argument("--sims", type=int, default=400)
    parser.add_argument("--perms", type=int, default=399)
    parser.add_argument("--seed", type=int, default=989)
    args = parser.parse_args(argv)
    paths = sorted(args.journal_dir.glob("*.trial.jsonl"))
    report = feasibility_report(
        [read_journal(path) for path in paths], sims=args.sims, perms=args.perms, seed=args.seed
    )
    report["journals"] = [path.name for path in paths]
    with args.out.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    summary = render_markdown(report)
    if args.markdown is not None:
        with args.markdown.open("x", encoding="utf-8") as handle:
            handle.write(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
