"""USB CDC backpressure probe for the rig screen (issue #677 Part B).

Floods realistic ``coaching.snapshot`` NDJSON frames at the screen (or a fake
serial for CI) using the same newline framing as :class:`SerialPeer`, then
parses firmware ``[serial][bp] …`` summary lines.

Usage (live COM port, sidecar stopped so this process owns the CDC)::

    python -m tools.ai_sidecar.serial_backpressure_probe --port COM6 --count 40

The probe is intentionally **host-side only** — it does not change the protocol
v1 envelope the sidecar already speaks.

Hard gates (evaluated on **counter deltas** after a priming baseline):

* ``overflow_drops`` delta == 0
* ``parse_drops`` delta == 0
* ``frames_ok`` delta >= measured frame count
* ``last_drain_ms`` (this drain) <= ``--max-drain-ms`` (default 100)

Waves are paced to fit the 8 KiB CDC RX ring (~16 × ~350 B frames). A single
40-frame write is ~14 KiB and overfills the ring.
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
    r"(?:\s+last_drain_ms=(?P<last_drain_ms>\d+))?"
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
    last_drain_ms: int | None = None
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
        last_drain_ms=int(g["last_drain_ms"]) if g.get("last_drain_ms") is not None else None,
        linked=int(g["linked"]) if g.get("linked") is not None else None,
        peers=int(g["peers"]) if g.get("peers") is not None else None,
        last_ms=int(g["last_ms"]) if g.get("last_ms") is not None else None,
        heap=int(g["heap"]) if g.get("heap") is not None else None,
    )


def evaluate_bp_delta(
    before: BpStats,
    after: BpStats,
    *,
    max_drain_ms: int,
    require_frames: int,
) -> tuple[bool, str]:
    """Gate on counter deltas + this-burst ``last_drain_ms``."""
    d_ok = after.ok - before.ok
    d_drop = after.drop - before.drop
    d_parse = after.parse - before.parse
    if d_drop > 0:
        return False, f"overflow drops delta={d_drop}"
    if d_parse > 0:
        return False, f"parse drops delta={d_parse}"
    if d_ok < require_frames:
        return False, f"frames_ok delta={d_ok} < required {require_frames}"
    drain = after.last_drain_ms if after.last_drain_ms is not None else after.max_drain_ms
    if drain > max_drain_ms:
        return False, f"last_drain_ms={drain} > budget {max_drain_ms}"
    return True, "ok"


def _read_bp_until(
    ser: Any,
    *,
    settle_s: float,
    buf: bytearray,
) -> BpStats | None:
    last: BpStats | None = None
    end = time.monotonic() + settle_s
    while time.monotonic() < end:
        chunk = ser.read(1024) if hasattr(ser, "read") else b""
        if chunk:
            buf.extend(chunk)
            while b"\n" in buf:
                line_b, _, rest = bytes(buf).partition(b"\n")
                buf[:] = rest
                try:
                    line = line_b.decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    continue
                parsed = parse_bp_line(line)
                if parsed is not None:
                    last = parsed
        else:
            time.sleep(0.02)
    return last


def _write_waves(ser: Any, count: int, *, start_seq: int = 0, wave: int = 8) -> None:
    # Keep each wave well under the 8 KiB CDC RX ring and wait for firmware
    # drain + LVGL before the next write (pile-up → silent USB drops with
    # drop=0/parse=0 — the classic #463 ring failure).
    for off in range(0, count, wave):
        n = min(wave, count - off)
        ser.write(build_burst(n, start_seq=start_seq + off))
        if hasattr(ser, "flush"):
            ser.flush()
        time.sleep(0.35)


def run_burst_on_port(
    port: str,
    *,
    count: int = 40,
    baud: int = DEFAULT_BAUD,
    settle_s: float = 2.0,
    max_drain_ms: int = 100,
    open_fn: Callable[[str, int], Any] | None = None,
) -> BpStats:
    """Open ``port``, prime a baseline, flood ``count`` snapshots, gate on deltas."""
    opener = open_fn or open_serial
    ser = opener(port, baud)
    try:
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            waiting = getattr(ser, "in_waiting", 0) or 0
            if waiting:
                ser.read(waiting)
            else:
                time.sleep(0.02)
        ser.write(b"\n")
        if hasattr(ser, "flush"):
            ser.flush()
        time.sleep(0.05)

        buf = bytearray()
        # Priming wave establishes a true pre-measurement baseline (reviewer HIGH).
        prime = 8
        _write_waves(ser, prime, start_seq=0, wave=prime)
        baseline = _read_bp_until(ser, settle_s=max(1.0, settle_s * 0.5), buf=buf)
        if baseline is None:
            raise RuntimeError(
                "no baseline [serial][bp] line after priming — is the #677 build flashed "
                "and the sidecar stopped so this probe owns the CDC port?"
            )

        _write_waves(ser, count, start_seq=prime, wave=8)
        # Poll until the frames_ok delta covers the measured burst (or settle).
        after: BpStats | None = None
        deadline = time.monotonic() + max(settle_s, count * 0.05 + 2.0)
        while time.monotonic() < deadline:
            got = _read_bp_until(ser, settle_s=0.4, buf=buf)
            if got is not None:
                after = got
                if after.ok - baseline.ok >= count:
                    break
        if after is None:
            raise RuntimeError("no post-burst [serial][bp] line from firmware")

        ok, reason = evaluate_bp_delta(
            baseline,
            after,
            max_drain_ms=max_drain_ms,
            require_frames=count,
        )
        if not ok:
            raise RuntimeError(
                f"backpressure probe failed: {reason} (baseline={baseline}, after={after})"
            )
        return after
    finally:
        try:
            ser.close()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="USB CDC port (e.g. COM6)")
    p.add_argument("--count", type=int, default=40, help="measured snapshot frames to flood")
    p.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    p.add_argument(
        "--max-drain-ms",
        type=int,
        default=100,
        help="fail if last_drain_ms exceeds this (default 100)",
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
        f"PASS drop={stats.drop} ok={stats.ok} last_drain_ms={stats.last_drain_ms} "
        f"max_avail={stats.max_avail} heap={stats.heap}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
