"""Capture the rig screen's framebuffer through the sidecar and write it as a PNG (#86).

The screen copies its LVGL canvas (the exact pixels flushed to the panel) and streams it back
as ``screen.capture.chunk`` frames over its normal sidecar link, so the capture shows the live
UI with real data. Usage::

    python -m tools.screen_capture --out .scratch/screen.png
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Any

from tools.ai_sidecar.external_protocol import (
    ENVELOPE_KEY,
    ENVELOPE_VERSION,
    TYPE_ERROR,
    TYPE_KEY,
    TYPE_SCREEN_CAPTURE,
    TYPE_SCREEN_CAPTURE_CHUNK,
)
from tools.ai_sidecar.harness_client import HarnessClient

DEFAULT_URL = "ws://127.0.0.1:8765"


class CaptureError(RuntimeError):
    """The screen reported a failure or sent an inconsistent capture."""


def assemble(chunks: list[dict[str, Any]]) -> tuple[bytes, int, int]:
    """Join one capture's chunks by offset; returns ``(raw, width, height)``."""
    if not chunks:
        raise CaptureError("no chunks received")
    errors = [c["error"] for c in chunks if c.get("error")]
    if errors:
        raise CaptureError(f"screen refused the capture: {errors[0]}")
    total, width, height = chunks[0]["total"], chunks[0]["width"], chunks[0]["height"]
    if total != width * height * 2:
        raise CaptureError(f"total {total} is not {width}x{height} RGB565")
    raw = bytearray(total)
    covered = 0
    for chunk in sorted(chunks, key=lambda c: c["offset"]):
        data = base64.b64decode(chunk["data"])
        offset = chunk["offset"]
        if offset != covered or offset + len(data) > total:
            raise CaptureError(f"chunk at {offset} does not follow {covered} (missing or overlap)")
        raw[offset : offset + len(data)] = data
        covered += len(data)
    if covered != total:
        raise CaptureError(f"received {covered} of {total} bytes")
    return bytes(raw), width, height


def rgb565_to_png(raw: bytes, width: int, height: int, *, big_endian: bool) -> bytes:
    """Encode RGB565 pixels as an 8-bit RGB PNG using only the standard library."""
    fmt = ">" if big_endian else "<"
    pixels = struct.unpack(f"{fmt}{width * height}H", raw)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for p in pixels[y * width : (y + 1) * width]:
            r, g, b = (p >> 11) & 0x1F, (p >> 5) & 0x3F, p & 0x1F
            rows += bytes(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def _is_reply_for(capture_id: str):
    """Match this capture's chunks, or a sidecar error about a screen.capture request."""

    def match(frame: dict[str, Any]) -> bool:
        if frame.get(TYPE_KEY) == TYPE_ERROR:
            return frame.get("ref_type") == TYPE_SCREEN_CAPTURE
        return (
            frame.get(TYPE_KEY) == TYPE_SCREEN_CAPTURE_CHUNK
            and frame.get("capture_id") == capture_id
        )

    return match


async def capture(url: str, token: str | None, *, wait_s: float) -> tuple[bytes, int, int]:
    capture_id = f"cap-{int(time.time() * 1000)}"
    chunks: list[dict[str, Any]] = []
    request = {ENVELOPE_KEY: ENVELOPE_VERSION, TYPE_KEY: TYPE_SCREEN_CAPTURE}
    request["capture_id"] = capture_id
    async with HarnessClient(url, token=token, client_id="screen-capture") as client:
        if await client.hello() is None:
            raise CaptureError("sidecar did not acknowledge hello")
        await client.send(request)
        deadline = time.monotonic() + wait_s
        match = _is_reply_for(capture_id)
        while True:
            left = deadline - time.monotonic()
            frame = await client.wait_for(match, timeout=left) if left > 0 else None
            if frame is None:
                raise CaptureError(f"timed out after {len(chunks)} chunks")
            if frame.get(TYPE_KEY) == TYPE_ERROR:
                raise CaptureError(f"sidecar: {frame.get('message')}")
            chunks.append(frame)
            if frame.get("done"):
                break
    return assemble(chunks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", type=Path, required=True)
    # Longer than the sidecar's 60 s stale window: a live-session capture takes ~15 s.
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--byte-order",
        choices=("le", "be"),
        default="le",
        help="RGB565 byte order of the screen canvas",
    )
    args = parser.parse_args(argv)
    token = os.environ.get("AC_COPILOT_SIDECAR_TOKEN") or None
    try:
        raw, width, height = asyncio.run(capture(args.url, token, wait_s=args.timeout))
    except (CaptureError, OSError) as exc:
        print(f"screen-capture: FAIL {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(rgb565_to_png(raw, width, height, big_endian=args.byte_order == "be"))
    print(f"screen-capture: wrote {args.out} {width}x{height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
