"""EPIC #529 / #674 Layer-4 stint optimizer — offline, no rig."""

from __future__ import annotations

import math

import pytest

from tools.ac_harness.auto_drive import generic_gt3_ggv
from tools.ac_harness.corner_refine import L3Params, refine_profile
from tools.ac_harness.env_observer import EnvironmentState
from tools.ac_harness.ggv_profile import with_binned_uncertainty
from tools.ac_harness.stint_optimizer import (
    StintInputs,
    StintOptimizerError,
    inner_loop_inputs,
    plan_stint,
)


def _uncertain_model():
    prior = generic_gt3_ggv()
    rows = []
    for speed in range(50, 151, 10):
        for _ in range(40):
            rows.append(
                {
                    "speed_kmh": float(speed),
                    "accg_lat": 1.2,
                    "accg_lon": -1.2,
                    "source": "brake_probe",
                }
            )
    return with_binned_uncertainty(prior, rows, prior)


def _plant(*, core_temp_c: float = 90.0, with_cohort: bool = True) -> dict:
    model = _uncertain_model()
    ggv: dict = {"ok": True, "model": model.to_dict()}
    if with_cohort:
        ggv["thermal_cohort"] = {
            "core_temp_c": core_temp_c,
            "pressure_psi": 27.0,
            "core_tolerance_c": 5.0,
            "pressure_tolerance_psi": 2.0,
            "compound": 1,
            "setup_hash": "setup-a",
            "thermal_tag": "optimal",
        }
    return {
        "schema_version": 3,
        "ok": True,
        "car_id": "car_a",
        "track_id": "track_a",
        "layout": None,
        "setup": "race",
        "constants": {
            "ff_sign": 1.0,
            "ff_c1": 0.5,
            "ff_c2": 0.0,
            "rpm_up": 7000.0,
            "rpm_dn": 5000.0,
            "gear_ratios": {"2": 3.0, "3": 2.0, "4": 1.5},
            "r_eff_m": 0.32,
        },
        "ggv": ggv,
    }


def test_plan_emits_deterministic_thermal_fuel_wear_targets() -> None:
    plan = plan_stint(
        StintInputs(
            plant_artifact=_plant(core_temp_c=90.0),
            environment=None,
            laps_remaining=8,
            fuel_start_l=30.0,
            fuel_burn_l_per_lap=2.0,
            wear_budget_fraction=0.35,
        )
    )
    assert plan.schema_version == 1
    assert plan.pace_scale == 1.0
    assert plan.degraded is False
    assert plan.target_thermal_window_c == (85.0, 95.0)
    assert plan.projected_fuel_end_l == pytest.approx(14.0)
    assert plan.fuel_target_l == pytest.approx(14.0)
    knobs = inner_loop_inputs(plan)
    assert knobs["ggv_scale"] == 1.0
    assert isinstance(knobs["l3_params"], L3Params)


def test_nonstationary_environment_and_missing_cohort_degrade() -> None:
    env = EnvironmentState(
        n_laps=3,
        track_grip_mean=0.8,
        track_grip_std=0.12,
        nonstationary=True,
        reason="grip_std=0.120>=0.080",
        reidentify_recommended=True,
        evidence_lap_uuids=("a", "b", "c"),
    )
    degraded = plan_stint(
        StintInputs(
            plant_artifact=_plant(with_cohort=False),
            environment=env,
            laps_remaining=5,
            fuel_start_l=8.0,
            fuel_burn_l_per_lap=2.5,
            wear_budget_fraction=0.1,
        )
    )
    assert degraded.degraded is True
    assert degraded.pace_scale < 1.0
    assert degraded.pace_scale >= 0.85
    assert "missing_thermal_cohort" in degraded.reasons
    assert any("grip_std" in reason for reason in degraded.reasons)
    assert degraded.l3_params is not None
    assert degraded.l3_params["z_ladder"] == [1.0]


def test_unusable_plant_fails_loud() -> None:
    with pytest.raises(StintOptimizerError, match="stint_plant_unusable"):
        plan_stint(
            StintInputs(
                plant_artifact={"ok": True, "ggv": {"ok": False}},
                environment=None,
                laps_remaining=1,
            )
        )
    with pytest.raises(StintOptimizerError, match="stint_laps_remaining_invalid"):
        plan_stint(StintInputs(plant_artifact=_plant(), environment=None, laps_remaining=0))


def test_inner_loop_knobs_feed_refine_profile() -> None:
    plan = plan_stint(
        StintInputs(
            plant_artifact=_plant(),
            environment=EnvironmentState(
                n_laps=2,
                nonstationary=True,
                reason="thermal_delta_c=10.00>=8.00",
                reidentify_recommended=True,
            ),
            laps_remaining=3,
        )
    )
    knobs = inner_loop_inputs(plan)
    ggv = _uncertain_model()
    # Tiny cyclic track: straight + corner + straight.
    n = 12
    seg = [10.0] * n
    kappa = [0.0] * 3 + [0.02] * 6 + [0.0] * 3
    v_qss = [40.0] * n
    params = knobs["l3_params"]
    assert params is not None
    refined, report = refine_profile(seg, kappa, v_qss, ggv, params, v_top_ms=60.0)
    assert len(refined) == n
    assert report["schema_version"] == 1
    assert all(math.isfinite(v) and v > 0 for v in refined)
