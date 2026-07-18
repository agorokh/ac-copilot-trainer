"""Off-rig tests for the resilient launcher's verdict logic (#624 / #619).

The launcher's value is entirely in *how it decides* an attempt succeeded: the delayed CSP init
livelock lands ~48-90 s AFTER go-live, so a gate that declares success on a few early live reads
(as ``entry_launcher`` does) reports a wedged session as good. These tests pin the sustained-window
semantics against synthetic traces — no Assetto Corsa, no Windows shared memory.
"""

from __future__ import annotations

import pytest

from tools.ac_harness.resilient_launch import (
    LaunchVerdict,
    Sample,
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


def test_acs_exit_after_go_live_is_froze_not_stable():
    samples = steady(0.0, 10.0, first_packet=100)
    samples += trace([(11.0, None, False)])
    assert classify(samples, go_live_timeout=30.0, stability_window=45.0) is LaunchVerdict.FROZE


def test_empty_trace_is_never_live():
    assert classify([]) is LaunchVerdict.NEVER_LIVE


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


@pytest.mark.parametrize("stall_samples", [2, 3, 5])
def test_stall_threshold_is_honored(stall_samples: int):
    samples = steady(0.0, 10.0, first_packet=100)
    held = samples[-1].gfx_packet
    samples += trace([(11.0 + i, held, True) for i in range(stall_samples)])
    verdict = classify(
        samples, go_live_timeout=30.0, stability_window=120.0, stall_samples=stall_samples
    )
    assert verdict is LaunchVerdict.FROZE
