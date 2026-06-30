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
import hashlib
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
    _match_reference_corners,
    analyze_balance,
    coach_lap,
)
from tools.ai_sidecar.lap_dynamics import (
    LapTrace,
    corner_signatures,
    lap_trace_from_archive,
    segment_corners,
)
from tools.ai_sidecar.sector_benchmark import (
    SectorDeltaReport,
    SuperLap,
    build_sector_delta_report,
    build_superlap,
)
from tools.ai_sidecar.setup_model import CarSetup, from_lap_archive, load_setup_file
from tools.ai_sidecar.track_reference import (
    CornerScore,
    add_corpus_lap,
    build_references,
    score_lap,
)
from tools.ai_sidecar.trail_brake import TrailBrakeFinding, analyze_trail_braking
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

    Corners where the reference is actually SLOWER than the driven lap (negative deficit) are
    dropped: a stale/slower reference must not be published as a pace target the driver has already
    beaten (codex #291). If the reference is slower everywhere, the block is omitted entirely.
    """
    if reference_lap is None:
        return None
    refs = build_references(reference_lap)
    if not refs:
        return None
    add_corpus_lap(refs, reference_lap)  # the reference lap IS the corpus best
    scores = [s for s in score_lap(refs, driven_lap) if s.deficit_to_target_kmh >= 0]
    return scores or None


def _archive_lap_is_valid(archive: dict | None) -> bool:
    lap = archive.get("lap") if isinstance(archive, dict) else None
    return not (isinstance(lap, dict) and lap.get("is_valid") is False)


def _archive_track_layout(archive: dict | None) -> str | None:
    track = archive.get("track") if isinstance(archive, dict) else None
    layout = track.get("layout") if isinstance(track, dict) else None
    if layout is None or layout == "":
        return None
    return str(layout)


def _same_archive_layout(candidate: dict | None, anchor: dict | None) -> bool:
    candidate_layout = _archive_track_layout(candidate)
    anchor_layout = _archive_track_layout(anchor)
    if candidate_layout is None and anchor_layout is None:
        return True
    return candidate_layout == anchor_layout


def _same_optional_identity(candidate: str | None, anchor: str | None, *, required: bool) -> bool:
    if candidate is None or anchor is None:
        return False if required else candidate is None and anchor is None
    return candidate == anchor


def _same_archive_scope(
    candidate_lap: LapTrace,
    anchor_lap: LapTrace,
    candidate_archive: dict | None,
    anchor_archive: dict | None,
    *,
    require_identity: bool,
) -> bool:
    if not _same_optional_identity(
        candidate_lap.car_id, anchor_lap.car_id, required=require_identity
    ):
        return False
    if not _same_optional_identity(
        candidate_lap.track_id, anchor_lap.track_id, required=require_identity
    ):
        return False
    return _same_archive_layout(candidate_archive, anchor_archive)


def _archive_content_key(archive: dict | None) -> str:
    identity = {
        key: archive.get(key)
        for key in ("car", "track", "lap", "trace")
        if isinstance(archive, dict)
    }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_debrief(
    corners: list[CornerCoaching],
    balance: BalanceFinding | None = None,
    setup: CarSetup | None = None,
    *,
    title: str = "Coaching debrief",
    tyres: TyreReport | None = None,
    conditions: ConditionsReport | None = None,
    corner_reference: list[CornerScore] | None = None,
    trail_braking: list[TrailBrakeFinding] | None = None,
    sector_deltas: SectorDeltaReport | None = None,
    superlap: SuperLap | None = None,
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
    if sector_deltas and sector_deltas.sectors:
        total = sector_deltas.total_delta_s
        out.append(f"\nSector deltas vs reference (total {_signed_seconds(total)}):")
        for seg in sector_deltas.sectors:
            out.append(f"  {seg.label}: {_signed_seconds(seg.delta_s)}")
        losses = sorted(
            (s for s in sector_deltas.micro_sectors if s.delta_s > 0.03),
            key=lambda s: s.delta_s,
            reverse=True,
        )
        if losses:
            out.append("  Biggest micro-sector losses:")
            for seg in losses[:3]:
                out.append(f"      - {seg.label}: {_signed_seconds(seg.delta_s)}")
    if superlap and superlap.segments:
        gain = (
            "unknown gain"
            if superlap.gain_vs_best_s is None
            else f"{max(0.0, superlap.gain_vs_best_s):.2f}s available"
        )
        out.append(
            f"\nSuperLap target: {superlap.lap_time_s:.2f}s ({gain}), stitched from "
            f"{len(superlap.segments)} micro-sectors across {superlap.source_count} source lap(s)."
        )
    flagged = [f for f in (trail_braking or []) if f.classification != "good_trail_brake"]
    if flagged:
        out.append(f"\nTrail braking ({len(flagged)} corner(s) to work on):")
        for f in flagged:
            out.append(f"  T{f.corner + 1} ({f.classification}): {f.coaching}")
    return "\n".join(out)


def _signed_seconds(value: float) -> str:
    return f"{value:+.2f}s"


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


def _trail_braking_struct(findings: list[TrailBrakeFinding] | None) -> list[dict] | None:
    """JSON-serializable per-corner trail-braking block, or None when no corner braked.

    Inferred from brake+steer overlap + decel (no direct load-transfer measurement) — a technique
    read, not a proof of tyre state; the analyzer's docstring carries that caveat.
    """
    if not findings:
        return None
    return [
        {
            "corner": f.corner,
            "apex_spline": round(f.apex_spline, 4),
            "classification": f.classification,
            "trail_overlap": f.trail_overlap,
            "brake_off_rel": f.brake_off_rel,
            "release_abruptness": f.release_abruptness,
            "coaching": f.coaching,
        }
        for f in findings
    ]


def _sector_delta_struct(report: SectorDeltaReport | None) -> dict | None:
    if report is None:
        return None

    def segment(seg) -> dict:
        return {
            "key": seg.key,
            "label": seg.label,
            "spline_start": round(seg.spline_start, 6),
            "spline_end": round(seg.spline_end, 6),
            "candidate_s": round(seg.candidate_s, 4),
            "reference_s": round(seg.reference_s, 4),
            "delta_s": round(seg.delta_s, 4),
            "sector_index": seg.sector_index,
            "micro_index": seg.micro_index,
        }

    return {
        "total_delta_s": round(report.total_delta_s, 4),
        "car_id": report.car_id,
        "track_id": report.track_id,
        "sectors": [segment(s) for s in report.sectors],
        "micro_sectors": [segment(s) for s in report.micro_sectors],
    }


def _superlap_struct(superlap: SuperLap | None) -> dict | None:
    if superlap is None:
        return None
    return {
        "lap_time_s": round(superlap.lap_time_s, 4),
        "baseline_best_lap_s": (
            None if superlap.baseline_best_lap_s is None else round(superlap.baseline_best_lap_s, 4)
        ),
        "gain_vs_best_s": (
            None if superlap.gain_vs_best_s is None else round(superlap.gain_vs_best_s, 4)
        ),
        "source_count": superlap.source_count,
        "segments": [
            {
                "key": seg.key,
                "label": seg.label,
                "spline_start": round(seg.spline_start, 6),
                "spline_end": round(seg.spline_end, 6),
                "duration_s": round(seg.duration_s, 4),
                "source_index": seg.source_index,
                "source_lap_s": (None if seg.source_lap_s is None else round(seg.source_lap_s, 4)),
                "car_id": seg.car_id,
                "track_id": seg.track_id,
            }
            for seg in superlap.segments
        ],
    }


def _analyze(
    lap_archive: dict,
    *,
    reference_archive: dict | None,
    history_archives: list[dict] | None = None,
    corpus_archives: list[dict] | None = None,
    setup: CarSetup | None,
    grip_ceiling_g: float | None,
) -> dict:
    """Run the whole brain once and return the analysis pieces both renderers share.

    Raises ``ValueError`` (from :func:`lap_trace_from_archive`) when the archive has no usable
    trace.
    """
    lap = lap_trace_from_archive(lap_archive)
    setup = setup or from_lap_archive(lap_archive)
    raw_ref = lap_trace_from_archive(reference_archive) if reference_archive else None
    ref = (
        raw_ref
        if raw_ref is not None
        and _archive_lap_is_valid(reference_archive)
        and _same_archive_scope(
            raw_ref,
            lap,
            reference_archive,
            lap_archive,
            require_identity=False,
        )
        else None
    )
    current_archive_key = _archive_content_key(lap_archive)
    seen_history_keys = {current_archive_key}
    history_laps: list[LapTrace] = []
    for history_archive in history_archives or []:
        if not _archive_lap_is_valid(history_archive):
            continue
        history_key = _archive_content_key(history_archive)
        if history_key in seen_history_keys:
            continue
        seen_history_keys.add(history_key)
        try:
            history_lap = lap_trace_from_archive(history_archive)
        except ValueError:
            continue
        if _same_archive_scope(
            history_lap,
            lap,
            history_archive,
            lap_archive,
            require_identity=True,
        ):
            history_laps.append(history_lap)
    corners = segment_corners(lap)
    sigs = corner_signatures(lap, corners)
    reference_matches = _match_reference_corners(lap, ref, anchors=sigs) if ref is not None else {}
    report = coach_lap(
        lap,
        setup,
        reference=ref,
        history=history_laps,
        grip_ceiling_g=grip_ceiling_g,
        corners=corners,
        signatures=sigs,
        reference_matches=reference_matches,
    )
    deltas = [delta for _ref_sig, delta in reference_matches.values()] if ref is not None else None
    balance = analyze_balance(lap, sigs, deltas=deltas, grip_ceiling_g=grip_ceiling_g)
    tyres = tyres_from_lap_archive(lap_archive)
    conditions = conditions_from_lap_archive(lap_archive, reference_archive=reference_archive)
    # The tyre block is the slick compound-window thermal model; it is meaningless in the wet. When
    # conditions say the slick model is invalid (wet regime), suppress it rather than publish a
    # contradictory "cold slick — build heat" cue alongside wet-regime coaching (codex #291).
    if tyres is not None and not conditions.slick_model_valid:
        tyres = None
    corner_reference = _corner_reference_scores(ref, lap)
    # trail-braking technique read, per corner (only corners that actually braked surface a finding)
    trail_braking = [f for f in analyze_trail_braking(lap) if f.classification != "no_braking"]
    sector_deltas = build_sector_delta_report(lap, ref) if ref is not None else None
    corpus_laps: list[LapTrace] = []
    if ref is not None:
        corpus_laps.append(ref)
    if (ref is not None or corpus_archives) and _archive_lap_is_valid(lap_archive):
        corpus_laps.append(lap)
    for archive in corpus_archives or []:
        if not _archive_lap_is_valid(archive):
            continue
        try:
            corpus_lap = lap_trace_from_archive(archive)
        except ValueError:
            continue
        if _same_archive_scope(corpus_lap, lap, archive, lap_archive, require_identity=True):
            corpus_laps.append(corpus_lap)
    superlap = build_superlap(corpus_laps) if corpus_laps else None
    return {
        "lap": lap,
        "setup": setup,
        "report": report,
        "balance": balance,
        "tyres": tyres,
        "conditions": conditions,
        "corner_reference": corner_reference,
        "trail_braking": trail_braking,
        "sector_deltas": sector_deltas,
        "superlap": superlap,
    }


def build_structured_debrief(
    lap_archive: dict,
    *,
    reference_archive: dict | None = None,
    history_archives: list[dict] | None = None,
    corpus_archives: list[dict] | None = None,
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
            history_archives=history_archives,
            corpus_archives=corpus_archives,
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
        trail_braking=a["trail_braking"],
        sector_deltas=a["sector_deltas"],
        superlap=a["superlap"],
    )
    corners = [
        {
            "index": c.index,
            "apex_spline": round(c.apex_spline, 4),
            "min_speed_kmh": c.min_speed_kmh,
            "time_loss_s": c.delta_s,
            "headline": c.headline,
            "diagnostics": c.diagnostics,
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
        "trail_braking": _trail_braking_struct(a["trail_braking"]),
        "sector_deltas": _sector_delta_struct(a["sector_deltas"]),
        "superlap": _superlap_struct(a["superlap"]),
    }


def build_debrief(
    lap_archive: dict,
    *,
    reference_archive: dict | None = None,
    history_archives: list[dict] | None = None,
    corpus_archives: list[dict] | None = None,
    setup: CarSetup | None = None,
    grip_ceiling_g: float | None = None,
) -> str:
    """End-to-end: archive(s) → debrief text."""
    a = _analyze(
        lap_archive,
        reference_archive=reference_archive,
        history_archives=history_archives,
        corpus_archives=corpus_archives,
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
        trail_braking=a["trail_braking"],
        sector_deltas=a["sector_deltas"],
        superlap=a["superlap"],
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Per-corner setup-vs-technique coaching debrief")
    p.add_argument("lap", help="lap archive JSON to coach")
    p.add_argument("--reference", help="reference lap archive JSON (e.g. a faster lap)")
    p.add_argument(
        "--corpus",
        action="append",
        default=[],
        help="additional lap archive JSON to include in the SuperLap corpus",
    )
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
    corpus = [_load_archive(path) for path in args.corpus]
    print(
        build_debrief(
            _load_archive(args.lap),
            reference_archive=ref,
            corpus_archives=corpus,
            setup=setup,
            grip_ceiling_g=args.grip_ceiling_g,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
