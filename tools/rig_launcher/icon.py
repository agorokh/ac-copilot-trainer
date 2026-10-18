"""Racing Atelier app icon for the Game Point launcher (issue #881).

The icon is drawn from code, never hand-edited: :func:`render_rgba` rasterises the
mark at each size and :func:`build_ico` packs the sizes into one ``.ico``. The
committed ``assets/game_point.ico`` is the output of ``python -m
tools.rig_launcher.icon --write``; ``tests/test_rig_launcher_icon.py`` regenerates
it and fails on drift, so the binary can never diverge from this source.

The mark is the launcher panel itself, reduced to its signature: a carbon tile
framed by four machined brass corner brackets (the house frame) holding a
shift-light segment bar (the brand's "magnitude is a count" element) — three lit
chalk segments, the amber leading edge, the red zone. Square corners, flat
fields, no glow (``docs/10_Development/design/racing-atelier/project/readme.md``
§ Visual foundations / Iconography).

Every shape is an axis-aligned rectangle snapped to whole pixels per size, so
the small sizes stay crisp instead of being a blurred downscale of the 256 px
art. Pure stdlib (``struct`` + ``zlib``): no Pillow dependency for the build.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

from tools.rig_launcher import theme

#: Sizes packed into the ``.ico``: every size the Windows shell, taskbar and
#: title bar ask for at 100–200 % scaling, up to the 256 px Explorer tile.
ICO_SIZES: tuple[int, ...] = (16, 20, 24, 32, 40, 48, 64, 128, 256)

#: Sizes stored PNG-compressed. Smaller ones are stored as 32-bit DIBs, the most
#: widely understood ICO payload (Tk's own ICO reader, older shell paths).
_PNG_MIN_SIZE = 128

ICON_PATH = Path(__file__).resolve().parent / "assets" / "game_point.ico"

Rgba = tuple[int, int, int, int]
Rect = tuple[int, int, int, int]  # x0, y0, x1, y1 (exclusive)


def _rgba(hex_color: str) -> Rgba:
    value = hex_color.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


_CARBON = _rgba(theme.CARBON)
_BRASS = _rgba(theme.BRASS)
_CHALK = _rgba(theme.CHALK)


def _metric(base: float, size: int, minimum: int = 1) -> int:
    """Scale a 256 px design metric to ``size`` as a whole pixel count."""
    return max(minimum, round(base * size / 256))


def _glyph_g(x: int, y: int, w: int, h: int, t: int) -> list[Rect]:
    """Squared Saira-style G: open top-right is closed, spur turns in at mid height."""
    mid = y + h // 2
    return [
        (x, y, x + w, y + t),  # top
        (x, y, x + t, y + h),  # stem
        (x, y + h - t, x + w, y + h),  # bottom
        (x + w - t, mid, x + w, y + h),  # lower right
        (x + w - max(t, w // 2), mid, x + w, mid + t),  # spur
    ]


def _glyph_p(x: int, y: int, w: int, h: int, t: int) -> list[Rect]:
    """Squared Saira-style P: stem plus a closed bowl over the upper half."""
    bowl = y + max(2 * t + 1, round(h * 0.58))
    return [
        (x, y, x + t, y + h),  # stem
        (x, y, x + w, y + t),  # top
        (x + w - t, y, x + w, bowl),  # bowl right
        (x, bowl - t, x + w, bowl),  # bowl bottom
    ]


def mark_rects(size: int) -> list[tuple[Rect, Rgba]]:
    """The mark as pixel-snapped rectangles (painter's order) for one icon size."""
    rects: list[tuple[Rect, Rgba]] = [((0, 0, size, size), _CARBON)]

    # Machined corner brackets: brass L's flush with the tile corners.
    stroke = _metric(14, size)
    arm = max(stroke + 2, _metric(60, size))
    far = size - arm
    edge = size - stroke
    for x0, y0, vert_x, vert_y in (
        (0, 0, 0, 0),
        (far, 0, edge, 0),
        (0, edge, 0, far),
        (far, edge, edge, far),
    ):
        rects.append(((x0, y0, x0 + arm, y0 + stroke), _BRASS))
        rects.append(((vert_x, vert_y, vert_x + stroke, vert_y + arm), _BRASS))

    # The BrandMark lockup: brass seg-mark, then the GP monogram in chalk caps.
    height = _metric(100, size, minimum=5)
    weight = _metric(22, size)
    g_width = _metric(70, size, minimum=4)
    p_width = _metric(64, size, minimum=4)
    # The seg-mark is chunkier and taller than the caps (as in the window header),
    # so it reads as the brass house bar rather than a letter "I".
    mark_width = _metric(28, size, minimum=2)
    mark_over = _metric(10, size)
    mark_gap = _metric(16, size)
    letter_gap = _metric(12, size)
    total = mark_width + mark_gap + g_width + letter_gap + p_width
    x = (size - total) // 2
    y = (size - height) // 2
    rects.append(((x, y - mark_over, x + mark_width, y + height + mark_over), _BRASS))
    x += mark_width + mark_gap
    rects.extend((rect, _CHALK) for rect in _glyph_g(x, y, g_width, height, weight))
    x += g_width + letter_gap
    rects.extend((rect, _CHALK) for rect in _glyph_p(x, y, p_width, height, weight))
    return rects


def render_rgba(size: int) -> bytes:
    """Rasterise the mark to top-down RGBA bytes (``size * size * 4``)."""
    pixels = bytearray(size * size * 4)
    for (x0, y0, x1, y1), color in mark_rects(size):
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(size, x1), min(size, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        row = bytes(color) * (x1 - x0)
        for y in range(y0, y1):
            start = (y * size + x0) * 4
            pixels[start : start + len(row)] = row
    return bytes(pixels)


def _png(size: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    stride = size * 4
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _dib(size: int, rgba: bytes) -> bytes:
    """32-bit BGRA DIB payload: bottom-up XOR bitmap + all-opaque AND mask."""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    stride = size * 4
    rows = []
    for y in range(size - 1, -1, -1):
        row = rgba[y * stride : (y + 1) * stride]
        bgra = bytearray(row)
        bgra[0::4], bgra[2::4] = row[2::4], row[0::4]
        rows.append(bytes(bgra))
    mask_stride = ((size + 31) // 32) * 4
    return header + b"".join(rows) + b"\x00" * (mask_stride * size)


def build_ico(sizes: tuple[int, ...] = ICO_SIZES) -> bytes:
    """Pack every size into one ``.ico`` (ICONDIR + entries + payloads)."""
    payloads = [
        _png(size, render_rgba(size)) if size >= _PNG_MIN_SIZE else _dib(size, render_rgba(size))
        for size in sizes
    ]
    out = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for size, payload in zip(sizes, payloads, strict=True):
        dim = 0 if size >= 256 else size  # 0 encodes 256 in an ICONDIRENTRY
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(payload), offset)
        offset += len(payload)
    for payload in payloads:
        out += payload
    return bytes(out)


def write_png(path: Path, size: int, *, zoom: int = 1) -> Path:
    """Write one size as a PNG (``zoom`` enlarges nearest-neighbour for review)."""
    rgba = render_rgba(size)
    if zoom > 1:
        stride = size * 4
        rows = []
        for y in range(size):
            row = rgba[y * stride : (y + 1) * stride]
            wide = b"".join(row[x * 4 : x * 4 + 4] * zoom for x in range(size))
            rows.extend([wide] * zoom)
        rgba, size = b"".join(rows), size * zoom
    path.write_bytes(_png(size, rgba))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the Game Point app icon.")
    parser.add_argument("--write", action="store_true", help=f"Rewrite {ICON_PATH.name}.")
    parser.add_argument("--preview-dir", default=None, help="Also dump per-size PNGs here.")
    parser.add_argument("--zoom", type=int, default=1, help="Nearest-neighbour preview zoom.")
    args = parser.parse_args(argv)
    if args.preview_dir:
        out = Path(args.preview_dir)
        out.mkdir(parents=True, exist_ok=True)
        for size in ICO_SIZES:
            write_png(out / f"game_point_{size}.png", size, zoom=args.zoom)
    data = build_ico()
    if args.write:
        ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
        ICON_PATH.write_bytes(data)
        print(f"wrote {ICON_PATH} ({len(data)} bytes, sizes {ICO_SIZES})")
    elif ICON_PATH.is_file() and ICON_PATH.read_bytes() != data:
        print(f"{ICON_PATH} is stale; rerun with --write", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
