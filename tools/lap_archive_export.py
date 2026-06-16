"""Export AC Copilot Trainer per-lap archives to analysis CSV files.

The trainer writes one JSON file per completed lap under ``journal/laps``. This
module reads those immutable archives and writes either a stable generic CSV or
a best-effort MoTeC-shaped CSV for i2's CSV conversion path.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

LAP_ARCHIVE_SCHEMA_VERSION = 1

CSV_COLUMNS: tuple[str, ...] = (
    "source_file",
    "lap_uuid",
    "session_uuid",
    "car_id",
    "track_id",
    "lap_n",
    "lap_ms",
    "is_valid",
    "sample_index",
    "time_s",
    "elapsed_ms",
    "spline",
    "lap_distance_m",
    "speed_kmh",
    "brake",
    "throttle",
    "steering",
    "gear",
    "position_x_m",
    "position_y_m",
    "position_z_m",
)

_TRACE_TO_CSV: dict[str, str] = {
    "eMs": "elapsed_ms",
    "spline": "spline",
    "speed": "speed_kmh",
    "brake": "brake",
    "throttle": "throttle",
    "steer": "steering",
    "gear": "gear",
    "px": "position_x_m",
    "py": "position_y_m",
    "pz": "position_z_m",
}

_MOTEC_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("Time", "s", "time_s"),
    ("Ground Speed", "km/h", "speed_kmh"),
    ("Brake Pos", "%", "brake_pct"),
    ("Throttle Pos", "%", "throttle_pct"),
    ("Steering", "none", "steering"),
    ("Gear", "none", "gear"),
    ("Spline", "none", "spline"),
    ("Lap Distance", "m", "lap_distance_m"),
    ("Position X", "m", "position_x_m"),
    ("Position Y", "m", "position_y_m"),
    ("Position Z", "m", "position_z_m"),
    ("Lap Number", "none", "lap_n"),
    ("Lap Time", "s", "lap_time_s"),
    ("Valid Lap", "none", "valid_lap"),
)


class LapArchiveExportError(ValueError):
    """Raised when an archive cannot be read as a schema-v1 lap archive."""


def iter_lap_archive_paths(inputs: Iterable[str | Path]) -> Iterator[Path]:
    """Yield input files, expanding directories to sorted ``lap_*.json`` files."""
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(path.glob("lap_*.json"))
        else:
            yield path


def _as_finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        return text if text and text != "-0" else "0"
    return str(value)


def load_lap_archive(path: str | Path) -> dict[str, Any]:
    """Load one JSON archive file and validate the minimal schema envelope."""
    archive_path = Path(path)
    try:
        parsed = json.loads(archive_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LapArchiveExportError(f"{archive_path}: invalid JSON: {exc}") from exc
    except OSError as exc:
        raise LapArchiveExportError(f"{archive_path}: cannot read: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LapArchiveExportError(f"{archive_path}: root must be an object")
    if parsed.get("schema_version") != LAP_ARCHIVE_SCHEMA_VERSION:
        raise LapArchiveExportError(
            f"{archive_path}: schema_version must be {LAP_ARCHIVE_SCHEMA_VERSION}"
        )
    trace = parsed.get("trace")
    if not isinstance(trace, dict):
        raise LapArchiveExportError(f"{archive_path}: trace must be an object")
    if not isinstance(trace.get("fields"), list):
        raise LapArchiveExportError(f"{archive_path}: trace.fields must be an array")
    if not isinstance(trace.get("samples"), list):
        raise LapArchiveExportError(f"{archive_path}: trace.samples must be an array")
    return parsed


def lap_is_valid(record: dict[str, Any]) -> bool:
    """Return whether this archive lap should be exported by default."""
    lap = record.get("lap")
    if not isinstance(lap, dict):
        return True
    return lap.get("is_valid") is not False


def _field_map(record: dict[str, Any]) -> dict[str, int]:
    fields = record.get("trace", {}).get("fields", [])
    out: dict[str, int] = {}
    for idx, name in enumerate(fields):
        if isinstance(name, str) and name not in out:
            out[name] = idx
    return out


def _sample_value(sample: Any, fields: dict[str, int], name: str) -> float | None:
    if not isinstance(sample, list):
        return None
    idx = fields.get(name)
    if idx is None or idx >= len(sample):
        return None
    return _as_finite_float(sample[idx])


def _metadata(record: dict[str, Any], source_path: Path) -> dict[str, Any]:
    lap = record.get("lap") if isinstance(record.get("lap"), dict) else {}
    car = record.get("car") if isinstance(record.get("car"), dict) else {}
    track = record.get("track") if isinstance(record.get("track"), dict) else {}
    return {
        "source_file": source_path.name,
        "lap_uuid": record.get("lap_uuid"),
        "session_uuid": record.get("session_uuid"),
        "car_id": car.get("id"),
        "track_id": track.get("id"),
        "lap_n": lap.get("lap_n"),
        "lap_ms": lap.get("lap_ms"),
        "is_valid": lap.get("is_valid", True) is not False,
    }


def iter_csv_rows(
    archives: Iterable[tuple[Path, dict[str, Any]]],
) -> Iterator[dict[str, Any]]:
    """Yield normalized per-sample rows from loaded archive records."""
    for source_path, record in archives:
        fields = _field_map(record)
        trace = record.get("trace", {})
        samples = trace.get("samples", [])
        meta = _metadata(record, source_path)
        track = record.get("track") if isinstance(record.get("track"), dict) else {}
        track_len_m = _as_finite_float(track.get("lengthM"))
        for index, sample in enumerate(samples):
            row = {column: None for column in CSV_COLUMNS}
            row.update(meta)
            row["sample_index"] = index
            for trace_name, column in _TRACE_TO_CSV.items():
                row[column] = _sample_value(sample, fields, trace_name)
            elapsed_ms = row["elapsed_ms"]
            if elapsed_ms is not None:
                row["time_s"] = elapsed_ms / 1000.0
            spline = row["spline"]
            if spline is not None and track_len_m is not None:
                row["lap_distance_m"] = spline * track_len_m
            yield row


def _loaded_archives(
    inputs: Iterable[str | Path],
    *,
    include_invalid: bool,
) -> list[tuple[Path, dict[str, Any]]]:
    archives: list[tuple[Path, dict[str, Any]]] = []
    for path in iter_lap_archive_paths(inputs):
        record = load_lap_archive(path)
        if include_invalid or lap_is_valid(record):
            archives.append((path, record))
    return archives


def export_csv(
    inputs: Iterable[str | Path],
    output: str | Path,
    *,
    include_invalid: bool = False,
) -> int:
    """Write stable analysis CSV rows. Returns rows written."""
    archives = _loaded_archives(inputs, include_invalid=include_invalid)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in iter_csv_rows(archives):
            writer.writerow({column: _format_cell(row.get(column)) for column in CSV_COLUMNS})
            rows_written += 1
    return rows_written


def _parse_exported_at(record: dict[str, Any]) -> datetime | None:
    raw = record.get("exported_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _motec_header(
    archives: Sequence[tuple[Path, dict[str, Any]]], rows: list[dict[str, Any]]
) -> list[list[Any]]:
    first = archives[0][1] if archives else {}
    first_meta = _metadata(first, archives[0][0]) if archives else {}
    first_dt = _parse_exported_at(first)
    log_date = first_dt.strftime("%d/%m/%Y") if first_dt else ""
    log_time = first_dt.strftime("%I:%M:%S %p") if first_dt else ""
    end_time = max((_as_finite_float(row.get("time_s")) or 0.0 for row in rows), default=0.0)
    end_distance = max(
        (_as_finite_float(row.get("lap_distance_m")) or 0.0 for row in rows),
        default=0.0,
    )
    sample_rate = _sample_rate_hz(rows)
    beacon_markers = _beacon_markers(archives)
    return [
        ["Driver", "AC Copilot Trainer", "", "", "Vehicle ID", first_meta.get("car_id") or ""],
        ["Device", "AC Copilot Trainer"],
        [
            "Comment",
            "Exported from AC Copilot Trainer schema-v1 lap archives",
            "",
            "",
            "Session",
            first_meta.get("session_uuid") or "",
        ],
        ["Log Date", log_date, "", "", "Origin Time", "0.000", "s"],
        ["Log Time", log_time, "", "", "Start Time", "0.000", "s"],
        [
            "Sample Rate",
            _format_cell(sample_rate),
            "Hz",
            "",
            "End Time",
            _format_cell(end_time),
            "s",
        ],
        ["Duration", _format_cell(end_time), "s", "", "Start Distance", "0", "m"],
        ["Range", "entire outing", "", "", "End Distance", _format_cell(end_distance), "m"],
        ["Beacon Markers", " ".join(_format_cell(marker) for marker in beacon_markers)],
    ]


def _sample_rate_hz(rows: Sequence[dict[str, Any]]) -> float | None:
    times = [_as_finite_float(row.get("time_s")) for row in rows]
    finite = [time for time in times if time is not None]
    if len(finite) < 2:
        return None
    duration = finite[-1] - finite[0]
    if duration <= 0:
        return None
    return (len(finite) - 1) / duration


def _beacon_markers(archives: Sequence[tuple[Path, dict[str, Any]]]) -> list[float]:
    markers: list[float] = []
    offset = 0.0
    for _, record in archives:
        lap = record.get("lap") if isinstance(record.get("lap"), dict) else {}
        lap_ms = _as_finite_float(lap.get("lap_ms"))
        if lap_ms is None or lap_ms <= 0:
            continue
        offset += lap_ms / 1000.0
        markers.append(offset)
    return markers


def _rows_for_motec(archives: Sequence[tuple[Path, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset_s = 0.0
    for archive in archives:
        record = archive[1]
        lap = record.get("lap") if isinstance(record.get("lap"), dict) else {}
        lap_ms = _as_finite_float(lap.get("lap_ms"))
        lap_s = lap_ms / 1000.0 if lap_ms is not None else None
        for row in iter_csv_rows([archive]):
            motec = dict(row)
            raw_time = _as_finite_float(row.get("time_s"))
            motec["time_s"] = (offset_s + raw_time) if raw_time is not None else offset_s
            brake = _as_finite_float(row.get("brake"))
            throttle = _as_finite_float(row.get("throttle"))
            motec["brake_pct"] = brake * 100.0 if brake is not None else None
            motec["throttle_pct"] = throttle * 100.0 if throttle is not None else None
            motec["lap_time_s"] = lap_s
            motec["valid_lap"] = 1 if row.get("is_valid") is True else 0
            rows.append(motec)
        if lap_s is not None and lap_s > 0:
            offset_s += lap_s
    return rows


def export_motec_csv(
    inputs: Iterable[str | Path],
    output: str | Path,
    *,
    include_invalid: bool = False,
) -> int:
    """Write a MoTeC-shaped CSV. Returns sample rows written.

    This is not a native MoTeC ``.ld`` writer. The output intentionally follows
    the public i2 CSV-import conventions: metadata rows, a channel row, a units
    row, and quoted fields.
    """
    archives = _loaded_archives(inputs, include_invalid=include_invalid)
    rows = _rows_for_motec(archives)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
        for header_row in _motec_header(archives, rows):
            writer.writerow([_format_cell(value) for value in header_row])
        writer.writerow([name for name, _, _ in _MOTEC_CHANNELS])
        writer.writerow([unit for _, unit, _ in _MOTEC_CHANNELS])
        for row in rows:
            writer.writerow([_format_cell(row.get(key)) for _, _, key in _MOTEC_CHANNELS])
    return len(rows)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs", nargs="+", help="Archive JSON files or directories containing lap_*.json"
    )
    parser.add_argument("-o", "--output", required=True, help="Output CSV path")
    parser.add_argument(
        "--format",
        choices=("csv", "motec-csv"),
        default="csv",
        help="Export format (default: csv)",
    )
    parser.add_argument(
        "--include-invalid",
        action="store_true",
        help="Include laps with lap.is_valid=false; skipped by default",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, stderr: TextIO | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    err = stderr if stderr is not None else sys.stderr
    try:
        if args.format == "csv":
            count = export_csv(args.inputs, args.output, include_invalid=args.include_invalid)
        else:
            count = export_motec_csv(args.inputs, args.output, include_invalid=args.include_invalid)
    except LapArchiveExportError as exc:
        print(f"lap-archive-export: {exc}", file=err)
        return 2
    print(f"wrote {count} sample rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
