"""Synthetic producer for tablet-dash page work (#531 Part F).

Phase 1 proved the dash against a throwaway ``.scratch/dash_feeder.py`` that was lost with the
scratch dir (the Phase-1 vault node flagged the loss); this is its durable replacement. It
connects to a running sidecar as the loopback Lua producer would — ``hello`` then a stream of
``telemetry_tick`` frames plus the ``delta`` / ``lap`` / ``tire_temps`` / ``session`` /
``coaching.snapshot`` topics — so every dash page renders live data with **no sim and no rig**:

    python -m tools.ai_sidecar.dash.dev_feeder --port 8765 [--laps 3] [--rate 20]

Deliberately simple and self-contained (stdlib + websockets, which the sidecar already
requires). The synthetic lap is a closed analytic circuit (two straights + four corners), so
spline/speed/gear/delta stay mutually consistent and the MAP page's dot tracks the outline the
sidecar derives from a reference — pass ``--reference <archive.json>`` to have the feeder drive
the REAL geometry instead (spline-faithful replay of the archive trace).

Not a test fixture: tests use in-process fakes. This is an operator/dev tool for eyeballing
the page on a desktop browser or the P7 without launching AC.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path
from typing import Any

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError as exc:  # pragma: no cover - dep ships with the sidecar
    raise SystemExit("dev_feeder requires the 'websockets' package (sidecar dependency)") from exc

LAP_S = 90.0
RPM_MAX = 8500.0
SHIFT_RPM = 7800.0
FUEL_START_L = 42.0
BURN_L_PER_LAP = 2.4


def _speed_profile(s: float) -> float:
    """Synthetic speed (km/h) over spline: straights ~230, four braking zones down to ~80."""
    v = 200.0 + 40.0 * math.sin(2 * math.pi * s)
    for corner_s in (0.15, 0.4, 0.65, 0.85):
        d = min(abs(s - corner_s), 1 - abs(s - corner_s))
        v -= 130.0 * math.exp(-((d / 0.035) ** 2))
    return max(75.0, v)


def _gear_for(v_kmh: float) -> int:
    return max(1, min(6, int(v_kmh // 45) + 1))


def _tick_payload(s: float, lap: int, lap_time_ms: float, fuel_l: float) -> dict[str, Any]:
    v = _speed_profile(s)
    gear = _gear_for(v)
    accel = _speed_profile((s + 0.004) % 1.0) - v
    throttle = 0.95 if accel >= 0 else 0.1
    brake = 0.0 if accel >= 0 else min(1.0, -accel / 8.0)
    rpm = 3000 + (v % 45) / 45 * (RPM_MAX - 3400)
    return {
        "speed_kmh": round(v, 1),
        "rpm": round(rpm),
        "throttle": throttle,
        "brake": round(brake, 2),
        "steer": round(0.4 * math.sin(6 * math.pi * s), 3),
        "gear": gear,
        "lat_g": round(1.4 * abs(math.sin(6 * math.pi * s)), 2),
        "long_g": round(-brake * 1.2 + throttle * 0.4, 2),
        "spline": round(s, 5),
        "lap": lap,
        "rpm_max": RPM_MAX,
        "shift_rpm": SHIFT_RPM,
        "shift_rpm_source": "learned",
        "lap_time_ms": round(lap_time_ms),
        "fuel_l": round(fuel_l, 2),
        "fuel_capacity_l": 120.0,
        "tyre_temps_c": {"fl": 82, "fr": 84, "rl": 86, "rr": 88},
        "tyre_pressures_psi": {"fl": 27.6, "fr": 27.7, "rl": 27.9, "rr": 28.1},
        "tyre_wear_pct": {"fl": 1.2, "fr": 1.4, "rl": 2.1, "rr": 2.3},
        "tc_active": (0.13 < (s % 0.25) < 0.145),
        "abs_active": False,
        "race_laps_remaining": 12.0,
    }


def _load_reference_spline(path: str) -> list[float] | None:
    archive = json.loads(Path(path).read_text(encoding="utf-8"))
    trace = archive.get("trace") or {}
    fields, samples = trace.get("fields") or [], trace.get("samples") or []
    if "spline" in fields and samples:
        i_sp = fields.index("spline")
        return [float(row[i_sp]) for row in samples]
    return None


async def _run(args: argparse.Namespace) -> None:
    uri = f"ws://127.0.0.1:{args.port}/"
    reference_spline: list[float] | None = None
    if args.reference:
        # One-shot startup read of a small file — fine to do before the socket opens.
        reference_spline = await asyncio.to_thread(_load_reference_spline, args.reference)

    async with ws_connect(uri, max_size=2**22) as ws:

        async def send(obj: dict[str, Any]) -> None:
            await ws.send(json.dumps(obj))

        await send({"v": 1, "type": "hello", "client": "dev-feeder", "client_class": "external"})
        await asyncio.sleep(0.3)
        if args.review_lap_dir:
            # Loopback peers may ask the sidecar to generate the post-session review — this
            # exercises the COACH page against REAL lap archives without a sim.
            await send(
                {
                    "v": 1,
                    "type": "session.review.generate",
                    "lap_dir": args.review_lap_dir,
                }
            )
        await send(
            {
                "v": 1,
                "type": "state.snapshot",
                "topic": "session",
                "payload": {
                    "car_id": "dev_feeder_gt3",
                    "track_id": "synthetic",
                    "session_index": 0,
                },
            }
        )
        dt = 1.0 / args.rate
        seq = 0
        fuel = FUEL_START_L
        best_ms: float | None = None
        for lap in range(args.laps):
            lap_start = time.monotonic()
            while (elapsed := time.monotonic() - lap_start) < LAP_S / args.speedup:
                s = (elapsed * args.speedup) / LAP_S
                if reference_spline:
                    idx = min(len(reference_spline) - 1, int(s * (len(reference_spline) - 1)))
                    s = reference_spline[idx]
                seq += 1
                lap_ms = elapsed * args.speedup * 1000.0
                await send(
                    {
                        "v": 1,
                        "type": "telemetry_tick",
                        "seq": seq,
                        "payload": _tick_payload(s, lap, lap_ms, fuel),
                    }
                )
                if seq % max(1, args.rate // 10) == 0:
                    await send(
                        {
                            "v": 1,
                            "type": "state.snapshot",
                            "topic": "delta",
                            "payload": {
                                "delta_s": round(0.8 * math.sin(2 * math.pi * s), 3),
                                "spline": round(s, 5),
                                "reference_lap_ms": LAP_S * 1000.0,
                            },
                        }
                    )
                if seq % args.rate == 0:
                    await send(
                        {
                            "v": 1,
                            "type": "state.snapshot",
                            "topic": "tire_temps",
                            "payload": {
                                "fl": 82,
                                "fr": 84,
                                "rl": 86,
                                "rr": 88,
                                "inner": {"fl": 84, "fr": 86, "rl": 88, "rr": 92},
                                "middle": {"fl": 82, "fr": 84, "rl": 86, "rr": 89},
                                "outer": {"fl": 79, "fr": 81, "rl": 83, "rr": 86},
                            },
                        }
                    )
                await asyncio.sleep(dt)
            fuel -= BURN_L_PER_LAP
            lap_ms = LAP_S * 1000.0 + (lap % 3) * 400.0
            best_ms = lap_ms if best_ms is None or lap_ms < best_ms else best_ms
            await send(
                {
                    "v": 1,
                    "type": "state.snapshot",
                    "topic": "lap",
                    "payload": {
                        "lap": lap + 1,
                        "last_lap_ms": lap_ms,
                        "best_lap_ms": best_ms,
                        "laps_completed": lap + 1,
                        "valid": True,
                    },
                }
            )
            print(f"feeder: lap {lap + 1}/{args.laps} complete ({lap_ms / 1000:.3f}s)")
        print("feeder: done")


async def _run_resilient(args: argparse.Namespace) -> None:
    """Reconnect-and-continue wrapper: a busy dev box (or a sidecar restart) drops the WS
    with a keepalive timeout; a feeder that dies with it makes page work miserable."""
    attempt = 0
    while True:
        try:
            await _run(args)
            return
        except (OSError, Exception) as exc:  # noqa: BLE001 — dev tool: log and retry
            attempt += 1
            if attempt > 20:
                raise
            print(f"feeder: connection lost ({type(exc).__name__}: {exc}); reconnecting…")
            await asyncio.sleep(1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--laps", type=int, default=3)
    parser.add_argument("--rate", type=int, default=20, help="telemetry_tick Hz")
    parser.add_argument("--speedup", type=float, default=1.0, help="time compression factor")
    parser.add_argument("--reference", help="optional lap archive to replay spline from")
    parser.add_argument(
        "--review-lap-dir",
        help="optional journal/laps dir — ask the sidecar to generate a session review "
        "(exercises the COACH page with real archives)",
    )
    args = parser.parse_args()
    asyncio.run(_run_resilient(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
