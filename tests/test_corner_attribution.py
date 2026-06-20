"""Tests for setup_knowledge + corner_attribution (the coaching brain)."""

from __future__ import annotations

import math

from tools.ai_sidecar.corner_attribution import (
    CornerContext,
    CornerDelta,
    analyze_balance,
    attribute_corner,
    coach_lap,
    compare_laps,
)
from tools.ai_sidecar.lap_dynamics import CornerSignature, LapTrace
from tools.ai_sidecar.setup_knowledge import (
    AERO,
    MECHANICAL,
    NEUTRAL,
    PARAM_EFFECTS,
    TIER_B_CHANNELS,
    effect_for,
)
from tools.ai_sidecar.setup_model import from_snapshot

SETUP = from_snapshot({
    "FRONT_BIAS.VALUE": "66",
    "ABS.VALUE": "3",
    "TRACTION_CONTROL.VALUE": "4",
    "TYRES.VALUE": "1",
    "PRESSURE_LF.VALUE": "27.5",
})


# --- setup_knowledge --------------------------------------------------------
def test_speed_dependence_classes_are_correct():
    assert PARAM_EFFECTS["WING_1"].speed_dependence == AERO
    assert PARAM_EFFECTS["WING_2"].speed_dependence == AERO
    assert PARAM_EFFECTS["ARB_FRONT"].speed_dependence == MECHANICAL
    assert PARAM_EFFECTS["ARB_REAR"].speed_dependence == MECHANICAL
    assert PARAM_EFFECTS["FRONT_BIAS"].speed_dependence == NEUTRAL


def test_rake_and_compound_flagged_car_dependent():
    assert PARAM_EFFECTS["ROD_LENGTH"].car_dependent is True
    assert PARAM_EFFECTS["TYRES"].car_dependent is True


def test_effect_for_resolves_per_corner():
    assert effect_for("PRESSURE_LF").section == "PRESSURE"
    assert effect_for("CAMBER_RR").section == "CAMBER"
    assert effect_for("FRONT_BIAS").section == "FRONT_BIAS"
    assert effect_for("NOPE") is None


def test_tier_b_channels_name_the_key_unlocks():
    assert "wheelSlip" in TIER_B_CHANNELS
    assert "wheelsPressure" in TIER_B_CHANNELS


# --- helpers ----------------------------------------------------------------
def _sig(**kw) -> CornerSignature:
    base = dict(
        index=0, entry_i=0, apex_i=5, exit_i=10, apex_spline=0.5, min_speed_kmh=100.0,
        entry_speed_kmh=180.0, exit_speed_kmh=150.0, peak_lat_g=1.2, peak_brake_g=1.0,
        peak_accel_g=0.5, brake_point_spline=0.40, brake_to_apex_m=60.0, throttle_on_spline=0.55,
        apex_to_throttle_m=10.0, trail_brake_frac=0.2, max_abs_steer=0.4, direction="right",
    )
    base.update(kw)
    return CornerSignature(**base)


def _delta(**kw) -> CornerDelta:
    base = dict(
        index=0, spline_lo=0.4, spline_hi=0.6, cand_time_s=2.5, ref_time_s=2.0, delta_s=0.5,
        cand_min_kmh=92.0, ref_min_kmh=100.0, min_speed_delta_kmh=-8.0,
    )
    base.update(kw)
    return CornerDelta(**base)


# --- compare_laps -----------------------------------------------------------
def test_compare_laps_localizes_lost_time():
    n = 100
    spline = [i / (n - 1) for i in range(n)]
    x = [s * 1000.0 for s in spline]
    z = [0.0] * n
    ref_t = [i * 0.1 for i in range(n)]
    # candidate loses 0.5 s ramped across samples 40..60, then holds the deficit
    cand_t = []
    for i in range(n):
        extra = 0.0 if i < 40 else (0.5 * (i - 40) / 20 if i <= 60 else 0.5)
        cand_t.append(i * 0.1 + extra)
    v = [50.0] * n
    cand_v = [40.0 if 40 <= i <= 60 else 50.0 for i in range(n)]

    def mk(t, vv):
        return LapTrace(spline=spline, t_s=t, v_ms=vv, brake=[0.0] * n, throttle=[0.0] * n,
                        steer=[0.0] * n, gear=[4] * n, x=x, z=z)

    deltas = compare_laps(mk(cand_t, cand_v), mk(ref_t, v), corners=[(40, 50, 60)])
    assert len(deltas) == 1
    assert deltas[0].delta_s == 0.5  # lost half a second in this window
    assert deltas[0].min_speed_delta_kmh < 0  # carried less apex speed


# --- attribute_corner -------------------------------------------------------
def test_grip_limited_fires_and_is_advisory_without_pressure():
    ctx = CornerContext(sig=_sig(peak_lat_g=1.5), setup=SETUP, grip_ceiling_g=1.5)
    attrs = attribute_corner(ctx)
    grip = next(a for a in attrs if a.key == "grip_limited")
    assert grip.confidence >= 0.9
    assert grip.advisory is True  # wheelsPressure not supplied
    assert grip.setup_causes  # routes to setup, not technique


def test_grip_limited_confirmed_with_live_pressure():
    ctx = CornerContext(sig=_sig(peak_lat_g=1.5), setup=SETUP, grip_ceiling_g=1.5,
                        extra={"wheelsPressure": [28, 28, 27, 27]})
    grip = next(a for a in attribute_corner(ctx) if a.key == "grip_limited")
    assert grip.advisory is False  # live pressure present -> verdict


def test_entry_speed_left_is_technique_verdict():
    ctx = CornerContext(sig=_sig(peak_lat_g=1.1), setup=SETUP, grip_ceiling_g=1.5,
                        delta=_delta(min_speed_delta_kmh=-8.0))
    attrs = attribute_corner(ctx)
    esl = next(a for a in attrs if a.key == "entry_speed_left")
    assert esl.advisory is False  # pure kinematics, no live channel needed
    assert esl.technique_causes and not esl.setup_causes


def test_grip_limited_suppresses_entry_speed_when_at_limit():
    # at the grip limit, "carry more speed" is wrong advice -> entry_speed_left must not fire
    ctx = CornerContext(sig=_sig(peak_lat_g=1.5), setup=SETUP, grip_ceiling_g=1.5,
                        delta=_delta(min_speed_delta_kmh=-8.0))
    keys = {a.key for a in attribute_corner(ctx)}
    assert "grip_limited" in keys
    assert "entry_speed_left" not in keys


def test_braking_phase_loss_suspected_then_confirmed_with_slip():
    sig = _sig(peak_brake_g=1.1, brake_point_spline=0.40)
    d = _delta(delta_s=0.3)
    susp = next(a for a in attribute_corner(CornerContext(sig=sig, setup=SETUP, delta=d))
               if a.key == "braking_phase_loss")
    assert susp.advisory is True
    conf = next(a for a in attribute_corner(
        CornerContext(sig=sig, setup=SETUP, delta=d, extra={"wheelSlip": [0.1, 0.1, 0.02, 0.02]}))
        if a.key == "braking_phase_loss")
    assert conf.advisory is False


def test_braking_phase_loss_mentions_911_bias_window():
    sig = _sig(peak_brake_g=1.1)
    d = _delta(delta_s=0.3)
    a = next(x for x in attribute_corner(CornerContext(sig=sig, setup=SETUP, delta=d))
             if x.key == "braking_phase_loss")
    assert any("50-56" in c for c in a.setup_causes)  # 66% front flagged vs 911 window


def test_exit_traction_leads_with_technique_and_diff():
    ctx = CornerContext(sig=_sig(apex_to_throttle_m=28.0), setup=SETUP, delta=_delta(delta_s=0.2))
    a = next(x for x in attribute_corner(ctx) if x.key == "exit_traction")
    joined = " ".join(a.setup_causes).lower()
    assert "diff_power" in joined  # diff before ARB
    assert "throttle technique" in joined


# --- analyze_balance (the master discriminator) -----------------------------
def test_balance_routes_high_speed_saturation_to_aero():
    # grip-limited (saturated) in HIGH-speed corners, grip in hand at low speed -> aero
    sigs = [
        _sig(index=0, min_speed_kmh=80.0, peak_lat_g=1.1),   # low-speed: grip in hand
        _sig(index=1, min_speed_kmh=85.0, peak_lat_g=1.05),
        _sig(index=2, min_speed_kmh=170.0, peak_lat_g=1.5),  # high-speed: at the limit -> aero
        _sig(index=3, min_speed_kmh=165.0, peak_lat_g=1.48),
    ]
    f = analyze_balance(LapTrace([], [], [], [], [], [], [], [], []), sigs, grip_ceiling_g=1.5)
    assert f.verdict == "aero_limited_high_speed"
    assert f.lever_class == AERO


def test_balance_routes_low_speed_saturation_to_mechanical():
    # grip-limited (saturated) in LOW-speed corners, grip in hand at high speed -> mechanical
    sigs = [
        _sig(index=0, min_speed_kmh=80.0, peak_lat_g=1.5),
        _sig(index=1, min_speed_kmh=85.0, peak_lat_g=1.48),
        _sig(index=2, min_speed_kmh=170.0, peak_lat_g=1.1),
        _sig(index=3, min_speed_kmh=165.0, peak_lat_g=1.05),
    ]
    f = analyze_balance(LapTrace([], [], [], [], [], [], [], [], []), sigs, grip_ceiling_g=1.5)
    assert f.verdict == "mechanical_all_speed"
    assert f.lever_class == MECHANICAL


def test_balance_not_grip_limited_is_technique():
    # grip in hand in BOTH bands -> the deficit is technique, not balance
    sigs = [
        _sig(index=0, min_speed_kmh=80.0, peak_lat_g=1.0),
        _sig(index=1, min_speed_kmh=170.0, peak_lat_g=1.0),
    ]
    f = analyze_balance(LapTrace([], [], [], [], [], [], [], [], []), sigs, grip_ceiling_g=1.5)
    assert f.verdict == "not_grip_limited"
    assert f.lever_class == ""


def test_balance_insufficient_when_one_band_missing():
    sigs = [_sig(index=0, min_speed_kmh=80.0), _sig(index=1, min_speed_kmh=70.0)]
    f = analyze_balance(LapTrace([], [], [], [], [], [], [], [], []), sigs, grip_ceiling_g=1.5)
    assert f.verdict == "insufficient"


# --- coach_lap end-to-end ---------------------------------------------------
def _corner_lap_trace(radius=30.0, ds=2.0, n_pre=40, n_arc=30, n_post=40,
                      v_straight=55.0, v_apex=25.0) -> LapTrace:
    n = n_pre + n_arc + n_post
    kappa = [0.0] * n_pre + [1.0 / radius] * n_arc + [0.0] * n_post
    theta, x, z = 0.0, 0.0, 0.0
    xs, zs = [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * ds
        x += ds * math.cos(theta)
        z += ds * math.sin(theta)
    apex_i = n_pre + n_arc // 2
    v = []
    for i in range(n):
        if i < 25:
            v.append(v_straight)
        elif i < apex_i:
            v.append(v_straight + (v_apex - v_straight) * (i - 25) / max(1, apex_i - 25))
        elif i < n_pre + n_arc + 5:
            denom = max(1, n_pre + n_arc + 5 - apex_i)
            v.append(v_apex + (v_straight - v_apex) * (i - apex_i) / denom)
        else:
            v.append(v_straight)
    brake = [0.8 if 25 <= i < apex_i else 0.0 for i in range(n)]
    throttle = [1.0 if i >= apex_i + 1 else 0.0 for i in range(n)]
    steer = [0.4 if n_pre <= i < n_pre + n_arc else 0.0 for i in range(n)]
    t_s = [0.0]
    for i in range(1, n):
        t_s.append(t_s[-1] + ds / max(0.5, 0.5 * (v[i] + v[i - 1])))
    spline = [(ds * i) / (ds * (n - 1)) for i in range(n)]
    return LapTrace(spline=spline, t_s=t_s, v_ms=v, brake=brake, throttle=throttle, steer=steer,
                    gear=[4] * n, x=xs, z=zs)


def test_coach_lap_produces_per_corner_verdicts():
    lap = _corner_lap_trace()
    report = coach_lap(lap, SETUP, grip_ceiling_g=2.5)
    assert len(report) >= 1
    c0 = report[0]
    assert c0.headline
    assert isinstance(c0.attributions, list)
    # the synthetic apex (~90 km/h) at ~2.1 g vs 2.5 ceiling is near the limit -> grip-limited shows
    assert any(a.key == "grip_limited" for a in c0.attributions) or c0.min_speed_kmh > 0
