"""Cross-process ownership tests for the single physical AC rig (#555)."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import tools.ac_harness.rig_lock as rig_lock_module
from tools.ac_harness.rig_lock import (
    RigSessionBusy,
    RigSessionLock,
    RigSessionOwner,
    default_rig_session_lock_path,
    read_rig_session_owner,
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
import os
import sys
import time
from pathlib import Path
from tools.ac_harness.rig_lock import RigSessionLock, RigSessionOwner

path, ready, release = map(Path, sys.argv[1:])
owner = RigSessionOwner(
    pid=os.getpid(), cwd='peer-worktree', car='peer-car', track='peer-track'
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

        assert exc_info.value.owner["pid"] == proc.pid
        assert exc_info.value.owner["car"] == "peer-car"
        assert "peer-worktree" in str(exc_info.value)
        assert read_rig_session_owner(path) == {
            "pid": proc.pid,
            "cwd": "peer-worktree",
            "car": "peer-car",
            "track": "peer-track",
            "started_at": None,
            "session_kind": None,
            "phase": None,
        }
    finally:
        release.touch()
        proc.wait(timeout=5)
    assert read_rig_session_owner(path) is None


def test_lock_is_released_for_next_owner(tmp_path: Path) -> None:
    path = tmp_path / "rig-session.lock"
    with RigSessionLock(path, owner=_owner(1)):
        pass
    with RigSessionLock(path, owner=_owner(2)):
        assert path.exists()


def test_owner_phase_update_is_visible_while_lock_remains_held(tmp_path: Path) -> None:
    path = tmp_path / "rig-session.lock"
    lock = RigSessionLock(
        path,
        owner=RigSessionOwner(
            pid=os.getpid(),
            cwd="game-point",
            session_kind="resilient_launch",
            phase="stabilizing",
        ),
    )

    with lock:
        assert read_rig_session_owner(path)["phase"] == "stabilizing"  # type: ignore[index]
        lock.set_phase("stable")
        assert read_rig_session_owner(path)["phase"] == "stable"  # type: ignore[index]


def test_stale_metadata_with_reused_live_pid_is_not_authoritative(tmp_path: Path) -> None:
    path = tmp_path / "rig-session.lock"
    stale = _owner(os.getpid()).to_dict()
    path.write_bytes(b"\0" + json.dumps(stale).encode("utf-8"))

    assert read_rig_session_owner(path) is None


def test_windows_status_probe_never_acquires_the_exclusive_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rig-session.lock"
    path.write_bytes(b"\0")

    def fail_lock(_lock_file) -> None:
        raise AssertionError("Windows status must use a contend-only byte read")

    monkeypatch.setattr(rig_lock_module.sys, "platform", "win32")
    monkeypatch.setattr(RigSessionLock, "_lock_byte", fail_lock)

    assert read_rig_session_owner(path) is None


def test_contended_lock_without_metadata_returns_unknown_owner(tmp_path: Path) -> None:
    path = tmp_path / "rig-session.lock"
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    script = """
import os
import sys
import time
from pathlib import Path
from tools.ac_harness.rig_lock import RigSessionLock, RigSessionOwner

path, ready, release = map(Path, sys.argv[1:])
lock = RigSessionLock(path, owner=RigSessionOwner(pid=os.getpid(), cwd='peer-worktree'))
lock.acquire()
assert lock._file is not None
lock._file.seek(1)
lock._file.truncate()
lock._file.flush()
ready.touch()
try:
    while not release.exists():
        time.sleep(0.01)
finally:
    lock.release()
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
        assert read_rig_session_owner(path) == {"cwd": "unknown"}
    finally:
        release.touch()
        proc.wait(timeout=5)


def test_status_probe_reports_unknown_when_lock_file_cannot_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rig-session.lock"

    def fail_open(_path: Path, *_args, **_kwargs):
        raise PermissionError("sharing violation")

    monkeypatch.setattr(Path, "open", fail_open)

    assert read_rig_session_owner(path) == {"cwd": "unknown"}


def test_status_probe_reports_unknown_on_non_contention_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rig-session.lock"
    path.write_bytes(b"\0")

    def fail_lock(_lock_file) -> None:
        raise OSError(errno.EIO, "device failure")

    monkeypatch.setattr(RigSessionLock, "_lock_byte", fail_lock)

    assert read_rig_session_owner(path) == {"cwd": "unknown"}


def test_lock_validates_timing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timeout"):
        RigSessionLock(tmp_path / "lock", owner=_owner(1), timeout=-1)
    with pytest.raises(ValueError, match="poll interval"):
        RigSessionLock(tmp_path / "lock", owner=_owner(1), poll_interval=0)
    for invalid in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="timeout"):
            RigSessionLock(tmp_path / "lock", owner=_owner(1), timeout=invalid)
        with pytest.raises(ValueError, match="poll interval"):
            RigSessionLock(tmp_path / "lock", owner=_owner(1), poll_interval=invalid)


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
