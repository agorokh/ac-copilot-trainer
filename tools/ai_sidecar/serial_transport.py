"""USB CDC serial transport for the rig screen (issue #463).

Lets the ESP32 screen speak the **same** protocol-v1 ``{v,type}`` envelope over a
USB CDC serial link instead of WebSocket, removing the Windows Mobile Hotspot
dependency. On single-radio WiFi adapters (e.g. the rig PC's Intel AC 7260),
hosting a 2.4 GHz SoftAP for the ESP32 while the client is on 5 GHz forces one
radio onto two bands and drops the main WiFi (it will not reconnect). USB has no
such conflict — the board already enumerates as a native CDC port.

Design: this is a thin **peer adapter**, not a transport refactor. The sidecar's
:func:`server._handle_external_frame` is already transport-agnostic (it dispatches
a parsed ``dict`` against any peer object that exposes an async ``send(str)``),
and :func:`server._broadcast_external` fans out via the same ``send``. So the
serial path only needs:

* :class:`SerialPeer` — an ``_external_peers``-compatible peer whose ``send``
  writes newline-delimited JSON to the port, with a non-loopback
  ``remote_address`` so the screen is classified as an external client (matching
  the WS screen peer).
* :func:`run_serial_transport` — opens the port with **DTR asserted, RTS low** (RX
  works and the ESP32-S3 does not auto-reset — both verified live on COM6), reads
  NDJSON frames on a background thread, and feeds each into the injected
  ``handle_frame(peer, data)`` coroutine. It reconnects on USB drop/replug.

``pyserial`` is imported lazily inside :func:`open_serial` so the sidecar core
stays dependency-free for users who never enable the serial transport.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BAUD = 115_200
# Native USB CDC ignores baud, but pyserial still requires a value.
_READ_TIMEOUT_S = 0.2
_WRITE_TIMEOUT_S = 2.0
_RECONNECT_DELAY_S = 2.0
# Drop a partial line that never terminates rather than grow unbounded.
_MAX_LINE_BYTES = 1_000_000

# Pushed onto the inbound queue by the reader thread to signal disconnect.
_DISCONNECT = object()

FrameHandler = Callable[[Any, dict[str, Any]], Awaitable[None]]
PeerGoneCallback = Callable[[Any], None]
SerialFactory = Callable[[str, int], Any]


class SerialPeer:
    """A fan-out peer backed by a serial port.

    Implements only the surface the sidecar hub uses: an async ``send(str)`` and a
    ``remote_address``. ``remote_address`` is a ``serial:<port>`` marker string —
    :func:`server._peer_host` returns it verbatim and :func:`server._is_loopback`
    treats it as non-loopback, so the screen is handled as an external client
    exactly like the WebSocket screen peer.
    """

    def __init__(self, port_name: str, write_bytes: Callable[[bytes], None]) -> None:
        self.remote_address = f"serial:{port_name}"
        self._write_bytes = write_bytes
        self._write_lock = asyncio.Lock()

    async def send(self, payload: str) -> None:
        """Write one NDJSON frame to the port (blocking write offloaded to a thread)."""
        line = payload.encode("utf-8") + b"\n"
        async with self._write_lock:
            await asyncio.to_thread(self._write_bytes, line)

    async def close(self) -> None:  # parity with websocket.close(); the port is owned by the loop
        return None


def open_serial(port: str, baud: int) -> Any:
    """Open ``port`` with DTR asserted and RTS low — RX works, board does not reset.

    On the ESP32-S3 native USB CDC, the device only delivers host→device (RX) bytes
    to the sketch once the host asserts **DTR** ("terminal ready"); with DTR low the
    board never sees the sidecar's frames (verified live: it kept re-``hello``-ing).
    The board's auto-reset is driven by the **RTS** line pulse (and pyserial/.NET's
    default of toggling *both* on open), not by a steady DTR — so DTR=True + RTS=False,
    applied **before** ``open()`` as a steady state, gives working RX with no reset.
    """
    import serial  # lazy: only required when the serial transport is enabled

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = _READ_TIMEOUT_S
    ser.write_timeout = _WRITE_TIMEOUT_S
    ser.rts = False  # never pulse RTS -> no ESP32 auto-reset
    ser.dtr = True  # assert DTR so the S3 CDC delivers RX to the firmware
    ser.open()
    # Some drivers only apply line state after open; reassert defensively.
    try:
        ser.rts = False
        ser.dtr = True
    except OSError:
        pass
    return ser


def _spawn_reader(
    ser: Any,
    loop: asyncio.AbstractEventLoop,
    inbound: asyncio.Queue,
    reader_stop: threading.Event,
    port: str,
) -> threading.Thread:
    """Background thread: accumulate bytes, split on newlines, hand lines to the loop.

    Explicit newline framing (not ``readline``) so a read timeout mid-frame cannot
    fragment a JSON object into two malformed lines.
    """

    def _push(item: Any) -> None:
        loop.call_soon_threadsafe(inbound.put_nowait, item)

    def _reader() -> None:
        buf = bytearray()
        try:
            while not reader_stop.is_set():
                try:
                    waiting = ser.in_waiting
                    chunk = ser.read(waiting if waiting and waiting > 0 else 1)
                except Exception as exc:  # noqa: BLE001 - any serial error ends this session
                    _push((_DISCONNECT, repr(exc)))
                    return
                if not chunk:
                    continue  # read timeout with no data — keep polling
                buf.extend(chunk)
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    line = bytes(buf[:nl])
                    del buf[: nl + 1]
                    text = line.decode("utf-8", "replace").strip()
                    if text:
                        _push((text, None))
                if len(buf) > _MAX_LINE_BYTES:
                    logger.warning("serial %s: dropping %d bytes with no newline", port, len(buf))
                    buf.clear()
        finally:
            _push((_DISCONNECT, "reader-exit"))

    thread = threading.Thread(target=_reader, name=f"serial-reader-{port}", daemon=True)
    thread.start()
    return thread


async def run_serial_transport(
    *,
    port: str,
    baud: int = DEFAULT_BAUD,
    handle_frame: FrameHandler,
    on_peer_gone: PeerGoneCallback | None = None,
    serial_factory: SerialFactory = open_serial,
    reconnect_delay: float = _RECONNECT_DELAY_S,
) -> None:
    """Serve the screen over ``port`` until cancelled, reconnecting on USB drop.

    Each inbound NDJSON line is parsed and dispatched through ``handle_frame`` (the
    sidecar's :func:`server._handle_external_frame`), so the screen registers itself
    with a ``hello`` frame and receives ``hello_ack`` / fan-out exactly like a WS peer.
    ``on_peer_gone`` is invoked when the port disconnects so the caller can evict the
    peer from the fan-out set. ``serial_factory`` is injectable for tests.
    """
    loop = asyncio.get_running_loop()
    while True:
        try:
            ser = await asyncio.to_thread(serial_factory, port, baud)
        except Exception as exc:  # noqa: BLE001 - open failure is retryable, not fatal
            logger.warning(
                "serial %s: open failed (%s); retrying in %.1fs", port, exc, reconnect_delay
            )
            await asyncio.sleep(reconnect_delay)
            continue

        logger.info("serial transport open port=%s baud=%s (DTR high, RTS low)", port, baud)
        inbound: asyncio.Queue = asyncio.Queue()
        reader_stop = threading.Event()
        _spawn_reader(ser, loop, inbound, reader_stop, port)

        def _write_bytes(data: bytes, _ser: Any = ser) -> None:
            _ser.write(data)
            flush = getattr(_ser, "flush", None)
            if callable(flush):
                flush()

        peer = SerialPeer(port, _write_bytes)
        try:
            while True:
                item, meta = await inbound.get()
                if item is _DISCONNECT:
                    logger.info("serial %s: disconnect (%s)", port, meta)
                    break
                # The firmware shares this CDC for both protocol frames and plain-text
                # debug prints (`[serial] …`, `[boot] …`). Demultiplex: only a line that
                # looks like a JSON object/array is a protocol frame; anything else is a
                # firmware trace — log it at DEBUG, never WARNING (issue #463 log-spam fix).
                if not item.lstrip().startswith(("{", "[")):
                    logger.debug("serial %s [fw]: %s", port, item[:200])
                    continue
                try:
                    data = json.loads(item)
                except json.JSONDecodeError:
                    logger.warning(
                        "serial %s: malformed json frame (first 200): %s", port, item[:200]
                    )
                    continue
                if not isinstance(data, dict):
                    logger.warning(
                        "serial %s: json root must be object, got %s", port, type(data).__name__
                    )
                    continue
                try:
                    await handle_frame(peer, data)
                except Exception:  # noqa: BLE001 - one bad frame must not kill the transport
                    logger.exception("serial %s: handle_frame failed", port)
        finally:
            reader_stop.set()
            if on_peer_gone is not None:
                try:
                    on_peer_gone(peer)
                except Exception:  # noqa: BLE001
                    logger.exception("serial %s: on_peer_gone failed", port)
            try:
                await asyncio.to_thread(ser.close)
            except Exception:  # noqa: BLE001
                logger.debug("serial %s: close raised", port, exc_info=True)

        await asyncio.sleep(reconnect_delay)
