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
    evaluate_bp_delta,
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
    assert len(line) >= 280


def test_build_burst_is_newline_delimited() -> None:
    blob = build_burst(5, start_seq=10)
    lines = [ln for ln in blob.split(b"\n") if ln]
    assert len(lines) == 5
    assert "#10" in json.loads(lines[0])["payload"]["secondary_line"]


def test_parse_bp_line_with_last_drain() -> None:
    full = (
        "[serial][bp] ok=40 drop=0 parse=0 max_avail=1200 max_drain_ms=40 "
        "last_drain_ms=12 linked=1 peers=1 last_ms=12345 heap=180000"
    )
    st = parse_bp_line(full)
    assert st is not None
    assert st.last_drain_ms == 12
    assert st.ok == 40


def test_evaluate_bp_delta_gates() -> None:
    before = BpStats(ok=8, drop=0, parse=0, max_avail=100, max_drain_ms=10, last_drain_ms=8)
    after = BpStats(ok=48, drop=0, parse=0, max_avail=5000, max_drain_ms=40, last_drain_ms=20)
    ok, _ = evaluate_bp_delta(before, after, max_drain_ms=100, require_frames=40)
    assert ok
    bad, reason = evaluate_bp_delta(
        before,
        BpStats(ok=48, drop=1, parse=0, max_avail=5000, max_drain_ms=40, last_drain_ms=20),
        max_drain_ms=100,
        require_frames=40,
    )
    assert not bad and "drop" in reason
    bad_p, reason_p = evaluate_bp_delta(
        before,
        BpStats(ok=48, drop=0, parse=1, max_avail=5000, max_drain_ms=40, last_drain_ms=20),
        max_drain_ms=100,
        require_frames=40,
    )
    assert not bad_p and "parse" in reason_p


class _FakeBpSerial:
    """Accepts writes; emits cumulative bp lines after each wave."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._out = bytearray()
        self._ok = 0
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
            if data == b"\n":
                return 1
            frames = data.count(b"\n")
            self._ok += frames
            line = (
                f"[serial][bp] ok={self._ok} drop=0 parse=0 max_avail={len(data)} "
                f"max_drain_ms=12 last_drain_ms=8 linked=1 peers=1 last_ms=99 heap=200000\n"
            ).encode()
            self._out.extend(line)
            self._cond.notify_all()
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_run_burst_on_port_with_fake_serial_uses_baseline_delta() -> None:
    fake = _FakeBpSerial()

    def opener(port: str, baud: int) -> _FakeBpSerial:
        assert port == "COM_FAKE"
        return fake

    stats = run_burst_on_port(
        "COM_FAKE",
        count=16,
        settle_s=1.0,
        max_drain_ms=100,
        open_fn=opener,
    )
    # prime(8) + measured(16) = 24 cumulative ok on the fake.
    assert stats.ok == 24
    assert fake.closed
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

    with pytest.raises(RuntimeError, match="no baseline"):
        run_burst_on_port(
            "COM_SILENT",
            count=8,
            settle_s=0.2,
            open_fn=lambda _p, _b: _Silent(),
        )
