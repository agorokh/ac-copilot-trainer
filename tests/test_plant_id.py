"""Tests for the #532 plant-ID handshake — synthetic plant with KNOWN constants, recovered.

The end-to-end tests drive :class:`HandshakeController` against a pure kinematic simulator whose
steer feedforward (``c1``/``c2``/``ff_sign``), gear ratios, limiter, and wheel radius are known,
and assert the handshake measures them back within tolerance — plus every gate's interpretable
failure path. No game, no Windows, no I/O beyond tmp_path.
"""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from tools.ac_harness.auto_drive import AutoDriveConfig, _build_driver, generic_gt3_ggv
from tools.ac_harness.ggv_profile import GGVModel, with_binned_uncertainty
from tools.ac_harness.lap_driver import PHASE_LAP, DriveFrame
from tools.ac_harness.plant_id import (
    PLANT_SCHEMA_VERSION,
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
    plant_ggv_model,
    plant_ready_for_full_consumption,
    refine_ggv_from_lap_archives,
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
        self._accel = 0.0  # last longitudinal accel (m/s^2) — for the #532 Part B friction phys
        self._kappa = 0.0  # last path curvature (1/m)

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
        # #532 Part B: also expose the accG channel (real lateral / longitudinal g) + speed so the
        # controller's friction-row sampler can build the GGV envelope. accg_lon < 0 under braking,
        # matching ggv_from_telemetry's brake = -lon convention.
        return SimpleNamespace(
            wheel_omega=(base, base, base, base),
            speed_kmh=self.speed_kmh,
            accg_lat=self.v * self.v * self._kappa / 9.81,
            accg_lon=self._accel / 9.81,
        )

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
        self._accel = accel
        self._kappa = kappa
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


def test_apply_handshake_outcome_success_only_when_reached():
    # The clobber guard lives in auto_drive._main, but apply_handshake_outcome itself must still
    # produce a "no result" outcome for an EMPTY sink (used only when the drive reached handshake).
    from types import SimpleNamespace

    report = SimpleNamespace(ok=True, stage="done", error=None, notes=[])
    apply_handshake_outcome(report, {})
    assert report.ok is False and report.stage == "handshake"


def test_aborted_sweep_attempt_samples_discarded():
    # #532 Codex: a mid-WOT abort (recovery/jump/stuck) must also discard the current attempt's
    # samples, or a later retry fits shift points from non-contiguous pulls.
    line = _stadium_line()
    ctrl = HandshakeController(line, _profile_for(line), sink={})
    ctrl._sweep_samples = [{"gear": 2, "rpm": 5000, "speed_kmh": 100, "accel_mps2": 6.0}]
    ctrl._active = {"kind": "accel_sweep", "data": {"samples_start": 0}}
    ctrl._abort_active("driver stuck mid-WOT")
    assert ctrl._sweep_samples == []  # aborted attempt's samples discarded


def test_failed_sweep_attempt_samples_discarded():
    # Two disjoint single-gear pulls must NOT combine into a fake multi-gear sweep. Simulate by
    # driving the controller and asserting fit uses only same-attempt gears — here we unit-check
    # the discard directly on the controller's sweep bookkeeping.
    line = _stadium_line()
    ctrl = HandshakeController(line, _profile_for(line), sink={})
    # First failed attempt: one gear worth of samples, samples_start=0
    ctrl._active = {"kind": "accel_sweep", "data": {"samples_start": 0}}
    ctrl._sweep_samples = [{"gear": 2, "rpm": 5000, "speed_kmh": 100, "accel_mps2": 6.0}]
    ctrl._end_sweep(1.0)
    assert ctrl._sweep_samples == []  # single-gear attempt discarded


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


def test_fit_shift_points_rejects_low_rpm_false_crossover():
    # A flat/noisy low-rpm pull where the next gear marginally out-accelerates early must NOT be
    # taken as the shift point (Codex review): it should fall back to the limiter margin, not
    # emit a low rpm_up. Two gears, next gear's accel a hair higher at LOW rpm, both flat.
    samples = []
    for rpm in range(3000, 8001, 100):
        samples.append({"gear": 2, "rpm": float(rpm), "accel_mps2": 6.0})
        samples.append({"gear": 3, "rpm": float(rpm), "accel_mps2": 6.05})  # tiny, flat advantage
    m = fit_shift_points(samples, {2: 110.0, 3: 82.0})
    assert m.passed
    # Must NOT pick a low-rpm crossover; a real shift point is high in the pull (limiter fallback).
    assert m.value["rpm_up"] > 7000.0
    assert m.method == "limiter-margin"


def test_fit_shift_points_accepts_high_rpm_real_crossover():
    # A genuine crossover: gear 2 falls off near the top while gear 3 stays strong -> accepted.
    samples = []
    for rpm in range(3000, 8001, 100):
        a2 = 8.0 if rpm < 6500 else 3.0  # gear 2 falls off past 6500
        a3 = 6.5  # gear 3 steady
        samples.append({"gear": 2, "rpm": float(rpm), "accel_mps2": a2})
        samples.append({"gear": 3, "rpm": float(rpm * 82.0 / 110.0), "accel_mps2": a3})
    m = fit_shift_points(samples, {2: 110.0, 3: 82.0})
    assert m.passed
    assert m.method == "accel-crossover"
    assert m.value["rpm_up"] >= 6000.0  # high in the pull, not a low-rpm artifact


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
    assert loaded["schema_version"] == PLANT_SCHEMA_VERSION


def test_artifact_refuses_failed_result(tmp_path):
    with pytest.raises(ValueError, match="failed handshake"):
        save_plant_artifact(tmp_path, _result_dict(ok=False))


def test_artifact_load_rejects_wrong_combo(tmp_path):
    save_plant_artifact(tmp_path, _result_dict())
    assert load_plant_artifact(tmp_path, "other_car", "test_oval") is None
    assert load_plant_artifact(tmp_path, "test_car", "other_track") is None


def test_artifact_load_rejects_partial_constants(tmp_path):
    # A persisted artifact with a MISSING required constant must be rejected (Codex review): else
    # --use-plant full silently drives on generic steering.
    result = _result_dict()
    del result["constants"]["ff_c1"]
    path = save_plant_artifact(tmp_path, result)
    assert path.exists()
    assert load_plant_artifact(tmp_path, "test_car", "test_oval") is None


def test_artifact_keyed_by_setup(tmp_path):
    # A plant measured on the default setup must NOT be loaded for a --setup run, and vice versa.
    default = _result_dict()
    save_plant_artifact(tmp_path, default)
    tuned = _result_dict()
    tuned["setup"] = "Realistic_BB_v3"
    tuned["constants"]["rpm_up"] = 8888.0
    save_plant_artifact(tmp_path, tuned)
    # default-key load gets the default plant, not the tuned one
    d = load_plant_artifact(tmp_path, "test_car", "test_oval")
    assert d is not None and d["constants"]["rpm_up"] == 7600.0
    # setup-key load gets the tuned plant
    t = load_plant_artifact(tmp_path, "test_car", "test_oval", "Realistic_BB_v3")
    assert t is not None and t["constants"]["rpm_up"] == 8888.0
    # a setup with no matching artifact loads nothing (no silent default reuse)
    assert load_plant_artifact(tmp_path, "test_car", "test_oval", "Aggressive") is None


def test_artifact_keyed_by_layout_with_legacy_none_back_compat(tmp_path):
    legacy = plant_artifact_path(tmp_path, "test_car", "test_oval")
    assert legacy.name == "test_car__test_oval.json"

    layout_a = _result_dict()
    layout_a["layout"] = "gp"
    layout_a["constants"]["rpm_up"] = 8100.0
    path_a = save_plant_artifact(tmp_path, layout_a)
    assert path_a.name == "test_car__test_oval__layout-gp.json"
    assert (
        plant_artifact_path(tmp_path, "test_car", "test_oval", "Foo", layout="gp").name
        == "test_car__test_oval__layout-gp__setup-Foo.json"
    )
    loaded_a = load_plant_artifact(tmp_path, "test_car", "test_oval", layout="gp")
    assert loaded_a is not None and loaded_a["constants"]["rpm_up"] == 8100.0

    # A missing B artifact never falls back to A. Even if an A file is copied/renamed to B's key,
    # the stored layout identity rejects it rather than driving on the wrong physical course.
    assert load_plant_artifact(tmp_path, "test_car", "test_oval", layout="short") is None
    path_b = plant_artifact_path(tmp_path, "test_car", "test_oval", layout="short")
    path_b.write_bytes(path_a.read_bytes())
    assert load_plant_artifact(tmp_path, "test_car", "test_oval", layout="short") is None

    layout_b = _result_dict()
    layout_b["layout"] = "short"
    layout_b["constants"]["rpm_up"] = 7200.0
    save_plant_artifact(tmp_path, layout_b)
    loaded_b = load_plant_artifact(tmp_path, "test_car", "test_oval", layout="short")
    assert loaded_b is not None and loaded_b["constants"]["rpm_up"] == 7200.0


def test_artifact_layout_rejects_path_shaped_id(tmp_path):
    with pytest.raises(ValueError, match="unsafe track layout"):
        plant_artifact_path(tmp_path, "test_car", "test_oval", layout="../gp")
    # The path builder is strict for writers, while the tolerant loader degrades an invalid lookup
    # to a cache miss so CLI consumers keep the generic plant.
    assert load_plant_artifact(tmp_path, "test_car", "test_oval", layout="../gp") is None


def test_artifact_load_portable_when_creator_setup_ini_unreadable(tmp_path):
    # Daemon HIGH: the load must NOT re-hash the STORED creator absolute setup_ini path (unreadable
    # on another machine). Save with an ini, then load with a DIFFERENT-path ini of the same
    # content -> must still load (content-hashed filename is the identity, not the stored path).
    creator = tmp_path / "creatorhome" / "Foo.ini"
    creator.parent.mkdir(parents=True)
    creator.write_text("[GEARS]\nFINAL=3.9\n")
    result = _result_dict()
    result["setup"] = "Foo"
    result["setup_ini"] = str(creator)
    save_plant_artifact(tmp_path, result)
    # Simulate another machine: the creator path is gone, same setup content lives elsewhere.
    creator.unlink()
    loader = tmp_path / "loaderhome" / "Foo.ini"
    loader.parent.mkdir(parents=True)
    loader.write_text("[GEARS]\nFINAL=3.9\n")  # identical content -> identical hash
    loaded = load_plant_artifact(tmp_path, "test_car", "test_oval", "Foo", str(loader))
    assert loaded is not None  # portable: found by content-hashed filename, not the stored path
    assert loaded["constants"]["rpm_up"] == 7600.0
    # different content -> different hash -> not loaded
    loader.write_text("[GEARS]\nFINAL=4.4\n")
    assert load_plant_artifact(tmp_path, "test_car", "test_oval", "Foo", str(loader)) is None


def test_setup_key_content_hash_distinguishes_same_basename(tmp_path):
    from tools.ac_harness.plant_id import _setup_key

    a = tmp_path / "a" / "Foo.ini"
    b = tmp_path / "b" / "Foo.ini"
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    a.write_text("[GEARS]\nFINAL=3.9\n")
    b.write_text("[GEARS]\nFINAL=4.4\n")  # same basename, different content
    ka = _setup_key("Foo", a)
    kb = _setup_key("Foo", b)
    assert ka != kb  # content hash disambiguates
    assert ka.startswith("__setup-Foo-") and kb.startswith("__setup-Foo-")
    # no ini -> basename-only key (best effort)
    assert _setup_key("Foo") == "__setup-Foo"


def test_handshake_set_phys_read_injection():
    # The controller does not open OS memory; the harness injects the reader (daemon review).
    line = _stadium_line()
    ctrl = HandshakeController(line, _profile_for(line), sink={}, phys_read=None)
    assert ctrl._read_phys() is None  # no reader -> None
    from types import SimpleNamespace

    ctrl.set_phys_read(lambda: SimpleNamespace(wheel_omega=(1.0, 1.0, 1.0, 1.0)))
    assert ctrl._read_phys().wheel_omega == (1.0, 1.0, 1.0, 1.0)


def test_handshake_layout_flows_through_controller_result_and_build_driver():
    line = _stadium_line()
    profile = _profile_for(line)
    ctrl = HandshakeController(line, profile, track_id="test_oval", layout="gp", sink={})
    ctrl.finalize(now=0.0)
    assert ctrl.layout == "gp"
    assert ctrl.result is not None and ctrl.result.layout == "gp"
    assert ctrl.sink["result"]["layout"] == "gp"

    built = _build_driver(
        AutoDriveConfig(
            driver="handshake",
            car_id="test_car",
            track_id="test_oval",
            track_layout="short",
            # A previously loaded optimized plant is deliberately ignored by the handshake branch;
            # its measurement prior is always the generic safety baseline (daemon rebuttal).
            plant_ggv=GGVModel(9.0, 0.5, 3.0, 0.1, 2.0, 0.0, 0.5, 1.5),
        ),
        line,
        profile,
    )
    assert isinstance(built, HandshakeController)
    assert built.layout == "short"
    assert built._prior_ggv == generic_gt3_ggv()


def test_plant_driver_kwargs_full_raises_on_missing_steering():
    from tools.ac_harness.plant_id import plant_driver_kwargs

    artifact = {"constants": {"rpm_up": 7600.0, "rpm_dn": 5100.0}}  # no ff_* keys
    with pytest.raises(ValueError, match="steering constants"):
        plant_driver_kwargs(artifact, steer=True)
    # auto mode tolerates missing steering (shift points only)
    assert plant_driver_kwargs(artifact, steer=False) == {"rpm_up": 7600.0, "rpm_dn": 5100.0}


def test_fit_shift_points_requires_adjacent_gears():
    # Only non-adjacent gears (AC 2 and 4, i.e. 1st and 3rd) observed -> no real shift step.
    samples = []
    for gear, ratio in ((2, 110.0), (4, 62.0)):
        for rpm in range(3000, 8001, 100):
            samples.append(
                {"gear": gear, "rpm": float(rpm), "accel_mps2": 6.0, "speed_kmh": rpm / ratio}
            )
    m = fit_shift_points(samples, {2: 110.0, 4: 62.0})
    assert not m.passed
    assert "ADJACENT" in m.detail or "adjacent" in m.detail


def test_fit_shift_points_fails_when_sweep_never_revs_out():
    # Two adjacent gears but the pull only reached low rpm (tall gear / early abort) -> must FAIL,
    # not persist a low rpm_up from the limiter fallback (Codex review).
    samples = []
    for gear, ratio in ((2, 110.0), (3, 82.0)):
        for rpm in range(1500, 4001, 100):  # never past ~4k
            samples.append(
                {"gear": gear, "rpm": float(rpm), "accel_mps2": 6.0, "speed_kmh": rpm / ratio}
            )
    m = fit_shift_points(samples, {2: 110.0, 3: 82.0})
    assert not m.passed
    assert "revved out" in m.detail


# ---------------------------------------------------------------------------
# #532 Part B — per-combo friction plant (GGV block)
# ---------------------------------------------------------------------------
def test_brake_probe_queued_only_with_prior():
    line = _stadium_line()
    without = HandshakeController(line, _profile_for(line), sink={})
    assert "brake_probe" not in without._pending
    with_prior = HandshakeController(line, _profile_for(line), sink={}, prior_ggv=generic_gt3_ggv())
    assert "brake_probe" in with_prior._pending
    assert with_prior.brake_probe_seconds == 2.5
    assert with_prior.brake_min_entry_kmh == 110.0
    assert with_prior.friction_row_interval_s == 0.01


def test_friction_sampler_deduplicates_physics_packets():
    line = _stadium_line()
    phys = SimpleNamespace(packet_id=7, speed_kmh=80.0, accg_lat=0.2, accg_lon=-1.0)
    ctrl = HandshakeController(
        line,
        _profile_for(line),
        sink={},
        prior_ggv=generic_gt3_ggv(),
        phys_read=lambda: phys,
    )
    ctrl._mine_friction(0.0)
    ctrl._mine_friction(0.02)
    assert len(ctrl._friction_rows) == 1
    phys.packet_id = 8
    ctrl._mine_friction(0.04)
    assert len(ctrl._friction_rows) == 2


def test_brake_probe_requires_speed_dependent_stopping_room():
    line = _stadium_line()
    ctrl = HandshakeController(line, _profile_for(line), sink={}, prior_ggv=generic_gt3_ggv())
    assert ctrl._brake_probe_required_m(110.0) > 100.0
    ctrl._pending.remove("brake_probe")
    ctrl._active = {"kind": "brake_probe", "stage": "prep", "t_stage": 0.0, "data": {}}
    base = DriveFrame(0.5, 0.0, 0.0, False, False, PHASE_LAP, False, False)
    assert ctrl._step_brake(base, 110.0, 100.0, 0.0) is base
    assert ctrl._active is None
    assert "brake_probe" in ctrl._pending


def test_handshake_no_ggv_block_without_prior(handshake_outcome):
    # The module fixture runs WITHOUT a prior -> no ggv block, and it never captured friction rows.
    ctrl, sink = handshake_outcome
    assert ctrl.result.ggv is None
    assert sink["result"]["ggv"] is None
    assert ctrl.result_diagnostics["friction_rows"] == 0


def test_handshake_emits_provisional_ggv_until_thermal_archive_arrives():
    line = _stadium_line()
    sim = PlantSim(line)
    prior = generic_gt3_ggv()
    sink: dict = {}
    ctrl = HandshakeController(
        line,
        _profile_for(line),
        car_id="test_car",
        track_id="test_oval",
        sink=sink,
        phys_read=sim.phys,
        prior_ggv=prior,
    )
    _run_handshake(ctrl, sim)
    assert ctrl.finished
    ggv = ctrl.result.ggv
    assert ggv is not None and ggv["ok"] is False, ggv
    assert ctrl.result_diagnostics["friction_rows"] >= ctrl.min_friction_rows
    assert ggv["reason"] == "awaiting thermally tagged lap archive"
    model = GGVModel.from_dict(ggv["provisional_model"])
    # Safe-envelope guarantees: lateral pinned to the prior (a conservative drive under-measures the
    # limit, so it never lowers/regresses), aero-lateral stays 0, caps kept.
    assert model.k_aero_lat == 0.0
    assert model.mu_lat_g == prior.mu_lat_g
    assert model.provenance["blend_source"]["lateral"] == "prior"
    assert model.ay_cap_g == prior.ay_cap_g
    assert model.ax_brake_cap_g == prior.ax_brake_cap_g
    # Provenance labels each curve measured-vs-prior.
    assert set(model.provenance["blend_source"]) == {"lateral", "brake", "drive", "ellipse_n"}
    assert ggv["provisional_probe_rows"]
    assert all(
        row["source"] in {"brake_probe", "accel_sweep"} for row in ggv["provisional_probe_rows"]
    )
    # The ggv block is ADVISORY — it never gates the core-constant ok.
    assert sink["result"]["ggv"]["ok"] is False


def test_uncertainty_handshake_waits_for_clean_post_probe_thermal_lap():
    line = _stadium_line()
    ctrl = HandshakeController(
        line,
        _profile_for(line),
        prior_ggv=generic_gt3_ggv(),
        min_corner_rows=0,
    )
    ctrl._pending.clear()

    def frame(*, lap_completed: bool) -> DriveFrame:
        return DriveFrame(0.2, 0.0, 0.0, False, False, PHASE_LAP, lap_completed, False)

    ctrl._base.step = lambda *args: frame(lap_completed=False)
    ctrl.step((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, 0.0)
    assert ctrl.finished is False
    assert ctrl._laps == 0

    ctrl._base.step = lambda *args: frame(lap_completed=True)
    ctrl.step((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, 1.0)
    assert ctrl.finished is False
    assert ctrl._laps == 1

    ctrl.step((2.0, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, 2.0)
    assert ctrl.finished is True
    assert ctrl.result is not None and ctrl.result.laps_used == 2


def test_uncertainty_handshake_uses_ac_completed_laps_over_false_line_wraps():
    line = _stadium_line()
    completed = {"value": 0}
    ctrl = HandshakeController(
        line,
        _profile_for(line),
        prior_ggv=generic_gt3_ggv(),
        min_corner_rows=0,
        phys_read=lambda: SimpleNamespace(completed_laps=completed["value"]),
    )
    ctrl._pending.clear()
    ctrl._base.step = lambda *args: DriveFrame(0.2, 0.0, 0.0, False, False, PHASE_LAP, True, False)

    for now in (0.0, 1.0, 2.0):
        ctrl.step((now, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, now)
    assert ctrl.finished is False
    assert ctrl._uses_completed_laps is True
    assert ctrl._laps == 0

    completed["value"] = 1
    ctrl.step((3.0, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, 3.0)
    assert ctrl.finished is False
    assert ctrl._laps == 1

    completed["value"] = 2
    ctrl.step((4.0, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, 4.0)
    assert ctrl.finished is True
    assert ctrl.result is not None and ctrl.result.laps_used == 2


def test_uncertainty_handshake_late_graphics_counter_preserves_fallback_laps():
    line = _stadium_line()
    physics = {"frame": SimpleNamespace(completed_laps=None)}
    ctrl = HandshakeController(
        line,
        _profile_for(line),
        prior_ggv=generic_gt3_ggv(),
        min_corner_rows=0,
        phys_read=lambda: physics["frame"],
    )
    ctrl._pending.clear()
    ctrl._base.step = lambda *args: DriveFrame(0.2, 0.0, 0.0, False, False, PHASE_LAP, True, False)

    ctrl.step((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, 0.0)
    assert ctrl._laps == 1
    physics["frame"] = SimpleNamespace(completed_laps=7)
    ctrl.step((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, 1.0)
    assert ctrl._uses_completed_laps is True
    assert ctrl._laps == 1
    physics["frame"] = SimpleNamespace(completed_laps=8)
    ctrl.step((2.0, 0.0, 0.0), (1.0, 0.0, 0.0), 60.0, 5000.0, 3, 2.0)
    assert ctrl._laps == 2


def test_handshake_preserves_probe_rows_before_overall_friction_row_gate():
    line = _stadium_line()
    ctrl = HandshakeController(line, _profile_for(line), prior_ggv=generic_gt3_ggv())
    ctrl._friction_rows = [
        {
            "speed_kmh": 60.0,
            "accg_lat": 0.0,
            "accg_lon": -1.1,
            "source": "brake_probe",
            "lap_number": 1,
        }
        for _ in range(8)
    ]
    block = ctrl._build_ggv_block()
    assert block is not None
    assert "insufficient friction rows" in block["reason"]
    assert len(block["provisional_probe_rows"]) == 8


def _uncertain_prior() -> GGVModel:
    prior = generic_gt3_ggv()
    rows = []
    for speed in range(50, 151, 10):
        for _ in range(50):
            rows.append(
                {
                    "speed_kmh": float(speed),
                    "accg_lat": 1.2,
                    "accg_lon": -1.2,
                    "source": "brake_probe",
                }
            )
    return with_binned_uncertainty(prior, rows, prior)


def test_plant_ggv_model_resolves_valid_rejects_invalid():
    prior = generic_gt3_ggv()
    good = {"ggv": {"ok": True, "model": _uncertain_prior().to_dict()}}
    assert plant_ggv_model(good) is not None
    assert plant_ggv_model({"ggv": {"ok": True, "model": prior.to_dict()}}) is None
    # ok=False block -> None (consumer keeps generic)
    assert plant_ggv_model({"ggv": {"ok": False, "model": None}}) is None
    # non-finite serialized model -> rejected (never act on a nan grip curve)
    assert plant_ggv_model({"ggv": {"ok": True, "model": {"mu_lat_g": float("nan")}}}) is None
    # v1 / Part-A artifact with no ggv block -> None
    assert plant_ggv_model({"constants": {"ff_sign": 1.0}}) is None


def test_refine_ggv_without_thermal_archive_stays_non_runtime():
    result = _result_dict()
    result["ggv"] = {"ok": False, "reason": "awaiting thermally tagged lap archive"}
    block = refine_ggv_from_lap_archives(result, [], generic_gt3_ggv())
    assert block["ok"] is False
    assert block["model"] is None
    assert "no thermally consistent" in block["reason"]
    assert plant_ggv_model({"ggv": block}) is None


def test_refine_ggv_respects_explicit_friction_id_opt_out():
    result = _result_dict()
    block = refine_ggv_from_lap_archives(result, [], generic_gt3_ggv())
    assert block["skipped"] is True
    assert "not requested" in block["reason"]
    assert "ggv" not in result


def test_refine_ggv_rejects_stale_other_combo_archive():
    result = _result_dict()
    result["ggv"] = {"ok": False, "reason": "awaiting thermally tagged lap archive"}
    stale = {
        "car": {"id": "other_car"},
        "track": {"id": "test_oval", "layout": None},
        "lap_uuid": "stale",
    }
    block = refine_ggv_from_lap_archives(result, [stale], generic_gt3_ggv())
    assert block["ok"] is False
    assert block["lap_archives_seen"] == 1
    assert block["lap_archives_loaded"] == 0
    assert any("identity mismatch" in error for error in block["load_errors"])


def test_refine_ggv_accepts_current_run_archive_when_writer_omits_layout():
    result = _result_dict()
    result["ggv"] = {"ok": False, "reason": "awaiting thermally tagged lap archive"}
    result["layout"] = "gp"
    archive = {
        "car": {"id": "test_car"},
        "track": {"id": "test_oval"},
        "lap_uuid": "fresh-layout-run",
    }
    block = refine_ggv_from_lap_archives(
        result, [archive], generic_gt3_ggv(), archives_same_run=True
    )
    assert block["ok"] is False  # no thermal trace, but identity was accepted
    assert block["lap_archives_loaded"] == 1
    assert block["load_errors"] == []
    assert any("omitted layout" in note for note in block["identity_notes"])

    result = _result_dict()
    result["ggv"] = {"ok": False, "reason": "awaiting thermally tagged lap archive"}
    result["layout"] = "gp"
    block = refine_ggv_from_lap_archives(result, [archive], generic_gt3_ggv())
    assert block["lap_archives_loaded"] == 0
    assert any("outside current-run scope" in error for error in block["load_errors"])


def test_refine_ggv_offline_rejects_wrong_or_unidentified_setup_archive():
    result = _result_dict()
    result["setup"] = "requested.ini"
    result["ggv"] = {"ok": False, "reason": "awaiting thermally tagged lap archive"}
    wrong = {
        "car": {"id": "test_car"},
        "track": {"id": "test_oval"},
        "setup": {"path": "other.ini", "hash": "abc", "snapshot": {"path": "other.ini"}},
        "lap_uuid": "wrong-setup",
    }
    block = refine_ggv_from_lap_archives(result, [wrong], generic_gt3_ggv())
    assert block["lap_archives_loaded"] == 0
    assert any("setup mismatch" in error for error in block["load_errors"])


def test_artifact_v1_still_loads_without_ggv(tmp_path):
    # A v1 Part-A artifact (schema_version=1, no ggv block) must still load after the v2 bump so
    # existing shift-point / steering consumption is not invalidated (back-compat).
    import json as _json

    result = _result_dict()
    payload = {"schema_version": 1, "created_utc": "2026-07-12T00:00:00Z", **result}
    path = plant_artifact_path(tmp_path, "test_car", "test_oval")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(payload), encoding="utf-8")
    loaded = load_plant_artifact(tmp_path, "test_car", "test_oval")
    assert loaded is not None
    assert loaded["schema_version"] == 1
    assert plant_ggv_model(loaded) is None  # no ggv block -> generic plant


def test_artifact_v2_constants_load_but_point_ggv_falls_back_to_generic(tmp_path):
    import json as _json

    result = _result_dict()
    result["ggv"] = {"ok": True, "model": generic_gt3_ggv().to_dict()}
    payload = {"schema_version": 2, "created_utc": "2026-07-12T00:00:00Z", **result}
    path = plant_artifact_path(tmp_path, "test_car", "test_oval")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(payload), encoding="utf-8")
    loaded = load_plant_artifact(tmp_path, "test_car", "test_oval")
    assert loaded is not None
    assert loaded["schema_version"] == 2
    assert loaded["constants"]["rpm_up"] == 7600.0
    assert plant_ggv_model(loaded) is None


def test_schema_v3_artifact_refuses_point_estimate_ggv(tmp_path):
    result = _result_dict()
    result["ggv"] = {"ok": True, "model": generic_gt3_ggv().to_dict()}
    with pytest.raises(ValueError, match="without uncertainty bins"):
        save_plant_artifact(tmp_path, result)


def test_ggv_block_round_trips_through_artifact(tmp_path):
    prior = generic_gt3_ggv()
    result = _result_dict()
    result["ggv"] = {"ok": True, "friction_rows": 1234, "model": _uncertain_prior().to_dict()}
    save_plant_artifact(tmp_path, result)
    loaded = load_plant_artifact(tmp_path, "test_car", "test_oval")
    assert loaded is not None
    assert loaded["schema_version"] == PLANT_SCHEMA_VERSION
    model = plant_ggv_model(loaded)
    assert model is not None
    assert abs(model.mu_lat_g - prior.mu_lat_g) < 1e-9
    assert model.uncertainty_aware


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


def test_plant_ready_for_full_consumption_shared_gate(tmp_path):
    # The single readiness gate shared by the alien resolution, the alien preflight, and
    # auto_alien.needs_identification (#572 daemon review) — the three sites must see the
    # identical verdict for the identical artifact.
    assert "no plant artifact" in plant_ready_for_full_consumption(None, require_friction_fit=True)
    save_plant_artifact(tmp_path, _result_dict())
    artifact = load_plant_artifact(tmp_path, "test_car", "test_oval")
    # Complete measured constants, no friction fit: ggv `--use-plant full` semantics pass...
    assert plant_ready_for_full_consumption(artifact, require_friction_fit=False) is None
    # ...but the alien path additionally demands the #543 uncertainty-aware fit.
    assert "uncertainty-aware" in plant_ready_for_full_consumption(
        artifact, require_friction_fit=True
    )
    # Incomplete steering constants fail regardless of the fit requirement.
    broken = dict(artifact)
    broken["constants"] = {k: v for k, v in artifact["constants"].items() if k not in ("ff_c1",)}
    assert "steering constants" in plant_ready_for_full_consumption(
        broken, require_friction_fit=False
    )


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


# --------------------------------------------------------------------------- #577 self-play refine
def _selfplay_thermal_archive(lap_uuid: str, *, lateral_g: float = 1.3, lap_n: int = 1) -> dict:
    """A fit-eligible lap archive for the pipeline's own combo (test_car/test_oval)."""
    from tools.ac_harness.reference_lap import TRACE_FIELDS

    fields = list(TRACE_FIELDS)
    samples = []
    for i in range(600):
        values = dict.fromkeys(fields, 0.0)
        speed = 50.0 + float((i // 50) % 11) * 10.0
        braking = i % 2 == 0
        values.update(
            {
                "spline": i / 600.0,
                "speed": speed,
                "eMs": i * 10.0,
                "brake": 0.8 if braking else 0.0,
                "throttle": 0.0 if braking else 1.0,
                "accG_lat": lateral_g,
                "accG_long": -1.25 if braking else 0.75,
            }
        )
        for wheel in ("fl", "fr", "rl", "rr"):
            values[f"tyreCoreTemp_{wheel}"] = 90.0
            values[f"tyreTempInner_{wheel}"] = 92.0
            values[f"tyreTempMid_{wheel}"] = 90.0
            values[f"tyreTempOuter_{wheel}"] = 88.0
            values[f"wheelsPressure_{wheel}"] = 27.0
            values[f"dy_{wheel}"] = 1.5
        samples.append([values[field] for field in fields])
    return {
        "schema_version": 1,
        "source": "in_game",
        "lap_uuid": lap_uuid,
        "car": {"id": "test_car"},
        "track": {"id": "test_oval", "layout": None},
        "lap": {"lap_n": lap_n, "lap_ms": 90000, "is_valid": True},
        "setup": {"hash": "setup-a"},
        "tyres": {"compoundIndex": 1, "name": "M", "optimalTempC": 90.0},
        "trace": {"fields": fields, "samples": samples, "samples_count": len(samples)},
    }


def _selfplay_artifact() -> dict:
    artifact = _result_dict()
    artifact["schema_version"] = PLANT_SCHEMA_VERSION
    artifact["created_utc"] = "2026-07-01T00:00:00Z"
    artifact["ggv"] = {"ok": True, "model": _uncertain_prior().to_dict(), "reason": "ok"}
    return artifact


def test_selfplay_refine_requires_current_fit_and_archives():
    from tools.ac_harness.plant_id import selfplay_refine_result

    no_fit = _result_dict()
    result, block = selfplay_refine_result(no_fit, [], generic_gt3_ggv())
    assert result is None and "#543" in block["reason"]

    result, block = selfplay_refine_result(_selfplay_artifact(), [], generic_gt3_ggv())
    assert result is None  # batch refit degraded -> keep last valid, reason named
    assert block["ok"] is False
    assert "no thermally consistent" in block["reason"]


def test_selfplay_refine_reports_which_thermal_term_emptied_the_cohort():
    """#749: a refused refit must name the failing term per lap, not just the symptom.

    Reproduces the 2026-08-10 huracan@spa stall shape: every lap AC-valid with a real setup
    identity and full sample coverage, but core temperatures swinging so the per-wheel stability
    fraction falls under the 0.80 floor. Before this, the block carried only "no thermally
    consistent valid lap archives" and the operator had to re-run the observer over the archives
    by hand to learn which of the seven terms rejected them — while the ladder silently stopped
    compounding.
    """
    from tools.ac_harness.plant_id import selfplay_refine_result

    artifact = _selfplay_artifact()
    archives = [
        _selfplay_thermal_archive("unstable-1", lateral_g=1.35, lap_n=1),
        _selfplay_thermal_archive("unstable-2", lateral_g=1.35, lap_n=2),
    ]
    # Swing each wheel far from its own median for most of the lap: stability collapses while
    # coverage, compound identity, setup identity and lap validity all still pass.
    for archive in archives:
        index = {name: i for i, name in enumerate(archive["trace"]["fields"])}
        for n, sample in enumerate(archive["trace"]["samples"]):
            for wheel in ("fl", "fr", "rl", "rr"):
                sample[index[f"tyreCoreTemp_{wheel}"]] = 90.0 + (12.0 if n % 2 else -12.0)

    result, block = selfplay_refine_result(artifact, archives, generic_gt3_ggv())
    assert result is None and block["ok"] is False
    assert "no thermally consistent valid lap archives" in block["reason"]

    report = block["thermal_eligibility"]
    assert report["eligible_count"] == 0
    assert report["dominant_count"] == 2
    # The INDIVIDUAL predicate must be named. `observe_lap_tyre_state`'s own reason collapses
    # coverage / stability / wheel-spread / validity / unknown-tag into one string, so counting
    # that would report a low-coverage batch identically to this stability stall (#749 Codex P2).
    assert report["dominant_terms"] == ["stability_below_min"]
    assert report["failing_term_counts"] == {"stability_below_min": 2}
    # The thresholds are reported alongside the measurements, so the gap is readable in place.
    assert report["thresholds"]["min_stability_fraction"] == 0.80
    for lap in report["laps"]:
        assert lap["fit_eligible"] is False
        assert lap["failing_terms"] == ["stability_below_min"]
        assert lap["thermal_stability_fraction"] < 0.80
        # …and the terms that PASSED are shown too, so they need not be re-derived by hand.
        assert lap["sample_coverage_fraction"] == 1.0
        assert lap["setup_hash"]
        assert lap["lap_n"] in (1, 2)


def test_thermal_eligibility_distinguishes_coverage_from_stability_failures():
    """Distinct terms must not collapse into one dominant reason (#749 Codex P2).

    `observe_lap_tyre_state` returns the same `outside thermal stability/validity gate` string
    for coverage, stability, wheel-spread, validity and unknown-tag failures. If the report
    counted that, a low-coverage batch would be indistinguishable from a stability stall — and
    they demand different fixes.
    """
    from tools.ac_harness.plant_id import selfplay_refine_result

    def _blank_coverage(archive: dict) -> dict:
        index = {name: i for i, name in enumerate(archive["trace"]["fields"])}
        for sample in archive["trace"]["samples"][:400]:
            for wheel in ("fl", "fr", "rl", "rr"):
                sample[index[f"tyreCoreTemp_{wheel}"]] = 0.0
        return archive

    archives = [
        _blank_coverage(_selfplay_thermal_archive("low-coverage-1", lateral_g=1.35, lap_n=1)),
        _blank_coverage(_selfplay_thermal_archive("low-coverage-2", lateral_g=1.35, lap_n=2)),
    ]
    _, block = selfplay_refine_result(_selfplay_artifact(), archives, generic_gt3_ggv())
    assert block["ok"] is False
    report = block["thermal_eligibility"]
    assert report["eligible_count"] == 0
    # Named as coverage, NOT as the stability stall — the two are now separable.
    assert "coverage_below_min" in report["failing_term_counts"]
    assert "stability_below_min" not in report["dominant_terms"]
    for lap in report["laps"]:
        assert "coverage_below_min" in lap["failing_terms"]


def test_thermal_eligibility_keeps_early_observer_reasons_and_reports_ties():
    """Two ways the diagnostic could mislead, both closed (#749 Codex P2, round 3).

    1. An early observer failure (missing trace) returns ZEROED measurements, so re-deriving
       predicates from them would invent coverage + stability + tag + spread failures for what is
       really one cause. The observer's own reason is authoritative there.
    2. A tie between two causes must report BOTH — one low-coverage lap and one unstable lap is a
       different situation from two unstable laps, and naming one sends the reader the wrong way.
    """
    from tools.ac_harness.plant_id import selfplay_refine_result

    # 1. Missing trace on both laps.
    blind = [
        _selfplay_thermal_archive("no-trace-1", lateral_g=1.35, lap_n=1),
        _selfplay_thermal_archive("no-trace-2", lateral_g=1.35, lap_n=2),
    ]
    for archive in blind:
        archive["trace"] = {}
    _, block = selfplay_refine_result(_selfplay_artifact(), blind, generic_gt3_ggv())
    report = block["thermal_eligibility"]
    for lap in report["laps"]:
        assert lap["failing_terms"] == ["observer:missing trace"]
        assert "coverage_below_min" not in lap["failing_terms"]
        assert "stability_below_min" not in lap["failing_terms"]

    # 2. One low-coverage lap and one unstable lap -> a genuine 1-1 tie.
    mixed = [
        _selfplay_thermal_archive("tie-coverage", lateral_g=1.35, lap_n=1),
        _selfplay_thermal_archive("tie-stability", lateral_g=1.35, lap_n=2),
    ]
    cov_index = {name: i for i, name in enumerate(mixed[0]["trace"]["fields"])}
    for sample in mixed[0]["trace"]["samples"][:400]:
        for wheel in ("fl", "fr", "rl", "rr"):
            sample[cov_index[f"tyreCoreTemp_{wheel}"]] = 0.0
    stab_index = {name: i for i, name in enumerate(mixed[1]["trace"]["fields"])}
    for n, sample in enumerate(mixed[1]["trace"]["samples"]):
        for wheel in ("fl", "fr", "rl", "rr"):
            sample[stab_index[f"tyreCoreTemp_{wheel}"]] = 90.0 + (12.0 if n % 2 else -12.0)

    _, block = selfplay_refine_result(_selfplay_artifact(), mixed, generic_gt3_ggv())
    report = block["thermal_eligibility"]
    assert report["eligible_count"] == 0
    assert report["dominant_count"] == 1
    assert "coverage_below_min" in report["dominant_terms"]
    assert "stability_below_min" in report["dominant_terms"]


def test_thermal_eligibility_reports_identity_and_measured_failures_together():
    """An identity failure must not hide a co-occurring measured one (#749 Codex P2, round 4).

    `observe_lap_tyre_state`'s reason names only the first term its conjunction tripped, so a lap
    missing setup identity that ALSO fails stability reported identity alone — and fixing identity
    would then surface stability with no warning. The measurements are valid whenever the
    conjunction was reached, so every failing predicate is reported.
    """
    from tools.ac_harness.plant_id import selfplay_refine_result

    archives = [
        _selfplay_thermal_archive("identity-and-stability", lateral_g=1.35, lap_n=1),
        _selfplay_thermal_archive("identity-and-stability-2", lateral_g=1.35, lap_n=2),
    ]
    for archive in archives:
        archive["setup"] = {}  # strip setup identity
        index = {name: i for i, name in enumerate(archive["trace"]["fields"])}
        for n, sample in enumerate(archive["trace"]["samples"]):
            for wheel in ("fl", "fr", "rl", "rr"):
                sample[index[f"tyreCoreTemp_{wheel}"]] = 90.0 + (12.0 if n % 2 else -12.0)

    _, block = selfplay_refine_result(_selfplay_artifact(), archives, generic_gt3_ggv())
    report = block["thermal_eligibility"]
    assert report["eligible_count"] == 0
    for lap in report["laps"]:
        assert "missing_setup_identity" in lap["failing_terms"]
        # …and the measured failure is NOT hidden behind it.
        assert "stability_below_min" in lap["failing_terms"]


def test_selfplay_refine_merges_monotonically_and_strips_stale_meta(tmp_path):
    from tools.ac_harness.ggv_profile import GGVModel as _GGV
    from tools.ac_harness.plant_id import selfplay_refine_result

    artifact = _selfplay_artifact()
    current = plant_ggv_model(artifact)
    archives = [
        _selfplay_thermal_archive("sp-1", lateral_g=1.35, lap_n=1),
        _selfplay_thermal_archive("sp-2", lateral_g=1.35, lap_n=2),
    ]
    result, block = selfplay_refine_result(artifact, archives, generic_gt3_ggv())
    assert result is not None
    assert block["ok"] is True
    assert "selfplay_merge" in block
    # Stale identity meta is stripped so save_plant_artifact stamps fresh values.
    assert "schema_version" not in result and "created_utc" not in result
    merged = _GGV.from_dict(result["ggv"]["model"])
    assert merged.uncertainty_aware
    for cur_bin, new_bin in zip(current.uncertainty_bins, merged.uncertainty_bins, strict=True):
        assert new_bin["lateral"]["safe_g"] >= cur_bin["lateral"]["safe_g"]
        assert dict(new_bin["brake"]) == dict(cur_bin["brake"])
    # The refined result persists through the SAME artifact gate every plant rides.
    path = save_plant_artifact(tmp_path, result)
    reloaded = load_plant_artifact(tmp_path, "test_car", "test_oval")
    assert reloaded is not None
    assert plant_ggv_model(reloaded) is not None
    assert reloaded["ggv"]["selfplay_merge"] == block["selfplay_merge"]
    assert path.exists()
    # The original artifact object was never mutated (deep-copied inside).
    assert artifact["ggv"]["reason"] == "ok"


def test_selfplay_refine_owns_the_caller_resolved_setup_identity(tmp_path):
    from tools.ac_harness.plant_id import selfplay_refine_result

    setup_ini = tmp_path / "moved-setup.ini"
    setup_ini.write_text("[GEARS]\nFINAL=3.4\n", encoding="utf-8")
    artifact = _selfplay_artifact()
    artifact["setup"] = "moved-setup"
    artifact["setup_ini"] = "C:/old-host/creator-path.ini"
    archives = [
        _selfplay_thermal_archive("sp-identity-1", lateral_g=1.35, lap_n=1),
        _selfplay_thermal_archive("sp-identity-2", lateral_g=1.35, lap_n=2),
    ]
    result, block = selfplay_refine_result(
        artifact,
        archives,
        generic_gt3_ggv(),
        setup_ini=setup_ini,
    )
    assert block["ok"] is True and result is not None
    assert result["setup_ini"] == str(setup_ini)
    assert artifact["setup_ini"] == "C:/old-host/creator-path.ini"


def test_selfplay_persist_and_revert_are_peer_safe(monkeypatch, tmp_path):
    from tools.ac_harness import rig_lock
    from tools.ac_harness.plant_id import persist_selfplay_refinement, revert_plant_artifact

    monkeypatch.setattr(
        rig_lock,
        "default_rig_session_lock_path",
        lambda: tmp_path / "state" / "rig-session.lock",
    )
    artifact = _selfplay_artifact()
    path = save_plant_artifact(tmp_path, artifact)
    previous_bytes = path.read_bytes()
    candidate = load_plant_artifact(tmp_path, "test_car", "test_oval")
    assert candidate is not None
    candidate.pop("schema_version", None)
    candidate.pop("created_utc", None)
    candidate["ggv"]["reason"] = "ok (self-play test candidate)"

    saved, candidate_bytes, skipped = persist_selfplay_refinement(
        tmp_path,
        candidate,
        expected_path=path,
        expected_current_bytes=previous_bytes,
    )
    assert saved == path and candidate_bytes == path.read_bytes() and skipped is None
    assert revert_plant_artifact(
        path,
        previous_bytes,
        expected_current_bytes=candidate_bytes,
        car_id="test_car",
        track_id="test_oval",
    )
    assert path.read_bytes() == previous_bytes

    path.write_text('{"peer": true}', encoding="utf-8")
    saved, candidate_bytes, skipped = persist_selfplay_refinement(
        tmp_path,
        candidate,
        expected_path=path,
        expected_current_bytes=previous_bytes,
    )
    assert saved is None and candidate_bytes is None
    assert "changed between load and save" in str(skipped)
    assert path.read_text(encoding="utf-8") == '{"peer": true}'


def test_selfplay_persist_keeps_resolved_path_when_setup_becomes_unreadable(monkeypatch, tmp_path):
    from tools.ac_harness import rig_lock
    from tools.ac_harness.plant_id import persist_selfplay_refinement

    monkeypatch.setattr(
        rig_lock,
        "default_rig_session_lock_path",
        lambda: tmp_path / "state" / "rig-session.lock",
    )
    setup_ini = tmp_path / "race-setup.ini"
    setup_ini.write_text("[GEARS]\nFINAL=3.4\n", encoding="utf-8")
    artifact = _selfplay_artifact()
    artifact["setup"] = "race-setup"
    artifact["setup_ini"] = str(setup_ini)
    path = save_plant_artifact(tmp_path, artifact)
    previous_bytes = path.read_bytes()
    candidate = json.loads(previous_bytes)
    candidate["ggv"]["reason"] = "ok (self-play setup-race candidate)"

    # The driven identity was resolved while the setup was readable. Persistence must not derive
    # a different, unhashed filename if that same file disappears before the conditional write.
    setup_ini.unlink()
    saved, candidate_bytes, skipped = persist_selfplay_refinement(
        tmp_path,
        candidate,
        expected_path=path,
        expected_current_bytes=previous_bytes,
    )
    assert saved == path and candidate_bytes == path.read_bytes() and skipped is None
    assert path.exists()
    assert not (tmp_path / "plant_id" / "test_car__test_oval__setup-race-setup.json").exists()
