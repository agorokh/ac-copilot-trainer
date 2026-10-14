"""Deterministic watchdog safety checks; never touch rig processes or audio."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.ac_harness import rig_watchdog as watchdog

OWNER = watchdog.ProcessIdentity(100, 10001, r"C:\Python\python.exe")
AC = watchdog.ProcessIdentity(200, 20001, r"C:\AC\acs.exe")
SIDECAR = watchdog.ProcessIdentity(300, 30001, r"C:\Python\python.exe")


class FakeClock:
    def __init__(self):
        self.now = 50.0
        self.on_sleep = lambda: None

    def __call__(self):
        return self.now

    def sleep(self, duration):
        assert 0 <= duration <= 1.0
        self.now += duration
        self.on_sleep()


class Process:
    def __init__(self, identity, clock, *, graceful=True, terminates=True):
        self.observed = identity
        self.clock = clock
        self.graceful = graceful
        self.terminates = terminates
        self.dead = False
        self.calls = []
        self.closed = False

    def identity(self):
        return self.observed

    def exited(self):
        return self.dead

    def request_close(self):
        self.calls.append(("close", self.clock()))
        if self.graceful:
            self.dead = True
        return 1

    def terminate(self):
        self.calls.append(("terminate", self.clock()))
        if self.terminates:
            self.dead = True

    def close(self):
        self.closed = True


@pytest.fixture
def harness(tmp_path):
    clock = FakeClock()
    processes = {identity.pid: Process(identity, clock) for identity in (OWNER, AC, SIDECAR)}
    metadata = {"pid": OWNER.pid, "cwd": "owned", "started_at": "original", "phase": "ready"}
    config = watchdog.WatchdogConfig(
        OWNER.pid, AC, tmp_path, max_runtime_s=3, graceful_s=2, terminate_s=1, poll_s=0.25
    )
    requests = []

    def factory(pid, *, can_terminate):
        requests.append((pid, can_terminate))
        return processes[pid]

    def run(*, lock_factory=None, **changes):
        def unexpected_lock(*_args, **_kwargs):
            pytest.fail("ordinary watchdog operation must not acquire a rig lock")

        return watchdog.run_watchdog(
            replace(config, **changes),
            process_factory=factory,
            owner_reader=lambda _path: metadata or None,
            lock_factory=lock_factory or unexpected_lock,
            clock=clock,
            sleep=clock.sleep,
        )

    return config, clock, processes, metadata, run, requests


def test_fixed_deadline_graceful_shutdown_without_agent_heartbeat(harness):
    config, clock, processes, _, run, requests = harness
    result = run()
    assert result["status"] == "complete"
    assert result["reason"] == "deadline"
    assert processes[AC.pid].calls == [("close", 53.0)]
    assert processes[OWNER.pid].calls == processes[SIDECAR.pid].calls == []
    assert requests == [(OWNER.pid, False), (AC.pid, True)]
    assert all(processes[pid].closed for pid in (OWNER.pid, AC.pid))
    assert not processes[SIDECAR.pid].closed
    armed = json.loads((config.run_dir / "watchdog/armed.json").read_text())
    assert armed["deadline_monotonic_s"] == result["deadline_monotonic_s"] == 53.0
    assert clock() == 53
    assert json.loads((config.run_dir / "watchdog/receipt.json").read_text()) == result


def test_wedged_ac_forces_only_retained_process_after_grace(harness):
    _, clock, processes, _, run, _ = harness
    processes[AC.pid].graceful = False
    result = run()
    assert result["status"] == "complete"
    assert result["forced"] == ["ac"]
    assert processes[AC.pid].calls == [("close", 53.0), ("terminate", 55.0)]
    assert clock() == 55
    assert processes[OWNER.pid].calls == processes[SIDECAR.pid].calls == []


def test_termination_failure_has_finite_bound_and_failed_receipt(harness):
    _, clock, processes, _, run, _ = harness
    processes[AC.pid].graceful = processes[AC.pid].terminates = False
    result = run()
    assert result["status"] == "failed"
    assert result["reason"] == "shutdown_timeout"
    assert result["exited"] == {"ac": False}
    assert clock() == 56


@pytest.mark.parametrize("observed", [None, {"pid": 999}, {"cwd": "unknown"}])
def test_canonical_owner_mismatch_never_opens_or_signals_targets(harness, observed):
    config, _, processes, metadata, run, requests = harness
    metadata.clear()
    metadata.update(observed or {})
    result = run()
    assert result["status"] == "failed"
    assert result["reason"] == "canonical_owner_mismatch"
    assert requests == []
    assert not (config.run_dir / "watchdog/armed.json").exists()
    assert all(not process.calls for process in processes.values())


@pytest.mark.parametrize(
    "identity", [replace(AC, created_filetime=20002), replace(AC, exe=r"C:\Peer\acs.exe")]
)
def test_pid_reuse_or_executable_mismatch_cannot_arm(harness, identity):
    config, _, processes, _, run, _ = harness
    processes[AC.pid].observed = identity
    result = run()
    assert result["status"] == "failed"
    assert "process_identity_mismatch" in result["reason"]
    assert not (config.run_dir / "watchdog/armed.json").exists()
    assert processes[AC.pid].calls == []


@pytest.mark.parametrize("change", ["lock_pid", "owner_dead", "owner_identity", "new_session"])
def test_owner_loss_after_arm_fails_without_touching_processes(harness, change):
    _, clock, processes, metadata, run, _ = harness

    def lose_owner():
        if change == "lock_pid":
            metadata["pid"] = 999
        elif change == "owner_dead":
            processes[OWNER.pid].dead = True
        elif change == "owner_identity":
            processes[OWNER.pid].observed = replace(OWNER, created_filetime=999)
        else:
            metadata["started_at"] = "replacement session"

    clock.on_sleep = lose_owner
    result = run()
    assert result["status"] == "failed"
    assert all(not process.calls for process in processes.values())


def test_legitimate_phase_updates_never_extend_deadline(harness):
    _, clock, processes, metadata, run, _ = harness
    clock.on_sleep = lambda: metadata.update(phase=str(clock()))
    result = run()
    assert result["status"] == "complete"
    assert processes[AC.pid].calls == [("close", 53.0)]


def test_owner_transfer_during_grace_prevents_forced_kill(harness):
    _, clock, processes, metadata, run, _ = harness
    processes[AC.pid].graceful = False

    def transfer():
        if clock() > 53:
            metadata["pid"] = 999

    clock.on_sleep = transfer
    result = run()
    assert result["status"] == "failed"
    assert processes[AC.pid].calls == [("close", 53.0)]


def test_identity_recheck_prevents_shutdown_after_binding(harness):
    _, clock, processes, _, run, _ = harness
    clock.on_sleep = lambda: setattr(
        processes[AC.pid], "observed", replace(AC, created_filetime=999)
    )
    result = run()
    assert result["status"] == "failed"
    assert "process_identity_mismatch" in result["reason"]
    assert processes[AC.pid].calls == []


def test_owner_death_takes_idle_lock_for_immediate_bounded_cleanup(harness):
    config, clock, processes, metadata, run, _ = harness
    processes[AC.pid].graceful = False
    calls = []

    class Lease:
        def __init__(self, path, *, owner, timeout):
            assert path == watchdog.default_rig_session_lock_path()
            assert owner.session_kind == "bounded_watchdog_cleanup"
            assert owner.phase == "closing"
            assert timeout == 0

        def acquire(self):
            calls.append("acquire")

        def release(self):
            assert processes[AC.pid].dead
            assert processes[AC.pid].closed
            calls.append("release")

    def original_owner_dies():
        processes[OWNER.pid].dead = True
        metadata.clear()

    clock.on_sleep = original_owner_dies
    result = run(lock_factory=Lease)
    assert result["status"] == "complete"
    assert result["reason"] == "owner_exited"
    assert processes[AC.pid].calls == [("close", 50.25), ("terminate", 52.25)]
    assert calls == ["acquire", "release"]
    assert result["deadline_monotonic_s"] == 53
    assert result["forced"] == ["ac"]
    assert processes[OWNER.pid].calls == []
    assert json.loads((config.run_dir / "watchdog/receipt.json").read_text()) == result


def test_competing_owner_winning_takeover_race_blocks_cleanup(harness):
    _, clock, processes, metadata, run, _ = harness

    class Lease:
        def __init__(self, *_args, **_kwargs):
            pass

        def acquire(self):
            raise watchdog.OwnershipError("another owner won canonical lock")

        def release(self):
            pytest.fail("never release a peer's lock")

    def original_owner_dies():
        processes[OWNER.pid].dead = True
        metadata.clear()

    clock.on_sleep = original_owner_dies
    result = run(lock_factory=Lease)
    assert result["status"] == "failed"
    assert "another owner won" in result["reason"]
    assert processes[AC.pid].calls == []


def test_living_owner_releasing_lock_does_not_authorize_takeover(harness):
    _, clock, processes, metadata, run, _ = harness
    clock.on_sleep = metadata.clear
    result = run()
    assert result["status"] == "failed"
    assert processes[AC.pid].calls == []


def test_ac_normal_exit_shuts_down_only_explicit_sidecar(harness):
    config, clock, processes, _, run, _ = harness
    stop_file = config.run_dir / "sidecar.stop"

    def react():
        processes[AC.pid].dead = True
        if stop_file.exists():
            processes[SIDECAR.pid].dead = True

    clock.on_sleep = react
    result = run(sidecar=SIDECAR, sidecar_stop_file=stop_file)
    assert result["status"] == "complete"
    assert result["reason"] == "ac_exited"
    assert result["exited"] == {"ac": True, "sidecar": True}
    assert json.loads(stop_file.read_text()) == {"owner_pid": 100, "sidecar_pid": 300}
    assert all(not process.calls for process in processes.values())


def test_optional_sidecar_forced_cleanup_is_bounded_and_not_a_tree_kill(harness):
    config, clock, processes, _, run, requests = harness
    result = run(sidecar=SIDECAR, sidecar_stop_file=config.run_dir / "sidecar.stop")
    assert result["status"] == "complete"
    assert result["forced"] == ["sidecar"]
    assert processes[SIDECAR.pid].calls == [("terminate", 55.0)]
    assert processes[OWNER.pid].calls == []
    assert requests == [(100, False), (200, True), (300, True)]
    assert clock() == 55


def test_denied_ac_termination_does_not_strand_explicit_sidecar(harness):
    config, clock, processes, _, run, _ = harness
    processes[AC.pid].graceful = False

    def denied():
        raise OSError("access denied")

    processes[AC.pid].terminate = denied
    result = run(sidecar=SIDECAR, sidecar_stop_file=config.run_dir / "sidecar.stop")
    assert result["status"] == "failed"
    assert result["reason"] == "shutdown_timeout"
    assert result["exited"] == {"ac": False, "sidecar": True}
    assert processes[SIDECAR.pid].calls == [("terminate", 55.0)]
    assert clock() == 56
    assert any(event["event"] == "terminate_failed" for event in result["events"])


@pytest.mark.parametrize("existing", [False, True])
def test_stop_path_must_be_fresh_and_inside_owned_run(harness, tmp_path, existing):
    config, _, processes, _, run, requests = harness
    stop_file = config.run_dir / "sidecar.stop" if existing else tmp_path.parent / "peer.stop"
    if existing:
        stop_file.write_text("preserve me")
    result = run(sidecar=SIDECAR, sidecar_stop_file=stop_file)
    assert result["status"] == "failed"
    assert "stop file must be fresh" in result["reason"]
    assert requests == []
    assert all(not process.calls for process in processes.values())
    if existing:
        assert stop_file.read_text() == "preserve me"


def test_fresh_receipt_directory_prevents_rearming_or_reset(harness):
    config, _, processes, _, run, _ = harness
    (config.run_dir / "watchdog").mkdir()
    marker = config.run_dir / "watchdog/armed.json"
    marker.write_text("previous run")
    with pytest.raises(FileExistsError):
        run()
    assert marker.read_text() == "previous run"
    assert all(not process.calls for process in processes.values())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1, 601, True])
def test_deadline_rejects_unbounded_invalid_or_excessive_duration(harness, value):
    config, *_ = harness
    with pytest.raises(ValueError, match="max_runtime_s"):
        replace(config, max_runtime_s=value)


def test_graceful_request_failure_still_enforces_deadline(harness):
    _, _, processes, _, run, _ = harness

    def fails():
        raise OSError("window access denied")

    processes[AC.pid].request_close = fails
    result = run()
    assert result["status"] == "complete"
    assert result["forced"] == ["ac"]
    assert any(row["event"] == "graceful_close_failed" for row in result["events"])


def test_lost_event_sink_does_not_cancel_armed_deadline(harness):
    config, clock, processes, _, run, _ = harness

    def break_events():
        event_file = config.run_dir / "watchdog/events.jsonl"
        if event_file.is_file():
            event_file.unlink()
            event_file.mkdir()

    clock.on_sleep = break_events
    result = run()
    assert processes[AC.pid].calls == [("close", 53.0)]
    assert result["status"] == "failed"
    assert result["errors"]
    assert result["exited"] == {"ac": True}


def test_cli_requires_full_sidecar_identity():
    with pytest.raises(SystemExit):
        watchdog.main(
            [
                "run",
                "--owner-pid",
                "100",
                "--run-dir",
                ".",
                "--ac-pid",
                "200",
                "--ac-created-filetime",
                "20001",
                "--ac-exe",
                AC.exe,
                "--sidecar-pid",
                "300",
            ]
        )


@pytest.mark.parametrize(
    "mutation", [None, "normalized", "duration", "elevation", "action", "run_id", "principal"]
)
def test_task_definition_requires_exact_action_and_hard_execution_bound(tmp_path, mutation):
    from tools.ac_harness.remote_launcher import watchdog_task_xml

    exe, shim = tmp_path / "pythonw.exe", tmp_path / "_remote_exec.py"
    xml = watchdog_task_xml(
        interpreter=exe, shim=shim, run_id="owned", when=datetime.now(UTC), run_as="operator"
    )
    if mutation == "duration":
        xml = xml.replace("PT660S", "PT0S")
    elif mutation == "elevation":
        xml = xml.replace("LeastPrivilege", "HighestAvailable")
    elif mutation == "action":
        xml = xml.replace(str(exe), str(tmp_path / "peer.exe"))
    elif mutation == "run_id":
        xml = xml.replace("owned", "peer")
    elif mutation == "principal":
        xml = xml.replace('Context="Operator"', 'Context="Unverified"')
    elif mutation == "normalized":
        xml = xml.replace("<RunLevel>LeastPrivilege</RunLevel>", "").replace("PT660S", "PT11M")
    if mutation not in {None, "normalized"}:
        with pytest.raises(RuntimeError):
            watchdog.validate_scheduled_definition(
                xml, run_id="owned", interpreter=str(exe), shim=shim
            )
    else:
        watchdog.validate_scheduled_definition(xml, run_id="owned", interpreter=str(exe), shim=shim)


def test_detached_start_waits_for_bound_live_child_and_original_deadline(harness, monkeypatch):
    config, clock, _, _, _, _ = harness
    monkeypatch.setattr(watchdog.sys, "platform", "win32")
    calls = []

    class Child:
        pid = 400

        def poll(self):
            return None

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        output = config.run_dir / "watchdog"
        output.mkdir()
        (output / "armed.json").write_text(
            json.dumps(
                {
                    "watchdog_pid": 400,
                    "status": "armed",
                    "deadline_monotonic_s": 53,
                }
            )
        )
        return Child()

    result = watchdog.start_watchdog(config, popen=popen, clock=clock, sleep=clock.sleep)
    assert result["deadline_monotonic_s"] == 53
    command, options = calls[0]
    assert command[:5] == [
        getattr(sys, "_base_executable", sys.executable),
        "-B",
        "-m",
        "tools.ac_harness.rig_watchdog",
        "run",
    ]
    assert command[command.index("--ac-created-filetime") + 1] == str(AC.created_filetime)
    assert options["creationflags"] == 0x01000208
    assert options["stdin"] == subprocess.DEVNULL
    assert options["close_fds"] is True
    assert "--max-runtime-s" in command


@pytest.mark.parametrize("state", ["timeout", "failed", "expired", "wrong_pid"])
def test_unconfirmed_start_never_allows_activation_or_kills_guardian(harness, monkeypatch, state):
    config, clock, _, _, _, _ = harness
    monkeypatch.setattr(watchdog.sys, "platform", "win32")

    class Child:
        pid = 400

        def poll(self):
            return 1 if state == "failed" else None

        def terminate(self):
            pytest.fail("startup failure must not cancel a potentially armed guardian")

    def popen(*_args, **_kwargs):
        if state in {"expired", "wrong_pid"}:
            output = config.run_dir / "watchdog"
            output.mkdir()
            (output / "armed.json").write_text(
                json.dumps(
                    {
                        "watchdog_pid": 999 if state == "wrong_pid" else 400,
                        "status": "armed",
                        "deadline_monotonic_s": 49 if state == "expired" else 53,
                    }
                )
            )
        return Child()

    with pytest.raises(RuntimeError):
        watchdog.start_watchdog(config, popen=popen, clock=clock, sleep=clock.sleep)
    assert clock() <= 55.000001


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows process handle proof")
def test_native_retained_handle_terminates_disposable_child_preserving_peer():
    """Actual OS calls only on two test-owned Python sleepers; no rig/app access."""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for _ in range(2)
    ]
    bound = None
    try:
        target, peer = children
        bound = watchdog.WindowsProcess(target.pid, can_terminate=True)
        first = bound.identity()
        assert first.pid == target.pid
        assert first.created_filetime > 0
        assert Path(first.exe).resolve() == Path(sys.executable).resolve()
        assert first.matches(bound.identity())
        assert not bound.exited()
        assert bound.request_close() == 0
        bound.terminate()
        assert target.wait(timeout=5) == 1
        assert bound.exited()
        assert peer.poll() is None
    finally:
        if bound is not None:
            bound.close()
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
