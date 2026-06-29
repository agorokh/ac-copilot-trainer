"""Build helper for the AC Copilot Game Point PyInstaller artifact."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.rig_launcher.supervisor import build_pyinstaller_args


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    cmd = [sys.executable, "-m", "PyInstaller", *build_pyinstaller_args(project_root)]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
