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
    assert _register_for(0.4, "calm") == "alert"
    assert _register_for(0.62, "calm") == "urgent"
    assert _register_for(0.9, "calm") == "critical"


def test_register_for_has_hysteresis() -> None:
    # Same severity, different incoming tier → different result (no frame-to-frame flicker).
    s = 0.76  # below critical-rise, above critical-fall
    assert _register_for(s, "urgent") == "urgent"  # rising has not crossed crit-rise yet
    assert _register_for(s, "critical") == "critical"  # falling holds above crit-fall


def test_register_for_cap_clamps() -> None:
    assert _register_for(0.99, "calm", cap="urgent") == "urgent"
    assert _register_for(0.99, "calm", cap="firm") == "urgent"  # legacy alias
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


def test_past_point_hot_coast_is_silent_and_flagged() -> None:
    # #522: deep past the brake point a spoken imperative is after-the-fact noise — the
    # observer stays SILENT (no live "Brake!" alarm exists) and flags the pass so
    # corner-exit grading owns the feedback.
    ref = _ref(optimal_apex_kmh=100.0, best_observed_apex_kmh=100.0)
    obs = RealtimeObserver([ref], lap_length_m=2500.0)
    out = obs.observe({"spline": 0.49, "speed": 180.0, "brake": 0.0, "throttle": 0.0})
    assert [a for a in out if a.kind == "late_brake"] == []
    assert obs._passes[ref.index].late_uncoached is True


def test_calm_prepare_is_the_only_live_cue_across_frames() -> None:
    # #522 (supersedes the #371 escalation ladder): the calm anticipatory heads-up is the
    # ONLY live brake cue. Arriving hot past the point speaks nothing — the miss is owned
    # by exit grading, never by a live alarm that would always land after the fact.
    ref = _ref(optimal_apex_kmh=120.0, best_observed_apex_kmh=120.0)
    obs = RealtimeObserver([ref], lap_length_m=2500.0)
    first = [
        a
        for a in obs.observe({"spline": 0.443, "speed": 122.0, "brake": 0.0, "throttle": 0.0})
        if a.kind == "late_brake"
    ]
    assert [(a.urgency, a.register) for a in first] == [("prepare", "calm")]
    second = [
        a
        for a in obs.observe({"spline": 0.49, "speed": 190.0, "brake": 0.0, "throttle": 0.0})
        if a.kind == "late_brake"
    ]
    assert second == []
    assert obs._passes[ref.index].late_uncoached is True


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
    assert rel and rel[0].register in ("calm", "alert", "urgent")
    assert rel[0].register != "critical"  # a correction, never an alarm (capped at urgent)


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


def test_braking_in_lead_window_suppresses_false_late_brake() -> None:
    # codex review #371: braking during the anticipatory lead (before the brake point) counts as
    # braking this pass — a later release-and-coast must NOT draw a false late-brake alarm.
    ref = _ref()
    obs = RealtimeObserver([ref])
    obs.observe({"spline": 0.44, "speed": 150.0, "brake": 0.6, "throttle": 0.0})  # braked in lead
    out = obs.observe(
        {"spline": 0.49, "speed": 120.0, "brake": 0.0, "throttle": 0.0}
    )  # release+coast
    assert [a for a in out if a.kind == "late_brake"] == []


def test_lead_window_wraps_over_start_finish() -> None:
    # codex review #371: a first corner with bp≈0 — the lead window wraps past start/finish; a frame
    # at spline≈0.995 (within the lead before bp) must still fire the anticipatory cue (not a lap).
    ref = _ref(
        apex_spline=0.05,
        spline_lo=0.0,
        spline_hi=0.10,
        best_brake_point_spline=0.01,
    )
    obs = RealtimeObserver([ref], track_length_m=2500.0)
    out = obs.observe({"spline": 0.995, "speed": 180.0, "brake": 0.0, "throttle": 0.0})
    brake = [a for a in out if a.kind == "late_brake"]
    assert brake and brake[0].detail["anticipatory"] is True


def test_wrapped_first_corner_lead_resets_previous_lap_cue_state() -> None:
    # A T1 brake point near 0.0 starts its next-lap lead before the spline wrap is observed. The
    # previous lap's emitted brake cue must not suppress that new anticipatory lead.
    ref = _ref(
        apex_spline=0.05,
        spline_lo=0.0,
        spline_hi=0.10,
        best_brake_point_spline=0.01,
    )
    obs = RealtimeObserver([ref], track_length_m=2500.0)
    # inside the (wrapped) lead window, BEFORE the bp — the #522 heads-up fires here
    first = obs.observe({"spline": 0.005, "speed": 180.0, "brake": 0.0, "throttle": 0.0})
    assert [a for a in first if a.kind == "late_brake"]

    wrapped_lead = obs.observe({"spline": 0.995, "speed": 180.0, "brake": 0.0, "throttle": 0.0})
    brake = [a for a in wrapped_lead if a.kind == "late_brake"]
    assert brake
    assert brake[0].detail["anticipatory"] is True
    assert brake[0].urgency == "prepare"


# --- throttle now flows through normalization -----------------------------------------------------


def test_normalize_frame_extracts_throttle_from_live_payload() -> None:
    spline, speed, brake, throttle, lap = _normalize_frame(
        {"payload": {"spline": 0.5, "speed_kmh": 120.0, "brake": 0.2, "throttle": 0.8}}
    )
    assert (spline, speed, brake, throttle) == (0.5, 120.0, 0.2, 0.8)
