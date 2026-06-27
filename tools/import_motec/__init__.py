"""MoTeC CSV importer for AC Copilot Trainer lap archive records.

The importer is intentionally stdlib-only: it converts a MoTeC-style CSV into
the same schema-v1 JSON records written by ``modules/lap_archive.lua`` so the
Lua app has one lap/reference format to consume.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TRACE_FIELDS = ["spline", "speed", "eMs", "throttle", "brake", "steer", "gear", "px", "py", "pz"]
DEFAULT_SAMPLE_COUNT = 2000

CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "time": (
        "time",
        "times",
        "timestamp",
        "elapsedtime",
        "laptime",
        "timeelapsed",
    ),
    "distance": (
        "distance",
        "dist",
        "distancem",
        "distance_m",
        "lapdistance",
        "lapdistancem",
        "s",
    ),
    "spline": (
        "spline",
        "splineposition",
        "normalizeddistance",
        "lapdistancepct",
        "lapdistancepercent",
    ),
    "speed": ("speed", "speedkmh", "speed_kmh", "vehiclespeed", "gpsspeed", "v"),
    "throttle": (
        "throttle",
        "throttlepct",
        "throttlepercent",
        "throttleposition",
        "throttlepos",
        "tps",
    ),
    "brake": ("brake", "brakepct", "brakepercent", "brakepressure", "brakepedal", "bps"),
    "steer": (
        "steer",
        "steering",
        "steeringangle",
        "steering_angle",
        "steerangle",
        "steerangledeg",
        "sa",
    ),
    "gear": ("gear", "gearnumber", "selectedgear"),
    "lap": ("lap", "lapnumber", "lapno", "lapnum"),
    "px": ("px", "posx", "positionx", "worldx", "x"),
    "py": ("py", "posy", "positiony", "worldy", "y"),
    "pz": ("pz", "posz", "positionz", "worldz", "z"),
}

REQUIRED_CHANNELS = ("speed", "throttle", "brake", "steer", "gear")


class MotecImportError(ValueError):
    """Raised for user-correctable CSV/import problems."""


@dataclass(frozen=True)
class ImportOptions:
    car: str
    track: str
    layout: str | None = None
    output_dir: Path | None = None
    csp_state_dir: Path | None = None
    track_length_m: float | None = None
    sample_count: int = DEFAULT_SAMPLE_COUNT
    steering_lock_deg: float = 450.0
    speed_unit: str = "auto"


@dataclass(frozen=True)
class ImportResult:
    path: Path
    lap_ms: int
    samples_count: int
    lap_number: int


@dataclass(frozen=True)
class ParsedCsv:
    header: list[str]
    units: list[str]
    mapping: dict[str, int]
    rows: list[list[str]]


def _norm_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.strip().lower())


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("%"):
        s = s[:-1].strip()
    if "," in s and "." not in s and s.count(",") == 1:
        s = s.replace(",", ".")
    try:
        out = float(s)
    except ValueError:
        return None
    if not math.isfinite(out):
        return None
    return out


def _parse_time_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    direct = _parse_float(s)
    if direct is not None:
        return direct
    parts = s.split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        nums = [float(p.replace(",", ".")) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        minutes, seconds = nums
        return minutes * 60.0 + seconds
    hours, minutes, seconds = nums
    return hours * 3600.0 + minutes * 60.0 + seconds


def _parse_gear(value: str | None) -> int:
    if value is None:
        return 0
    s = str(value).strip().upper()
    if s == "R":
        return -1
    if s == "N":
        return 0
    n = _parse_float(s)
    if n is None:
        return 0
    return int(round(n))


def _channel_mapping(header: list[str]) -> dict[str, int]:
    normalized = {_norm_header(name): idx for idx, name in enumerate(header)}
    mapping: dict[str, int] = {}
    for channel, aliases in CHANNEL_ALIASES.items():
        for alias in aliases:
            key = _norm_header(alias)
            if key in normalized:
                mapping[channel] = normalized[key]
                break
    return mapping


def _mapping_ok(mapping: dict[str, int]) -> bool:
    has_position = "distance" in mapping or "spline" in mapping
    return has_position and all(ch in mapping for ch in REQUIRED_CHANNELS)


def _looks_like_units(row: list[str], mapping: dict[str, int]) -> bool:
    if not row:
        return False
    unitish = 0
    nonnumeric = 0
    for idx in set(mapping.values()):
        if idx >= len(row):
            continue
        raw = row[idx].strip().lower()
        if not raw:
            continue
        if _parse_float(raw) is None:
            nonnumeric += 1
        if any(token in raw for token in ("%", "deg", "rad", "km/h", "kph", "m/s", "mph", "s")):
            unitish += 1
    return nonnumeric >= 2 and unitish >= 1


def parse_motec_csv(path: Path) -> ParsedCsv:
    rows: list[list[str]]
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = [row for row in csv.reader(fh) if any(cell.strip() for cell in row)]
    except UnicodeDecodeError:
        with path.open("r", encoding="cp1252", newline="") as fh:
            rows = [row for row in csv.reader(fh) if any(cell.strip() for cell in row)]

    for i, row in enumerate(rows):
        mapping = _channel_mapping(row)
        if _mapping_ok(mapping):
            units: list[str] = []
            data_start = i + 1
            if data_start < len(rows) and _looks_like_units(rows[data_start], mapping):
                units = rows[data_start]
                data_start += 1
            return ParsedCsv(header=row, units=units, mapping=mapping, rows=rows[data_start:])

    required = "distance/spline plus speed, throttle, brake, steer, and gear columns"
    raise MotecImportError(f"could not find a header row with {required}")


def _cell(row: list[str], idx: int | None) -> str | None:
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _unit(parsed: ParsedCsv, channel: str) -> str:
    idx = parsed.mapping.get(channel)
    if idx is None or idx >= len(parsed.units):
        name = parsed.header[idx] if idx is not None and idx < len(parsed.header) else ""
        return name.lower()
    return f"{parsed.header[idx]} {parsed.units[idx]}".lower()


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _normalize_pedal(value: float, max_abs: float, unit: str) -> float:
    if "%" in unit or max_abs > 1.5:
        value = value / 100.0
    return _clamp(value, 0.0, 1.0)


def _normalize_speed(value: float, unit: str, override: str) -> float:
    mode = override.lower()
    if mode == "mph" or (mode == "auto" and "mph" in unit):
        return value * 1.609344
    if mode in {"mps", "m/s"} or (mode == "auto" and ("m/s" in unit or "ms-1" in unit)):
        return value * 3.6
    return value


def _normalize_steer(value: float, max_abs: float, unit: str, steering_lock_deg: float) -> float:
    if "rad" in unit:
        value = math.degrees(value)
    elif max_abs <= 1.2:
        return _clamp(value, -1.0, 1.0)
    elif max_abs <= math.tau + 0.25 and "deg" not in unit:
        value = math.degrees(value)
    lock = steering_lock_deg if steering_lock_deg > 0 else 450.0
    return _clamp(value / lock, -1.0, 1.0)


def _group_rows(parsed: ParsedCsv) -> list[tuple[int, list[list[str]]]]:
    lap_idx = parsed.mapping.get("lap")
    if lap_idx is None:
        return [(1, parsed.rows)]
    ordered: list[tuple[int, list[list[str]]]] = []
    by_key: dict[int, list[list[str]]] = {}
    for row in parsed.rows:
        lap_raw = _parse_float(_cell(row, lap_idx))
        lap_no = int(lap_raw) if lap_raw is not None else 1
        if lap_no not in by_key:
            by_key[lap_no] = []
            ordered.append((lap_no, by_key[lap_no]))
        by_key[lap_no].append(row)
    return ordered


def _interpolate(points: list[dict[str, float]], target: float, field: str) -> float:
    if target <= points[0]["spline"]:
        return points[0][field]
    if target >= points[-1]["spline"]:
        return points[-1][field]
    lo = 0
    hi = len(points) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if points[mid]["spline"] <= target:
            lo = mid
        else:
            hi = mid
    a = points[lo]
    b = points[hi]
    span = b["spline"] - a["spline"]
    if span <= 0:
        return a[field]
    frac = (target - a["spline"]) / span
    return a[field] + (b[field] - a[field]) * frac


def _integrated_elapsed_ms(points: list[dict[str, float]], track_length_m: float) -> None:
    elapsed = 0.0
    points[0]["eMs"] = 0.0
    for i in range(1, len(points)):
        prev = points[i - 1]
        cur = points[i]
        ds = max(0.0, cur["spline"] - prev["spline"]) * track_length_m
        speed_kmh = max(1.0, (prev["speed"] + cur["speed"]) * 0.5)
        elapsed += (ds / (speed_kmh / 3.6)) * 1000.0
        cur["eMs"] = elapsed


def _resample(points: list[dict[str, float]], sample_count: int) -> list[list[float]]:
    out: list[list[float]] = []
    count = max(2, sample_count)
    for i in range(count):
        target = i / count
        row: list[float] = []
        for field in TRACE_FIELDS:
            value = _interpolate(points, target, field)
            if field == "gear":
                value = int(round(value))
            row.append(value)
        out.append(row)
    return out


def _points_for_lap(
    parsed: ParsedCsv, rows: list[list[str]], opts: ImportOptions
) -> list[dict[str, float]]:
    m = parsed.mapping
    raw: list[dict[str, float]] = []
    max_throttle = 0.0
    max_brake = 0.0
    max_steer = 0.0
    for row in rows:
        speed = _parse_float(_cell(row, m.get("speed")))
        throttle = _parse_float(_cell(row, m.get("throttle")))
        brake = _parse_float(_cell(row, m.get("brake")))
        steer = _parse_float(_cell(row, m.get("steer")))
        gear = _parse_gear(_cell(row, m.get("gear")))
        pos = _parse_float(_cell(row, m.get("spline")))
        distance = _parse_float(_cell(row, m.get("distance")))
        if speed is None or throttle is None or brake is None or steer is None:
            continue
        if pos is None and distance is None:
            continue
        max_throttle = max(max_throttle, abs(throttle))
        max_brake = max(max_brake, abs(brake))
        max_steer = max(max_steer, abs(steer))
        raw.append(
            {
                "raw_pos": pos if pos is not None else distance,
                "raw_distance": distance,
                "speed": speed,
                "throttle": throttle,
                "brake": brake,
                "steer": steer,
                "gear": float(gear),
                "px": _parse_float(_cell(row, m.get("px"))) or 0.0,
                "py": _parse_float(_cell(row, m.get("py"))) or 0.0,
                "pz": _parse_float(_cell(row, m.get("pz"))) or 0.0,
                "time_s": _parse_time_seconds(_cell(row, m.get("time"))),
            }
        )

    if len(raw) < 2:
        raise MotecImportError("lap has fewer than two usable telemetry rows")

    if "spline" in m and "distance" not in m:
        pos_values = [p["raw_pos"] for p in raw]
        max_pos = max(pos_values)
        min_pos = min(pos_values)
        if max_pos > 1.5 or min_pos < -0.05:
            span = max_pos - min_pos
            if span <= 0:
                raise MotecImportError("spline/distance column has no usable span")
            for p in raw:
                p["spline"] = _clamp((p["raw_pos"] - min_pos) / span, 0.0, 1.0)
            track_length = opts.track_length_m or span
        else:
            for p in raw:
                p["spline"] = _clamp(p["raw_pos"], 0.0, 1.0)
            track_length = opts.track_length_m or 1.0
    else:
        distances = [
            p["raw_distance"] if p["raw_distance"] is not None else p["raw_pos"] for p in raw
        ]
        start = min(distances)
        span = opts.track_length_m or (max(distances) - start)
        if span <= 0:
            raise MotecImportError("distance column has no usable span; pass --track-length")
        for p, d in zip(raw, distances, strict=True):
            p["spline"] = _clamp((d - start) / span, 0.0, 1.0)
        track_length = span

    throttle_unit = _unit(parsed, "throttle")
    brake_unit = _unit(parsed, "brake")
    steer_unit = _unit(parsed, "steer")
    speed_unit = _unit(parsed, "speed")
    time_values = [p["time_s"] for p in raw if p["time_s"] is not None]
    time_origin = min(time_values) if time_values else None

    points: list[dict[str, float]] = []
    for p in raw:
        e_ms = 0.0
        if p["time_s"] is not None and time_origin is not None:
            e_ms = max(0.0, (p["time_s"] - time_origin) * 1000.0)
        points.append(
            {
                "spline": p["spline"],
                "speed": _normalize_speed(p["speed"], speed_unit, opts.speed_unit),
                "eMs": e_ms,
                "throttle": _normalize_pedal(p["throttle"], max_throttle, throttle_unit),
                "brake": _normalize_pedal(p["brake"], max_brake, brake_unit),
                "steer": _normalize_steer(
                    p["steer"], max_steer, steer_unit, opts.steering_lock_deg
                ),
                "gear": p["gear"],
                "px": p["px"],
                "py": p["py"],
                "pz": p["pz"],
            }
        )

    points.sort(key=lambda item: item["spline"])
    deduped: list[dict[str, float]] = []
    for p in points:
        if deduped and abs(deduped[-1]["spline"] - p["spline"]) < 1e-9:
            deduped[-1] = p
        else:
            deduped.append(p)
    if len(deduped) < 2:
        raise MotecImportError("lap has fewer than two unique spline positions")
    if not time_values:
        _integrated_elapsed_ms(deduped, track_length)
    return deduped


def _record_for_lap(
    samples: list[list[float]],
    opts: ImportOptions,
    *,
    lap_ms: int,
    lap_number: int,
    session_uuid: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "imported",
        "import_format": "motec_csv",
        "lap_uuid": uuid.uuid4().hex[:16],
        "session_uuid": session_uuid,
        "exported_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "car": {"id": opts.car, "displayName": None},
        "track": {"id": opts.track, "layout": opts.layout, "lengthM": opts.track_length_m},
        "conditions": {
            "trackGripLevel": None,
            "ambientTempC": None,
            "trackTempC": None,
            "weatherType": None,
        },
        "lap": {"lap_n": lap_number, "lap_ms": lap_ms, "is_pb": False, "is_valid": True},
        "setup": {"hash": "", "path": None, "snapshot": {}},
        "trace": {
            "samples_count": len(samples),
            "fields": TRACE_FIELDS,
            "samples": samples,
        },
        "corners": [],
        "coaching": {"rules_hints": [], "sidecar_debrief": None, "corner_advice_used": None},
    }


def _use_windows_ac_default() -> bool:
    return os.name == "nt"


def default_output_dir(opts: ImportOptions) -> Path:
    env_laps = os.environ.get("AC_COPILOT_LAP_ARCHIVE_DIR")
    if env_laps:
        return Path(env_laps)
    csp_state = opts.csp_state_dir or (
        Path(os.environ["AC_COPILOT_CSP_STATE_DIR"])
        if os.environ.get("AC_COPILOT_CSP_STATE_DIR")
        else None
    )
    if csp_state is not None:
        return csp_state / "ac_copilot_trainer" / "journal" / "laps"
    if _use_windows_ac_default():
        docs = Path.home() / "Documents" / "Assetto Corsa"
        candidate = (
            docs
            / "cfg"
            / "extension"
            / "state"
            / "lua"
            / "app"
            / "AC_Copilot_Trainer"
            / "ac_copilot_trainer"
            / "journal"
            / "laps"
        )
        return candidate
    return Path.cwd() / "journal" / "laps"


def import_file(input_csv: Path, opts: ImportOptions) -> list[ImportResult]:
    parsed = parse_motec_csv(input_csv)
    output_dir = opts.output_dir or default_output_dir(opts)
    output_dir.mkdir(parents=True, exist_ok=True)
    session_uuid = uuid.uuid4().hex[:12]
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    results: list[ImportResult] = []

    for ordinal, (lap_number, rows) in enumerate(_group_rows(parsed), start=1):
        points = _points_for_lap(parsed, rows, opts)
        samples = _resample(points, opts.sample_count)
        lap_ms = int(round(max(row[2] for row in samples)))
        record = _record_for_lap(
            samples,
            opts,
            lap_ms=lap_ms,
            lap_number=lap_number if lap_number > 0 else ordinal,
            session_uuid=session_uuid,
        )
        lap_key = f"{lap_number if lap_number > 0 else ordinal:02d}"
        filename = f"lap_imported_{timestamp}_{session_uuid}_motec_{lap_ms}_{lap_key}.json"
        path = output_dir / filename
        path.write_text(
            json.dumps(record, separators=(",", ":"), allow_nan=False), encoding="utf-8"
        )
        results.append(
            ImportResult(
                path=path, lap_ms=lap_ms, samples_count=len(samples), lap_number=lap_number
            )
        )
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a MoTeC CSV as AC Copilot lap archive JSON"
    )
    parser.add_argument("input_csv", type=Path)
    parser.add_argument(
        "--car", required=True, help="Assetto Corsa car id, e.g. ks_porsche_911_gt3_rs"
    )
    parser.add_argument("--track", required=True, help="Assetto Corsa track id, e.g. ks_magione")
    parser.add_argument("--layout", default=None, help="Optional AC track layout id")
    parser.add_argument(
        "--output-dir", type=Path, default=None, help="Destination journal/laps directory"
    )
    parser.add_argument(
        "--csp-state-dir",
        type=Path,
        default=None,
        help="CSP ScriptConfig app dir; appends ac_copilot_trainer/journal/laps",
    )
    parser.add_argument(
        "--track-length",
        dest="track_length_m",
        type=float,
        default=None,
        help="Track length in meters. Defaults to the distance column span.",
    )
    parser.add_argument("--samples", dest="sample_count", type=int, default=DEFAULT_SAMPLE_COUNT)
    parser.add_argument("--steering-lock-deg", type=float, default=450.0)
    parser.add_argument(
        "--speed-unit", choices=("auto", "kmh", "mph", "mps", "m/s"), default="auto"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    opts = ImportOptions(
        car=args.car,
        track=args.track,
        layout=args.layout,
        output_dir=args.output_dir,
        csp_state_dir=args.csp_state_dir,
        track_length_m=args.track_length_m,
        sample_count=args.sample_count,
        steering_lock_deg=args.steering_lock_deg,
        speed_unit=args.speed_unit,
    )
    try:
        results = import_file(args.input_csv, opts)
    except MotecImportError as exc:
        parser.exit(2, f"import_motec: {exc}\n")
    for result in results:
        detail = (
            f"{result.path} lap={result.lap_number} "
            f"lap_ms={result.lap_ms} samples={result.samples_count}"
        )
        print(detail)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
