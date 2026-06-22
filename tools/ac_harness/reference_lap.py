"""Generated reference-lap archive adapter for issue #116.

The trainer's durable lap data shape is the Lua ``lap_archive`` schema v1:
columnar telemetry samples under ``trace`` plus lap, car, track, setup, corner,
and coaching metadata. This module gives offline generators a Python-side seam
for emitting that exact shape without Assetto Corsa, GPU training, or optional
RL dependencies.

The default CLI generator uses the existing deterministic synthetic traces from
``trace_replay``. A future TUMFTM/CommonRoad adapter should feed its frames into
``build_archive_record`` and inherit the same schema validator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.ac_harness.trace_replay import available_scenarios, synthesize_trace

TRACE_FIELDS: tuple[str, ...] = (
    "spline",
    "speed",
    "eMs",
    "throttle",
    "brake",
    "steer",
    "gear",
    "px",
    "py",
    "pz",
    # Per-wheel channels (issue #266) — MUST stay identical to lap_archive.lua::TRACE_FIELDS.
    # Order: FL, FR, RL, RR. angularSpeed (rad/s) is the canonical longitudinal slip source;
    # slip (AC ndSlip) is secondary; tyre core temp (degC) feeds the tyre thermal model.
    "wheelAngularSpeed_fl",
    "wheelAngularSpeed_fr",
    "wheelAngularSpeed_rl",
    "wheelAngularSpeed_rr",
    "wheelSlip_fl",
    "wheelSlip_fr",
    "wheelSlip_rl",
    "wheelSlip_rr",
    "tyreCoreTemp_fl",
    "tyreCoreTemp_fr",
    "tyreCoreTemp_rl",
    "tyreCoreTemp_rr",
)

SCHEMA_VERSION = 1
GENERATED_IMPORT_FORMAT = "generated_reference_v1"
DEFAULT_TRACK_LENGTH_M = 4500.0


class LapArchiveSchemaError(ValueError):
    """Raised when a generated archive record does not match schema v1."""


def _finite_float(raw: Any, field: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise LapArchiveSchemaError(f"{field} must be numeric, got {raw!r}") from exc
    if not math.isfinite(value):
        raise LapArchiveSchemaError(f"{field} must be finite, got {raw!r}")
    return value


def _stable_id(prefix: str, rows: Sequence[Sequence[float]]) -> str:
    payload = json.dumps(rows, separators=(",", ":"), sort_keys=False)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


#: The original required trace columns. Fields beyond these (the per-wheel #266 channels) are
#: OPTIONAL and default to 0.0 when a frame omits them, so hand-built / pre-#266 traces stay valid.
_REQUIRED_TRACE_FIELDS: tuple[str, ...] = TRACE_FIELDS[:10]


def _normalize_trace_frame(frame: Mapping[str, Any], index: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for field in TRACE_FIELDS:
        raw = frame.get(field)
        # Optional per-wheel channels default to 0.0 whether absent OR explicitly null — both mean
        # "no reading this frame", the desired graceful degradation. A REQUIRED field that is
        # absent/None still falls through to _finite_float, which raises (a real schema violation).
        if raw is None and field not in _REQUIRED_TRACE_FIELDS:
            out[field] = 0.0
        else:
            out[field] = _finite_float(raw, f"trace[{index}].{field}")
    if out["spline"] < 0.0 or out["spline"] > 1.0:
        raise LapArchiveSchemaError(f"trace[{index}].spline must be in [0, 1]")
    return out


def trace_to_columns(frames: Iterable[Mapping[str, Any]]) -> list[list[float]]:
    """Convert object-style trace frames to lap-archive column rows."""
    rows: list[list[float]] = []
    last_elapsed = -math.inf
    for index, frame in enumerate(frames):
        normalized = _normalize_trace_frame(frame, index)
        elapsed = normalized["eMs"]
        if elapsed < last_elapsed:
            raise LapArchiveSchemaError("trace eMs must be monotonic nondecreasing")
        last_elapsed = elapsed
        rows.append([normalized[field] for field in TRACE_FIELDS])
    if len(rows) < 2:
        raise LapArchiveSchemaError("reference trace needs at least two samples")
    return rows


def _first_brake_corner(rows: Sequence[Sequence[float]]) -> dict[str, Any] | None:
    brake_idx = TRACE_FIELDS.index("brake")
    speed_idx = TRACE_FIELDS.index("speed")
    spline_idx = TRACE_FIELDS.index("spline")
    throttle_idx = TRACE_FIELDS.index("throttle")
    steer_idx = TRACE_FIELDS.index("steer")
    for i, row in enumerate(rows):
        if row[brake_idx] < 0.3:
            continue
        braking = rows[i:]
        release_offset = len(braking)
        for candidate_offset, candidate in enumerate(braking[1:], start=1):
            if candidate[brake_idx] < 0.1:
                release_offset = candidate_offset
                break
        window = braking[:release_offset]
        speeds = [candidate[speed_idx] for candidate in window]
        brake_values = [candidate[brake_idx] for candidate in window]
        steer_values = [candidate[steer_idx] for candidate in window]
        throttle_values = [candidate[throttle_idx] for candidate in window]
        max_brake = max(brake_values)
        avg_brake = sum(brake_values) / len(brake_values)
        return {
            "label": "T1",
            "entrySpeed": row[speed_idx],
            "minSpeed": min(speeds),
            "exitSpeed": speeds[-1],
            "brakePointSpline": row[spline_idx],
            "trailBrakeRatio": 0.0 if max_brake <= 1e-6 else min(1.0, avg_brake / max_brake),
            "throttleAvg": sum(throttle_values) / len(throttle_values),
            "steerReversals": 0,
            "tractionCircleProxy": max(abs(value) for value in steer_values),
        }
    return None


def build_archive_record(
    frames: Iterable[Mapping[str, Any]],
    *,
    car_id: str = "generated_car",
    track_id: str = "generated_track",
    track_length_m: float = DEFAULT_TRACK_LENGTH_M,
    lap_n: int = 1,
    exported_at: str | None = None,
    lap_uuid: str | None = None,
    session_uuid: str | None = None,
    generator_name: str = "ac_harness.reference_lap",
) -> dict[str, Any]:
    """Build one generated-reference lap archive record.

    ``frames`` are object traces with keys matching :data:`TRACE_FIELDS`. The
    returned record is schema v1 and can be written as ``lap_*.json`` or
    converted to the trainer persistence payload via
    :func:`build_trainer_reference_payload`.
    """
    rows = trace_to_columns(frames)
    lap_ms = int(round(rows[-1][TRACE_FIELDS.index("eMs")]))
    if lap_ms <= 0:
        raise LapArchiveSchemaError("lap_ms must be positive")
    record = {
        "schema_version": SCHEMA_VERSION,
        "source": "imported",
        "import_format": GENERATED_IMPORT_FORMAT,
        "lap_uuid": lap_uuid or _stable_id("lap", rows),
        "session_uuid": session_uuid or _stable_id("generated-session", rows[:8]),
        "exported_at": exported_at or _iso_now(),
        "car": {"id": car_id, "displayName": None},
        "track": {
            "id": track_id,
            "layout": None,
            "lengthM": _finite_float(track_length_m, "track_length_m"),
        },
        "conditions": {
            "trackGripLevel": None,
            "ambientTempC": None,
            "trackTempC": None,
            "weatherType": None,
        },
        "lap": {
            "lap_n": int(lap_n),
            "lap_ms": lap_ms,
            "is_pb": True,
            "is_valid": True,
        },
        "setup": {"hash": "", "path": None, "snapshot": {}},
        "trace": {
            "samples_count": len(rows),
            "fields": list(TRACE_FIELDS),
            "samples": rows,
        },
        "corners": [],
        "coaching": {
            "rules_hints": [
                "Generated reference lap seed; validate in-sim before treating as driver truth."
            ],
            "sidecar_debrief": None,
            "corner_advice_used": None,
        },
        "generator": {
            "name": generator_name,
            "version": 1,
            "decision_issue": 116,
        },
    }
    corner = _first_brake_corner(rows)
    if corner is not None:
        record["corners"].append(corner)
    validate_lap_archive_record(record)
    return record


def build_archive_record_from_scenario(
    scenario: str = "brake_too_late",
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a schema v1 archive record from a deterministic harness scenario."""
    frames = synthesize_trace(scenario)
    return build_archive_record(frames, generator_name=f"trace_replay:{scenario}", **kwargs)


def validate_lap_archive_record(record: Mapping[str, Any]) -> None:
    """Raise :class:`LapArchiveSchemaError` unless ``record`` matches schema v1."""
    if record.get("schema_version") != SCHEMA_VERSION:
        raise LapArchiveSchemaError("schema_version must be 1")
    if record.get("source") not in {"in_game", "imported"}:
        raise LapArchiveSchemaError("source must be 'in_game' or 'imported'")
    if record.get("source") == "imported" and not isinstance(record.get("import_format"), str):
        raise LapArchiveSchemaError("imported records require string import_format")
    for key in (
        "lap_uuid",
        "session_uuid",
        "exported_at",
        "car",
        "track",
        "lap",
        "setup",
        "trace",
        "coaching",
        "corners",
    ):
        if key not in record:
            raise LapArchiveSchemaError(f"missing top-level key: {key}")

    lap = record["lap"]
    if not isinstance(lap, Mapping):
        raise LapArchiveSchemaError("lap must be an object")
    lap_ms = _finite_float(lap.get("lap_ms"), "lap.lap_ms")
    if lap_ms <= 0:
        raise LapArchiveSchemaError("lap.lap_ms must be positive")

    trace = record["trace"]
    if not isinstance(trace, Mapping):
        raise LapArchiveSchemaError("trace must be an object")
    fields = trace.get("fields")
    # Accept the pre-#266 10-field trace AND the per-wheel-extended set: SCHEMA_VERSION is still 1
    # and existing archives carry only the required columns. A valid trace is the required columns,
    # optionally followed by the #266 per-wheel channels (exact, in order).
    if fields not in (list(_REQUIRED_TRACE_FIELDS), list(TRACE_FIELDS)):
        raise LapArchiveSchemaError(
            f"trace.fields must be {list(_REQUIRED_TRACE_FIELDS)!r} or {list(TRACE_FIELDS)!r}"
        )
    samples = trace.get("samples")
    if not isinstance(samples, list):
        raise LapArchiveSchemaError("trace.samples must be a list")
    if len(samples) < 2:
        raise LapArchiveSchemaError("trace.samples must contain at least two rows")
    if trace.get("samples_count") != len(samples):
        raise LapArchiveSchemaError("trace.samples_count must equal len(trace.samples)")
    last_elapsed = -math.inf
    # Row width must match the DECLARED fields (10 pre-#266, 22 with per-wheel channels).
    n_cols = len(fields)
    for row_index, row in enumerate(samples):
        if not isinstance(row, list) or len(row) != n_cols:
            raise LapArchiveSchemaError(f"trace.samples[{row_index}] must have {n_cols} columns")
        for field_index, value in enumerate(row):
            parsed = _finite_float(value, f"trace.samples[{row_index}][{field_index}]")
            if fields[field_index] == "spline" and (parsed < 0.0 or parsed > 1.0):
                raise LapArchiveSchemaError(f"trace.samples[{row_index}].spline must be in [0, 1]")
            if fields[field_index] == "eMs":
                if parsed < last_elapsed:
                    raise LapArchiveSchemaError("trace eMs must be monotonic nondecreasing")
                last_elapsed = parsed
    if abs(lap_ms - round(last_elapsed)) > 1.0:
        raise LapArchiveSchemaError("lap.lap_ms must match final trace eMs")

    corners = record["corners"]
    if not isinstance(corners, list):
        raise LapArchiveSchemaError("corners must be a list")


def archive_trace_to_object_trace(record: Mapping[str, Any]) -> list[dict[str, float]]:
    """Convert archive column rows into the live trainer's ``bestLapTrace`` shape."""
    validate_lap_archive_record(record)
    rows = record["trace"]["samples"]
    frames: list[dict[str, float]] = []
    for row in rows:
        frame = {field: float(row[i]) for i, field in enumerate(TRACE_FIELDS)}
        frame["gear"] = int(frame["gear"])
        frames.append(frame)
    return frames


def _nearest_frame(frames: Sequence[Mapping[str, float]], spline: float) -> Mapping[str, float]:
    return min(frames, key=lambda frame: abs(float(frame["spline"]) - spline))


def _brake_points_from_corners(
    record: Mapping[str, Any],
    frames: Sequence[Mapping[str, float]],
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    corners = record.get("corners", [])
    if not isinstance(corners, list):
        return points
    for corner in corners:
        if not isinstance(corner, Mapping):
            continue
        raw_spline = corner.get("brakePointSpline")
        raw_entry = corner.get("entrySpeed")
        if raw_spline is None or raw_entry is None:
            continue
        spline = _finite_float(raw_spline, "corner.brakePointSpline")
        entry = _finite_float(raw_entry, "corner.entrySpeed")
        nearest = _nearest_frame(frames, spline)
        point: dict[str, Any] = {
            "spline": spline,
            "px": float(nearest["px"]),
            "py": float(nearest["py"]),
            "pz": float(nearest["pz"]),
            "entrySpeed": entry,
            "heading": 0.0,
        }
        label = corner.get("label")
        if isinstance(label, str) and label:
            point["label"] = label
        points.append(point)
    return points


def build_trainer_reference_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build the live trainer persistence fragment for a generated reference.

    The app currently loads ``bestLapTrace`` from its per-car/track persistence
    JSON and archives completed laps separately. This function is the explicit
    bridge: a future importer can merge this payload into the persistence file
    while keeping the source archive record immutable.
    """
    frames = archive_trace_to_object_trace(record)
    lap = record["lap"]
    lap_ms = int(round(_finite_float(lap.get("lap_ms"), "lap.lap_ms")))
    corners = record.get("corners", [])
    return {
        "bestReferenceLapMs": lap_ms,
        "bestLapTrace": frames,
        "bestBrakePoints": _brake_points_from_corners(record, frames),
        "bestCornerFeatures": corners if isinstance(corners, list) else [],
    }


def _json_text(payload: Mapping[str, Any], *, pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=available_scenarios(), default="brake_too_late")
    parser.add_argument("--car-id", default="generated_car")
    parser.add_argument("--track-id", default="generated_track")
    parser.add_argument("--track-length-m", type=float, default=DEFAULT_TRACK_LENGTH_M)
    parser.add_argument("--lap-n", type=int, default=1)
    parser.add_argument(
        "--emit",
        choices=("archive", "trainer-state"),
        default="archive",
        help="archive emits lap_archive schema v1; trainer-state emits the persistence fragment.",
    )
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout.")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    record = build_archive_record_from_scenario(
        args.scenario,
        car_id=args.car_id,
        track_id=args.track_id,
        track_length_m=args.track_length_m,
        lap_n=args.lap_n,
    )
    payload = build_trainer_reference_payload(record) if args.emit == "trainer-state" else record
    text = _json_text(payload, pretty=args.pretty)
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
