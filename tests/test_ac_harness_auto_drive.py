"""Off-sim tests for the composed autonomous drive+assert loop (EPIC #154 Part G).

The four legs (launch / hijack / drive / tap) are injected as fakes so the orchestration —
ordering, the stop-event teardown, the drove-gates-success rule, and the failure-stage
reporting — is verified with no Assetto Corsa, no Windows, and no real sidecar.
"""

from __future__ import annotations

import asyncio
import pathlib
import threading
from dataclasses import replace

import pytest

from tools.ac_harness.auto_drive import (
    AutoDriveConfig,
    AutoDriveReport,
    DriveStats,
    ProgressWatchdog,
    SimProcessIdentityMonitor,
    _build_arg_parser,
    _build_driver,
    _config_from_args,
    _wait_live,
    bake_setup_into_race_ini,
    build_practice_preset,
    candidate_journal_laps_dirs,
    collect_lap_archives,
    custom_ai_enabled,
    default_ac_root,
    drive_leg_succeeded,
    fuel_matches,
    generic_gt3_ggv,
    known_journal_laps_dir,
    parse_setup_fuel,
    preflight,
    race_ini_setup_bake_loop,
    resolve_ac_user_dir,
    resolve_fast_lane,
    resolve_setup_ini,
    rig_hijack,
    rig_launch,
    run_auto_drive,
    should_try_line_teleport_on_recovery,
    verify_setup_ack,
    write_evidence,
    write_setup_baked_race_ini,
)
from tools.ac_harness.shared_memory import AcGameStatus, GraphicsSnapshot, PhysicsSnapshot

# A tiny closed square line + a per-point speed profile, for driver-construction tests.
_LINE = [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (50.0, 0.0, 50.0), (0.0, 0.0, 50.0)]
_PROFILE = [40.0, 40.0, 40.0, 40.0]  # m/s targets


def _cfg(**kw) -> AutoDriveConfig:
    # lap_finalize_grace_s=0.0 so orchestration tests don't real-sleep the post-lap grace; the grace
    # behaviour itself is covered by test_wait_lap_grace_drive_finalizes_archive.
    base = dict(
        cm_preset="preset.cmpreset", track_id="imola", tap_seconds=0.0, lap_finalize_grace_s=0.0
    )
    base.update(kw)
    return AutoDriveConfig(**base)  # type: ignore[arg-type]


def _snap(topic: str) -> dict:
    return {"type": "state.snapshot", "topic": topic, "v": 1, "payload": {}}


CONTINUOUS = [_snap("connection"), _snap("tire_temps"), _snap("coaching.snapshot")]


class FakeController:
    def __init__(self) -> None:
        self.closed = False

    def write_controls(self, *a, **k) -> None:  # noqa: ANN002, ANN003
        pass

    def read_car_data(self):  # noqa: ANN201
        return {
            "position": (0.0, 0.0, 0.0),
            "look": (1.0, 0.0, 0.0),
            "speed_kmh": 50.0,
            "rpm": 4000.0,
            "gear": 2,
            "packet_id": 1,
        }

    def teleport_to_pits(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _LiveReader:
    def __init__(self, packet_ids: list[int]) -> None:
        self.packet_ids = list(packet_ids)
        self.index = 0
        self.closed = False

    def read_graphics(self) -> GraphicsSnapshot:
        return GraphicsSnapshot(
            packet_id=self._packet_id(),
            status=AcGameStatus.LIVE,
            is_in_pit=False,
        )

    def read_physics(self) -> PhysicsSnapshot:
        pkt = self._packet_id()
        self.index += 1
        return PhysicsSnapshot(packet_id=pkt)

    def close(self) -> None:
        self.closed = True

    def _packet_id(self) -> int:
        if self.index >= len(self.packet_ids):
            return self.packet_ids[-1]
        return self.packet_ids[self.index]


def _drive_returning(stats: DriveStats, record: dict):
    def _drive(controller, config, stop: threading.Event) -> DriveStats:
        record["stop_set"] = stop.wait(timeout=2.0)
        record["controller"] = controller
        return stats

    return _drive


def _tap_returning(frames: list[dict], record: dict | None = None):
    async def _tap(url, *, seconds, wait_for_lap, **kwargs):  # noqa: ANN001
        if record is not None:
            record.update(seconds=seconds, wait_for_lap=wait_for_lap, **kwargs)
        return frames

    return _tap


def _ok_launch(config) -> tuple[bool, str]:  # noqa: ANN001
    return True, "live"


def test_launch_failure_exhausts_launch_budget_before_failing():
    record: dict = {}
    launches: list[int] = []

    def _fail_launch(config):  # noqa: ANN001
        launches.append(config.max_launches)
        return False, "no LIVE"

    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_fail_launch,
            hijack=lambda c: pytest.fail("hijack must not run after launch failure"),
            drive=_drive_returning(DriveStats(drove=True), record),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.ok is False
    assert report.stage == "launch"
    assert report.error == "no LIVE"
    # Each attempt launches with max_launches=1 (rig_launch does one cycle); the outer loop retries
    # up to the config budget.
    assert launches == [1, 1, 1, 1, 1]
    assert report.hijacked is False


def test_launch_failure_retries_until_later_launch_reaches_live():
    record: dict = {}
    outcomes = [(False, "first miss"), (True, "live")]
    ctrl = FakeController()
    launches: list[int] = []

    def _launch(config):  # noqa: ANN001
        launches.append(config.max_launches)
        return outcomes.pop(0)

    report = asyncio.run(
        run_auto_drive(
            _cfg(max_launches=2),
            launch=_launch,
            hijack=lambda c: ctrl,
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), record),
            tap=_tap_returning(CONTINUOUS),
        )
    )

    assert report.ok is True
    assert launches == [1, 1]
    assert report.launched is True
    assert report.hijacked is True
    assert ctrl.closed is True


def test_hijack_failure_reports_stage_hijack():
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: None,
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.ok is False
    assert report.stage == "hijack"
    assert report.launched is True
    assert report.hijacked is False


def test_hijack_failure_relaunches_until_control_lands():
    launches: list[int] = []
    budgets: list[int] = []
    hijacks: list[FakeController | None] = [None, FakeController()]

    def _launch(config):  # noqa: ANN001
        launches.append(1)
        budgets.append(config.max_launches)
        return True, "live"

    report = asyncio.run(
        run_auto_drive(
            _cfg(max_launches=2),
            launch=_launch,
            hijack=lambda c: hijacks.pop(0),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), {}),
            tap=_tap_returning(CONTINUOUS),
        )
    )

    assert report.ok is True
    assert launches == [1, 1]
    assert budgets == [1, 1]
    assert report.hijacked is True


def test_happy_path_window_mode_passes_and_tears_down():
    record: dict = {}
    ctrl = FakeController()
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: ctrl,
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), record),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.ok is True
    assert report.stage == "done"
    assert report.sequence_ok is True
    assert report.drive is not None and report.drive.drove is True
    # Orchestrator must always stop the drive and release the controller.
    assert record["stop_set"] is True
    assert ctrl.closed is True


def test_pipeline_failure_when_continuous_topic_missing():
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning([_snap("connection"), _snap("tire_temps")]),  # no coaching.snapshot
        )
    )
    assert report.ok is False
    assert report.sequence_ok is False


def test_wait_lap_requires_a_lap_frame():
    # wait_lap but no lap frame -> require_lap fails the sequence.
    tap_record: dict = {}
    no_lap = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, drive_seconds=420.0),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning(CONTINUOUS, tap_record),
        )
    )
    assert no_lap.ok is False
    # The lap wait scales with the drive budget (a Spa lap outlives the 180 s tap default).
    assert tap_record["lap_timeout"] == 420.0
    # lap frame present -> passes.
    with_lap = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning([*CONTINUOUS, _snap("session"), _snap("lap")]),
        )
    )
    assert with_lap.ok is True


def _timed_lap(ms: int = 90_000) -> dict:
    """A `lap` snapshot carrying a positive lap time (an archiveable, timed lap)."""
    return {"v": 1, "type": "state.snapshot", "topic": "lap", "payload": {"last_lap_ms": ms}}


def test_wait_lap_grace_drive_finalizes_archive(monkeypatch):
    # After a --wait-lap TIMED lap the car must keep driving briefly (grace) so the trainer's async
    # lap-archive writer finalizes lap 1's trace before teardown (#515). Assert the grace is awaited
    # for a timed lap and NOT for: no lap, --wait-lap off, or an untimed (unarchiveable) out-lap
    # (#516). asyncio.sleep is spied so no real time passes.
    import tools.ac_harness.auto_drive as ad

    slept: list[float] = []

    async def _spy(dt):
        slept.append(dt)

    monkeypatch.setattr(ad.asyncio, "sleep", _spy)

    got = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, lap_finalize_grace_s=5.0),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning([*CONTINUOUS, _snap("session"), _timed_lap()]),
        )
    )
    assert got.ok is True
    assert 5.0 in slept  # grace-drive awaited on a completed timed lap
    assert got.lap_grace_applied is True  # the single flag the evidence poll gates on

    slept.clear()
    no_lap = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, lap_finalize_grace_s=5.0),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning(CONTINUOUS),  # no lap frame -> no grace
        )
    )
    assert 5.0 not in slept
    assert no_lap.lap_grace_applied is False

    # Lap seen but --wait-lap disabled: grace gated off, flag False, poll must not wait (#516).
    slept.clear()
    no_wait = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=False, lap_finalize_grace_s=5.0),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning([*CONTINUOUS, _timed_lap()]),
        )
    )
    assert 5.0 not in slept
    assert no_wait.lap_grace_applied is False

    # Untimed out-lap (last_lap_ms absent): the trainer archives only timed laps, so the grace must
    # NOT fire on an unarchiveable boundary (#516 codex).
    slept.clear()
    untimed = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, lap_finalize_grace_s=5.0),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning([*CONTINUOUS, _snap("session"), _snap("lap")]),  # lap frame, no time
        )
    )
    assert 5.0 not in slept
    assert untimed.lap_grace_applied is False


def test_has_timed_lap_detects_only_positive_time():
    from tools.ac_harness.auto_drive import _has_timed_lap

    assert _has_timed_lap([_timed_lap(90_000)]) is True
    assert _has_timed_lap([_snap("connection"), _timed_lap()]) is True
    assert _has_timed_lap([_snap("lap")]) is False  # lap frame, no last_lap_ms
    zero = {"v": 1, "type": "state.snapshot", "topic": "lap", "payload": {"last_lap_ms": 0}}
    assert _has_timed_lap([zero]) is False  # untimed boundary
    diag = {"v": 1, "type": "diagnostic", "topic": "lap", "payload": {"last_lap_ms": 5}}
    assert _has_timed_lap([diag]) is False  # not a state.snapshot
    assert _has_timed_lap([]) is False


def test_wait_lap_extends_drive_budget_for_grace_headroom(monkeypatch):
    # The drive thread self-terminates on drive_seconds and brakes on exit; the post-lap grace must
    # have driving headroom or the car stops at S/F and the trace never finalizes (#515/#516). The
    # budget must outlive the LATEST lap the tap accepts (max(180, drive_seconds)) PLUS the grace.
    import tools.ac_harness.auto_drive as ad

    async def _spy(_dt):
        pass

    monkeypatch.setattr(ad.asyncio, "sleep", _spy)

    captured: dict = {}

    def _capture_drive(controller, config, stop):
        captured["drive_seconds"] = config.drive_seconds
        return DriveStats(drove=True)

    asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, drive_seconds=100.0, lap_finalize_grace_s=8.0),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_capture_drive,
            tap=_tap_returning([*CONTINUOUS, _snap("session"), _snap("lap")]),
        )
    )
    # settle(120) + max(180, 100) + grace(8) = 308 — outlives the full tap window + grace
    assert captured["drive_seconds"] == 308.0

    # grace=0 with wait_lap must STILL align to the full tap window (else the drive stops early and
    # the tap hangs on a stopped car): 120 + max(180, 50) + 0 = 300 (#516 daemon review).
    captured.clear()
    asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, drive_seconds=50.0, lap_finalize_grace_s=0.0),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_capture_drive,
            tap=_tap_returning([*CONTINUOUS, _timed_lap()]),
        )
    )
    assert captured["drive_seconds"] == 300.0

    captured.clear()
    asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=False, drive_seconds=100.0, lap_finalize_grace_s=8.0),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_capture_drive,
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert captured["drive_seconds"] == 100.0  # no wait_lap -> no headroom


def test_drove_false_gates_overall_success_even_if_pipeline_ok():
    # Sim died mid-drive: pipeline frames present but the drive did not actually move the car.
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=False, sim_dead=True, reason="acs died"), {}),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.sequence_ok is True
    assert report.ok is False  # drove=False must veto success
    assert report.drive is not None and report.drive.sim_dead is True


def test_tap_exception_marks_pipeline_stage_and_still_tears_down():
    record: dict = {}
    ctrl = FakeController()

    async def _boom(url, *, seconds, wait_for_lap, **kwargs):  # noqa: ANN001
        raise RuntimeError("sidecar exploded")

    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: ctrl,
            drive=_drive_returning(DriveStats(drove=True), record),
            tap=_boom,
        )
    )
    assert report.ok is False
    assert report.stage == "pipeline"
    assert report.error is not None and "sidecar exploded" in report.error
    assert record["stop_set"] is True  # teardown still ran
    assert ctrl.closed is True


def test_skip_launch_does_not_call_launch():
    report = asyncio.run(
        run_auto_drive(
            _cfg(skip_launch=True),
            launch=lambda c: pytest.fail("launch must be skipped"),
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.ok is True
    assert report.launched is False


def test_resolve_fast_lane_direct_layout_and_missing(tmp_path):
    root = tmp_path
    direct = root / "content" / "tracks" / "imola" / "ai"
    direct.mkdir(parents=True)
    (direct / "fast_lane.ai").write_bytes(b"x")
    assert resolve_fast_lane(root, "imola") == direct / "fast_lane.ai"

    layout = root / "content" / "tracks" / "monza" / "layout_gp" / "ai"
    layout.mkdir(parents=True)
    (layout / "fast_lane.ai").write_bytes(b"x")
    assert resolve_fast_lane(root, "monza") == layout / "fast_lane.ai"

    with pytest.raises(FileNotFoundError):
        resolve_fast_lane(root, "nonexistent")


def test_resolve_fast_lane_explicit_layout(tmp_path):
    root = tmp_path
    lay = root / "content" / "tracks" / "monza" / "layout_gp" / "ai"
    lay.mkdir(parents=True)
    (lay / "fast_lane.ai").write_bytes(b"x")
    assert resolve_fast_lane(root, "monza", "layout_gp") == lay / "fast_lane.ai"
    with pytest.raises(FileNotFoundError):
        resolve_fast_lane(root, "monza", "no_such_layout")


def test_sim_dead_vetoes_success_even_when_drove_true():
    # sim_dead can be set AFTER the car passed the distance/speed thresholds — must still FAIL.
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(
                DriveStats(drove=True, total_distance_m=900.0, sim_dead=True), {}
            ),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.sequence_ok is True
    assert report.ok is False  # sim_dead vetoes despite drove=True


def test_drive_exception_closes_controller_and_reports_drive_stage():
    ctrl = FakeController()

    def _boom_drive(controller, config, stop):  # noqa: ANN001
        raise RuntimeError("drive blew up")

    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: ctrl,
            drive=_boom_drive,
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.ok is False
    assert report.stage == "drive"
    assert report.error is not None and "drive blew up" in report.error
    assert ctrl.closed is True  # controller released despite the drive thread crashing


def test_skip_launch_hijack_failure_reports_launched_false():
    report = asyncio.run(
        run_auto_drive(
            _cfg(skip_launch=True),
            launch=lambda c: pytest.fail("launch must be skipped"),
            hijack=lambda c: None,
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.ok is False
    assert report.stage == "hijack"
    assert report.launched is False  # skip_launch -> launched stays False on hijack failure


def test_wait_live_rejects_stale_live_shared_memory(monkeypatch):
    from tools.ac_harness import auto_drive, shared_memory

    clock = _Clock()
    monkeypatch.setattr(auto_drive.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(auto_drive.time, "sleep", clock.sleep)
    monkeypatch.setattr(shared_memory, "SharedMemoryReader", lambda: _LiveReader([42]))

    assert _wait_live(timeout=0.3) is False


def test_wait_live_requires_real_packet_advancement(monkeypatch):
    from tools.ac_harness import auto_drive, shared_memory

    clock = _Clock()
    monkeypatch.setattr(auto_drive.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(auto_drive.time, "sleep", clock.sleep)
    monkeypatch.setattr(
        shared_memory,
        "SharedMemoryReader",
        lambda: _LiveReader([1, 2, 3, 4, 5, 6]),
    )

    assert _wait_live(timeout=1.0) is True


def test_build_driver_racing_is_default_and_shifts_gears():
    from tools.ac_harness.lap_driver import LapDriver
    from tools.ac_harness.racing_driver import RacingDriver

    # Default config -> racing.
    assert _cfg().driver == "racing"
    racing = _build_driver(_cfg(pace=1.0, racing_max_speed_kmh=240.0), _LINE, _PROFILE)
    assert isinstance(racing, RacingDriver)
    # RacingDriver can shift well past 1st gear; LapDriver is capped at 3 (AC enc) = 2nd.
    assert racing.max_gear >= 6

    cruise = _build_driver(_cfg(driver="cruise"), _LINE, _PROFILE)
    assert isinstance(cruise, LapDriver)


def test_build_driver_racing_requires_speed_profile():
    with pytest.raises(ValueError, match="speed_profile"):
        _build_driver(_cfg(driver="racing"), _LINE, None)


def test_build_driver_ggv_builds_min_time_racingdriver():
    from tools.ac_harness.racing_driver import RacingDriver

    # GGV computes its own min-time profile from the line curvature (no speed_profile needed).
    d = _build_driver(_cfg(driver="ggv", racing_max_speed_kmh=200.0, ggv_scale=0.9), _LINE, None)
    assert isinstance(d, RacingDriver)
    assert d.max_gear >= 6  # top gears available for flat-out straights


_ALIEN_PLANT_KWARGS = {
    "steering_mode": "curvature_ff",
    "ff_sign": -1.0,
    "ff_c1": -5.1,
    "ff_c2": -0.0033,
    "rpm_up": 8500.0,
    "rpm_dn": 6200.0,
}


def test_build_driver_alien_tracks_resolved_line_and_profile():
    from tools.ac_harness.racing_driver import RacingDriver

    cfg = _cfg(
        driver="alien",
        alien_line=_LINE,
        alien_v_target=[50.0, 40.0, 45.0, 40.0],
        plant_kwargs=dict(_ALIEN_PLANT_KWARGS),
        ggv_scale=0.9,
    )
    d = _build_driver(cfg, _LINE, None)
    assert isinstance(d, RacingDriver)
    # ggv_scale applies at construction: the profile the driver tracks is the scaled optimum.
    assert max(d.profile) == pytest.approx(50.0 * 0.9)


def test_build_driver_alien_requires_line_and_plant():
    with pytest.raises(ValueError, match="alien-line artifact"):
        _build_driver(_cfg(driver="alien", plant_kwargs=dict(_ALIEN_PLANT_KWARGS)), _LINE, None)
    with pytest.raises(ValueError, match="measured plant constants"):
        _build_driver(
            _cfg(driver="alien", alien_line=_LINE, alien_v_target=[40.0] * 4), _LINE, None
        )


def test_build_driver_alien_rejects_overspeed_scale():
    # The artifact's v_target is envelope-verified at build time; a scale above 1 would push
    # corner speeds past the verified plant envelope after that check.
    cfg = _cfg(
        driver="alien",
        alien_line=_LINE,
        alien_v_target=[40.0] * 4,
        plant_kwargs=dict(_ALIEN_PLANT_KWARGS),
        ggv_scale=1.1,
    )
    with pytest.raises(ValueError, match="ggv_scale"):
        _build_driver(cfg, _LINE, None)
    with pytest.raises(ValueError, match="ggv_scale"):
        _build_driver(replace(cfg, ggv_scale=0.0), _LINE, None)


def test_generic_gt3_ggv_is_realistic():
    from tools.ac_harness.ggv_profile import GGVModel

    g = generic_gt3_ggv()
    assert isinstance(g, GGVModel)
    assert 1.0 < g.mu_lat_g < 2.0  # realistic GT3 mechanical lateral grip
    assert 0.8 < g.brake_b0_g < 2.5  # low-speed braking g (rises with speed via brake_b1)
    assert g.k_aero_lat == 0.0  # aero-lateral term MUST be 0 (#259: spins the GT3 out live)


def test_build_driver_rejects_unknown_driver():
    with pytest.raises(ValueError, match="unknown driver"):
        _build_driver(_cfg(driver="bogus"), _LINE, _PROFILE)


def test_build_driver_ggv_consumes_plant_kwargs():
    # #532: measured plant constants flow into the GGV driver (shift points + measured steering).
    d = _build_driver(
        _cfg(
            driver="ggv",
            racing_max_speed_kmh=200.0,
            plant_kwargs={
                "rpm_up": 7600.0,
                "rpm_dn": 5100.0,
                "steering_mode": "curvature_ff",
                "ff_sign": 1.0,
                "ff_c1": 6.0,
                "ff_c2": 0.015,
            },
        ),
        _LINE,
        None,
    )
    assert d.rpm_up == 7600.0
    assert d.rpm_dn == 5100.0
    assert d.steering_mode == "curvature_ff"
    assert d.cff is not None
    assert d.cff.ff_sign == 1.0
    assert d.cff.c1 == 6.0


def test_build_driver_handshake_builds_controller_with_own_sink():
    from tools.ac_harness.plant_id import HandshakeController

    cfg = _cfg(driver="handshake", car_id="test_car")
    d = _build_driver(cfg, _LINE, _PROFILE)
    assert isinstance(d, HandshakeController)
    assert isinstance(d.sink, dict)  # controller owns its sink (no config side-channel)
    assert d.car_id == "test_car"
    assert d.finished is False


def test_build_driver_handshake_requires_speed_profile():
    with pytest.raises(ValueError, match="speed_profile"):
        _build_driver(_cfg(driver="handshake"), _LINE, None)


def test_track_ids_match_rules():
    from tools.ac_harness.auto_drive import track_ids_match

    assert track_ids_match("magione", "magione")
    assert track_ids_match("Magione", "magione")  # case-insensitive
    assert not track_ids_match("magione", "spa")
    # empty/unknown loaded id => cannot confirm => match (never block on a missing read)
    assert track_ids_match("magione", "")
    assert track_ids_match("", "spa")


def test_run_auto_drive_fails_fast_on_track_mismatch():
    # #532: CM launched a cached session (spa) instead of the requested track (magione). The
    # harness must FAIL at stage="launch", not drive the requested line on the wrong track.
    ctrl = FakeController()

    report = asyncio.run(
        run_auto_drive(
            _cfg(track_id="magione", skip_launch=True),
            launch=_ok_launch,
            hijack=lambda c: ctrl,
            drive=lambda controller, config, stop: pytest.fail("must not drive the wrong track"),
            tap=_tap_returning(CONTINUOUS),
            verify_track=lambda c: ("spa", "ks_porsche_911_gt3_r_2016"),
        )
    )
    assert report.ok is False
    assert report.stage == "launch"
    assert "spa" in report.error and "magione" in report.error
    assert ctrl.closed is True  # controller released before bailing


def test_handshake_outcome_gate_preserves_any_prior_failure():
    # #532 daemon HIGH + Codex: ANY run-level failure stays authoritative. The _main gate is
    # `if report.ok`, so a NOT-ok report — a raised error OR an error-less veto (seq_ok False /
    # sim_dead / recovery_capped, which keep error=None but set ok=False) — is never overwritten
    # with "handshake produced no result".
    from types import SimpleNamespace

    from tools.ac_harness.plant_id import apply_handshake_outcome

    # error-carrying failures AND error-less vetoes (ok=False, error=None) must both be preserved
    cases = [
        {"stage": "launch", "error": "launch failed"},
        {"stage": "pipeline", "error": "tap crashed"},
        {"stage": "done", "error": None},  # error-less drive/pipeline veto (ok=False)
    ]
    for c in cases:
        report = SimpleNamespace(ok=False, stage=c["stage"], error=c["error"], notes=[])
        if report.ok:  # the _main gate
            apply_handshake_outcome(report, {})
        assert report.stage == c["stage"] and report.error == c["error"]  # preserved
    # A clean run (ok True) with an empty sink DOES get the honest "no result" verdict.
    ok_report = SimpleNamespace(ok=True, stage="done", error=None, notes=[])
    if ok_report.ok:
        apply_handshake_outcome(ok_report, {})
    assert ok_report.stage == "handshake" and ok_report.ok is False


def test_run_auto_drive_fails_fast_on_car_mismatch():
    # Same track, different CAR served by a cached CM session -> must not persist a mislabeled
    # plant artifact under the requested car (#532 Codex review).
    ctrl = FakeController()
    report = asyncio.run(
        run_auto_drive(
            _cfg(track_id="spa", car_id="ks_porsche_911_gt3_r_2016", skip_launch=True),
            launch=_ok_launch,
            hijack=lambda c: ctrl,
            drive=lambda controller, config, stop: pytest.fail("must not drive the wrong car"),
            tap=_tap_returning(CONTINUOUS),
            verify_track=lambda c: ("spa", "ks_audi_r8_lms"),
        )
    )
    assert report.ok is False
    assert report.stage == "launch"
    assert "ks_audi_r8_lms" in report.error and "car" in report.error


def test_run_auto_drive_track_match_proceeds():
    record: dict = {}
    report = asyncio.run(
        run_auto_drive(
            _cfg(track_id="magione", car_id="ks_porsche_911_gt3_r_2016", skip_launch=True),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), record),
            tap=_tap_returning(CONTINUOUS),
            verify_track=lambda c: ("magione", "ks_porsche_911_gt3_r_2016"),
        )
    )
    assert report.stage != "launch"
    assert record["controller"] is not None  # the drive leg ran


def test_run_auto_drive_relaunches_on_track_mismatch_then_drives():
    # #537: CM served its cached session (spa) on the first launch; the harness must RELAUNCH
    # (bounded) rather than fail — the second launch loads the requested magione and drives it.
    # #558: the relaunch must RESTART the launcher (kill CM) BEFORE the next launch so a fresh CM
    # cold-starts and honors the preset — a plain URL re-issue to a stale CM never recovers.
    record: dict = {}
    launches: list[int] = []
    restarts: list[int] = []
    c_bad = FakeController()
    c_good = FakeController()
    controllers: list[FakeController] = [c_bad, c_good]
    loaded_tracks = ["spa", "magione"]  # cached (wrong) first, requested second

    def _launch(config):  # noqa: ANN001
        launches.append(1)
        return True, "live"

    report = asyncio.run(
        run_auto_drive(
            _cfg(track_id="magione", car_id="ks_porsche_911_gt3_r_2016", max_launches=3),
            launch=_launch,
            hijack=lambda c: controllers.pop(0),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), record),
            tap=_tap_returning(CONTINUOUS),
            verify_track=lambda c: (loaded_tracks.pop(0), "ks_porsche_911_gt3_r_2016"),
            restart_launcher=lambda c: restarts.append(1),
        )
    )

    assert report.ok is True
    assert report.stage != "launch"  # did not fail-fast on the first (mismatched) launch
    assert len(launches) == 2  # relaunched exactly once
    assert len(restarts) == 1  # #558: CM restarted once, before the recovery relaunch
    assert c_bad.closed is True  # the mismatched controller was released before relaunch
    assert record["controller"] is c_good  # drove on the correct-track session


def test_run_auto_drive_restart_launcher_failure_does_not_crash_recovery():
    # #558: a restart-seam failure must be swallowed — the plain relaunch still runs and recovers.
    record: dict = {}
    controllers: list[FakeController] = [FakeController(), FakeController()]
    loaded_tracks = ["spa", "magione"]

    def _boom(config):  # noqa: ANN001
        raise OSError("taskkill blew up")

    report = asyncio.run(
        run_auto_drive(
            _cfg(track_id="magione", car_id="ks_porsche_911_gt3_r_2016", max_launches=3),
            launch=lambda c: (True, "live"),
            hijack=lambda c: controllers.pop(0),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), record),
            tap=_tap_returning(CONTINUOUS),
            verify_track=lambda c: (loaded_tracks.pop(0), "ks_porsche_911_gt3_r_2016"),
            restart_launcher=_boom,
        )
    )

    assert report.ok is True  # the run recovered despite the restart seam raising


def test_run_auto_drive_restarts_cm_after_persistent_hijack_stall():
    # #558: a PERSISTENT pre-drive overlay stall (hijack never lands) is severe CM degradation. A
    # TRANSIENT stall gets one plain relaunch; a persistent one escalates to a CM restart (fresh
    # cold-start) before the next attempt — not a restart per relaunch. hijack: stall, stall, land.
    restarts: list[int] = []
    record: dict = {}
    hijacks: list = [None, None, FakeController()]

    report = asyncio.run(
        run_auto_drive(
            _cfg(track_id="magione", car_id="ks_porsche_911_gt3_r_2016", max_launches=4),
            launch=lambda c: (True, "live"),
            hijack=lambda c: hijacks.pop(0),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), record),
            tap=_tap_returning(CONTINUOUS),
            verify_track=lambda c: ("magione", "ks_porsche_911_gt3_r_2016"),  # correct combo
            restart_launcher=lambda c: restarts.append(1),
        )
    )

    assert report.ok is True
    # idx0 stall (no restart); idx1 plain relaunch (transient, no restart); idx2 (>=2) restarts CM
    # once, then the hijack lands and drives.
    assert len(restarts) == 1


def test_run_auto_drive_track_mismatch_fails_fast_after_exhausting_relaunches():
    # #537 bound: a PERSISTENT cached-session mismatch must not loop forever or ever drive the
    # wrong line — it FAILs at stage="launch" once the launch budget is spent (#535 honest guard).
    launches: list[int] = []
    controllers: list[FakeController] = []

    def _launch(config):  # noqa: ANN001
        launches.append(1)
        return True, "live"

    def _hijack(config):  # noqa: ANN001
        ctrl = FakeController()
        controllers.append(ctrl)
        return ctrl

    report = asyncio.run(
        run_auto_drive(
            _cfg(track_id="magione", car_id="ks_porsche_911_gt3_r_2016", max_launches=2),
            launch=_launch,
            hijack=_hijack,
            drive=lambda controller, config, stop: pytest.fail("must never drive the wrong track"),
            tap=_tap_returning(CONTINUOUS),
            verify_track=lambda c: ("spa", "ks_porsche_911_gt3_r_2016"),  # always wrong
        )
    )

    assert report.ok is False
    assert report.stage == "launch"
    assert "spa" in report.error and "magione" in report.error
    assert len(launches) == 2  # bounded by max_launches — no infinite relaunch
    assert all(c.closed for c in controllers)  # every mismatched controller released


def test_loaded_combo_mismatch_rules():
    from tools.ac_harness.auto_drive import loaded_combo_mismatch

    c = _cfg(track_id="magione", car_id="ks_porsche_911_gt3_r_2016")
    assert loaded_combo_mismatch(c, None) is None  # unreadable → cannot confirm → no block
    assert loaded_combo_mismatch(c, ("magione", "ks_porsche_911_gt3_r_2016")) is None  # match
    assert "track" in (loaded_combo_mismatch(c, ("spa", "ks_porsche_911_gt3_r_2016")) or "")
    assert "car" in (loaded_combo_mismatch(c, ("magione", "ks_audi_r8_lms")) or "")
    assert loaded_combo_mismatch(c, ("", "")) is None  # empty loaded id → cannot confirm
    c2 = _cfg(track_id="magione")  # no car requested → car not checked
    assert loaded_combo_mismatch(c2, ("magione", "anything")) is None


def test_setup_run_relaunches_on_cached_session_then_verifies():
    # #537 (Codex P2): a --setup run whose first CM launch serves a cached wrong session fails setup
    # fuel verification. The harness must RELAUNCH (bounded) rather than abort at stage="setup" on
    # the first cached session, so setup A/B runs get the same #537 retry; attempt 2 loads the
    # requested magione and the setup verifies.
    acks = [
        {"ok": False, "error": "fuel 60.0 != 45.0"},  # cached spa session — wrong fuel
        {"ok": True, "name": "Realistic_BB_v3", "path": "x/Realistic_BB_v3.ini"},  # correct magione
    ]
    loaded_tracks = ["spa", "magione"]
    launches: list[int] = []
    record: dict = {}

    def _launch(config):  # noqa: ANN001
        launches.append(1)
        return True, "live"

    async def _apply(config):  # noqa: ANN001
        return acks.pop(0)

    report = asyncio.run(
        run_auto_drive(
            _cfg(
                setup="Realistic_BB_v3",
                track_id="magione",
                car_id="ks_porsche_911_gt3_r_2016",
                max_launches=3,
            ),
            launch=_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), record),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply,
            verify_track=lambda c: (loaded_tracks.pop(0), "ks_porsche_911_gt3_r_2016"),
        )
    )
    assert report.ok is True
    assert report.stage != "setup"  # did not abort on the first cached session
    assert len(launches) == 2  # relaunched once for the cached session
    assert report.setup_applied is True
    assert record["controller"] is not None  # drove on the correct-combo session


def test_setup_run_cached_session_fails_setup_stage_after_budget():
    # Bound: a PERSISTENT cached wrong session on a --setup run still FAILs (bounded), and the error
    # names the cached-session cause so the evidence bundle isn't misread as a plain setup bug.
    launches: list[int] = []

    def _launch(config):  # noqa: ANN001
        launches.append(1)
        return True, "live"

    async def _apply(config):  # noqa: ANN001
        return {"ok": False, "error": "fuel 60.0 != 45.0"}

    report = asyncio.run(
        run_auto_drive(
            _cfg(
                setup="Realistic_BB_v3",
                track_id="magione",
                car_id="ks_porsche_911_gt3_r_2016",
                max_launches=2,
            ),
            launch=_launch,
            hijack=lambda c: pytest.fail("must not hijack the wrong session"),
            drive=lambda *a: pytest.fail("must not drive"),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply,
            verify_track=lambda c: ("spa", "ks_porsche_911_gt3_r_2016"),  # always cached spa
        )
    )
    assert report.ok is False
    assert report.stage == "setup"
    assert len(launches) == 2  # bounded — no infinite relaunch
    assert "cached session" in (report.error or "")  # names the real cause, not a plain setup bug


def test_run_auto_drive_mismatch_then_launch_failure_reports_stage_launch():
    # #537 (Codex P2): attempt 1 hits a cached-session mismatch (relaunch); attempt 2's launch never
    # reaches LIVE. The report must read stage="launch" (the real terminal cause), not a misleading
    # stage="hijack" that points the evidence bundle at the wrong subsystem.
    launch_outcomes = [(True, "live"), (False, "sim never reached LIVE")]

    def _launch(config):  # noqa: ANN001
        return launch_outcomes.pop(0)

    report = asyncio.run(
        run_auto_drive(
            _cfg(track_id="magione", car_id="ks_porsche_911_gt3_r_2016", max_launches=2),
            launch=_launch,
            hijack=lambda c: FakeController(),  # only attempt 1 reaches hijack
            drive=lambda controller, config, stop: pytest.fail("must not drive the wrong track"),
            tap=_tap_returning(CONTINUOUS),
            verify_track=lambda c: ("spa", "ks_porsche_911_gt3_r_2016"),  # attempt-1 mismatch
        )
    )
    assert report.ok is False
    assert report.stage == "launch"  # not "hijack" — the terminal cause was the failed relaunch
    assert "sim never reached LIVE" in (report.error or "")


def test_run_auto_drive_handshake_drive_outlives_the_tap():
    # #532: the handshake self-terminates (driver.finished); the orchestrator must NOT stop it at
    # the tap boundary or the probe schedule dies mid-maneuver.
    import time

    from tools.ac_harness.auto_drive import DriveStats, run_auto_drive

    seen: dict = {}

    def drive(controller, config, stop):
        time.sleep(0.15)  # tap below returns immediately; a premature stop would be set by now
        seen["stop_was_set"] = stop.is_set()
        return DriveStats(drove=True, laps=0, max_speed_kmh=90.0, total_distance_m=500.0)

    # A PASSING pipeline (CONTINUOUS -> seq_ok True) must NOT stop the handshake drive early.
    report = asyncio.run(
        run_auto_drive(
            _cfg(driver="handshake", skip_launch=True),
            launch=lambda c: (True, "ok"),
            hijack=lambda c: FakeController(),
            drive=drive,
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert seen["stop_was_set"] is False
    assert report.drive is not None and report.drive.drove is True


def test_run_auto_drive_handshake_stops_on_pipeline_failure():
    # #532 Codex: a FAILED pipeline (seq_ok False — e.g. missing continuous topics) must stop the
    # handshake drive instead of burning the whole drive_seconds budget.
    seen: dict = {}

    def drive(controller, config, stop):
        import time

        time.sleep(0.15)
        seen["stop_was_set"] = stop.is_set()
        return DriveStats(drove=True)

    report = asyncio.run(
        run_auto_drive(
            _cfg(driver="handshake", skip_launch=True),
            launch=lambda c: (True, "ok"),
            hijack=lambda c: FakeController(),
            drive=drive,
            tap=_tap_returning([_snap("connection")]),  # missing tire_temps/coaching -> seq fails
        )
    )
    assert report.sequence_ok is False
    assert seen["stop_was_set"] is True


def test_racing_driver_step_upshifts_at_high_rpm():
    # Direct evidence the racing controller commands an upshift out of 1st when revving + moving.
    racing = _build_driver(_cfg(pace=1.0, racing_max_speed_kmh=240.0), _LINE, _PROFILE)
    racing.phase = "LAP"  # skip OUT phase so longitudinal/gear logic runs
    frame = racing.step((25.0, 0.0, 0.0), (1.0, 0.0, 0.0), 120.0, 7500.0, 3, now=10.0)
    assert frame.gear_up is True  # rpm 7500 > rpm_up, gear 3 (2nd) < max -> upshift


def test_cli_args_map_to_config():
    args = _build_arg_parser().parse_args(
        [
            "--cm-preset",
            "p.cmpreset",
            "--track",
            "spa",
            "--wait-lap",
            "--strict",
            "--skip-launch",
            "--drive-seconds",
            "120",
            "--target-speed",
            "70",
            "--min-corner",
            "40",
            "--tap-seconds",
            "15",
            "--rig-lock-timeout",
            "12",
        ]
    )
    cfg = _config_from_args(args)
    assert str(cfg.cm_preset) == "p.cmpreset"
    assert cfg.track_id == "spa"
    assert cfg.wait_lap is True
    assert cfg.strict is True
    assert cfg.skip_launch is True
    assert cfg.drive_seconds == 120
    assert cfg.target_speed_kmh == 70
    assert cfg.min_corner_speed_kmh == 40
    assert cfg.tap_seconds == 15
    assert args.rig_lock_timeout == 12
    # --ac-root omitted -> default factory used.
    assert cfg.ac_root == default_ac_root()


def test_report_summary_renders_all_sections():
    report = AutoDriveReport(
        ok=True,
        stage="done",
        launched=True,
        hijacked=True,
        drive=DriveStats(drove=True, laps=1, total_distance_m=5200.0, max_speed_kmh=63.0),
        sequence_ok=True,
        counts={"coaching.snapshot": 300, "connection": 30},
        notes=["delta: not in window"],
    )
    text = report.summary()
    assert "PASS" in text
    assert "drove=True" in text
    assert "coaching.snapshot=300" in text
    assert "delta: not in window" in text


def test_report_summary_distinguishes_session_takeover_from_sim_death():
    report = AutoDriveReport(
        ok=False,
        stage="done",
        drive=DriveStats(
            drove=True,
            sim_pid=101,
            unexpected_sim_pids=[202],
            session_replaced=True,
            reason="unexpected acs.exe PID takeover",
        ),
    )
    text = report.summary()
    assert "session_replaced=True" in text
    assert "sim_dead=False" in text
    assert "unexpected_sim_pids=[202]" in text


# ---------------------------------------------------------------------------
# Setup application + verification (#459 Part A).
# ---------------------------------------------------------------------------
def _setups_tree(tmp_path):
    """A user-dir with setups for one car across track/generic/top-level folders."""
    user = tmp_path / "Assetto Corsa"
    car = user / "setups" / "ks_porsche_911_gt3_r_2016"
    (car / "spa").mkdir(parents=True)
    (car / "generic").mkdir(parents=True)
    (car / "spa" / "Realistic_BB_v3.ini").write_text("[FRONT_BIAS]\nVALUE=60\n")
    (car / "generic" / "AllRounder.ini").write_text("[FRONT_BIAS]\nVALUE=58\n")
    (car / "TopLevel.ini").write_text("[FRONT_BIAS]\nVALUE=55\n")
    return user


def test_resolve_setup_ini_precedence_track_then_generic_then_car(tmp_path):
    user = _setups_tree(tmp_path)
    car = "ks_porsche_911_gt3_r_2016"
    track_hit = resolve_setup_ini(user, car, "spa", "Realistic_BB_v3")
    assert track_hit.name == "Realistic_BB_v3.ini" and track_hit.parent.name == "spa"
    generic_hit = resolve_setup_ini(user, car, "spa", "AllRounder")
    assert generic_hit.parent.name == "generic"
    top_hit = resolve_setup_ini(user, car, "spa", "TopLevel")
    assert top_hit.parent.name == car


def test_resolve_setup_ini_layout_folder_wins_when_given(tmp_path):
    user = _setups_tree(tmp_path)
    car = "ks_porsche_911_gt3_r_2016"
    lay = user / "setups" / car / "spa" / "gp"
    lay.mkdir(parents=True)
    (lay / "Realistic_BB_v3.ini").write_text("[FRONT_BIAS]\nVALUE=61\n")
    hit = resolve_setup_ini(user, car, "spa", "Realistic_BB_v3", layout="gp")
    assert hit.parent.name == "gp"


def test_resolve_setup_ini_not_found_names_all_searched_locations(tmp_path):
    user = _setups_tree(tmp_path)
    with pytest.raises(FileNotFoundError) as err:
        resolve_setup_ini(user, "ks_porsche_911_gt3_r_2016", "spa", "NoSuchSetup")
    msg = str(err.value)
    assert "spa" in msg and "generic" in msg


def test_resolve_setup_ini_rejects_traversal_and_outside_paths(tmp_path):
    user = _setups_tree(tmp_path)
    car = "ks_porsche_911_gt3_r_2016"
    with pytest.raises(ValueError, match="unsafe setup name"):
        resolve_setup_ini(user, car, "spa", "..")
    outside = tmp_path / "evil.ini"
    outside.write_text("[X]\nVALUE=1\n")
    with pytest.raises(ValueError, match="user setups folder"):
        resolve_setup_ini(user, car, "spa", str(outside))
    with pytest.raises(ValueError, match="user setups folder"):
        resolve_setup_ini(user, car, "spa", "../../evil.ini")


def test_resolve_setup_ini_rejects_path_shaped_car_and_track_ids(tmp_path):
    # car/track/layout become path segments under the setups root — a separator or `..` in them
    # must be rejected before they join the root (#460 review: no containment on the id join).
    user = _setups_tree(tmp_path)
    with pytest.raises(ValueError, match="unsafe car id"):
        resolve_setup_ini(user, "../evil", "spa", "Realistic_BB_v3")
    with pytest.raises(ValueError, match="unsafe track id"):
        resolve_setup_ini(user, "ks_porsche_911_gt3_r_2016", "../../etc", "Realistic_BB_v3")
    with pytest.raises(ValueError, match="unsafe layout id"):
        resolve_setup_ini(
            user, "ks_porsche_911_gt3_r_2016", "spa", "Realistic_BB_v3", layout="../x"
        )


def test_resolve_setup_ini_bare_ini_basename_uses_name_search(tmp_path):
    # A bare "Foo.ini" (no separator) an operator copies from disk must search the car/track/generic
    # candidates, not resolve as a setups-root-relative path that skips the combo folders.
    user = _setups_tree(tmp_path)
    car = "ks_porsche_911_gt3_r_2016"
    hit = resolve_setup_ini(user, car, "spa", "Realistic_BB_v3.ini")
    assert hit.name == "Realistic_BB_v3.ini" and hit.parent.name == "spa"


def test_resolve_setup_ini_accepts_path_inside_setups_root(tmp_path):
    user = _setups_tree(tmp_path)
    car = "ks_porsche_911_gt3_r_2016"
    inside = user / "setups" / car / "spa" / "Realistic_BB_v3.ini"
    assert resolve_setup_ini(user, car, "spa", str(inside)) == inside.resolve()
    # Relative to the setups root also resolves.
    rel = f"{car}/spa/Realistic_BB_v3.ini"
    assert resolve_setup_ini(user, car, "spa", rel) == inside.resolve()


def test_resolve_ac_user_dir_prefers_existing_onedrive_redirect(tmp_path):
    onedrive = tmp_path / "OneDrive" / "Documents" / "Assetto Corsa"
    onedrive.mkdir(parents=True)
    assert resolve_ac_user_dir(home=tmp_path) == onedrive
    # Plain Documents wins when it exists (checked first).
    plain = tmp_path / "Documents" / "Assetto Corsa"
    plain.mkdir(parents=True)
    assert resolve_ac_user_dir(home=tmp_path) == plain
    # Explicit always wins.
    assert resolve_ac_user_dir(tmp_path / "explicit", home=tmp_path) == tmp_path / "explicit"


def test_bake_setup_into_race_ini_writes_both_keys_and_spawn():
    import configparser
    from pathlib import Path as _P

    # POSIX path so the test is platform-independent (on the rig setup_ini is a Windows Path;
    # Path.name only splits on the host separator, so a literal backslash path would not split
    # under Linux CI — the real caller always passes a native path).
    race = "[CAR_0]\nSKIN=brg\nMODEL=-\n\n[SESSION_0]\nNAME=Practice\nTYPE=1\nSPAWN_SET=PIT\n"
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    out = bake_setup_into_race_ini(race, setup)
    p = configparser.ConfigParser(strict=False)
    p.optionxform = str
    p.read_string(out)
    assert p.get("CAR_0", "SETUP") == "Realistic_BB_v3.ini"
    assert p.get("CAR_0", "_EXT_SETUP_FILENAME") == str(setup)
    assert p.get("SESSION_0", "SPAWN_SET") == "START"  # start line, not pit
    # Existing keys preserved.
    assert p.get("CAR_0", "SKIN") == "brg"


def test_bake_setup_creates_car0_section_if_absent():
    import configparser
    from pathlib import Path as _P

    out = bake_setup_into_race_ini("[RACE]\nMODEL=car\n", _P("/s/My Setup.ini"), spawn_set="PIT")
    p = configparser.ConfigParser(strict=False)
    p.optionxform = str
    p.read_string(out)
    assert p.get("CAR_0", "SETUP") == "My Setup.ini"
    assert p.get("SESSION_0", "SPAWN_SET") == "PIT"


def test_write_setup_baked_race_ini_updates_existing_race_ini_atomically(tmp_path):
    import configparser
    from pathlib import Path as _P

    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    race_ini.parent.mkdir(parents=True)
    race_ini.write_text("[CAR_0]\nSKIN=brg\n\n[SESSION_0]\nSPAWN_SET=PIT\n", encoding="utf-8")
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")

    assert write_setup_baked_race_ini(race_ini, setup) == "written"
    assert not (race_ini.parent / ".race.ini.ac_copilot_setup.tmp").exists()

    p = configparser.ConfigParser(strict=False)
    p.optionxform = str
    p.read_string(race_ini.read_text(encoding="utf-8"))
    assert p.get("CAR_0", "SETUP") == "Realistic_BB_v3.ini"
    assert p.get("CAR_0", "_EXT_SETUP_FILENAME") == str(setup)
    assert p.get("CAR_0", "SKIN") == "brg"
    assert p.get("SESSION_0", "SPAWN_SET") == "START"


def test_write_setup_baked_race_ini_skips_replace_when_already_baked(tmp_path, monkeypatch):
    from pathlib import Path as _P

    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    race_ini.parent.mkdir(parents=True)
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    race_ini.write_text(bake_setup_into_race_ini("[CAR_0]\n", setup), encoding="utf-8")
    replace_calls: list[pathlib.Path] = []
    original_replace = pathlib.Path.replace

    def _replace_records(self, target):  # noqa: ANN001, ANN202
        replace_calls.append(self)
        return original_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", _replace_records)

    assert write_setup_baked_race_ini(race_ini, setup) == "unchanged"
    assert replace_calls == []


def test_write_setup_baked_race_ini_waits_for_cm_to_create_race_ini(tmp_path):
    from pathlib import Path as _P

    missing = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    assert write_setup_baked_race_ini(missing, setup) == "missing"


def test_write_setup_baked_race_ini_rejects_non_ac_documents_target(tmp_path):
    from pathlib import Path as _P

    bad = tmp_path / "cfg" / "race.ini"
    bad.parent.mkdir()
    bad.write_text("[CAR_0]\n", encoding="utf-8")
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    with pytest.raises(ValueError, match="Assetto Corsa/cfg/race.ini"):
        write_setup_baked_race_ini(bad, setup)


def test_write_setup_baked_race_ini_allows_symlinked_ac_documents_dir(tmp_path):
    from pathlib import Path as _P

    real_root = tmp_path / "AC_Configs"
    real_cfg = real_root / "cfg"
    real_cfg.mkdir(parents=True)
    logical_root = tmp_path / "Documents" / "Assetto Corsa"
    logical_root.parent.mkdir(parents=True)
    try:
        logical_root.symlink_to(real_root, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    race_ini = logical_root / "cfg" / "race.ini"
    race_ini.write_text("[CAR_0]\n", encoding="utf-8")
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")

    assert write_setup_baked_race_ini(race_ini, setup) == "written"
    assert "_EXT_SETUP_FILENAME" in (real_cfg / "race.ini").read_text(encoding="utf-8")


def test_write_setup_baked_race_ini_cleans_temp_on_replace_failure(tmp_path, monkeypatch):
    from pathlib import Path as _P

    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    race_ini.parent.mkdir(parents=True)
    race_ini.write_text("[CAR_0]\n", encoding="utf-8")
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    tmp = race_ini.parent / ".race.ini.ac_copilot_setup.tmp"
    original_replace = pathlib.Path.replace

    def _replace_raises(self, target):  # noqa: ANN001, ANN202
        if self == tmp:
            raise OSError("locked")
        return original_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", _replace_raises)
    with pytest.raises(OSError, match="locked"):
        write_setup_baked_race_ini(race_ini, setup)
    assert not tmp.exists()


def test_write_setup_baked_race_ini_skips_torn_read_and_preserves_cm_keys(tmp_path, monkeypatch):
    """#466 B3: a torn read (race.ini changing under us mid-CM-write) must never be baked back — an
    atomic replace derived from a truncated read would silently drop the CM-owned sections. Two
    non-identical back-to-back reads are detected as unstable and nothing is written."""
    from pathlib import Path as _P

    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    race_ini.parent.mkdir(parents=True)
    cm_content = "[RACE]\nMODEL=cm_owned\n[CAR_0]\nSKIN=brg\n[SESSION_0]\nTYPE=1\n"
    race_ini.write_text(cm_content, encoding="utf-8")
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    # Two consecutive reads return different bytes → CM is rewriting the file right now.
    reads = iter([cm_content, "[CAR_0]\nSKIN=brg\n"])  # second read caught mid-truncation
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, *a, **k: next(reads))

    assert write_setup_baked_race_ini(race_ini, setup) == "unstable"

    monkeypatch.undo()
    # On-disk file is byte-for-byte the CM content — the truncation was never persisted.
    assert race_ini.read_text(encoding="utf-8") == cm_content
    assert not (race_ini.parent / ".race.ini.ac_copilot_setup.tmp").exists()


def test_write_setup_baked_race_ini_skips_unparseable_snapshot(tmp_path, monkeypatch):
    """#466 B3: a STABLE but unparseable read (torn such that two reads agree yet the content is not
    valid INI) is treated as a no-op instead of atomically replacing race.ini with a bad bake."""
    from pathlib import Path as _P

    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    race_ini.parent.mkdir(parents=True)
    cm_content = "[CAR_0]\nSKIN=brg\n"
    race_ini.write_text(cm_content, encoding="utf-8")
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    # Key=value before any [section] → MissingSectionHeaderError (a configparser.Error).
    garbage = "torn=1\nno_section_header=2\n"
    monkeypatch.setattr(pathlib.Path, "read_text", lambda self, *a, **k: garbage)

    assert write_setup_baked_race_ini(race_ini, setup) == "unstable"

    monkeypatch.undo()
    assert race_ini.read_text(encoding="utf-8") == cm_content
    assert not (race_ini.parent / ".race.ini.ac_copilot_setup.tmp").exists()


def test_race_ini_setup_bake_loop_rejects_non_positive_interval(tmp_path):
    from pathlib import Path as _P

    race_ini = tmp_path / "Assetto Corsa" / "cfg" / "race.ini"
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    with pytest.raises(ValueError, match="interval"):
        with race_ini_setup_bake_loop(race_ini, setup, interval=0):
            pass


def test_rig_launch_stops_rebake_loop_before_live_settle(tmp_path, monkeypatch):
    from pathlib import Path as _P

    import tools.ac_harness.entry_launcher as entry_launcher

    ac_user_dir = tmp_path / "Assetto Corsa"
    setup = _P("/home/x/Documents/Assetto Corsa/setups/car/spa/Realistic_BB_v3.ini")
    state = type("FakeBakeState", (), {"ready": 0, "writes": 0, "last_error": "locked"})()
    active = {"loop": False}
    sleeps: list[float] = []

    class FakeBakeLoop:
        def __enter__(self):  # noqa: ANN204
            active["loop"] = True
            return state

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            active["loop"] = False
            return False

    class FakeActuator:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        def normalize_prior_state(self) -> None:
            pass

        def launch(self) -> None:
            pass

        def relaunch(self) -> None:
            pytest.fail("single-attempt rig_launch should not relaunch after LIVE")

    def _fake_bake_loop(race_ini, setup_ini, *, interval):  # noqa: ANN001, ANN202
        assert race_ini == ac_user_dir / "cfg" / "race.ini"
        assert setup_ini == setup
        assert interval == 0.05
        return FakeBakeLoop()

    def _sleep(seconds: float) -> None:
        assert active["loop"] is False
        sleeps.append(seconds)

    monkeypatch.setattr(entry_launcher, "ContentManagerActuator", FakeActuator)
    monkeypatch.setattr("tools.ac_harness.auto_drive.race_ini_setup_bake_loop", _fake_bake_loop)
    monkeypatch.setattr("tools.ac_harness.auto_drive._wait_live", lambda timeout: True)
    monkeypatch.setattr("tools.ac_harness.auto_drive.time.sleep", _sleep)

    ok, detail = rig_launch(
        _cfg(
            ac_user_dir=ac_user_dir,
            setup="Realistic_BB_v3",
            setup_ini=setup,
            max_launches=1,
            settle_seconds=1.5,
        )
    )

    assert ok is True
    assert "setup verification deferred" in detail
    assert "locked" in detail
    assert sleeps == [1.5]


# ---------------------------------------------------------------------------
# Overlay fast-fail + CLI validation (#466).
# ---------------------------------------------------------------------------
def test_probe_and_rebake_cli_flags_map_to_config():
    base = ["--car", "ks_porsche_911_gt3_r_2016", "--track", "spa"]
    cfg = _config_from_args(_build_arg_parser().parse_args(base))
    assert cfg.hijack_probe_seconds == 5.0
    assert (
        cfg.setup_rebake_interval == AutoDriveConfig.setup_rebake_interval
    )  # CLI default == field
    cfg = _config_from_args(
        _build_arg_parser().parse_args(
            base + ["--hijack-probe-seconds", "2.5", "--setup-rebake-interval", "0.3"]
        )
    )
    assert cfg.hijack_probe_seconds == 2.5
    assert cfg.setup_rebake_interval == 0.3


def test_positive_float_flags_reject_bad_values():
    # A non-positive OR non-finite value must fail at parse time (clean usage error), not deep in
    # race_ini_setup_bake_loop, and not as a never-expiring hijack deadline (#482 review). `inf`
    # would make `deadline = monotonic() + probe` never expire — the exact hang #466 removes.
    base = ["--car", "ks_porsche_911_gt3_r_2016", "--track", "spa"]
    for flag in ("--setup-rebake-interval", "--hijack-probe-seconds", "--drive-seconds"):
        for bad in ("0", "-0.5", "inf", "nan"):
            with pytest.raises(SystemExit):
                _build_arg_parser().parse_args(base + [flag, bad])
    # A finite positive value still parses.
    cfg = _config_from_args(
        _build_arg_parser().parse_args(base + ["--hijack-probe-seconds", "7.5"])
    )
    assert cfg.hijack_probe_seconds == 7.5


def _fake_cai_factory(created: list, ready_when):
    """A fake CustomAIController: ``read_car_data`` returns a dict once ``ready_when()`` is true."""

    class _FakeCAI:
        def __init__(self, index: int = 0) -> None:
            self.index = index
            self.closed = False
            created.append(self)

        def read_car_data(self):  # noqa: ANN201
            return {"packet_id": 1} if ready_when() else None

        def close(self) -> None:
            self.closed = True

    return _FakeCAI


def test_rig_hijack_lands_on_a_later_recreate_probe(monkeypatch):
    """Car0 that only appears after a CarControls0 recreate is hijacked on the later probe."""
    import tools.ac_harness.auto_drive as ad

    clock = _Clock()
    created: list = []
    logs: list[str] = []

    # Car0 appears only once a 2nd CarControls0 has been created (the early-LIVE recreate race).
    monkeypatch.setattr(
        "tools.ac_harness.custom_ai.CustomAIController",
        _fake_cai_factory(created, lambda: len(created) >= 2),
    )
    monkeypatch.setattr(ad, "_log", lambda m: logs.append(m))
    monkeypatch.setattr(ad.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ad.time, "sleep", clock.sleep)

    ctrl = rig_hijack(_cfg(hijack_attempts=3, hijack_probe_seconds=0.5))

    assert ctrl is not None  # landed after the first recreate
    assert len(created) == 2  # probe 1 recreated, probe 2 landed — no third launch cycle needed
    assert created[0].closed is True  # the first section was released before the recreate
    assert any("hijack landed" in m for m in logs)


def test_rig_hijack_fast_fails_to_none_and_bounds_dead_time(monkeypatch):
    """A hard overlay stall (Car0 never appears) fast-fails to None, bounded probe budget."""
    import tools.ac_harness.auto_drive as ad

    clock = _Clock()
    created: list = []

    monkeypatch.setattr(
        "tools.ac_harness.custom_ai.CustomAIController",
        _fake_cai_factory(created, lambda: False),  # Car0 never appears
    )
    monkeypatch.setattr(ad, "_log", lambda m: None)
    monkeypatch.setattr(ad.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ad.time, "sleep", clock.sleep)

    ctrl = rig_hijack(_cfg(hijack_attempts=3, hijack_probe_seconds=0.5))

    assert ctrl is None
    assert len(created) == 3  # one short probe per attempt
    assert all(c.closed for c in created)  # every section released (no controller leak)
    # Bounded dead-wait: ~3 probes * 0.5 s (+ up to one 0.1 s poll each), NOT a single long
    # timeout. The point is the bound, not the exact figure — this is what kills the 25 s dead-wait.
    assert clock.now <= 3 * (0.5 + 0.1) + 1e-6


def test_parse_setup_fuel_reads_value_and_tolerates_missing():
    assert parse_setup_fuel("[FUEL]\nVALUE=45\nMIN=2\nMAX=120\n") == 45.0
    assert parse_setup_fuel("[FUEL]\nVALUE=63.5 ; litres\n") == 63.5
    assert parse_setup_fuel("[FRONT_BIAS]\nVALUE=60\n") is None  # no FUEL section
    assert parse_setup_fuel("[FUEL]\nVALUE=notanumber\n") is None


def test_fuel_matches_within_tolerance():
    assert fuel_matches(45.0, 45.0, 2.5) is True
    assert fuel_matches(45.0, 43.0, 2.5) is True
    assert fuel_matches(45.0, 40.0, 2.5) is False
    assert fuel_matches(None, 45.0, 2.5) is False
    assert fuel_matches(45.0, None, 2.5) is False


def test_verify_setup_ack_accepts_matching_name_or_path():
    ok, detail = verify_setup_ack(
        {"ok": True, "name": "Realistic_BB_v3", "path": "C:/x/spa/Realistic_BB_v3.ini"},
        "Realistic_BB_v3",
    )
    assert ok is True and "Realistic_BB_v3" in detail
    ok_path_only, _ = verify_setup_ack(
        {"ok": True, "name": "", "path": "C:\\x\\spa\\Realistic_BB_v3.ini"}, "Realistic_BB_v3"
    )
    assert ok_path_only is True


def test_verify_setup_ack_rejects_refusal_missing_and_wrong_setup():
    assert verify_setup_ack(None, "X")[0] is False
    refused_ok, refused_detail = verify_setup_ack({"ok": False, "error": "must be in pits"}, "X")
    assert refused_ok is False and "pits" in refused_detail
    wrong_ok, wrong_detail = verify_setup_ack(
        {"ok": True, "name": "OtherSetup", "path": "C:/x/OtherSetup.ini"}, "Realistic_BB_v3"
    )
    assert wrong_ok is False and "different setup" in wrong_detail


def _apply_returning(ack: dict, record: dict):
    async def _apply(config):  # noqa: ANN001
        record["applied"] = True
        return ack

    return _apply


def test_setup_leg_verified_run_proceeds_and_reports_applied():
    record: dict = {}
    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="Realistic_BB_v3"),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), {}),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply_returning(
                {"ok": True, "name": "Realistic_BB_v3", "path": "x/Realistic_BB_v3.ini"}, record
            ),
        )
    )
    assert record.get("applied") is True
    assert report.ok is True
    assert report.setup_requested == "Realistic_BB_v3"
    assert report.setup_applied is True
    assert "Realistic_BB_v3" in report.summary()


def test_setup_leg_refusal_fails_at_stage_setup_before_hijack():
    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="Realistic_BB_v3"),
            launch=_ok_launch,
            hijack=lambda c: pytest.fail("hijack must not run after a setup refusal"),
            drive=lambda *a: pytest.fail("must not drive with an unverified setup"),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply_returning({"ok": False, "error": "not found"}, {}),
        )
    )
    assert report.ok is False
    assert report.stage == "setup"
    assert report.hijacked is False  # setup applies BEFORE the hijack (pits gate closes under it)
    assert report.setup_applied is False
    assert "not found" in (report.error or "")


def test_setup_reapplies_after_hijack_relaunch():
    # A hijack miss relaunches AC — a NEW session — so the setup must re-apply each launch.
    applies: list[int] = []

    async def _apply(config):  # noqa: ANN001
        applies.append(1)
        return {"ok": True, "name": "Realistic_BB_v3", "path": "x/Realistic_BB_v3.ini"}

    hijacks: list[FakeController | None] = [None, FakeController()]
    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="Realistic_BB_v3", max_launches=2),
            launch=_ok_launch,
            hijack=lambda c: hijacks.pop(0),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), {}),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply,
        )
    )
    assert report.ok is True
    assert len(applies) == 2  # once per launch attempt — never a stale prior-session load


def test_setup_leg_wrong_setup_in_ack_fails():
    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="Realistic_BB_v3"),
            launch=_ok_launch,
            hijack=lambda c: pytest.fail("hijack must not run"),
            drive=lambda *a: pytest.fail("must not drive"),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply_returning({"ok": True, "name": "SomethingElse"}, {}),
        )
    )
    assert report.stage == "setup"
    assert report.ok is False


def test_setup_leg_exception_fails_before_hijack():
    async def _boom(config):  # noqa: ANN001
        raise RuntimeError("sidecar vanished")

    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="X"),
            launch=_ok_launch,
            hijack=lambda c: pytest.fail("hijack must not run"),
            drive=lambda *a: pytest.fail("must not drive"),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_boom,
        )
    )
    assert report.stage == "setup"
    assert "sidecar vanished" in (report.error or "")
    assert report.hijacked is False


def test_setup_requested_without_apply_leg_fails_explicitly():
    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="X"),
            launch=_ok_launch,
            hijack=lambda c: pytest.fail("hijack must not run"),
            drive=lambda *a: pytest.fail("must not drive"),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.stage == "setup"
    assert "no apply_setup leg" in (report.error or "")


def test_no_setup_requested_skips_apply_leg():
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, total_distance_m=900.0), {}),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply_returning({"ok": False}, {}),  # would fail if consulted
        )
    )
    assert report.ok is True
    assert report.setup_requested is None
    assert report.setup_applied is None


# ---------------------------------------------------------------------------
# Stall recovery (#459 Part D).
# ---------------------------------------------------------------------------
def test_progress_watchdog_trips_only_after_stall_window():
    dog = ProgressWatchdog(stall_seconds=10.0, min_progress_m=1.0)
    assert dog.update(0.0, 0.0) is False  # anchor
    assert dog.update(0.5, 5.0) is False  # <1 m progress but window not elapsed
    assert dog.update(0.6, 10.1) is True  # stalled: <1 m for >10 s
    # Progress re-anchors.
    dog2 = ProgressWatchdog(stall_seconds=10.0)
    dog2.update(0.0, 0.0)
    assert dog2.update(50.0, 9.0) is False  # moved — new anchor
    assert dog2.update(50.4, 18.9) is False  # window restarts from the move
    assert dog2.update(50.4, 19.1) is True


def test_progress_watchdog_reset_reanchors_after_recovery():
    dog = ProgressWatchdog(stall_seconds=5.0)
    dog.update(100.0, 0.0)
    assert dog.update(100.1, 5.1) is True
    dog.reset(6.0, 100.1)
    assert dog.update(100.2, 10.0) is False  # window restarted at reset
    assert dog.update(100.2, 11.2) is True


def test_should_try_line_teleport_on_recovery_off_line_always_retries():
    # #528: a car OFF the racing line must RETRY the line teleport on recovery even when no prior
    # line teleport is known good. car_off_line covers BOTH an off-line spawn AND a car a prior
    # recovery teleported into the pits (a mid-lap spin recovered to pits — the self-hosted
    # reviewer's case): teleport_to_pits leaves it off-line and would otherwise loop at 0 m.
    assert should_try_line_teleport_on_recovery(
        spawn_to_line_enabled=True, car_off_line=True, line_teleport_known_good=False
    )
    assert should_try_line_teleport_on_recovery(
        spawn_to_line_enabled=True, car_off_line=True, line_teleport_known_good=True
    )


def test_should_try_line_teleport_on_recovery_on_line_uses_pits():
    # A car ON the line (never teleported off) that spins: teleport_to_pits is the correct first
    # reset, so the line teleport is not attempted unless a prior line teleport is known good. Once
    # that pit teleport leaves the car off-line, _recover flips off_line True and the next recovery
    # takes the branch above — closing the mid-lap-into-pits loop the reviewer flagged.
    assert not should_try_line_teleport_on_recovery(
        spawn_to_line_enabled=True, car_off_line=False, line_teleport_known_good=False
    )
    assert should_try_line_teleport_on_recovery(
        spawn_to_line_enabled=True, car_off_line=False, line_teleport_known_good=True
    )


def test_should_try_line_teleport_on_recovery_honors_no_spawn_line():
    # --no-spawn-line (spawn_to_line_enabled=False) opts out of racing-line teleports entirely: even
    # an off-line car with a known-good line teleport must fall back to the pit exit, not the line,
    # on every recovery (codex on #539).
    assert not should_try_line_teleport_on_recovery(
        spawn_to_line_enabled=False, car_off_line=True, line_teleport_known_good=True
    )


def test_drive_leg_succeeded_true_only_for_a_real_clean_drive():
    assert drive_leg_succeeded(DriveStats(drove=True, total_distance_m=3200.0)) is True


def test_drive_leg_succeeded_vetoes_every_528_failure_shape():
    # None (hijack never landed), a never-moved stall, sim-death, and a recovery-capped stall must
    # each read as NOT a successful drive (#528). recovery_capped vetoes even with drove=True.
    assert drive_leg_succeeded(None) is False
    assert drive_leg_succeeded(DriveStats(drove=False, total_distance_m=0.0)) is False
    assert drive_leg_succeeded(DriveStats(drove=True, sim_dead=True)) is False
    assert drive_leg_succeeded(DriveStats(drove=True, session_replaced=True)) is False
    assert (
        drive_leg_succeeded(DriveStats(drove=True, total_distance_m=560.0, recovery_capped=True))
        is False
    )


def test_sim_process_identity_monitor_adopts_one_pid_and_detects_takeover():
    monitor = SimProcessIdentityMonitor()
    assert monitor.observe(set()) == ()
    assert monitor.observe({101}) == ()
    assert monitor.expected_pid == 101
    assert monitor.observe({101}) == ()
    assert monitor.observe(set()) == ()  # expected process can disappear before stall attribution
    assert monitor.observe({202}) == (202,)
    assert monitor.observe({101, 303}) == (303,)


def test_sim_process_identity_monitor_rejects_multiple_initial_acs_processes():
    monitor = SimProcessIdentityMonitor({303, 101})
    assert monitor.expected_pid is None
    assert monitor.observe({101, 303}) == (101, 303)
    assert monitor.observe({101}) == (101,)
    assert monitor.observe(set()) == (101, 303)
    assert monitor.expected_pid is None


def test_main_releases_registered_rig_cleanup_on_exception(monkeypatch):
    import tools.ac_harness.auto_drive as auto_drive_module

    released: list[bool] = []

    def fail_after_lock(_argv, cleanup):
        cleanup.callback(released.append, True)
        raise RuntimeError("evidence capture failed")

    monkeypatch.setattr(auto_drive_module, "_main_impl", fail_after_lock)
    with pytest.raises(RuntimeError, match="evidence capture failed"):
        auto_drive_module._main([])
    assert released == [True]


def test_rig_drive_synchronously_checks_pid_before_clean_stop(monkeypatch):
    import tools.ac_harness.ai_line as ai_line_module
    import tools.ac_harness.auto_drive as auto_drive_module
    import tools.ac_harness.entry_launcher as entry_launcher_module

    class NoopThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def join(self, **_kwargs) -> None:
            pass

    class Driver:
        pass

    observations = iter(({101}, {202}, {202}))
    monkeypatch.setattr(ai_line_module, "load_ai_line", lambda _path: _LINE)
    monkeypatch.setattr(
        auto_drive_module, "resolve_fast_lane", lambda *_args: pathlib.Path("fast_lane.ai")
    )
    monkeypatch.setattr(auto_drive_module, "_build_driver", lambda *_args: Driver())
    monkeypatch.setattr(auto_drive_module.threading, "Thread", NoopThread)
    monkeypatch.setattr(
        entry_launcher_module, "running_process_ids", lambda _name: frozenset(next(observations))
    )
    stop = threading.Event()
    stop.set()

    stats = auto_drive_module.rig_drive(
        FakeController(), _cfg(driver="lap", drive_seconds=1.0, spawn_to_line=False), stop
    )

    assert stats.session_replaced is True
    assert stats.sim_pid == 101
    assert stats.unexpected_sim_pids == [202]
    assert "expected_sim_pid=101" in stats.reason


def test_progress_watchdog_rejects_nonpositive_params():
    with pytest.raises(ValueError):
        ProgressWatchdog(stall_seconds=0.0)
    with pytest.raises(ValueError):
        ProgressWatchdog(stall_seconds=1.0, min_progress_m=0.0)


def test_recovery_capped_flag_vetoes_success():
    # The veto is a structured flag, NOT a magic substring in `reason` (#460 review).
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(
                DriveStats(
                    drove=True,
                    total_distance_m=560.0,
                    recoveries=7,
                    recovery_capped=True,
                    reason="recovery cap (6) exceeded at 560m",
                ),
                {},
            ),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.sequence_ok is True
    assert report.ok is False  # capped-out stall must not report success
    assert "recovery cap" in report.summary()


def test_recovery_capped_flag_is_what_vetoes_not_the_reason_string():
    # Even if `reason` were reworded, the flag alone must veto — proves the contract is the flag.
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(
                DriveStats(drove=True, total_distance_m=560.0, recovery_capped=True, reason=""),
                {},
            ),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.ok is False


def test_dual_failure_keeps_pipeline_stage_and_records_drive_crash_in_notes():
    # Sidecar death makes the tap raise AND the drive thread raise. The report must keep the
    # first (pipeline) stage/error and surface the drive crash in notes, never silently drop it.
    async def _boom_tap(url, *, seconds, wait_for_lap, **kwargs):  # noqa: ANN001
        raise RuntimeError("tap exploded")

    def _boom_drive(controller, config, stop):  # noqa: ANN001
        raise RuntimeError("drive exploded too")

    ctrl = FakeController()
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=_ok_launch,
            hijack=lambda c: ctrl,
            drive=_boom_drive,
            tap=_boom_tap,
        )
    )
    assert report.ok is False
    assert report.stage == "pipeline"  # first failure wins the stage
    assert "tap exploded" in (report.error or "")
    assert any("drive exploded too" in n for n in report.notes)  # drive crash not dropped
    assert ctrl.closed is True


# ---------------------------------------------------------------------------
# Deterministic preset + preflight (#459 Part B).
# ---------------------------------------------------------------------------
def test_build_practice_preset_is_deterministic_and_mode_correct():
    import json as _json

    a = build_practice_preset("ks_audi_r8_lms", "imola")
    b = build_practice_preset("ks_audi_r8_lms", "imola")
    assert a == b  # determinism-lock: identical output for identical combo
    preset = _json.loads(a)
    assert preset["CarId"] == "ks_audi_r8_lms"
    assert preset["TrackId"] == "imola"
    assert preset["Mode"].endswith("QuickDrive_Practice.xaml")
    assert preset["RealConditions"] is False  # pinned conditions, not live weather
    assert _json.loads(preset["ModeData"])["StartType"] == "START"
    pit = _json.loads(build_practice_preset("x", "y", start_type="PIT"))
    assert _json.loads(pit["ModeData"])["StartType"] == "PIT"
    with pytest.raises(ValueError, match="start_type"):
        build_practice_preset("x", "y", start_type="HOTLAP")


def _fake_rig(tmp_path, *, custom_ai="ENABLED=1\n"):
    """Minimal on-disk rig: ac_root with car/track content + CSP config, user dir, CM exe."""
    ac_root = tmp_path / "ac"
    (ac_root / "content" / "tracks" / "spa" / "ai").mkdir(parents=True)
    (ac_root / "content" / "tracks" / "spa" / "ai" / "fast_lane.ai").write_bytes(b"x")
    (ac_root / "content" / "cars" / "ks_porsche_911_gt3_r_2016").mkdir(parents=True)
    (ac_root / "extension" / "config").mkdir(parents=True)
    (ac_root / "extension" / "config" / "new_behaviour.ini").write_text(
        f"[CUSTOM_AI]\n; hidden\n{custom_ai}"
    )
    user = _setups_tree(tmp_path)
    cm = tmp_path / "cm" / "Content Manager.exe"
    cm.parent.mkdir(parents=True)
    cm.write_bytes(b"x")
    return ac_root, user, cm


def test_preflight_passes_on_complete_rig(tmp_path):
    ac_root, user, cm = _fake_rig(tmp_path)
    cfg = _cfg(
        ac_root=ac_root,
        ac_user_dir=user,
        cm_exe=cm,
        track_id="spa",
        car_id="ks_porsche_911_gt3_r_2016",
        setup="Realistic_BB_v3",
        cm_preset=None,
    )
    assert preflight(cfg) == []


def test_preflight_reports_missing_content_and_disabled_custom_ai(tmp_path):
    ac_root, user, cm = _fake_rig(tmp_path, custom_ai="ENABLED=0\n")
    cfg = _cfg(
        ac_root=ac_root,
        ac_user_dir=user,
        cm_exe=cm,
        track_id="nordschleife",  # not installed in the fake rig
        car_id="ks_missing_car",
        setup="NoSuchSetup",
        cm_preset=None,
    )
    checks = {i.check for i in preflight(cfg)}
    assert {"track", "car", "custom_ai", "setup"} <= checks


def test_preflight_detects_preset_combo_mismatch(tmp_path):
    import json as _json

    ac_root, user, cm = _fake_rig(tmp_path)
    preset = tmp_path / "wrong.cmpreset"
    preset.write_text(_json.dumps({"CarId": "ks_audi_r8_lms", "TrackId": "magione"}))
    cfg = _cfg(
        ac_root=ac_root,
        ac_user_dir=user,
        cm_exe=cm,
        track_id="spa",
        car_id="ks_porsche_911_gt3_r_2016",
        cm_preset=preset,
    )
    checks = {i.check for i in preflight(cfg)}
    assert "preset_track_mismatch" in checks
    assert "preset_car_mismatch" in checks


def test_preflight_flags_missing_cm_preset(tmp_path):
    ac_root, user, cm = _fake_rig(tmp_path)
    cfg = _cfg(
        ac_root=ac_root,
        ac_user_dir=user,
        cm_exe=cm,
        track_id="spa",
        cm_preset=tmp_path / "does-not-exist.cmpreset",
    )
    checks = {i.check for i in preflight(cfg)}
    assert "preset_missing" in checks


def test_preflight_rejects_skip_launch_with_setup(tmp_path):
    ac_root, user, cm = _fake_rig(tmp_path)
    cfg = _cfg(
        ac_root=ac_root,
        ac_user_dir=user,
        cm_exe=cm,
        track_id="spa",
        car_id="ks_porsche_911_gt3_r_2016",
        setup="Realistic_BB_v3",
        skip_launch=True,
        cm_preset=None,
    )
    issues = [i for i in preflight(cfg) if i.check == "setup"]
    assert any("skip-launch" in i.message for i in issues)


def test_preflight_layout_preset_mismatch(tmp_path):
    import json as _json

    ac_root, user, cm = _fake_rig(tmp_path)
    # add a layout fast_lane so track resolution passes
    lay = ac_root / "content" / "tracks" / "spa" / "gp" / "ai"
    lay.mkdir(parents=True)
    (lay / "fast_lane.ai").write_bytes(b"x")
    preset = tmp_path / "baselayout.cmpreset"
    preset.write_text(_json.dumps({"CarId": "ks_porsche_911_gt3_r_2016", "TrackId": "spa"}))
    cfg = _cfg(
        ac_root=ac_root,
        ac_user_dir=user,
        cm_exe=cm,
        track_id="spa",
        track_layout="gp",
        car_id="ks_porsche_911_gt3_r_2016",
        cm_preset=preset,
    )
    checks = {i.check for i in preflight(cfg)}
    assert "preset_track_mismatch" in checks  # preset TrackId "spa" != wanted "spa/gp"


def test_build_practice_preset_folds_layout_into_trackid():
    import json as _json

    p = _json.loads(build_practice_preset("car", "monza", layout="layout_junior"))
    assert p["TrackId"] == "monza/layout_junior"
    # No layout → base track.
    assert _json.loads(build_practice_preset("car", "monza"))["TrackId"] == "monza"


def test_preflight_missing_ac_root_short_circuits(tmp_path):
    cfg = _cfg(ac_root=tmp_path / "nope", track_id="spa", cm_preset=None)
    issues = preflight(cfg)
    assert len(issues) == 1 and issues[0].check == "ac_root"


def test_custom_ai_enabled_user_file_overrides_root(tmp_path):
    ac_root, user, _cm = _fake_rig(tmp_path, custom_ai="ENABLED=1\n")
    enabled, _ = custom_ai_enabled(ac_root, user)
    assert enabled is True
    user_ini = user / "cfg" / "extension" / "new_behaviour.ini"
    user_ini.parent.mkdir(parents=True)
    user_ini.write_text("[CUSTOM_AI]\nENABLED=0\n")
    enabled_after, detail = custom_ai_enabled(ac_root, user)
    assert enabled_after is False and "cfg" in detail


def test_custom_ai_enabled_unknown_when_no_file_carries_the_key(tmp_path):
    enabled, detail = custom_ai_enabled(tmp_path / "ac", tmp_path / "user")
    assert enabled is None and "new_behaviour.ini" in detail


def test_custom_ai_enabled_tolerates_utf8_bom(tmp_path):
    # CM/CSP tooling writes some ini files with a UTF-8 BOM — a BOM'd first section header used
    # to raise MissingSectionHeaderError and falsely block preflight (#460 review).
    ac_root = tmp_path / "ac"
    (ac_root / "extension" / "config").mkdir(parents=True)
    path = ac_root / "extension" / "config" / "new_behaviour.ini"
    path.write_text("[CUSTOM_AI]\nENABLED=1\n", encoding="utf-8-sig")  # BOM prefix
    enabled, _ = custom_ai_enabled(ac_root, tmp_path / "user")
    assert enabled is True


def test_custom_ai_enabled_does_not_crash_on_undecodable_bytes(tmp_path):
    ac_root = tmp_path / "ac"
    (ac_root / "extension" / "config").mkdir(parents=True)
    path = ac_root / "extension" / "config" / "new_behaviour.ini"
    path.write_bytes(b"[CUSTOM_AI]\nENABLED=1\n\xff\xfe not utf-8 \x80\x81")
    # Must not raise — returns (None, detail) so preflight can report, not blow up.
    enabled, detail = custom_ai_enabled(ac_root, tmp_path / "user")
    assert enabled in (True, None)
    assert isinstance(detail, str)


# ---------------------------------------------------------------------------
# Evidence bundle (#459 Part C).
# ---------------------------------------------------------------------------
def test_write_evidence_bundles_report_and_extras(tmp_path):
    import json as _json

    report = AutoDriveReport(
        ok=True,
        stage="done",
        car_id="ks_porsche_911_gt3_r_2016",
        track_id="spa",
        setup_requested="Realistic_BB_v3",
        setup_applied=True,
        drive=DriveStats(drove=True, total_distance_m=7004.0, recoveries=1),
    )
    out = write_evidence(tmp_path / "ev", report, extras={"hud": {"rendering": True}})
    payload = _json.loads(out.read_text(encoding="utf-8"))
    assert payload["report"]["ok"] is True
    assert payload["report"]["setup_applied"] is True
    assert payload["report"]["drive"]["recoveries"] == 1
    assert payload["hud"]["rendering"] is True


def test_collect_lap_archives_filters_by_mtime(tmp_path):
    import os

    laps = tmp_path / "laps"
    laps.mkdir()
    old = laps / "lap_old.json"
    new = laps / "lap_new.json"
    old.write_text("{}")
    new.write_text("{}")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    assert collect_lap_archives(laps, since_epoch=1_500_000) == [str(new)]
    assert collect_lap_archives(None, since_epoch=0) == []


def test_collect_lap_archives_no_wait_returns_immediately(tmp_path):
    # A run that produced no lap must NOT poll — return the (empty) scan immediately, no sleeping.
    laps = tmp_path / "laps"
    laps.mkdir()
    slept: list[float] = []
    got = collect_lap_archives(
        laps, since_epoch=0, wait_for_first=False, _sleep=slept.append, _clock=lambda: 0.0
    )
    assert got == []
    assert slept == []  # never waited


def test_collect_lap_archives_waits_for_async_archive(tmp_path):
    # The async writer finalizes lap_*.json a moment AFTER the lap frame (#515). With wait_for_first
    # the poll must pick it up once it lands rather than racing to an empty list.
    import os

    laps = tmp_path / "laps"
    laps.mkdir()
    lap = laps / "lap_late.json"
    clock = {"t": 0.0}

    def _clock() -> float:
        return clock["t"]

    def _sleep(dt: float) -> None:
        clock["t"] += dt
        if clock["t"] >= 1.0 and not lap.exists():  # writer finalizes ~1s in
            lap.write_text("{}")
            os.utime(lap, (2_000_000, 2_000_000))

    got = collect_lap_archives(
        laps,
        since_epoch=1_500_000,
        wait_for_first=True,
        timeout_s=8.0,
        poll_s=0.5,
        _clock=_clock,
        _sleep=_sleep,
    )
    assert got == [str(lap)]


def test_collect_lap_archives_waits_for_expected_handshake_count(tmp_path):
    import os

    laps = tmp_path / "laps"
    laps.mkdir()
    first = laps / "lap_1.json"
    second = laps / "lap_2.json"
    first.write_text("{}")
    os.utime(first, (2_000_000, 2_000_000))
    clock = {"t": 0.0}

    def _clock() -> float:
        return clock["t"]

    def _sleep(dt: float) -> None:
        clock["t"] += dt
        if clock["t"] >= 1.0 and not second.exists():
            second.write_text("{}")
            os.utime(second, (2_000_001, 2_000_001))

    got = collect_lap_archives(
        laps,
        since_epoch=1_500_000,
        wait_for_first=True,
        min_count=2,
        timeout_s=8.0,
        poll_s=0.5,
        _clock=_clock,
        _sleep=_sleep,
    )
    assert got == [str(second), str(first)]
    assert clock["t"] >= 1.0


def test_collect_lap_archives_waits_for_expected_valid_handshake_count(tmp_path):
    import os

    laps = tmp_path / "laps"
    laps.mkdir()
    invalid = laps / "lap_invalid.json"
    first = laps / "lap_valid_1.json"
    invalid.write_text('{"lap":{"is_valid":false}}')
    first.write_text('{"lap":{"is_valid":true}}')
    os.utime(invalid, (2_000_000, 2_000_000))
    os.utime(first, (2_000_001, 2_000_001))
    second = laps / "lap_valid_2.json"
    clock = {"t": 0.0}

    def _clock() -> float:
        return clock["t"]

    def _sleep(dt: float) -> None:
        clock["t"] += dt
        if clock["t"] >= 1.0 and not second.exists():
            second.write_text('{"lap":{"is_valid":true}}')
            os.utime(second, (2_000_002, 2_000_002))

    got = collect_lap_archives(
        laps,
        since_epoch=1_500_000,
        wait_for_first=True,
        min_count=2,
        min_valid_count=2,
        timeout_s=8.0,
        poll_s=0.5,
        _clock=_clock,
        _sleep=_sleep,
    )
    assert got == [str(second), str(first), str(invalid)]
    assert clock["t"] >= 1.0


def test_collect_lap_archives_valid_count_applies_combo_predicate(tmp_path):
    import os

    laps = tmp_path / "laps"
    laps.mkdir()
    wrong = laps / "lap_wrong.json"
    right = laps / "lap_right.json"
    wrong.write_text('{"car":{"id":"other"},"track":{"id":"magione"},"lap":{"is_valid":true}}')
    right.write_text('{"car":{"id":"car"},"track":{"id":"magione"},"lap":{"is_valid":true}}')
    os.utime(wrong, (2_000_000, 2_000_000))
    os.utime(right, (2_000_001, 2_000_001))
    clock = {"t": 0.0}
    final = laps / "lap_final.json"

    def _sleep(dt: float) -> None:
        clock["t"] += dt
        if clock["t"] >= 1.0 and not final.exists():
            final.write_text(
                '{"car":{"id":"car"},"track":{"id":"magione"},"lap":{"is_valid":true}}'
            )
            os.utime(final, (2_000_002, 2_000_002))

    got = collect_lap_archives(
        laps,
        since_epoch=1_500_000,
        wait_for_first=True,
        min_valid_count=2,
        valid_archive_predicate=lambda payload: payload.get("car", {}).get("id") == "car",
        timeout_s=8.0,
        poll_s=0.5,
        _clock=lambda: clock["t"],
        _sleep=_sleep,
    )
    assert got[0] == str(final)
    assert clock["t"] >= 1.0


def test_collect_lap_archives_rejects_invalid_required_count(tmp_path):
    with pytest.raises(ValueError, match="min_count"):
        collect_lap_archives(tmp_path, since_epoch=0, min_count=0)


def test_collect_lap_archives_wait_times_out_bounded(tmp_path):
    # If the archive never appears, the poll is bounded and returns [] rather than hanging.
    laps = tmp_path / "laps"
    laps.mkdir()
    clock = {"t": 0.0}
    calls = {"n": 0}

    def _clock() -> float:
        return clock["t"]

    def _sleep(dt: float) -> None:
        clock["t"] += dt
        calls["n"] += 1

    got = collect_lap_archives(
        laps,
        since_epoch=0,
        wait_for_first=True,
        timeout_s=2.0,
        poll_s=0.5,
        _clock=_clock,
        _sleep=_sleep,
    )
    assert got == []
    assert calls["n"] <= 5  # ~timeout_s/poll_s, bounded — did not spin forever


def test_collect_lap_archives_present_first_skips_wait(tmp_path):
    # An archive already on disk is returned without entering the poll loop.
    import os

    laps = tmp_path / "laps"
    laps.mkdir()
    lap = laps / "lap_present.json"
    lap.write_text("{}")
    os.utime(lap, (2_000_000, 2_000_000))
    slept: list[float] = []
    got = collect_lap_archives(
        laps, since_epoch=1_500_000, wait_for_first=True, _sleep=slept.append, _clock=lambda: 0.0
    )
    assert got == [str(lap)]
    assert slept == []  # found on the first scan, never polled


def test_collect_lap_archives_waits_for_dir_created_during_poll(tmp_path):
    # Fresh profile: journal/laps does not exist at the first scan; the async writer creates BOTH
    # the dir and the finalized file on a later frame. Polling the (initially absent) path must
    # still find it once it appears (#515 review — discovery would return None otherwise).
    import os

    laps = tmp_path / "cfg_laps_not_yet"
    clock = {"t": 0.0}

    def _clock() -> float:
        return clock["t"]

    def _sleep(dt: float) -> None:
        clock["t"] += dt
        if clock["t"] >= 1.0 and not laps.exists():
            laps.mkdir()
            lap = laps / "lap_x.json"
            lap.write_text("{}")
            os.utime(lap, (2_000_000, 2_000_000))

    got = collect_lap_archives(
        laps,
        since_epoch=1_500_000,
        wait_for_first=True,
        timeout_s=8.0,
        poll_s=0.5,
        _clock=_clock,
        _sleep=_sleep,
    )
    assert got == [str(laps / "lap_x.json")]


def test_collect_lap_archives_rediscovers_dir_during_poll(tmp_path):
    # Fresh profile + (possibly renamed) install: journal_dir is None at call time; the writer makes
    # the dir at its ACTUAL path mid-poll. A `resolve` callable re-run each scan must find it, not a
    # hardcoded path (#516 review — the known-path fallback broke renamed installs).
    import os

    target = tmp_path / "renamed_app" / "journal" / "laps"

    def _resolve():
        return [target] if target.is_dir() else []

    clock = {"t": 0.0}

    def _clock() -> float:
        return clock["t"]

    def _sleep(dt: float) -> None:
        clock["t"] += dt
        if clock["t"] >= 1.0 and not target.exists():
            target.mkdir(parents=True)
            lap = target / "lap_y.json"
            lap.write_text("{}")
            os.utime(lap, (2_000_000, 2_000_000))

    got = collect_lap_archives(
        None,
        since_epoch=1_500_000,
        resolve=_resolve,
        wait_for_first=True,
        timeout_s=8.0,
        poll_s=0.5,
        _clock=_clock,
        _sleep=_sleep,
    )
    assert got == [str(target / "lap_y.json")]


def test_collect_lap_archives_follows_resolver_off_stale_dir(tmp_path):
    # A stale leftover dir (old files) is returned first; the canonical dir with the NEW archive
    # appears mid-poll. With journal_dir=None the poll re-resolves each scan and must follow the
    # resolver to the canonical dir, not pin to stale — the stale old file is excluded by the
    # since_epoch gate (#516 review).
    import os

    stale = tmp_path / "stale" / "laps"
    stale.mkdir(parents=True)
    old = stale / "lap_old.json"
    old.write_text("{}")
    os.utime(old, (1_000_000, 1_000_000))  # before since_epoch -> filtered out
    canonical = tmp_path / "canonical" / "laps"

    clock = {"t": 0.0}

    def _clock() -> float:
        return clock["t"]

    def _resolve():
        # Both are candidates — the stale default persists after a rename (CSP doesn't delete it).
        # Scanning all + the mtime gate must still find the fresh archive, not shadow it with stale.
        return [d for d in (stale, canonical) if d.is_dir()]

    def _sleep(dt: float) -> None:
        clock["t"] += dt
        if clock["t"] >= 1.0 and not canonical.exists():
            canonical.mkdir(parents=True)
            new = canonical / "lap_new.json"
            new.write_text("{}")
            os.utime(new, (2_000_000, 2_000_000))

    got = collect_lap_archives(
        None,
        since_epoch=1_500_000,
        resolve=_resolve,
        wait_for_first=True,
        timeout_s=8.0,
        poll_s=0.5,
        _clock=_clock,
        _sleep=_sleep,
    )
    assert got == [str(canonical / "lap_new.json")]  # followed to canonical; stale old file ignored


def test_candidate_journal_laps_dirs_includes_canonical_and_renamed(tmp_path):
    # A stale canonical dir AND a renamed-install dir both exist; candidate_journal_laps_dirs must
    # return BOTH so the scan finds the active writer's archive regardless of the stale leftover.
    canonical = known_journal_laps_dir(tmp_path)
    canonical.mkdir(parents=True)
    renamed = tmp_path / "cfg" / "extension" / "state" / "lua" / "app" / "Renamed" / "renamed"
    renamed_laps = renamed / "journal" / "laps"
    renamed_laps.mkdir(parents=True)
    dirs = candidate_journal_laps_dirs(tmp_path)
    assert canonical in dirs
    assert renamed_laps in dirs
    # No dirs when nothing exists.
    assert candidate_journal_laps_dirs(tmp_path / "empty") == []


def test_known_journal_laps_dir_is_canonical(tmp_path):
    d = known_journal_laps_dir(tmp_path)
    assert d == (
        tmp_path
        / "cfg"
        / "extension"
        / "state"
        / "lua"
        / "app"
        / "AC_Copilot_Trainer"
        / "ac_copilot_trainer"
        / "journal"
        / "laps"
    )


def test_nonneg_float_allows_zero_rejects_inf_and_negative():
    import argparse

    from tools.ac_harness.auto_drive import _nonneg_float

    assert _nonneg_float("0") == 0.0
    assert _nonneg_float("8") == 8.0
    for bad in ("inf", "-inf", "nan", "-1"):
        with pytest.raises(argparse.ArgumentTypeError):
            _nonneg_float(bad)


def test_cli_new_flags_map_to_config(tmp_path):
    args = _build_arg_parser().parse_args(
        [
            "--car",
            "ks_porsche_911_gt3_r_2016",
            "--track",
            "spa",
            "--setup",
            "Realistic_BB_v3",
            "--driver",
            "ggv",
            "--max-recoveries",
            "3",
            "--progress-stall-seconds",
            "8",
            "--no-spawn-line",
        ]
    )
    cfg = _config_from_args(args)
    assert cfg.cm_preset is None  # generated later from --car/--track
    assert cfg.car_id == "ks_porsche_911_gt3_r_2016"
    assert cfg.setup == "Realistic_BB_v3"
    assert cfg.driver == "ggv"
    assert cfg.max_recoveries == 3
    assert cfg.progress_stall_seconds == 8.0
    assert cfg.spawn_to_line is False


# --------------------------------------------------------------------------- #577 flying-lap window
def _timed_lap_snap(ms: int | None) -> dict:
    return {"type": "state.snapshot", "topic": "lap", "v": 1, "payload": {"last_lap_ms": ms}}


def test_multi_lap_window_passes_lap_count_and_reports_lap_times():
    record: dict = {}
    tap_record: dict = {}
    frames = [
        *CONTINUOUS,
        _snap("session"),
        _timed_lap_snap(None),  # teleport/out-lap boundary: not counted
        _timed_lap_snap(95000),
        _timed_lap_snap(93000),
        _timed_lap_snap(91500),
    ]
    report = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, target_laps=3),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, laps=3), record),
            tap=_tap_returning(frames, tap_record),
        )
    )
    assert report.ok is True
    assert tap_record["lap_count"] == 3  # the tap holds the window open for the batch
    assert report.lap_times_ms == [95000, 93000, 91500]
    assert report.laps_requested == 3
    assert not any("requested 3" in n for n in report.notes)  # no shortfall note when met


def test_multi_lap_window_shortfall_is_noted_not_failed():
    record: dict = {}
    frames = [*CONTINUOUS, _snap("session"), _timed_lap_snap(96000)]
    report = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, target_laps=3),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, laps=1), record),
            tap=_tap_returning(frames, record),
        )
    )
    # "N laps or the time budget, whichever first": one timed lap still satisfies require_lap;
    # the shortfall is reported honestly for the self-play verdict to consume.
    assert report.ok is True
    assert report.lap_times_ms == [96000]
    assert any("requested 3, observed 1" in n for n in report.notes)


def test_single_lap_wait_keeps_legacy_tap_contract():
    record: dict = {}
    frames = [*CONTINUOUS, _snap("session"), _snap("lap")]
    report = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, laps=1), record),
            tap=_tap_returning(frames, record),
        )
    )
    assert report.ok is True
    assert "lap_count" not in record  # legacy single-lap wait: no batch kwarg
    assert report.lap_times_ms == []  # untimed boundary carries no trajectory


def test_cli_laps_implies_wait_lap_and_rejects_negative():
    args = _build_arg_parser().parse_args(["--car", "c", "--track", "t", "--laps", "3"])
    cfg = _config_from_args(args)
    assert cfg.wait_lap is True
    assert cfg.target_laps == 3
    assert cfg.drive_seconds == 180.0 + 240.0 * 3
    explicit = _build_arg_parser().parse_args(
        ["--car", "c", "--track", "t", "--laps", "3", "--drive-seconds", "200"]
    )
    assert _config_from_args(explicit).drive_seconds == 200.0
    from tools.ac_harness.auto_drive import resolve_lap_window_drive_seconds

    for bad in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="drive seconds must be finite and > 0"):
            resolve_lap_window_drive_seconds(bad, 3)
    args = _build_arg_parser().parse_args(["--car", "c", "--track", "t"])
    cfg = _config_from_args(args)
    assert cfg.wait_lap is False and cfg.target_laps == 0 and cfg.drive_seconds == 300.0
    from tools.ac_harness.auto_drive import _main

    assert _main(["--car", "c", "--track", "magione", "--laps", "-1"]) == 2


def test_build_driver_alien_overspeed_optin_is_bounded():
    # #577: the self-play ladder may probe above the uncertainty-safe envelope, but only via the
    # explicit opt-in and never above the hard cap.
    from tools.ac_harness.auto_drive import ALIEN_MAX_OVERSPEED_SCALE
    from tools.ac_harness.racing_driver import RacingDriver

    cfg = _cfg(
        driver="alien",
        alien_line=_LINE,
        alien_v_target=[40.0] * 4,
        plant_kwargs=dict(_ALIEN_PLANT_KWARGS),
        ggv_scale=1.1,
        alien_overspeed=True,
    )
    d = _build_driver(cfg, _LINE, None)
    assert isinstance(d, RacingDriver)
    assert max(d.profile) == pytest.approx(40.0 * 1.1)
    with pytest.raises(ValueError, match="ggv_scale"):
        _build_driver(replace(cfg, ggv_scale=ALIEN_MAX_OVERSPEED_SCALE + 0.01), _LINE, None)
    with pytest.raises(ValueError, match="ggv_scale"):
        _build_driver(replace(cfg, alien_overspeed=False), _LINE, None)


def test_one_lap_batch_requires_a_timed_lap_window():
    # #579 daemon HIGH: --laps 1 is a BATCH of one TIMED lap, not the legacy any-boundary wait —
    # the tap must receive lap_count=1 so an untimed out-lap/teleport boundary cannot end the
    # window with zero timed laps (which would falsify a healthy self-play iteration).
    record: dict = {}
    frames = [*CONTINUOUS, _snap("session"), _timed_lap_snap(97000)]
    report = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, target_laps=1),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, laps=1), record),
            tap=_tap_returning(frames, record),
        )
    )
    assert report.ok is True
    assert record["lap_count"] == 1
    assert report.lap_times_ms == [97000]


def test_lap_window_with_zero_timed_laps_fails_honestly():
    # #579 Codex P2: --laps N + only an untimed boundary must FAIL the run, not exit 0 with an
    # empty trajectory (require_lap alone is satisfiable by the untimed frame).
    record: dict = {}
    frames = [*CONTINUOUS, _snap("session"), _timed_lap_snap(None)]
    report = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True, target_laps=1),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True, laps=0), record),
            tap=_tap_returning(frames, record),
        )
    )
    assert report.ok is False
    assert report.lap_times_ms == []
    assert any("observed ZERO" in n for n in report.notes)


def test_collect_lap_archives_matching_count_is_validity_agnostic(tmp_path):
    # #579 Qodo + Codex: the batch gate waits for THIS combo's archives (a foreign app/combo's
    # file must not satisfy it) but never gates on validity (an AC-invalid archive is
    # falsification evidence that can never turn valid by waiting).
    import json as _json

    journal = tmp_path / "journal"
    journal.mkdir()

    def _write(name, car, valid):
        (journal / name).write_text(
            _json.dumps(
                {
                    "car": {"id": car},
                    "track": {"id": "imola", "layout": None},
                    "lap": {"lap_n": 1, "lap_ms": 90000, "is_valid": valid},
                }
            ),
            encoding="utf-8",
        )

    _write("lap_own_invalid.json", "car_a", False)
    _write("lap_foreign_valid.json", "other_car", True)

    def predicate(payload: dict) -> bool:
        return str(payload.get("car", {}).get("id")) == "car_a"

    clock = _Clock()
    # One own-combo (AC-invalid) archive satisfies min_matching_count=1 immediately — validity
    # never gates the batch poll.
    found = collect_lap_archives(
        journal,
        0.0,
        wait_for_first=True,
        min_count=1,
        min_matching_count=1,
        valid_archive_predicate=predicate,
        timeout_s=5.0,
        _clock=clock.monotonic,
        _sleep=clock.sleep,
    )
    assert len(found) == 2 and clock.now == 0.0  # returned on the first scan, no waiting
    # A foreign valid archive alone can NOT satisfy the matching gate: the poll runs to its
    # bounded timeout and returns what exists (honest shortfall, no hang).
    found = collect_lap_archives(
        journal,
        0.0,
        wait_for_first=True,
        min_count=1,
        min_matching_count=2,
        valid_archive_predicate=predicate,
        timeout_s=5.0,
        _clock=clock.monotonic,
        _sleep=clock.sleep,
    )
    assert len(found) == 2 and clock.now >= 5.0  # waited the bounded budget, then honest return
