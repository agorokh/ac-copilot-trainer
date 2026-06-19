"""Racing telemetry recorder — capture human-driven laps as the dataset a racing controller is
built on (EPIC #154 Part G, #241 follow-up).

The synthetic ``fast_lane.ai`` profile gets the car around but understeers/cuts at pace. A few real
human GT3 laps give the truth a controller (and the trainer's coaching reference) actually needs:
the line, the braking points (where brake goes on vs track position), the carried corner speeds, and
the lateral-grip envelope. This reads AC's shared memory (``acpmf_physics`` + ``acpmf_graphics``) at
~the physics rate, dedupes on packetId, segments by lap (``completedLaps``), and writes one CSV row
per frame plus a per-lap summary — while a HUMAN drives (no Custom-AI hijack).

The frame parsers are pure (CI-testable on synthetic buffers); the mmap loop is Windows/rig-only.

CLI:  python -m tools.ac_harness.racing_telemetry --out human_laps.csv --laps 10
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import time
from dataclasses import dataclass

from tools.ac_harness.shared_memory import SHM_GRAPHICS, SHM_PHYSICS, open_shared_memory

# acpmf_physics layout (standard AC SPageFilePhysics, little-endian):
#   int packetId@0, float gas@4, float brake@8, float fuel@12, int gear@16, int rpms@20,
#   float steerAngle@24, float speedKmh@28, float velocity[3]@32, float accG[3]@44,
#   float wheelSlip[4]@56, float wheelLoad[4]@72, float wheelsPressure[4]@88,
#   float wheelAngularSpeed[4]@104, ...
_PHYS_BYTES = 160
# acpmf_graphics: int packetId@0, int status@4; completedLaps@132, normalizedCarPosition@248
#   (@248 ground-truthed live by scanning for the only changing in-range float; @156=distanceTraveled)
_GFX_BYTES = 256
# Minimum bytes needed: norm_pos at offset 248 is a 4-byte float.
_GFX_MIN_BYTES = 252

CSV_HEADER = (
    "lap,t_s,norm_pos,speed_kmh,gear,rpm,gas,brake,steer,accg_lat,accg_lon,"
    "slip_fl,slip_fr,slip_rl,slip_rr"
)


@dataclass(frozen=True)
class PhysFrame:
    packet_id: int
    gas: float
    brake: float
    gear: int
    rpm: int
    steer: float
    speed_kmh: float
    accg_lat: float
    accg_lon: float
    slip: tuple[float, float, float, float]


@dataclass(frozen=True)
class GfxFrame:
    packet_id: int
    status: int
    completed_laps: int
    norm_pos: float


def parse_physics(buf: bytes) -> PhysFrame:
    """Parse an ``acpmf_physics`` buffer (pure)."""
    if len(buf) < _PHYS_BYTES:
        raise ValueError(f"physics buffer too short: {len(buf)} < {_PHYS_BYTES}")
    packet_id = struct.unpack_from("<i", buf, 0)[0]
    gas, brake = struct.unpack_from("<2f", buf, 4)
    gear, rpm = struct.unpack_from("<2i", buf, 16)
    steer, speed = struct.unpack_from("<2f", buf, 24)
    accg = struct.unpack_from("<3f", buf, 44)  # [lateral, vertical, longitudinal]
    slip = struct.unpack_from("<4f", buf, 56)
    _require_finite(
        gas=gas,
        brake=brake,
        steer=steer,
        speed=speed,
        accg_lat=accg[0],
        accg_lon=accg[2],
        slip_fl=slip[0],
        slip_fr=slip[1],
        slip_rl=slip[2],
        slip_rr=slip[3],
    )
    return PhysFrame(packet_id, gas, brake, gear, rpm, steer, speed, accg[0], accg[2], slip)


def parse_graphics(buf: bytes) -> GfxFrame:
    """Parse an ``acpmf_graphics`` buffer (pure)."""
    if len(buf) < _GFX_MIN_BYTES:
        raise ValueError(f"graphics buffer too short: {len(buf)} < {_GFX_MIN_BYTES}")
    packet_id = struct.unpack_from("<i", buf, 0)[0]
    status = struct.unpack_from("<i", buf, 4)[0]
    completed_laps = struct.unpack_from("<i", buf, 132)[0]
    norm_pos = struct.unpack_from("<f", buf, 248)[0]
    _require_finite(norm_pos=norm_pos)
    return GfxFrame(packet_id, status, completed_laps, norm_pos)


def _require_finite(**fields: float) -> None:
    bad = [name for name, value in fields.items() if not math.isfinite(value)]
    if bad:
        raise ValueError(f"non-finite shared-memory fields: {', '.join(bad)}")


def csv_display_gear(raw: int) -> int:
    """Map AC physics gear index to CSV gear (0=neutral, -1=reverse, 1..N forward).

    Live-probed encoding: 0=reverse, 1=neutral, 2=1st … (see vault autonomous-drive note).
    """
    if raw == 0:
        return -1
    if raw == 1:
        return 0
    return raw - 1


def csv_row(lap: int, t: float, p: PhysFrame, g: GfxFrame) -> str:
    return (
        f"{lap},{t:.3f},{g.norm_pos:.5f},{p.speed_kmh:.2f},{csv_display_gear(p.gear)},{p.rpm},"
        f"{p.gas:.3f},{p.brake:.3f},{p.steer:.4f},{p.accg_lat:.3f},{p.accg_lon:.3f},"
        f"{p.slip[0]:.3f},{p.slip[1]:.3f},{p.slip[2]:.3f},{p.slip[3]:.3f}"
    )


def record(out_path: str, *, max_laps: int = 10, max_seconds: float = 1800.0) -> int:
    """Record physics+graphics frames to ``out_path`` (CSV) until ``max_laps`` or ``max_seconds``.

    Windows/rig-only. Physics-led pairing: a row is emitted only when the physics packetId
    advances, with graphics read immediately afterward (minimizes time-skew). Segments laps on
    ``completedLaps``, and prints a per-lap summary (time, min/max speed).
    Returns the number of completed laps.
    """
    if sys.platform != "win32":
        raise RuntimeError("racing_telemetry recording is Windows-only (AC shared memory)")
    phys = gfx = None
    laps = 0
    rows = 0
    try:
        phys = open_shared_memory(SHM_PHYSICS, _PHYS_BYTES)
        gfx = open_shared_memory(SHM_GRAPHICS, _GFX_BYTES)
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(CSV_HEADER + "\n")

            last_phys_packet: int | None = None
            lap_rows = 0
            base_laps: int | None = None
            lap_start_t = 0.0
            lap_min = 1e9
            lap_max = 0.0
            t0 = time.monotonic()
            print(
                f"recording to {out_path} — drive! (Ctrl-C or {max_laps} laps to stop)",
                flush=True,
            )
            try:
                while True:
                    now = time.monotonic()
                    if now - t0 >= max_seconds or laps >= max_laps:
                        break
                    pbuf = phys.read(_PHYS_BYTES)
                    try:
                        p = parse_physics(pbuf)
                    except ValueError as exc:
                        print(f"  skip physics frame: {exc}", flush=True)
                        time.sleep(0.003)
                        continue
                    if last_phys_packet is not None and p.packet_id <= last_phys_packet:
                        time.sleep(0.003)
                        continue
                    last_phys_packet = p.packet_id

                    gbuf = gfx.read(_GFX_BYTES)
                    try:
                        g = parse_graphics(gbuf)
                    except ValueError as exc:
                        print(f"  skip graphics frame: {exc}", flush=True)
                        time.sleep(0.003)
                        continue
                    if base_laps is None:
                        base_laps = g.completed_laps
                        lap_start_t = now
                    lap = g.completed_laps - base_laps
                    fh.write(csv_row(lap, now - t0, p, g) + "\n")
                    rows += 1
                    lap_rows += 1
                    lap_min = min(lap_min, p.speed_kmh)
                    lap_max = max(lap_max, p.speed_kmh)
                    if lap > laps:  # crossed start/finish -> a lap completed
                        lt = now - lap_start_t
                        print(
                            f"  LAP {laps + 1} done: {lt:6.1f}s  speed "
                            f"{lap_min:5.1f}-{lap_max:5.1f} km/h ({lap_rows} frames)",
                            flush=True,
                        )
                        laps = lap
                        lap_start_t = now
                        lap_min, lap_max = 1e9, 0.0
                        lap_rows = 0
                    time.sleep(0.004)
            except KeyboardInterrupt:
                print("\nstopped.", flush=True)
    finally:
        if gfx is not None:
            gfx.close()
        if phys is not None:
            phys.close()
    print(f"\nwrote {rows} frames over {laps} completed lap(s) -> {out_path}", flush=True)
    return laps


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record human-driven AC laps (EPIC #154 #241)")
    parser.add_argument("--out", default="human_laps.csv", help="Output CSV path")
    parser.add_argument("--laps", type=int, default=10, help="Stop after this many completed laps")
    parser.add_argument("--seconds", type=float, default=1800.0, help="Max recording seconds")
    return parser


def _main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    record(args.out, max_laps=args.laps, max_seconds=args.seconds)
    return 0


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    raise SystemExit(_main())
