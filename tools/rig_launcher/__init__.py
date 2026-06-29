"""AC Copilot Game Point launcher and supervisor."""

from tools.rig_launcher.install import (
    ShortcutInstallResult,
    default_exe_path,
    install_desktop_shortcut,
)
from tools.rig_launcher.settings import LauncherSettings, ensure_settings_file
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointStatus,
    GamePointSupervisor,
    LauncherPaths,
    ProbeResult,
    build_pyinstaller_args,
)

__all__ = [
    "GamePointConfig",
    "GamePointStatus",
    "GamePointSupervisor",
    "LauncherPaths",
    "LauncherSettings",
    "ProbeResult",
    "ShortcutInstallResult",
    "build_pyinstaller_args",
    "default_exe_path",
    "ensure_settings_file",
    "install_desktop_shortcut",
]
