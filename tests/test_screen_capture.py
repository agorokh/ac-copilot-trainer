"""Rig-screen framebuffer capture: protocol validation and PNG reassembly (#86)."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
import zlib

import pytest

from tools.ai_sidecar import external_protocol as ep
from tools.screen_capture import CaptureError, assemble, rgb565_to_png


def chunk(offset, data, *, total, done, width=2, height=2, **extra):
    frame = {
        "v": 1,
        "type": "screen.capture.chunk",
        "capture_id": "cap-1",
        "width": width,
        "height": height,
        "format": "rgb565",
        "offset": offset,
        "total": total,
        "data": base64.b64encode(data).decode(),
        "done": done,
    }
    frame.update(extra)
    return frame


def test_capture_request_and_chunk_validate():
    assert ep.validate_inbound({"v": 1, "type": "screen.capture", "capture_id": "cap-1"}) is None
    assert ep.validate_inbound(chunk(0, b"\x00" * 8, total=8, done=True)) is None


@pytest.mark.parametrize(
    "frame",
    [
        {"v": 1, "type": "screen.capture"},
        {"v": 1, "type": "screen.capture", "capture_id": "bad id\n"},
        {"v": 1, "type": "screen.capture", "capture_id": "x" * 65},
        chunk(0, b"", total=8, done=True, capture_id=""),
        chunk(0, b"", total=0, done=True),
        chunk(9, b"", total=8, done=True),
        chunk(0, b"", total=8, done="yes"),
        chunk(0, b"", total=8, done=True, width=True),
        chunk(0, b"", total=8, done=True, height=4096),
        chunk(0, b"", total=ep.MAX_SCREEN_CAPTURE_BYTES + 1, done=True),
        {
            **chunk(0, b"", total=8, done=True),
            "data": "A" * (ep.MAX_SCREEN_CAPTURE_CHUNK_CHARS + 9),
        },
        chunk(0, b"", total=8, done=True, error="x" * 201),
    ],
)
def test_malformed_capture_frames_are_rejected(frame):
    assert ep.validate_inbound(frame) is not None


class _Peer:
    remote_address = ("127.0.0.1", 49152)

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


def test_sidecar_routes_request_to_screens_and_chunks_back_to_requester_only():
    from tools.ai_sidecar import server as srv

    async def run():
        srv._reset_external_state()
        try:
            screen, tool, lua = _Peer(), _Peer(), _Peer()
            for peer, client, cls in (
                (screen, "ac-copilot-screen-01", ep.CLIENT_CLASS_SCREEN),
                (tool, "screen-capture", ep.CLIENT_CLASS_EXTERNAL),
                (lua, "browser", ep.CLIENT_CLASS_BROWSER),
            ):
                await srv._handle_external_frame(
                    peer, {"v": 1, "type": "hello", "client": client, "client_class": cls}
                )
                peer.sent.clear()
            request = {"v": 1, "type": "screen.capture", "capture_id": "cap-1"}
            await srv._handle_external_frame(tool, request)
            assert screen.sent == [request]
            assert tool.sent == [] and lua.sent == []

            part = chunk(0, b"\x00" * 4, total=8, done=False)
            last = chunk(4, b"\x00" * 4, total=8, done=True)
            await srv._handle_external_frame(screen, part)
            await srv._handle_external_frame(screen, last)
            assert tool.sent == [part, last]
            assert lua.sent == []
            # The finished capture is forgotten; a stray late chunk goes nowhere.
            await srv._handle_external_frame(screen, part)
            assert tool.sent == [part, last]

            # Only a rig screen may answer.
            await srv._handle_external_frame(lua, part)
            assert lua.sent[-1]["type"] == ep.TYPE_ERROR
            assert tool.sent == [part, last]
        finally:
            srv._reset_external_state()

    asyncio.run(run())


def test_sidecar_admits_one_capture_at_a_time_and_expires_a_stuck_one(monkeypatch):
    from tools.ai_sidecar import server as srv

    clock = [1000.0]
    monkeypatch.setattr(srv.time, "monotonic", lambda: clock[0])

    async def run():
        srv._reset_external_state()
        try:
            screen, first, second = _Peer(), _Peer(), _Peer()
            for peer, client, cls in (
                (screen, "ac-copilot-screen-01", ep.CLIENT_CLASS_SCREEN),
                (first, "screen-capture", ep.CLIENT_CLASS_EXTERNAL),
                (second, "screen-capture", ep.CLIENT_CLASS_EXTERNAL),
            ):
                await srv._handle_external_frame(
                    peer, {"v": 1, "type": "hello", "client": client, "client_class": cls}
                )
                peer.sent.clear()
            await srv._handle_external_frame(
                first, {"v": 1, "type": "screen.capture", "capture_id": "cap-1"}
            )
            await srv._handle_external_frame(
                second, {"v": 1, "type": "screen.capture", "capture_id": "cap-2"}
            )
            # The screen ignores a request while busy, so the sidecar must say so itself.
            assert [f["capture_id"] for f in screen.sent] == ["cap-1"]
            assert second.sent[0]["type"] == ep.TYPE_ERROR
            assert "already in progress" in second.sent[0]["message"]

            # A capture that never finishes stops blocking once it is stale.
            clock[0] += srv.SCREEN_CAPTURE_STALE_S + 1
            await srv._handle_external_frame(
                second, {"v": 1, "type": "screen.capture", "capture_id": "cap-3"}
            )
            assert [f["capture_id"] for f in screen.sent] == ["cap-1", "cap-3"]
        finally:
            srv._reset_external_state()

    asyncio.run(run())


def test_sidecar_reports_when_no_screen_is_connected():
    from tools.ai_sidecar import server as srv

    async def run():
        srv._reset_external_state()
        try:
            tool = _Peer()
            await srv._handle_external_frame(
                tool, {"v": 1, "type": "hello", "client": "screen-capture"}
            )
            tool.sent.clear()
            await srv._handle_external_frame(
                tool, {"v": 1, "type": "screen.capture", "capture_id": "cap-1"}
            )
            assert tool.sent[0]["type"] == ep.TYPE_ERROR
            assert "no rig screen" in tool.sent[0]["message"]
        finally:
            srv._reset_external_state()

    asyncio.run(run())


def test_assemble_orders_chunks_and_checks_coverage():
    raw = bytes(range(8))
    chunks = [chunk(4, raw[4:], total=8, done=True), chunk(0, raw[:4], total=8, done=False)]
    assert assemble(chunks) == (raw, 2, 2)
    with pytest.raises(CaptureError, match="received 4 of 8"):
        assemble([chunk(0, raw[:4], total=8, done=True)])
    with pytest.raises(CaptureError, match="does not follow"):
        assemble([chunk(0, raw[:4], total=8, done=False), chunk(6, raw[6:], total=8, done=True)])


def test_assemble_surfaces_a_screen_error():
    with pytest.raises(CaptureError, match="psram alloc failed"):
        assemble([chunk(0, b"", total=8, done=True, error="psram alloc failed")])


def test_rgb565_to_png_decodes_both_byte_orders():
    # red, green, blue, white
    pixels = [0xF800, 0x07E0, 0x001F, 0xFFFF]
    for big_endian, fmt in ((False, "<"), (True, ">")):
        png = rgb565_to_png(struct.pack(f"{fmt}4H", *pixels), 2, 2, big_endian=big_endian)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        idat_len = struct.unpack(">I", png[33:37])[0]
        rows = zlib.decompress(png[41 : 41 + idat_len])
        assert rows == bytes([0, 255, 0, 0, 0, 255, 0, 0, 0, 0, 255, 255, 255, 255])
