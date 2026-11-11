"""USB-serial screen transport tests for the AI sidecar (issue #463).

Covers the serial peer adapter that lets the ESP32 screen speak protocol v1 over
USB CDC instead of WebSocket (removing the Windows Mobile Hotspot dependency):

- ``SerialPeer.send`` writes newline-delimited JSON.
- ``open_serial`` holds DTR/RTS LOW *before* ``open()`` so the ESP32-S3 does not reset.
- End-to-end: a ``hello`` read from the port registers a screen peer, a ``hello_ack``
  is written back, and a hub ``_broadcast_external`` frame reaches the serial peer.
- Newline framing reassembles a frame split across reads and dispatches two frames
  from one chunk.
- A malformed JSON line is skipped without killing the transport.
- A serial error evicts the peer via ``on_peer_gone``.

Tests use plain ``asyncio.run`` + an injected fake serial — no hardware, no
pytest-asyncio dependency (matching ``test_ai_sidecar_external.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from pathlib import Path

import pytest

from tools.ai_sidecar import server as srv
from tools.ai_sidecar.serial_transport import (
    SerialPeer,
    open_serial,
    run_serial_transport,
)


class _FakeSerial:
    """In-memory pyserial stand-in: ``feed`` inbound bytes, inspect ``written``."""

    def __init__(self, preload: bytes = b"") -> None:
        self._cond = threading.Condition()
        self._inbuf = bytearray(preload)
        self._written = bytearray()
        self._fail = False
        self.closed = False

    # --- test-facing API ---
    def feed(self, data: bytes) -> None:
        with self._cond:
            self._inbuf.extend(data)
            self._cond.notify_all()

    def fail(self) -> None:
        """Simulate a USB unplug: subsequent reads raise."""
        with self._cond:
            self._fail = True
            self._cond.notify_all()

    def pop_written(self) -> bytes:
        with self._cond:
            out = bytes(self._written)
            self._written.clear()
            return out

    # --- pyserial-like API used by the transport ---
    @property
    def in_waiting(self) -> int:
        with self._cond:
            if self._fail:
                raise OSError("device disconnected")
            return len(self._inbuf)

    def read(self, size: int = 1) -> bytes:
        with self._cond:
            if self._fail:
                raise OSError("device disconnected")
            if not self._inbuf:
                self._cond.wait(timeout=0.05)  # emulate read timeout
                if self._fail:
                    raise OSError("device disconnected")
                if not self._inbuf:
                    return b""
            take = min(size, len(self._inbuf))
            out = bytes(self._inbuf[:take])
            del self._inbuf[:take]
            return out

    def write(self, data: bytes) -> int:
        with self._cond:
            self._written.extend(data)
            return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()


async def _next_frame(fake: _FakeSerial, buf: bytearray, max_wait: float = 2.0) -> dict:
    """Await the next complete NDJSON frame written to ``fake``."""
    deadline = time.monotonic() + max_wait
    while True:
        buf.extend(fake.pop_written())
        nl = buf.find(b"\n")
        if nl >= 0:
            line = bytes(buf[:nl])
            del buf[: nl + 1]
            return json.loads(line)
        if time.monotonic() > deadline:
            raise AssertionError("no NDJSON frame written before timeout")
        await asyncio.sleep(0.02)


async def _wait_for(predicate, max_wait: float = 2.0) -> None:
    deadline = time.monotonic() + max_wait
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met before timeout")
        await asyncio.sleep(0.02)


def test_serial_peer_send_writes_ndjson() -> None:
    written: list[bytes] = []
    peer = SerialPeer("COM_TEST", written.append)

    asyncio.run(peer.send(json.dumps({"v": 1, "type": "hello_ack"})))

    assert written == [b'{"v": 1, "type": "hello_ack"}\n']
    # Non-loopback marker so the screen is classified as an external client.
    assert peer.remote_address == "serial:COM_TEST"
    assert not srv._is_loopback_peer(peer)


def test_open_serial_asserts_dtr_keeps_rts_low_before_open() -> None:
    # pyserial is an optional runtime dep (lazy-imported by open_serial); skip when
    # it is not installed, like the duckdb/sentence-transformers tests.
    serial = pytest.importorskip("serial")

    events: list[tuple[str, object]] = []

    class _RecordingSerial:
        def __init__(self) -> None:
            self._dtr: object = None
            self._rts: object = None
            self.port: object = None
            self.baudrate: object = None
            self.timeout: object = None
            self.write_timeout: object = None

        @property
        def dtr(self) -> object:
            return self._dtr

        @dtr.setter
        def dtr(self, value: object) -> None:
            self._dtr = value
            events.append(("dtr", value))

        @property
        def rts(self) -> object:
            return self._rts

        @rts.setter
        def rts(self, value: object) -> None:
            self._rts = value
            events.append(("rts", value))

        def open(self) -> None:
            events.append(("open", (self._dtr, self._rts)))

    original = serial.Serial
    serial.Serial = _RecordingSerial  # type: ignore[misc,assignment]
    try:
        ser = open_serial("COM9", 115200)
    finally:
        serial.Serial = original  # type: ignore[misc]

    open_event = next(e for e in events if e[0] == "open")
    # At open: DTR asserted (RX works on the S3 CDC), RTS low (no auto-reset).
    assert open_event[1] == (True, False)
    assert ser.port == "COM9"
    assert ser.baudrate == 115200


def test_serial_hello_registers_screen_peer_and_receives_broadcast() -> None:
    async def _run() -> tuple[dict, dict, tuple[int, int]]:
        srv._reset_external_state()
        fake = _FakeSerial()
        task = asyncio.create_task(
            run_serial_transport(
                port="COM_TEST",
                baud=115200,
                handle_frame=srv._handle_external_frame,
                on_peer_gone=srv._drop_external_peer,
                serial_factory=lambda _port, _baud: fake,
                reconnect_delay=0.01,
            )
        )
        try:
            fake.feed(
                json.dumps(
                    {
                        "v": 1,
                        "type": "hello",
                        "client": "ac-copilot-screen-01",
                        "client_class": "screen",
                    }
                ).encode()
                + b"\n"
            )
            buf = bytearray()
            ack = await _next_frame(fake, buf)
            await _wait_for(lambda: srv._peer_counts() == (1, 1))
            counts = srv._peer_counts()
            await srv._broadcast_external(
                {
                    "v": 1,
                    "type": "state.snapshot",
                    "topic": "coaching.snapshot",
                    "payload": {"corner": 3},
                },
                exclude=None,
            )
            snap = await _next_frame(fake, buf)
            return ack, snap, counts
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            srv._reset_external_state()

    ack, snap, counts = asyncio.run(_run())
    assert ack["type"] == "hello_ack"
    assert counts == (1, 1)
    assert snap["type"] == "state.snapshot"
    assert snap["topic"] == "coaching.snapshot"
    assert snap["payload"] == {"corner": 3}


def test_serial_reassembles_split_frame_and_dispatches_batch() -> None:
    async def _run() -> int:
        srv._reset_external_state()
        fake = _FakeSerial()
        task = asyncio.create_task(
            run_serial_transport(
                port="COM_TEST",
                baud=115200,
                handle_frame=srv._handle_external_frame,
                on_peer_gone=srv._drop_external_peer,
                serial_factory=lambda _p, _b: fake,
                reconnect_delay=0.01,
            )
        )
        try:
            hello = json.dumps(
                {"v": 1, "type": "hello", "client": "screen", "client_class": "screen"}
            ).encode()
            # Frame split across two reads: no newline in the first chunk.
            fake.feed(hello[:10])
            await asyncio.sleep(0.05)
            fake.feed(hello[10:] + b"\n")
            await _wait_for(lambda: srv._peer_counts() == (1, 1))
            return srv._peer_counts()[1]
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            srv._reset_external_state()

    assert asyncio.run(_run()) == 1


def test_serial_skips_firmware_traces_and_malformed_frames(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _run() -> tuple[int, dict]:
        srv._reset_external_state()
        fake = _FakeSerial()
        task = asyncio.create_task(
            run_serial_transport(
                port="COM_TEST",
                baud=115200,
                handle_frame=srv._handle_external_frame,
                on_peer_gone=srv._drop_external_peer,
                serial_factory=lambda _p, _b: fake,
                reconnect_delay=0.01,
            )
        )
        try:
            # A firmware debug trace (shares the CDC) and a `{`-prefixed malformed
            # frame must both be skipped without killing the transport; a valid
            # hello after them still registers the screen (issue #463 demux).
            fake.feed(b"[serial] link up (sidecar answered)\n")
            fake.feed(b'{"v":1,"type":\n')  # looks like a frame but is broken
            fake.feed(
                json.dumps(
                    {"v": 1, "type": "hello", "client": "screen", "client_class": "screen"}
                ).encode()
                + b"\n"
            )
            buf = bytearray()
            ack = await _next_frame(fake, buf)
            await _wait_for(lambda: srv._peer_counts() == (1, 1))
            return srv._peer_counts()[1], ack
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            srv._reset_external_state()

    with caplog.at_level(logging.DEBUG, logger="tools.ai_sidecar.serial_transport"):
        screens, ack = asyncio.run(_run())
    assert screens == 1
    assert ack["type"] == "hello_ack"
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    # A `[serial]`-prefixed firmware trace must NOT warn (it starts with '[', not '{').
    assert not any("link up (sidecar answered)" in m for m in warnings), warnings
    # A `{`-looking line that fails to parse IS a real malformed frame -> WARNING.
    assert any("malformed json" in m for m in warnings), warnings


def test_serial_disconnect_evicts_peer() -> None:
    async def _run() -> tuple[int, int]:
        srv._reset_external_state()
        fake = _FakeSerial()
        task = asyncio.create_task(
            run_serial_transport(
                port="COM_TEST",
                baud=115200,
                handle_frame=srv._handle_external_frame,
                on_peer_gone=srv._drop_external_peer,
                serial_factory=lambda _p, _b: fake,
                reconnect_delay=600,  # do not reconnect within the test window
            )
        )
        try:
            fake.feed(
                json.dumps(
                    {"v": 1, "type": "hello", "client": "screen", "client_class": "screen"}
                ).encode()
                + b"\n"
            )
            await _wait_for(lambda: srv._peer_counts() == (1, 1))
            before = srv._peer_counts()[0]
            fake.fail()  # simulate USB unplug
            await _wait_for(lambda: srv._peer_counts() == (0, 0))
            return before, srv._peer_counts()[0]
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            srv._reset_external_state()

    before, after = asyncio.run(_run())
    assert before == 1
    assert after == 0


def test_serial_bounds_oversized_spinner_and_setup_lists_while_non_screen_gets_full_payload() -> (
    None
):
    """#86: 59-spinner GT3 setup.spinner.list.result (~12.8 KB) must fit serial/screen ring while
    full frames still reach browser/WebSocket external peers."""

    class _BrowserPeer:
        remote_address = ("192.168.1.50", 54321)

        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

    async def _run() -> tuple[dict, dict, list[dict]]:
        srv._reset_external_state()
        fake = _FakeSerial()
        browser = _BrowserPeer()
        task = asyncio.create_task(
            run_serial_transport(
                port="COM_TEST",
                baud=115200,
                handle_frame=srv._handle_external_frame,
                on_peer_gone=srv._drop_external_peer,
                serial_factory=lambda _p, _b: fake,
                reconnect_delay=0.01,
            )
        )
        try:
            fake.feed(
                json.dumps(
                    {"v": 1, "type": "hello", "client": "screen", "client_class": "screen"}
                ).encode()
                + b"\n"
            )
            buf = bytearray()
            await _next_frame(fake, buf)  # hello_ack
            await _wait_for(lambda: srv._peer_counts() == (1, 1))
            await srv._handle_external_frame(
                browser,
                {"v": 1, "type": "hello", "client": "tablet-dash", "client_class": "browser"},
            )
            browser.sent.clear()

            spinners_frame = {
                "v": 1,
                "type": "setup.spinner.list.result",
                "ok": True,
                "source": "csp",
                "reset_allowed": True,
                "lock_reason": "",
                "spinners": [
                    {
                        "section": f"SPINNER_{i:02d}",
                        "label": f"Damper Spinner {i:02d}",
                        "value": i,
                        "min": 0,
                        "max": 40,
                        "step": 1,
                        "unit": "clicks",
                        "range_known": True,
                        "adjustable": True,
                        "display_multiplier": 1,
                    }
                    for i in range(59)
                ],
            }
            assert len(json.dumps(spinners_frame, separators=(",", ":")).encode()) > 9000
            await srv._broadcast_external(spinners_frame, exclude=None)
            serial_spinners = await _next_frame(fake, buf)

            active_path = "C:/Users/driver/Documents/Assetto Corsa/setups/car/spa/Active_Tail.ini"
            setups_frame = {
                "v": 1,
                "type": "setup.list.result",
                "car_id": "ks_porsche_911_gt3_r_2016",
                "track_id": "spa",
                "active": "Active_Tail",
                "active_path": active_path,
                "count": 60,
                "setups": [
                    {
                        "name": "Active_Tail" if i == 59 else f"Setup_{i:02d}_long_scientist_name",
                        "path": active_path
                        if i == 59
                        else (
                            "C:/Users/driver/Documents/Assetto Corsa/setups/"
                            f"car/spa/Setup_{i:02d}_long_scientist_name.ini"
                        ),
                        "mtime_iso": "2026-11-10T12:00:00Z",
                        "summary": {"brake_bias": 64, "abs": 8, "tc": 3, "wing_f": 1, "wing_r": 20},
                    }
                    for i in range(60)
                ],
            }
            assert len(json.dumps(setups_frame, separators=(",", ":")).encode()) > 10000
            await srv._broadcast_external(setups_frame, exclude=None)
            serial_setups = await _next_frame(fake, buf)
            return serial_spinners, serial_setups, browser.sent
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            srv._reset_external_state()

    serial_spinners, serial_setups, browser_sent = asyncio.run(_run())
    assert len(serial_spinners["spinners"]) == srv.SCREEN_PEER_MAX_SPINNERS == 12
    spinners_bytes = len(json.dumps(serial_spinners, separators=(",", ":")).encode())
    setups_bytes = len(json.dumps(serial_setups, separators=(",", ":")).encode())
    assert spinners_bytes <= srv.SCREEN_PEER_MAX_SPINNER_LIST_BYTES
    assert len(browser_sent[0]["spinners"]) == 59

    assert setups_bytes <= srv.SCREEN_PEER_MAX_LINE_BYTES
    # Combined dual-list burst + 10 Hz coaching.snapshot headroom fits even legacy 8192 B rings.
    assert spinners_bytes + setups_bytes + 512 <= 8192
    assert serial_setups["count"] == len(serial_setups["setups"]) < 60
    assert any(s["name"] == "Active_Tail" for s in serial_setups["setups"])
    assert len(browser_sent[1]["setups"]) == 60

    header = (
        Path(__file__).resolve().parents[1]
        / "firmware"
        / "screen"
        / "include"
        / "ui"
        / "screen_pocket_technician.h"
    ).read_text(encoding="utf-8")
    assert f"#define PT_MAX_SPINNERS {srv.SCREEN_PEER_MAX_SPINNERS}" in header
