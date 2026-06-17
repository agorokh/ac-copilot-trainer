"""HUD framebuffer capture — the vision oracle's "eyes" (EPIC #154 Part G).

The WS pipeline (`self_test` / `sequence_probe`) answers "is the trainer publishing?"; this module
answers the independent question "does the HUD actually render?" — a black or frozen frame is a real
failure the WS check can miss. It is a **stdlib `ctypes` GDI** desktop grab (no new dependency; the
harness already uses `ctypes` in :mod:`shared_memory`), verified on the rig where AC runs
borderless-windowed (a GDI grab captures it; it does not return black).

The capture itself is Windows-only and live; the conversion / region / PNG / liveness helpers are
pure and unit-tested. The agent-vision / OCR assertion of specific HUD strings is the consuming step
(read the saved PNG), not part of this primitive.

CLI: ``python -m tools.ac_harness.hud_capture --out hud.png --region coaching``
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from dataclasses import dataclass

# GDI / DIB constants.
_SRCCOPY = 0x00CC0020
_DIB_RGB_COLORS = 0
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1

# Named HUD regions as fractions of the primary screen (x, y, w, h). "coaching"/"left" target the
# top-left where the trainer's coaching widget renders; "full" is the whole screen.
_REGIONS: dict[str, tuple[float, float, float, float]] = {
    "full": (0.0, 0.0, 1.0, 1.0),
    "left": (0.0, 0.0, 1 / 3, 1.0),
    "coaching": (0.0, 0.0, 0.35, 0.5),
}


@dataclass(frozen=True)
class LivenessScore:
    """Cheap "is the HUD rendering?" signal over a captured buffer."""

    mean: float
    distinct: int

    def is_rendering(self, *, min_mean: float = 2.0, min_distinct: int = 8) -> bool:
        """True unless the frame looks black/uniform (mean ~0 or almost no distinct values)."""
        return self.mean > min_mean and self.distinct > min_distinct


def region_rect(name: str, screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
    """Resolve a named region to an integer ``(x, y, w, h)`` rect on the given screen size."""
    if name not in _REGIONS:
        raise ValueError(f"unknown region {name!r} (expected one of {sorted(_REGIONS)})")
    fx, fy, fw, fh = _REGIONS[name]
    x = int(fx * screen_w)
    y = int(fy * screen_h)
    w = max(1, int(fw * screen_w))
    h = max(1, int(fh * screen_h))
    return x, y, w, h


def liveness_score(bgra: bytes) -> LivenessScore:
    """Mean byte + distinct-byte-value count over a (sampled) BGRA buffer — black-frame detector."""
    if not bgra:
        return LivenessScore(mean=0.0, distinct=0)
    step = max(1, len(bgra) // 50000)
    sample = bgra[::step]
    return LivenessScore(mean=sum(sample) / len(sample), distinct=len(set(sample)))


def bgra_to_rgb(w: int, h: int, bgra: bytes, *, stride: int = 1) -> tuple[int, int, bytes]:
    """Convert a top-down BGRA buffer to packed RGB, optionally downsampling by ``stride``."""
    if stride < 1:
        raise ValueError("stride must be >= 1")
    out_w, out_h = w // stride, h // stride
    out = bytearray(out_w * out_h * 3)
    mv = memoryview(bgra)
    o = 0
    for ry in range(out_h):
        base = (ry * stride) * w * 4
        for rx in range(out_w):
            i = base + (rx * stride) * 4
            out[o] = mv[i + 2]  # R
            out[o + 1] = mv[i + 1]  # G
            out[o + 2] = mv[i]  # B
            o += 3
    return out_w, out_h, bytes(out)


def encode_png(w: int, h: int, rgb: bytes) -> bytes:
    """Encode packed 8-bit RGB into a PNG (stdlib zlib; filter 0 per row)."""
    if len(rgb) != w * h * 3:
        raise ValueError(f"rgb length {len(rgb)} != {w * h * 3} for {w}x{h}")

    def _chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + rgb[r * w * 3 : (r + 1) * w * 3] for r in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def capture_bgra(x: int = 0, y: int = 0, w: int | None = None, h: int | None = None):
    """Capture a desktop rectangle as top-down BGRA via GDI BitBlt (Windows-only, live)."""
    if sys.platform != "win32":
        raise RuntimeError("hud_capture is Windows-only (GDI BitBlt)")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    try:
        user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 - DPI awareness is best-effort
        pass

    class _BMIH(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    if w is None:
        w = user32.GetSystemMetrics(_SM_CXSCREEN)
    if h is None:
        h = user32.GetSystemMetrics(_SM_CYSCREEN)
    hdc = user32.GetDC(0)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    try:
        gdi32.BitBlt(mdc, 0, 0, w, h, hdc, x, y, _SRCCOPY)
        bmi = _BMIH()
        bmi.biSize = ctypes.sizeof(_BMIH)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB
        buf = (ctypes.c_char * (w * h * 4))()
        gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), _DIB_RGB_COLORS)
        return w, h, bytes(buf)
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(0, hdc)


def capture_region(name: str = "full"):
    """Capture a named HUD region; returns ``(w, h, bgra)``."""
    if sys.platform != "win32":
        raise RuntimeError("hud_capture is Windows-only (GDI BitBlt)")
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    sw = user32.GetSystemMetrics(_SM_CXSCREEN)
    sh = user32.GetSystemMetrics(_SM_CYSCREEN)
    x, y, w, h = region_rect(name, sw, sh)
    return capture_bgra(x, y, w, h)


def save_png(path: str, w: int, h: int, bgra: bytes, *, stride: int = 1) -> tuple[int, int]:
    """Convert a BGRA buffer to PNG and write it; returns the saved ``(w, h)``."""
    out_w, out_h, rgb = bgra_to_rgb(w, h, bgra, stride=stride)
    with open(path, "wb") as fh:
        fh.write(encode_png(out_w, out_h, rgb))
    return out_w, out_h


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HUD framebuffer capture (EPIC #154 Part G)")
    parser.add_argument("--out", default="hud.png", help="Output PNG path")
    parser.add_argument(
        "--region", choices=sorted(_REGIONS), default="coaching", help="Capture region"
    )
    parser.add_argument(
        "--stride", type=int, default=1, help="Downsample factor for the saved PNG (>=1)"
    )
    return parser


def _main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    w, h, bgra = capture_region(args.region)
    score = liveness_score(bgra)
    out_w, out_h = save_png(args.out, w, h, bgra, stride=args.stride)
    rendering = score.is_rendering()
    print(
        f"hud-capture: {'RENDERING' if rendering else 'BLACK/FROZEN'} "
        f"region={args.region} {w}x{h} -> {args.out} ({out_w}x{out_h}) "
        f"mean={score.mean:.1f} distinct={score.distinct}"
    )
    return 0 if rendering else 1


if __name__ == "__main__":  # pragma: no cover - rig-only CLI wiring
    raise SystemExit(_main())
