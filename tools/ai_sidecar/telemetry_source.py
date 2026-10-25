"""Telemetry source: feed the sidecar's ``telemetry_tick`` contract so the M0 voice loop can run.

The producer side of the M0 voice-coaching slice (#341). The in-game Lua app emits
``telemetry_tick`` at ~20 Hz via :mod:`telemetry_publisher` (spline + lap on the wire); the Python
replay/shared-memory sources below remain for offline CI and rig fallback:

* **replay** (offline, CI-tested core): stream a stored lap archive as ``telemetry_tick`` frames so
  the whole spine (frame -> observer -> ``coaching.cue`` -> voice) is validated without the rig. Run
  the sidecar with a FASTER ``--reference-archive`` and replay a SLOWER lap to HEAR the cues.
* **live** (rig step, pragma-guarded): read AC shared memory at ~20 Hz and emit the same contract so
  a human can DRIVE and hear cues. Reuses the parsers in :mod:`tools.ac_harness.racing_telemetry`.

The pure core (archive -> ``telemetry_tick`` frames) is CI-testable; the WS send loop and the
shared-memory reads are pragma-guarded.

    # offline spine check (sidecar already running with a faster --reference-archive):
    python -m tools.ai_sidecar.telemetry_source replay --archive slower_lap.json
    # human drives the rig:
    python -m tools.ai_sidecar.telemetry_source live
"""

from __future__ import annotations

import argparse
import math
import struct
from collections.abc import Mapping
from typing import Any

from tools.ai_sidecar.external_protocol import (
    AUTH_HEADER,
    ENVELOPE_KEY,
    ENVELOPE_VERSION,
    TYPE_HELLO,
    TYPE_KEY,
    make_telemetry_tick,
)
from tools.ai_sidecar.lap_dynamics import lap_trace_from_archive

#: Default replay/live cadence. The sidecar caps ``telemetry_tick`` at 20 Hz.
DEFAULT_HZ = 20.0
#: Default steering lock (degrees) for normalizing AC ``steerAngle`` to ``[-1, 1]``.
#: Matches ``import_motec`` default (450°).
DEFAULT_STEER_LOCK_DEG = 450.0
#: Minimum sleep on shared-memory parse failure so a bad/unready rig cannot busy-loop.
_PARSE_FAILURE_SLEEP_S = 0.05

_WHEELS: tuple[str, ...] = ("fl", "fr", "rl", "rr")
_TYRE_TEMP_COL_SPECS: tuple[tuple[str, ...], ...] = (
    ("fl", "tyreCoreTemp_fl", "tyre_temp_fl"),
    ("fr", "tyreCoreTemp_fr", "tyre_temp_fr"),
    ("rl", "tyreCoreTemp_rl", "tyre_temp_rl"),
    ("rr", "tyreCoreTemp_rr", "tyre_temp_rr"),
)
_BRAKE_TEMP_COL_SPECS: tuple[tuple[str, ...], ...] = (
    ("fl", "brakeTemp_fl", "brake_temp_fl"),
    ("fr", "brakeTemp_fr", "brake_temp_fr"),
    ("rl", "brakeTemp_rl", "brake_temp_rl"),
    ("rr", "brakeTemp_rr", "brake_temp_rr"),
)
# Optional AC SPageFilePhysics thermal offsets when an extended buffer is supplied.
_SHM_TYRE_CORE_TEMP_OFFSET = 152
_SHM_BRAKE_TEMP_OFFSET = 348
_SHM_WHEEL_VEC4 = struct.Struct("<4f")


def _finite_float(value: Any) -> float | None:
    """Return a finite float for ``value``, rejecting ``bool``, ``None``, ``NaN``, and ``±inf``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _safe_number(value: Any, default: float = 0.0) -> float:
    """Return a finite non-bool float or ``default``."""
    f = _finite_float(value)
    return default if f is None else f


def period_seconds(hz: float) -> float:
    """Return the inter-frame period for ``hz``; reject non-finite/non-positive values."""
    f = _finite_float(hz)
    if f is None or f <= 0:
        raise ValueError(f"hz must be a finite value > 0, got {hz!r}")
    return 1.0 / f


def close_shared_memory_maps(phys_map: Any, gfx_map: Any) -> None:
    """Close AC shared-memory mappings when present (rig/runtime helper)."""
    if phys_map is not None:
        phys_map.close()
    if gfx_map is not None:
        gfx_map.close()


def normalize_live_steer(
    steer_angle_deg: float, *, lock_deg: float = DEFAULT_STEER_LOCK_DEG
) -> float:
    """Map raw AC ``steerAngle`` degrees into the telemetry_tick ``[-1, 1]`` contract."""
    lock_f = _finite_float(lock_deg)
    lock = lock_f if lock_f is not None and lock_f > 0 else DEFAULT_STEER_LOCK_DEG
    steer_f = _finite_float(steer_angle_deg)
    if steer_f is None:
        return 0.0
    return _clamp(steer_f / lock, -1.0, 1.0)


def _clamp(value: Any, lo: float, hi: float) -> float:
    f = _finite_float(value)
    if f is None:
        return lo
    return lo if f < lo else hi if f > hi else f


def _safe_gear(value: Any) -> int:
    f = _finite_float(value)
    if f is None:
        return 0
    return max(0, int(f))


def _sanitize_corner_map(raw: Any) -> dict[str, float] | None:
    """Sanitize a per-wheel ``{fl, fr, rl, rr}`` map or 4-tuple, rejecting bool/NaN/±inf."""
    if isinstance(raw, Mapping):
        out: dict[str, float] = {}
        for wheel in _WHEELS:
            f = _finite_float(raw.get(wheel))
            if f is not None:
                out[wheel] = f
        return out or None
    if isinstance(raw, list | tuple) and len(raw) == 4:
        out = {}
        for wheel, item in zip(_WHEELS, raw, strict=True):
            f = _finite_float(item)
            if f is not None:
                out[wheel] = f
        return out or None
    return None


def _extract_trace_corner_maps(
    archive: Mapping[str, Any],
    lap: Any,
    attr_name: str,
    col_specs: tuple[tuple[str, ...], ...],
    n_samples: int,
) -> list[dict[str, float] | None]:
    """Extract per-sample sanitized corner thermal maps from ``lap`` or ``archive['trace']``."""
    lap_attr = getattr(lap, attr_name, None)
    if isinstance(lap_attr, list | tuple):
        return [
            _sanitize_corner_map(lap_attr[i]) if i < len(lap_attr) else None
            for i in range(n_samples)
        ]
    if isinstance(lap_attr, Mapping):
        single = _sanitize_corner_map(lap_attr)
        return [dict(single) if single else None for _ in range(n_samples)]

    trace = archive.get("trace") if isinstance(archive, Mapping) else None
    if not isinstance(trace, Mapping):
        return [None] * n_samples
    fields = trace.get("fields")
    samples = trace.get("samples")
    if not isinstance(fields, list) or not isinstance(samples, list):
        return [None] * n_samples
    field_index = {name: idx for idx, name in enumerate(fields) if isinstance(name, str)}

    if attr_name in field_index:
        col_idx = field_index[attr_name]
        out: list[dict[str, float] | None] = []
        for i in range(n_samples):
            row = samples[i] if i < len(samples) and isinstance(samples[i], list | tuple) else ()
            cell = row[col_idx] if col_idx < len(row) else None
            out.append(_sanitize_corner_map(cell))
        return out

    wheel_cols: dict[str, int] = {}
    for spec in col_specs:
        wheel = spec[0]
        for candidate in spec[1:]:
            if candidate in field_index:
                wheel_cols[wheel] = field_index[candidate]
                break
    if not wheel_cols:
        return [None] * n_samples

    per_sample: list[dict[str, float] | None] = []
    any_non_zero = False
    for i in range(n_samples):
        row = samples[i] if i < len(samples) and isinstance(samples[i], list | tuple) else ()
        sample_map: dict[str, float] = {}
        for wheel, col_idx in wheel_cols.items():
            if col_idx < len(row):
                f = _finite_float(row[col_idx])
                if f is not None:
                    sample_map[wheel] = f
                    if f != 0.0:
                        any_non_zero = True
        per_sample.append(sample_map or None)

    # #266: all-zero across the entire trace means the CSP channel was unread (sentinel 0.0).
    if not any_non_zero:
        return [None] * n_samples
    return per_sample


def _sanitize_trace_scalar(
    archive: Mapping[str, Any],
    col_names: tuple[str, ...],
    sample_idx: int,
    fallback: Any,
) -> float:
    """Guard against ``lap_dynamics`` coercing ``bool`` cells via ``float(True) == 1.0``."""
    trace = archive.get("trace") if isinstance(archive, Mapping) else None
    if isinstance(trace, Mapping):
        fields = trace.get("fields")
        samples = trace.get("samples")
        if isinstance(fields, list) and isinstance(samples, list) and sample_idx < len(samples):
            row = samples[sample_idx]
            if isinstance(row, list | tuple):
                for name in col_names:
                    if name in fields:
                        idx = fields.index(name)
                        if idx < len(row):
                            f = _finite_float(row[idx])
                            return 0.0 if f is None else f
    return _safe_number(fallback, 0.0)


def _pick_mapping_value(mapping: Mapping[str, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _clean_str(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None


def _sanitize_conditions(
    raw_conditions: Any,
    raw_car: Any = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Extract sanitized ``conditions`` metadata and top-level ``telemetry_tick`` fields."""
    cond_map = raw_conditions if isinstance(raw_conditions, Mapping) else None
    car_map = raw_car if isinstance(raw_car, Mapping) else None
    if cond_map is None and car_map is None:
        return None, {}

    cond_out: dict[str, Any] = {}
    top_out: dict[str, Any] = {}

    grip = _finite_float(_pick_mapping_value(cond_map, "trackGripLevel", "track_grip_level"))
    if grip is not None and grip >= 0.0:
        cond_out["trackGripLevel"] = grip
        top_out["track_grip_level"] = grip

    track_temp = _finite_float(_pick_mapping_value(cond_map, "trackTempC", "track_temp_c"))
    if track_temp is not None:
        cond_out["trackTempC"] = track_temp
        top_out["track_temp_c"] = track_temp

    ambient_temp = _finite_float(_pick_mapping_value(cond_map, "ambientTempC", "ambient_temp_c"))
    if ambient_temp is not None:
        cond_out["ambientTempC"] = ambient_temp
        top_out["ambient_temp_c"] = ambient_temp

    wind_speed = _finite_float(_pick_mapping_value(cond_map, "windSpeedKmh", "wind_speed_kmh"))
    if wind_speed is not None:
        cond_out["windSpeedKmh"] = wind_speed

    wind_dir = _finite_float(
        _pick_mapping_value(cond_map, "windDirectionDeg", "wind_direction_deg")
    )
    if wind_dir is not None:
        cond_out["windDirectionDeg"] = wind_dir

    optimal_temp = _finite_float(
        _pick_mapping_value(cond_map, "optimalTempC", "tyre_optimal_temp_c", "optimal_temp_c")
        or _pick_mapping_value(car_map, "optimalTempC", "tyre_optimal_temp_c", "optimal_temp_c")
    )
    if optimal_temp is not None and optimal_temp > 0.0:
        cond_out["optimalTempC"] = optimal_temp

    weather = _clean_str(_pick_mapping_value(cond_map, "weatherType", "weather_type"))
    if weather is not None:
        cond_out["weatherType"] = weather
        top_out["weather_type"] = weather

    compound = _clean_str(
        _pick_mapping_value(cond_map, "tyreCompound", "tyre_compound")
        or _pick_mapping_value(car_map, "tyreCompound", "tyre_compound")
    )
    if compound is not None:
        cond_out["tyreCompound"] = compound
        top_out["tyre_compound"] = compound

    return (cond_out if cond_out else None), top_out


def ticks_from_archive(archive: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the ordered ``telemetry_tick`` frames for a stored lap archive (pure).

    Each frame carries the FULL payload :func:`external_protocol._validate_telemetry_tick` requires
    (so the sidecar admits it and feeds the observer) plus ``spline`` for corner location, and
    propagates finite per-wheel ``tyre_temps_c``, ``brake_temps_c``, and ``conditions`` metadata
    when present so offline replay matches the Lua producer contract.
    """
    lap = lap_trace_from_archive(archive)
    speed, spline, brake = lap.v_kmh, lap.spline, lap.brake
    throttle, steer, gear = lap.throttle, lap.steer, lap.gear
    lat_g, long_g = lap.lat_g, lap.long_g
    n_samples = len(lap)
    tyre_maps = _extract_trace_corner_maps(
        archive, lap, "tyre_temps_c", _TYRE_TEMP_COL_SPECS, n_samples
    )
    brake_maps = _extract_trace_corner_maps(
        archive, lap, "brake_temps_c", _BRAKE_TEMP_COL_SPECS, n_samples
    )
    cond_dict, top_cond_fields = _sanitize_conditions(
        archive.get("conditions") if isinstance(archive, Mapping) else None,
        archive.get("car") if isinstance(archive, Mapping) else None,
    )
    frames: list[dict[str, Any]] = []
    for i in range(n_samples):
        payload: dict[str, Any] = {
            "speed_kmh": max(0.0, _safe_number(speed[i], 0.0)),
            "rpm": 0,
            "throttle": _clamp(throttle[i], 0.0, 1.0),
            "brake": _clamp(brake[i], 0.0, 1.0),
            "steer": _clamp(steer[i], -1.0, 1.0),
            "gear": _safe_gear(gear[i]),
            "lat_g": _sanitize_trace_scalar(archive, ("lat_g", "latg", "accG"), i, lat_g[i]),
            "long_g": _sanitize_trace_scalar(archive, ("long_g", "longg"), i, long_g[i]),
            "spline": _clamp(spline[i], 0.0, 1.0),
        }
        if tyre_maps[i] is not None:
            payload["tyre_temps_c"] = dict(tyre_maps[i])  # type: ignore[arg-type]
        if brake_maps[i] is not None:
            payload["brake_temps_c"] = dict(brake_maps[i])  # type: ignore[arg-type]
        if top_cond_fields:
            payload.update(top_cond_fields)
        if cond_dict is not None:
            payload["conditions"] = dict(cond_dict)
        frames.append(make_telemetry_tick(payload, seq=i))
    return frames


def _shm_wheel_map(buf: bytes | None, offset: int) -> dict[str, float] | None:
    """Unpack 4-wheel floats from an extended ``acpmf_physics`` buffer when non-zero and finite."""
    if not isinstance(buf, bytes | bytearray | memoryview):
        return None
    if len(buf) < offset + _SHM_WHEEL_VEC4.size:
        return None
    values = _SHM_WHEEL_VEC4.unpack_from(buf, offset)
    sanitized = _sanitize_corner_map(values)
    if sanitized is None or all(v == 0.0 for v in sanitized.values()):
        return None
    return sanitized


def build_live_tick_payload(
    phys: Any,
    gfx: Any,
    *,
    phys_buf: bytes | None = None,
    conditions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a sanitized ``telemetry_tick`` payload from AC shared-memory samples (pure)."""
    from tools.ac_harness.racing_telemetry import csv_display_gear

    rpm_f = _finite_float(getattr(phys, "rpm", 0))
    laps_f = _finite_float(getattr(gfx, "completed_laps", 0))
    payload: dict[str, Any] = {
        "speed_kmh": max(0.0, _safe_number(getattr(phys, "speed_kmh", 0.0), 0.0)),
        "rpm": max(0, int(rpm_f) if rpm_f is not None else 0),
        "throttle": _clamp(getattr(phys, "gas", 0.0), 0.0, 1.0),
        "brake": _clamp(getattr(phys, "brake", 0.0), 0.0, 1.0),
        "steer": normalize_live_steer(getattr(phys, "steer", 0.0)),
        "gear": csv_display_gear(_safe_gear(getattr(phys, "gear", 0))),
        "lat_g": _safe_number(getattr(phys, "accg_lat", 0.0), 0.0),
        "long_g": _safe_number(getattr(phys, "accg_lon", 0.0), 0.0),
        "spline": _clamp(getattr(gfx, "norm_pos", 0.0), 0.0, 1.0),
        "lap": max(0, int(laps_f) if laps_f is not None else 0),
    }

    tyre_temps = (
        _sanitize_corner_map(getattr(phys, "tyre_temps_c", None))
        or _sanitize_corner_map(getattr(phys, "tyre_core_temp", None))
        or _shm_wheel_map(phys_buf, _SHM_TYRE_CORE_TEMP_OFFSET)
    )
    if tyre_temps is not None:
        payload["tyre_temps_c"] = tyre_temps

    brake_temps = (
        _sanitize_corner_map(getattr(phys, "brake_temps_c", None))
        or _sanitize_corner_map(getattr(phys, "brake_temp", None))
        or _shm_wheel_map(phys_buf, _SHM_BRAKE_TEMP_OFFSET)
    )
    if brake_temps is not None:
        payload["brake_temps_c"] = brake_temps

    raw_cond: dict[str, Any] = {}
    for src in (
        getattr(gfx, "conditions", None),
        getattr(phys, "conditions", None),
        conditions,
    ):
        if isinstance(src, Mapping):
            raw_cond.update(src)
    for attr_key, cond_key in (
        ("surface_grip", "trackGripLevel"),
        ("track_grip_level", "trackGripLevel"),
        ("road_temp", "trackTempC"),
        ("track_temp_c", "trackTempC"),
        ("air_temp", "ambientTempC"),
        ("ambient_temp_c", "ambientTempC"),
        ("weather_type", "weatherType"),
        ("tyre_compound", "tyreCompound"),
    ):
        for obj in (gfx, phys):
            val = getattr(obj, attr_key, None)
            if val is not None and cond_key not in raw_cond:
                raw_cond[cond_key] = val

    cond_dict, top_cond_fields = _sanitize_conditions(raw_cond or None)
    if top_cond_fields:
        payload.update(top_cond_fields)
    if cond_dict is not None:
        payload["conditions"] = cond_dict
    return payload


def make_hello_frame(client: str = "telemetry-source") -> dict[str, Any]:
    """Hello so the sidecar admits the producer (it only ever sends telemetry_tick frames)."""
    return {ENVELOPE_KEY: ENVELOPE_VERSION, TYPE_KEY: TYPE_HELLO, "client": client}


async def replay(  # pragma: no cover - runtime/ws
    url: str, archive: dict[str, Any], *, hz: float = DEFAULT_HZ, token: str | None = None
) -> None:
    """Stream a stored lap archive to the sidecar as live ``telemetry_tick`` frames."""
    import asyncio
    import json

    import websockets

    frames = ticks_from_archive(archive)
    headers = {AUTH_HEADER: token} if token else {}
    period = period_seconds(hz)
    async with websockets.connect(url, additional_headers=headers) as ws:
        await ws.send(json.dumps(make_hello_frame()))
        for frame in frames:
            await ws.send(json.dumps(frame))
            if period:
                await asyncio.sleep(period)


async def stream_live(url: str, *, hz: float = DEFAULT_HZ, token: str | None = None) -> None:
    """Read AC shared memory at ``hz`` and emit ``telemetry_tick`` frames so a human can drive."""
    import asyncio
    import json

    import websockets

    from tools.ac_harness.racing_telemetry import (
        GFX_BYTES,
        PHYS_BYTES,
        parse_graphics,
        parse_physics,
    )
    from tools.ac_harness.shared_memory import (
        SHM_GRAPHICS,
        SHM_PHYSICS,
        open_shared_memory,
    )

    # Map/read lengths come from racing_telemetry's own parser constants (single source of truth):
    # speedKmh@28/brake@8 (phys) and normalizedCarPosition@248/completedLaps@132 (gfx).
    phys_map = None
    gfx_map = None
    try:
        phys_map = open_shared_memory(SHM_PHYSICS, PHYS_BYTES)
        gfx_map = open_shared_memory(SHM_GRAPHICS, GFX_BYTES)
        headers = {AUTH_HEADER: token} if token else {}
        period = period_seconds(hz)
        seq = 0
        async with websockets.connect(url, additional_headers=headers) as ws:
            await ws.send(json.dumps(make_hello_frame("telemetry-source-live")))
            while True:
                try:
                    raw_phys = phys_map.read(PHYS_BYTES)
                    raw_gfx = gfx_map.read(GFX_BYTES)
                    phys = parse_physics(raw_phys)
                    gfx = parse_graphics(raw_gfx)
                except ValueError:
                    await asyncio.sleep(max(period, _PARSE_FAILURE_SLEEP_S))
                    continue
                payload = build_live_tick_payload(phys, gfx, phys_buf=raw_phys)
                await ws.send(json.dumps(make_telemetry_tick(payload, seq=seq)))
                seq += 1
                await asyncio.sleep(period)
    finally:
        close_shared_memory_maps(phys_map, gfx_map)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI wiring
    import asyncio
    import json

    p = argparse.ArgumentParser(description="AC Copilot telemetry source (telemetry_tick producer)")
    p.add_argument("--url", default="ws://127.0.0.1:8765")
    p.add_argument("--token", default=None)
    p.add_argument("--hz", type=float, default=DEFAULT_HZ)
    sub = p.add_subparsers(dest="mode", required=True)
    rp = sub.add_parser("replay", help="stream a stored lap archive (offline spine check)")
    rp.add_argument("--archive", required=True, help="path to a lap archive JSON to replay")
    sub.add_parser("live", help="read AC shared memory and stream live (rig)")
    args = p.parse_args(argv)

    if not math.isfinite(args.hz) or args.hz <= 0:
        raise SystemExit("--hz must be a finite value > 0")

    try:
        if args.mode == "replay":
            with open(args.archive, encoding="utf-8") as fh:
                archive = json.load(fh)
            asyncio.run(replay(args.url, archive, hz=args.hz, token=args.token))
        else:
            asyncio.run(stream_live(args.url, hz=args.hz, token=args.token))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
