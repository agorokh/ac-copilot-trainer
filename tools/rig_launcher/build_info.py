"""Package-time build identity for the frozen Game Point EXE (issue #569).

``observability.build_commit`` / ``build_time`` resolve the running build's identity
from ``AC_COPILOT_BUILD_COMMIT`` / ``AC_COPILOT_BUILD_TIME`` first, then fall back to
``git`` for dev checkouts. A frozen PyInstaller EXE runs from the Game Point user dir
with no ``.git``, so without a bake it reports ``"unknown"`` — the secondary "*which*
build is running" identifier is lost (the *primary* stale-build signal, the ``/health``
``endpoints`` set plus the ``--self-test`` route gate, is compiled in and needs neither).

This module closes that gap by generating a PyInstaller **runtime hook** at package
time. PyInstaller executes user runtime hooks *before* the entry script, so the baked
values are in ``os.environ`` by the time any sidecar code reads them — the frozen build
resolves its identity through the exact same env-first path a dev checkout does, with no
``sys.frozen`` branch in the reader. Because the frozen launcher re-spawns *itself* for
the sidecar child (``supervisor.sidecar_command`` → ``[sys.executable, "--sidecar-child"]``),
the hook runs in the child too and the bake needs no propagation logic.

``setdefault`` (not assignment): an operator-set env var still wins, so a build can be
overridden in the field for debugging.

Env var names are kept literal here rather than imported from ``tools.ai_sidecar``, so the
launcher stays decoupled from the sidecar package — the same convention
``supervisor._probe_endpoint_status`` uses for the auth header.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Mirrors ``tools.ai_sidecar.observability`` — keep in lockstep.
BUILD_COMMIT_ENV = "AC_COPILOT_BUILD_COMMIT"
BUILD_TIME_ENV = "AC_COPILOT_BUILD_TIME"

#: Filename of the generated hook. ``pyi_rth_`` matches PyInstaller's own convention.
RUNTIME_HOOK_NAME = "pyi_rth_ac_copilot_build_info.py"

#: Reported when git cannot answer (no repo, no git on PATH, shallow/empty checkout).
UNKNOWN = "unknown"


@dataclass(frozen=True)
class BuildInfo:
    """Identity of a packaged build, resolved once at package time."""

    commit: str
    build_time: str


def _git(
    args: list[str],
    project_root: Path,
    run: Callable[..., Any],
) -> str:
    """Best-effort ``git`` stdout, anchored to ``project_root``. ``""`` on any failure.

    Build identity is a nice-to-have: a checkout without git (or an export tarball) must
    still package successfully and honestly report ``UNKNOWN`` rather than fail the build.
    """
    try:
        completed = run(
            ["git", *args],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if getattr(completed, "returncode", 1) != 0:
        return ""
    return (completed.stdout or "").strip()


def resolve_build_info(
    project_root: Path,
    *,
    run: Callable[..., Any] = subprocess.run,
    now: Callable[[], datetime] | None = None,
) -> BuildInfo:
    """Resolve the commit + packaging timestamp to bake into the EXE.

    ``run`` / ``now`` are injected so ``build_pyinstaller_args`` stays testable without
    shelling out to git or reading the wall clock.

    The commit carries a ``-dirty`` suffix when the worktree has uncommitted changes:
    the EXE is packaged from the *working tree*, not from ``HEAD``, so a bare hash would
    claim an identity the bundled code does not have — defeating the point of the bake.
    ``build_time`` is when the package was built (the operator's ask on #569); the dev/
    source path instead reports the commit date, since there is no packaging event.
    """
    commit = _git(["rev-parse", "--short", "HEAD"], project_root, run)
    if commit and _git(["status", "--porcelain"], project_root, run):
        commit = f"{commit}-dirty"
    stamp = (now or (lambda: datetime.now(UTC)))()
    return BuildInfo(
        commit=commit or UNKNOWN,
        build_time=stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def render_runtime_hook(info: BuildInfo) -> str:
    """Source of the PyInstaller runtime hook that bakes ``info`` into the EXE's env.

    Values are embedded with ``repr`` so a hostile or merely odd git output cannot break
    out of the literal.

    Deliberately not ``os.environ.setdefault``: an env var that is *set but empty* would
    keep setdefault from baking, while the reader (``observability.build_commit``) strips
    and treats empty as unset — so the EXE would fall back to ``git``/``"unknown"``. The
    emitted guard mirrors the reader's truthiness check exactly, so the bake and the
    reader agree on what "already set" means. A non-empty operator value still wins.
    """
    return (
        "# Generated at package time by tools.rig_launcher.build_info (issue #569).\n"
        "# PyInstaller runs runtime hooks BEFORE the entry script, so these are set\n"
        "# before any sidecar code reads them. A real operator value still wins; an\n"
        "# empty one does not (it would strand the frozen EXE on 'unknown').\n"
        "import os\n"
        "\n"
        "for _name, _baked in (\n"
        f"    ({BUILD_COMMIT_ENV!r}, {info.commit!r}),\n"
        f"    ({BUILD_TIME_ENV!r}, {info.build_time!r}),\n"
        "):\n"
        "    if not os.environ.get(_name, '').strip():\n"
        "        os.environ[_name] = _baked\n"
    )


def write_runtime_hook(directory: Path, info: BuildInfo) -> Path:
    """Write the runtime hook into ``directory`` and return its path.

    Always overwrites: a stale hook left from a previous build would bake the previous
    commit into this one.
    """
    directory.mkdir(parents=True, exist_ok=True)
    hook = directory / RUNTIME_HOOK_NAME
    hook.write_text(render_runtime_hook(info), encoding="utf-8")
    return hook
