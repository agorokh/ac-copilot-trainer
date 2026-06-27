"""Off-sim tests for the composed autonomous drive+assert loop (EPIC #154 Part G).

The four legs (launch / hijack / drive / tap) are injected as fakes so the orchestration —
ordering, the stop-event teardown, the drove-gates-success rule, and the failure-stage
reporting — is verified with no Assetto Corsa, no Windows, and no real sidecar.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from tools.ac_harness.auto_drive import (
    AutoDriveConfig,
    AutoDriveReport,
    DriveStats,
    _build_arg_parser,
    _build_driver,
    _config_from_args,
    default_ac_root,
    resolve_fast_lane,
    run_auto_drive,
)

# A tiny closed square line + a per-point speed profile, for driver-construction tests.
_LINE = [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (50.0, 0.0, 50.0), (0.0, 0.0, 50.0)]
_PROFILE = [40.0, 40.0, 40.0, 40.0]  # m/s targets


def _cfg(**kw) -> AutoDriveConfig:
    base = dict(cm_preset="preset.cmpreset", track_id="imola", tap_seconds=0.0)
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


def _drive_returning(stats: DriveStats, record: dict):
    def _drive(controller, config, stop: threading.Event) -> DriveStats:
        record["stop_set"] = stop.wait(timeout=2.0)
        record["controller"] = controller
        return stats

    return _drive


def _tap_returning(frames: list[dict]):
    async def _tap(url, *, seconds, wait_for_lap):  # noqa: ANN001
        return frames

    return _tap


def _ok_launch(config) -> tuple[bool, str]:  # noqa: ANN001
    return True, "live"


def test_launch_failure_short_circuits():
    record: dict = {}
    report = asyncio.run(
        run_auto_drive(
            _cfg(),
            launch=lambda c: (False, "no LIVE"),
            hijack=lambda c: pytest.fail("hijack must not run after launch failure"),
            drive=_drive_returning(DriveStats(drove=True), record),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert report.ok is False
    assert report.stage == "launch"
    assert report.error == "no LIVE"
    assert report.hijacked is False


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
    no_lap = asyncio.run(
        run_auto_drive(
            _cfg(wait_lap=True),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=_drive_returning(DriveStats(drove=True), {}),
            tap=_tap_returning(CONTINUOUS),
        )
    )
    assert no_lap.ok is False
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

    async def _boom(url, *, seconds, wait_for_lap):  # noqa: ANN001
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


def test_build_driver_rejects_unknown_driver():
    with pytest.raises(ValueError, match="unknown driver"):
        _build_driver(_cfg(driver="bogus"), _LINE, _PROFILE)


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
