"""Layer-4 stint-level optimizer (EPIC #529 / issue #674).

Slow-timescale planner that consumes thermally tagged plant fits and a Layer-0 environment
estimate, then emits targets the QSS+L3 inner loop can consume (pace scale, optional tighter
:class:`~tools.ac_harness.corner_refine.L3Params`). Never mutates the plant GGV model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from tools.ac_harness.corner_refine import L3Params
from tools.ac_harness.env_observer import EnvironmentState
from tools.ac_harness.plant_id import plant_ggv_model, plant_ready_for_full_consumption

STINT_SCHEMA_VERSION = 1
DEFAULT_TYRE_TEMP_TARGET_C = 90.0
DEFAULT_TYRE_TEMP_TOLERANCE_C = 5.0
DEFAULT_WEAR_BUDGET = 0.35
DEFAULT_FUEL_START_L = 30.0
DEFAULT_FUEL_BURN_L_PER_LAP = 2.2
MIN_PACE_SCALE = 0.85
NONSTATIONARY_PACE_SCALE = 0.94
HOT_THERMAL_PACE_SCALE = 0.96


class StintOptimizerError(ValueError):
    """Unsafe or incomplete inputs for the Layer-4 stint planner."""


def _finite(value: Any, *, name: str, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool) or value is None:
        raise StintOptimizerError(f"stint_{name}_missing")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise StintOptimizerError(f"stint_{name}_invalid") from exc
    if not math.isfinite(result):
        raise StintOptimizerError(f"stint_{name}_non_finite")
    if lo is not None and result < lo:
        raise StintOptimizerError(f"stint_{name}_out_of_range")
    if hi is not None and result > hi:
        raise StintOptimizerError(f"stint_{name}_out_of_range")
    return result


@dataclass(frozen=True)
class StintInputs:
    """Operator + plant inputs for a multi-lap stint plan."""

    plant_artifact: Mapping[str, Any]
    environment: EnvironmentState | None
    laps_remaining: int
    fuel_start_l: float = DEFAULT_FUEL_START_L
    fuel_burn_l_per_lap: float = DEFAULT_FUEL_BURN_L_PER_LAP
    tyre_temp_target_c: float = DEFAULT_TYRE_TEMP_TARGET_C
    tyre_temp_tolerance_c: float = DEFAULT_TYRE_TEMP_TOLERANCE_C
    wear_budget_fraction: float = DEFAULT_WEAR_BUDGET
    v_top_kmh: float = 250.0


@dataclass(frozen=True)
class StintPlan:
    """Slow-timescale targets for the QSS+L3 inner loop."""

    schema_version: int
    target_thermal_window_c: tuple[float, float]
    fuel_target_l: float
    projected_fuel_end_l: float
    wear_budget_fraction: float
    pace_scale: float
    l3_params: dict[str, Any] | None
    stationary_required: bool
    environment_confidence: float
    degraded: bool
    reasons: tuple[str, ...]
    thermal_cohort: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["target_thermal_window_c"] = list(self.target_thermal_window_c)
        payload["reasons"] = list(self.reasons)
        return payload


def _thermal_cohort(plant: Mapping[str, Any]) -> dict[str, Any] | None:
    ggv = plant.get("ggv")
    if not isinstance(ggv, Mapping):
        return None
    cohort = ggv.get("thermal_cohort")
    return dict(cohort) if isinstance(cohort, Mapping) else None


def _environment_confidence(environment: EnvironmentState | None) -> float:
    if environment is None or environment.n_laps <= 0:
        return 0.0
    if environment.nonstationary:
        return 0.25
    std = environment.track_grip_std
    if std is None:
        return min(1.0, 0.35 + 0.1 * environment.n_laps)
    # Low grip std → high confidence; clamp.
    return max(0.35, min(1.0, 1.0 - 4.0 * float(std)))


def plan_stint(inputs: StintInputs) -> StintPlan:
    """Emit slow-timescale stint targets from a plant + optional Layer-0 state."""
    if not isinstance(inputs.laps_remaining, int) or inputs.laps_remaining < 1:
        raise StintOptimizerError("stint_laps_remaining_invalid")
    fuel_start = _finite(inputs.fuel_start_l, name="fuel_start_l", lo=0.0, hi=200.0)
    burn = _finite(inputs.fuel_burn_l_per_lap, name="fuel_burn_l_per_lap", lo=0.0, hi=20.0)
    temp_target = _finite(inputs.tyre_temp_target_c, name="tyre_temp_target_c", lo=40.0, hi=140.0)
    temp_tol = _finite(inputs.tyre_temp_tolerance_c, name="tyre_temp_tolerance_c", lo=0.5, hi=30.0)
    wear_budget = _finite(inputs.wear_budget_fraction, name="wear_budget_fraction", lo=0.01, hi=1.0)
    v_top = _finite(inputs.v_top_kmh, name="v_top_kmh", lo=40.0, hi=400.0)

    reasons: list[str] = []
    degraded = False
    pace_scale = 1.0
    l3: L3Params | None = L3Params()

    ready = plant_ready_for_full_consumption(dict(inputs.plant_artifact), require_friction_fit=True)
    if ready is not None:
        raise StintOptimizerError(f"stint_plant_unusable:{ready}")
    if plant_ggv_model(dict(inputs.plant_artifact)) is None:
        raise StintOptimizerError("stint_plant_missing_uncertainty_fit")

    cohort = _thermal_cohort(inputs.plant_artifact)
    if cohort is None:
        degraded = True
        reasons.append("missing_thermal_cohort")
        window = (temp_target - temp_tol, temp_target + temp_tol)
    else:
        core = _finite(cohort.get("core_temp_c"), name="cohort_core_temp_c", lo=-20.0, hi=200.0)
        cohort_tol = _finite(
            cohort.get("core_tolerance_c", temp_tol),
            name="cohort_core_tolerance_c",
            lo=0.5,
            hi=30.0,
        )
        # Prefer the plant's identified thermal center; operator target only recenters when the
        # cohort is far from the requested window.
        center = core if abs(core - temp_target) <= cohort_tol else temp_target
        window = (center - cohort_tol, center + cohort_tol)
        if core > window[1]:
            pace_scale = min(pace_scale, HOT_THERMAL_PACE_SCALE)
            reasons.append("cohort_hot_vs_window")
            degraded = True

    environment = inputs.environment
    confidence = _environment_confidence(environment)
    stationary_required = True
    if environment is not None and environment.nonstationary:
        pace_scale = min(pace_scale, NONSTATIONARY_PACE_SCALE)
        # Tighter L3: only the stability floor remains — refuse aggressive z-ladder steps while
        # the track/environment is drifting.
        l3 = L3Params(z_ladder=(1.0,), max_rel_std=0.15)
        reasons.append(environment.reason or "environment_nonstationary")
        degraded = True
        stationary_required = True

    projected_end = fuel_start - burn * float(inputs.laps_remaining)
    if projected_end < 0.0:
        # Pace derate scales with the fuel shortfall fraction, never below MIN_PACE_SCALE.
        shortfall = min(1.0, -projected_end / max(fuel_start, 1e-6))
        fuel_scale = max(MIN_PACE_SCALE, 1.0 - 0.1 * shortfall)
        pace_scale = min(pace_scale, fuel_scale)
        reasons.append(f"fuel_shortfall_l={-projected_end:.2f}")
        degraded = True
        projected_end = 0.0

    # Keep a small reserve so the final lap is not planned to absolute empty.
    fuel_target = max(0.5, projected_end)

    if wear_budget < 0.15:
        pace_scale = min(pace_scale, 0.97)
        reasons.append("tight_wear_budget")
        degraded = True

    pace_scale = max(MIN_PACE_SCALE, min(1.0, pace_scale))
    # v_top is accepted for contract completeness; L4 does not invent a second speed solver.
    _ = v_top

    return StintPlan(
        schema_version=STINT_SCHEMA_VERSION,
        target_thermal_window_c=(round(window[0], 3), round(window[1], 3)),
        fuel_target_l=round(fuel_target, 3),
        projected_fuel_end_l=round(projected_end, 3),
        wear_budget_fraction=round(wear_budget, 4),
        pace_scale=round(pace_scale, 4),
        l3_params=l3.to_dict() if l3 is not None else None,
        stationary_required=stationary_required,
        environment_confidence=round(confidence, 4),
        degraded=degraded,
        reasons=tuple(reasons),
        thermal_cohort=cohort,
    )


def inner_loop_inputs(plan: StintPlan) -> dict[str, Any]:
    """Map a stint plan onto existing alien-drive knobs (ggv_scale / L3 params)."""
    l3_params = None
    if plan.l3_params is not None:
        l3_params = L3Params.from_dict(plan.l3_params)
    return {
        "ggv_scale": plan.pace_scale,
        "l3_params": l3_params,
        "l3_params_dict": plan.l3_params,
        "degraded": plan.degraded,
        "reasons": list(plan.reasons),
    }
