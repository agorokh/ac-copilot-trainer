"""Evidence-gated Coach v2 targets derived from an alien-line artifact (epic #529 P5).

The alien line is a *ceiling*, not a technique demonstration.  This module therefore changes only
the per-corner minimum-speed target.  Brake point, throttle timing, steering and cue anchors stay
on the human reference lap.  Inputs are treated as immutable authority and the derived frontier is
kept in memory; malformed, wrong-combo, unverified or unmatchable artifacts fail closed.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tools.ai_sidecar.lap_dynamics import LapTrace
from tools.ai_sidecar.track_reference import CornerReference, build_references

_SCHEMA_VERSION = 1
_ENVELOPE_TOL = 1e-3
_APEX_MATCH_TOL = 0.08
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
        raise FrontierError(
            "alien_combo_mismatch: "
            f"expected={combo[0]}/{combo[1]}/{combo[2] or '-'} "
            f"actual={actual[0]}/{actual[1]}/{actual[2] or '-'}"
        )


def _validate_provenance(artifact: Mapping[str, Any]) -> None:
    provenance = artifact.get("plant_provenance")
    plant_sha = str(provenance.get("sha12") or "") if isinstance(provenance, Mapping) else ""
    lane_sha = str(artifact.get("fast_lane_sha12") or "")
    if not _SHA12_RE.fullmatch(plant_sha):
        raise FrontierError("alien_provenance_missing: plant_provenance.sha12")
    if not _SHA12_RE.fullmatch(lane_sha):
        raise FrontierError("alien_provenance_missing: fast_lane_sha12")


def _validate_envelope(artifact: Mapping[str, Any]) -> None:
    corridor = artifact.get("corridor")
    if not isinstance(corridor, Mapping):
        raise FrontierError("alien_envelope_missing: corridor")
    safe_util = _finite(corridor.get("max_ay_utilisation"))
    if safe_util is None or safe_util < 0.0 or safe_util > 1.0 + _ENVELOPE_TOL:
        raise FrontierError(f"alien_envelope_unverified: safe_utilisation={safe_util}")
    if "l3" in artifact:
        l3 = artifact.get("l3")
        if not isinstance(l3, Mapping):
            raise FrontierError("alien_envelope_unverified: malformed_l3")
        barrier_util = _finite(l3.get("max_ay_utilisation_vs_barrier"))
        if barrier_util is None or barrier_util < 0.0 or barrier_util > 1.0 + _ENVELOPE_TOL:
            raise FrontierError(f"alien_envelope_unverified: barrier_utilisation={barrier_util}")
        qss_profile = artifact.get("v_target_qss_mps")
        if (
            not isinstance(qss_profile, Sequence)
            or isinstance(qss_profile, (str, bytes))
            or any(_finite(speed, positive=True) is None for speed in qss_profile)
        ):
            raise FrontierError("alien_envelope_unverified: l3_missing_qss_profile")


def alien_lap_trace(artifact: Mapping[str, Any], *, combo: tuple[str, str, str]) -> LapTrace:
    """Validate an alien artifact and expose its line/speed envelope as a :class:`LapTrace`."""
    if artifact.get("schema_version") != _SCHEMA_VERSION:
        raise FrontierError(f"alien_schema_unsupported: {artifact.get('schema_version')!r}")
    _validate_identity(artifact, combo)
    _validate_provenance(artifact)
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
        raise FrontierError("alien_profile_malformed: line/speed length mismatch")
    if "l3" in artifact and len(artifact["v_target_qss_mps"]) != len(raw_speed):
        raise FrontierError("alien_envelope_unverified: l3_qss_length_mismatch")

    points: list[tuple[float, float, float]] = []
    speeds: list[float] = []
    for index, (point, speed) in enumerate(zip(raw_line, raw_speed, strict=True)):
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) < 3:
            raise FrontierError(f"alien_profile_malformed: point[{index}]")
        xyz = tuple(_finite(point[axis]) for axis in range(3))
        parsed_speed = _finite(speed, positive=True)
        if any(value is None for value in xyz) or parsed_speed is None:
            raise FrontierError(f"alien_profile_malformed: non-finite sample[{index}]")
        points.append((float(xyz[0]), float(xyz[1]), float(xyz[2])))
        speeds.append(parsed_speed)

    segment_m: list[float] = []
    for index, point in enumerate(points):
        previous = points[index - 1]
        segment_m.append(math.hypot(point[0] - previous[0], point[2] - previous[2]))
    total_m = sum(segment_m)
    if not math.isfinite(total_m) or total_m <= 1.0:
        raise FrontierError("alien_profile_malformed: degenerate line geometry")

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


def _match_corners(
    references: Sequence[CornerReference], alien_refs: Sequence[CornerReference]
) -> list[AlienCorner]:
    if not references or not alien_refs:
        raise FrontierError("alien_corners_unusable: no segmented corners")
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
            raise FrontierError(f"alien_corner_unmatched: reference_corner={ref.index}")
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


def _corner_history(profile: Mapping[str, Any] | None) -> dict[int, Mapping[str, Any]]:
    if not isinstance(profile, Mapping) or not isinstance(profile.get("corner_history"), Mapping):
        return {}
    out: dict[int, Mapping[str, Any]] = {}
    for row in profile["corner_history"].values():
        if not isinstance(row, Mapping):
            continue
        raw_index = row.get("corner_index")
        if isinstance(raw_index, bool):
            continue
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        out[index] = row
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
) -> dict[str, Any]:
    """Apply bounded personalized speed targets to ``references`` and return audit metadata.

    The function mutates only the newly-built in-memory references passed by the caller.  A failure
    occurs before any mutation, so callers can retain the demonstrated reference unchanged.
    """
    alien_trace = alien_lap_trace(artifact, combo=combo)
    matches = _match_corners(references, build_references(alien_trace))
    rows = _corner_history(profile)

    planned: list[tuple[CornerReference, float, dict[str, Any]]] = []
    for match in matches:
        ref = next(item for item in references if item.index == match.reference_index)
        row = rows.get(ref.index)
        if row is None:
            continue
        driver_best = _finite(row.get("best_min_speed_kmh"), positive=True)
        if driver_best is None:
            continue
        if driver_best >= match.ceiling_kmh:
            raise FrontierError(
                "driver_at_or_above_alien_ceiling: "
                f"corner={ref.index} driver={driver_best:.1f} alien={match.ceiling_kmh:.1f}"
            )
        cap = _gain_cap(driver_level, row)
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
