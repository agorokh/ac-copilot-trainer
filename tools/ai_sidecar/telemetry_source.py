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


def period_seconds(hz: float) -> float:
    """Return the inter-frame period for ``hz``; reject non-finite/non-positive values."""
    if not math.isfinite(hz) or hz <= 0:
        raise ValueError(f"hz must be a finite value > 0, got {hz!r}")
    return 1.0 / hz


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
    lock = lock_deg if lock_deg > 0 else DEFAULT_STEER_LOCK_DEG
    return _clamp(steer_angle_deg / lock, -1.0, 1.0)


def _clamp(value: float, lo: float, hi: float) -> float:
    if not math.isfinite(value):
        return lo
    return lo if value < lo else hi if value > hi else value


def _safe_gear(value: float) -> int:
    if not math.isfinite(value):
        return 0
    return max(0, int(value))


def ticks_from_archive(archive: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the ordered ``telemetry_tick`` frames for a stored lap archive (pure).

    Each frame carries the FULL payload :func:`external_protocol._validate_telemetry_tick` requires
    (so the sidecar admits it and feeds the observer) plus ``spline`` for corner location. ``rpm``
    is absent from the lap trace, so it is reported as 0; bounded channels are clamped to their
    contract range to tolerate real-archive jitter. Raises ``ValueError`` (from
    :func:`tools.ai_sidecar.lap_dynamics.lap_trace_from_archive`) when there is no usable trace.
    """
    lap = lap_trace_from_archive(archive)
    speed, spline, brake = lap.v_kmh, lap.spline, lap.brake
    throttle, steer, gear = lap.throttle, lap.steer, lap.gear
    lat_g, long_g = lap.lat_g, lap.long_g
    frames: list[dict[str, Any]] = []
    for i in range(len(lap)):
        payload = {
            "speed_kmh": max(0.0, speed[i]),
            "rpm": 0,
            "throttle": _clamp(throttle[i], 0.0, 1.0),
            "brake": _clamp(brake[i], 0.0, 1.0),
            "steer": _clamp(steer[i], -1.0, 1.0),
            "gear": _safe_gear(gear[i]),
            "lat_g": lat_g[i],
            "long_g": long_g[i],
            "spline": _clamp(spline[i], 0.0, 1.0),
        }
        frames.append(make_telemetry_tick(payload, seq=i))
    return frames


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


async def stream_live(
    url: str, *, hz: float = DEFAULT_HZ, token: str | None = None
) -> None:
    """Read AC shared memory at ``hz`` and emit ``telemetry_tick`` frames so a human can drive."""
    import asyncio
    import json

    import websockets

    from tools.ac_harness.racing_telemetry import (
        GFX_BYTES,
        PHYS_BYTES,
        csv_display_gear,
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
                    phys = parse_physics(phys_map.read(PHYS_BYTES))
                    gfx = parse_graphics(gfx_map.read(GFX_BYTES))
                except ValueError:
                    await asyncio.sleep(max(period, _PARSE_FAILURE_SLEEP_S))
                    continue
                payload = {
                    "speed_kmh": max(0.0, phys.speed_kmh),
                    "rpm": max(0, phys.rpm),
                    "throttle": _clamp(phys.gas, 0.0, 1.0),
                    "brake": _clamp(phys.brake, 0.0, 1.0),
                    "steer": normalize_live_steer(phys.steer),
                    "gear": csv_display_gear(phys.gear),
                    "lat_g": phys.accg_lat,
                    "long_g": phys.accg_lon,
                    "spline": _clamp(gfx.norm_pos, 0.0, 1.0),
                    "lap": max(0, gfx.completed_laps),
                }
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
