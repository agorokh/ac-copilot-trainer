"""Rig-screen framebuffer capture: protocol validation and PNG reassembly (#86)."""

from __future__ import annotations

import base64
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
