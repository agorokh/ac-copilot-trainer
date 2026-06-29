"""Windows install helpers for the AC Copilot Game Point launcher."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

EXE_NAME = "AC-Copilot-Game-Point.exe"
SHORTCUT_NAME = "AC Copilot Game Point.lnk"


@dataclass(frozen=True)
class ShortcutInstallResult:
    """Resolved paths for a created or refreshed Desktop shortcut."""

    shortcut_path: Path
    target_path: Path
    working_directory: Path


def default_exe_path(project_root: Path) -> Path:
    """Return the standard packaged launcher path under the repository root."""
    return project_root / "dist" / EXE_NAME


def install_desktop_shortcut(
    target_path: Path,
    *,
    working_directory: Path,
    shortcut_path: Path | None = None,
    description: str = "AC Copilot Game Point launcher",
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    env: Mapping[str, str] | None = None,
    require_windows: bool = True,
) -> ShortcutInstallResult:
    """Create or update the Windows Desktop shortcut for the packaged launcher."""
    if require_windows and os.name != "nt":
        raise RuntimeError("Desktop shortcut install is supported on Windows only.")

    target = target_path.expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(
            f"Launcher exe not found at {target}. Build it with "
            "python -m tools.rig_launcher --build-exe first."
        )

    workdir = working_directory.expanduser().resolve()
    if not workdir.is_dir():
        raise FileNotFoundError(f"Working directory not found at {workdir}.")

    shortcut = shortcut_path.expanduser().resolve() if shortcut_path is not None else None
    if shortcut is not None:
        shortcut.parent.mkdir(parents=True, exist_ok=True)

    proc_env = dict(os.environ if env is None else env)
    proc_env.update(
        {
            "AC_COPILOT_SHORTCUT_TARGET": str(target),
            "AC_COPILOT_SHORTCUT_WORKDIR": str(workdir),
            "AC_COPILOT_SHORTCUT_DESCRIPTION": description,
            "AC_COPILOT_SHORTCUT_PATH": str(shortcut or ""),
            "AC_COPILOT_SHORTCUT_NAME": SHORTCUT_NAME,
        }
    )
    proc = run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _SHORTCUT_SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        env=proc_env,
    )
    if proc.returncode != 0:
        detail = _short(proc.stderr or proc.stdout)
        raise RuntimeError(f"Desktop shortcut install failed: {detail}")

    created = shortcut or _path_from_stdout(proc.stdout)
    if created is None:
        raise RuntimeError("Desktop shortcut install did not report a shortcut path.")
    if not created.is_file():
        raise RuntimeError(f"Desktop shortcut was not created at {created}.")
    return ShortcutInstallResult(created, target, workdir)


def _path_from_stdout(stdout: str) -> Path | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    return Path(lines[-1])


def _short(text: str, limit: int = 400) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "..."


_SHORTCUT_SCRIPT = "\n".join(
    [
        "$ErrorActionPreference = 'Stop'",
        "$shortcutPath = $env:AC_COPILOT_SHORTCUT_PATH",
        "if ([string]::IsNullOrWhiteSpace($shortcutPath)) {",
        "  $desktop = [Environment]::GetFolderPath('Desktop')",
        "  $shortcutPath = Join-Path $desktop $env:AC_COPILOT_SHORTCUT_NAME",
        "}",
        "$shell = New-Object -ComObject WScript.Shell",
        "$shortcut = $shell.CreateShortcut($shortcutPath)",
        "$shortcut.TargetPath = $env:AC_COPILOT_SHORTCUT_TARGET",
        "$shortcut.WorkingDirectory = $env:AC_COPILOT_SHORTCUT_WORKDIR",
        "$shortcut.Description = $env:AC_COPILOT_SHORTCUT_DESCRIPTION",
        '$shortcut.IconLocation = "$($env:AC_COPILOT_SHORTCUT_TARGET),0"',
        "$shortcut.Save()",
        "Write-Output $shortcutPath",
    ]
)
