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
from pathlib import Path
from statistics import median
from typing import Any, TextIO

from tools.ai_sidecar.coach_report import build_structured_debrief
from tools.lap_archive_export import iter_lap_archive_paths, lap_is_valid, load_lap_archive

REPORT_SCHEMA_VERSION = 1
DEFAULT_OUTPUT_DIR = Path("journal/reports")
DEFAULT_SESSION = "latest"
_LOSS_THRESHOLD_S = 0.03


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


@dataclass(frozen=True)
class WrittenSessionReport:
    """Paths and payload returned by :func:`write_session_report`."""

    markdown_path: Path
    json_path: Path
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


def _format_ms(value: int | float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) / 1000.0:.3f}s"


def _slug(value: Any, *, fallback: str = "unknown") -> str:
    text = str(value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text)
    return text.strip("-") or fallback


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
        latest = max((_parse_dt(lap.exported_at) for lap in item[1]), default=None)
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


def _select_reference(laps: list[LoadedLap], selected: list[LoadedLap]) -> LoadedLap | None:
    valid_selected = _valid_laps(selected)
    if not valid_selected:
        return None
    combo = _combo_key(valid_selected[0])
    candidates = [lap for lap in _valid_laps(laps) if _combo_key(lap) == combo]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda lap: (
            lap.lap_ms if lap.lap_ms is not None else 999_999_999,
            _parse_dt(lap.exported_at) or datetime.max.replace(tzinfo=UTC),
            lap.path.name,
        ),
    )


def _session_stats(session_uuid: str, selected: list[LoadedLap]) -> dict[str, Any]:
    valid = _valid_laps(selected)
    times = [lap.lap_ms for lap in valid if lap.lap_ms is not None]
    best = min(valid, key=lambda lap: lap.lap_ms or 999_999_999) if valid else None
    first = min((_parse_dt(lap.exported_at) for lap in selected), default=None)
    last = max((_parse_dt(lap.exported_at) for lap in selected), default=None)
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
) -> tuple[list[dict[str, Any]], list[str]]:
    problems: dict[int, dict[str, Any]] = {}
    skipped: list[str] = []
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
        if not structured:
            skipped.append(f"{lap.path.name}: no usable trace")
            continue
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
    return ranked, skipped


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
) -> dict[str, Any]:
    """Build a JSON-serializable session review report."""
    laps, load_skipped = _load_laps(inputs)
    selected_session, selected = _select_session(laps, session)
    stats = _session_stats(selected_session, selected)
    if not stats["valid_laps"]:
        raise SessionReviewError(f"session {selected_session!r} has no valid timed laps")
    reference = _select_reference(laps, selected)
    problems, analysis_skipped = _aggregate_problems(
        selected,
        reference=reference,
        grip_ceiling_g=grip_ceiling_g,
    )
    prep = _prep_items(problems)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or _iso_now(),
        "driver_id": driver_id,
        "session": stats,
        "reference": _reference_struct(reference),
        "problems": problems,
        "next_session_prep": prep,
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


def _reference_struct(reference: LoadedLap | None) -> dict[str, Any] | None:
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
    }


def _resolve_output_dir(output_dir: str | Path) -> Path:
    raw = Path(output_dir)
    base_dir = Path.cwd().resolve()
    resolved = raw.resolve() if raw.is_absolute() else (base_dir / raw).resolve()
    report_root = (base_dir / DEFAULT_OUTPUT_DIR).resolve()
    try:
        resolved.relative_to(report_root)
    except ValueError as exc:
        report_root_label = DEFAULT_OUTPUT_DIR.as_posix()
        raise SessionReviewError(
            f"{raw}: report output must stay under {report_root_label}"
        ) from exc
    return resolved


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
        lines.append(
            f"- Reference: `{reference.get('source_file')}` ({_format_ms(reference.get('lap_ms'))})"
        )
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
    lines.extend(["", "## Spoken Summary", "", str(report.get("spoken_summary") or "")])
    return "\n".join(lines).rstrip() + "\n"


def write_session_report(
    report: Mapping[str, Any],
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> WrittenSessionReport:
    """Write Markdown and JSON report files under ``journal/reports``."""
    resolved_dir = _resolve_output_dir(output_dir)
    basename = _report_basename(report)
    markdown_path = resolved_dir / f"{basename}.md"
    json_path = resolved_dir / f"{basename}.json"
    _atomic_write(markdown_path, render_markdown(report))
    _atomic_write(json_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    return WrittenSessionReport(
        markdown_path=markdown_path, json_path=json_path, report=dict(report)
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
        print(report["spoken_summary"], file=out)
    return 0
