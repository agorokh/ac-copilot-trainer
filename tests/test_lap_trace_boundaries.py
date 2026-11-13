"""Exercise native counter-lag sampling with the actual Lua recorder/reset guard."""

from __future__ import annotations

import pytest

pytest.importorskip("lupa")

from tools.ac_harness.trace_replay import TraceReplayHarness  # noqa: E402


@pytest.mark.parametrize("lag_frames", [1, 2, 15, 29])
def test_pending_finish_wrap_does_not_enter_completed_lap(lag_frames):
    h = TraceReplayHarness()
    telemetry, delta = h.require("telemetry"), h.require("delta")
    recorder = telemetry.new(h.lua.table())
    recorder.beginLapClock(recorder, 0)

    def sample(now, spline, record_lap=True):
        car = h.make_car(speedKmh=100, splinePosition=spline)
        sim = h.make_sim(isInMainMenu=False, gameTime=now)
        h.call_guarding_schema(recorder.update, recorder, 0.016, car, sim, record_lap)

    sample(0, 0.001)
    sample(119.98, 0.999)
    pending, frames, previous_spline = None, 0, 0.999
    for frame in range(lag_frames):
        spline = 0.0001 + frame * 0.0001
        decision = delta.rollingResetDecision(
            h.lua.table_from(
                dict(
                    pendingWrapLapCount=pending,
                    pendingWrapFrames=frames,
                    lastLapCount=1,
                    lapCount=1,
                    prevSpline=previous_spline,
                    spline=spline,
                )
            )
        )
        assert decision.reset is False
        pending, frames = decision.pendingWrapLapCount, decision.pendingWrapFrames
        sample(120 + frame * 0.016, spline, pending is None)
        previous_spline = spline

    # Live telemetry continues, but none of the ambiguous next-lap frames may
    # contaminate the completed trace or replace its original sensor values.
    assert recorder.sampleCount(recorder) == lag_frames + 1  # 0s evicted by rolling window
    trace = recorder.finalizeLapTrace(recorder)
    assert len(trace) == 2
    assert trace[2].spline == pytest.approx(0.999)
    assert trace[2].eMs == pytest.approx(119_980)

    decision = delta.rollingResetDecision(
        h.lua.table_from(
            dict(
                pendingWrapLapCount=pending,
                pendingWrapFrames=frames,
                lastLapCount=1,
                lapCount=2,
                prevSpline=previous_spline,
                spline=0.004,
            )
        )
    )
    assert decision.reset is False
    assert decision.pendingWrapLapCount is None
    now = 120 + lag_frames * 0.016
    recorder.beginLapClock(recorder, now)
    sample(now, 0.004, decision.pendingWrapLapCount is None)
    sample(now + 0.016, 0.0042)
    next_trace = recorder.finalizeLapTrace(recorder)
    assert len(next_trace) == 2
    assert next_trace[1].eMs == 0
    assert next_trace[2].eMs == pytest.approx(16)


def test_trace_sampling_pause_preserves_clock_and_default_callers():
    h = TraceReplayHarness()
    recorder = h.require("telemetry").new(h.lua.table())
    recorder.beginLapClock(recorder, 10)
    car = h.make_car(speedKmh=100, splinePosition=0.2)
    for now, record_lap in [(10, None), (11, False), (12, None)]:
        sim = h.make_sim(isInMainMenu=False, gameTime=now)
        h.call_guarding_schema(recorder.update, recorder, 1, car, sim, record_lap)
    assert recorder.sampleCount(recorder) == 3
    trace = recorder.finalizeLapTrace(recorder)
    assert [row.eMs for row in trace.values()] == [0, 2000]


@pytest.mark.parametrize("transition", ["timeout", "teleport", "rollback"])
def test_unconfirmed_wrap_still_discards_abandoned_trace(transition):
    h = TraceReplayHarness()
    decision = h.require("delta").rollingResetDecision(
        h.lua.table_from(
            dict(
                pendingWrapLapCount=1,
                pendingWrapFrames=29 if transition == "timeout" else 1,
                lastLapCount=1,
                lapCount=0 if transition == "rollback" else 1,
                prevSpline=0.001,
                spline=0.002,
                teleported=transition == "teleport",
            )
        )
    )
    assert decision.reset is True
    assert decision.pendingWrapLapCount is None
