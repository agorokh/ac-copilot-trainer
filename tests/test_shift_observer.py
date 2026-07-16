"""#531 Part E: live upshift/downshift cues from the telemetry tick."""

from __future__ import annotations

from tools.ai_sidecar.shift_observer import (
    DEFAULT_SHIFT_ZONE_FRAC,
    DOWNSHIFT_COOLDOWN_S,
    DOWNSHIFT_SUSTAIN_S,
    UPSHIFT_COOLDOWN_S,
    ShiftObserver,
)


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _tick(**payload):
    base = {
        "speed_kmh": 140.0,
        "rpm": 5000.0,
        "throttle": 0.9,
        "brake": 0.0,
        "gear": 3,
        "rpm_max": 9000.0,
        "spline": 0.4,
    }
    base.update(payload)
    return {"type": "telemetry_tick", "payload": base}


def _observer() -> tuple[ShiftObserver, _Clock]:
    clock = _Clock()
    return ShiftObserver(clock=clock), clock


def test_upshift_fires_once_per_gear_engagement_from_learned_target() -> None:
    obs, clock = _observer()

    assert obs.observe(_tick(rpm=7000, shift_rpm=7400, shift_rpm_source="learned")) == []
    out = obs.observe(_tick(rpm=7450, shift_rpm=7400, shift_rpm_source="learned"))
    assert [a.kind for a in out] == ["upshift"]
    assert out[0].register == "calm"
    assert out[0].detail["shift_rpm"] == 7400
    assert out[0].detail["shift_rpm_source"] == "learned"

    # Still over the target in the same gear: no repeat.
    clock.t += UPSHIFT_COOLDOWN_S + 1
    assert obs.observe(_tick(rpm=7500, shift_rpm=7400)) == []

    # Gear change re-arms; next gear's target reached fires again.
    clock.t += UPSHIFT_COOLDOWN_S + 1
    assert obs.observe(_tick(gear=4, rpm=6000, shift_rpm=7400)) == []
    out = obs.observe(_tick(gear=4, rpm=7500, shift_rpm=7400))
    assert [a.kind for a in out] == ["upshift"]


def test_upshift_falls_back_to_limiter_heuristic_without_shift_rpm() -> None:
    obs, _clock = _observer()
    threshold = 9000.0 * DEFAULT_SHIFT_ZONE_FRAC

    assert obs.observe(_tick(rpm=threshold - 100)) == []
    out = obs.observe(_tick(rpm=threshold + 50))
    assert [a.kind for a in out] == ["upshift"]
    assert out[0].detail["shift_rpm_source"] == "heuristic"


def test_upshift_needs_throttle_and_no_braking() -> None:
    obs, _clock = _observer()
    assert obs.observe(_tick(rpm=8900, throttle=0.2)) == []
    assert obs.observe(_tick(rpm=8900, brake=0.6)) == []


def test_upshift_cooldown_spans_gear_bounce() -> None:
    obs, clock = _observer()
    out = obs.observe(_tick(rpm=8500))
    assert [a.kind for a in out] == ["upshift"]
    # Immediate bounce to another gear and back over target: cooldown suppresses.
    clock.t += 0.2
    assert obs.observe(_tick(gear=4, rpm=8500)) == []


def test_no_cue_without_rpm_max_or_learned_target() -> None:
    obs, _clock = _observer()
    frame = _tick(rpm=8900)
    del frame["payload"]["rpm_max"]
    assert obs.observe(frame) == []


def test_neutral_and_missing_channels_are_silent() -> None:
    obs, _clock = _observer()
    assert obs.observe(_tick(gear=0, rpm=8900)) == []
    frame = _tick()
    del frame["payload"]["rpm"]
    assert obs.observe(frame) == []


def test_downshift_bog_requires_sustain_and_cooldown() -> None:
    obs, clock = _observer()
    bog = dict(rpm=2500.0, gear=4, throttle=0.9, speed_kmh=90.0)  # target 8280, 40% = 3312

    assert obs.observe(_tick(**bog)) == []  # bog starts, not sustained yet
    clock.t += DOWNSHIFT_SUSTAIN_S + 0.1
    out = obs.observe(_tick(**bog))
    assert [a.kind for a in out] == ["downshift"]
    assert out[0].detail["classification"] == "bog_heuristic"

    # Sustained bog again inside the cooldown: silent.
    clock.t += DOWNSHIFT_SUSTAIN_S + 0.1
    assert obs.observe(_tick(**bog)) == []

    # Break the streak (throttle lifted), wait out the cooldown, then a fresh sustained
    # bog cues again.
    assert obs.observe(_tick(rpm=2500.0, gear=4, throttle=0.1, speed_kmh=90.0)) == []
    clock.t += DOWNSHIFT_COOLDOWN_S + 1
    assert obs.observe(_tick(**bog)) == []  # streak restarts, not yet sustained
    clock.t += DOWNSHIFT_SUSTAIN_S + 0.1
    out = obs.observe(_tick(**bog))
    assert [a.kind for a in out] == ["downshift"]


def test_downshift_not_cued_at_low_speed_or_low_gear() -> None:
    obs, clock = _observer()
    for frame in (
        _tick(rpm=2500, gear=4, speed_kmh=10.0),  # pulling away
        _tick(rpm=2500, gear=1, speed_kmh=90.0),  # first gear never bogs
    ):
        obs.observe(frame)
        clock.t += DOWNSHIFT_SUSTAIN_S + 0.5
        assert obs.observe(frame) == []
        obs.reset()
        clock.t += 1


def test_reset_clears_armed_state() -> None:
    obs, clock = _observer()
    out = obs.observe(_tick(rpm=8500))
    assert [a.kind for a in out] == ["upshift"]
    obs.reset()
    clock.t += UPSHIFT_COOLDOWN_S + 1
    out = obs.observe(_tick(rpm=8500))
    assert [a.kind for a in out] == ["upshift"]
