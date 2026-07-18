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
    _ensure_acs_gone,
    _ensure_cm_running,
    _non_negative_float,
    _positive_float,
    _positive_int,
    _wait_process_exit,
    _watch_live,
    classify,
    run_retry_loop,
)


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
    _ensure_acs_gone(lambda: next(alive))
    assert calls == [["taskkill", "/im", "acs.exe", "/f", "/t"]]


def test_ensure_cm_running_fails_fast_when_executable_is_missing(tmp_path):
    assert _ensure_cm_running(tmp_path / "missing.exe") is False
