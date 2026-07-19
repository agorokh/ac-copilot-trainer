"""Shared Windows foreground helpers for Content Manager launch flows."""

from __future__ import annotations


def minimize_foreground_window() -> None:  # pragma: no cover - rig-only
    """Best-effort: minimize the non-AC/CM window holding foreground before a CM launch.

    A foreground window that is not Content Manager or Assetto Corsa makes CM's auto-start race
    lose almost every time on the rig. AC and CM themselves are deliberately left untouched.
    """

    import ctypes

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 255)
        title = (buf.value or "").lower()
        if "assetto corsa" in title or "content manager" in title:
            return
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
    except Exception:  # noqa: BLE001 - best-effort; the launch retry covers a miss
        return
