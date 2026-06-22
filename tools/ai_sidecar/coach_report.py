"""Render a pro-engineer coaching debrief from the attribution layer, + a CLI.

Ties :mod:`setup_model`, :mod:`lap_dynamics`, :mod:`corner_attribution`, :mod:`tyre_model`,
:mod:`conditions_model`, and :mod:`track_reference` into a human-readable debrief: the setup at a
glance, the aero-vs-mechanical balance verdict, the tyre-thermal read, the track conditions, a
per-corner "where you lost time and whether it's setup or technique" breakdown, and (when a faster
reference lap is supplied) the apex-speed deficit per corner.

CLI::

    python -m tools.ai_sidecar.coach_report LAP.json [--reference REF.json] [--setup SETUP.ini]
                                            [--grip-ceiling-g 1.5]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.ai_sidecar.conditions_model import (
    ConditionsReport,
    conditions_from_lap_archive,
)
from tools.ai_sidecar.corner_attribution import (
    Attribution,
    BalanceFinding,
    CornerCoaching,
    analyze_balance,
    coach_lap,
    compare_laps,
)
from tools.ai_sidecar.lap_dynamics import (
    LapTrace,
    corner_signatures,
    lap_trace_from_archive,
    segment_corners,
)
from tools.ai_sidecar.setup_model import CarSetup, from_lap_archive, load_setup_file
from tools.ai_sidecar.track_reference import (
    CornerScore,
    add_corpus_lap,
    build_references,
    score_lap,
)
from tools.ai_sidecar.tyre_model import TyreReport, tyres_from_lap_archive


def _conditions_meaningful(report: ConditionsReport | None) -> bool:
    """True when the conditions report carries real data worth surfacing (not all-unknown).

    Temperatures alone count: ``conditions_model`` produces qualitative cold/hot-track coaching from
    ``trackTempC`` / ``ambientTempC`` even with no grip or weather (codex #292). We key on concrete
    inputs, not on ``findings`` — an archive with NO conditions block still yields a "no track-grip
    data" finding, and surfacing a block that only says "no data" would be noise.
    """
    return report is not None and (
        report.regime != "unknown"
        or report.grip_level is not None
        or report.weather is not None
        or report.track_temp_c is not None
        or report.ambient_temp_c is not None
    )


def _corner_reference_scores(
    reference_lap: LapTrace | None, driven_lap: LapTrace
) -> list[CornerScore] | None:
    """Apex-speed deficit per corner vs the supplied (faster) reference lap, or None.

    The reference lap is treated as the **corpus best** — the realistic, demonstrated target. We do
    NOT fabricate a GGV theoretical ceiling from a driven lap (that field stays equal to the corpus
    best, so :func:`track_reference.score_lap` correctly frames deficits as "under the best lap").
    """
    if reference_lap is None:
        return None
    refs = build_references(reference_lap)
    if not refs:
        return None
    add_corpus_lap(refs, reference_lap)  # the reference lap IS the corpus best
    scores = score_lap(refs, driven_lap)
    return scores or None


def format_debrief(
    corners: list[CornerCoaching],
    balance: BalanceFinding | None = None,
    setup: CarSetup | None = None,
    *,
    title: str = "Coaching debrief",
    tyres: TyreReport | None = None,
    conditions: ConditionsReport | None = None,
    corner_reference: list[CornerScore] | None = None,
) -> str:
    """Render the full debrief as text."""
    out: list[str] = [f"=== {title} ==="]
    if setup is not None and setup.tunables():
        out.append("\nSetup at a glance:")
        out.extend("  " + line for line in setup.human_summary())
    if balance is not None:
        out.append("\nBalance (aero vs mechanical):")
        out.append(
            f"  verdict: {balance.verdict}"
            + (f" → {balance.lever_class} levers" if balance.lever_class else "")
        )
        out.append(f"  {balance.coaching}")
        gu = []
        if balance.low_band_grip_used is not None:
            gu.append(f"low-speed grip used {balance.low_band_grip_used:.0%}")
        if balance.high_band_grip_used is not None:
            gu.append(f"high-speed grip used {balance.high_band_grip_used:.0%}")
        if gu:
            out.append("  (" + "; ".join(gu) + ")")
        out.append(f"  caveat: {balance.caveat}")
    if tyres is not None:
        out.append("\nTyres (thermal):")
        out.append("  " + tyres.headline())
        for f in tyres.findings[:3]:
            scope = "" if f.core_only else " [needs richer channels]"
            out.append(f"      - [{f.severity}{scope}] {f.summary} (conf {f.confidence})")
    if _conditions_meaningful(conditions):
        out.append("\nConditions (track/weather):")
        out.append("  " + conditions.headline())
        for f in conditions.findings[:3]:
            tag = " [approx]" if f.approximate else ""
            out.append(f"      - {f.summary}{tag} (conf {f.confidence})")
    lost = [c for c in corners if c.delta_s is not None and c.delta_s > 0.03]
    total_lost = sum(c.delta_s for c in lost if c.delta_s)
    out.append(
        f"\nPer-corner ({len(corners)} corners"
        + (f", {len(lost)} losing time, {total_lost:.2f}s total" if lost else "")
        + "):"
    )
    for c in corners:
        out.append("  " + c.headline)
        for a in c.attributions[:2]:
            kind = (
                "SETUP"
                if a.setup_causes and not a.technique_causes
                else ("TECHNIQUE" if a.technique_causes and not a.setup_causes else "SETUP+TECH")
            )
            flag = " [suspected]" if a.advisory else ""
            out.append(f"      - [{kind}{flag}] {a.symptom} (conf {a.confidence:.0%})")
    if corner_reference:
        behind = [s for s in corner_reference if s.deficit_to_target_kmh >= 2.0]
        out.append(
            f"\nApex speed vs reference lap ({len(corner_reference)} corners"
            + (f", {len(behind)} below target" if behind else "")
            + "):"
        )
        for s in corner_reference:
            out.append("  " + s.headline)
            for fnd in s.findings[:1]:
                out.append(f"      - {fnd}")
    return "\n".join(out)


def _load_archive(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cause_class(attr: Attribution) -> str:
    """Collapse an attribution to a single machine-readable cause class."""
    if attr.key == "grip_limited":
        return "grip"
    has_setup = bool(attr.setup_causes)
    has_tech = bool(attr.technique_causes)
    if has_setup and has_tech:
        return "setup+technique"
    if has_setup:
        return "setup"
    if has_tech:
        return "technique"
    return "unknown"


def _tyres_struct(report: TyreReport | None) -> dict | None:
    """JSON-serializable tyre-thermal block, or None when no per-wheel temp channels exist."""
    if report is None:
        return None
    return {
        "headline": report.headline(),
        "compound": report.compound,
        "window_c": list(report.window),
        "mean_core_c": report.mean_core,
        "spread_c": report.spread,
        "front_minus_rear_c": report.front_minus_rear,
        "left_minus_right_c": report.left_minus_right,
        "status": report.status,
        "warming": report.warming,
        "hot_pressure_est_psi": report.hot_pressure_est,
        "findings": [
            {
                "key": f.key,
                "summary": f.summary,
                "severity": f.severity,
                "core_only": f.core_only,
                "coaching": f.coaching,
                "confidence": f.confidence,
            }
            for f in report.findings
        ],
    }


def _conditions_struct(report: ConditionsReport | None) -> dict | None:
    """JSON-serializable conditions block, or None when nothing meaningful is known."""
    if not _conditions_meaningful(report):
        return None
    return {
        "headline": report.headline(),
        "regime": report.regime,
        "grip_level": report.grip_level,
        "grip_band": report.grip_band,
        "track_temp_c": report.track_temp_c,
        "ambient_temp_c": report.ambient_temp_c,
        "weather": report.weather,
        "grip_level_delta": report.grip_level_delta,
        "slick_model_valid": report.slick_model_valid,
        "findings": [
            {
                "key": f.key,
                "summary": f.summary,
                "coaching": f.coaching,
                "confidence": f.confidence,
                "approximate": f.approximate,
            }
            for f in report.findings
        ],
    }


def _corner_reference_struct(scores: list[CornerScore] | None) -> list[dict] | None:
    """JSON-serializable per-corner apex-speed-vs-reference block, or None.

    Surfaces the realistic target (corpus best = the supplied reference lap) and the driver's
    deficit to it. Deliberately omits an "optimal/GGV ceiling" field: in the debrief the reference
    is a driven lap, not a friction-circle QSS profile, so labeling it a theoretical ceiling would
    over-claim (see track_reference docstring + the #244 frontier diagnostics).
    """
    if not scores:
        return None
    return [
        {
            "index": s.index,
            "apex_spline": round(s.apex_spline, 4),
            "driven_apex_kmh": s.driven_apex_kmh,
            "target_apex_kmh": s.target_apex_kmh,
            "deficit_to_target_kmh": s.deficit_to_target_kmh,
            "source": "reference_lap",
            "headline": s.headline,
            "findings": s.findings,
        }
        for s in scores
    ]


def _analyze(
    lap_archive: dict,
    *,
    reference_archive: dict | None,
    setup: CarSetup | None,
    grip_ceiling_g: float | None,
) -> dict:
    """Run the whole brain once and return the analysis pieces both renderers share.

    Raises ``ValueError`` (from :func:`lap_trace_from_archive`) when the archive has no usable
    trace.
    """
    lap = lap_trace_from_archive(lap_archive)
    setup = setup or from_lap_archive(lap_archive)
    ref = lap_trace_from_archive(reference_archive) if reference_archive else None
    report = coach_lap(lap, setup, reference=ref, grip_ceiling_g=grip_ceiling_g)
    sigs = corner_signatures(lap, segment_corners(lap))
    deltas = compare_laps(lap, ref) if ref is not None else None
    balance = analyze_balance(lap, sigs, deltas=deltas, grip_ceiling_g=grip_ceiling_g)
    tyres = tyres_from_lap_archive(lap_archive)
    conditions = conditions_from_lap_archive(lap_archive, reference_archive=reference_archive)
    corner_reference = _corner_reference_scores(ref, lap)
    return {
        "lap": lap,
        "setup": setup,
        "report": report,
        "balance": balance,
        "tyres": tyres,
        "conditions": conditions,
        "corner_reference": corner_reference,
    }


def build_structured_debrief(
    lap_archive: dict,
    *,
    reference_archive: dict | None = None,
    setup: CarSetup | None = None,
    grip_ceiling_g: float | None = None,
) -> dict | None:
    """Run the coaching brain and return a JSON-serializable structured debrief.

    Returns ``{text, corners[], balance, car_id, track_id, tyres, conditions, corner_reference}`` —
    the same analysis as :func:`build_debrief` plus a machine-readable per-corner breakdown
    (cause_class, confidence, advisory, coaching) and the tyre/conditions/reference blocks, for
    the sidecar / coach-handoff protocol. ``tyres``/``conditions``/``corner_reference`` are
    ``None`` when the archive lacks the data. Returns ``None`` when the archive has no usable trace
    (so callers fall back to the shallow rules debrief).
    """
    try:
        a = _analyze(
            lap_archive,
            reference_archive=reference_archive,
            setup=setup,
            grip_ceiling_g=grip_ceiling_g,
        )
    except ValueError:
        return None
    lap = a["lap"]
    balance = a["balance"]
    text = format_debrief(
        a["report"],
        balance,
        a["setup"],
        title=f"Coaching debrief — {lap.car_id or '?'} @ {lap.track_id or '?'}",
        tyres=a["tyres"],
        conditions=a["conditions"],
        corner_reference=a["corner_reference"],
    )
    corners = [
        {
            "index": c.index,
            "apex_spline": round(c.apex_spline, 4),
            "min_speed_kmh": c.min_speed_kmh,
            "time_loss_s": c.delta_s,
            "headline": c.headline,
            "attributions": [
                {
                    "key": at.key,
                    "symptom": at.symptom,
                    "phase": at.phase,
                    "cause_class": _cause_class(at),
                    "confidence": at.confidence,
                    "advisory": at.advisory,
                    "coaching": at.coaching,
                    "setup_causes": at.setup_causes,
                    "technique_causes": at.technique_causes,
                }
                for at in c.attributions
            ],
        }
        for c in a["report"]
    ]
    return {
        "text": text,
        "car_id": lap.car_id,
        "track_id": lap.track_id,
        "balance": {
            "verdict": balance.verdict,
            "lever_class": balance.lever_class,
            "coaching": balance.coaching,
            "low_band_grip_used": balance.low_band_grip_used,
            "high_band_grip_used": balance.high_band_grip_used,
        },
        "corners": corners,
        "tyres": _tyres_struct(a["tyres"]),
        "conditions": _conditions_struct(a["conditions"]),
        "corner_reference": _corner_reference_struct(a["corner_reference"]),
    }


def build_debrief(
    lap_archive: dict,
    *,
    reference_archive: dict | None = None,
    setup: CarSetup | None = None,
    grip_ceiling_g: float | None = None,
) -> str:
    """End-to-end: archive(s) → debrief text."""
    a = _analyze(
        lap_archive,
        reference_archive=reference_archive,
        setup=setup,
        grip_ceiling_g=grip_ceiling_g,
    )
    lap = a["lap"]
    return format_debrief(
        a["report"],
        a["balance"],
        a["setup"],
        title=f"Coaching debrief — {lap.car_id or '?'} @ {lap.track_id or '?'}",
        tyres=a["tyres"],
        conditions=a["conditions"],
        corner_reference=a["corner_reference"],
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Per-corner setup-vs-technique coaching debrief")
    p.add_argument("lap", help="lap archive JSON to coach")
    p.add_argument("--reference", help="reference lap archive JSON (e.g. a faster lap)")
    p.add_argument("--setup", help="setup .ini to use instead of the lap's snapshot")
    p.add_argument(
        "--grip-ceiling-g",
        type=float,
        default=None,
        help="lateral grip ceiling in g (separates grip-limited from technique)",
    )
    args = p.parse_args(argv)
    setup = load_setup_file(args.setup) if args.setup else None
    ref = _load_archive(args.reference) if args.reference else None
    print(
        build_debrief(
            _load_archive(args.lap),
            reference_archive=ref,
            setup=setup,
            grip_ceiling_g=args.grip_ceiling_g,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
