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
    ProgressWatchdog,
    _build_arg_parser,
    _build_driver,
    _config_from_args,
    _wait_live,
    build_practice_preset,
    collect_lap_archives,
    custom_ai_enabled,
    default_ac_root,
    generic_gt3_ggv,
    preflight,
    resolve_ac_user_dir,
    resolve_fast_lane,
    resolve_setup_ini,
    run_auto_drive,
    verify_setup_ack,
    write_evidence,
)
from tools.ac_harness.shared_memory import AcGameStatus, GraphicsSnapshot, PhysicsSnapshot

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


def _tap_returning(frames: list[dict]):
    async def _tap(url, *, seconds, wait_for_lap):  # noqa: ANN001
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
    assert launches == [1, 1, 1]
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


def test_setup_leg_refusal_fails_at_stage_setup_without_driving():
    ctrl = FakeController()
    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="Realistic_BB_v3"),
            launch=_ok_launch,
            hijack=lambda c: ctrl,
            drive=lambda *a: pytest.fail("must not drive with an unverified setup"),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply_returning({"ok": False, "error": "not found"}, {}),
        )
    )
    assert report.ok is False
    assert report.stage == "setup"
    assert report.setup_applied is False
    assert "not found" in (report.error or "")
    assert ctrl.closed is True  # hijack released even though the run aborted


def test_setup_leg_wrong_setup_in_ack_fails():
    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="Realistic_BB_v3"),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
            drive=lambda *a: pytest.fail("must not drive"),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_apply_returning({"ok": True, "name": "SomethingElse"}, {}),
        )
    )
    assert report.stage == "setup"
    assert report.ok is False


def test_setup_leg_exception_fails_and_releases_controller():
    ctrl = FakeController()

    async def _boom(config):  # noqa: ANN001
        raise RuntimeError("sidecar vanished")

    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="X"),
            launch=_ok_launch,
            hijack=lambda c: ctrl,
            drive=lambda *a: pytest.fail("must not drive"),
            tap=_tap_returning(CONTINUOUS),
            apply_setup=_boom,
        )
    )
    assert report.stage == "setup"
    assert "sidecar vanished" in (report.error or "")
    assert ctrl.closed is True


def test_setup_requested_without_apply_leg_fails_explicitly():
    report = asyncio.run(
        run_auto_drive(
            _cfg(setup="X"),
            launch=_ok_launch,
            hijack=lambda c: FakeController(),
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


def test_progress_watchdog_rejects_nonpositive_params():
    with pytest.raises(ValueError):
        ProgressWatchdog(stall_seconds=0.0)
    with pytest.raises(ValueError):
        ProgressWatchdog(stall_seconds=1.0, min_progress_m=0.0)


def test_recovery_cap_reason_vetoes_success():
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
