"""Build helper for the AC Copilot Game Point PyInstaller artifact.

``pyinstaller_command`` is the one path both ``python -m tools.rig_launcher.build`` and
``python -m tools.rig_launcher --build-exe`` take, so the pre-Analysis checks below cannot drift
between them. They exist because the EXE used to depend on the build interpreter's ambient
site-packages (issue #893): a repo ``.venv`` build lacked the comtypes SpeechLib wrapper that a
long-lived system Python had cached, and PyInstaller only *warns* about a missing hidden import.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from tools.rig_launcher.supervisor import (
    FROZEN_REQUIRED_MODULES,
    FROZEN_REQUIRED_WINDOWS_MODULES,
    SAPI_SPEECHLIB_MODULE,
    build_pyinstaller_args,
)

# Exactly what pyttsx3.drivers.sapi5 does on import (CreateObject on a miss), so the build
# generates the same wrapper the driver would; then report where it landed.
_SPEECHLIB_PROBE = (
    "import pyttsx3.drivers.sapi5, importlib; "
    f"print(importlib.import_module({SAPI_SPEECHLIB_MODULE!r}).__file__)"
)


class FrozenBuildError(RuntimeError):
    """The build interpreter cannot produce a complete Game Point EXE."""


def missing_frozen_modules(
    *,
    platform: str = sys.platform,
    find: Callable[[str], object | None] = find_spec,
) -> list[str]:
    required = list(FROZEN_REQUIRED_MODULES)
    if platform == "win32":
        required.extend(FROZEN_REQUIRED_WINDOWS_MODULES)
    return [module for module in required if find(module) is None]


def ensure_sapi_speechlib(
    *,
    python: str = sys.executable,
    run: Callable[..., Any] = subprocess.run,
    find: Callable[[str], Any] = find_spec,
) -> Path:
    """Generate ``comtypes.gen.SpeechLib`` in this interpreter and return its path.

    Runs in a child interpreter so COM initialisation stays out of the build process. The
    wrapper must land in the comtypes package's own ``gen`` directory: when site-packages is
    read-only comtypes falls back to a per-user cache that PyInstaller's Analysis cannot see,
    which would silently drop it from the bundle again.
    """
    proc = run(
        [python, "-c", _SPEECHLIB_PROBE],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise FrozenBuildError(
            f"could not generate {SAPI_SPEECHLIB_MODULE} for the pyttsx3 SAPI5 voice "
            f"({detail[-1] if detail else f'exit {proc.returncode}'})"
        )
    lines = (proc.stdout or "").strip().splitlines()
    if not lines:
        raise FrozenBuildError(f"{SAPI_SPEECHLIB_MODULE} probe printed no module path")
    generated = Path(lines[-1])
    spec = find("comtypes")
    locations = list(getattr(spec, "submodule_search_locations", None) or [])
    gen_dirs = [Path(location) / "gen" for location in locations]
    if not any(_same_path(generated.parent, gen_dir) for gen_dir in gen_dirs):
        raise FrozenBuildError(
            f"{SAPI_SPEECHLIB_MODULE} was generated at {generated}, outside the comtypes "
            f"package ({', '.join(map(str, gen_dirs)) or 'not found'}); PyInstaller would not "
            "bundle it. Build from an interpreter whose site-packages is writable."
        )
    return generated


def prepare_frozen_build(
    *,
    platform: str = sys.platform,
    find: Callable[[str], Any] = find_spec,
    speechlib: Callable[[], Path] = ensure_sapi_speechlib,
) -> None:
    missing = missing_frozen_modules(platform=platform, find=find)
    if missing:
        raise FrozenBuildError(
            f"missing {', '.join(missing)} in {sys.executable}; "
            'run `pip install -e ".[launcher]"` in this interpreter first'
        )
    if platform == "win32":
        speechlib()


def pyinstaller_command(
    project_root: Path,
    *,
    prepare: Callable[[], None] = prepare_frozen_build,
) -> list[str]:
    prepare()
    return [sys.executable, "-m", "PyInstaller", *build_pyinstaller_args(project_root)]


def run_build(project_root: Path) -> int:
    try:
        cmd = pyinstaller_command(project_root)
    except FrozenBuildError as exc:
        print(f"Game Point build aborted: {exc}", file=sys.stderr)
        return 2
    return subprocess.call(cmd)


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def main() -> int:
    return run_build(Path(__file__).resolve().parents[2])


if __name__ == "__main__":
    raise SystemExit(main())
