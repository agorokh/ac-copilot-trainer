"""Generate a saved post-session debrief artifact from lap archives.

The session review is a derived data product: it reads immutable
``journal/laps/lap_*.json`` archives, compares the selected session against the
best known lap for the same car/track, and writes Markdown + JSON under
``journal/reports``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape as html_escape
from pathlib import Path
from statistics import median
from typing import Any, TextIO

from tools.ai_sidecar.coach_report import build_structured_debrief
from tools.lap_archive_export import iter_lap_archive_paths, lap_is_valid, load_lap_archive

REPORT_SCHEMA_VERSION = 2
DEFAULT_OUTPUT_DIR = Path("journal/reports")
DEFAULT_SESSION = "latest"
_LOSS_THRESHOLD_S = 0.03
_MAX_COMPARE_LAPS = 40
_MAX_TRACE_POINTS = 240
REFERENCE_SOURCE_CHOICES = ("auto", "your-best", "pro", "tt", "generated", "imported", "none")
_REFERENCE_SOURCE_ALIASES = {
    "pb": "your-best",
    "personal": "your-best",
    "personal-best": "your-best",
    "your-best-lap": "your-best",
    "your-best-reference": "your-best",
    "track-titan": "tt",
    "tracktitan": "tt",
    "disabled": "none",
    "off": "none",
}


class SessionReviewError(ValueError):
    """Raised when a session report cannot be generated safely."""


@dataclass(frozen=True)
class LoadedLap:
    """One loaded lap archive plus normalized metadata."""

    path: Path
    record: dict[str, Any]
    session_uuid: str
    car_id: str
    track_id: str
    track_layout: str | None
    lap_n: int | None
    lap_ms: int | None
    exported_at: str | None
    is_valid: bool
    source: str | None
    import_format: str | None
    reference_kind: str


@dataclass(frozen=True)
class ReferenceSelection:
    """Reference-source selection result for one session report."""

    requested_source: str
    reference: LoadedLap | None
    reason: str
    reference_file: str | None = None


@dataclass(frozen=True)
class WrittenSessionReport:
    """Paths and payload returned by :func:`write_session_report`."""

    markdown_path: Path
    json_path: Path
    html_path: Path
    report: dict[str, Any]


def _num_ms(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    return int(round(parsed))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parsed_datetimes(laps: Iterable[LoadedLap]) -> list[datetime]:
    return [dt for dt in (_parse_dt(lap.exported_at) for lap in laps) if dt is not None]


def _format_ms(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) / 1000.0:.3f}s"


def _slug(value: Any, *, fallback: str = "unknown") -> str:
    text = str(value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text)
    return text.strip("-") or fallback


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def normalize_reference_source(value: str | None) -> str:
    """Normalize a user-facing reference source selector."""
    raw = (value or "auto").strip().lower().replace("_", "-")
    source = _REFERENCE_SOURCE_ALIASES.get(raw, raw)
    if source not in REFERENCE_SOURCE_CHOICES:
        choices = ", ".join(REFERENCE_SOURCE_CHOICES)
        raise SessionReviewError(f"reference_source must be one of: {choices}")
    return source


def _reference_kind(record: Mapping[str, Any]) -> str:
    source = _clean_text(record.get("source"))
    import_format = _clean_text(record.get("import_format"))
    generator = record.get("generator") if isinstance(record.get("generator"), Mapping) else {}
    generator_name = _clean_text(generator.get("name")) if isinstance(generator, Mapping) else None
    tt_reference = generator.get("tt_reference") if isinstance(generator, Mapping) else None
    if import_format == "track_titan_reference_v1" or isinstance(tt_reference, Mapping):
        return "tt"
    if import_format == "generated_reference_v1" or (
        generator_name is not None
        and (
            generator_name.startswith("ac_harness.reference_lap")
            or generator_name.startswith("tools.ac_harness.reference_lap")
            or generator_name.startswith("trace_replay:")
        )
    ):
        return "generated"
    if source == "in_game":
        return "your-best"
    if source == "imported" and import_format == "motec_csv":
        return "pro"
    if source == "imported":
        return "imported"
    return "unknown"


def _is_partial_tt_reference(record: Mapping[str, Any]) -> bool:
    generator = record.get("generator") if isinstance(record.get("generator"), Mapping) else {}
    tt_reference = generator.get("tt_reference") if isinstance(generator, Mapping) else None
    return isinstance(tt_reference, Mapping) and tt_reference.get("partial") is True


def _loaded_lap(path: Path, record: dict[str, Any]) -> LoadedLap:
    lap = record.get("lap") if isinstance(record.get("lap"), Mapping) else {}
    car = record.get("car") if isinstance(record.get("car"), Mapping) else {}
    track = record.get("track") if isinstance(record.get("track"), Mapping) else {}
    lap_n = lap.get("lap_n")
    return LoadedLap(
        path=path,
        record=record,
        session_uuid=str(record.get("session_uuid") or "unknown_session"),
        car_id=str(car.get("id") or "unknown_car"),
        track_id=str(track.get("id") or "unknown_track"),
        track_layout=str(track.get("layout")) if track.get("layout") is not None else None,
        lap_n=lap_n if isinstance(lap_n, int) and not isinstance(lap_n, bool) else None,
        lap_ms=_num_ms(lap.get("lap_ms")),
        exported_at=record.get("exported_at")
        if isinstance(record.get("exported_at"), str)
        else None,
        is_valid=lap_is_valid(record),
        source=_clean_text(record.get("source")),
        import_format=_clean_text(record.get("import_format")),
        reference_kind=_reference_kind(record),
    )


def _load_laps(inputs: Iterable[str | Path]) -> tuple[list[LoadedLap], list[str]]:
    laps: list[LoadedLap] = []
    skipped: list[str] = []
    try:
        paths = list(iter_lap_archive_paths(inputs))
    except Exception as exc:
        raise SessionReviewError(str(exc)) from exc
    for path in paths:
        try:
            record = load_lap_archive(path)
        except Exception as exc:  # noqa: BLE001 - one corrupt archive should not erase the review
            skipped.append(f"{Path(path).name}: {type(exc).__name__}")
            continue
        laps.append(_loaded_lap(Path(path), record))
    return laps, skipped


def _combo_key(lap: LoadedLap) -> tuple[str, str, str | None]:
    return lap.car_id, lap.track_id, lap.track_layout


def _session_candidates(laps: list[LoadedLap]) -> dict[str, list[LoadedLap]]:
    grouped: dict[str, list[LoadedLap]] = defaultdict(list)
    for lap in laps:
        grouped[lap.session_uuid].append(lap)
    return dict(grouped)


def _select_session(laps: list[LoadedLap], session: str) -> tuple[str, list[LoadedLap]]:
    sessions = _session_candidates(laps)
    if not sessions:
        raise SessionReviewError("no lap archives found")
    if session != DEFAULT_SESSION:
        selected = sessions.get(session)
        if not selected:
            raise SessionReviewError(f"session {session!r} was not found in the lap corpus")
        return session, sorted(selected, key=_lap_sort_key)

    def last_seen(item: tuple[str, list[LoadedLap]]) -> tuple[datetime, str]:
        timestamps = _parsed_datetimes(item[1])
        latest = max(timestamps) if timestamps else None
        return latest or datetime.min.replace(tzinfo=UTC), item[0]

    selected_session, selected_laps = max(sessions.items(), key=last_seen)
    return selected_session, sorted(selected_laps, key=_lap_sort_key)


def _lap_sort_key(lap: LoadedLap) -> tuple[int, datetime, str]:
    return (
        lap.lap_n if lap.lap_n is not None else 999_999,
        _parse_dt(lap.exported_at) or datetime.min.replace(tzinfo=UTC),
        lap.path.name,
    )


def _valid_laps(laps: Iterable[LoadedLap]) -> list[LoadedLap]:
    return [lap for lap in laps if lap.is_valid and lap.lap_ms is not None]


def _reference_candidates(laps: Iterable[LoadedLap]) -> list[LoadedLap]:
    return [lap for lap in _valid_laps(laps) if not _is_partial_tt_reference(lap.record)]


def _reference_sort_key(lap: LoadedLap) -> tuple[int, datetime, str]:
    return (
        lap.lap_ms if lap.lap_ms is not None else 999_999_999,
        _parse_dt(lap.exported_at) or datetime.max.replace(tzinfo=UTC),
        lap.path.name,
    )


def _reference_matches_source(lap: LoadedLap, source: str) -> bool:
    if source == "auto":
        return True
    return lap.reference_kind == source


def _select_reference(
    laps: list[LoadedLap],
    selected: list[LoadedLap],
    *,
    reference_source: str = "auto",
    reference_path: str | Path | None = None,
) -> ReferenceSelection:
    requested_source = normalize_reference_source(reference_source)
    if requested_source == "none":
        return ReferenceSelection(
            requested_source=requested_source,
            reference=None,
            reason="reference comparison disabled by request",
        )
    valid_selected = _valid_laps(selected)
    if not valid_selected:
        return ReferenceSelection(
            requested_source=requested_source,
            reference=None,
            reason="selected session has no valid timed laps",
        )
    combo = _combo_key(valid_selected[0])
    candidates = [lap for lap in _reference_candidates(laps) if _combo_key(lap) == combo]
    if not candidates:
        return ReferenceSelection(
            requested_source=requested_source,
            reference=None,
            reason="no valid same car/track reference candidates found",
        )
    if reference_path is not None:
        requested_path = Path(reference_path)
        requested_name = requested_path.name or "reference file"
        try:
            resolved = requested_path.resolve()
        except (OSError, RuntimeError) as exc:
            raise SessionReviewError(
                f"{requested_name}: reference path cannot be resolved"
            ) from exc
        for candidate in candidates:
            try:
                candidate_resolved = candidate.path.resolve()
            except (OSError, RuntimeError):
                candidate_resolved = candidate.path.absolute()
            if candidate_resolved == resolved:
                return ReferenceSelection(
                    requested_source=requested_source,
                    reference=candidate,
                    reason="explicit reference file selected",
                    reference_file=candidate.path.name,
                )
        raise SessionReviewError(
            f"{requested_path.name}: reference file is not a valid same car/track lap archive"
        )

    source_candidates = [
        lap for lap in candidates if _reference_matches_source(lap, requested_source)
    ]
    if not source_candidates:
        return ReferenceSelection(
            requested_source=requested_source,
            reference=None,
            reason=f"no valid same car/track reference candidates for {requested_source}",
        )
    reason = (
        "fastest valid same car/track reference"
        if requested_source == "auto"
        else f"fastest valid same car/track {requested_source} reference"
    )
    reference = min(source_candidates, key=_reference_sort_key)
    return ReferenceSelection(
        requested_source=requested_source,
        reference=reference,
        reason=reason,
        reference_file=reference.path.name,
    )


def _session_stats(session_uuid: str, selected: list[LoadedLap]) -> dict[str, Any]:
    valid = _valid_laps(selected)
    times = [lap.lap_ms for lap in valid if lap.lap_ms is not None]
    best = min(valid, key=lambda lap: lap.lap_ms or 999_999_999) if valid else None
    timestamps = _parsed_datetimes(selected)
    first = min(timestamps) if timestamps else None
    last = max(timestamps) if timestamps else None
    return {
        "session_uuid": session_uuid,
        "car_id": selected[0].car_id if selected else None,
        "track_id": selected[0].track_id if selected else None,
        "track_layout": selected[0].track_layout if selected else None,
        "first_exported_at": first.isoformat().replace("+00:00", "Z") if first else None,
        "last_exported_at": last.isoformat().replace("+00:00", "Z") if last else None,
        "lap_count": len(selected),
        "valid_laps": len(valid),
        "best_lap_ms": best.lap_ms if best else None,
        "best_lap_uuid": best.record.get("lap_uuid") if best else None,
        "best_source_file": best.path.name if best else None,
        "median_lap_ms": float(median(times)) if times else None,
        "consistency_ms": _population_stdev(times),
    }


def _population_stdev(values: list[int]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / len(values))


def _problem_seed(index: int) -> dict[str, Any]:
    return {
        "corner": index,
        "label": f"T{index + 1}",
        "laps_affected": 0,
        "total_time_loss_s": 0.0,
        "worst_time_loss_s": 0.0,
        "max_apex_deficit_kmh": 0.0,
        "causes": Counter(),
        "fixes": Counter(),
        "symptoms": Counter(),
        "headlines": Counter(),
        "lap_examples": [],
    }


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _add_corner_problem(
    problems: dict[int, dict[str, Any]],
    *,
    lap: LoadedLap,
    corner: Mapping[str, Any],
    reference_by_corner: Mapping[int, Mapping[str, Any]],
    trail_by_corner: Mapping[int, Mapping[str, Any]],
) -> None:
    index = int(corner.get("index") or 0)
    time_loss = max(_as_float(corner.get("time_loss_s")) or 0.0, 0.0)
    ref = reference_by_corner.get(index)
    deficit = max(_as_float(ref.get("deficit_to_target_kmh")) if ref else 0.0, 0.0)
    trail = trail_by_corner.get(index)
    attributions = [attr for attr in corner.get("attributions") or [] if isinstance(attr, Mapping)]
    has_advisory = any(bool(attr.get("advisory")) for attr in attributions)
    has_trail_issue = bool(trail and trail.get("classification") != "good_trail_brake")
    if time_loss < _LOSS_THRESHOLD_S and deficit < 2.0 and not has_advisory and not has_trail_issue:
        return

    problem = problems.setdefault(index, _problem_seed(index))
    problem["laps_affected"] += 1
    problem["total_time_loss_s"] += time_loss
    problem["worst_time_loss_s"] = max(problem["worst_time_loss_s"], time_loss)
    problem["max_apex_deficit_kmh"] = max(problem["max_apex_deficit_kmh"], deficit)
    if isinstance(corner.get("headline"), str):
        problem["headlines"][corner["headline"]] += 1

    for attr in attributions[:3]:
        cause = str(attr.get("cause_class") or "unknown")
        problem["causes"][cause] += 1
        symptom = str(attr.get("symptom") or "").strip()
        coaching = str(attr.get("coaching") or "").strip()
        if symptom:
            problem["symptoms"][symptom] += 1
        if coaching:
            problem["fixes"][coaching] += 1
    if ref:
        for finding in ref.get("findings") or []:
            if isinstance(finding, str) and finding.strip():
                problem["fixes"][finding.strip()] += 1
                break
    if trail and isinstance(trail.get("coaching"), str):
        problem["fixes"][trail["coaching"].strip()] += 1

    if len(problem["lap_examples"]) < 3:
        problem["lap_examples"].append(
            {
                "lap_uuid": lap.record.get("lap_uuid"),
                "lap_n": lap.lap_n,
                "source_file": lap.path.name,
                "time_loss_s": round(time_loss, 3),
                "apex_deficit_kmh": round(deficit, 1),
            }
        )


def _clean_problem(problem: Mapping[str, Any]) -> dict[str, Any]:
    fixes = problem["fixes"].most_common(3)
    causes = problem["causes"].most_common(3)
    symptoms = problem["symptoms"].most_common(3)
    headline = problem["headlines"].most_common(1)
    top_fix = fixes[0][0] if fixes else "Repeat the corner with an earlier, calmer reference."
    return {
        "corner": problem["corner"],
        "label": problem["label"],
        "laps_affected": problem["laps_affected"],
        "total_time_loss_s": round(problem["total_time_loss_s"], 3),
        "worst_time_loss_s": round(problem["worst_time_loss_s"], 3),
        "max_apex_deficit_kmh": round(problem["max_apex_deficit_kmh"], 1),
        "primary_cause": causes[0][0] if causes else "unknown",
        "causes": [{"cause": key, "count": count} for key, count in causes],
        "symptoms": [{"symptom": key, "count": count} for key, count in symptoms],
        "headline": headline[0][0] if headline else f"{problem['label']} needs attention",
        "ranked_fixes": [{"text": key, "count": count} for key, count in fixes],
        "recommended_fix": top_fix,
        "lap_examples": list(problem["lap_examples"]),
    }


def _aggregate_problems(
    selected: list[LoadedLap],
    *,
    reference: LoadedLap | None,
    grip_ceiling_g: float | None,
) -> tuple[list[dict[str, Any]], list[str], int]:
    problems: dict[int, dict[str, Any]] = {}
    skipped: list[str] = []
    analyzed = 0
    reference_record = reference.record if reference else None
    for lap in _valid_laps(selected):
        ref_for_lap = (
            None if reference is not None and reference.path == lap.path else reference_record
        )
        structured = build_structured_debrief(
            lap.record,
            reference_archive=ref_for_lap,
            grip_ceiling_g=grip_ceiling_g,
        )
        if structured is None and ref_for_lap is not None:
            structured = build_structured_debrief(
                lap.record,
                reference_archive=None,
                grip_ceiling_g=grip_ceiling_g,
            )
            if structured is not None and reference is not None:
                skipped.append(
                    f"{reference.path.name}: unusable reference for {lap.path.name}; "
                    "used lap-only analysis"
                )
        if not structured:
            skipped.append(f"{lap.path.name}: no usable trace")
            continue
        analyzed += 1
        reference_by_corner = {
            int(row.get("index") or 0): row
            for row in structured.get("corner_reference") or []
            if isinstance(row, Mapping)
        }
        trail_by_corner = {
            int(row.get("corner") or 0): row
            for row in structured.get("trail_braking") or []
            if isinstance(row, Mapping)
        }
        for corner in structured.get("corners") or []:
            if isinstance(corner, Mapping):
                _add_corner_problem(
                    problems,
                    lap=lap,
                    corner=corner,
                    reference_by_corner=reference_by_corner,
                    trail_by_corner=trail_by_corner,
                )

    ranked = sorted(
        (_clean_problem(problem) for problem in problems.values()),
        key=lambda row: (
            row["total_time_loss_s"],
            row["laps_affected"],
            row["max_apex_deficit_kmh"],
        ),
        reverse=True,
    )
    return ranked, skipped, analyzed


def _prep_items(problems: list[Mapping[str, Any]]) -> list[str]:
    items = []
    for problem in problems[:3]:
        items.append(f"{problem['label']}: {problem['recommended_fix']}")
    if not items:
        items.append("Bank clean laps and keep the same reference so trend data accumulates.")
    return items


def _spoken_summary(stats: Mapping[str, Any], problems: list[Mapping[str, Any]]) -> str:
    car = stats.get("car_id") or "car"
    track = stats.get("track_id") or "track"
    if problems:
        focus = ", ".join(str(problem["label"]) for problem in problems[:3])
        return (
            f"Session debrief for {car} at {track}: best lap "
            f"{_format_ms(stats.get('best_lap_ms'))}. Next session, focus {focus}."
        )
    return (
        f"Session debrief for {car} at {track}: best lap "
        f"{_format_ms(stats.get('best_lap_ms'))}. No repeated corner losses stood out."
    )


def _screen_summary(problems: list[Mapping[str, Any]]) -> list[str]:
    if not problems:
        return ["No repeated corner loss above threshold.", "Keep banking comparable laps."]
    return [
        f"{problem['label']}: {problem['total_time_loss_s']:.2f}s - {problem['primary_cause']}"
        for problem in problems[:3]
    ]


def build_session_report(
    inputs: Iterable[str | Path],
    *,
    session: str = DEFAULT_SESSION,
    driver_id: str = "local-driver",
    grip_ceiling_g: float | None = None,
    generated_at: str | None = None,
    reference_source: str = "auto",
    reference_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable session review report."""
    laps, load_skipped = _load_laps(inputs)
    selected_session, selected = _select_session(laps, session)
    stats = _session_stats(selected_session, selected)
    if not stats["valid_laps"]:
        raise SessionReviewError(f"session {selected_session!r} has no valid timed laps")
    reference_selection = _select_reference(
        laps,
        selected,
        reference_source=reference_source,
        reference_path=reference_path,
    )
    reference = reference_selection.reference
    problems, analysis_skipped, analyzed = _aggregate_problems(
        selected,
        reference=reference,
        grip_ceiling_g=grip_ceiling_g,
    )
    if analyzed == 0:
        raise SessionReviewError(
            f"session {selected_session!r} has no valid laps with usable trace"
        )
    prep = _prep_items(problems)
    history = _history_payload(laps, selected)
    comparison = _comparison_payload(
        laps,
        selected,
        reference=reference,
        reference_comparison_enabled=reference_selection.requested_source != "none",
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or _iso_now(),
        "driver_id": driver_id,
        "session": stats,
        "reference": _reference_struct(reference, reference_selection),
        "reference_selection": _reference_selection_struct(reference_selection),
        "problems": problems,
        "next_session_prep": prep,
        "history": history,
        "comparison": comparison,
        "share": {
            "formats": ["html", "markdown", "json"],
            "self_contained_html": True,
            "host_paths_in_broadcasts": False,
        },
        "spoken_summary": _spoken_summary(stats, problems),
        "screen_summary": _screen_summary(problems),
        "source": {
            "lap_files": len(laps),
            "selected_lap_files": [lap.path.name for lap in selected],
            "skipped": load_skipped + analysis_skipped,
        },
    }


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _reference_selection_struct(selection: ReferenceSelection) -> dict[str, Any]:
    return {
        "requested_source": selection.requested_source,
        "active": selection.reference is not None,
        "active_source": selection.reference.reference_kind if selection.reference else None,
        "source_file": selection.reference_file,
        "reason": selection.reason,
    }


def _reference_struct(
    reference: LoadedLap | None, selection: ReferenceSelection
) -> dict[str, Any] | None:
    if reference is None:
        return None
    return {
        "lap_uuid": reference.record.get("lap_uuid"),
        "session_uuid": reference.session_uuid,
        "source_file": reference.path.name,
        "lap_ms": reference.lap_ms,
        "car_id": reference.car_id,
        "track_id": reference.track_id,
        "track_layout": reference.track_layout,
        "source": reference.source,
        "import_format": reference.import_format,
        "kind": reference.reference_kind,
        "selection_source": selection.requested_source,
        "selection_reason": selection.reason,
    }


def _lap_uuid(lap: LoadedLap | None) -> str | None:
    if lap is None:
        return None
    value = lap.record.get("lap_uuid")
    return str(value) if value is not None else lap.path.stem


def _best_valid_lap(laps: Iterable[LoadedLap]) -> LoadedLap | None:
    valid = _valid_laps(laps)
    if not valid:
        return None
    return min(
        valid,
        key=lambda lap: (
            lap.lap_ms if lap.lap_ms is not None else 999_999_999,
            _parse_dt(lap.exported_at) or datetime.max.replace(tzinfo=UTC),
            lap.path.name,
        ),
    )


def _same_combo_laps(laps: Iterable[LoadedLap], selected: list[LoadedLap]) -> list[LoadedLap]:
    anchor = _best_valid_lap(selected) or (selected[0] if selected else None)
    if anchor is None:
        return []
    combo = _combo_key(anchor)
    return [lap for lap in laps if _combo_key(lap) == combo]


def _lap_browser_row(lap: LoadedLap, *, include_trace: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {
        "lap_uuid": _lap_uuid(lap),
        "session_uuid": lap.session_uuid,
        "source_file": lap.path.name,
        "car_id": lap.car_id,
        "track_id": lap.track_id,
        "track_layout": lap.track_layout,
        "lap_n": lap.lap_n,
        "lap_ms": lap.lap_ms,
        "is_valid": lap.is_valid,
        "exported_at": lap.exported_at,
        "source": lap.source,
        "import_format": lap.import_format,
        "reference_kind": lap.reference_kind,
    }
    if include_trace:
        row["trace"] = _trace_payload(lap)
    return row


def _session_history(laps: list[LoadedLap]) -> list[dict[str, Any]]:
    rows = [
        _session_stats(session_uuid, sorted(grouped, key=_lap_sort_key))
        for session_uuid, grouped in _session_candidates(laps).items()
    ]
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("last_exported_at") or ""),
            str(row.get("session_uuid") or ""),
        ),
    )


def _trend_sessions(same_combo: list[LoadedLap]) -> list[dict[str, Any]]:
    return _session_history(same_combo)


def _corner_value(corner: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _as_float(corner.get(key))
        if value is not None:
            return value
    return None


def _corner_trends(same_combo: list[LoadedLap]) -> list[dict[str, Any]]:
    by_corner: dict[int, dict[str, Any]] = {}
    grouped: dict[tuple[int, str], dict[str, Any]] = {}
    session_dates = {
        row["session_uuid"]: row.get("last_exported_at") for row in _trend_sessions(same_combo)
    }
    for lap in _valid_laps(same_combo):
        corners = lap.record.get("corners")
        if not isinstance(corners, list):
            continue
        for fallback_index, corner_raw in enumerate(corners):
            if not isinstance(corner_raw, Mapping):
                continue
            corner_index = corner_raw.get("index")
            try:
                index = (
                    int(corner_index)
                    if corner_index is not None and not isinstance(corner_index, bool)
                    else fallback_index
                )
            except (TypeError, ValueError):
                index = fallback_index
            label = str(corner_raw.get("label") or f"T{index + 1}")
            by_corner.setdefault(index, {"corner": index, "label": label})
            key = (index, lap.session_uuid)
            bucket = grouped.setdefault(
                key,
                {
                    "session_uuid": lap.session_uuid,
                    "last_exported_at": session_dates.get(lap.session_uuid),
                    "min_speeds": [],
                    "exit_speeds": [],
                },
            )
            min_speed = _corner_value(corner_raw, "minSpeed", "min_speed")
            exit_speed = _corner_value(corner_raw, "exitSpeed", "exit_speed")
            if min_speed is not None:
                bucket["min_speeds"].append(min_speed)
            if exit_speed is not None:
                bucket["exit_speeds"].append(exit_speed)

    results: list[dict[str, Any]] = []
    for index, meta in sorted(by_corner.items()):
        points = []
        for (corner_index, _session_uuid), bucket in grouped.items():
            if corner_index != index:
                continue
            min_values = bucket["min_speeds"]
            exit_values = bucket["exit_speeds"]
            if not min_values and not exit_values:
                continue
            points.append(
                {
                    "session_uuid": bucket["session_uuid"],
                    "last_exported_at": bucket["last_exported_at"],
                    "avg_min_speed_kmh": (
                        round(sum(min_values) / len(min_values), 1) if min_values else None
                    ),
                    "avg_exit_speed_kmh": (
                        round(sum(exit_values) / len(exit_values), 1) if exit_values else None
                    ),
                    "laps": max(len(min_values), len(exit_values)),
                }
            )
        points.sort(
            key=lambda row: (
                str(row.get("last_exported_at") or ""),
                str(row.get("session_uuid") or ""),
            )
        )
        if points:
            results.append({**meta, "points": points})
    return results


def _sample_indices(count: int, limit: int = _MAX_TRACE_POINTS) -> list[int]:
    if count <= 0:
        return []
    if count <= limit:
        return list(range(count))
    step = (count - 1) / max(limit - 1, 1)
    indexes = {0, count - 1}
    indexes.update(int(round(i * step)) for i in range(limit))
    return sorted(index for index in indexes if 0 <= index < count)


def _trace_payload(lap: LoadedLap) -> dict[str, Any]:
    trace = lap.record.get("trace")
    if not isinstance(trace, Mapping):
        return {"sample_count": 0, "sampled_points": 0, "points": []}
    fields = trace.get("fields")
    samples = trace.get("samples")
    if not isinstance(fields, list) or not isinstance(samples, list):
        return {"sample_count": 0, "sampled_points": 0, "points": []}
    field_index = {str(name): i for i, name in enumerate(fields)}
    spline_idx = field_index.get("spline")
    speed_idx = field_index.get("speed")
    brake_idx = field_index.get("brake")
    throttle_idx = field_index.get("throttle")
    steer_idx = field_index.get("steer")
    ems_idx = field_index.get("eMs")

    def sample_value(sample: Any, index: int | None) -> float | None:
        if index is None or not isinstance(sample, (list, tuple)) or index >= len(sample):
            return None
        return _as_float(sample[index])

    points = []
    denominator = max(len(samples) - 1, 1)
    for sample_index in _sample_indices(len(samples)):
        sample = samples[sample_index]
        spline = sample_value(sample, spline_idx)
        point = {
            "x": round(spline if spline is not None else sample_index / denominator, 5),
            "speed_kmh": _round_or_none(sample_value(sample, speed_idx), 2),
            "brake": _round_or_none(sample_value(sample, brake_idx), 4),
            "throttle": _round_or_none(sample_value(sample, throttle_idx), 4),
            "steer": _round_or_none(sample_value(sample, steer_idx), 4),
            "e_ms": _round_or_none(sample_value(sample, ems_idx), 1),
        }
        points.append(point)
    return {
        "sample_count": len(samples),
        "sampled_points": len(points),
        "points": points,
    }


def _round_or_none(value: float | None, digits: int) -> float | None:
    return round(value, digits) if value is not None else None


def _history_payload(laps: list[LoadedLap], selected: list[LoadedLap]) -> dict[str, Any]:
    same_combo = _same_combo_laps(laps, selected)
    anchor = _best_valid_lap(selected) or (selected[0] if selected else None)
    combo = (
        {
            "car_id": anchor.car_id,
            "track_id": anchor.track_id,
            "track_layout": anchor.track_layout,
        }
        if anchor
        else None
    )
    return {
        "sessions": _session_history(laps),
        "laps": [_lap_browser_row(lap) for lap in sorted(same_combo, key=_lap_sort_key)],
        "trend": {
            "combo": combo,
            "sessions": _trend_sessions(same_combo),
            "corner_speed": _corner_trends(same_combo),
        },
    }


def _comparison_payload(
    laps: list[LoadedLap],
    selected: list[LoadedLap],
    *,
    reference: LoadedLap | None,
    reference_comparison_enabled: bool = True,
) -> dict[str, Any]:
    same_combo = sorted(_reference_candidates(_same_combo_laps(laps, selected)), key=_lap_sort_key)
    best_selected = _best_valid_lap(selected)
    best_path = best_selected.path if best_selected is not None else None
    default_b = reference if reference is not None and reference.path != best_path else None
    if default_b is None and reference_comparison_enabled:
        default_b = next(
            (
                lap
                for lap in sorted(same_combo, key=lambda item: item.lap_ms or 999_999_999)
                if lap.path != best_path
            ),
            None,
        )

    included: dict[Path, LoadedLap] = {}
    for lap in same_combo[-_MAX_COMPARE_LAPS:]:
        included[lap.path] = lap
    for lap in (best_selected, default_b, reference):
        if lap is not None:
            included[lap.path] = lap
    compare_laps = sorted(included.values(), key=_lap_sort_key)
    return {
        "default_pair": {
            "a": _lap_uuid(best_selected),
            "b": _lap_uuid(default_b),
        },
        "laps": [_lap_browser_row(lap, include_trace=True) for lap in compare_laps],
    }


def _resolve_output_dir(output_dir: str | Path) -> Path:
    raw = Path(output_dir)
    base_dir = Path.cwd().resolve()
    resolved = raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()
    report_root = (base_dir / DEFAULT_OUTPUT_DIR).resolve()
    allowed = False
    try:
        resolved.relative_to(report_root)
        allowed = True
    except ValueError:
        allowed = False
    if not allowed and resolved.name == "reports" and resolved.parent.name == "journal":
        allowed = True
    if not allowed:
        report_root_label = DEFAULT_OUTPUT_DIR.as_posix()
        raise SessionReviewError(f"{raw}: report output must stay under {report_root_label}")
    return resolved


def report_dir_for_lap_dir(lap_dir: str | Path) -> Path:
    """Return the sibling ``journal/reports`` directory for a lap archive corpus."""
    raw = Path(lap_dir)
    resolved = raw.resolve() if raw.is_absolute() else (Path.cwd() / raw).resolve()
    return resolved.parent / "reports"


def _report_basename(report: Mapping[str, Any]) -> str:
    session = report.get("session") if isinstance(report.get("session"), Mapping) else {}
    parts = [
        "session",
        _slug(session.get("session_uuid")),
        _slug(session.get("car_id"), fallback="car"),
        _slug(session.get("track_id"), fallback="track"),
    ]
    return "_".join(parts)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the session report as driver-readable Markdown."""
    session = report.get("session") if isinstance(report.get("session"), Mapping) else {}
    reference = report.get("reference") if isinstance(report.get("reference"), Mapping) else None
    title = f"{session.get('car_id') or 'car'} @ {session.get('track_id') or 'track'}"
    lines = [
        f"# Session Review - {title}",
        "",
        f"- Session: `{session.get('session_uuid')}`",
        f"- Best lap: {_format_ms(session.get('best_lap_ms'))}",
        f"- Valid laps: {session.get('valid_laps')} / {session.get('lap_count')}",
        f"- Median lap: {_format_ms(session.get('median_lap_ms'))}",
        f"- Consistency: {_format_ms(session.get('consistency_ms'))}",
    ]
    if reference:
        kind = reference.get("kind") or reference.get("source") or "reference"
        lines.append(
            f"- Reference: `{reference.get('source_file')}` "
            f"({_format_ms(reference.get('lap_ms'))}, {kind})"
        )
    else:
        selection = (
            report.get("reference_selection")
            if isinstance(report.get("reference_selection"), Mapping)
            else None
        )
        if selection:
            lines.append(f"- Reference: none ({selection.get('reason')})")
    lines.extend(["", "## Problem List"])
    problems = report.get("problems") if isinstance(report.get("problems"), list) else []
    if problems:
        for rank, problem in enumerate(problems, start=1):
            lines.extend(
                [
                    "",
                    f"{rank}. **{problem['label']}** - "
                    f"{problem['total_time_loss_s']:.3f}s total loss across "
                    f"{problem['laps_affected']} lap(s)",
                    f"   - Cause: {problem['primary_cause']}",
                    f"   - Symptom: {problem['headline']}",
                    f"   - Fix: {problem['recommended_fix']}",
                ]
            )
    else:
        lines.extend(["", "No repeated corner loss above threshold."])
    lines.extend(["", "## Next Session Prep"])
    for item in report.get("next_session_prep") or []:
        lines.append(f"- {item}")
    history = report.get("history") if isinstance(report.get("history"), Mapping) else {}
    trend = history.get("trend") if isinstance(history.get("trend"), Mapping) else {}
    trend_sessions = trend.get("sessions") if isinstance(trend.get("sessions"), list) else []
    if trend_sessions:
        lines.extend(["", "## Lap History"])
        for row in trend_sessions[-5:]:
            lines.append(
                "- "
                f"{row.get('session_uuid')}: best {_format_ms(row.get('best_lap_ms'))}, "
                f"median {_format_ms(row.get('median_lap_ms'))}, "
                f"valid {row.get('valid_laps')} / {row.get('lap_count')}"
            )
    comparison = report.get("comparison") if isinstance(report.get("comparison"), Mapping) else {}
    pair = (
        comparison.get("default_pair")
        if isinstance(comparison.get("default_pair"), Mapping)
        else {}
    )
    if pair.get("a") or pair.get("b"):
        lines.extend(
            [
                "",
                "## Lap Compare",
                f"- Lap A: `{pair.get('a') or 'n/a'}`",
                f"- Lap B: `{pair.get('b') or 'n/a'}`",
            ]
        )
    lines.extend(["", "## Spoken Summary", "", str(report.get("spoken_summary") or "")])
    return "\n".join(lines).rstrip() + "\n"


def _html(value: Any) -> str:
    return html_escape("" if value is None else str(value), quote=True)


def _html_ms(value: Any) -> str:
    return _html(_format_ms(value))


def _trend_svg(points: list[Mapping[str, Any]]) -> str:
    values = [
        _as_float(point.get("best_lap_ms"))
        for point in points
        if _as_float(point.get("best_lap_ms")) is not None
    ]
    if len(values) < 2:
        return '<p class="empty">Need at least two sessions for a lap-time trend.</p>'
    width, height, pad = 720, 180, 28
    min_value = min(values)
    max_value = max(values)
    span = max(max_value - min_value, 1.0)
    trend_points = []
    value_points = [point for point in points if _as_float(point.get("best_lap_ms")) is not None]
    for index, point in enumerate(value_points):
        value = _as_float(point.get("best_lap_ms")) or 0.0
        x = pad + (width - 2 * pad) * index / max(len(value_points) - 1, 1)
        y = height - pad - (height - 2 * pad) * (max_value - value) / span
        trend_points.append((x, y, value, point))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _value, _point in trend_points)
    circles = "\n".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4"><title>'
        f"{_html(point.get('session_uuid'))}: {_html_ms(value)}</title></circle>"
        for x, y, value, point in trend_points
    )
    start_label = _html_ms(trend_points[0][2])
    end_label = _html_ms(trend_points[-1][2])
    return f"""
<svg class="trend-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Best lap trend">
  <line class="axis" x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" />
  <line class="axis" x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" />
  <polyline class="lap-line" points="{polyline}" />
  {circles}
  <text x="{pad}" y="{height - 6}" class="chart-label">{start_label}</text>
  <text x="{width - pad}" y="{height - 6}" class="chart-label" text-anchor="end">{end_label}</text>
</svg>
""".strip()


def _history_rows_html(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return '<tr><td colspan="6">No history rows.</td></tr>'
    rendered = []
    for row in rows[-12:]:
        rendered.append(
            "<tr>"
            f"<td>{_html(row.get('session_uuid'))}</td>"
            f"<td>{_html(row.get('last_exported_at'))}</td>"
            f"<td>{_html_ms(row.get('best_lap_ms'))}</td>"
            f"<td>{_html_ms(row.get('median_lap_ms'))}</td>"
            f"<td>{_html_ms(row.get('consistency_ms'))}</td>"
            f"<td>{_html(row.get('valid_laps'))}/{_html(row.get('lap_count'))}</td>"
            "</tr>"
        )
    return "\n".join(rendered)


def _problem_rows_html(problems: list[Mapping[str, Any]]) -> str:
    if not problems:
        return '<tr><td colspan="5">No repeated corner loss above threshold.</td></tr>'
    rendered = []
    for rank, problem in enumerate(problems[:8], start=1):
        rendered.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{_html(problem.get('label'))}</td>"
            f"<td>{_html(problem.get('primary_cause'))}</td>"
            f"<td>{_html(problem.get('total_time_loss_s'))}s</td>"
            f"<td>{_html(problem.get('recommended_fix'))}</td>"
            "</tr>"
        )
    return "\n".join(rendered)


def _corner_trend_html(corners: list[Mapping[str, Any]]) -> str:
    if not corners:
        return '<p class="empty">No corner trend rows in this corpus yet.</p>'
    rendered = []
    for corner in corners[:8]:
        points = corner.get("points") if isinstance(corner.get("points"), list) else []
        latest = points[-1] if points else {}
        rendered.append(
            "<tr>"
            f"<td>{_html(corner.get('label'))}</td>"
            f"<td>{_html(latest.get('avg_min_speed_kmh'))}</td>"
            f"<td>{_html(latest.get('avg_exit_speed_kmh'))}</td>"
            f"<td>{_html(len(points))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Corner</th><th>Apex km/h</th><th>Exit km/h</th>"
        "<th>Sessions</th></tr></thead><tbody>" + "\n".join(rendered) + "</tbody></table>"
    )


def _json_for_script(report: Mapping[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")


def render_html(report: Mapping[str, Any]) -> str:
    """Render a self-contained session review HTML report."""
    session = report.get("session") if isinstance(report.get("session"), Mapping) else {}
    history = report.get("history") if isinstance(report.get("history"), Mapping) else {}
    trend = history.get("trend") if isinstance(history.get("trend"), Mapping) else {}
    trend_sessions = trend.get("sessions") if isinstance(trend.get("sessions"), list) else []
    corners = trend.get("corner_speed") if isinstance(trend.get("corner_speed"), list) else []
    problems = report.get("problems") if isinstance(report.get("problems"), list) else []
    prep_items = (
        report.get("next_session_prep") if isinstance(report.get("next_session_prep"), list) else []
    )
    reference = report.get("reference") if isinstance(report.get("reference"), Mapping) else None
    reference_selection = (
        report.get("reference_selection")
        if isinstance(report.get("reference_selection"), Mapping)
        else None
    )
    title = f"{session.get('car_id') or 'car'} at {session.get('track_id') or 'track'}"
    prep_html = "\n".join(f"<li>{_html(item)}</li>" for item in prep_items)
    if not prep_html:
        prep_html = "<li>Keep banking comparable laps.</li>"
    data_json = _json_for_script(report)
    if reference:
        reference_meta = (
            f"Reference {_html(reference.get('source_file'))} "
            f"({_html_ms(reference.get('lap_ms'))}, {_html(reference.get('kind') or 'reference')})"
        )
    elif reference_selection:
        reference_meta = f"Reference none ({_html(reference_selection.get('reason'))})"
    else:
        reference_meta = "Reference none"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Session Review - {_html(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #182126;
      --muted: #60717a;
      --paper: #f8f7f2;
      --line: #d7d2c4;
      --panel: #ffffff;
      --teal: #167c80;
      --red: #d1495b;
      --amber: #e3a12f;
      --blue: #2f6fbb;
      --green: #3a8b5c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 15px/1.45 "Segoe UI", Arial, sans-serif;
      letter-spacing: 0;
    }}
    header {{
      padding: 28px clamp(18px, 5vw, 56px) 22px;
      border-bottom: 1px solid var(--line);
      background: #fffdf7;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px clamp(16px, 4vw, 36px) 48px;
    }}
    h1, h2, h3 {{ margin: 0; line-height: 1.1; letter-spacing: 0; }}
    h1 {{ font-size: clamp(30px, 4vw, 48px); }}
    h2 {{ font-size: 22px; margin-bottom: 14px; }}
    h3 {{
      font-size: 15px;
      color: var(--muted);
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .meta {{ margin-top: 10px; color: var(--muted); }}
    section {{ padding: 22px 0; border-bottom: 1px solid var(--line); }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .kpi {{
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 14px;
      border-radius: 8px;
    }}
    .kpi strong {{ display: block; font-size: 24px; color: var(--teal); }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, .8fr);
      gap: 22px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    ul {{ margin: 0; padding-left: 20px; }}
    .trend-svg {{
      width: 100%;
      min-height: 180px;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    .axis {{ stroke: var(--line); stroke-width: 1; }}
    .lap-line {{ fill: none; stroke: var(--red); stroke-width: 3; }}
    circle {{ fill: var(--red); }}
    .chart-label {{ fill: var(--muted); font-size: 12px; }}
    .controls {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }}
    label {{
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    select {{
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: white;
      color: var(--ink);
    }}
    #compare-chart {{
      width: 100%;
      min-height: 260px;
      background: var(--panel);
      border: 1px solid var(--line);
      display: block;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
      margin-top: 10px;
    }}
    .swatch {{
      display: inline-block;
      width: 20px;
      height: 3px;
      margin-right: 6px;
      vertical-align: middle;
    }}
    .empty {{
      color: var(--muted);
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 14px;
      margin: 0;
    }}
    @media (max-width: 760px) {{
      .kpis, .grid, .controls {{ grid-template-columns: 1fr; }}
      th, td {{ padding: 8px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{_html(title)}</h1>
    <div class="meta">
      Session {_html(session.get("session_uuid"))} - generated {_html(report.get("generated_at"))}
    </div>
    <div class="meta">{reference_meta}</div>
  </header>
  <main>
    <section class="kpis" aria-label="Session summary">
      <div class="kpi">
        <h3>Best Lap</h3><strong>{_html_ms(session.get("best_lap_ms"))}</strong>
      </div>
      <div class="kpi">
        <h3>Median</h3><strong>{_html_ms(session.get("median_lap_ms"))}</strong>
      </div>
      <div class="kpi">
        <h3>Consistency</h3><strong>{_html_ms(session.get("consistency_ms"))}</strong>
      </div>
      <div class="kpi">
        <h3>Valid Laps</h3>
        <strong>{_html(session.get("valid_laps"))}/{_html(session.get("lap_count"))}</strong>
      </div>
    </section>
    <section class="grid">
      <div>
        <h2>Debrief</h2>
        <table>
          <thead><tr><th>Rank</th><th>Corner</th><th>Cause</th><th>Loss</th><th>Fix</th></tr></thead>
          <tbody>{_problem_rows_html(problems)}</tbody>
        </table>
      </div>
      <div>
        <h2>Next Session</h2>
        <ul>{prep_html}</ul>
      </div>
    </section>
    <section>
      <h2>History</h2>
      <table>
        <thead>
          <tr>
            <th>Session</th><th>Last Lap</th><th>Best</th>
            <th>Median</th><th>Consistency</th><th>Valid</th>
          </tr>
        </thead>
        <tbody>{_history_rows_html(trend_sessions)}</tbody>
      </table>
    </section>
    <section class="grid">
      <div>
        <h2>Lap-Time Trend</h2>
        {_trend_svg(trend_sessions)}
      </div>
      <div>
        <h2>Corner Trends</h2>
        {_corner_trend_html(corners)}
      </div>
    </section>
    <section>
      <h2>Lap Compare</h2>
      <div class="controls">
        <label>Lap A<select id="lap-a"></select></label>
        <label>Lap B<select id="lap-b"></select></label>
      </div>
      <svg id="compare-chart" viewBox="0 0 900 300" role="img"
        aria-label="Telemetry trace comparison"></svg>
      <div class="legend">
        <span><span class="swatch" style="background:var(--red)"></span>Speed A/B</span>
        <span><span class="swatch" style="background:var(--blue)"></span>Throttle</span>
        <span><span class="swatch" style="background:var(--amber)"></span>Brake</span>
        <span><span class="swatch" style="background:var(--green)"></span>Steer</span>
      </div>
    </section>
  </main>
  <script id="review-data" type="application/json">{data_json}</script>
  <script>
    const report = JSON.parse(document.getElementById("review-data").textContent);
    const laps = (report.comparison && report.comparison.laps) || [];
    const pair = (report.comparison && report.comparison.default_pair) || {{}};
    const selectA = document.getElementById("lap-a");
    const selectB = document.getElementById("lap-b");
    const chart = document.getElementById("compare-chart");
    const colors = {{
      speed_kmh: "#d1495b",
      throttle: "#2f6fbb",
      brake: "#e3a12f",
      steer: "#3a8b5c"
    }};
    function labelFor(lap) {{
      const n = lap.lap_n === null || lap.lap_n === undefined ? "?" : lap.lap_n;
      const time = lap.lap_ms ? (lap.lap_ms / 1000).toFixed(3) + "s" : "n/a";
      return "L" + n + " - " + time + " - " + lap.session_uuid;
    }}
    function fillSelect(select, preferred) {{
      select.textContent = "";
      for (const lap of laps) {{
        const option = document.createElement("option");
        option.value = lap.lap_uuid;
        option.textContent = labelFor(lap);
        select.appendChild(option);
      }}
      if (preferred) select.value = preferred;
    }}
    function lapById(id) {{
      return laps.find((lap) => lap.lap_uuid === id) || laps[0];
    }}
    function maxSpeed() {{
      let value = 1;
      for (const lap of laps) {{
        for (const point of ((lap.trace && lap.trace.points) || [])) {{
          if (Number.isFinite(point.speed_kmh)) {{
            value = Math.max(value, point.speed_kmh);
          }}
        }}
      }}
      return value;
    }}
    function norm(point, key, speedMax) {{
      const value = point[key];
      if (!Number.isFinite(value)) return null;
      if (key === "speed_kmh") return value / speedMax;
      if (key === "steer") return (Math.max(-1, Math.min(1, value)) + 1) / 2;
      return Math.max(0, Math.min(1, value));
    }}
    function pathFor(points, key, speedMax, yBase, yScale) {{
      const coords = [];
      for (const point of points) {{
        const yNorm = norm(point, key, speedMax);
        if (yNorm === null) continue;
        const x = 32 + point.x * 836;
        const y = yBase - yNorm * yScale;
        coords.push(x.toFixed(1) + "," + y.toFixed(1));
      }}
      return coords.join(" ");
    }}
    function draw() {{
      const a = lapById(selectA.value);
      const b = lapById(selectB.value);
      const speedMax = maxSpeed();
      const aPoints = (a && a.trace && a.trace.points) || [];
      const bPoints = (b && b.trace && b.trace.points) || [];
      chart.textContent = "";
      const ns = "http://www.w3.org/2000/svg";
      function add(tag, attrs) {{
        const node = document.createElementNS(ns, tag);
        for (const [key, value] of Object.entries(attrs)) {{
          node.setAttribute(key, value);
        }}
        chart.appendChild(node);
        return node;
      }}
      add("line", {{x1: 32, y1: 260, x2: 868, y2: 260, stroke: "#d7d2c4"}});
      add("line", {{x1: 32, y1: 40, x2: 32, y2: 260, stroke: "#d7d2c4"}});
      for (const key of ["speed_kmh", "throttle", "brake", "steer"]) {{
        const pathA = pathFor(aPoints, key, speedMax, 260, 210);
        const pathB = pathFor(bPoints, key, speedMax, 260, 210);
        const width = key === "speed_kmh" ? 3 : 1.8;
        if (pathA) {{
          add("polyline", {{
            points: pathA,
            fill: "none",
            stroke: colors[key],
            "stroke-width": width
          }});
        }}
        if (pathB) {{
          add("polyline", {{
            points: pathB,
            fill: "none",
            stroke: colors[key],
            "stroke-width": width,
            "stroke-dasharray": "7 5"
          }});
        }}
      }}
      add("text", {{
        x: 32,
        y: 286,
        fill: "#60717a",
        "font-size": 12
      }}).textContent = a ? labelFor(a) : "No lap";
      add("text", {{
        x: 868,
        y: 286,
        fill: "#60717a",
        "font-size": 12,
        "text-anchor": "end"
      }}).textContent = b ? labelFor(b) : "No lap";
    }}
    fillSelect(selectA, pair.a);
    fillSelect(selectB, pair.b);
    selectA.addEventListener("change", draw);
    selectB.addEventListener("change", draw);
    draw();
  </script>
</body>
</html>
"""


def write_session_report(
    report: Mapping[str, Any],
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> WrittenSessionReport:
    """Write Markdown, JSON, and HTML report files under ``journal/reports``."""
    resolved_dir = _resolve_output_dir(output_dir)
    basename = _report_basename(report)
    markdown_path = resolved_dir / f"{basename}.md"
    json_path = resolved_dir / f"{basename}.json"
    html_path = resolved_dir / f"{basename}.html"
    _atomic_write(markdown_path, render_markdown(report))
    _atomic_write(json_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _atomic_write(html_path, render_html(report))
    return WrittenSessionReport(
        markdown_path=markdown_path,
        json_path=json_path,
        html_path=html_path,
        report=dict(report),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lap-dir",
        action="append",
        type=Path,
        default=[],
        help="Directory containing lap_*.json archives; repeat for multiple corpora.",
    )
    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help="Session UUID to review, or 'latest' (default).",
    )
    parser.add_argument("--driver-id", default="local-driver")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--grip-ceiling-g", type=float, default=None)
    parser.add_argument(
        "--reference-source",
        choices=REFERENCE_SOURCE_CHOICES,
        default="auto",
        help=(
            "Reference selector for same-car/track comparison: auto, your-best, pro, "
            "tt, generated, imported, or none."
        ),
    )
    parser.add_argument(
        "--reference-path",
        type=Path,
        default=None,
        help="Optional explicit lap_*.json archive to use as the reference.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result paths.")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    if not args.lap_dir:
        parser.error("pass at least one --lap-dir")
    try:
        report = build_session_report(
            args.lap_dir,
            session=args.session,
            driver_id=args.driver_id,
            grip_ceiling_g=args.grip_ceiling_g,
            reference_source=args.reference_source,
            reference_path=args.reference_path,
        )
        written = write_session_report(report, output_dir=args.output_dir)
    except SessionReviewError as exc:
        print(f"session-review: {exc}", file=err)
        return 2
    if args.json:
        print(
            json.dumps(
                {
                    "markdown": str(written.markdown_path),
                    "json": str(written.json_path),
                    "html": str(written.html_path),
                    "reference": report.get("reference"),
                    "reference_selection": report.get("reference_selection"),
                    "spoken_summary": report["spoken_summary"],
                    "screen_summary": report["screen_summary"],
                },
                sort_keys=True,
            ),
            file=out,
        )
    else:
        print(f"session-review: wrote {written.markdown_path}", file=out)
        print(f"session-review: wrote {written.json_path}", file=out)
        print(f"session-review: wrote {written.html_path}", file=out)
        print(report["spoken_summary"], file=out)
    return 0
