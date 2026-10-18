"""Native window chrome for the Game Point launcher: app icon + dark title bar (#881).

The launcher keeps the **native** Windows frame and recolours it through DWM
instead of drawing its own title bar. A Tk ``overrideredirect`` frame would lose
the taskbar button, Alt+Tab, Aero snap, the native resize borders and the
system menu, and getting them back means re-implementing each by hand. DWM
gives the same look with none of that risk:

* ``DWMWA_USE_IMMERSIVE_DARK_MODE`` — dark caption + dark caption buttons
  (Windows 10 20H1+; attribute 19 on the earlier 1809–1909 builds).
* ``DWMWA_CAPTION_COLOR`` / ``DWMWA_TEXT_COLOR`` / ``DWMWA_BORDER_COLOR`` —
  paint the caption exactly the Racing Atelier carbon ground with chalk text and
  an edge-tone border, so the title bar is continuous with the window body
  (Windows 11 22000+; older builds keep the plain dark caption).

Every call is best-effort: off-Windows, on an old build, or when an attribute is
rejected, the window simply keeps whatever chrome it has — chrome must never
stop the launcher from opening.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.rig_launcher import theme
from tools.rig_launcher.icon import ICON_PATH

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
#: The pre-20H1 (builds 17763–18363) id of the same attribute.
DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY = 19
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

#: Taskbar identity for a source (``python -m``) launch; see :func:`set_app_user_model_id`.
APP_USER_MODEL_ID = "RacingAtelier.ACCopilot.GamePoint"

# SetWindowPos flags: re-evaluate the frame without moving, sizing, reordering or
# activating, so a caption recoloured after the window mapped repaints at once.
_SWP_FRAME_REFRESH = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020

SetAttribute = Callable[[int, int, int], bool]


def colorref(hex_color: str) -> int:
    """``#RRGGBB`` -> Win32 ``COLORREF`` (``0x00BBGGRR``)."""
    value = hex_color.lstrip("#")
    red, green, blue = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


#: (attribute, value) pairs applied after dark mode, in order.
CAPTION_COLORS: tuple[tuple[int, int], ...] = (
    (DWMWA_CAPTION_COLOR, colorref(theme.CARBON)),
    (DWMWA_TEXT_COLOR, colorref(theme.CHALK)),
    (DWMWA_BORDER_COLOR, colorref(theme.EDGE)),
)


def _dwm_set_attribute() -> SetAttribute | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        dwmapi = ctypes.windll.dwmapi  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - no DWM means no recolouring, never a crash
        return None

    def set_attribute(hwnd: int, attribute: int, value: int) -> bool:
        data = ctypes.c_int(value)
        try:
            result = dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)
            )
        except Exception:  # noqa: BLE001
            return False
        return result == 0  # S_OK

    return set_attribute


def _refresh_frame(hwnd: int) -> None:
    try:
        import ctypes

        ctypes.windll.user32.SetWindowPos(  # type: ignore[attr-defined]
            ctypes.c_void_p(hwnd), None, 0, 0, 0, 0, _SWP_FRAME_REFRESH
        )
    except Exception:  # noqa: BLE001 - a missed repaint fixes itself on next activation
        return


def window_handle(window: Any) -> int | None:
    """The top-level (frame) HWND Tk wraps around ``window``'s client area."""
    try:
        window.update_idletasks()
        return int(str(window.wm_frame()), 16) or None
    except Exception:  # noqa: BLE001
        return None


def apply_dark_title_bar(
    window: Any,
    *,
    set_attribute: SetAttribute | None = None,
    hwnd: int | None = None,
    refresh: Callable[[int], None] | None = None,
) -> bool:
    """Turn ``window``'s native caption dark and Atelier-coloured; True if dark mode took."""
    setter = set_attribute if set_attribute is not None else _dwm_set_attribute()
    if setter is None:
        return False
    handle = hwnd if hwnd is not None else window_handle(window)
    if not handle:
        return False
    dark = setter(handle, DWMWA_USE_IMMERSIVE_DARK_MODE, 1) or setter(
        handle, DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY, 1
    )
    for attribute, value in CAPTION_COLORS:
        setter(handle, attribute, value)  # unsupported before Windows 11: ignored
    (refresh or _refresh_frame)(handle)
    return dark


def apply_window_icon(window: Any, icon_path: Path = ICON_PATH) -> bool:
    """Set the Racing Atelier icon on ``window`` (and, for the root, every later Toplevel)."""
    if sys.platform != "win32" or not icon_path.is_file():
        return False
    try:
        if window.winfo_toplevel() is window and window.master is None:
            window.iconbitmap(default=str(icon_path))
        else:
            window.iconbitmap(str(icon_path))
    except Exception:  # noqa: BLE001 - a missing icon must never block the window
        return False
    return True


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """Give a source launch its own taskbar identity so the button shows our icon.

    Only for ``python -m tools.rig_launcher``: without it, Windows groups the window
    under ``python.exe`` and shows the Python icon. The frozen EXE deliberately
    skips this — its own exe identity is what the Desktop shortcut and any taskbar
    pin point at, and a custom id would split the running window from that pin.
    """
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return False
    try:
        import ctypes

        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        return shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id)) == 0
    except Exception:  # noqa: BLE001
        return False


def apply_window_chrome(window: Any) -> None:
    """Icon + dark caption for one launcher window. Safe to call on any platform."""
    apply_window_icon(window)
    apply_dark_title_bar(window)
