"""Layer-0 environment / track-evolution observer (EPIC #529 / issue #674).

Pure, per-lap updates over harness lap archives. Reuses the thermally tagged lap observer in
:mod:`tools.ac_harness.ggv_profile` and tracks grip/thermal/pressure drift across successive
laps so the pipeline can flag non-stationarity instead of silently re-fitting the plant.

This is the EPIC #529 Layer-0 (environment), not the off-sim Lua L0 harness in
:mod:`tools.ac_harness` package docs.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from tools.ac_harness.ggv_profile import observe_lap_tyre_state

ENV_SCHEMA_VERSION = 1
DEFAULT_GRIP_DRIFT = 0.08
DEFAULT_THERMAL_DRIFT_C = 8.0
DEFAULT_PRESSURE_DRIFT_PSI = 1.5
DEFAULT_MIN_LAPS_FOR_DRIFT = 2
_MAX_HISTORY = 32


class EnvironmentObserverError(ValueError):
    """Malformed telemetry or configuration for the Layer-0 observer."""


def _finite(value: Any, *, name: str, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool) or value is None:
        raise EnvironmentObserverError(f"environment_{name}_missing")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EnvironmentObserverError(f"environment_{name}_invalid") from exc
    if not math.isfinite(result):
        raise EnvironmentObserverError(f"environment_{name}_non_finite")
    if lo is not None and result < lo:
        raise EnvironmentObserverError(f"environment_{name}_out_of_range")
    if hi is not None and result > hi:
        raise EnvironmentObserverError(f"environment_{name}_out_of_range")
    return result


def _optional_finite(
    value: Any, *, name: str, lo: float | None = None, hi: float | None = None
) -> float | None:
    if value is None:
        return None
    return _finite(value, name=name, lo=lo, hi=hi)


@dataclass(frozen=True)
class EnvironmentObservation:
    """One lap's environment-relevant evidence."""

    lap_uuid: str
    lap_n: int
    lap_ms: int
    core_temp_c: float | None
    pressure_psi: float | None
    thermal_tag: str | None
    grip_multiplier: float | None
    fuel_end_l: float | None
    wear_mean: float | None
    fit_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EnvironmentState:
    """Running estimate of track/environment stationarity with uncertainty."""

    schema_version: int = ENV_SCHEMA_VERSION
    n_laps: int = 0
    track_grip_mean: float | None = None
    track_grip_std: float | None = None
    thermal_mean_c: float | None = None
    thermal_delta_c: float | None = None
    pressure_mean_psi: float | None = None
    pressure_delta_psi: float | None = None
    nonstationary: bool = False
    reason: str | None = None
    reidentify_recommended: bool = False
    evidence_lap_uuids: tuple[str, ...] = ()
    history: tuple[EnvironmentObservation, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_lap_uuids"] = list(self.evidence_lap_uuids)
        payload["history"] = [obs.to_dict() for obs in self.history]
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> EnvironmentState | None:
        if data is None:
            return None
        if not isinstance(data, Mapping):
            raise EnvironmentObserverError("environment_state_invalid")
        if int(data.get("schema_version") or 0) != ENV_SCHEMA_VERSION:
            raise EnvironmentObserverError("environment_state_unsupported_schema")
        history_raw = data.get("history") or ()
        if not isinstance(history_raw, Sequence):
            raise EnvironmentObserverError("environment_state_history_invalid")
        history = tuple(
            EnvironmentObservation(
                lap_uuid=str(row["lap_uuid"]),
                lap_n=int(row["lap_n"]),
                lap_ms=int(row["lap_ms"]),
                core_temp_c=row.get("core_temp_c"),
                pressure_psi=row.get("pressure_psi"),
                thermal_tag=row.get("thermal_tag"),
                grip_multiplier=row.get("grip_multiplier"),
                fuel_end_l=row.get("fuel_end_l"),
                wear_mean=row.get("wear_mean"),
                fit_eligible=bool(row.get("fit_eligible")),
            )
            for row in history_raw
            if isinstance(row, Mapping)
        )
        uuids = data.get("evidence_lap_uuids") or ()
        return cls(
            schema_version=ENV_SCHEMA_VERSION,
            n_laps=int(data.get("n_laps") or 0),
            track_grip_mean=data.get("track_grip_mean"),
            track_grip_std=data.get("track_grip_std"),
            thermal_mean_c=data.get("thermal_mean_c"),
            thermal_delta_c=data.get("thermal_delta_c"),
            pressure_mean_psi=data.get("pressure_mean_psi"),
            pressure_delta_psi=data.get("pressure_delta_psi"),
            nonstationary=bool(data.get("nonstationary")),
            reason=data.get("reason"),
            reidentify_recommended=bool(data.get("reidentify_recommended")),
            evidence_lap_uuids=tuple(str(u) for u in uuids),
            history=history,
        )


def _trace_channel_mean(archive: Mapping[str, Any], name: str) -> float | None:
    trace = archive.get("trace")
    if not isinstance(trace, Mapping):
        return None
    fields = trace.get("fields")
    samples = trace.get("samples")
    if not isinstance(fields, list) or not isinstance(samples, list) or name not in fields:
        return None
    index = fields.index(name)
    values: list[float] = []
    for row in samples:
        if not isinstance(row, (list, tuple)) or index >= len(row):
            continue
        try:
            value = float(row[index])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    if not values:
        return None
    return statistics.fmean(values)


def _wear_mean(archive: Mapping[str, Any]) -> float | None:
    wears = [
        _trace_channel_mean(archive, f"tyreWear_{wheel}") for wheel in ("fl", "fr", "rl", "rr")
    ]
    present = [value for value in wears if value is not None]
    if not present:
        return None
    return statistics.fmean(present)


def observation_from_lap_archive(payload: Mapping[str, Any]) -> EnvironmentObservation:
    """Validate one lap archive and extract the Layer-0 observation."""
    if not isinstance(payload, Mapping):
        raise EnvironmentObserverError("environment_archive_invalid")
    lap_uuid = str(payload.get("lap_uuid") or "").strip()
    if not lap_uuid or len(lap_uuid) > 128:
        raise EnvironmentObserverError("environment_lap_uuid_invalid")
    lap = payload.get("lap")
    if not isinstance(lap, Mapping):
        raise EnvironmentObserverError("environment_lap_block_missing")
    lap_n = int(_finite(lap.get("lap_n"), name="lap_n", lo=0, hi=10_000))
    lap_ms = int(_finite(lap.get("lap_ms"), name="lap_ms", lo=1, hi=3_600_000))
    if lap.get("is_valid") is not True:
        raise EnvironmentObserverError("environment_lap_invalid")

    tyre = observe_lap_tyre_state(dict(payload))
    core = _optional_finite(tyre.get("core_temp_c"), name="core_temp_c", lo=-20.0, hi=200.0)
    pressure = _optional_finite(tyre.get("pressure_psi"), name="pressure_psi", lo=0.0, hi=60.0)
    grip = _optional_finite(tyre.get("grip_multiplier"), name="grip_multiplier", lo=0.0, hi=1.0)
    fuel = _optional_finite(_trace_channel_mean(payload, "fuel"), name="fuel", lo=0.0, hi=200.0)
    wear = _optional_finite(_wear_mean(payload), name="wear", lo=0.0, hi=1.0)
    tag = tyre.get("tag")
    thermal_tag = str(tag) if isinstance(tag, str) and tag else None
    return EnvironmentObservation(
        lap_uuid=lap_uuid,
        lap_n=lap_n,
        lap_ms=lap_ms,
        core_temp_c=core,
        pressure_psi=pressure,
        thermal_tag=thermal_tag,
        grip_multiplier=grip,
        fuel_end_l=fuel,
        wear_mean=wear,
        fit_eligible=bool(tyre.get("fit_eligible")),
    )


def update_environment(
    prior: EnvironmentState | None,
    observation: EnvironmentObservation,
    *,
    grip_drift: float = DEFAULT_GRIP_DRIFT,
    thermal_drift_c: float = DEFAULT_THERMAL_DRIFT_C,
    pressure_drift_psi: float = DEFAULT_PRESSURE_DRIFT_PSI,
    min_laps_for_drift: int = DEFAULT_MIN_LAPS_FOR_DRIFT,
) -> EnvironmentState:
    """Fold one observation into the running environment estimate.

    Deliberately does **not** catch per-lap errors: a caller that wraps this in a broad
    ``except Exception`` would freeze the estimate while the pipeline keeps trusting it.
    """
    _finite(grip_drift, name="grip_drift", lo=0.0, hi=1.0)
    _finite(thermal_drift_c, name="thermal_drift_c", lo=0.0, hi=100.0)
    _finite(pressure_drift_psi, name="pressure_drift_psi", lo=0.0, hi=20.0)
    if not isinstance(min_laps_for_drift, int) or min_laps_for_drift < 2:
        raise EnvironmentObserverError("environment_min_laps_for_drift_invalid")

    history = list(prior.history if prior is not None else ())
    if any(obs.lap_uuid == observation.lap_uuid for obs in history):
        raise EnvironmentObserverError("environment_lap_duplicate")
    history.append(observation)
    history = history[-_MAX_HISTORY:]

    grips = [obs.grip_multiplier for obs in history if obs.grip_multiplier is not None]
    thermals = [obs.core_temp_c for obs in history if obs.core_temp_c is not None]
    pressures = [obs.pressure_psi for obs in history if obs.pressure_psi is not None]

    grip_mean = statistics.fmean(grips) if grips else None
    grip_std = statistics.pstdev(grips) if len(grips) >= 2 else (0.0 if grips else None)
    thermal_mean = statistics.fmean(thermals) if thermals else None
    thermal_delta = (max(thermals) - min(thermals)) if len(thermals) >= 2 else None
    pressure_mean = statistics.fmean(pressures) if pressures else None
    pressure_delta = (max(pressures) - min(pressures)) if len(pressures) >= 2 else None

    reasons: list[str] = []
    if len(history) >= min_laps_for_drift:
        if grip_std is not None and grip_std >= grip_drift:
            reasons.append(f"grip_std={grip_std:.3f}>={grip_drift:.3f}")
        if thermal_delta is not None and thermal_delta >= thermal_drift_c:
            reasons.append(f"thermal_delta_c={thermal_delta:.2f}>={thermal_drift_c:.2f}")
        if pressure_delta is not None and pressure_delta >= pressure_drift_psi:
            reasons.append(f"pressure_delta_psi={pressure_delta:.2f}>={pressure_drift_psi:.2f}")
        first_grip = history[0].grip_multiplier
        last_grip = history[-1].grip_multiplier
        if first_grip is not None and last_grip is not None:
            if abs(last_grip - first_grip) >= grip_drift:
                reasons.append(
                    f"grip_span={abs(last_grip - first_grip):.3f}>={grip_drift:.3f}"
                )

    nonstationary = bool(reasons)
    return EnvironmentState(
        schema_version=ENV_SCHEMA_VERSION,
        n_laps=len(history),
        track_grip_mean=round(grip_mean, 5) if grip_mean is not None else None,
        track_grip_std=round(grip_std, 5) if grip_std is not None else None,
        thermal_mean_c=round(thermal_mean, 3) if thermal_mean is not None else None,
        thermal_delta_c=round(thermal_delta, 3) if thermal_delta is not None else None,
        pressure_mean_psi=round(pressure_mean, 3) if pressure_mean is not None else None,
        pressure_delta_psi=round(pressure_delta, 3) if pressure_delta is not None else None,
        nonstationary=nonstationary,
        reason="; ".join(reasons) if reasons else None,
        reidentify_recommended=nonstationary,
        evidence_lap_uuids=tuple(obs.lap_uuid for obs in history),
        history=tuple(history),
    )


def environment_from_archives(
    archives: Sequence[Mapping[str, Any]],
    *,
    prior: EnvironmentState | None = None,
) -> EnvironmentState:
    """Fold a sequence of lap archives into an environment state (fail-loud on bad rows)."""
    state = prior
    for payload in archives:
        state = update_environment(state, observation_from_lap_archive(payload))
    if state is None:
        raise EnvironmentObserverError("environment_archives_empty")
    return state


def environment_for_plan(state: EnvironmentState) -> dict[str, Any]:
    """Compact, JSON-safe view for scientist / stint plan provenance."""
    return {
        "schema_version": state.schema_version,
        "n_laps": state.n_laps,
        "track_grip_mean": state.track_grip_mean,
        "track_grip_std": state.track_grip_std,
        "thermal_mean_c": state.thermal_mean_c,
        "thermal_delta_c": state.thermal_delta_c,
        "pressure_mean_psi": state.pressure_mean_psi,
        "pressure_delta_psi": state.pressure_delta_psi,
        "nonstationary": state.nonstationary,
        "reason": state.reason,
        "reidentify_recommended": state.reidentify_recommended,
        "evidence_lap_uuids": list(state.evidence_lap_uuids),
    }
