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
import tempfile
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
        elif path.is_file():
            yield path
        else:
            raise LapArchiveExportError(
                f"{path}: input path does not exist or is not a file/directory"
            )


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


def _iter_loaded_archives(
    inputs: Iterable[str | Path],
    *,
    include_invalid: bool,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    for path in iter_lap_archive_paths(inputs):
        record = load_lap_archive(path)
        if include_invalid or lap_is_valid(record):
            yield path, record


def _resolve_output_path(output: str | Path) -> Path:
    raw_path = Path(output)
    if raw_path.is_absolute():
        raise LapArchiveExportError(f"{raw_path}: output path must be relative")

    base_dir = Path.cwd().resolve()
    output_path = (base_dir / raw_path).resolve()
    try:
        output_path.relative_to(base_dir)
    except ValueError as exc:
        raise LapArchiveExportError(f"{raw_path}: output path must stay within {base_dir}") from exc
    if output_path.exists() and output_path.is_dir():
        raise LapArchiveExportError(f"{raw_path}: output path must be a file")
    return output_path


def _open_temporary_output(output_path: Path) -> tempfile._TemporaryFileWrapper[str]:
    return tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    )


def export_csv(
    inputs: Iterable[str | Path],
    output: str | Path,
    *,
    include_invalid: bool = False,
) -> int:
    """Write stable analysis CSV rows. Returns rows written."""
    output_path = _resolve_output_path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    rows_written = 0
    try:
        with _open_temporary_output(output_path) as fh:
            tmp_path = Path(fh.name)
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            archives = _iter_loaded_archives(inputs, include_invalid=include_invalid)
            for row in iter_csv_rows(archives):
                writer.writerow({column: _format_cell(row.get(column)) for column in CSV_COLUMNS})
                rows_written += 1
        assert tmp_path is not None
        tmp_path.replace(output_path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise
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
    first_archive: tuple[Path, dict[str, Any]] | None, stats: dict[str, Any]
) -> list[list[Any]]:
    first = first_archive[1] if first_archive else {}
    first_meta = _metadata(first, first_archive[0]) if first_archive else {}
    first_dt = _parse_exported_at(first)
    log_date = first_dt.strftime("%d/%m/%Y") if first_dt else ""
    log_time = first_dt.strftime("%I:%M:%S %p") if first_dt else ""
    end_time = _as_finite_float(stats.get("end_time_s")) or 0.0
    end_distance = _as_finite_float(stats.get("end_distance_m")) or 0.0
    sample_rate = _as_finite_float(stats.get("sample_rate_hz"))
    beacon_markers = stats.get("beacon_markers", [])
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


_MOTEC_GROUP_FIELDS = ("session_uuid", "car_id", "track_id", "track_layout")


def _motec_group_key(record: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    car = record.get("car") if isinstance(record.get("car"), dict) else {}
    track = record.get("track") if isinstance(record.get("track"), dict) else {}
    return (
        record.get("session_uuid"),
        car.get("id"),
        track.get("id"),
        track.get("layout"),
    )


def _format_motec_group_key(key: tuple[Any, Any, Any, Any]) -> str:
    return ", ".join(
        f"{name}={_format_cell(value) or '<blank>'}"
        for name, value in zip(_MOTEC_GROUP_FIELDS, key, strict=True)
    )


def _validate_motec_group(
    path: Path,
    key: tuple[Any, Any, Any, Any],
    expected: tuple[Any, Any, Any, Any],
) -> None:
    if key == expected:
        return
    raise LapArchiveExportError(
        f"{path}: motec-csv inputs must contain one session/car/track; "
        f"first archive is {_format_motec_group_key(expected)}, "
        f"this archive is {_format_motec_group_key(key)}"
    )


def _trace_duration_s(record: dict[str, Any]) -> float:
    fields = _field_map(record)
    samples = record.get("trace", {}).get("samples", [])
    max_elapsed_ms = max(
        (
            value
            for sample in samples
            if (value := _sample_value(sample, fields, "eMs")) is not None
        ),
        default=None,
    )
    if max_elapsed_ms is None or max_elapsed_ms <= 0:
        return 0.0
    return max_elapsed_ms / 1000.0


def _lap_duration_s(record: dict[str, Any]) -> float:
    lap = record.get("lap") if isinstance(record.get("lap"), dict) else {}
    lap_ms = _as_finite_float(lap.get("lap_ms"))
    if lap_ms is not None and lap_ms > 0:
        return lap_ms / 1000.0
    return _trace_duration_s(record)


def _lap_export_duration_s(record: dict[str, Any]) -> float:
    return _trace_duration_s(record)


def _iter_motec_archive_rows(
    archive: tuple[Path, dict[str, Any]],
    *,
    offset_s: float,
) -> Iterator[dict[str, Any]]:
    record = archive[1]
    lap_time_s = _lap_duration_s(record)
    for row in iter_csv_rows([archive]):
        motec = dict(row)
        raw_time = _as_finite_float(row.get("time_s"))
        if raw_time is None:
            continue
        motec["time_s"] = offset_s + raw_time
        brake = _as_finite_float(row.get("brake"))
        throttle = _as_finite_float(row.get("throttle"))
        motec["brake_pct"] = brake * 100.0 if brake is not None else None
        motec["throttle_pct"] = throttle * 100.0 if throttle is not None else None
        motec["lap_time_s"] = lap_time_s if lap_time_s > 0 else None
        motec["valid_lap"] = 1 if row.get("is_valid") is True else 0
        yield motec


def _iter_motec_rows(
    archives: Iterable[tuple[Path, dict[str, Any]]],
) -> Iterator[dict[str, Any]]:
    offset_s = 0.0
    for archive in archives:
        record = archive[1]
        yield from _iter_motec_archive_rows(archive, offset_s=offset_s)
        offset_s += _lap_export_duration_s(record)


def _scan_motec_archives(archives: Iterable[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    first_archive: tuple[Path, dict[str, Any]] | None = None
    expected_key: tuple[Any, Any, Any, Any] | None = None
    beacon_markers: list[float] = []
    offset_s = 0.0
    row_count = 0
    finite_time_count = 0
    first_time_s: float | None = None
    last_time_s: float | None = None
    end_time_s = 0.0
    end_distance_m = 0.0

    for archive in archives:
        path, record = archive
        key = _motec_group_key(record)
        if expected_key is None:
            expected_key = key
            first_archive = archive
        else:
            _validate_motec_group(path, key, expected_key)

        for row in _iter_motec_archive_rows(archive, offset_s=offset_s):
            row_count += 1
            time_s = _as_finite_float(row.get("time_s"))
            if time_s is not None:
                if first_time_s is None:
                    first_time_s = time_s
                last_time_s = time_s
                end_time_s = max(end_time_s, time_s)
                finite_time_count += 1
            distance_m = _as_finite_float(row.get("lap_distance_m"))
            if distance_m is not None:
                end_distance_m = max(end_distance_m, distance_m)

        duration_s = _lap_export_duration_s(record)
        if duration_s > 0 and row_count > 0:
            beacon_markers.append(offset_s + duration_s)
        offset_s += duration_s

    sample_rate_hz = None
    if (
        first_time_s is not None
        and last_time_s is not None
        and finite_time_count >= 2
        and last_time_s > first_time_s
    ):
        sample_rate_hz = (finite_time_count - 1) / (last_time_s - first_time_s)

    return {
        "first_archive": first_archive,
        "row_count": row_count,
        "end_time_s": end_time_s,
        "end_distance_m": end_distance_m,
        "sample_rate_hz": sample_rate_hz,
        "beacon_markers": beacon_markers,
    }


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
    paths = list(iter_lap_archive_paths(inputs))
    stats = _scan_motec_archives(_iter_loaded_archives(paths, include_invalid=include_invalid))
    output_path = _resolve_output_path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    rows_written = 0
    try:
        with _open_temporary_output(output_path) as fh:
            tmp_path = Path(fh.name)
            writer = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
            first_archive = stats.get("first_archive")
            for header_row in _motec_header(first_archive, stats):
                writer.writerow([_format_cell(value) for value in header_row])
            writer.writerow([name for name, _, _ in _MOTEC_CHANNELS])
            writer.writerow([unit for _, unit, _ in _MOTEC_CHANNELS])
            archives = _iter_loaded_archives(paths, include_invalid=include_invalid)
            for row in _iter_motec_rows(archives):
                writer.writerow([_format_cell(row.get(key)) for _, _, key in _MOTEC_CHANNELS])
                rows_written += 1
        assert tmp_path is not None
        tmp_path.replace(output_path)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise
    return rows_written


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
