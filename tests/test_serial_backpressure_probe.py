"""Host-side unit tests for the #677 Part B serial backpressure probe."""

from __future__ import annotations

import json
import threading
import time

import pytest

from tools.ai_sidecar.serial_backpressure_probe import (
    BpStats,
    build_burst,
    build_coaching_snapshot_frame,
    evaluate_bp,
    parse_bp_line,
    run_burst_on_port,
)


def test_build_coaching_snapshot_frame_is_v1_ndjson_payload() -> None:
    line = build_coaching_snapshot_frame(seq=3)
    assert "\n" not in line
    doc = json.loads(line)
    assert doc["v"] == 1
    assert doc["type"] == "state.snapshot"
    assert doc["topic"] == "coaching.snapshot"
    assert doc["payload"]["corner_id"] == "T1"
    # Sized into the historical overflow class that #463 fixed (256 B ring).
    assert len(line) >= 280


def test_build_burst_is_newline_delimited() -> None:
    blob = build_burst(5)
    lines = [ln for ln in blob.split(b"\n") if ln]
    assert len(lines) == 5
    for ln in lines:
        json.loads(ln)


def test_parse_bp_line_full_and_partial() -> None:
    full = (
        "[serial][bp] ok=40 drop=0 parse=0 max_avail=1200 max_drain_ms=12 "
        "linked=1 peers=1 last_ms=12345 heap=180000"
    )
    st = parse_bp_line(full)
    assert st == BpStats(
        ok=40,
        drop=0,
        parse=0,
        max_avail=1200,
        max_drain_ms=12,
        linked=1,
        peers=1,
        last_ms=12345,
        heap=180000,
    )
    assert parse_bp_line("noise") is None


def test_evaluate_bp_gates_drop_and_drain() -> None:
    ok, _ = evaluate_bp(
        BpStats(ok=40, drop=0, parse=0, max_avail=100, max_drain_ms=12),
        max_drain_ms=33,
        require_frames=20,
    )
    assert ok
    bad_drop, reason = evaluate_bp(
        BpStats(ok=40, drop=1, parse=0, max_avail=100, max_drain_ms=12),
        max_drain_ms=33,
    )
    assert not bad_drop and "drop" in reason
    bad_drain, reason2 = evaluate_bp(
        BpStats(ok=40, drop=0, parse=0, max_avail=100, max_drain_ms=50),
        max_drain_ms=33,
    )
    assert not bad_drain and "max_drain_ms" in reason2


class _FakeBpSerial:
    """Accepts a burst write and later yields a firmware bp summary line."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._written = bytearray()
        self._out = bytearray()
        self.closed = False

    @property
    def in_waiting(self) -> int:
        with self._cond:
            return len(self._out)

    def read(self, size: int = 1) -> bytes:
        with self._cond:
            if not self._out:
                self._cond.wait(timeout=0.05)
            chunk = bytes(self._out[:size])
            del self._out[:size]
            return chunk

    def write(self, data: bytes) -> int:
        with self._cond:
            self._written.extend(data)
            frames = data.count(b"\n")
            # Echo a firmware-shaped summary after the burst lands.
            line = (
                f"[serial][bp] ok={frames} drop=0 parse=0 max_avail={len(data)} "
                f"max_drain_ms=8 linked=1 peers=1 last_ms=99 heap=200000\n"
            ).encode()
            self._out.extend(line)
            self._cond.notify_all()
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_run_burst_on_port_with_fake_serial() -> None:
    fake = _FakeBpSerial()

    def opener(port: str, baud: int) -> _FakeBpSerial:
        assert port == "COM_FAKE"
        assert baud > 0
        return fake

    stats = run_burst_on_port(
        "COM_FAKE",
        count=16,
        settle_s=1.0,
        max_drain_ms=33,
        open_fn=opener,
    )
    assert stats.drop == 0
    assert stats.ok == 16
    assert stats.max_drain_ms == 8
    assert fake.closed
    # Give the background wait a moment if the host is slow.
    time.sleep(0.01)


def test_run_burst_fails_when_no_bp_line() -> None:
    class _Silent:
        in_waiting = 0

        def read(self, size: int = 1) -> bytes:
            return b""

        def write(self, data: bytes) -> int:
            return len(data)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    with pytest.raises(RuntimeError, match="no \\[serial\\]\\[bp\\]"):
        run_burst_on_port(
            "COM_SILENT",
            count=8,
            settle_s=0.2,
            open_fn=lambda _p, _b: _Silent(),
        )
