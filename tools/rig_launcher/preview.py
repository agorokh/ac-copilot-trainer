"""Render the Racing Atelier launcher to a PNG for visual verification (epic #432).

This is a developer / verification tool, **not** part of the shipped launcher UI:
it builds the themed view with a representative ``GamePointStatus``, shows the
window, and grabs the window's client rectangle to a PNG via the Windows GDI
(``System.Drawing.CopyFromScreen`` through PowerShell — so no Pillow dependency).
It has no import-time side effects.

Usage::

    python -m tools.rig_launcher.preview --out launcher.png
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

from tools.rig_launcher.chrome import (
    apply_dark_title_bar,
    apply_window_icon,
    set_app_user_model_id,
    window_handle,
)
from tools.rig_launcher.fonts import load_private_fonts
from tools.rig_launcher.supervisor import GamePointStatus, ProbeResult
from tools.rig_launcher.view import build_launcher_view

_NOOP_ACTIONS = {
    key: (lambda: None)
    for key in (
        "start",
        "resilient_launch",
        "resilient_release",
        "refresh",
        "logs",
        "settings",
        "setup_diff",
    )
}


def demo_status() -> GamePointStatus:
    """A representative 'all live, SimHub absent' snapshot matching the design mock."""
    return GamePointStatus(
        generated_at=0.0,
        sidecar=ProbeResult("sidecar", True, "healthy", "peers=1 screen_peers=1"),
        screen=ProbeResult("screen", True, "connected", "screen_peers=1"),
        voice=ProbeResult("voice", True, "enabled", "backend=sounddevice"),
        simhub=ProbeResult("simhub", True, "absent", "executable not found"),
        log_path="sidecar.log",
        status_path=r"%LOCALAPPDATA%\AC Copilot Trainer\GamePoint\status.json",
    )


def _capture_region(x: int, y: int, width: int, height: int, out_path: str) -> None:
    # Escape single quotes so a path containing one can't break out of the PS string literal.
    safe_path = out_path.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Drawing;"
        f"$b=New-Object System.Drawing.Bitmap {width},{height};"
        "$g=[System.Drawing.Graphics]::FromImage($b);"
        f"$g.CopyFromScreen({x},{y},0,0,$b.Size);"
        f"$b.Save('{safe_path}',[System.Drawing.Imaging.ImageFormat]::Png);"
        "$g.Dispose();$b.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
    )


def _frame_bounds(window: object) -> tuple[int, int, int, int] | None:
    """Visible window bounds incl. the native caption (DWMWA_EXTENDED_FRAME_BOUNDS).

    None (the caller keeps the client-rect crop) off-Windows or when DWM is unavailable.
    """
    if sys.platform != "win32":
        return None
    hwnd = window_handle(window)
    if not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        extended_frame_bounds = 9
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(  # type: ignore[attr-defined]
            ctypes.c_void_p(hwnd), extended_frame_bounds, ctypes.byref(rect), ctypes.sizeof(rect)
        )
    except Exception:  # noqa: BLE001 - no DWM: fall back to the client crop
        return None
    if result != 0:
        return None
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def render(
    out_path: str, *, status: GamePointStatus | None = None, with_frame: bool = False
) -> int:
    """Show the themed launcher and save it to ``out_path``.

    By default only the client rectangle is captured (the design-gate crop);
    ``with_frame`` captures the whole window including the native dark caption.
    """
    import tkinter as tk

    load_private_fonts()  # register design faces so the capture matches the rig
    set_app_user_model_id()
    root = tk.Tk()
    root.title("AC Copilot Game Point")
    apply_window_icon(root)
    view = build_launcher_view(
        root, actions=_NOOP_ACTIONS, status_path=demo_status().status_path, port=8765
    )
    view.update(status or demo_status())
    view.fit_window()
    apply_dark_title_bar(root)
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    for _ in range(6):
        root.update()
        time.sleep(0.08)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    width, height = root.winfo_width(), root.winfo_height()
    if with_frame:
        bounds = _frame_bounds(root)
        if bounds is not None:
            x, y, width, height = bounds
    time.sleep(0.2)
    root.update()
    try:
        _capture_region(x, y, width, height, out_path)
    finally:
        root.destroy()
    print(f"wrote {out_path} ({width}x{height} at {x},{y})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the Racing Atelier launcher to PNG.")
    parser.add_argument("--out", required=True, help="Output PNG path.")
    parser.add_argument(
        "--frame", action="store_true", help="Include the native title bar in the capture."
    )
    args = parser.parse_args(argv)
    return render(args.out, with_frame=args.frame)


if __name__ == "__main__":
    raise SystemExit(main())
