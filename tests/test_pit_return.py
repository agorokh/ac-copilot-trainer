"""Natural return navigation and independent native arrival gates (#956)."""

from __future__ import annotations

import asyncio
import math
from dataclasses import replace
from pathlib import Path

import pytest

from tools.ac_harness.auto_drive import (
    AutoDriveConfig,
    DriveStats,
    drive_veto_reason,
    run_auto_drive,
)
from tools.ac_harness.pit_return import (
    PitArrivalProof,
    PitBox,
    PitReturnDriver,
    PitReturnStop,
    build_route,
    distance,
    observe_until_drive_ends,
)
from tools.ac_harness.shared_memory import AcGameStatus, GraphicsSnapshot


def native(**changes):
    return dict(
        session_id="native1",
        car_id="car",
        track_id="track",
        layout_id="",
        offline=True,
        position=[150, 0, 5],
        look=[1, 0, 0],
        **changes,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("offline", False),
        ("offline", None),
        ("car_id", "other"),
        ("track_id", "other"),
        ("layout_id", "other"),
        ("session_id", ""),
        ("position", [math.nan, 0, 0]),
        ("position", [True, 0, 0]),
        ("look", [0, 0, 0]),
        ("look", [math.inf, 0, 0]),
    ],
)
def test_geometry_fails_closed(field, value):
    payload = native()
    payload[field] = value
    with pytest.raises(ValueError):
        PitBox.from_native(payload, "car", "track", "")


def lines():
    # A large closed route with a straight entry and a parallel pit lane.
    fast = [(float(i), 0.0, 0.0) for i in range(250)]
    fast += [(250.0, 0.0, float(i)) for i in range(1, 101)]
    fast += [(float(i), 0.0, 100.0) for i in range(249, -1, -1)]
    fast += [(0.0, 0.0, float(i)) for i in range(99, 0, -1)]
    pit = [(float(i), 0.0, 2.0) for i in range(50, 220)]
    return fast, pit


def test_route_is_forward_open_and_terminates_at_actual_box():
    fast, pit = lines()
    box = PitBox.from_native(native(), "car", "track", "")
    route = build_route(fast, pit, fast[20], box)
    assert route[0] == fast[20] and route[-1] == box.position
    assert max(distance(a, b) for a, b in zip(route, route[1:], strict=False)) <= 5
    assert all(b[0] >= a[0] for a, b in zip(route, route[1:], strict=False))
    assert len(route) < 200  # No closure from pit exit back to entry.


def test_route_that_cannot_finish_at_the_speed_cap_is_denied_before_navigation():
    fast = [(float(i), 0.0, 0.0) for i in range(4501)]
    fast += [(4500.0, 0.0, float(i)) for i in range(1, 101)]
    fast += [(float(i), 0.0, 100.0) for i in range(4499, -1, -1)]
    fast += [(0.0, 0.0, float(i)) for i in range(99, 0, -1)]
    _, pit = lines()
    with pytest.raises(ValueError, match="return budget"):
        build_route(fast, pit, fast[200], PitBox.from_native(native(), "car", "track", ""))


@pytest.mark.parametrize("failure", ["gap", "reversed", "box_far", "elevation", "disconnected"])
def test_invalid_authored_route_denied(failure):
    fast, pit = lines()
    box = PitBox.from_native(native(), "car", "track", "")
    if failure == "gap":
        pit[80] = (1000.0, 0.0, 0.0)
    elif failure == "reversed":
        box = replace(box, look=(-1.0, 0.0, 0.0))
    elif failure == "box_far":
        box = replace(box, position=(150.0, 0.0, 30.0))
    elif failure == "elevation":
        box = replace(box, position=(150.0, 5.0, 5.0))
    else:
        pit = [(p[0], p[1], p[2] + 30) for p in pit]
    with pytest.raises(ValueError):
        build_route(fast, pit, fast[20], box)


def test_steering_reuses_canonical_right_sign_and_stop_has_no_throttle():
    driver = PitReturnDriver([(float(i), 0.0, 1.0) for i in range(101)], started_at=0)
    right = driver.step((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 10.0, 4000.0, 2, 0.0)
    assert right.steer > 0
    at_end = PitReturnDriver([(float(i), 0.0, 0.0) for i in range(101)], started_at=0)
    at_end.index = 99
    frame = at_end.step((99.5, 0.0, 0.0), (1.0, 0.0, 0.0), 0.2, 4000.0, 2, 1.0)
    assert frame.gas == 0 and frame.brake > 0 and not frame.needs_recovery


@pytest.mark.parametrize(
    "position,now", [((0.0, 0.0, 20.0), 1), ((0.0, 0.0, 0.0), 13), ((0.0, 0.0, 0.0), 241)]
)
def test_route_deviation_stall_and_deadline_stop(position, now):
    driver = PitReturnDriver([(float(i), 0.0, 0.0) for i in range(101)], started_at=0)
    with pytest.raises(ValueError):
        driver.step(position, (1.0, 0.0, 0.0), 0.0, 4000.0, 2, now)


def graphics(packet, *, pit=True, laps=2, status=AcGameStatus.LIVE):
    return GraphicsSnapshot(packet, status, pit, laps)


def test_geometric_arrival_is_not_native_proof_and_both_packets_must_advance():
    proof = PitArrivalProof()
    assert not proof.observe(graphics(1, pit=False), 1, 0.0, 0.0, 0.0)
    assert not proof.observe(graphics(2), 2, 0.0, 0.0, 0.2)
    for t in (0.4, 0.6, 0.8):
        assert not proof.observe(graphics(2), 3, 0.0, 0.0, t)
    assert proof.samples == 1
    assert not proof.observe(graphics(3), 3, 0.0, 0.0, 1.0)
    assert proof.observe(graphics(4), 4, 0.0, 0.0, 1.2)


@pytest.mark.parametrize("failure", ["rollback", "pause", "missing", "motion", "outside_box"])
def test_arrival_proof_denies_bad_native_evidence(failure):
    proof = PitArrivalProof()
    assert not proof.observe(graphics(1), 1, 0.0, 0.0, 0.0)
    if failure in ("rollback", "pause", "missing"):
        g = (
            graphics(2, laps=1)
            if failure == "rollback"
            else (graphics(2, status=AcGameStatus.PAUSE) if failure == "pause" else None)
        )
        with pytest.raises(ValueError):
            proof.observe(g, 2, 0.0, 0.0, 0.2)
    else:
        for i in range(2, 6):
            assert not proof.observe(
                graphics(i),
                i,
                1.0 if failure == "motion" else 0.0,
                10.0 if failure == "outside_box" else 0.0,
                i * 0.2,
            )
        assert proof.samples == 0


def test_return_is_requested_only_after_good_pipeline_and_cleanup_always_runs(monkeypatch):
    import tools.ac_harness.auto_drive as ad
    import tools.ac_harness.pit_return as pr

    async def geometry(*args):
        return PitBox.from_native(native(), "car", "track", "")

    monkeypatch.setattr(pr, "read_pit_box", geometry)

    class Controller:
        closed = False

        def write_controls(self, gas, brake, steer):
            assert gas == 0 and brake > 0

        def close(self):
            self.closed = True

    config = AutoDriveConfig(
        natural_pit_return=True,
        wait_lap=True,
        target_laps=1,
        driver="ggv",
        spawn_to_line=False,
        max_recoveries=0,
        sim_death_retries=0,
        setup_verify_retries=0,
        lap_finalize_grace_s=0,
        skip_launch=True,
    )
    monkeypatch.setattr(
        ad,
        "evaluate_sequence",
        lambda *a, **k: type(
            "Result",
            (),
            {
                "ok": True,
                "counts": {"lap": 1},
                "checks": [],
                "notes": [],
            },
        )(),
    )

    async def tap(*args, **kwargs):
        return [
            {"v": 1, "type": "state.snapshot", "topic": "lap", "payload": {"last_lap_ms": 90000}}
        ]

    def drive(controller, cfg, stop):
        assert isinstance(stop, PitReturnStop)
        assert stop.return_requested.wait(2) and not stop.is_set()
        assert cfg.drive_seconds > config.drive_seconds + 250
        return DriveStats(drove=True, pit_return_status="arrived_pending_identity")

    controller = Controller()
    report = asyncio.run(
        run_auto_drive(
            config, launch=lambda _: (True, ""), hijack=lambda _: controller, drive=drive, tap=tap
        )
    )
    assert report.ok and controller.closed

    async def broken_tap(*args, **kwargs):
        raise ValueError("observer disconnected")

    def aborted(controller, cfg, stop):
        assert stop.wait(2) and not stop.return_requested.is_set()
        return DriveStats(drove=True, pit_return_status="failed")

    controller = Controller()
    report = asyncio.run(
        run_auto_drive(
            config,
            launch=lambda _: (True, ""),
            hijack=lambda _: controller,
            drive=aborted,
            tap=broken_tap,
        )
    )
    assert not report.ok and controller.closed
    assert drive_veto_reason(DriveStats(drove=True, pit_return_status="failed"))


@pytest.mark.parametrize(
    "failure", [OSError("socket lost"), RuntimeError("connection closed"), "identity"]
)
def test_arrival_connection_failure_is_retained_and_controller_released(monkeypatch, failure):
    import tools.ac_harness.auto_drive as ad
    import tools.ac_harness.pit_return as pr

    calls = 0

    async def geometry(*args):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        if calls == 2:
            if failure == "identity":
                return replace(PitBox.from_native(native(), "car", "track", ""), session_id="other")
            raise failure
        return PitBox.from_native(native(), "car", "track", "")

    monkeypatch.setattr(pr, "read_pit_box", geometry)
    monkeypatch.setattr(
        ad,
        "evaluate_sequence",
        lambda *a, **k: type("Result", (), {"ok": True, "counts": {}, "checks": [], "notes": []})(),
    )

    class Controller:
        closed = False

        def write_controls(self, gas, brake, steer):
            assert gas == 0 and brake > 0

        def close(self):
            self.closed = True

    config = AutoDriveConfig(
        natural_pit_return=True,
        wait_lap=True,
        target_laps=1,
        driver="ggv",
        spawn_to_line=False,
        max_recoveries=0,
        sim_death_retries=0,
        setup_verify_retries=0,
        lap_finalize_grace_s=0,
        skip_launch=True,
    )

    async def tap(*args, **kwargs):
        return [
            {"v": 1, "type": "state.snapshot", "topic": "lap", "payload": {"last_lap_ms": 90000}}
        ]

    def drive(controller, cfg, stop):
        assert stop.pit_box is not None and stop.return_requested.wait(2)
        return DriveStats(drove=True, pit_return_status="arrived_pending_identity")

    controller = Controller()
    report = asyncio.run(
        run_auto_drive(
            config, launch=lambda _: (True, ""), hijack=lambda _: controller, drive=drive, tap=tap
        )
    )
    assert not report.ok and controller.closed and calls == 2
    assert report.drive.pit_return_status == "failed"
    assert str(failure) in report.drive.reason


def test_geometry_reader_uses_a_distinct_non_control_identity(monkeypatch):
    import tools.ai_sidecar.harness_client as hc
    from tools.ac_harness.pit_return import read_pit_box
    from tools.ai_sidecar.external_protocol import SESSION_START_CLIENT_ID

    class Client:
        def __init__(self, url, *, token, client_id):
            assert client_id != SESSION_START_CLIENT_ID

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def hello(self):
            return True

        async def send(self, frame):
            assert frame == {"v": 1, "type": "config.get", "key": "harnessPitBox"}

        async def wait_for(self, predicate, *, timeout):  # noqa: ASYNC109 - client protocol
            await asyncio.sleep(0)
            reply = {"type": "config.value", "key": "harnessPitBox", "value": native()}
            assert predicate(reply)
            return reply

    monkeypatch.setattr(hc, "HarnessClient", Client)
    assert asyncio.run(read_pit_box("ws://fixture", "car", "track", "")).session_id == "native1"


def test_actual_lua_geometry_is_read_only_and_offline():
    lupa = pytest.importorskip("lupa")
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    module = (
        Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules/session_control.lua"
    )
    rt.execute("""
      calls=0; online=false
      ac={getSim=function() return {isOnlineRace=online} end,
          getCar=function() return {pitTransform={position={x=1,y=2,z=3},
                                                    look={x=0,y=0,z=1}}} end,
          getCarID=function() return 'car' end, getTrackID=function() return 'track' end,
          getTrackLayout=function() return '' end,
          tryToTeleportToPits=function() calls=calls+1; error('no writes') end}
    """)
    control = rt.execute(module.read_text()).new()
    assert control.pitBox("sid")["session_id"] == "sid"
    assert control.pitBox("sid")["position"][1] == 1
    rt.execute("online=true")
    assert control.pitBox("sid") is None and rt.globals().calls == 0


def test_early_driver_failure_cancels_the_lap_observer():
    async def run():
        cancelled = asyncio.Event()

        async def observer():
            try:
                await asyncio.sleep(20)
            finally:
                cancelled.set()

        async def driver():
            await asyncio.sleep(0.01)
            raise ValueError("native pit geometry unavailable")

        task = asyncio.create_task(driver())
        with pytest.raises(ValueError, match="geometry unavailable"):
            await observe_until_drive_ends(observer(), task)
        assert cancelled.is_set()

    asyncio.run(run())


def test_geometric_stop_without_native_arrival_is_bounded():
    driver = PitReturnDriver([(float(i), 0.0, 0.0) for i in range(101)], started_at=0)
    driver.index = 99
    driver.step((99.5, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 4000.0, 2, 0.0)
    with pytest.raises(ValueError, match="not confirmed"):
        driver.step((99.5, 0.0, 0.0), (1.0, 0.0, 0.0), 0.0, 4000.0, 2, 6.0)
