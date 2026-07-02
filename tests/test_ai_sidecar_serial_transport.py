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
import threading
import time

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


def test_serial_skips_firmware_traces_and_malformed_frames() -> None:
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

    screens, ack = asyncio.run(_run())
    assert screens == 1
    assert ack["type"] == "hello_ack"


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
