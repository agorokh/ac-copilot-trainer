"""Tests for setup_knowledge + corner_attribution (the coaching brain)."""

from __future__ import annotations

import math

import tools.ai_sidecar.corner_attribution as ca
from tools.ai_sidecar.corner_attribution import (
    WHEEL_RADIUS_M,
    CornerContext,
    CornerDelta,
    _corner_history_matches,
    _match_corner_signature,
    analyze_balance,
    analyze_corner_consistency,
    attribute_corner,
    coach_lap,
    compare_laps,
    corner_live_signals,
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

SETUP = from_snapshot(
    {
        "FRONT_BIAS.VALUE": "66",
        "ABS.VALUE": "3",
        "TRACTION_CONTROL.VALUE": "4",
        "TYRES.VALUE": "1",
        "PRESSURE_LF.VALUE": "27.5",
    }
)


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
        index=0,
        entry_i=0,
        apex_i=5,
        exit_i=10,
        apex_spline=0.5,
        min_speed_kmh=100.0,
        entry_speed_kmh=180.0,
        exit_speed_kmh=150.0,
        peak_lat_g=1.2,
        peak_brake_g=1.0,
        peak_accel_g=0.5,
        brake_point_spline=0.40,
        brake_to_apex_m=60.0,
        throttle_on_spline=0.55,
        apex_to_throttle_m=10.0,
        trail_brake_frac=0.2,
        max_abs_steer=0.4,
        direction="right",
    )
    base.update(kw)
    return CornerSignature(**base)


def _delta(**kw) -> CornerDelta:
    base = dict(
        index=0,
        spline_lo=0.4,
        spline_hi=0.6,
        cand_time_s=2.5,
        ref_time_s=2.0,
        delta_s=0.5,
        cand_min_kmh=92.0,
        ref_min_kmh=100.0,
        min_speed_delta_kmh=-8.0,
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
        return LapTrace(
            spline=spline,
            t_s=t,
            v_ms=vv,
            brake=[0.0] * n,
            throttle=[0.0] * n,
            steer=[0.0] * n,
            gear=[4] * n,
            x=x,
            z=z,
        )

    deltas = compare_laps(mk(cand_t, cand_v), mk(ref_t, v), corners=[(40, 50, 60)])
    assert len(deltas) == 1
    assert deltas[0].delta_s == 0.5  # lost half a second in this window
    assert deltas[0].min_speed_delta_kmh < 0  # carried less apex speed


def test_compare_laps_matches_reference_by_apex_spline(monkeypatch):
    n = 10
    spline = [i / (n - 1) for i in range(n)]
    reference = LapTrace(
        spline=spline,
        t_s=[float(i) for i in range(n)],
        v_ms=[40.0] * n,
        brake=[0.0] * n,
        throttle=[0.0] * n,
        steer=[0.0] * n,
        gear=[3] * n,
        x=[float(i) for i in range(n)],
        z=[0.0] * n,
    )
    cand_t = [float(i) for i in range(n)]
    cand_t[7] += 0.2
    cand_t[8] += 0.4
    candidate = LapTrace(
        spline=spline,
        t_s=cand_t,
        v_ms=[40.0] * n,
        brake=[0.0] * n,
        throttle=[0.0] * n,
        steer=[0.0] * n,
        gear=[4] * n,
        x=[float(i) for i in range(n)],
        z=[0.0] * n,
    )
    cand_sig = _sig(index=0, entry_i=4, apex_i=5, exit_i=6, apex_spline=spline[5])
    ref_sigs = [
        _sig(index=0, entry_i=1, apex_i=2, exit_i=3, apex_spline=spline[2]),
        _sig(index=1, entry_i=6, apex_i=7, exit_i=8, apex_spline=spline[5]),
    ]

    monkeypatch.setattr(
        ca,
        "corner_signatures",
        lambda lap_arg, _corners=None: [cand_sig] if lap_arg is candidate else ref_sigs,
    )

    deltas = compare_laps(candidate, reference)
    assert len(deltas) == 1
    assert deltas[0].index == 0
    assert deltas[0].spline_lo == round(spline[6], 4)
    assert deltas[0].delta_s == 0.4


# --- attribute_corner -------------------------------------------------------
def test_grip_limited_fires_and_is_advisory_without_pressure():
    ctx = CornerContext(sig=_sig(peak_lat_g=1.5), setup=SETUP, grip_ceiling_g=1.5)
    attrs = attribute_corner(ctx)
    grip = next(a for a in attrs if a.key == "grip_limited")
    assert grip.confidence >= 0.9
    assert grip.advisory is True  # wheelsPressure not supplied
    assert grip.setup_causes  # routes to setup, not technique


def test_grip_limited_confirmed_with_live_pressure():
    ctx = CornerContext(
        sig=_sig(peak_lat_g=1.5),
        setup=SETUP,
        grip_ceiling_g=1.5,
        extra={"wheelsPressure": [28, 28, 27, 27]},
    )
    grip = next(a for a in attribute_corner(ctx) if a.key == "grip_limited")
    assert grip.advisory is False  # live pressure present -> verdict


def test_turn_in_lag_advisory_without_yaw_then_verdict_with_live_yaw():
    # #478 AC2: turn_in_lag is advisory without yaw_rate and a verdict once the measured yaw-rate
    # channel is supplied.
    sig = _sig(max_abs_steer=0.5)  # high steer + no grip ceiling -> the rule fires
    advisory = next(
        a for a in attribute_corner(CornerContext(sig=sig, setup=SETUP)) if a.key == "turn_in_lag"
    )
    assert advisory.advisory is True  # yaw_rate not supplied
    confirmed = next(
        a
        for a in attribute_corner(CornerContext(sig=sig, setup=SETUP, extra={"yaw_rate": 0.3}))
        if a.key == "turn_in_lag"
    )
    assert confirmed.advisory is False  # live yaw-rate present -> verdict
    assert "0.3" in confirmed.coaching or "yaw-rate" in confirmed.coaching.lower()


def test_corner_live_signals_emits_chassis_and_pressure_markers():
    # #478: corner_live_signals derives the confirming yaw_rate + wheelsPressure markers (and accG)
    # from the persisted trace columns, so a lap carrying them graduates the turn_in_lag /
    # grip_limited rules to a verdict without a caller supplying extra by hand.
    n = 12
    lap = LapTrace(
        spline=[i / (n - 1) for i in range(n)],
        t_s=[i * 0.1 for i in range(n)],
        v_ms=[40.0] * n,
        brake=[0.0] * n,
        throttle=[0.0] * n,
        steer=[0.1] * n,
        gear=[3] * n,
        x=[float(i) for i in range(n)],
        z=[0.0] * n,
        yaw_rate=[0.30] * n,
        accg_lat=[1.2] * n,
        accg_long=[-0.4] * n,
        wheel_pressure=[[27.0, 27.1, 26.5, 26.6] for _ in range(n)],
    )
    assert lap.has_tier_b_data is True
    extra = corner_live_signals(lap, _sig(index=0, entry_i=2, apex_i=5, exit_i=9))
    assert extra["yaw_rate"] == 0.3
    assert extra["accG_lat"] == 1.2
    assert extra["accG_long"] == -0.4
    assert set(extra["wheelsPressure"]) == {"fl", "fr", "rl", "rr"}
    assert extra["wheelsPressure"]["fl"] == 27.0


def test_corner_live_signals_zero_yaw_through_turn_in_does_not_confirm():
    # cursor #483: a lap that carries yaw data but whose peak |yaw| through THIS corner's turn-in is
    # ~0 must NOT emit the yaw_rate marker (which would falsely confirm turn_in_lag at "0.0 rad/s").
    n = 12
    yaw = [0.0] * n
    yaw[n - 1] = 0.5  # rotation only well AFTER this corner's window
    lap = LapTrace(
        spline=[i / (n - 1) for i in range(n)],
        t_s=[i * 0.1 for i in range(n)],
        v_ms=[40.0] * n,
        brake=[0.0] * n,
        throttle=[0.0] * n,
        steer=[0.1] * n,
        gear=[3] * n,
        x=[float(i) for i in range(n)],
        z=[0.0] * n,
        yaw_rate=yaw,
    )
    # entry_i..apex_i covers only the zero region -> no rotation observed here -> no marker.
    extra = corner_live_signals(lap, _sig(index=0, entry_i=1, apex_i=4, exit_i=6))
    assert "yaw_rate" not in extra


def test_entry_speed_left_is_technique_verdict():
    ctx = CornerContext(
        sig=_sig(peak_lat_g=1.1),
        setup=SETUP,
        grip_ceiling_g=1.5,
        delta=_delta(min_speed_delta_kmh=-8.0),
    )
    attrs = attribute_corner(ctx)
    esl = next(a for a in attrs if a.key == "entry_speed_left")
    assert esl.advisory is False  # pure kinematics, no live channel needed
    assert esl.technique_causes and not esl.setup_causes


def test_grip_limited_suppresses_entry_speed_when_at_limit():
    # at the grip limit, "carry more speed" is wrong advice -> entry_speed_left must not fire
    ctx = CornerContext(
        sig=_sig(peak_lat_g=1.5),
        setup=SETUP,
        grip_ceiling_g=1.5,
        delta=_delta(min_speed_delta_kmh=-8.0),
    )
    keys = {a.key for a in attribute_corner(ctx)}
    assert "grip_limited" in keys
    assert "entry_speed_left" not in keys


def test_braking_phase_loss_suspected_then_confirmed_with_slip():
    sig = _sig(peak_brake_g=1.1, brake_point_spline=0.40)
    d = _delta(delta_s=0.3)
    susp = next(
        a
        for a in attribute_corner(CornerContext(sig=sig, setup=SETUP, delta=d))
        if a.key == "braking_phase_loss"
    )
    assert susp.advisory is True
    # supplying the confirming channel (+ a confirmed axle) flips advisory -> verdict
    conf = next(
        a
        for a in attribute_corner(
            CornerContext(
                sig=sig,
                setup=SETUP,
                delta=d,
                extra={"wheelAngularSpeed": True, "lock_axle": "front", "front_lock": -0.18},
            )
        )
        if a.key == "braking_phase_loss"
    )
    assert conf.advisory is False
    assert any("FRONT" in c for c in conf.setup_causes)  # names the confirmed axle


def test_braking_phase_loss_mentions_911_bias_window():
    sig = _sig(peak_brake_g=1.1)
    d = _delta(delta_s=0.3)
    a = next(
        x
        for x in attribute_corner(CornerContext(sig=sig, setup=SETUP, delta=d))
        if x.key == "braking_phase_loss"
    )
    assert any("50-56" in c for c in a.setup_causes)  # 66% front flagged vs 911 window


def test_exit_traction_leads_with_technique_and_diff():
    ctx = CornerContext(sig=_sig(apex_to_throttle_m=28.0), setup=SETUP, delta=_delta(delta_s=0.2))
    a = next(x for x in attribute_corner(ctx) if x.key == "exit_traction")
    joined = " ".join(a.setup_causes).lower()
    assert "diff_power" in joined  # diff before ARB
    assert "throttle technique" in joined


def test_steering_aggression_is_technique_verdict():
    ctx = CornerContext(
        sig=_sig(
            steering_correction_count=4,
            steering_smoothness_score=55.0,
            steering_scrub_index=0.24,
        ),
        setup=SETUP,
    )
    attr = next(a for a in attribute_corner(ctx) if a.key == "steering_aggression")
    assert attr.technique_causes and not attr.setup_causes
    assert "one input" in attr.coaching.lower()


def test_exit_road_usage_fires_from_reference_path_proxy():
    ctx = CornerContext(
        sig=_sig(),
        setup=SETUP,
        delta=_delta(delta_s=0.2),
        extra={"exit_road_usage": {"available": True, "missed_exit_width_m": 2.4}},
    )
    attr = next(a for a in attribute_corner(ctx) if a.key == "exit_road_usage")
    assert attr.confidence > 0.6
    assert "using the road" in attr.symptom


def test_gear_selection_compares_apex_gear_to_reference():
    ctx = CornerContext(
        sig=_sig(gear_at_apex=4),
        reference_sig=_sig(gear_at_apex=3),
        setup=SETUP,
        delta=_delta(delta_s=0.2),
    )
    attr = next(a for a in attribute_corner(ctx) if a.key == "gear_selection")
    assert attr.confidence > 0.5
    assert "Apex gear 4 vs reference 3" in attr.coaching


def test_gear_selection_ignores_stale_slower_reference():
    ctx = CornerContext(
        sig=_sig(gear_at_apex=4),
        reference_sig=_sig(gear_at_apex=3),
        setup=SETUP,
        delta=_delta(delta_s=-0.1),
    )
    assert not any(a.key == "gear_selection" for a in attribute_corner(ctx))


def test_brake_shape_attribution_names_pressure_rise():
    ctx = CornerContext(
        sig=_sig(brake_shape="increasing_pressure", brake_late_rise_count=3),
        setup=SETUP,
    )
    attr = next(a for a in attribute_corner(ctx) if a.key == "brake_trace_shape")
    assert attr.phase == "braking"
    assert "rises late" in attr.coaching


def test_corner_consistency_attribution_uses_history_score():
    ctx = CornerContext(
        sig=_sig(),
        setup=SETUP,
        extra={"consistency": {"available": True, "score": 61.0, "sample_count": 3}},
    )
    attr = next(a for a in attribute_corner(ctx) if a.key == "corner_consistency")
    assert attr.phase == "session"
    assert "repeatability" in attr.coaching


def test_reference_matching_uses_apex_spline_not_index():
    anchor = _sig(index=0, apex_spline=0.50)
    ref = [
        _sig(index=0, apex_spline=0.20, gear_at_apex=2),
        _sig(index=1, apex_spline=0.505, gear_at_apex=3),
    ]
    match = _match_corner_signature(anchor, ref)
    assert match is not None
    assert match.index == 1
    assert match.gear_at_apex == 3


def test_corner_history_matching_consumes_candidates_once(monkeypatch):
    anchors = [_sig(index=0, apex_spline=0.50), _sig(index=1, apex_spline=0.51)]
    candidate = _sig(index=9, apex_spline=0.505)
    monkeypatch.setattr(ca, "corner_signatures", lambda _lap: [candidate])
    matches = _corner_history_matches(
        [LapTrace([], [], [], [], [], [], [], [], [])],
        anchors,
    )
    matched_history_count = sum(len(sigs) - 1 for sigs in matches.values())
    assert matched_history_count == 1


def test_analyze_corner_consistency_reuses_precomputed_matches(monkeypatch):
    def fail_if_segmented(_lap):
        raise AssertionError("precomputed matches should not re-segment history")

    monkeypatch.setattr(ca, "corner_signatures", fail_if_segmented)
    matches = {
        0: [
            _sig(index=0, entry_speed_kmh=160.0, min_speed_kmh=95.0, exit_speed_kmh=140.0),
            _sig(index=7, entry_speed_kmh=150.0, min_speed_kmh=88.0, exit_speed_kmh=132.0),
        ]
    }
    consistency = analyze_corner_consistency(matches=matches)
    assert consistency[0].sample_count == 2
    assert consistency[0].score < 100.0


# --- analyze_balance (the master discriminator) -----------------------------
def test_balance_routes_high_speed_saturation_to_aero():
    # grip-limited (saturated) in HIGH-speed corners, grip in hand at low speed -> aero
    sigs = [
        _sig(index=0, min_speed_kmh=80.0, peak_lat_g=1.1),  # low-speed: grip in hand
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


# --- Tier-B confirmed attribution from per-wheel data -----------------------
def _wheel_lap(*, lock_axle: str | None, wheelspin: bool) -> tuple[LapTrace, CornerSignature]:
    """Construct a LapTrace with wheelAngularSpeed encoding a braking lock + an exit wheelspin."""
    r = WHEEL_RADIUS_M
    n = 20
    v_ms = [50.0] * 11 + [30.0] * 9  # decel into apex@10, slow exit
    brake = [0.0] * 5 + [0.8] * 6 + [0.0] * 9  # braking samples 5..10
    throttle = [0.0] * 12 + [1.0] * 8  # throttle samples 12..19

    def omega(slip: float, v: float) -> float:
        return v * (1.0 + slip) / r  # invert slip = (omega*r - v)/v

    wheel_omega = []
    for i in range(n):
        v = v_ms[i]
        fl = fr = rl = rr = v / r  # free-rolling default
        if brake[i] > 0.05 and lock_axle == "front":
            fl = fr = omega(-0.18, v)  # fronts locked
        elif brake[i] > 0.05 and lock_axle == "rear":
            rl = rr = omega(-0.18, v)  # rears locked
        if throttle[i] > 0.2 and wheelspin:
            rl = rr = omega(0.22, v)  # rears spinning
        wheel_omega.append([fl, fr, rl, rr])
    lap = LapTrace(
        spline=[i / (n - 1) for i in range(n)],
        t_s=[i * 0.1 for i in range(n)],
        v_ms=v_ms,
        brake=brake,
        throttle=throttle,
        steer=[0.3] * n,
        gear=[4] * n,
        x=[float(i) for i in range(n)],
        z=[0.0] * n,
        wheel_omega=wheel_omega,
    )
    sig = _sig(entry_i=4, apex_i=10, exit_i=19, apex_spline=0.5)
    return lap, sig


def test_corner_live_signals_detects_front_lock():
    lap, sig = _wheel_lap(lock_axle="front", wheelspin=False)
    s = corner_live_signals(lap, sig)
    assert s["wheelAngularSpeed"] is True
    assert s["lock_axle"] == "front"
    assert s["front_lock"] < -0.06
    assert s["wheelspin"] is False


def test_corner_live_signals_detects_rear_lock_and_wheelspin():
    lap, sig = _wheel_lap(lock_axle="rear", wheelspin=True)
    s = corner_live_signals(lap, sig)
    assert s["lock_axle"] == "rear"
    assert s["wheelspin"] is True
    assert s["rear_exit_slip"] > 0.1


def test_corner_live_signals_empty_without_wheel_data():
    lap, sig = _wheel_lap(lock_axle="front", wheelspin=False)
    lap.wheel_omega = None
    assert corner_live_signals(lap, sig) == {}


def test_corner_live_signals_ignores_unread_zero_wheel():
    # codex #274: one front wheel reads 0 (unread sentinel) while the car is NOT locking. The zero
    # must be excluded, not treated as slip=-1 (a false front lock).
    lap, sig = _wheel_lap(lock_axle=None, wheelspin=False)
    assert lap.wheel_omega is not None
    for k in range(sig.entry_i, sig.apex_i + 1):
        if lap.brake[k] > 0.05:
            lap.wheel_omega[k][0] = 0.0  # FL unread this frame
    s = corner_live_signals(lap, sig)
    assert s.get("lock_axle") is None  # the surviving FR (free-rolling) shows no lock


def test_live_signals_feed_confirmed_braking_attribution():
    # computed live signals + a braking-phase time loss -> CONFIRMED front-axle verdict
    lap, sig = _wheel_lap(lock_axle="front", wheelspin=False)
    extra = corner_live_signals(lap, sig)
    ctx = CornerContext(
        sig=_sig(peak_brake_g=1.1, brake_point_spline=0.4),
        setup=SETUP,
        delta=_delta(delta_s=0.3),
        extra=extra,
    )
    braking = next(a for a in attribute_corner(ctx) if a.key == "braking_phase_loss")
    assert braking.advisory is False  # confirmed, not suspected
    assert "rearward" in braking.coaching  # front lock -> move bias rearward
    assert any("FRONT" in c for c in braking.setup_causes)


def test_braking_stays_suspected_when_channel_present_but_no_braking_observed():
    # gemini #268: wheelAngularSpeed present but corner has NO braking -> lock_axle is never
    # computed, so the verdict must stay a SUSPICION, not falsely confirm.
    extra = {"wheelAngularSpeed": True}  # marker present, but no lock_axle key
    ctx = CornerContext(
        sig=_sig(peak_brake_g=1.1, brake_point_spline=0.4),
        setup=SETUP,
        delta=_delta(delta_s=0.3),
        extra=extra,
    )
    braking = next(a for a in attribute_corner(ctx) if a.key == "braking_phase_loss")
    assert braking.advisory is True  # not confirmed — no axle signal was computed


def test_live_signals_no_lock_routes_to_technique():
    # per-wheel data present but NO lock -> braking loss is technique, not bias
    lap, sig = _wheel_lap(lock_axle=None, wheelspin=False)
    extra = corner_live_signals(lap, sig)
    ctx = CornerContext(
        sig=_sig(peak_brake_g=1.1, brake_point_spline=0.4),
        setup=SETUP,
        delta=_delta(delta_s=0.3),
        extra=extra,
    )
    braking = next(a for a in attribute_corner(ctx) if a.key == "braking_phase_loss")
    assert braking.advisory is False
    assert any("NO axle lock" in c or "TECHNIQUE" in c for c in braking.setup_causes)


def test_balance_negative_grip_ceiling_is_ignored():
    # a nonsensical negative ceiling must not produce a negative grip fraction / misroute
    sigs = [_sig(index=0, min_speed_kmh=80.0), _sig(index=1, min_speed_kmh=170.0)]
    f = analyze_balance(LapTrace([], [], [], [], [], [], [], [], []), sigs, grip_ceiling_g=-1.0)
    assert f.low_band_grip_used is None and f.high_band_grip_used is None
    assert f.verdict in ("balanced", "insufficient")


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
def _corner_lap_trace(
    radius=30.0, ds=2.0, n_pre=40, n_arc=30, n_post=40, v_straight=55.0, v_apex=25.0
) -> LapTrace:
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
    return LapTrace(
        spline=spline,
        t_s=t_s,
        v_ms=v,
        brake=brake,
        throttle=throttle,
        steer=steer,
        gear=[4] * n,
        x=xs,
        z=zs,
    )


def test_coach_lap_produces_per_corner_verdicts():
    lap = _corner_lap_trace()
    report = coach_lap(lap, SETUP, grip_ceiling_g=2.5)
    assert len(report) >= 1
    c0 = report[0]
    assert c0.headline
    assert isinstance(c0.attributions, list)
    # the synthetic apex (~90 km/h) at ~2.1 g vs 2.5 ceiling is near the limit -> grip-limited shows
    assert any(a.key == "grip_limited" for a in c0.attributions) or c0.min_speed_kmh > 0


def test_coach_lap_exposes_diagnostics_with_reference_and_history():
    lap = _corner_lap_trace(v_apex=23.0)
    reference = _corner_lap_trace(v_apex=25.0)
    history = [_corner_lap_trace(v_apex=21.0)]
    report = coach_lap(lap, SETUP, reference=reference, history=history, grip_ceiling_g=2.5)
    diagnostics = report[0].diagnostics
    assert diagnostics["steering"]["available"] is True
    assert diagnostics["brake_shape"]["classification"]
    assert diagnostics["gear"]["available"] is True
    assert diagnostics["exit_road_usage"]["available"] is True
    assert diagnostics["consistency"]["available"] is True
    assert diagnostics["consistency"]["sample_count"] == 2


def test_coach_lap_preserves_caller_supplied_exit_width():
    lap = _corner_lap_trace()
    report = coach_lap(
        lap,
        SETUP,
        grip_ceiling_g=2.5,
        extra_by_corner={
            0: {
                "exit_road_usage": {
                    "available": True,
                    "source": "track_edge",
                    "under_used_exit_width_m": 2.0,
                }
            }
        },
    )
    diagnostics = report[0].diagnostics["exit_road_usage"]
    assert diagnostics["source"] == "track_edge"
    assert diagnostics["under_used_exit_width_m"] == 2.0
    assert any(a.key == "exit_road_usage" for a in report[0].attributions)


def test_coach_lap_uses_matched_reference_window_for_delta(monkeypatch):
    n = 10
    spline = [i / (n - 1) for i in range(n)]
    ref_t = [float(i) for i in range(n)]
    cand_t = [float(i) for i in range(n)]
    cand_t[7] += 0.2
    cand_t[8] += 0.4
    lap = LapTrace(
        spline=spline,
        t_s=cand_t,
        v_ms=[40.0] * n,
        brake=[0.0] * n,
        throttle=[0.0] * n,
        steer=[0.0] * n,
        gear=[4] * n,
        x=[float(i) for i in range(n)],
        z=[0.0] * n,
    )
    reference = LapTrace(
        spline=spline,
        t_s=ref_t,
        v_ms=[40.0] * n,
        brake=[0.0] * n,
        throttle=[0.0] * n,
        steer=[0.0] * n,
        gear=[3] * n,
        x=[float(i) for i in range(n)],
        z=[0.0] * n,
    )
    cand_sig = _sig(
        index=0,
        entry_i=4,
        apex_i=5,
        exit_i=6,
        apex_spline=spline[5],
        gear_at_apex=4,
    )
    ref_sigs = [
        _sig(index=0, entry_i=1, apex_i=2, exit_i=3, apex_spline=spline[2], gear_at_apex=4),
        _sig(index=1, entry_i=6, apex_i=7, exit_i=8, apex_spline=spline[5], gear_at_apex=3),
    ]

    monkeypatch.setattr(ca, "segment_corners", lambda _lap: [(4, 5, 6)])
    monkeypatch.setattr(
        ca,
        "corner_signatures",
        lambda lap_arg, _corners=None: [cand_sig] if lap_arg is lap else ref_sigs,
    )
    monkeypatch.setattr(ca, "analyze_trail_braking", lambda *_args, **_kw: [])

    report = coach_lap(lap, SETUP, reference=reference)
    assert report[0].delta_s == 0.4
    assert report[0].diagnostics["gear"]["reference_apex_gear"] == 3
    assert any(a.key == "gear_selection" for a in report[0].attributions)


# --- trail-braking folded into the attribution layer (#301) ------------------
def test_trail_brake_attribution_is_a_technique_verdict():
    # an injected trail-brake deficit becomes a TECHNIQUE attribution (no live channel needed)
    ctx = CornerContext(
        sig=_sig(),
        setup=SETUP,
        extra={
            "trail_brake": {"classification": "abrupt_release", "coaching": "bleed it off smoothly"}
        },
    )
    tb = next(a for a in attribute_corner(ctx) if a.key == "trail_brake")
    assert tb.advisory is False  # archive technique read — nothing live to confirm
    assert tb.technique_causes and not tb.setup_causes  # -> cause_class "technique", no setup delta
    assert tb.coaching == "bleed it off smoothly"  # forwards the classification's own coaching


def test_trail_brake_no_attribution_without_injected_signal():
    # attribute_corner called directly (no coach_lap injection) must not invent a trail_brake attr
    assert not any(
        a.key == "trail_brake" for a in attribute_corner(CornerContext(sig=_sig(), setup=SETUP))
    )


def test_good_trail_brake_does_not_attribute():
    ctx = CornerContext(
        sig=_sig(),
        setup=SETUP,
        extra={"trail_brake": {"classification": "good_trail_brake", "coaching": "textbook"}},
    )
    assert not any(a.key == "trail_brake" for a in attribute_corner(ctx))


def test_trail_brake_never_displaces_a_setup_bearing_attribution():
    # a corner that loses time braking AND trail-brakes poorly: braking_phase_loss stays PRIMARY
    # (it carries the bias/setup hint); trail_brake only participates as a lower-ranked cue
    ctx = CornerContext(
        sig=_sig(peak_brake_g=1.1, brake_point_spline=0.40),
        setup=SETUP,
        delta=_delta(delta_s=0.3, min_speed_delta_kmh=0.0),  # no apex-speed deficit -> only braking
        extra={"trail_brake": {"classification": "abrupt_release", "coaching": "bleed it off"}},
    )
    keys = [a.key for a in attribute_corner(ctx)]
    assert "braking_phase_loss" in keys and "trail_brake" in keys
    assert keys[0] == "braking_phase_loss"
    assert keys.index("trail_brake") > keys.index("braking_phase_loss")


def test_coach_lap_folds_in_trail_brake_attribution():
    # the square-brake fixture trail-brakes poorly -> coach_lap injects a trail_brake attribution
    lap = _corner_lap_trace()
    report = coach_lap(lap, SETUP, grip_ceiling_g=2.5)
    assert any(a.key == "trail_brake" for c in report for a in c.attributions)
