"""Tests for the package-time build-identity bake (issue #569).

All git interaction and the wall clock are injected — no test shells out to git or
depends on the checkout's commit, so the suite is deterministic anywhere.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tools.ai_sidecar import observability as obs
from tools.rig_launcher.build_info import (
    BUILD_COMMIT_ENV,
    BUILD_TIME_ENV,
    RUNTIME_HOOK_NAME,
    UNKNOWN,
    BuildInfo,
    render_runtime_hook,
    resolve_build_info,
    write_runtime_hook,
)
from tools.rig_launcher.supervisor import build_pyinstaller_args

_STAMP = datetime(2026, 7, 14, 8, 30, 45, tzinfo=UTC)
_STAMP_TEXT = "2026-07-14T08:30:45Z"


@pytest.fixture
def isolated_build_env() -> Iterator[None]:
    """Save/restore the baked env vars around tests that execute the generated hook.

    The hook's whole job is to mutate the real ``os.environ`` (it does its own ``import
    os``, so a stub global cannot intercept it) — monkeypatch cannot undo a key it never
    recorded, so own the save/restore here.
    """
    saved = {name: os.environ.get(name) for name in (BUILD_COMMIT_ENV, BUILD_TIME_ENV)}
    for name in saved:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _fake_run(outputs: dict[str, str], *, returncode: int = 0) -> Any:
    """subprocess.run stub keyed by the git subcommand."""

    def _run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        key = cmd[1]  # cmd is ["git", "<subcommand>", ...]
        return subprocess.CompletedProcess(cmd, returncode, outputs.get(key, ""), "")

    return _run


def test_resolve_build_info_reads_commit_and_stamps_package_time(tmp_path: Path) -> None:
    info = resolve_build_info(
        tmp_path,
        run=_fake_run({"rev-parse": "abc1234", "status": ""}),
        now=lambda: _STAMP,
    )
    assert info == BuildInfo(commit="abc1234", build_time=_STAMP_TEXT)


def test_resolve_build_info_marks_dirty_worktree(tmp_path: Path) -> None:
    """The EXE is packaged from the working tree, not from HEAD: a bare hash would claim
    an identity the bundled code does not have."""
    info = resolve_build_info(
        tmp_path,
        run=_fake_run({"rev-parse": "abc1234", "status": " M tools/rig_launcher/app.py"}),
        now=lambda: _STAMP,
    )
    assert info.commit == "abc1234-dirty"


def test_resolve_build_info_falls_back_to_unknown_without_git(tmp_path: Path) -> None:
    def _explode(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("git not on PATH")

    info = resolve_build_info(tmp_path, run=_explode, now=lambda: _STAMP)
    assert info.commit == UNKNOWN
    # A checkout without git must still package, and still report an honest build time.
    assert info.build_time == _STAMP_TEXT


def test_resolve_build_info_falls_back_to_unknown_on_git_failure(tmp_path: Path) -> None:
    """Non-zero git (e.g. not a repo) must not be mistaken for a commit."""
    info = resolve_build_info(
        tmp_path,
        run=_fake_run({"rev-parse": "fatal: not a git repository"}, returncode=128),
        now=lambda: _STAMP,
    )
    assert info.commit == UNKNOWN


def test_write_runtime_hook_returns_path_and_overwrites(tmp_path: Path) -> None:
    first = write_runtime_hook(tmp_path / "build", BuildInfo("aaaaaaa", _STAMP_TEXT))
    assert first.name == RUNTIME_HOOK_NAME
    assert first.is_file()

    second = write_runtime_hook(tmp_path / "build", BuildInfo("bbbbbbb", _STAMP_TEXT))
    # A stale hook from a previous build would bake the previous commit into this one.
    assert second == first
    assert "bbbbbbb" in first.read_text(encoding="utf-8")
    assert "aaaaaaa" not in first.read_text(encoding="utf-8")


@pytest.mark.usefixtures("isolated_build_env")
def test_runtime_hook_bakes_into_environment_and_operator_env_still_wins() -> None:
    code = compile(
        render_runtime_hook(BuildInfo("abc1234", _STAMP_TEXT)), RUNTIME_HOOK_NAME, "exec"
    )

    exec(code, {})
    assert os.environ[BUILD_COMMIT_ENV] == "abc1234"
    assert os.environ[BUILD_TIME_ENV] == _STAMP_TEXT

    # setdefault, not assignment: a field override survives the bake.
    os.environ[BUILD_COMMIT_ENV] = "operator"
    exec(code, {})
    assert os.environ[BUILD_COMMIT_ENV] == "operator"


def test_build_pyinstaller_args_bakes_build_identity(tmp_path: Path) -> None:
    args = build_pyinstaller_args(
        tmp_path,
        onefile=True,
        windowed=True,
        build_info=BuildInfo("abc1234", _STAMP_TEXT),
        hook_dir=tmp_path / "build",
    )
    assert "--runtime-hook" in args
    hook = Path(args[args.index("--runtime-hook") + 1])
    assert hook.is_file(), "PyInstaller would fail on a --runtime-hook path that does not exist"
    body = hook.read_text(encoding="utf-8")
    assert "abc1234" in body
    assert _STAMP_TEXT in body


def test_build_pyinstaller_args_defaults_hook_dir_under_project_root(tmp_path: Path) -> None:
    """Both packaging entrypoints (build.py, app.main --build-exe) call this with only a
    project_root, so the default must land somewhere writable and gitignored."""
    build_pyinstaller_args(
        tmp_path,
        build_info=BuildInfo("abc1234", _STAMP_TEXT),
    )
    assert (tmp_path / "build" / RUNTIME_HOOK_NAME).is_file()


@pytest.mark.usefixtures("isolated_build_env")
def test_baked_hook_is_what_observability_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The contract that makes #569 work end to end: whatever the hook bakes into the
    environment is exactly what /health reports. Guards against the bake and the reader
    drifting apart on env-var name or timestamp format."""
    hook = write_runtime_hook(tmp_path / "build", BuildInfo("abc1234", _STAMP_TEXT))
    monkeypatch.setattr(obs, "_build_commit_cache", None)
    monkeypatch.setattr(obs, "_build_time_cache", None)

    # Execute the generated hook exactly as PyInstaller's bootloader would: against the
    # real os.environ, before any sidecar code reads it.
    exec(compile(hook.read_text(encoding="utf-8"), str(hook), "exec"), {})

    assert obs.build_commit() == "abc1234"
    assert obs.build_time() == _STAMP_TEXT
