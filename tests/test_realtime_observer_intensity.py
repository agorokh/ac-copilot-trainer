"""Tests for the issue #368 intensity-expressive observer behavior.

Covers: the severity→register quantization (with hysteresis), register escalation on the brake cue
(calm anticipatory heads-up vs critical alarm), anticipatory firing (onset before the mark), the new
``brake_release`` cue, and that ``throttle`` now flows through ``_normalize_frame``.
"""

from __future__ import annotations

from tools.ai_sidecar.realtime_observer import RealtimeObserver, _normalize_frame, _register_for
from tools.ai_sidecar.track_reference import CornerReference


def _ref(**kw) -> CornerReference:
    base = dict(
        index=0,
        apex_spline=0.50,
        spline_lo=0.42,
        spline_hi=0.60,
        optimal_apex_kmh=100.0,
        best_observed_apex_kmh=100.0,
        best_brake_point_spline=0.45,
        n_corpus=1,
    )
    base.update(kw)
    return CornerReference(**base)


# --- register quantization (pure) -----------------------------------------------------------------


def test_register_for_thresholds_monotonic() -> None:
    assert _register_for(0.0, "calm") == "calm"
    assert _register_for(0.4, "calm") == "firm"
    assert _register_for(0.9, "calm") == "critical"


def test_register_for_has_hysteresis() -> None:
    # Same severity, different incoming tier → different result (no frame-to-frame flicker).
    s = 0.62  # between firm-rise (0.34) and crit-rise (0.67), above crit-fall (0.58)
    assert _register_for(s, "calm") == "firm"  # rising from calm has not crossed crit-rise yet
    assert _register_for(s, "critical") == "critical"  # falling from critical holds above crit-fall


def test_register_for_cap_clamps() -> None:
    assert _register_for(0.99, "calm", cap="firm") == "firm"
    assert _register_for(0.99, "calm", cap="calm") == "calm"


# --- brake cue register escalation (the headline) -------------------------------------------------


def test_brake_cue_calm_when_on_pace_anticipatory() -> None:
    # Arriving on pace (low closing speed), in the anticipatory lead window BEFORE the brake point.
    ref = _ref(optimal_apex_kmh=150.0, best_observed_apex_kmh=150.0)
    obs = RealtimeObserver([ref], lap_length_m=2500.0)
    # speed 152 km/h ≈ target+2 → tiny closing; lead ≈ (152/3.6)*0.8/2500 ≈ 0.0135 spline.
    out = obs.observe({"spline": 0.443, "speed": 152.0, "brake": 0.0, "throttle": 0.0})
    brake = [a for a in out if a.kind == "late_brake"]
    assert brake, "expected an anticipatory brake cue in the lead window"
    a = brake[0]
    assert a.register == "calm"
    assert a.urgency == "prepare"  # calm rides the anticipatory prepare urgency
    assert a.detail["anticipatory"] is True
    assert a.spline == ref.best_brake_point_spline  # advisory anchors to the control point
    assert a.detail["lead_s"] > 0.0  # emitted before the mark (issue #368 AC a)


def test_brake_cue_critical_when_arriving_far_too_hot() -> None:
    # Deep past the brake point, still coasting, carrying far more than the apex target → alarm.
    ref = _ref(optimal_apex_kmh=100.0, best_observed_apex_kmh=100.0)
    obs = RealtimeObserver([ref], lap_length_m=2500.0)
    out = obs.observe({"spline": 0.49, "speed": 180.0, "brake": 0.0, "throttle": 0.0})
    brake = [a for a in out if a.kind == "late_brake"]
    assert brake
    a = brake[0]
    assert a.register == "critical"
    assert a.urgency == "act"
    assert a.intensity > 0.66


def test_brake_cue_escalates_calm_to_critical_across_frames() -> None:
    # codex review #371: a calm anticipatory lead-in must NOT lock out the later critical alarm.
    ref = _ref(optimal_apex_kmh=120.0, best_observed_apex_kmh=120.0)
    obs = RealtimeObserver([ref], lap_length_m=2500.0)
    cues = []
    # frame 1: on pace in the lead window → calm/prepare heads-up
    cues += [
        a
        for a in obs.observe({"spline": 0.443, "speed": 122.0, "brake": 0.0, "throttle": 0.0})
        if a.kind == "late_brake"
    ]
    # frame 2: arriving far too hot, still coasting past the point → critical alarm (escalation)
    cues += [
        a
        for a in obs.observe({"spline": 0.49, "speed": 190.0, "brake": 0.0, "throttle": 0.0})
        if a.kind == "late_brake"
    ]
    regs = [c.register for c in cues]
    assert "calm" in regs and "critical" in regs  # both lead-in AND the escalated alarm fired
    rank = {"calm": 0, "firm": 1, "critical": 2}
    assert [rank[r] for r in regs] == sorted(rank[r] for r in regs)  # strictly escalating


def test_brake_cue_suppressed_once_braking() -> None:
    ref = _ref()
    obs = RealtimeObserver([ref])
    # in-window braking sets has_braked; a later coast past the point must NOT draw a brake cue
    obs.observe({"spline": 0.43, "speed": 110.0, "brake": 0.6, "throttle": 0.0})
    out = obs.observe({"spline": 0.49, "speed": 95.0, "brake": 0.0, "throttle": 0.0})
    assert [a for a in out if a.kind == "late_brake"] == []


# --- brake_release ------------------------------------------------------------------------------


def test_brake_release_fires_when_over_braking_past_apex_off_throttle() -> None:
    ref = _ref()
    obs = RealtimeObserver([ref])
    out = obs.observe({"spline": 0.55, "speed": 80.0, "brake": 0.7, "throttle": 0.0})
    rel = [a for a in out if a.kind == "brake_release"]
    assert rel and rel[0].register in ("calm", "firm")
    assert rel[0].register != "critical"  # a correction, never an alarm (capped at firm)


def test_brake_release_suppressed_when_on_throttle() -> None:
    # Already transitioning to power past the apex → a normal trail-brake release, not a fault.
    ref = _ref()
    obs = RealtimeObserver([ref])
    out = obs.observe({"spline": 0.55, "speed": 80.0, "brake": 0.7, "throttle": 0.5})
    assert [a for a in out if a.kind == "brake_release"] == []


def test_brake_release_fires_without_a_brake_point() -> None:
    # codex review #371: a GGV-only reference (no corpus brake point) must still emit the
    # over-braking release cue — it needs only the apex/window + brake/throttle, not a brake point.
    ref = _ref(best_brake_point_spline=None)
    obs = RealtimeObserver([ref])
    out = obs.observe({"spline": 0.55, "speed": 80.0, "brake": 0.7, "throttle": 0.0})
    assert [a for a in out if a.kind == "brake_release"]


# --- throttle now flows through normalization -----------------------------------------------------


def test_normalize_frame_extracts_throttle_from_live_payload() -> None:
    spline, speed, brake, throttle, lap = _normalize_frame(
        {"payload": {"spline": 0.5, "speed_kmh": 120.0, "brake": 0.2, "throttle": 0.8}}
    )
    assert (spline, speed, brake, throttle) == (0.5, 120.0, 0.2, 0.8)
