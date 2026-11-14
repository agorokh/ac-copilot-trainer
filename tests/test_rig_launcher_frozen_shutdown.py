"""Frozen sidecar teardown follows owned handles through the bootloader's exit."""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import tools.rig_launcher.supervisor as module
from tools.rig_launcher.supervisor import (
    GamePointConfig,
    GamePointSupervisor,
    LauncherPaths,
    ProbeResult,
)


class Process:
    def __init__(self, pid, exe, created, events):
        self.pid = pid
        self.exe = exe
        self.created = created
        self.events = events
        self.alive = True
        self.stubborn = False
        self.closed = False

    def identity(self):
        # Identity must be captured while live; a failed stop must retain that evidence.
        if not self.alive:
            raise OSError("image query unavailable after exit")
        return SimpleNamespace(pid=self.pid, exe=self.exe, created_filetime=self.created)

    def exited(self):
        return not self.alive

    def terminate(self):
        self.events.append(("terminate", self.pid))
        if self.stubborn:
            raise OSError("access denied")
        self.alive = False

    def close(self):
        self.closed = True

    def poll(self):
        return None if self.alive else 0

    def wait(self, timeout=None):
        assert not self.alive
        return 0

    def kill(self):
        self.terminate()


def owned_supervisor(tmp_path, monkeypatch, *, run=None):
    events = []
    exe = str(tmp_path / "gamepoint.exe")
    processes = {
        101: Process(101, exe, 1000, events),
        102: Process(102, exe, 1001, events),
        103: Process(103, exe, 1002, events),
        201: Process(201, exe, 900, events),  # same executable, unrelated ownership
    }
    parents = {101: 99, 102: 101, 103: 102, 201: 99}

    def bind(pid):
        events.append(("bind", pid))
        return processes[pid]

    def default_run(command, **_kwargs):
        events.append(("taskkill", command))
        # Reproduce the defect: bootloader exits while its Python server remains alive.
        processes[101].alive = False
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "_bind_windows_process", bind)
    monkeypatch.setattr(module, "_windows_process_parents", lambda: dict(parents))
    supervisor = GamePointSupervisor(
        GamePointConfig(paths=LauncherPaths(tmp_path)),
        frozen=True,
        python_executable=exe,
        environ={},
        popen=lambda *_args, **_kwargs: processes[101],
        run=run or default_run,
    )
    monkeypatch.setattr(supervisor, "preflight", lambda: [])
    monkeypatch.setattr(
        supervisor, "_read_health", lambda: ProbeResult("sidecar", False, "not_running")
    )
    assert supervisor.start_sidecar().state == "starting"
    return supervisor, processes, parents, events


def test_owned_descendants_are_bound_before_bootloader_exit_and_verified(tmp_path, monkeypatch):
    supervisor, processes, _, events = owned_supervisor(tmp_path, monkeypatch)
    assert supervisor.stop_sidecar(timeout=0).state == "stopped"
    kill_index = next(i for i, event in enumerate(events) if event[0] == "taskkill")
    assert events[:kill_index] == [("bind", 101), ("bind", 102), ("bind", 103)]
    assert events[kill_index][1] == ["taskkill", "/F", "/T", "/PID", "101"]
    assert all(not processes[pid].alive and processes[pid].closed for pid in (101, 102, 103))
    assert processes[201].alive and not processes[201].closed
    assert supervisor._sidecar_process is None
    assert supervisor._sidecar_family == {}


@pytest.mark.parametrize("failure", ["missing_taskkill", "nonzero_taskkill"])
def test_taskkill_failure_falls_back_to_exact_retained_handles(tmp_path, monkeypatch, failure):
    def failed_run(command, **_kwargs):
        if failure == "missing_taskkill":
            raise FileNotFoundError("taskkill unavailable")
        return subprocess.CompletedProcess(command, 1, "", "access denied")

    supervisor, processes, _, _ = owned_supervisor(tmp_path, monkeypatch, run=failed_run)
    assert supervisor.stop_sidecar(timeout=0).ok
    assert all(not processes[pid].alive for pid in (101, 102, 103))
    assert processes[201].alive


def test_living_descendant_is_stop_failed_and_ownership_survives_retry(tmp_path, monkeypatch):
    supervisor, processes, _, _ = owned_supervisor(tmp_path, monkeypatch)
    processes[102].stubborn = True
    result = supervisor.stop_sidecar(timeout=0)
    assert not result.ok and result.state == "stop_failed"
    assert "102" in result.detail
    assert not processes[101].alive and processes[102].alive
    assert supervisor._sidecar_process is processes[101]
    assert not processes[102].closed
    assert supervisor._sidecar_process_status().state == "stop_failed"
    assert supervisor.start_sidecar().state == "stop_failed"  # never discard orphan ownership.
    # A server that remains healthy must not hide the failed teardown on the UI's next poll.
    monkeypatch.setattr(supervisor, "preflight", lambda *_args: [])
    monkeypatch.setattr(
        supervisor,
        "_read_health_payload",
        lambda: (ProbeResult("sidecar", True, "running"), {}),
    )
    for method in (
        "probe_voice",
        "probe_practice_drill",
        "probe_simhub",
        "probe_tablet",
        "_resilient_process_status",
        "probe_keypad",
    ):
        monkeypatch.setattr(
            supervisor, method, lambda *_args, **_kwargs: ProbeResult("unused", True, "disabled")
        )
    assert supervisor.poll_status().sidecar.state == "stop_failed"
    processes[102].stubborn = False
    assert supervisor.stop_sidecar(timeout=0).state == "stopped"
    assert not processes[102].alive


def test_failed_descendant_snapshot_does_not_kill_or_claim_absence(tmp_path, monkeypatch):
    supervisor, processes, _, events = owned_supervisor(tmp_path, monkeypatch)

    def failed_snapshot():
        raise OSError("partial process enumeration")

    monkeypatch.setattr(module, "_windows_process_parents", failed_snapshot)
    result = supervisor.stop_sidecar(timeout=0)
    assert not result.ok and result.state == "stop_failed"
    assert all(process.alive for process in processes.values())
    assert not any(event[0] in {"taskkill", "terminate"} for event in events)
    assert supervisor._sidecar_process is processes[101]


@pytest.mark.parametrize("unproved", ["stale_parent", "wrong_image"])
def test_stale_parent_pid_or_wrong_image_is_not_owned(tmp_path, monkeypatch, unproved):
    supervisor, processes, parents, events = owned_supervisor(tmp_path, monkeypatch)
    if unproved == "stale_parent":
        parents[201] = 101  # older process's PPID belongs to a previous generation.
    else:
        processes[101].exe = str(tmp_path / "foreign.exe")
    result = supervisor.stop_sidecar(timeout=0)
    assert not result.ok and result.state == "stop_failed"
    assert all(process.alive for process in processes.values())
    assert not any(event[0] in {"taskkill", "terminate"} for event in events)


def test_adopted_frozen_sidecar_is_never_a_shutdown_target(tmp_path, monkeypatch):
    supervisor, processes, _, events = owned_supervisor(tmp_path, monkeypatch)
    # Model a separate supervisor adopting the same healthy endpoint without a Popen handle.
    adopted = GamePointSupervisor(
        supervisor.config, frozen=True, run=lambda *_args, **_kwargs: pytest.fail("foreign kill")
    )
    monkeypatch.setattr(adopted, "preflight", lambda: [])
    monkeypatch.setattr(adopted, "_read_health", lambda: ProbeResult("sidecar", True, "running"))
    assert "adopted" in adopted.start_sidecar().detail
    assert adopted.stop_sidecar().state == "stopped"
    assert all(process.alive for process in processes.values())
    assert events == []


@pytest.mark.parametrize("frozen,platform", [(False, "win32"), (True, "linux")])
def test_source_and_non_windows_shutdown_keep_the_direct_child_path(
    tmp_path, monkeypatch, frozen, platform
):
    supervisor, processes, _, events = owned_supervisor(tmp_path, monkeypatch)
    supervisor._frozen = frozen
    monkeypatch.setattr(module.sys, "platform", platform)
    assert supervisor.stop_sidecar().state == "stopped"
    assert events == [("terminate", 101)]
    assert processes[102].alive and processes[103].alive


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows process enumeration")
def test_native_parent_snapshot_includes_the_current_process():
    assert os.getpid() in module._windows_process_parents()
