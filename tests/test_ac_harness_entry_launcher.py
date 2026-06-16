"""L2 entry-launcher tests for the #177 detect-and-retry actuator loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tools.ac_harness.entry_launcher import (
    ActuatorEvent,
    EntryActuator,
    EntryLauncher,
    EntryLauncherConfig,
    EntryOutcome,
    EntryPhase,
    classify_entry_phase,
    normalize_race_ini_spawn_set,
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
    assert actuator.calls == ["normalize", "launch", "trigger_drive", "relaunch", "trigger_drive"]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"max_launches": 0}, "max_launches"),
        ({"attempt_timeout": 0.0}, "attempt_timeout"),
        ({"poll_interval": 0.0}, "poll_interval"),
        ({"trigger_after": -1.0}, "trigger_after"),
        ({"trigger_interval": 0.0}, "trigger_interval"),
        ({"max_drive_triggers_per_launch": -1}, "max_drive_triggers"),
    ],
)
def test_launcher_config_validates_retry_budget(kwargs: dict, match: str):
    with pytest.raises(ValueError, match=match):
        EntryLauncherConfig(**kwargs)
