"""Tests for the GGV friction-circle minimum-time speed profiler (tools.ac_harness.ggv_profile).

Pure-math, no game. Covers the red-team-mandated guards: curvature accuracy, friction-ellipse
corners, forward-backward correctness/feasibility on a synthetic track, GGV de-contamination
(straight-line high-speed bins must not poison lateral grip), and build determinism.
"""

from __future__ import annotations

import math

from tools.ac_harness.ggv_profile import (
    CurvatureFeedforwardSteering,
    GGVModel,
    blend_ggv_safe,
    build_ggv_speed_profile,
    curvature_profile,
    fit_steer_feedforward,
    forward_backward_profile,
    ggv_from_telemetry,
    menger_curvature,
    seg_lengths,
    signed_curvature_profile,
)

G = 9.81


def _circle(radius: float, n: int) -> list[tuple[float, float, float]]:
    return [
        (radius * math.cos(2 * math.pi * i / n), 0.0, radius * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _flat_ggv(mu=1.0, brake=1.0, drive=1.0, n=2.0) -> GGVModel:
    return GGVModel(
        mu_lat_g=mu,
        k_aero_lat=0.0,
        brake_b0_g=brake,
        brake_b1=0.0,
        drive_b0_g=drive,
        drive_b1=0.0,
        drive_min_g=0.3,
        ellipse_n=n,
    )


# --- curvature -------------------------------------------------------------
def test_menger_curvature_circle():
    r = 50.0
    pts = [(r * math.cos(a), r * math.sin(a)) for a in (0.0, 0.1, 0.2)]
    assert abs(menger_curvature(*pts) - 1.0 / r) < 1e-3


def test_curvature_profile_constant_on_circle():
    r = 40.0
    plane = [(p[0], p[2]) for p in _circle(r, 400)]
    kappa = curvature_profile(plane, smooth_win=2, span=3)
    # interior points: curvature ~ 1/r within a few percent
    mid = kappa[50:350]
    assert all(abs(k - 1.0 / r) < 0.05 * (1.0 / r) for k in mid), (min(mid), max(mid), 1 / r)


def test_curvature_zero_on_straight():
    plane = [(float(i), 0.0) for i in range(50)] + [(49.0 - i, 5.0) for i in range(50)]
    kappa = curvature_profile(plane, smooth_win=1, span=2)
    assert kappa[20] < 1e-3  # mid-straight


# --- friction ellipse ------------------------------------------------------
def test_ellipse_corners():
    ggv = _flat_ggv(mu=1.2, brake=2.0, n=2.0)
    v = 30.0
    # no lateral -> full braking
    assert abs(ggv.ax_brake_avail(0.0, v) - ggv.ax_brake_max(v)) < 1e-6
    # at the lateral limit -> ~zero braking left
    assert ggv.ax_brake_avail(ggv.ay_max(v), v) < 1e-3
    # interior is between, monotone decreasing in lateral usage
    a_lo = ggv.ax_brake_avail(0.3 * ggv.ay_max(v), v)
    a_hi = ggv.ax_brake_avail(0.7 * ggv.ay_max(v), v)
    assert ggv.ax_brake_max(v) > a_lo > a_hi > 0.0


def test_aero_braking_rises_with_speed():
    ggv = GGVModel(
        mu_lat_g=1.2,
        k_aero_lat=0.0,
        brake_b0_g=0.9,
        brake_b1=0.025,
        drive_b0_g=0.8,
        drive_b1=0.0,
        drive_min_g=0.3,
        ellipse_n=1.5,
    )
    assert ggv.ax_brake_max(60.0) > ggv.ax_brake_max(10.0)  # downforce


# --- forward-backward profile ---------------------------------------------
def test_profile_constant_on_circle_equals_apex():
    r = 60.0
    plane = [(p[0], p[2]) for p in _circle(r, 600)]
    seg = seg_lengths(plane)
    kappa = curvature_profile(plane, smooth_win=2, span=3)
    ggv = _flat_ggv(mu=1.0)
    v, _ = forward_backward_profile(kappa, seg, ggv, v_top_ms=200.0, v_floor_ms=1.0)
    apex = math.sqrt(ggv.ay_max(0.0) * r)  # sqrt(mu*g*R)
    mid = v[100:500]
    assert all(abs(x - apex) < 0.06 * apex for x in mid), (min(mid), max(mid), apex)


def test_profile_brakes_into_corner_and_respects_vtop():
    # long straight (kappa 0) into a tight arc: speed must fall toward the arc apex before it
    n_straight, r, n_arc = 300, 25.0, 120
    straight = [(float(i) * 3.0, 0.0) for i in range(n_straight)]
    cx = straight[-1][0]
    arc = [
        (cx + r * math.sin(a), r - r * math.cos(a))
        for a in (math.pi * 2 * i / (n_arc * 4) for i in range(n_arc))
    ]
    plane = straight + arc
    seg = seg_lengths(plane)
    kappa = curvature_profile(plane, smooth_win=1, span=2)
    ggv = _flat_ggv(mu=1.1, brake=1.3)
    v, _ = forward_backward_profile(kappa, seg, ggv, v_top_ms=80.0, v_floor_ms=2.0)
    assert max(v) <= 80.0 + 1e-6  # v_top respected
    assert v[n_straight + n_arc // 2] < v[50]  # slowed in the arc vs early straight
    # braking happened on the straight before the arc (speed decreasing approaching the corner)
    assert v[n_straight - 5] < v[n_straight - 60]


def test_profile_deterministic():
    r = 45.0
    plane = [(p[0], p[2]) for p in _circle(r, 300)]
    seg = seg_lengths(plane)
    kappa = curvature_profile(plane, smooth_win=2, span=3)
    ggv = _flat_ggv()
    a, _ = forward_backward_profile(kappa, seg, ggv)
    b, _ = forward_backward_profile(kappa, seg, ggv)
    assert a == b


# --- GGV de-contamination from telemetry ----------------------------------
def _rows(speed_kmh, lat_max, lon_brake_max, n):
    # deterministic spread 0..max via index fraction
    out = []
    for i in range(n):
        f = (i % 100) / 99.0
        out.append(
            {
                "speed_kmh": str(speed_kmh),
                "accg_lat": str(lat_max * f),
                "accg_lon": str(-lon_brake_max * f),
            }
        )
    return out


def test_ggv_decontamination_lateral_not_poisoned_by_straights():
    # mid-speed bin: real hard cornering (up to 1.3g). high-speed bin: straight-line only (0.1g lat)
    rows = _rows(60, 1.3, 1.2, 1500) + _rows(210, 0.1, 2.6, 1500)
    ggv = ggv_from_telemetry(rows, min_samples=50)
    # lateral grip reflects the cornering bin (~1.2-1.3g), NOT dragged toward 0.1
    assert ggv.mu_lat_g > 1.0, ggv.provenance["lat_model"]
    # high-speed bin tagged as non-cornering; mid-speed bin tagged cornering
    bins = ggv.provenance["bins"]
    assert bins[60]["cornered"] is True
    assert bins[210]["cornered"] is False
    # braking grip rises with speed (aero) — fitted slope positive
    assert ggv.ax_brake_max(55.0) > ggv.ax_brake_max(15.0)


def test_ggv_no_aero_lateral_extrapolation():
    rows = _rows(60, 1.3, 1.2, 1500) + _rows(210, 0.1, 2.6, 1500)
    ggv = ggv_from_telemetry(rows, min_samples=50)
    assert ggv.k_aero_lat == 0.0  # honest: no high-speed cornering data -> no aero-lateral claim
    assert ggv.ay_max(10.0) == ggv.ay_max(58.0)  # flat lateral grip


# --- end-to-end build determinism on a synthetic line ----------------------
def test_build_ggv_speed_profile_deterministic_and_capped(tmp_path):
    import csv as _csv

    csvp = tmp_path / "tele.csv"
    with csvp.open("w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["speed_kmh", "accg_lat", "accg_lon"])
        for r in _rows(60, 1.3, 1.2, 1500) + _rows(200, 0.1, 2.6, 1500):
            w.writerow([r["speed_kmh"], r["accg_lat"], r["accg_lon"]])
    line = _circle(50.0, 400)
    v1, g1, s1 = build_ggv_speed_profile(line, csvp, v_top_kmh=180.0)
    v2, g2, s2 = build_ggv_speed_profile(line, csvp, v_top_kmh=180.0)
    assert v1 == v2 and s1 == s2
    assert max(v1) <= 180.0 / 3.6 + 1e-6
    assert len(v1) == len(line)


def test_lat_grip_override_raises_apex_and_overrides_model(tmp_path):
    import csv as _csv

    csvp = tmp_path / "tele.csv"
    with csvp.open("w", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["speed_kmh", "accg_lat", "accg_lon"])
        for r in _rows(60, 1.3, 1.2, 1500) + _rows(200, 0.1, 2.6, 1500):
            w.writerow([r["speed_kmh"], r["accg_lat"], r["accg_lon"]])
    line = _circle(50.0, 400)
    lo, glo, _ = build_ggv_speed_profile(line, csvp, v_top_kmh=300.0)
    hi, ghi, _ = build_ggv_speed_profile(line, csvp, v_top_kmh=300.0, lat_grip_g=1.6)
    assert ghi.mu_lat_g == 1.6 and ghi.mu_lat_g > glo.mu_lat_g
    assert max(hi) > max(lo)  # higher lateral grip -> higher apex speed on the circle


# --- RacingDriver.from_ggv_profile wiring ----------------------------------
def test_from_ggv_profile_uses_target_verbatim_and_steps():
    from tools.ac_harness.racing_driver import RacingDriver

    line = _circle(50.0, 400)
    vt = [30.0] * len(line)  # constant 30 m/s target
    d = RacingDriver.from_ggv_profile(line, vt, steering_mode="stanley")
    assert d.profile == vt  # FINAL profile used verbatim: no cap, no fixed-brake_g backward pass
    f = d.step((50.0, 0.0, 0.0), (0.0, 0.0, 1.0), 100.0, 6000.0, 4, 1.0)
    assert 0.0 <= f.gas <= 1.0 and 0.0 <= f.brake <= 1.0 and -1.0 <= f.steer <= 1.0
    # over the 30 m/s target at 100 km/h (27.8 m/s)? 100km/h=27.8 < 30 so should not be max-braking
    f2 = d.step((50.0, 0.0, 0.0), (0.0, 0.0, 1.0), 200.0, 6000.0, 5, 2.0)  # 55 m/s >> 30 target
    assert f2.brake > 0.5  # well over target -> braking


def test_from_ggv_profile_length_mismatch_raises():
    import pytest

    from tools.ac_harness.racing_driver import RacingDriver

    line = _circle(50.0, 100)
    with pytest.raises(ValueError):
        RacingDriver.from_ggv_profile(line, [30.0] * 50)


# --- Stage 2: slip ratio + slip limiter + ax feedforward -------------------
def test_slip_ratio_sign_and_deadzone():
    from tools.ac_harness.racing_driver import slip_ratio

    r, v = 0.33, 30.0
    omega_match = v / r  # wheel surface speed == body speed -> ~0 slip
    assert abs(slip_ratio(omega_match, r, v)) < 1e-6
    assert slip_ratio(omega_match * 1.2, r, v) > 0.1  # wheelspin
    assert slip_ratio(omega_match * 0.8, r, v) < -0.1  # locking
    assert slip_ratio(omega_match, r, 0.1) == 0.0  # near-stationary deadzone


def test_slip_limited_controls_clamps_only():
    from tools.ac_harness.racing_driver import slip_limited_controls

    # below thresholds: untouched
    g, b = slip_limited_controls(1.0, 0.0, 0.05, 0.0)
    assert g == 1.0
    # wheelspin: gas cut, never raised
    g2, _ = slip_limited_controls(1.0, 0.0, 0.40, 0.0, accel_slip_target=0.16, cut_gain=4.0)
    assert 0.0 <= g2 < 1.0
    # lockup: brake cut
    _, b2 = slip_limited_controls(0.0, 1.0, 0.0, -0.40, brake_slip_target=0.16, cut_gain=4.0)
    assert 0.0 <= b2 < 1.0
    # extreme slip drives the command toward zero, never negative
    g3, b3 = slip_limited_controls(1.0, 1.0, 2.0, -2.0)
    assert g3 == 0.0 and b3 == 0.0


def test_profile_ax_feedforward_sign():
    from tools.ac_harness.racing_driver import RacingDriver

    line = _circle(50.0, 100)
    d = RacingDriver.from_ggv_profile(line, [30.0] * 100)
    assert abs(d._profile_ax(10)) < 1e-6  # constant profile -> no demanded accel
    d.profile[11] = 20.0
    assert d._profile_ax(10) < 0  # next point slower -> decelerate
    d.profile[11] = 40.0
    assert d._profile_ax(10) > 0  # next point faster -> accelerate


def test_ff_adds_braking_when_profile_decelerates():
    from tools.ac_harness.racing_driver import RacingDriver

    line = _circle(50.0, 100)
    d_ff = RacingDriver.from_ggv_profile(line, [30.0] * 100, ax_feedforward=True)
    d_no = RacingDriver.from_ggv_profile(line, [30.0] * 100, ax_feedforward=False)
    d_ff.profile[11] = 10.0
    d_no.profile[11] = 10.0
    _, b_ff = d_ff._longitudinal(10, 30.0 * 3.6, 0.0)
    _, b_no = d_no._longitudinal(10, 30.0 * 3.6, 0.0)
    assert b_ff >= b_no  # feedforward brakes at least as hard into the decel


# --- Stage 3: signed curvature + steer feedforward fit + lateral controller ---
def test_signed_curvature_consistent_sign_on_circle():
    plane = [(p[0], p[2]) for p in _circle(40.0, 400)]
    sk = signed_curvature_profile(plane, smooth_win=2, span=3)
    mid = sk[50:350]
    assert all((x > 0) == (mid[0] > 0) for x in mid)  # one consistent turn direction
    assert all(abs(abs(x) - 1.0 / 40.0) < 0.05 / 40.0 for x in mid)  # magnitude ~ 1/R


def test_fit_steer_feedforward_recovers_coeffs():
    # synthetic: steer = 4.0*kappa + 0.002*(v^2*kappa) exactly
    c1_true, c2_true = 4.0, 0.002
    rows = []
    for i in range(400):
        v = 20.0 + 0.2 * i  # m/s spread
        kappa = 0.01 + 0.00005 * (i % 50)
        ay = v * v * kappa
        steer = c1_true * kappa + c2_true * ay
        rows.append({"speed_kmh": str(v * 3.6), "accg_lat": str(ay / G), "steer": str(steer)})
    c1, c2, rms, n = fit_steer_feedforward(rows, min_lat_g=0.0, min_kmh=0.0)
    assert abs(c1 - c1_true) < 0.05 and abs(c2 - c2_true) < 1e-4
    assert rms < 0.02 and n == 400


def test_curvature_ff_steering_in_range_and_uses_curvature():
    line = _circle(50.0, 400)
    cff = CurvatureFeedforwardSteering(
        line, c1=5.0, c2=0.0, ff_sign=1.0, fb_weight=0.0, preview_m=2.0
    )
    # facing along +x at a point on the circle; FF should command a nonzero, in-range steer
    s = cff.steer((50.0, 0.0, 0.0), (0.0, 0.0, 1.0), 80.0)
    assert -1.0 <= s <= 1.0
    # zero coefficients + zero feedback -> zero steer (pure FF off)
    flat = CurvatureFeedforwardSteering(line, c1=0.0, c2=0.0, ff_sign=1.0, fb_weight=0.0)
    assert abs(flat.steer((50.0, 0.0, 0.0), (0.0, 0.0, 1.0), 80.0)) < 1e-9


def test_racing_driver_curvature_ff_mode_steps():
    from tools.ac_harness.racing_driver import RacingDriver

    line = _circle(50.0, 200)
    d = RacingDriver.from_ggv_profile(
        line, [30.0] * 200, steering_mode="curvature_ff", ff_c1=5.0, ff_c2=0.002
    )
    assert d.cff is not None
    f = d.step((50.0, 0.0, 0.0), (0.0, 0.0, 1.0), 100.0, 6000.0, 4, 1.0)
    assert -1.0 <= f.steer <= 1.0


# --- Stage 4: min-curvature optimized line --------------------------------
def test_min_curvature_reduces_perturbation_and_respects_corridor():
    from tools.ac_harness.ggv_profile import min_curvature_line

    r, n = 40.0, 200
    base = [
        (r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)
    ]
    base[50] = (base[50][0] * 1.08, base[50][1] * 1.08)  # bump one point outward
    sl = [3.0] * n
    sr = [3.0] * n
    k0 = sum(x * x for x in curvature_profile(base, smooth_win=1, span=2))
    opt, alpha = min_curvature_line(base, sl, sr, margin_m=0.5, iters=1500, damp=0.5)
    k1 = sum(x * x for x in curvature_profile(opt, smooth_win=1, span=2))
    assert k1 < k0 - 1e-6  # curvature is reduced; no-op output should fail
    assert max(abs(a) for a in alpha) > 1e-6
    # every offset stays inside the corridor (margin off each edge)
    assert all(-(sr[i] - 0.5) - 1e-6 <= alpha[i] <= (sl[i] - 0.5) + 1e-6 for i in range(n))
    assert len(opt) == n


def test_min_curvature_offset_zero_when_corridor_closed():
    from tools.ac_harness.ggv_profile import min_curvature_line

    plane = [(p[0], p[2]) for p in _circle(30.0, 120)]
    z = [0.0] * 120  # zero-width corridor (margin >= width) -> no movement allowed
    opt, alpha = min_curvature_line(plane, z, z, margin_m=1.0, iters=300, damp=0.5)
    assert all(abs(a) < 1e-9 for a in alpha)
    assert opt == plane


def test_ggv_speed_profile_from_model_and_aero_raises_apex():
    from tools.ac_harness.ggv_profile import GGVModel, ggv_speed_profile_from_model

    line = _circle(60.0, 300)
    flat = GGVModel(1.5, 0.0, 0.955, 0.0214, 1.1, -0.0117, 0.35, 1.55, ay_cap_g=3.5)
    aero = GGVModel(1.5, 0.0005, 0.955, 0.0214, 1.1, -0.0117, 0.35, 1.55, ay_cap_g=3.5)
    v_flat, s_flat = ggv_speed_profile_from_model(line, flat, v_top_kmh=300.0)
    v_aero, s_aero = ggv_speed_profile_from_model(line, aero, v_top_kmh=300.0)
    assert len(v_flat) == len(line)
    assert max(v_aero) >= max(v_flat)  # aero grip lets the constant-radius apex carry more speed
    assert s_aero["qss_laptime_s"] <= s_flat["qss_laptime_s"]  # ...so the lap is no slower


# --- #532 Part B: serialization + safe-envelope blend -----------------------
def _prior() -> GGVModel:
    return GGVModel(1.5, 0.0, 0.955, 0.0214, 1.1, -0.0117, 0.35, 1.55, ay_cap_g=1.8)


def _measured(
    mu,
    *,
    corner_bins,
    brake_bins,
    accel_bins,
    hull_points,
    ellipse_n=1.3,
    brake_b0=0.6,  # below the prior (0.955) by default -> does NOT trigger the raise branch
    brake_b1=0.02,
    drive_b0=0.7,  # below the prior (1.1) by default
    drive_b1=-0.01,
) -> GGVModel:
    return GGVModel(
        mu_lat_g=mu,
        k_aero_lat=0.0,
        brake_b0_g=brake_b0,
        brake_b1=brake_b1,
        drive_b0_g=drive_b0,
        drive_b1=drive_b1,
        drive_min_g=0.4,
        ellipse_n=ellipse_n,
        provenance={
            "lat_corner_bins": corner_bins,
            "brake_bins": brake_bins,
            "accel_bins": accel_bins,
            "hull_points": hull_points,
            "bins": {},
        },
    )


def test_ggv_model_roundtrip_and_rejects_nan():
    m = _prior()
    back = GGVModel.from_dict(m.to_dict())
    for f in ("mu_lat_g", "k_aero_lat", "brake_b0_g", "brake_b1", "ellipse_n", "ay_cap_g"):
        assert getattr(back, f) == getattr(m, f)
    import pytest

    with pytest.raises(ValueError):
        GGVModel.from_dict({**m.to_dict(), "mu_lat_g": float("nan")})
    with pytest.raises(ValueError):
        GGVModel.from_dict({k: v for k, v in m.to_dict().items() if k != "brake_b0_g"})


def test_blend_never_raises_lateral_above_prior():
    prior = _prior()
    # A measured HIGHER lateral must NOT lift the plant (aero-lateral spins the GT3, #259).
    grippier = _measured(1.9, corner_bins=6, brake_bins=6, accel_bins=6, hull_points=200)
    b = blend_ggv_safe(grippier, prior)
    assert b.mu_lat_g == prior.mu_lat_g
    assert b.k_aero_lat == 0.0
    assert b.ay_cap_g == prior.ay_cap_g
    assert b.provenance["blend_source"]["lateral"] == "prior"


def test_blend_pins_lateral_to_prior_even_when_measured_lower():
    # A conservative handshake under-measures the lateral limit, so a measured value BELOW the prior
    # is a lower bound, not a weaker car — it must NOT lower the plant (that would regress the
    # reference car). Lateral is pinned to the prior regardless of the measured value.
    prior = _prior()
    lower = _measured(1.15, corner_bins=6, brake_bins=6, accel_bins=6, hull_points=200)
    b = blend_ggv_safe(lower, prior)
    assert b.mu_lat_g == prior.mu_lat_g  # NOT lowered to 1.15
    assert b.provenance["blend_source"]["lateral"] == "prior"
    # The measured lower bound is still recorded (for a future slip-saturation pass).
    assert b.provenance["measured"]["mu_lat_g"] == 1.15


def test_blend_raises_braking_when_measured_confidently_exceeds_prior():
    # Braking is safely limit-reachable (straight-line): a measured brake curve that dominates the
    # prior across the covered speeds IS adopted (real evidence of more braking capability).
    prior = _prior()
    strong = _measured(
        1.2,
        corner_bins=6,
        brake_bins=6,
        accel_bins=6,
        hull_points=200,
        brake_b0=1.3,
        brake_b1=0.03,  # > prior (0.955 + 0.0214 v) at both 40 and 180 km/h
    )
    b = blend_ggv_safe(strong, prior)
    assert (b.brake_b0_g, b.brake_b1) == (1.3, 0.03)
    assert b.provenance["blend_source"]["brake"] == "measured(>prior)"
    assert b.ax_brake_cap_g == prior.ax_brake_cap_g  # hard cap still kept
    assert b.mu_lat_g == prior.mu_lat_g  # lateral untouched


def test_blend_sparse_bins_fall_back_to_prior():
    prior = _prior()
    # Under-covered: too few cornered/brake/accel bins, thin hull -> every curve reverts to prior.
    sparse = _measured(1.0, corner_bins=0, brake_bins=0, accel_bins=0, hull_points=3)
    b = blend_ggv_safe(sparse, prior)
    assert b.mu_lat_g == prior.mu_lat_g
    assert (b.brake_b0_g, b.brake_b1) == (prior.brake_b0_g, prior.brake_b1)
    assert (b.drive_b0_g, b.drive_b1) == (prior.drive_b0_g, prior.drive_b1)
    assert b.ellipse_n == prior.ellipse_n
    src = b.provenance["blend_source"]
    assert src == {
        "lateral": "prior",
        "brake": "prior",
        "drive": "prior",
        "ellipse_n": "prior",
    }


def test_blend_ellipse_reverts_when_hull_thin():
    prior = _prior()
    thin = _measured(1.2, corner_bins=6, brake_bins=6, accel_bins=6, hull_points=5, ellipse_n=1.1)
    b = blend_ggv_safe(thin, prior)
    assert b.ellipse_n == prior.ellipse_n  # not enough hull -> keep the prior coupling
    assert b.provenance["blend_source"]["ellipse_n"] == "prior"


def test_ggv_from_telemetry_records_bin_counts():
    rows = []
    for kmh in range(60, 141, 10):
        for _ in range(60):
            rows.append({"speed_kmh": float(kmh), "accg_lat": 1.1, "accg_lon": 0.0})
            rows.append({"speed_kmh": float(kmh), "accg_lat": 0.0, "accg_lon": -1.0})
            rows.append({"speed_kmh": float(kmh), "accg_lat": 0.05, "accg_lon": 0.7})
    m = ggv_from_telemetry(rows)
    assert m.provenance["brake_bins"] >= 2
    assert m.provenance["accel_bins"] >= 2
    assert m.provenance["hull_points"] > 0
