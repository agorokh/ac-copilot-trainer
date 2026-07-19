"""Off-rig tests for the resilient launcher's verdict logic (#624 / #619).

The launcher's value is entirely in *how it decides* an attempt succeeded: the delayed CSP init
livelock lands ~48-90 s AFTER go-live, so a gate that declares success on a few early live reads
(as ``entry_launcher`` does) reports a wedged session as good. These tests pin the sustained-window
semantics against synthetic traces — no Assetto Corsa, no Windows shared memory.
"""

from __future__ import annotations

import argparse

import pytest

from tools.ac_harness.resilient_launch import (
    LaunchVerdict,
    Sample,
    _Car0ProbeCleanupError,
    _ensure_acs_gone,
    _ensure_cm_running,
    _hold_rig_until_acs_gone,
    _hold_stable_session,
    _make_process_liveness_probe,
    _make_rig_safe,
    _non_negative_float,
    _OperatorRelease,
    _positive_float,
    _positive_int,
    _probe_car0_drivable,
    _run_with_safe_release,
    _sample_now,
    _wait_process_exit,
    _watch_live,
    classify,
    run_retry_loop,
)
from tools.ac_harness.shared_memory import SharedMemoryUnavailable


def trace(points: list[tuple[float, int | None, bool]]) -> list[Sample]:
    return [Sample(t=t, gfx_packet=p, acs_alive=a) for t, p, a in points]


def steady(start_t: float, end_t: float, *, first_packet: int, step: float = 1.0) -> list[Sample]:
    """A healthy render trace: packetId advances every sample."""
    out: list[Sample] = []
    packet = first_packet
    t = start_t
    while t <= end_t:
        out.append(Sample(t=t, gfx_packet=packet, acs_alive=True))
        packet += 60
        t += step
    return out


def test_never_live_when_sim_never_renders():
    """acs never maps shared memory / never advances a frame within the go-live budget."""
    samples = trace([(float(t), None, False) for t in range(0, 40, 2)])
    assert classify(samples, go_live_timeout=30.0) is LaunchVerdict.NEVER_LIVE


def test_never_live_when_process_up_but_render_never_starts():
    """acs is alive but the packet never advances — a stuck launch, not a live session."""
    samples = trace([(float(t), 7, True) for t in range(0, 40, 2)])
    assert classify(samples, go_live_timeout=30.0) is LaunchVerdict.NEVER_LIVE


def test_process_exit_after_first_appearing_fails_before_go_live_timeout():
    samples = [
        Sample(t=0.0, gfx_packet=None, acs_alive=False),
        Sample(t=1.0, gfx_packet=100, acs_alive=True, entry_ready=False),
        Sample(t=2.0, gfx_packet=None, acs_alive=False),
    ]

    assert classify(samples, go_live_timeout=80.0) is LaunchVerdict.NEVER_LIVE


def test_stable_when_render_advances_through_the_window():
    samples = steady(0.0, 60.0, first_packet=100)
    assert classify(samples, go_live_timeout=30.0, stability_window=45.0) is LaunchVerdict.STABLE


def test_delayed_init_freeze_is_caught_not_reported_stable():
    """THE regression this launcher exists for: live first, then wedges mid-window.

    ``entry_launcher``-style logic (success after a few early live reads) would call this a good
    session. The sustained window must call it FROZE.
    """
    samples = steady(0.0, 20.0, first_packet=100)
    frozen_at = samples[-1].gfx_packet
    samples += trace([(float(t), frozen_at, True) for t in range(21, 40)])
    assert classify(samples, go_live_timeout=30.0, stability_window=60.0) is LaunchVerdict.FROZE


def test_short_stall_then_recovery_is_not_a_freeze():
    """A brief hitch (fewer than stall_samples) must not fail an otherwise healthy session."""
    samples = steady(0.0, 10.0, first_packet=100)
    held = samples[-1].gfx_packet
    samples += trace([(11.0, held, True), (12.0, held, True)])  # 2 stalled samples < 4
    samples += steady(13.0, 60.0, first_packet=held + 60)
    verdict = classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
    assert verdict is LaunchVerdict.STABLE


def test_unknown_graphics_sample_breaks_the_consecutive_stall_run():
    samples = steady(0.0, 10.0, first_packet=100)
    held = samples[-1].gfx_packet
    samples += trace([(11.0, held, True), (12.0, held, True)])
    samples.append(Sample(t=13.0, gfx_packet=None, acs_alive=True, entry_ready=None))
    samples += trace([(14.0, held, True), (15.0, held, True)])
    samples += steady(16.0, 60.0, first_packet=held + 60)

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.STABLE
    )


def test_single_not_ready_flicker_does_not_abort_stability_window():
    samples = steady(0.0, 10.0, first_packet=100)
    samples.append(Sample(t=11.0, gfx_packet=800, acs_alive=True, entry_ready=False))
    samples += steady(12.0, 60.0, first_packet=860)

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.STABLE
    )


def test_unknown_readiness_breaks_the_consecutive_not_ready_run():
    samples = steady(0.0, 10.0, first_packet=100)
    samples += [
        Sample(t=11.0, gfx_packet=800, acs_alive=True, entry_ready=False),
        Sample(t=12.0, gfx_packet=801, acs_alive=True, entry_ready=False),
        Sample(t=13.0, gfx_packet=802, acs_alive=True, entry_ready=None),
        Sample(t=14.0, gfx_packet=803, acs_alive=True, entry_ready=False),
        Sample(t=15.0, gfx_packet=804, acs_alive=True, entry_ready=False),
    ]
    samples += steady(16.0, 60.0, first_packet=860)

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.STABLE
    )


def test_sustained_not_ready_state_fails_the_attempt():
    samples = steady(0.0, 10.0, first_packet=100)
    samples += [
        Sample(t=11.0 + index, gfx_packet=800 + index, acs_alive=True, entry_ready=False)
        for index in range(4)
    ]

    assert (
        classify(samples, go_live_timeout=30.0, stability_window=45.0, stall_samples=4)
        is LaunchVerdict.FROZE
    )


def test_unfinished_live_trace_is_pending_not_a_terminal_failure():
    samples = steady(0.0, 20.0, first_packet=100)
    assert classify(samples, go_live_timeout=10.0, stability_window=60.0) is LaunchVerdict.PENDING


def test_advancing_pre_drive_menu_is_not_accepted_as_stable():
    samples = [
        Sample(t=float(t), gfx_packet=100 + t, acs_alive=True, entry_ready=False)
        for t in range(0, 61)
    ]
    assert (
        classify(samples, go_live_timeout=30.0, stability_window=20.0) is LaunchVerdict.NEVER_LIVE
    )


def test_live_not_in_pit_overlay_without_car0_is_not_accepted_as_stable():
    samples = [
        Sample(
            t=float(t),
            gfx_packet=100 + t,
            acs_alive=True,
            entry_ready=True,
            drivable=False,
        )
        for t in range(0, 61)
    ]
    assert (
        classify(samples, go_live_timeout=30.0, stability_window=20.0) is LaunchVerdict.NEVER_LIVE
    )


def test_first_ready_frame_at_go_live_deadline_is_too_late():
    samples = [
        Sample(t=0.0, gfx_packet=100, acs_alive=True, entry_ready=False),
        Sample(t=5.0, gfx_packet=101, acs_alive=True, entry_ready=True),
    ]
    assert classify(samples, go_live_timeout=5.0, stability_window=20.0) is LaunchVerdict.NEVER_LIVE


def test_acs_exit_after_go_live_is_froze_not_stable():
    samples = steady(0.0, 10.0, first_packet=100)
    samples += trace([(11.0, None, False)])
    assert classify(samples, go_live_timeout=30.0, stability_window=45.0) is LaunchVerdict.FROZE


def test_empty_trace_is_pending():
    assert classify([]) is LaunchVerdict.PENDING


def test_stability_window_is_measured_from_go_live_not_from_launch():
    """A slow-loading session still gets its full stability window."""
    late = trace([(float(t), None, False) for t in range(0, 25, 5)])  # 25 s of loading
    late += steady(25.0, 65.0, first_packet=500)  # live at 25 s, 40 s of steady render
    assert classify(late, go_live_timeout=40.0, stability_window=35.0) is LaunchVerdict.STABLE
    # ...but a 60 s window is not satisfied by only 40 s of post-go-live render
    assert classify(late, go_live_timeout=40.0, stability_window=60.0) is not LaunchVerdict.STABLE


class TestRetryLoop:
    def test_stops_on_first_stable_and_counts_attempts(self):
        verdicts = [LaunchVerdict.FROZE, LaunchVerdict.FROZE, LaunchVerdict.STABLE]
        report = run_retry_loop(lambda i: verdicts[i - 1], max_attempts=10)
        assert report.succeeded
        assert (report.attempts, report.froze, report.never_live) == (3, 2, 0)

    def test_exhausts_budget_and_reports_failure_honestly(self):
        report = run_retry_loop(lambda i: LaunchVerdict.FROZE, max_attempts=4)
        assert not report.succeeded
        assert report.attempts == 4 and report.froze == 4
        assert report.verdict is LaunchVerdict.FROZE
        assert "reboot" in report.summary()

    def test_cold_restarts_cm_after_consecutive_never_live(self):
        """Repeated never_live means a stale CM ignoring the preset URL (#537/#558) — restart it."""
        calls: list[int] = []
        run_retry_loop(
            lambda i: LaunchVerdict.NEVER_LIVE,
            max_attempts=4,
            on_never_live_streak=lambda: calls.append(1),
            never_live_before_restart=2,
        )
        assert len(calls) == 2  # fires on attempts 2 and 4, streak resets between

    def test_freeze_breaks_the_never_live_streak(self):
        """A FROZE verdict proves CM is not stale, so it must reset the restart counter."""
        seq = [LaunchVerdict.NEVER_LIVE, LaunchVerdict.FROZE, LaunchVerdict.NEVER_LIVE]
        calls: list[int] = []
        run_retry_loop(
            lambda i: seq[i - 1],
            max_attempts=3,
            on_never_live_streak=lambda: calls.append(1),
            never_live_before_restart=2,
        )
        assert calls == []

    def test_rejects_pending_attempt_result(self):
        with pytest.raises(ValueError, match="non-terminal"):
            run_retry_loop(lambda _: LaunchVerdict.PENDING, max_attempts=1)


@pytest.mark.parametrize("stall_samples", [2, 3, 5])
def test_stall_threshold_is_honored(stall_samples: int):
    samples = steady(0.0, 10.0, first_packet=100)
    held = samples[-1].gfx_packet
    samples += trace([(11.0 + i, held, True) for i in range(stall_samples)])
    verdict = classify(
        samples, go_live_timeout=30.0, stability_window=120.0, stall_samples=stall_samples
    )
    assert verdict is LaunchVerdict.FROZE


def test_streaming_watch_survives_go_live_timeout_until_stability(monkeypatch):
    now = 0.0
    packet = 100

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    def read_state() -> tuple[int, bool]:
        nonlocal packet
        packet += 1
        return packet, True

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    assert (
        _watch_live(
            read_state,
            lambda: True,
            go_live_timeout=2.0,
            stability_window=5.0,
            poll_interval=1.0,
        )
        is LaunchVerdict.STABLE
    )


def test_sample_timestamp_follows_blocking_readiness_work(monkeypatch):
    now = 10.0
    observations: list[tuple[str, float]] = []

    def monotonic() -> float:
        return now

    def acs_alive() -> bool:
        observations.append(("alive", now))
        return True

    def read_state() -> tuple[int, bool, bool]:
        nonlocal now
        observations.append(("state", now))
        now += 5.0
        return 101, True, True

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)

    sample = _sample_now(read_state, acs_alive)

    assert sample.t == 15.0
    assert sample.acs_alive is True
    assert observations == [("state", 10.0), ("alive", 15.0)]
    assert now == 15.0


def test_blocking_readiness_probe_consumes_go_live_budget() -> None:
    samples = [
        Sample(t=15.0, gfx_packet=1, acs_alive=True, entry_ready=True, drivable=True),
        Sample(t=16.0, gfx_packet=2, acs_alive=True, entry_ready=True, drivable=True),
    ]

    assert (
        classify(
            samples,
            go_live_timeout=4.0,
            stability_window=20.0,
            started_at=10.0,
        )
        is LaunchVerdict.NEVER_LIVE
    )


def test_process_liveness_probe_fails_closed_and_confirms_absence() -> None:
    observations = iter(
        [
            OSError("snapshot failed"),
            (),
            (),
            (42,),
            (),
            (),
        ]
    )

    def process_ids(_image: str) -> tuple[int, ...]:
        observation = next(observations)
        if isinstance(observation, OSError):
            raise observation
        return observation

    alive = _make_process_liveness_probe("acs.exe", process_ids=process_ids)

    assert [alive() for _ in range(6)] == [True, True, False, True, True, False]


def test_process_liveness_probe_rejects_invalid_confirmation_count() -> None:
    with pytest.raises(ValueError, match="absent_confirmations"):
        _make_process_liveness_probe("acs.exe", absent_confirmations=0)


def test_streaming_watch_waits_through_short_hitch(monkeypatch):
    now = 0.0
    packets = iter([100, 101, 102, 102, 102, 103, 104, 105, 106, 107])

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    assert (
        _watch_live(
            lambda: (next(packets), True),
            lambda: True,
            go_live_timeout=2.0,
            stability_window=5.0,
            poll_interval=1.0,
        )
        is LaunchVerdict.STABLE
    )


def test_wait_process_exit_rejects_lingering_killed_process(monkeypatch):
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    monkeypatch.setattr("tools.ac_harness.resilient_launch._process_running", lambda _image: True)

    assert _wait_process_exit("Content Manager.exe", timeout=1.0, poll=0.25) is False
    assert now == 1.0


def test_wait_process_exit_clamps_sleep_to_deadline(monkeypatch):
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)
    monkeypatch.setattr("tools.ac_harness.resilient_launch._process_running", lambda _image: True)

    assert _wait_process_exit("Content Manager.exe", timeout=1.0, poll=0.6) is False
    assert now == 1.0


def test_wait_process_exit_honors_release_before_process_probe(monkeypatch):
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._process_running",
        lambda _image: pytest.fail("release must be checked before the process probe"),
    )

    with pytest.raises(_OperatorRelease):
        _wait_process_exit("Content Manager.exe", release_requested=lambda: True)


@pytest.mark.parametrize(
    ("parser", "value", "message"),
    [
        (_positive_float, "0", "finite and > 0"),
        (_positive_float, "-1", "finite and > 0"),
        (_positive_int, "0", "must be > 0"),
        (_positive_int, "-2", "must be > 0"),
    ],
)
def test_positive_cli_types_reject_non_positive(parser, value, message):
    with pytest.raises(argparse.ArgumentTypeError, match=message):
        parser(value)


def test_rig_lock_timeout_cli_type_rejects_negative():
    with pytest.raises(argparse.ArgumentTypeError, match="finite and >= 0"):
        _non_negative_float("-0.1")


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_float_cli_types_reject_non_finite(value):
    with pytest.raises(argparse.ArgumentTypeError, match="finite"):
        _positive_float(value)
    with pytest.raises(argparse.ArgumentTypeError, match="finite"):
        _non_negative_float(value)


def test_ensure_acs_gone_kills_the_full_process_tree(monkeypatch):
    calls: list[list[str]] = []
    alive = iter([True, False])

    monkeypatch.setattr(
        "subprocess.run",
        lambda command, **_kwargs: calls.append(command),
    )
    assert _ensure_acs_gone(lambda: next(alive)) is True
    assert calls == [["taskkill", "/im", "acs.exe", "/f", "/t"]]


def test_ensure_acs_gone_returns_false_when_process_survives(monkeypatch):
    now = 0.0

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert _ensure_acs_gone(lambda: True, timeout=1.0, poll=0.25) is False
    assert now == 1.0


def test_cleanup_failure_holds_ownership_until_acs_is_gone(monkeypatch):
    cleanup_results = iter([False, False, True])
    alive_results = iter([True, True, True, False])
    cleanup_calls: list[int] = []
    sleeps: list[float] = []

    def retry_cleanup(_acs_alive):
        cleanup_calls.append(1)
        return next(cleanup_results)

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    _hold_rig_until_acs_gone(
        lambda: next(alive_results),
        retry_cleanup=retry_cleanup,
        poll=0.25,
    )

    assert len(cleanup_calls) == 3
    assert sleeps == [0.25, 0.25]


def test_cleanup_hold_rechecks_liveness_after_reported_success(monkeypatch):
    alive_results = iter([True, True, True, False])
    cleanup_calls: list[int] = []
    sleeps: list[float] = []

    def retry_cleanup(_acs_alive) -> bool:
        cleanup_calls.append(1)
        return True

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    _hold_rig_until_acs_gone(
        lambda: next(alive_results),
        retry_cleanup=retry_cleanup,
        poll=0.25,
    )

    assert len(cleanup_calls) == 2
    assert sleeps == [0.25]


def test_cleanup_hold_allows_only_explicit_operator_release(monkeypatch):
    def interrupt(_acs_alive):
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep",
        lambda _seconds: pytest.fail("interrupt must release before sleeping"),
    )

    _hold_rig_until_acs_gone(lambda: True, retry_cleanup=interrupt)


def test_cleanup_hold_honors_game_point_release_signal() -> None:
    _hold_rig_until_acs_gone(
        lambda: True,
        retry_cleanup=lambda _acs_alive: pytest.fail("release must precede another cleanup"),
        release_requested=lambda: True,
    )


def test_cleanup_hold_forwards_release_to_default_cleanup(monkeypatch) -> None:
    callbacks: list[object] = []

    def release_requested() -> bool:
        return False

    def cleanup(_acs_alive, *, release_requested=None):
        callbacks.append(release_requested)
        raise _OperatorRelease

    monkeypatch.setattr("tools.ac_harness.resilient_launch._ensure_acs_gone", cleanup)

    _hold_rig_until_acs_gone(
        lambda: True,
        release_requested=release_requested,
    )

    assert callbacks == [release_requested]


def test_stable_session_exit_without_release_is_failure() -> None:
    assert _hold_stable_session(lambda: False, lambda: False) is False


def test_stable_session_release_is_success() -> None:
    assert _hold_stable_session(lambda: True, lambda: True) is True


def test_abnormal_retry_exit_makes_rig_safe_before_propagating(monkeypatch):
    calls: list[str] = []

    def fail() -> object:
        calls.append("run")
        raise RuntimeError("watch failed")

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._make_rig_safe",
        lambda _acs_alive, **_kwargs: calls.append("safe"),
    )

    with pytest.raises(RuntimeError, match="watch failed"):
        _run_with_safe_release(fail, lambda: True)

    assert calls == ["run", "safe"]


def test_pre_stable_operator_release_makes_rig_safe_before_propagating(monkeypatch):
    calls: list[tuple[str, dict[str, object]]] = []

    def release_requested() -> bool:
        return True

    def release() -> object:
        calls.append(("run", {}))
        raise _OperatorRelease

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._make_rig_safe",
        lambda _acs_alive, **kwargs: calls.append(("safe", kwargs)),
    )

    with pytest.raises(_OperatorRelease):
        _run_with_safe_release(release, lambda: True, release_requested=release_requested)

    # Cleanup is attempted first; the durable signal remains Game Point's no-console escape hatch.
    assert calls == [
        ("run", {}),
        ("safe", {"release_requested": release_requested}),
    ]


def test_make_rig_safe_attempts_cleanup_before_honoring_release(monkeypatch):
    callbacks: list[object] = []
    held_with: list[object] = []

    def release_requested() -> bool:
        return True

    def cleanup(_acs_alive, *, release_requested=None):
        callbacks.append(release_requested)
        return False

    monkeypatch.setattr("tools.ac_harness.resilient_launch._ensure_acs_gone", cleanup)
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._hold_rig_until_acs_gone",
        lambda _acs_alive, *, release_requested=None: held_with.append(release_requested),
    )

    _make_rig_safe(lambda: True, release_requested=release_requested)

    assert callbacks == [None]
    assert held_with == [release_requested]


def test_car0_probe_closes_controller_after_handshake(monkeypatch):
    reads = iter([None] * 12 + [{"packet_id": 1}])
    closed: list[bool] = []
    now = 0.0

    class Controller:
        def read_car_data(self):
            return next(reads)

        def close(self):
            closed.append(True)

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.monotonic", monotonic)
    monkeypatch.setattr("tools.ac_harness.resilient_launch.time.sleep", sleep)

    assert (
        _probe_car0_drivable(
            poll=0.1,
            controller_factory=Controller,
        )
        is True
    )
    assert closed == [True]
    assert now > 1.0


def test_car0_probe_mapping_failure_is_retryable() -> None:
    def fail_controller() -> object:
        raise SharedMemoryUnavailable("mapping unavailable")

    assert _probe_car0_drivable(controller_factory=fail_controller) is False


def test_car0_probe_honors_release_during_handshake(monkeypatch) -> None:
    release_checks = iter([False, False, True])
    closed: list[bool] = []

    class Controller:
        def read_car_data(self):
            return None

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch.time.sleep",
        lambda _seconds: pytest.fail("release must interrupt before another probe sleep"),
    )

    with pytest.raises(_OperatorRelease):
        _probe_car0_drivable(
            controller_factory=Controller,
            release_requested=lambda: next(release_checks),
        )

    assert closed == [True]


def test_car0_failure_verdict_does_not_restart_content_manager() -> None:
    restarts: list[bool] = []

    report = run_retry_loop(
        lambda _attempt: LaunchVerdict.FROZE,
        max_attempts=2,
        on_never_live_streak=lambda: restarts.append(True),
        never_live_before_restart=2,
    )

    assert report.verdict is LaunchVerdict.FROZE
    assert restarts == []


def test_car0_probe_close_failure_aborts_before_another_probe() -> None:
    class Controller:
        def read_car_data(self):
            return {"packet_id": 1}

        def close(self):
            raise OSError("unmap failed")

    with pytest.raises(_Car0ProbeCleanupError, match="could not close"):
        _probe_car0_drivable(controller_factory=Controller)


def test_ensure_cm_running_fails_before_same_named_process_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._process_running",
        lambda _image: pytest.fail("a running image cannot validate a missing configured path"),
    )

    assert _ensure_cm_running(tmp_path / "missing.exe") is False


def test_ensure_cm_running_probes_the_configured_image_name(tmp_path, monkeypatch):
    images: list[str] = []
    cm_exe = tmp_path / "PortableCM.exe"
    cm_exe.touch()

    def running(image: str) -> bool:
        images.append(image)
        return True

    monkeypatch.setattr("tools.ac_harness.resilient_launch._process_running", running)

    assert _ensure_cm_running(cm_exe) is True
    assert images == ["PortableCM.exe"]


def test_ensure_cm_running_honors_release_before_process_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.ac_harness.resilient_launch._process_running",
        lambda _image: pytest.fail("release must be checked before probing or starting CM"),
    )

    with pytest.raises(_OperatorRelease):
        _ensure_cm_running(tmp_path / "Content Manager.exe", release_requested=lambda: True)


def test_ensure_acs_gone_honors_release_before_process_probe() -> None:
    with pytest.raises(_OperatorRelease):
        _ensure_acs_gone(
            lambda: pytest.fail("release must be checked before probing or killing acs.exe"),
            release_requested=lambda: True,
        )
