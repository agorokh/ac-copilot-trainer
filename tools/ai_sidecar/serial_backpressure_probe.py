"""USB CDC backpressure probe for the rig screen (issue #677 Part B).

Floods realistic ``coaching.snapshot`` NDJSON frames at the screen (or a fake
serial for CI) using the same newline framing as :class:`SerialPeer`, then
parses firmware ``[serial][bp] …`` summary lines.

Usage (live COM port, sidecar stopped so this process owns the CDC)::

    python -m tools.ai_sidecar.serial_backpressure_probe --port COM6 --count 40

The probe is intentionally **host-side only** — it does not change the protocol
v1 envelope the sidecar already speaks. Exit 0 when ``drop=0`` (hard gate) and
every observed ``max_drain_ms`` is at or below ``--max-drain-ms``.

The default drain budget is **100 ms**, not one 16/33 ms LVGL tick: the 8 KiB
CDC RX ring exists specifically so a multi-frame USB burst can land across a
render gap and be drained on the next ``loop()`` without dropping. A saturated
ring of ~20–25 coaching.snapshot frames typically drains in ~40–80 ms on the
JC3248W535; that is absorption working, not a display stall. ``drop>0`` is the
failure that matches the #677 Part B acceptance criterion.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tools.ai_sidecar.serial_transport import DEFAULT_BAUD, open_serial

BP_RE = re.compile(
    r"\[serial\]\[bp\]\s+"
    r"ok=(?P<ok>\d+)\s+"
    r"drop=(?P<drop>\d+)\s+"
    r"parse=(?P<parse>\d+)\s+"
    r"max_avail=(?P<max_avail>\d+)\s+"
    r"max_drain_ms=(?P<max_drain_ms>\d+)"
    r"(?:\s+linked=(?P<linked>\d+)\s+peers=(?P<peers>\d+)"
    r"\s+last_ms=(?P<last_ms>\d+)\s+heap=(?P<heap>\d+))?"
)


@dataclass(frozen=True)
class BpStats:
    ok: int
    drop: int
    parse: int
    max_avail: int
    max_drain_ms: int
    linked: int | None = None
    peers: int | None = None
    last_ms: int | None = None
    heap: int | None = None


def build_coaching_snapshot_frame(
    *,
    corner_id: str = "T1",
    primary: str = "Brake earlier — you're still carrying too much speed",
    secondary: str = "Target 118 km/h; trail to apex",
    seq: int = 0,
) -> str:
    """Build one protocol-v1 ``coaching.snapshot`` line (no trailing newline)."""
    payload = {
        "corner_id": corner_id,
        "corner_label": corner_id,
        "primary_line": primary,
        "secondary_line": f"{secondary} #{seq}",
        "kind": "brake",
        "sub_state": "braking",
        "target_speed_kmh": 118,
        "current_speed_kmh": 142,
        "dist_to_brake_m": 45,
        "progress_pct": (seq * 7) % 100,
    }
    # Pad toward the historical hello_ack / snapshot size class (~300 B) so the
    # burst exercises the 8 KiB RX ring under LVGL drain gaps (#463 / #677).
    pad = "x" * max(0, 280 - len(json.dumps(payload)))
    if pad:
        payload["pad"] = pad
    frame = {"v": 1, "type": "state.snapshot", "topic": "coaching.snapshot", "payload": payload}
    return json.dumps(frame, separators=(",", ":"))


def build_burst(count: int, *, start_seq: int = 0) -> bytes:
    """Return ``count`` NDJSON coaching frames as one write buffer."""
    lines = [
        build_coaching_snapshot_frame(seq=start_seq + i).encode("utf-8") + b"\n"
        for i in range(count)
    ]
    return b"".join(lines)


def parse_bp_line(line: str) -> BpStats | None:
    m = BP_RE.search(line)
    if not m:
        return None
    g = m.groupdict()
    return BpStats(
        ok=int(g["ok"]),
        drop=int(g["drop"]),
        parse=int(g["parse"]),
        max_avail=int(g["max_avail"]),
        max_drain_ms=int(g["max_drain_ms"]),
        linked=int(g["linked"]) if g.get("linked") is not None else None,
        peers=int(g["peers"]) if g.get("peers") is not None else None,
        last_ms=int(g["last_ms"]) if g.get("last_ms") is not None else None,
        heap=int(g["heap"]) if g.get("heap") is not None else None,
    )


def evaluate_bp(
    stats: BpStats,
    *,
    max_drain_ms: int,
    require_frames: int = 1,
) -> tuple[bool, str]:
    """Return (pass, reason) for a single firmware bp summary (absolute counters)."""
    if stats.drop > 0:
        return False, f"overflow drops={stats.drop}"
    if stats.parse > 0:
        return False, f"parse drops={stats.parse}"
    if stats.ok < require_frames:
        return False, f"frames_ok={stats.ok} < required {require_frames}"
    if stats.max_drain_ms > max_drain_ms:
        return False, f"max_drain_ms={stats.max_drain_ms} > budget {max_drain_ms}"
    return True, "ok"


def evaluate_bp_delta(
    before: BpStats | None,
    after: BpStats,
    *,
    max_drain_ms: int,
    require_frames: int = 1,
) -> tuple[bool, str]:
    """Gate on the counter delta across one probe (firmware counters are cumulative)."""
    base = before or BpStats(ok=0, drop=0, parse=0, max_avail=0, max_drain_ms=0)
    delta = BpStats(
        ok=max(0, after.ok - base.ok),
        drop=max(0, after.drop - base.drop),
        parse=max(0, after.parse - base.parse),
        max_avail=after.max_avail,
        max_drain_ms=after.max_drain_ms,
        linked=after.linked,
        peers=after.peers,
        last_ms=after.last_ms,
        heap=after.heap,
    )
    return evaluate_bp(delta, max_drain_ms=max_drain_ms, require_frames=require_frames)


def run_burst_on_port(
    port: str,
    *,
    count: int = 40,
    baud: int = DEFAULT_BAUD,
    settle_s: float = 2.0,
    max_drain_ms: int = 100,
    open_fn: Callable[[str, int], Any] | None = None,
) -> BpStats:
    """Open ``port``, flood ``count`` snapshots, return the last parsed bp line."""
    opener = open_fn or open_serial
    ser = opener(port, baud)
    try:
        # Drain any boot banner so we don't confuse it with bp output.
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            waiting = getattr(ser, "in_waiting", 0) or 0
            if waiting:
                ser.read(waiting)
            else:
                time.sleep(0.02)
        # Terminate any partial host→device line left in the firmware accumulator
        # after flash/reset so the first snapshot cannot concatenate into garbage.
        ser.write(b"\n")
        if hasattr(ser, "flush"):
            ser.flush()
        time.sleep(0.05)
        # Pace waves that fit the 8 KiB CDC RX ring (~20 × ~350 B frames). A
        # single 40-frame write is ~14 KiB and overfills the ring — USB then
        # drops mid-frame bytes, which surfaces as parse>0 with drop=0 (app
        # overflow never fires). Real coaching.snapshot traffic is ~10 Hz; the
        # wave gap models "sustained burst" without lying about ring capacity.
        wave = 16
        for start in range(0, count, wave):
            n = min(wave, count - start)
            ser.write(build_burst(n, start_seq=start))
            if hasattr(ser, "flush"):
                ser.flush()
            time.sleep(0.08)
        # Firmware emits `[serial][bp]` after a ≥8-frame drain; wait for it.
        # Counters are cumulative since boot — gate on the first→last delta.
        buf = bytearray()
        first: BpStats | None = None
        last: BpStats | None = None
        end = time.monotonic() + settle_s
        while time.monotonic() < end:
            chunk = ser.read(1024) if hasattr(ser, "read") else b""
            if chunk:
                buf.extend(chunk)
                while b"\n" in buf:
                    line_b, _, rest = bytes(buf).partition(b"\n")
                    buf = bytearray(rest)
                    try:
                        line = line_b.decode("utf-8", errors="replace")
                    except Exception:  # noqa: BLE001 — probe must stay alive
                        continue
                    parsed = parse_bp_line(line)
                    if parsed is not None:
                        if first is None:
                            first = parsed
                        last = parsed
            else:
                time.sleep(0.02)
        if last is None:
            raise RuntimeError(
                "no [serial][bp] line from firmware — is the #677 build flashed "
                "and the sidecar stopped so this probe owns the CDC port?"
            )
        # Prefer absolute `last` when the first summary is still within this
        # probe's frame budget (fresh boot / first burst after reset). Only
        # diff when counters clearly pre-date the probe (prior runs left ok
        # already above `count`).
        # One full ring-fitting wave (≥8 frames, drop=0, parse=0) is enough to
        # prove absorption; later paced waves may drain below the firmware's
        # ≥8-frame emit threshold and never produce another bp line.
        require = min(16, max(8, count // 4))
        if first is None or first is last or first.ok <= count:
            ok, reason = evaluate_bp(
                last, max_drain_ms=max_drain_ms, require_frames=require
            )
        else:
            ok, reason = evaluate_bp_delta(
                first, last, max_drain_ms=max_drain_ms, require_frames=require
            )
        if not ok:
            raise RuntimeError(
                f"backpressure probe failed: {reason} (first={first}, last={last})"
            )
        return last
    finally:
        try:
            ser.close()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="USB CDC port (e.g. COM6)")
    p.add_argument("--count", type=int, default=40, help="snapshot frames to flood")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument(
        "--max-drain-ms",
        type=int,
        default=100,
        help=(
            "fail if firmware reports a longer single-tick drain (default 100; "
            "the 8 KiB ring is meant to absorb multi-frame bursts across a render gap)"
        ),
    )
    p.add_argument("--settle-s", type=float, default=2.0)
    args = p.parse_args(argv)
    stats = run_burst_on_port(
        args.port,
        count=args.count,
        baud=args.baud,
        settle_s=args.settle_s,
        max_drain_ms=args.max_drain_ms,
    )
    print(
        f"PASS drop={stats.drop} ok={stats.ok} max_drain_ms={stats.max_drain_ms} "
        f"max_avail={stats.max_avail} heap={stats.heap}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
