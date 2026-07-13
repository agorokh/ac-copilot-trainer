"""Cross-process ownership tests for the single physical AC rig (#555)."""

from __future__ import annotations

import errno
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.ac_harness.rig_lock import (
    RigSessionBusy,
    RigSessionLock,
    RigSessionOwner,
    default_rig_session_lock_path,
)


def _owner(pid: int) -> RigSessionOwner:
    return RigSessionOwner(
        pid=pid,
        cwd=f"worktree-{pid}",
        car="ks_audi_r8_lms",
        track="magione",
        started_at="2026-07-13T12:00:00Z",
    )


def test_default_lock_path_is_shared_app_data_not_worktree(tmp_path: Path) -> None:
    path = default_rig_session_lock_path(local_app_data=tmp_path)
    assert path == tmp_path / "AC Copilot Trainer" / "Harness" / "rig-session.lock"


def test_second_process_fails_busy_with_owner_metadata(tmp_path: Path) -> None:
    path = tmp_path / "rig-session.lock"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    script = """
import sys
import time
from pathlib import Path
from tools.ac_harness.rig_lock import RigSessionLock, RigSessionOwner

path, ready, release = map(Path, sys.argv[1:])
owner = RigSessionOwner(
    pid=4242, cwd='peer-worktree', car='peer-car', track='peer-track'
)
with RigSessionLock(path, owner=owner):
    ready.touch()
    while not release.exists():
        time.sleep(0.01)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(path), str(ready), str(release)], env=env
    )
    try:
        for _ in range(500):
            if ready.exists():
                break
            if proc.poll() is not None:
                raise AssertionError(f"lock-holder exited early: {proc.returncode}")
            time.sleep(0.01)
        assert ready.exists()

        with pytest.raises(RigSessionBusy) as exc_info:
            RigSessionLock(path, owner=_owner(9999)).acquire()

        assert exc_info.value.owner["pid"] == 4242
        assert exc_info.value.owner["car"] == "peer-car"
        assert "peer-worktree" in str(exc_info.value)
    finally:
        release.touch()
        proc.wait(timeout=5)


def test_lock_is_released_for_next_owner(tmp_path: Path) -> None:
    path = tmp_path / "rig-session.lock"
    with RigSessionLock(path, owner=_owner(1)):
        pass
    with RigSessionLock(path, owner=_owner(2)):
        assert path.exists()


def test_lock_validates_timing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timeout"):
        RigSessionLock(tmp_path / "lock", owner=_owner(1), timeout=-1)
    with pytest.raises(ValueError, match="poll interval"):
        RigSessionLock(tmp_path / "lock", owner=_owner(1), poll_interval=0)


def test_unexpected_lock_os_error_is_not_reported_as_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = RigSessionLock(tmp_path / "lock", owner=_owner(1))

    def fail_lock(_lock_file) -> None:
        raise OSError(errno.EIO, "device failure")

    monkeypatch.setattr(lock, "_lock_byte", fail_lock)
    with pytest.raises(OSError, match="device failure") as exc_info:
        lock.acquire()
    assert exc_info.value.errno == errno.EIO
