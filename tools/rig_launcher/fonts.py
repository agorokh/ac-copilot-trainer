"""Private design-font loading for the Game Point launcher (epic #432 photo parity).

Registers the Racing Atelier faces (Saira SemiCondensed statics, Saira Bold,
Spline Sans Mono Medium) *process-privately* on Windows via GDI's
``AddFontResourceExW(..., FR_PRIVATE, 0)`` so the launcher renders on-brand
without a system-wide font install and without leaking the faces to other
processes. Everything degrades silently: on non-Windows, when GDI is
unavailable, or when the font files are absent (they ship on the packaging
branch, not on ``main``), :func:`load_private_fonts` returns what it loaded —
possibly nothing — and the theme's font ladder falls back to Bahnschrift /
Consolas.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

#: GDI flag: the font is visible to this process only and never enumerated
#: system-wide (FR_PRIVATE in wingdi.h).
FR_PRIVATE = 0x10

#: The design statics the launcher uses (display, read, mono faces).
FONT_FILES: tuple[str, ...] = (
    "SairaSemiCondensed-SemiBold.ttf",
    "SairaSemiCondensed-Bold.ttf",
    "SairaSemiCondensed-ExtraBold.ttf",
    "Saira-Bold.ttf",
    "SplineSansMono-Medium.ttf",
)


def _font_dirs() -> list[Path]:
    """Candidate font directories, most specific first.

    (a) the PyInstaller onefile extraction dir (``sys._MEIPASS``/fonts, matching
    the ``--add-data`` destination in ``build_pyinstaller_args``), then
    (b) the repo checkout's bundled content fonts, located relative to this
    module so a dev-tree launch finds them without configuration.
    """
    dirs: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "fonts")
    repo_root = Path(__file__).resolve().parents[2]
    dirs.append(repo_root / "src" / "ac_copilot_trainer" / "content" / "fonts")
    return dirs


def _resolve_gdi_add_font() -> Callable[[str, int], bool] | None:
    """Return a ``(path, flags) -> bool`` GDI registrar, or None off-Windows."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - font loading must never break the launcher
        return None

    def add_font(path: str, flags: int) -> bool:
        try:
            return bool(gdi32.AddFontResourceExW(path, flags, 0))
        except Exception:  # noqa: BLE001 - a bad TTF must not break the launcher
            return False

    return add_font


def load_private_fonts(
    *,
    font_dirs: Sequence[Path] | None = None,
    add_font: Callable[[str, int], bool] | None = None,
) -> list[str]:
    """Register the design TTFs process-privately; return the loaded file names.

    Uses the first candidate directory that contains any of :data:`FONT_FILES`.
    No-op (empty list) on non-Windows, when GDI is unavailable, or when no font
    files exist anywhere — missing files are tolerated silently by design.
    """
    registrar = add_font if add_font is not None else _resolve_gdi_add_font()
    if registrar is None:
        return []
    for directory in font_dirs if font_dirs is not None else _font_dirs():
        found = [directory / name for name in FONT_FILES if (directory / name).is_file()]
        if not found:
            continue
        return [path.name for path in found if registrar(str(path), FR_PRIVATE)]
    return []
