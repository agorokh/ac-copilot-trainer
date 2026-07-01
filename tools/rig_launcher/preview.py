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
import time

from tools.rig_launcher.supervisor import GamePointStatus, ProbeResult
from tools.rig_launcher.view import build_launcher_view

_NOOP_ACTIONS = {
    key: (lambda: None) for key in ("start", "refresh", "logs", "settings", "setup_diff")
}


def demo_status() -> GamePointStatus:
    """A representative 'all live, SimHub absent' snapshot matching the design mock."""
    return GamePointStatus(
        generated_at=0.0,
        sidecar=ProbeResult("sidecar", True, "healthy", "peers=1 screen_peers=1"),
        screen=ProbeResult("screen", True, "connected", "screen_peers=1"),
        hotspot=ProbeResult("hotspot", True, "on", "state=On clients=1"),
        voice=ProbeResult("voice", True, "enabled", "backend=sounddevice"),
        simhub=ProbeResult("simhub", True, "absent", "executable not found"),
        log_path="sidecar.log",
        status_path=r"%LOCALAPPDATA%\AC Copilot Trainer\GamePoint\status.json",
    )


def _capture_region(x: int, y: int, width: int, height: int, out_path: str) -> None:
    script = (
        "Add-Type -AssemblyName System.Drawing;"
        f"$b=New-Object System.Drawing.Bitmap {width},{height};"
        "$g=[System.Drawing.Graphics]::FromImage($b);"
        f"$g.CopyFromScreen({x},{y},0,0,$b.Size);"
        f"$b.Save('{out_path}',[System.Drawing.Imaging.ImageFormat]::Png);"
        "$g.Dispose();$b.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
    )


def render(out_path: str, *, status: GamePointStatus | None = None) -> int:
    """Show the themed launcher and save its client rectangle to ``out_path``."""
    import tkinter as tk

    root = tk.Tk()
    root.title("AC Copilot Game Point")
    root.geometry("660x440+140+140")
    view = build_launcher_view(root, actions=_NOOP_ACTIONS, status_path=demo_status().status_path)
    view.update(status or demo_status())
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    for _ in range(6):
        root.update()
        time.sleep(0.08)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    width, height = root.winfo_width(), root.winfo_height()
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
    args = parser.parse_args(argv)
    return render(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
