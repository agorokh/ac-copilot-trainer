"""Tests for the #532 plant-ID handshake — synthetic plant with KNOWN constants, recovered.

The end-to-end tests drive :class:`HandshakeController` against a pure kinematic simulator whose
steer feedforward (``c1``/``c2``/``ff_sign``), gear ratios, limiter, and wheel radius are known,
and assert the handshake measures them back within tolerance — plus every gate's interpretable
failure path. No game, no Windows, no I/O beyond tmp_path.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from tools.ac_harness.plant_id import (
    HandshakeController,
    apply_handshake_outcome,
    find_straights,
    fit_ff_sign,
    fit_gear_ratios,
    fit_r_eff,
    fit_shift_points,
    fit_steer_ff,
    load_plant_artifact,
    plant_artifact_path,
    plant_driver_kwargs,
    save_plant_artifact,
)

# ---------------------------------------------------------------------------
# Synthetic track (stadium oval) + plant simulator with known constants
# ---------------------------------------------------------------------------
STRAIGHT_M = 900.0
R1, R2 = 100.0, 160.0
SPACING_M = 6.0

# Plant truth. ff_sign=+1 matches the harness convention Stanley steering assumes (steer > 0
# rotates the heading cross-positive in the (x, z) plane) — the base navigator requires it.
C1_TRUE = 6.0
C2_TRUE = 0.015
R_EFF_TRUE = 0.34
RATIOS_TRUE = {2: 110.0, 3: 82.0, 4: 62.0, 5: 47.0}  # rpm per km/h, AC gear encoding
LIMITER_RPM = 8200.0
MAX_GEAR = 5


def _stadium_line() -> list[tuple[float, float, float]]:
    pts: list[tuple[float, float, float]] = []

    def add(x: float, z: float) -> None:
        pts.append((x, 0.0, z))

    n1 = int(STRAIGHT_M // SPACING_M)
    for i in range(n1):
        add(i * SPACING_M, 0.0)
    arc1_len = math.pi * R1
    for i in range(int(arc1_len // SPACING_M)):
        phi = -math.pi / 2 + math.pi * (i * SPACING_M / arc1_len)
        add(STRAIGHT_M + R1 * math.cos(phi), R1 + R1 * math.sin(phi))
    for i in range(n1):
        add(STRAIGHT_M - i * SPACING_M, 2 * R1)
    # closing arc joins z=2*R1 at x=0 back to z=0; use an elliptical-ish blend via a semicircle
    # of radius R1 (keep geometry closed) but traversed with different point density so the two
    # corners still differ in speed via the profile.
    arc2_len = math.pi * R1
    for i in range(int(arc2_len // (SPACING_M * 0.75))):
        phi = math.pi / 2 + math.pi * (i * SPACING_M * 0.75 / arc2_len)
        add(R1 * math.cos(phi) - 0.0, R1 + R1 * math.sin(phi))
    return pts


def _profile_for(line: list[tuple[float, float, float]]) -> list[float]:
    """Per-point target speed (m/s): fast straights, two distinct corner speeds.

    Distinct corner speeds matter: with a single cornering speed the ``c2`` (v^2*kappa) column is
    collinear with the ``c1`` (kappa) column and the steer-FF fit is degenerate by construction.
    """
    profile = []
    for x, _, _z in line:
        on_straight = 0.0 < x < STRAIGHT_M
        if on_straight:
            profile.append(45.0)
        elif x >= STRAIGHT_M:  # right-end corner: slow (pace-scaled ~19 m/s, ~0.37 g at R=100)
            profile.append(29.0)
        else:  # left-end corner: fast (pace-scaled ~26 m/s) -> v^2 spread identifies c2
            profile.append(40.0)
    return profile


def _torque_frac(rpm: float) -> float:
    return max(0.3, 1.0 - 0.5 * ((rpm - 5600.0) / 3000.0) ** 2)


class PlantSim:
    """Kinematic bicycle-ish plant: steer -> curvature via the KNOWN feedforward relation."""

    def __init__(self, line, *, c1=C1_TRUE, c2=C2_TRUE, r_eff=R_EFF_TRUE):
        self.c1, self.c2, self.r_eff = c1, c2, r_eff
        x0, _, z0 = line[0]
        x1, _, z1 = line[1]
        norm = math.hypot(x1 - x0, z1 - z0)
        self.pos = [x0, z0]
        self.heading = [(x1 - x0) / norm, (z1 - z0) / norm]
        self.v = 0.0
        self.gear = 1  # AC encoding: neutral

    @property
    def speed_kmh(self) -> float:
        return self.v * 3.6

    @property
    def rpm(self) -> float:
        ratio = RATIOS_TRUE.get(self.gear, RATIOS_TRUE[2])
        return max(900.0, min(LIMITER_RPM, ratio * self.speed_kmh))

    def observe(self):
        return (
            (self.pos[0], 0.0, self.pos[1]),
            (self.heading[0], 0.0, self.heading[1]),
            self.speed_kmh,
            self.rpm,
            self.gear,
        )

    def phys(self):
        base = self.v / self.r_eff
        return SimpleNamespace(wheel_omega=(base, base, base, base))

    def apply(self, frame, dt: float) -> None:
        if frame.gear_up:
            self.gear = min(self.gear + 1, MAX_GEAR) if self.gear >= 2 else 2
        elif frame.gear_dn and self.gear > 2:
            self.gear -= 1
        drive = 0.0
        if self.gear >= 2 and self.rpm < LIMITER_RPM - 1.0:
            ratio_frac = RATIOS_TRUE[self.gear] / RATIOS_TRUE[2]
            drive = 14.0 * ratio_frac * _torque_frac(self.rpm) * frame.gas
        accel = drive - 0.004 * self.v * self.v - 0.15 - 9.0 * frame.brake
        self.v = max(0.0, self.v + accel * dt)
        kappa = frame.steer / (self.c1 + self.c2 * self.v * self.v)
        dpsi = kappa * self.v * dt
        c, s = math.cos(dpsi), math.sin(dpsi)
        hx, hz = self.heading
        self.heading = [hx * c - hz * s, hx * s + hz * c]
        self.pos[0] += self.heading[0] * self.v * dt
        self.pos[1] += self.heading[1] * self.v * dt


def _run_handshake(ctrl: HandshakeController, sim: PlantSim, *, max_seconds=420.0, dt=1 / 60):
    now = 0.0
    while now < max_seconds and not ctrl.finished:
        pos, look, speed, rpm, gear = sim.observe()
        frame = ctrl.step(pos, look, speed, rpm, gear, now)
        sim.apply(frame, dt)
        now += dt
    return ctrl


@pytest.fixture(scope="module")
def handshake_outcome():
    line = _stadium_line()
    sim = PlantSim(line)
    sink: dict = {}
    ctrl = HandshakeController(
        line,
        _profile_for(line),
        car_id="test_car",
        track_id="test_oval",
        sink=sink,
        phys_read=sim.phys,
    )
    _run_handshake(ctrl, sim)
    return ctrl, sink


# ---------------------------------------------------------------------------
# End-to-end recovery of the known plant
# ---------------------------------------------------------------------------
def test_handshake_finishes_and_passes(handshake_outcome):
    ctrl, sink = handshake_outcome
    assert ctrl.finished, "handshake never completed on the synthetic plant"
    assert ctrl.result is not None
    failed = ctrl.result.failed()
    assert ctrl.result.ok, f"handshake failed: {[(m.name, m.detail) for m in failed]}"
    assert sink["ok"] is True
    assert sink["constants"] == ctrl.result.constants()


def test_handshake_recovers_ff_sign(handshake_outcome):
    ctrl, _ = handshake_outcome
    assert ctrl.result.constants()["ff_sign"] == 1.0


def test_handshake_recovers_steer_feedforward(handshake_outcome):
    ctrl, _ = handshake_outcome
    constants = ctrl.result.constants()
    c1, c2 = constants["ff_c1"], constants["ff_c2"]
    # The steer the fitted FF predicts must match the true plant at the OPERATING POINTS the
    # handshake actually visited (both corners are R1; speeds differ) — extrapolation beyond the
    # mined envelope is not part of the fit's contract.
    for v, kappa in ((19.0, 1 / R1), (26.0, 1 / R1), (22.0, 1 / R1)):
        true_steer = (C1_TRUE + C2_TRUE * v * v) * kappa
        fit_steer = c1 * kappa + c2 * (v * v * kappa)
        assert fit_steer == pytest.approx(true_steer, rel=0.15), (
            f"FF mismatch at v={v} kappa={kappa}: fit {fit_steer:.4f} vs true {true_steer:.4f} "
            f"(c1={c1:.3f} c2={c2:.5f})"
        )


def test_handshake_recovers_gear_ratios(handshake_outcome):
    ctrl, _ = handshake_outcome
    ratios = ctrl.result.constants()["gear_ratios"]
    assert len(ratios) >= 2
    for gear_str, measured in ratios.items():
        assert measured == pytest.approx(RATIOS_TRUE[int(gear_str)], rel=0.02)


def test_handshake_shift_points_plausible(handshake_outcome):
    ctrl, _ = handshake_outcome
    constants = ctrl.result.constants()
    assert 6500.0 <= constants["rpm_up"] <= LIMITER_RPM
    assert constants["rpm_dn"] < constants["rpm_up"] * 0.85
    assert constants["rpm_dn"] >= 1500.0


def test_handshake_recovers_wheel_radius(handshake_outcome):
    ctrl, _ = handshake_outcome
    assert ctrl.result.constants()["r_eff_m"] == pytest.approx(R_EFF_TRUE, abs=0.005)


def test_handshake_within_lap_budget(handshake_outcome):
    ctrl, _ = handshake_outcome
    assert ctrl.result.laps_used <= 2


def test_handshake_finalize_on_drive_end_produces_partial_result():
    # #532: a drive that ends before the schedule self-completes must still yield a result naming
    # which constants were measured — not a bare "no result".
    line = _stadium_line()
    sim = PlantSim(line)
    sink: dict = {}
    ctrl = HandshakeController(
        line, _profile_for(line), car_id="c", track_id="t", sink=sink, phys_read=sim.phys
    )
    # Drive only briefly, then force finalize (simulates the rig drive budget expiring).
    now = 0.0
    while now < 25.0 and not ctrl.finished:
        pos, look, speed, rpm, gear = sim.observe()
        ctrl.step(pos, look, speed, rpm, gear, now)
        sim.apply(ctrl._base.step(pos, look, speed, rpm, gear, now), 1 / 60)
        now += 1 / 60
    if not ctrl.finished:
        ctrl.finalize(now)
    assert ctrl.finished
    assert sink.get("result") is not None
    assert "diagnostics" in sink
    # finalize is idempotent
    prev = sink["result"]
    ctrl.finalize(now + 1)
    assert sink["result"] is prev


def test_probe_failure_cap_drops_probe_and_completes():
    # A probe that can never satisfy its straight requirement must DROP after the cap so the
    # schedule can complete, rather than looping forever (#532 Spa sweep hang).
    line = _stadium_line()
    sink: dict = {}
    ctrl = HandshakeController(
        line, _profile_for(line), car_id="c", track_id="t", sink=sink, phys_read=lambda: None
    )
    ctrl._max_probe_attempts = 3
    # Simulate the abort/re-queue cycle: the probe is consumed (not pending), fails, re-queues.
    for _ in range(10):
        if "accel_sweep" in ctrl._pending:
            ctrl._pending.remove("accel_sweep")
        ctrl._requeue("accel_sweep", front=False, failed=True)
    assert ctrl._probe_attempts["accel_sweep"] >= 3
    assert "accel_sweep" not in ctrl._pending  # dropped after the cap, never re-added


def test_handshake_without_physics_fails_r_eff_interpretably():
    line = _stadium_line()
    sim = PlantSim(line)
    sink: dict = {}
    ctrl = HandshakeController(
        line,
        _profile_for(line),
        car_id="test_car",
        track_id="test_oval",
        sink=sink,
        phys_read=None,
    )
    _run_handshake(ctrl, sim)
    assert ctrl.finished
    assert not ctrl.result.ok
    failed = {m.name: m for m in ctrl.result.failed()}
    assert set(failed) == {"r_eff"}
    assert "coast" in failed["r_eff"].detail
    # the hard-abort surfaces through the report finalizer
    report = SimpleNamespace(ok=True, stage="done", error=None, notes=[])
    apply_handshake_outcome(report, sink)
    assert report.ok is False
    assert report.stage == "handshake"
    assert "r_eff" in report.error


# ---------------------------------------------------------------------------
# Pure fit gates
# ---------------------------------------------------------------------------
def _pulse(steer: float, dpsi: float, speed=60.0) -> dict:
    return {"steer": steer, "dpsi_rad": dpsi, "duration_s": 0.9, "speed_kmh": speed}


def test_fit_ff_sign_negative_convention():
    m = fit_ff_sign([_pulse(0.12, -0.2), _pulse(-0.12, 0.18)])
    assert m.passed and m.value["ff_sign"] == -1.0


def test_fit_ff_sign_disagreement_fails():
    m = fit_ff_sign([_pulse(0.12, 0.2), _pulse(-0.12, 0.18)])
    assert not m.passed
    assert "disagree" in m.detail


def test_fit_ff_sign_ambiguous_yaw_fails():
    m = fit_ff_sign([_pulse(0.12, 0.001), _pulse(-0.12, -0.001)])
    assert not m.passed
    assert "ambiguous" in m.detail


def test_fit_ff_sign_too_few_pulses_fails():
    m = fit_ff_sign([_pulse(0.12, 0.2)])
    assert not m.passed
    assert "1/2" in m.detail


def _ff_rows(c1: float, c2: float, *, n=300) -> list[dict]:
    rows = []
    for i in range(n):
        v = 14.0 + (i % 7) * 2.5
        kappa = 0.006 + (i % 5) * 0.003
        sign = 1 if i % 2 else -1
        ay_g = sign * v * v * kappa / 9.81
        rows.append(
            {
                "speed_kmh": v * 3.6,
                "accg_lat": ay_g,
                "steer": sign * (c1 * kappa + c2 * v * v * kappa),
            }
        )
    return rows


def test_fit_steer_ff_recovers_and_normalizes():
    m = fit_steer_ff(_ff_rows(6.0, 0.015), ff_sign=1.0)
    assert m.passed
    assert m.value["ff_c1"] == pytest.approx(6.0, rel=0.02)
    assert m.value["ff_c2"] == pytest.approx(0.015, rel=0.05)


def test_fit_steer_ff_sign_contradiction_fails():
    m = fit_steer_ff(_ff_rows(6.0, 0.015), ff_sign=-1.0)
    assert not m.passed
    assert "contradicts" in m.detail


def test_fit_steer_ff_insufficient_rows_fails():
    m = fit_steer_ff(_ff_rows(6.0, 0.015, n=20))
    assert not m.passed
    assert "rows" in m.detail


def test_fit_gear_ratios_monotonic_gate():
    good = {2: [110.0] * 30, 3: [82.0] * 30}
    m = fit_gear_ratios(good)
    assert m.passed
    bad = {2: [80.0] * 30, 3: [110.0] * 30}
    m = fit_gear_ratios(bad)
    assert not m.passed and "decreasing" in m.detail


def test_fit_gear_ratios_scatter_gate():
    noisy = {2: [110.0 + (-20.0 if i % 2 else 20.0) for i in range(40)], 3: [82.0] * 30}
    m = fit_gear_ratios(noisy)
    assert not m.passed and "scatter" in m.detail


def test_fit_shift_points_needs_two_gears():
    samples = [{"gear": 2, "rpm": 4000.0 + i, "accel_mps2": 5.0} for i in range(50)]
    m = fit_shift_points(samples, {2: 110.0, 3: 82.0})
    assert not m.passed
    assert "1 gear" in m.detail


def test_fit_shift_points_limiter_fallback():
    samples = []
    for gear, ratio in ((2, 110.0), (3, 82.0)):
        for rpm in range(3000, 8001, 100):
            samples.append(
                {"gear": gear, "rpm": float(rpm), "accel_mps2": 6.0, "speed_kmh": rpm / ratio}
            )
    m = fit_shift_points(samples, {2: 110.0, 3: 82.0})
    assert m.passed
    assert m.value["rpm_up"] <= 8000.0 * 0.98
    assert m.value["rpm_dn"] < m.value["rpm_up"] * 0.85


def test_fit_r_eff_spread_gate():
    good = [{"v_mps": 20.0, "omega": (58.8, 58.8, 58.8, 58.8)} for _ in range(30)]
    m = fit_r_eff(good)
    assert m.passed and m.value["r_eff_m"] == pytest.approx(20.0 / 58.8, abs=0.001)
    skewed = [{"v_mps": 20.0, "omega": (58.8, 58.8, 58.8, 45.0)} for _ in range(30)]
    m = fit_r_eff(skewed)
    assert not m.passed and "disagree" in m.detail


def test_fit_r_eff_empty_names_cause():
    m = fit_r_eff([])
    assert not m.passed
    assert "physics reader unavailable or coast probe never ran" in m.detail


# ---------------------------------------------------------------------------
# Straight detection
# ---------------------------------------------------------------------------
def test_find_straights_on_stadium():
    plane = [(p[0], p[2]) for p in _stadium_line()]
    straights = find_straights(plane, min_length_m=100.0)
    assert len(straights) >= 2
    assert straights[0].length_m >= 700.0
    assert straights[1].length_m >= 700.0


def test_find_straights_none_on_circle():
    plane = [
        (50.0 * math.cos(2 * math.pi * i / 200), 50.0 * math.sin(2 * math.pi * i / 200))
        for i in range(200)
    ]
    assert find_straights(plane) == []


# ---------------------------------------------------------------------------
# Artifact persistence + consumption
# ---------------------------------------------------------------------------
def _result_dict(ok=True) -> dict:
    return {
        "ok": ok,
        "car_id": "test_car",
        "track_id": "test_oval",
        "laps_used": 2,
        "duration_s": 180.0,
        "constants": {
            "ff_sign": 1.0,
            "ff_c1": 6.0,
            "ff_c2": 0.015,
            "rpm_up": 7600.0,
            "rpm_dn": 5100.0,
            "gear_ratios": {"2": 110.0, "3": 82.0},
            "r_eff_m": 0.34,
        },
        "measurements": [],
    }


def test_artifact_round_trip(tmp_path):
    path = save_plant_artifact(tmp_path, _result_dict())
    assert path == plant_artifact_path(tmp_path, "test_car", "test_oval")
    loaded = load_plant_artifact(tmp_path, "test_car", "test_oval")
    assert loaded is not None
    assert loaded["constants"]["rpm_up"] == 7600.0
    assert loaded["schema_version"] == 1


def test_artifact_refuses_failed_result(tmp_path):
    with pytest.raises(ValueError, match="failed handshake"):
        save_plant_artifact(tmp_path, _result_dict(ok=False))


def test_artifact_load_rejects_wrong_combo(tmp_path):
    save_plant_artifact(tmp_path, _result_dict())
    assert load_plant_artifact(tmp_path, "other_car", "test_oval") is None
    assert load_plant_artifact(tmp_path, "test_car", "other_track") is None


def test_artifact_load_rejects_nan_constants(tmp_path):
    result = _result_dict()
    result["constants"]["rpm_up"] = float("nan")
    path = save_plant_artifact(tmp_path, result)
    assert path.exists()
    assert load_plant_artifact(tmp_path, "test_car", "test_oval") is None


def test_plant_driver_kwargs_auto_vs_full(tmp_path):
    save_plant_artifact(tmp_path, _result_dict())
    artifact = load_plant_artifact(tmp_path, "test_car", "test_oval")
    auto = plant_driver_kwargs(artifact, steer=False)
    assert auto == {"rpm_up": 7600.0, "rpm_dn": 5100.0}
    full = plant_driver_kwargs(artifact, steer=True)
    assert full["steering_mode"] == "curvature_ff"
    assert full["ff_sign"] == 1.0
    assert full["ff_c1"] == 6.0
    assert full["ff_c2"] == 0.015


def test_apply_handshake_outcome_empty_sink():
    report = SimpleNamespace(ok=True, stage="done", error=None, notes=[])
    apply_handshake_outcome(report, {})
    assert report.ok is False
    assert report.stage == "handshake"
    assert "no result" in report.error


def test_apply_handshake_outcome_success_notes():
    report = SimpleNamespace(ok=True, stage="done", error=None, notes=[])
    sink = {"ok": True, "result": _result_dict(), "constants": _result_dict()["constants"]}
    apply_handshake_outcome(report, sink)
    assert report.ok is True
    assert report.notes and "handshake ok" in report.notes[0]
