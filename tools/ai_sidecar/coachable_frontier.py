"""Evidence-gated Coach v2 targets derived from an alien-line artifact (epic #529 P5).

The alien line is a *ceiling*, not a technique demonstration.  This module therefore changes only
the per-corner minimum-speed target.  Brake point, throttle timing, steering and cue anchors stay
on the human reference lap.  Inputs are treated as immutable authority and the derived frontier is
kept in memory; malformed, wrong-combo, unverified or unmatchable artifacts fail closed.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tools.ai_sidecar.lap_dynamics import CornerSignature, LapTrace
from tools.ai_sidecar.track_reference import CornerReference, build_references
from tools.lap_qualification import Qualification

_SCHEMA_VERSION = 1
_ENVELOPE_TOL = 1e-3
_APEX_MATCH_TOL = 0.08
_BRAKE_POINT_MATCH_TOL = 0.04
_MATCH_UNIQUE_GAP = 0.01
_GAIN_BY_LEVEL_KMH = {
    "unknown": 1.5,
    "novice": 2.0,
    "intermediate": 4.0,
    "advanced": 6.0,
}
_SHA12_RE = re.compile(r"^[0-9a-f]{12}$")


class FrontierError(ValueError):
    """Raised when alien evidence cannot safely influence coaching targets."""


@dataclass(frozen=True)
class AlienCorner:
    """One alien-envelope corner matched to the human reference by track position."""

    reference_index: int
    alien_apex_spline: float
    ceiling_kmh: float


@dataclass(frozen=True)
class HumanDrillTarget:
    """Frozen, human-demonstrated phase targets and whole-corner guardrails.

    Only ``metric`` is an instruction. The remaining reference values preserve
    the existing human anchors; exit speed and time guard against trading a
    better-looking primary metric for a worse whole corner.
    """

    combo: tuple[str, str, str]
    corner: int
    drill_id: str
    root: str
    metric: str
    brake_point_spline: float | None
    trail_brake_frac: float
    min_speed_kmh: float
    throttle_on_spline: float | None
    exit_speed_kmh: float
    baseline_exit_speed_kmh: float
    baseline_corner_time_s: float
    tolerance: float
    exit_speed_tolerance_kmh: float
    corner_time_tolerance_s: float
    reference_identity: str
    baseline_identity: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["combo"] = list(self.combo)
        result["source"] = "qualified_human_reference"
        return result

    def assess(self, signature: CornerSignature, *, corner_time_s: float) -> dict[str, Any]:
        """Assess a completed observation against the frozen band and guardrails."""
        observed = _finite(getattr(signature, self.metric, None))
        exit_speed = _finite(signature.exit_speed_kmh, positive=True)
        elapsed = _finite(corner_time_s, positive=True)
        if (
            signature.index != self.corner
            or observed is None
            or exit_speed is None
            or elapsed is None
        ):
            return {"eligible": False, "success": False, "reason": "trial_metrics_unavailable"}
        if self.metric.endswith("_spline") and not 0.0 <= observed <= 1.0:
            return {"eligible": False, "success": False, "reason": "trial_metrics_unavailable"}
        if self.metric == "trail_brake_frac" and not 0.0 <= observed <= 1.0:
            return {"eligible": False, "success": False, "reason": "trial_metrics_unavailable"}
        if self.metric == "min_speed_kmh" and observed <= 0.0:
            return {"eligible": False, "success": False, "reason": "trial_metrics_unavailable"}
        if exit_speed < self.baseline_exit_speed_kmh - self.exit_speed_tolerance_kmh:
            return {"eligible": True, "success": False, "reason": "exit_speed_degraded"}
        if elapsed > self.baseline_corner_time_s + self.corner_time_tolerance_s:
            return {"eligible": True, "success": False, "reason": "corner_time_degraded"}
        expected = getattr(self, self.metric)
        delta = (
            _circular_distance(observed, expected)
            if self.metric.endswith("_spline")
            else abs(observed - expected)
        )
        success = delta <= self.tolerance
        return {
            "eligible": True,
            "success": success,
            "reason": "target_band_met" if success else "target_band_missed",
            "observed": observed,
            "target": expected,
        }


def build_human_drill_target(
    reference: CornerSignature,
    baseline: CornerSignature,
    *,
    reference_qualification: Qualification,
    baseline_qualification: Qualification,
    drill_id: str,
    combo: tuple[str, str, str],
    baseline_corner_time_s: float,
    reference_identity: str,
    baseline_identity: str,
    exit_speed_tolerance_kmh: float = 2.0,
    corner_time_tolerance_s: float = 0.1,
) -> HumanDrillTarget:
    """Freeze one curriculum target from already-qualified human observations.

    Qualification and exact archive/geometry matching belong to the caller's
    normal consumer boundary. Legacy-unknown/assisted records cannot enter here.
    Mutating a later reference or EMA cannot move the returned target.
    """
    from tools.ai_sidecar.coaching_diagnosis import (
        APEX_KMH_FLOOR,
        BRAKE_SPLINE_FLOOR,
        THROTTLE_SPLINE_FLOOR,
        TRAIL_FRAC_FLOOR,
        RootError,
    )
    from tools.ai_sidecar.driver_progression import drill_definition, drill_primary_metric

    if any(
        getattr(decision, "allowed", False) is not True
        or getattr(decision, "authority", None) != "human"
        for decision in (reference_qualification, baseline_qualification)
    ):
        raise FrontierError("drill_requires_qualified_human_archives")
    if (
        not isinstance(combo, (tuple, list))
        or len(combo) != 3
        or any(not isinstance(value, str) for value in combo)
        or not combo[0]
        or not combo[1]
        or not isinstance(reference.index, int)
        or isinstance(reference.index, bool)
        or reference.index < 0
        or type(baseline.index) is not int
        or reference.index != baseline.index
        or not isinstance(reference_identity, str)
        or not reference_identity
        or not isinstance(baseline_identity, str)
        or not baseline_identity
    ):
        raise FrontierError("drill_identity_unavailable")
    drill = drill_definition(drill_id)
    metric = drill_primary_metric(drill_id)
    for name in ("brake_point_spline", "throttle_on_spline"):
        value = getattr(reference, name)
        if value is not None and (_finite(value) is None or not 0.0 <= value <= 1.0):
            raise FrontierError("drill_reference_metrics_unavailable")
    if getattr(reference, metric) is None:
        raise FrontierError("drill_primary_metric_unavailable")
    numeric = (
        reference.min_speed_kmh,
        reference.exit_speed_kmh,
        baseline.exit_speed_kmh,
        baseline_corner_time_s,
    )
    if any(_finite(value, positive=True) is None for value in numeric):
        raise FrontierError("drill_reference_metrics_unavailable")
    if _finite(reference.trail_brake_frac) is None or not 0.0 <= reference.trail_brake_frac <= 1.0:
        raise FrontierError("drill_reference_metrics_unavailable")
    if any(
        _finite(value) is None or value < 0.0
        for value in (exit_speed_tolerance_kmh, corner_time_tolerance_s)
    ):
        raise FrontierError("drill_guardrail_tolerance_invalid")
    tolerances = {
        "min_speed_kmh": APEX_KMH_FLOOR,
        "brake_point_spline": BRAKE_SPLINE_FLOOR,
        "throttle_on_spline": THROTTLE_SPLINE_FLOOR,
        "trail_brake_frac": TRAIL_FRAC_FLOOR,
    }
    baseline_primary = _finite(getattr(baseline, metric, None))
    if (
        baseline_primary is None
        or (metric.endswith("_spline") and not 0.0 <= baseline_primary <= 1.0)
        or (metric == "trail_brake_frac" and not 0.0 <= baseline_primary <= 1.0)
        or (metric == "min_speed_kmh" and baseline_primary <= 0.0)
    ):
        raise FrontierError("drill_baseline_metric_unavailable")
    reference_primary = float(getattr(reference, metric))
    root = drill.roots[0]
    if metric.endswith("_spline"):
        circular_delta = (reference_primary - baseline_primary) % 1.0
        if math.isclose(circular_delta, 0.5, rel_tol=0.0, abs_tol=1e-9):
            raise FrontierError("drill_phase_ambiguous")
        signed_delta = (circular_delta + 0.5) % 1.0 - 0.5
        phases = []
        for signature, point in ((reference, reference_primary), (baseline, baseline_primary)):
            apex = _finite(signature.apex_spline)
            if apex is None or not 0.0 <= apex <= 1.0:
                raise FrontierError("drill_stage_phase_unavailable")
            phase = (apex - point) % 1.0 if metric == "brake_point_spline" else (point - apex) % 1.0
            if math.isclose(phase, 0.5, rel_tol=0.0, abs_tol=1e-9):
                raise FrontierError("drill_phase_ambiguous")
            if phase > 0.5:
                raise FrontierError("drill_stage_phase_unavailable")
            phases.append(phase)
        if metric == "brake_point_spline":
            delta = abs(signed_delta)
            root = RootError.EARLY_BRAKE if signed_delta > 0.0 else RootError.LATE_BRAKE
        else:
            # Throttle technique is relative to the apex, including corners at
            # start/finish; a smaller raw spline is not necessarily earlier.
            delta = phases[1] - phases[0]
    else:
        # Carry-more and trail-more roots only make sense when the reference
        # demonstrates MORE than this baseline, not merely a different value.
        delta = reference_primary - baseline_primary
    if abs(delta) <= tolerances[metric]:
        raise FrontierError("drill_baseline_already_in_target_band")
    if delta < 0.0:
        raise FrontierError("drill_reference_not_a_directional_improvement")
    return HumanDrillTarget(
        combo=tuple(combo),
        corner=reference.index,
        drill_id=drill.id,
        root=root.value,
        metric=metric,
        brake_point_spline=reference.brake_point_spline,
        trail_brake_frac=float(reference.trail_brake_frac),
        min_speed_kmh=float(reference.min_speed_kmh),
        throttle_on_spline=reference.throttle_on_spline,
        exit_speed_kmh=float(reference.exit_speed_kmh),
        baseline_exit_speed_kmh=float(baseline.exit_speed_kmh),
        baseline_corner_time_s=float(baseline_corner_time_s),
        tolerance=tolerances[metric],
        exit_speed_tolerance_kmh=float(exit_speed_tolerance_kmh),
        corner_time_tolerance_s=float(corner_time_tolerance_s),
        reference_identity=reference_identity,
        baseline_identity=baseline_identity,
    )


def _finite(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        return None
    return parsed


def _identity(value: Any) -> str:
    return str(value or "")


def _circular_distance(left: float, right: float) -> float:
    direct = abs(left - right)
    return min(direct, 1.0 - direct)


def _validate_identity(artifact: Mapping[str, Any], combo: tuple[str, str, str]) -> None:
    actual = (
        _identity(artifact.get("car_id")),
        _identity(artifact.get("track_id")),
        _identity(artifact.get("layout")),
    )
    if actual != combo:
        raise FrontierError("alien_combo_mismatch")


def _validate_provenance(
    artifact: Mapping[str, Any],
    *,
    expected_plant_sha12: str,
    expected_fast_lane_sha12: str,
) -> None:
    provenance = artifact.get("plant_provenance")
    plant_sha = str(provenance.get("sha12") or "") if isinstance(provenance, Mapping) else ""
    lane_sha = str(artifact.get("fast_lane_sha12") or "")
    if not _SHA12_RE.fullmatch(expected_plant_sha12) or plant_sha != expected_plant_sha12:
        raise FrontierError("alien_plant_provenance_mismatch")
    if not _SHA12_RE.fullmatch(expected_fast_lane_sha12) or lane_sha != expected_fast_lane_sha12:
        raise FrontierError("alien_fast_lane_provenance_mismatch")


def _validate_envelope(artifact: Mapping[str, Any]) -> None:
    corridor = artifact.get("corridor")
    if not isinstance(corridor, Mapping):
        raise FrontierError("alien_envelope_missing")
    safe_util = _finite(corridor.get("max_ay_utilisation"))
    if safe_util is None or safe_util < 0.0 or safe_util > 1.0 + _ENVELOPE_TOL:
        raise FrontierError("alien_envelope_unverified")
    if "l3" in artifact:
        l3 = artifact.get("l3")
        if not isinstance(l3, Mapping):
            raise FrontierError("alien_envelope_unverified")
        barrier_util = _finite(l3.get("max_ay_utilisation_vs_barrier"))
        if barrier_util is None or barrier_util < 0.0 or barrier_util > 1.0 + _ENVELOPE_TOL:
            raise FrontierError("alien_envelope_unverified")
        qss_profile = artifact.get("v_target_qss_mps")
        if (
            not isinstance(qss_profile, Sequence)
            or isinstance(qss_profile, (str, bytes))
            or any(_finite(speed, positive=True) is None for speed in qss_profile)
        ):
            raise FrontierError("alien_envelope_unverified")


def alien_lap_trace(
    artifact: Mapping[str, Any],
    *,
    combo: tuple[str, str, str],
    expected_plant_sha12: str,
    expected_fast_lane_sha12: str,
) -> LapTrace:
    """Validate an alien artifact and expose its line/speed envelope as a :class:`LapTrace`."""
    if artifact.get("schema_version") != _SCHEMA_VERSION:
        raise FrontierError("alien_schema_unsupported")
    _validate_identity(artifact, combo)
    _validate_provenance(
        artifact,
        expected_plant_sha12=expected_plant_sha12,
        expected_fast_lane_sha12=expected_fast_lane_sha12,
    )
    _validate_envelope(artifact)

    raw_line = artifact.get("line")
    raw_speed = artifact.get("v_target_mps")
    if (
        not isinstance(raw_line, Sequence)
        or isinstance(raw_line, (str, bytes))
        or not isinstance(raw_speed, Sequence)
        or isinstance(raw_speed, (str, bytes))
        or len(raw_line) < 5
        or len(raw_line) != len(raw_speed)
    ):
        raise FrontierError("alien_profile_malformed")
    if "l3" in artifact and len(artifact["v_target_qss_mps"]) != len(raw_speed):
        raise FrontierError("alien_envelope_unverified")

    points: list[tuple[float, float, float]] = []
    speeds: list[float] = []
    for point, speed in zip(raw_line, raw_speed, strict=True):
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) < 3:
            raise FrontierError("alien_profile_malformed")
        xyz = tuple(_finite(point[axis]) for axis in range(3))
        parsed_speed = _finite(speed, positive=True)
        if any(value is None for value in xyz) or parsed_speed is None:
            raise FrontierError("alien_profile_malformed")
        points.append((float(xyz[0]), float(xyz[1]), float(xyz[2])))
        speeds.append(parsed_speed)

    # This trace is an open sampling of one lap.  Keep the first segment at zero so the
    # cumulative numerator and total-distance denominator describe the same polyline.
    segment_m: list[float] = []
    for index, point in enumerate(points):
        previous = points[index - 1] if index else point
        segment_m.append(math.hypot(point[0] - previous[0], point[2] - previous[2]))
    total_m = sum(segment_m)
    if not math.isfinite(total_m) or total_m <= 1.0:
        raise FrontierError("alien_profile_malformed")

    spline: list[float] = []
    t_s: list[float] = []
    distance = 0.0
    elapsed = 0.0
    for index in range(len(points)):
        if index:
            distance += segment_m[index]
            elapsed += segment_m[index] / max((speeds[index - 1] + speeds[index]) / 2.0, 0.1)
        spline.append(distance / total_m)
        t_s.append(elapsed)
    return LapTrace(
        spline=spline,
        t_s=t_s,
        v_ms=speeds,
        brake=[0.0] * len(points),
        throttle=[0.0] * len(points),
        steer=[0.0] * len(points),
        gear=[0.0] * len(points),
        x=[point[0] for point in points],
        z=[point[2] for point in points],
        car_id=combo[0],
        track_id=combo[1],
    )


def _default_fast_lane_path(ac_root: Path, *, track_id: str, layout: str) -> Path:
    from tools.ac_harness.auto_drive import validate_ac_id

    try:
        safe_track_id = validate_ac_id("track", track_id)
        safe_layout = validate_ac_id("layout", layout) if layout else ""
    except ValueError:
        raise FrontierError("alien_fast_lane_source_invalid") from None
    tracks_root = (ac_root / "content" / "tracks").resolve()
    track_root = tracks_root / safe_track_id
    candidate = (
        track_root / safe_layout / "ai" / "fast_lane.ai"
        if safe_layout
        else track_root / "ai" / "fast_lane.ai"
    )
    try:
        candidate.resolve().relative_to(tracks_root)
    except ValueError:
        raise FrontierError("alien_fast_lane_source_invalid") from None
    return candidate


def load_verified_alien_evidence(
    path: str | Path,
    *,
    combo: tuple[str, str, str],
    plant_path: str | Path | None = None,
    fast_lane_path: str | Path | None = None,
    ac_root: str | Path | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Load and re-verify alien evidence against its current plant and lane inputs.

    Hashes persisted inside the alien JSON are never accepted as self-attestation. The plant hash
    is recomputed from the current sibling ``plant_id`` artifact, the lane hash from the current
    ``fast_lane.ai`` bytes, and the cached line/profile is re-run through the same corridor and
    plant-envelope verifier used by the autonomous driver.
    """
    artifact_path = Path(path)
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FrontierError("alien_artifact_unreadable") from None
    if not isinstance(payload, dict):
        raise FrontierError("alien_profile_malformed")
    _validate_identity(payload, combo)

    if plant_path is None:
        if artifact_path.parent.name != "alien_line":
            raise FrontierError("alien_plant_source_unresolved")
        resolved_plant = artifact_path.parent.parent / "plant_id" / artifact_path.name
    else:
        resolved_plant = Path(plant_path)
    try:
        plant_artifact = json.loads(resolved_plant.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise FrontierError("alien_plant_source_unreadable") from None
    if not isinstance(plant_artifact, dict):
        raise FrontierError("alien_plant_source_invalid")
    plant_combo = (
        _identity(plant_artifact.get("car_id")),
        _identity(plant_artifact.get("track_id")),
        _identity(plant_artifact.get("layout")),
    )
    if plant_combo != combo or _identity(plant_artifact.get("setup")) != _identity(
        payload.get("setup")
    ):
        raise FrontierError("alien_plant_source_identity_mismatch")

    from tools.ac_harness.ai_line import load_ai_line
    from tools.ac_harness.alien_line import (
        fast_lane_sha12,
        plant_provenance,
        validate_corridor,
        verify_alien_line_artifact,
    )
    from tools.ac_harness.ggv_profile import load_track_widths
    from tools.ac_harness.plant_id import (
        plant_ggv_model,
        plant_ready_for_full_consumption,
    )

    if plant_ready_for_full_consumption(plant_artifact, require_friction_fit=True) is not None:
        raise FrontierError("alien_plant_source_invalid")
    plant = plant_ggv_model(plant_artifact)
    if plant is None:
        raise FrontierError("alien_plant_source_invalid")
    expected_plant_sha12 = str(plant_provenance(plant_artifact)["sha12"])

    resolved_lane = (
        Path(fast_lane_path)
        if fast_lane_path is not None
        else _default_fast_lane_path(
            (
                Path(ac_root)
                if ac_root is not None
                else Path(r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa")
            ),
            track_id=combo[1],
            layout=combo[2],
        )
    )
    try:
        expected_fast_lane_sha12 = fast_lane_sha12(resolved_lane)
        fast_line = load_ai_line(resolved_lane)
        side_left, side_right = load_track_widths(resolved_lane)
        validate_corridor(side_left, side_right, len(fast_line))
    except (OSError, ValueError):
        raise FrontierError("alien_fast_lane_source_invalid") from None

    # Structural and external-provenance checks happen before the heavier geometric revalidation.
    alien_lap_trace(
        payload,
        combo=combo,
        expected_plant_sha12=expected_plant_sha12,
        expected_fast_lane_sha12=expected_fast_lane_sha12,
    )
    params = payload.get("params") if isinstance(payload.get("params"), Mapping) else {}
    margin_m = _finite(params.get("margin_m"))
    if margin_m is None or margin_m < 0.0:
        raise FrontierError("alien_build_params_invalid")
    try:
        reason = verify_alien_line_artifact(
            payload,
            fast_line,
            side_left,
            side_right,
            plant,
            margin_m=margin_m,
        )
    except (TypeError, ValueError, IndexError):
        raise FrontierError("alien_content_revalidation_failed") from None
    if reason is not None:
        raise FrontierError("alien_content_revalidation_failed")
    return payload, expected_plant_sha12, expected_fast_lane_sha12


def _match_corners(
    references: Sequence[CornerReference], alien_refs: Sequence[CornerReference]
) -> list[AlienCorner]:
    if not references or not alien_refs:
        raise FrontierError("alien_corners_unusable")
    unused = set(range(len(alien_refs)))
    matched: list[AlienCorner] = []
    for ref in references:
        candidates = sorted(
            (
                (_circular_distance(ref.apex_spline, alien_refs[index].apex_spline), index)
                for index in unused
            ),
            key=lambda item: item[0],
        )
        if not candidates or candidates[0][0] > _APEX_MATCH_TOL:
            raise FrontierError("alien_corner_unmatched")
        if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < _MATCH_UNIQUE_GAP:
            raise FrontierError("alien_corner_ambiguous")
        _, alien_index = candidates[0]
        unused.remove(alien_index)
        alien_ref = alien_refs[alien_index]
        matched.append(
            AlienCorner(
                reference_index=ref.index,
                alien_apex_spline=alien_ref.apex_spline,
                ceiling_kmh=alien_ref.optimal_apex_kmh,
            )
        )
    return matched


def _driver_samples_by_reference(
    profile: Mapping[str, Any] | None,
    reference_brake_points: Mapping[int, float | None],
) -> dict[int, list[Mapping[str, Any]]]:
    """Assign raw driver samples to the nearest reference brake point.

    Profile ``corner_index`` is deliberately ignored: it is an enumeration of each source lap's
    segmentation and can shift when a complex splits or merges. The per-lap brake-point spline is
    the stable geometric identity. Old profiles without that field simply contribute no frontier
    target until rebuilt, which is safer than borrowing another corner's speed.
    """
    if not isinstance(profile, Mapping) or not isinstance(profile.get("corner_history"), Mapping):
        return {}
    usable_refs: dict[int, float] = {}
    for index, raw_brake_point in reference_brake_points.items():
        brake_point = _finite(raw_brake_point)
        if brake_point is not None and 0.0 <= brake_point <= 1.0:
            usable_refs[index] = brake_point
    out: dict[int, list[Mapping[str, Any]]] = {index: [] for index in usable_refs}
    for row in profile["corner_history"].values():
        if not isinstance(row, Mapping):
            continue
        samples = row.get("corner_samples_by_lap_uuid")
        if not isinstance(samples, Mapping):
            continue
        for sample in samples.values():
            if not isinstance(sample, Mapping):
                continue
            brake_point = _finite(sample.get("brake_point_spline"))
            if (
                brake_point is None
                or not 0.0 <= brake_point <= 1.0
                or _finite(sample.get("min_speed_kmh"), positive=True) is None
            ):
                continue
            candidates = sorted(
                (
                    (_circular_distance(brake_point, ref_brake), ref_index)
                    for ref_index, ref_brake in usable_refs.items()
                ),
                key=lambda item: item[0],
            )
            nearest_is_usable = candidates and candidates[0][0] <= _BRAKE_POINT_MATCH_TOL
            nearest_is_unique = (
                len(candidates) == 1 or candidates[1][0] - candidates[0][0] >= _MATCH_UNIQUE_GAP
            )
            if nearest_is_usable and nearest_is_unique:
                out[candidates[0][1]].append(sample)
    return out


def _gain_cap(level: str, row: Mapping[str, Any]) -> float:
    cap = _GAIN_BY_LEVEL_KMH.get(level, _GAIN_BY_LEVEL_KMH["unknown"])
    reversals = _finite(row.get("avg_steer_reversals"))
    if reversals is not None and reversals > 5.0:
        return min(cap, 1.0)
    if reversals is not None and reversals > 3.0:
        return min(cap, 2.0)
    return cap


def derive_coachable_frontier(
    references: list[CornerReference],
    artifact: Mapping[str, Any],
    *,
    combo: tuple[str, str, str],
    profile: Mapping[str, Any] | None,
    driver_level: str,
    reference_brake_points: Mapping[int, float | None],
    expected_plant_sha12: str,
    expected_fast_lane_sha12: str,
) -> dict[str, Any]:
    """Apply bounded personalized speed targets to ``references`` and return audit metadata.

    The function mutates only the newly-built in-memory references passed by the caller.  A failure
    occurs before any mutation, so callers can retain the demonstrated reference unchanged.
    """
    alien_trace = alien_lap_trace(
        artifact,
        combo=combo,
        expected_plant_sha12=expected_plant_sha12,
        expected_fast_lane_sha12=expected_fast_lane_sha12,
    )
    matches = _match_corners(references, build_references(alien_trace))
    samples_by_reference = _driver_samples_by_reference(profile, reference_brake_points)

    planned: list[tuple[CornerReference, float, dict[str, Any]]] = []
    for match in matches:
        ref = next(item for item in references if item.index == match.reference_index)
        samples = samples_by_reference.get(ref.index) or []
        if not samples:
            continue
        driver_best = max(
            speed
            for sample in samples
            if (speed := _finite(sample.get("min_speed_kmh"), positive=True)) is not None
        )
        if driver_best >= match.ceiling_kmh:
            raise FrontierError("driver_at_or_above_alien_ceiling")
        reversals = [
            value
            for sample in samples
            if (value := _finite(sample.get("steer_reversals"))) is not None
        ]
        technique = {"avg_steer_reversals": sum(reversals) / len(reversals) if reversals else None}
        cap = _gain_cap(driver_level, technique)
        target = round(min(match.ceiling_kmh, driver_best + cap), 1)
        planned.append(
            (
                ref,
                target,
                {
                    "corner_index": ref.index,
                    "driver_best_kmh": round(driver_best, 1),
                    "target_kmh": target,
                    "alien_ceiling_kmh": round(match.ceiling_kmh, 1),
                    "gain_cap_kmh": cap,
                    "alien_apex_spline": round(match.alien_apex_spline, 6),
                },
            )
        )

    for ref, target, _ in planned:
        ref.coachable_apex_kmh = target
        ref.target_source = "alien_coachable_frontier"
    active = bool(planned)
    reason = "active" if active else "no_same_combo_driver_corner_history"
    return {
        "configured": True,
        "active": active,
        "source": "alien_coachable_frontier" if active else "reference",
        "reason": reason,
        "driver_level": driver_level,
        "plant_sha12": str(artifact["plant_provenance"]["sha12"]),
        "fast_lane_sha12": str(artifact["fast_lane_sha12"]),
        "corners": [detail for _, _, detail in planned],
    }


def frontier_fallback(reason: str) -> dict[str, Any]:
    """JSON-safe, non-secret audit state for a configured artifact that was rejected."""
    return {
        "configured": True,
        "active": False,
        "source": "reference",
        "reason": reason,
        "corners": [],
    }
