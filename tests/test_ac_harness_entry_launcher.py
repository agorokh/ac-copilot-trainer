"""L2 entry-launcher tests for the #177 detect-and-retry actuator loop."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tools.ac_harness import entry_launcher
from tools.ac_harness.entry_launcher import (
    ActuatorEvent,
    ColdRestartActuator,
    ContentManagerActuator,
    EntryActuator,
    EntryLauncher,
    EntryLauncherConfig,
    EntryLaunchUnsupported,
    EntryOutcome,
    EntryPhase,
    classify_entry_phase,
    make_actuator,
    normalize_race_ini_spawn_set,
    running_process_ids,
    terminate_process_tree_confirmed_absent,
)
from tools.ac_harness.shared_memory import (
    AcGameStatus,
    DrivingEntryDetector,
    GraphicsSnapshot,
    PhysicsSnapshot,
    SharedMemoryUnavailable,
)


def _g(status: AcGameStatus, *, in_pit: bool = False, packet_id: int = 0) -> GraphicsSnapshot:
    return GraphicsSnapshot(packet_id=packet_id, status=status, is_in_pit=in_pit)


def _p(packet_id: int) -> PhysicsSnapshot:
    return PhysicsSnapshot(packet_id=packet_id)


@dataclass
class FakeReader:
    frames: list[tuple[GraphicsSnapshot, PhysicsSnapshot | None]]
    index: int = 0
    closed: bool = False

    def read_graphics(self) -> GraphicsSnapshot:
        frame = self._current()
        return frame[0]

    def read_physics(self) -> PhysicsSnapshot | None:
        frame = self._current()
        self.index += 1
        return frame[1]

    def close(self) -> None:
        self.closed = True

    def _current(self) -> tuple[GraphicsSnapshot, PhysicsSnapshot | None]:
        if not self.frames:
            raise SharedMemoryUnavailable("no frames configured")
        if self.index >= len(self.frames):
            return self.frames[-1]
        return self.frames[self.index]


@dataclass
class ReaderFactory:
    attempts: list[list[tuple[GraphicsSnapshot, PhysicsSnapshot | None]]]
    readers: list[FakeReader] = field(default_factory=list)

    def __call__(self) -> FakeReader:
        if not self.attempts:
            raise SharedMemoryUnavailable("no more attempts")
        reader = FakeReader(self.attempts.pop(0))
        self.readers.append(reader)
        return reader


@dataclass
class WarmingReaderFactory:
    failures_before_ready: int
    frames: list[tuple[GraphicsSnapshot, PhysicsSnapshot | None]]
    calls: int = 0
    readers: list[FakeReader] = field(default_factory=list)

    def __call__(self) -> FakeReader:
        self.calls += 1
        if self.calls <= self.failures_before_ready:
            raise SharedMemoryUnavailable("shared memory warming up")
        reader = FakeReader(self.frames)
        self.readers.append(reader)
        return reader


@dataclass
class FakeActuator(EntryActuator):
    trigger_supported: bool = True
    calls: list[str] = field(default_factory=list)

    def normalize_prior_state(self) -> ActuatorEvent:
        self.calls.append("normalize")
        return ActuatorEvent("normalize", "fake")

    def launch(self) -> ActuatorEvent:
        self.calls.append("launch")
        return ActuatorEvent("launch", "fake")

    def trigger_drive(self) -> ActuatorEvent:
        self.calls.append("trigger_drive")
        return ActuatorEvent("trigger_drive", "fake", supported=self.trigger_supported)

    def relaunch(self) -> ActuatorEvent:
        self.calls.append("relaunch")
        return ActuatorEvent("relaunch", "fake")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _config(**overrides) -> EntryLauncherConfig:
    base = dict(
        max_launches=2,
        attempt_timeout=0.20,
        poll_interval=0.01,
        trigger_after=0.02,
        trigger_interval=0.02,
        max_drive_triggers_per_launch=3,
        required_live_reads=2,
        stagnation_seconds=0.05,
    )
    base.update(overrides)
    return EntryLauncherConfig(**base)


def test_normalize_race_ini_sets_spawn_set_to_pit(tmp_path: Path):
    race_ini = tmp_path / "race.ini"
    race_ini.write_text(
        "[RACE]\nMODEL=ks_abarth500\n\n[SESSION_0]\nTYPE=3\nSPAWN_SET=HOTLAP\n",
        encoding="utf-8",
    )

    normalize_race_ini_spawn_set(race_ini)

    text = race_ini.read_text(encoding="utf-8")
    assert "[SESSION_0]" in text
    assert "TYPE=3" in text
    assert "SPAWN_SET=PIT" in text
    assert not race_ini.with_suffix(".ini.tmp").exists()


def test_normalize_race_ini_creates_session_section(tmp_path: Path):
    race_ini = tmp_path / "race.ini"
    race_ini.write_text("[RACE]\nMODEL=ks_abarth500\n", encoding="utf-8")

    normalize_race_ini_spawn_set(race_ini)

    assert "SPAWN_SET=PIT" in race_ini.read_text(encoding="utf-8")


def test_classify_entry_phase_distinguishes_menu_pit_and_driving():
    det = DrivingEntryDetector(required_live_reads=1)
    assert classify_entry_phase(_g(AcGameStatus.PAUSE), detector=det) is EntryPhase.STUCK_IN_MENU
    assert (
        classify_entry_phase(_g(AcGameStatus.LIVE, in_pit=True), detector=det) is EntryPhase.IN_PIT
    )
    assert classify_entry_phase(_g(AcGameStatus.LIVE), detector=det) is EntryPhase.STARTING

    det.observe(_g(AcGameStatus.LIVE), _p(1), now=0.0)  # baseline
    det.observe(_g(AcGameStatus.LIVE), _p(2), now=0.01)  # clear -> driving
    assert classify_entry_phase(_g(AcGameStatus.LIVE), detector=det) is EntryPhase.DRIVING


def test_launcher_succeeds_without_retry_when_detector_observes_driving():
    frames = [
        (_g(AcGameStatus.LIVE), _p(1)),  # baseline
        (_g(AcGameStatus.LIVE), _p(2)),
        (_g(AcGameStatus.LIVE), _p(3)),
    ]
    factory = ReaderFactory([frames])
    actuator = FakeActuator()
    clock = FakeClock()

    result = EntryLauncher(
        actuator,
        reader_factory=factory,
        config=_config(required_live_reads=2),
        clock=clock,
        sleep=clock.sleep,
    ).run()

    assert result.outcome is EntryOutcome.DRIVING
    assert result.launches == 1
    assert result.polls == 3
    assert actuator.calls == ["normalize", "launch"]
    assert factory.readers[0].closed is True


def test_launcher_waits_for_shared_memory_to_appear_after_launch():
    frames = [
        (_g(AcGameStatus.LIVE), _p(1)),
        (_g(AcGameStatus.LIVE), _p(2)),
        (_g(AcGameStatus.LIVE), _p(3)),
    ]
    factory = WarmingReaderFactory(failures_before_ready=3, frames=frames)
    actuator = FakeActuator()
    clock = FakeClock()

    result = EntryLauncher(
        actuator,
        reader_factory=factory,
        config=_config(required_live_reads=2),
        clock=clock,
        sleep=clock.sleep,
    ).run()

    assert result.ok is True
    assert factory.calls == 4
    assert result.reason == "shared-memory detector observed sustained driving"


def test_launcher_triggers_drive_when_current_actuator_supports_in_session_retry():
    frames = [(_g(AcGameStatus.PAUSE), _p(1))] * 20
    actuator = FakeActuator(trigger_supported=True)
    clock = FakeClock()

    result = EntryLauncher(
        actuator,
        reader_factory=ReaderFactory([frames, frames]),
        config=_config(max_launches=1, max_drive_triggers_per_launch=2),
        clock=clock,
        sleep=clock.sleep,
    ).run()

    assert result.ok is False
    assert actuator.calls.count("trigger_drive") == 2
    assert actuator.calls == ["normalize", "launch", "trigger_drive", "trigger_drive"]


def test_launcher_can_disable_in_session_drive_triggers():
    frames = [(_g(AcGameStatus.PAUSE), _p(1))] * 20
    actuator = FakeActuator(trigger_supported=True)
    clock = FakeClock()

    result = EntryLauncher(
        actuator,
        reader_factory=ReaderFactory([frames]),
        config=_config(max_launches=1, max_drive_triggers_per_launch=0),
        clock=clock,
        sleep=clock.sleep,
    ).run()

    assert result.ok is False
    assert "trigger_drive" not in actuator.calls
    assert actuator.calls == ["normalize", "launch"]


def test_launcher_relaunches_when_default_actuator_has_no_drive_trigger():
    stuck = [(_g(AcGameStatus.PAUSE), _p(1))] * 20
    driving = [
        (_g(AcGameStatus.LIVE), _p(1)),
        (_g(AcGameStatus.LIVE), _p(2)),
        (_g(AcGameStatus.LIVE), _p(3)),
    ]
    actuator = FakeActuator(trigger_supported=False)
    clock = FakeClock()

    result = EntryLauncher(
        actuator,
        reader_factory=ReaderFactory([stuck, driving]),
        config=_config(max_launches=2),
        clock=clock,
        sleep=clock.sleep,
    ).run()

    assert result.ok is True
    assert result.launches == 2
    assert actuator.calls == ["normalize", "launch", "trigger_drive", "relaunch"]


def test_launcher_fails_after_capped_relaunches():
    stuck = [(_g(AcGameStatus.PAUSE), _p(1))] * 20
    actuator = FakeActuator(trigger_supported=False)
    clock = FakeClock()

    result = EntryLauncher(
        actuator,
        reader_factory=ReaderFactory([stuck, stuck]),
        config=_config(max_launches=2),
        clock=clock,
        sleep=clock.sleep,
    ).run()

    assert result.ok is False
    assert result.launches == 2
    assert result.last_phase is EntryPhase.STUCK_IN_MENU
    assert "last attempt: actuator requested relaunch" in result.reason
    assert actuator.calls == ["normalize", "launch", "trigger_drive", "relaunch", "trigger_drive"]


def test_cold_restart_normalize_kills_even_without_race_ini(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    actuator = ColdRestartActuator(acs_exe=tmp_path / "acs.exe", runner=runner)

    event = actuator.normalize_prior_state()

    assert event is not None
    assert event.detail == "killed acs.exe"
    assert calls == [["taskkill", "/IM", "acs.exe", "/F", "/T"]]


def test_running_process_ids_parses_all_matching_acs_rows(monkeypatch):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # noqa: ANN001
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='"acs.exe","101","Console","1","1,024 K"\n'
            '"ACS.EXE","202","Console","1","1,024 K"\n',
            stderr="",
        )

    assert running_process_ids("acs.exe", runner) == frozenset({101, 202})
    assert calls == [["tasklist", "/FI", "IMAGENAME eq acs.exe", "/FO", "CSV", "/NH"]]


def test_running_process_ids_treats_no_match_and_tasklist_failure_as_empty(monkeypatch):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    def no_match(cmd, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(cmd, 0, stdout="INFO: No tasks are running", stderr="")

    def failed(cmd, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="access denied")

    assert running_process_ids("acs.exe", no_match) == frozenset()
    assert running_process_ids("acs.exe", failed) == frozenset()


def test_running_process_ids_strict_mode_surfaces_enumeration_failure(monkeypatch):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    def failed(cmd, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="access denied")

    with pytest.raises(OSError, match="access denied"):
        running_process_ids("acs.exe", failed, strict=True)


def test_running_process_ids_native_failure_is_only_suppressed_in_best_effort_mode(monkeypatch):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    def fail_snapshot(_name: str) -> frozenset[int]:
        raise OSError("snapshot failed")

    monkeypatch.setattr(
        entry_launcher,
        "_toolhelp_process_ids",
        fail_snapshot,
    )

    assert running_process_ids("acs.exe") == frozenset()
    with pytest.raises(OSError, match="snapshot failed"):
        running_process_ids("acs.exe", strict=True)


def test_running_process_ids_preserves_partial_native_snapshot_for_best_effort_callers(
    monkeypatch,
):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    def fail_after_match(_name: str) -> frozenset[int]:
        raise entry_launcher._PartialProcessEnumerationError(
            5,
            "Process32NextW failed",
            {42},
        )

    monkeypatch.setattr(entry_launcher, "_toolhelp_process_ids", fail_after_match)

    assert running_process_ids("acs.exe") == frozenset({42})
    with pytest.raises(OSError, match="Process32NextW failed"):
        running_process_ids("acs.exe", strict=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Toolhelp32 is Windows-only")
def test_running_process_ids_native_snapshot_finds_current_python():
    assert os.getpid() in running_process_ids(Path(sys.executable).name)


def test_terminate_process_tree_requires_consecutive_absence(monkeypatch):
    clock = FakeClock()
    observations = iter([True, False, False])
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    assert (
        terminate_process_tree_confirmed_absent(
            "acs.exe",
            is_running=lambda: next(observations),
            timeout=2.0,
            poll=0.1,
            runner=runner,
            clock=clock,
            sleep=clock.sleep,
        )
        is True
    )
    assert calls == [["taskkill", "/IM", "acs.exe", "/F", "/T"]]
    assert clock.now == pytest.approx(0.2)


def test_terminate_process_tree_fails_closed_off_windows(monkeypatch):
    calls: list[list[str]] = []
    messages: list[str] = []

    monkeypatch.setattr(entry_launcher.sys, "platform", "darwin")

    assert (
        terminate_process_tree_confirmed_absent(
            "acs.exe",
            is_running=lambda: False,
            runner=lambda command, **_kwargs: calls.append(command),
            log=messages.append,
        )
        is False
    )
    assert calls == []
    assert messages == ["cannot confirm acs.exe termination on unsupported platform darwin"]


def test_terminate_process_tree_bounds_unknown_enumeration(monkeypatch):
    clock = FakeClock()
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    assert (
        terminate_process_tree_confirmed_absent(
            "acs.exe",
            is_running=lambda: (_ for _ in ()).throw(OSError("snapshot failed")),
            timeout=0.3,
            poll=0.1,
            runner=runner,
            clock=clock,
            sleep=clock.sleep,
        )
        is False
    )
    assert calls == [["taskkill", "/IM", "acs.exe", "/F", "/T"]]
    assert clock.now == pytest.approx(0.3)


def test_cold_restart_relaunch_reapplies_race_ini_normalization(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    acs_exe = tmp_path / "acs.exe"
    acs_exe.write_text("", encoding="utf-8")
    race_ini = tmp_path / "race.ini"
    race_ini.write_text("[SESSION_0]\nSPAWN_SET=HOTLAP\n", encoding="utf-8")
    killed: list[list[str]] = []
    launched: list[list[str]] = []

    def runner(cmd, **kwargs):
        killed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def popen(cmd, **kwargs):
        launched.append(cmd)
        return object()

    actuator = ColdRestartActuator(
        acs_exe=acs_exe,
        race_ini=race_ini,
        runner=runner,
        popen=popen,
    )

    event = actuator.relaunch()

    assert "SPAWN_SET=PIT" in race_ini.read_text(encoding="utf-8")
    assert killed == [["taskkill", "/IM", "acs.exe", "/F", "/T"]]
    assert launched == [[str(acs_exe.resolve())]]
    assert event.action == "relaunch"
    assert "SPAWN_SET=PIT" in event.detail


def test_content_manager_quick_drive_url_encodes_preset_path():
    preset = r"C:\Quick Drive\base test.cmpreset"
    actuator = ContentManagerActuator(preset=preset, cm_exe="cm.exe")
    url = actuator.quick_drive_url()

    assert url.startswith("acmanager://race/quick?presetFile=")
    assert "%20" in url  # spaces encoded
    assert "%3A" in url  # colon encoded
    assert " " not in url  # no raw spaces survive into the URL


def test_content_manager_resolves_relative_preset_to_absolute():
    # A separate CM process reads presetFile with its own cwd, so it must be absolute.
    actuator = ContentManagerActuator(preset="drive.cmpreset", cm_exe="cm.exe")
    assert actuator.preset.is_absolute()
    assert "drive.cmpreset" in actuator.quick_drive_url()


def test_content_manager_launch_spawns_cm_with_url(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    cm_exe = tmp_path / "Content Manager.exe"
    cm_exe.write_text("", encoding="utf-8")
    preset = tmp_path / "drive.cmpreset"
    preset.write_text("{}", encoding="utf-8")
    launched: list[list[str]] = []

    def popen(cmd, **kwargs):
        launched.append(cmd)
        return object()

    actuator = ContentManagerActuator(preset=preset, cm_exe=cm_exe, popen=popen)
    event = actuator.launch()

    assert event.action == "launch"
    assert launched == [[str(actuator.cm_exe), actuator.quick_drive_url()]]
    assert event.detail == actuator.quick_drive_url()


def test_content_manager_restart_kills_cm_process(monkeypatch, tmp_path: Path):
    # #558: restart_content_manager kills the CM process (tree) so the next launch cold-starts a
    # FRESH CM — the recovery a plain URL re-issue to a stale CM cannot perform.
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    cm_exe = tmp_path / "Content Manager.exe"
    cm_exe.write_text("", encoding="utf-8")
    preset = tmp_path / "drive.cmpreset"
    preset.write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # noqa: ANN001
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    actuator = ContentManagerActuator(preset=preset, cm_exe=cm_exe, runner=runner)
    event = actuator.restart_content_manager()

    assert event.action == "restart_cm"
    assert calls == [["taskkill", "/IM", "Content Manager.exe", "/F", "/T"]]
    assert "killed Content Manager.exe" in event.detail


def test_content_manager_launch_requires_windows(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(entry_launcher.sys, "platform", "linux")
    actuator = ContentManagerActuator(preset=tmp_path / "x.cmpreset", cm_exe=tmp_path / "cm.exe")

    with pytest.raises(EntryLaunchUnsupported, match="Windows-only"):
        actuator.launch()


def test_content_manager_launch_missing_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    # Missing CM exe.
    actuator = ContentManagerActuator(
        preset=tmp_path / "x.cmpreset", cm_exe=tmp_path / "missing.exe"
    )
    with pytest.raises(FileNotFoundError, match="Content Manager not found"):
        actuator.launch()

    # CM present but preset missing.
    cm_exe = tmp_path / "cm.exe"
    cm_exe.write_text("", encoding="utf-8")
    actuator = ContentManagerActuator(preset=tmp_path / "missing.cmpreset", cm_exe=cm_exe)
    with pytest.raises(FileNotFoundError, match="preset not found"):
        actuator.launch()


def test_content_manager_trigger_drive_unsupported_requests_relaunch():
    actuator = ContentManagerActuator(preset="x.cmpreset", cm_exe="cm.exe")
    event = actuator.trigger_drive()

    assert event.supported is False
    assert "relaunch" in event.detail


def test_content_manager_relaunch_kills_then_relaunches(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    cm_exe = tmp_path / "cm.exe"
    cm_exe.write_text("", encoding="utf-8")
    preset = tmp_path / "drive.cmpreset"
    preset.write_text("{}", encoding="utf-8")
    killed: list[list[str]] = []
    launched: list[list[str]] = []

    def runner(cmd, **kwargs):
        killed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def popen(cmd, **kwargs):
        launched.append(cmd)
        return object()

    actuator = ContentManagerActuator(preset=preset, cm_exe=cm_exe, runner=runner, popen=popen)
    event = actuator.relaunch()

    assert killed == [["taskkill", "/IM", "acs.exe", "/F", "/T"]]
    assert launched == [[str(actuator.cm_exe), actuator.quick_drive_url()]]
    assert event.action == "relaunch"
    assert "killed acs.exe" in event.detail


def test_make_actuator_cm_builds_content_manager_actuator(tmp_path: Path):
    actuator = make_actuator("cm", cm_preset=tmp_path / "d.cmpreset", cm_exe=tmp_path / "cm.exe")
    assert isinstance(actuator, ContentManagerActuator)
    assert actuator.quick_drive_url().startswith("acmanager://race/quick?presetFile=")


def test_make_actuator_acs_builds_cold_restart(tmp_path: Path):
    actuator = make_actuator("acs", acs_exe=tmp_path / "acs.exe")
    assert isinstance(actuator, ColdRestartActuator)


@pytest.mark.parametrize(
    ("mode", "kwargs", "match"),
    [
        ("cm", {}, "cm_preset"),
        ("acs", {}, "acs_exe"),
        ("nope", {"cm_preset": "x", "acs_exe": "y"}, "unknown launch_mode"),
    ],
)
def test_make_actuator_validates_mode(mode: str, kwargs: dict, match: str):
    with pytest.raises(ValueError, match=match):
        make_actuator(mode, **kwargs)


def test_cli_acs_mode_requires_acs_exe():
    with pytest.raises(SystemExit):
        entry_launcher._main(["--launch-mode", "acs"])


def test_cli_cm_mode_requires_preset():
    with pytest.raises(SystemExit):
        entry_launcher._main(["--launch-mode", "cm"])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"max_launches": 0}, "max_launches"),
        ({"attempt_timeout": 0.0}, "attempt_timeout"),
        ({"poll_interval": 0.0}, "poll_interval"),
        ({"trigger_after": -1.0}, "trigger_after"),
        ({"trigger_interval": 0.0}, "trigger_interval"),
        ({"max_drive_triggers_per_launch": -1}, "max_drive_triggers"),
        ({"required_live_reads": 0}, "required_live_reads"),
        ({"stagnation_seconds": 0.0}, "stagnation_seconds"),
    ],
)
def test_launcher_config_validates_retry_budget(kwargs: dict, match: str):
    with pytest.raises(ValueError, match=match):
        EntryLauncherConfig(**kwargs)


def test_terminate_graceful_grace_soft_close_succeeds_without_forced_kill(monkeypatch):
    """#668 — a healthy process honoring WM_CLOSE is never force-killed."""
    clock = FakeClock()
    observations = iter([True, True, False, False])
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    assert (
        terminate_process_tree_confirmed_absent(
            "acs.exe",
            is_running=lambda: next(observations),
            timeout=30.0,
            poll=0.1,
            runner=runner,
            clock=clock,
            sleep=clock.sleep,
            graceful_grace=20.0,
        )
        is True
    )
    # Only the soft close ran — no /F anywhere.
    assert calls == [["taskkill", "/IM", "acs.exe"]]


def test_terminate_graceful_grace_escalates_to_forced_after_grace(monkeypatch):
    """A wedged pump cannot process WM_CLOSE — past the grace the old forced boundary returns."""
    clock = FakeClock()
    calls: list[list[str]] = []
    messages: list[str] = []
    state = {"dead": False}

    def runner(command, **_kwargs):
        calls.append(command)
        if "/F" in command:
            state["dead"] = True
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    assert (
        terminate_process_tree_confirmed_absent(
            "acs.exe",
            is_running=lambda: not state["dead"],
            timeout=10.0,
            poll=0.5,
            runner=runner,
            clock=clock,
            sleep=clock.sleep,
            log=messages.append,
            graceful_grace=2.0,
        )
        is True
    )
    assert calls[0] == ["taskkill", "/IM", "acs.exe"]
    assert calls[1] == ["taskkill", "/IM", "acs.exe", "/F", "/T"]
    assert len(calls) == 2
    assert any("escalating to forced kill" in message for message in messages)


def test_terminate_graceful_grace_zero_is_the_old_behavior(monkeypatch):
    clock = FakeClock()
    observations = iter([True, False, False])
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")

    assert (
        terminate_process_tree_confirmed_absent(
            "acs.exe",
            is_running=lambda: next(observations),
            timeout=2.0,
            poll=0.1,
            runner=runner,
            clock=clock,
            sleep=clock.sleep,
            graceful_grace=0.0,
        )
        is True
    )
    assert calls == [["taskkill", "/IM", "acs.exe", "/F", "/T"]]


def test_terminate_graceful_grace_validation(monkeypatch):
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    with pytest.raises(ValueError, match="graceful_grace"):
        terminate_process_tree_confirmed_absent(
            "acs.exe", is_running=lambda: False, graceful_grace=-1.0
        )
    with pytest.raises(ValueError, match="forced phase"):
        terminate_process_tree_confirmed_absent(
            "acs.exe", is_running=lambda: False, timeout=10.0, graceful_grace=10.0
        )


# ---------------------------------------------------------------------------
# #738: the shared EntryLauncher path (daemon /session/start, entry_launcher CLI)
# arms the CSP-dialog skip watcher for CM launches — Codex #743 "wire the daemon too".
# ---------------------------------------------------------------------------
class _FakeWatcher:
    def __init__(self, skips: int = 0, summary: str | None = None) -> None:
        self.started = False
        self.stopped = False
        self.skips = skips
        self._summary = summary

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.stopped = True

    def summary(self) -> str | None:
        return self._summary


def _one_launch_driving_factory():
    frames = [
        (_g(AcGameStatus.LIVE), _p(1)),
        (_g(AcGameStatus.LIVE), _p(2)),
        (_g(AcGameStatus.LIVE), _p(3)),
    ]
    return ReaderFactory([frames])


def test_entry_launcher_arms_and_stops_dialog_watcher_on_cm_launch():
    watchers: list[_FakeWatcher] = []

    def factory():
        w = _FakeWatcher()
        watchers.append(w)
        return w

    clock = FakeClock()
    result = EntryLauncher(
        FakeActuator(),
        reader_factory=_one_launch_driving_factory(),
        config=_config(required_live_reads=2),
        clock=clock,
        sleep=clock.sleep,
        dialog_watcher_factory=factory,
    ).run()

    assert result.outcome is EntryOutcome.DRIVING
    assert len(watchers) == 1
    assert watchers[0].started is True
    assert watchers[0].stopped is True  # stopped via the run() finally


def test_entry_launcher_surfaces_dialog_watcher_forensics_on_result():
    # antigravity #743: the daemon/CLI path must not silently discard skips — the count and a
    # summary must ride the returned result, mirroring auto_drive / resilient_launch.
    watcher = _FakeWatcher(skips=2, summary="csp_dialog_skips=2")
    clock = FakeClock()
    result = EntryLauncher(
        FakeActuator(),
        reader_factory=_one_launch_driving_factory(),
        config=_config(required_live_reads=2),
        clock=clock,
        sleep=clock.sleep,
        dialog_watcher_factory=lambda: watcher,
    ).run()

    assert result.dialog_skips == 2
    assert "csp_dialog_skips=2" in result.reason


def test_entry_launcher_result_has_no_dialog_skips_when_watcher_absent():
    # No watcher (opt-out / non-CM) → dialog_skips stays None, reason untouched.
    clock = FakeClock()
    result = EntryLauncher(
        FakeActuator(),
        reader_factory=_one_launch_driving_factory(),
        config=_config(required_live_reads=2, cm_dialog_skip=False),
        clock=clock,
        sleep=clock.sleep,
        dialog_watcher_factory=lambda: _FakeWatcher(),
    ).run()
    assert result.dialog_skips is None


def test_entry_launcher_stops_watcher_even_when_launch_raises():
    watcher = _FakeWatcher()

    class BoomActuator(FakeActuator):
        def launch(self) -> ActuatorEvent:  # type: ignore[override]
            raise RuntimeError("launch blew up")

    with pytest.raises(RuntimeError, match="launch blew up"):
        EntryLauncher(
            BoomActuator(),
            reader_factory=_one_launch_driving_factory(),
            config=_config(),
            clock=FakeClock(),
            sleep=lambda _s: None,
            dialog_watcher_factory=lambda: watcher,
        ).run()

    assert watcher.started is True
    assert watcher.stopped is True  # finally guarantees teardown on an exception


def test_entry_launcher_skips_watcher_when_config_opts_out():
    watchers: list[_FakeWatcher] = []
    clock = FakeClock()
    EntryLauncher(
        FakeActuator(),
        reader_factory=_one_launch_driving_factory(),
        config=_config(required_live_reads=2, cm_dialog_skip=False),
        clock=clock,
        sleep=clock.sleep,
        dialog_watcher_factory=lambda: watchers.append(_FakeWatcher()) or watchers[-1],
    ).run()
    assert watchers == []  # opt-out short-circuits before the factory is called


def test_default_factory_builds_no_watcher_for_non_cm_actuator(tmp_path):
    # The default (None) factory path only arms for a ContentManagerActuator; a ColdRestart
    # (direct acs.exe) launch must resolve to no watcher without touching UIA or subprocess.
    acs = tmp_path / "acs.exe"
    acs.write_text("", encoding="utf-8")
    launcher = EntryLauncher(
        ColdRestartActuator(acs_exe=acs),
        reader_factory=_one_launch_driving_factory(),
        config=_config(),
    )
    assert launcher._start_dialog_watcher() is None


def test_default_factory_opt_out_skips_cm_actuator(tmp_path, monkeypatch):
    # Even for a CM actuator, config opt-out returns no watcher (default-factory branch).
    monkeypatch.setattr(entry_launcher.sys, "platform", "win32")
    cm = tmp_path / "Content Manager.exe"
    cm.write_text("", encoding="utf-8")
    preset = tmp_path / "quick.cmpreset"
    preset.write_text("[PRESET]\n", encoding="utf-8")
    launcher = EntryLauncher(
        ContentManagerActuator(preset=preset, cm_exe=cm),
        reader_factory=_one_launch_driving_factory(),
        config=_config(cm_dialog_skip=False),
    )
    assert launcher._start_dialog_watcher() is None
