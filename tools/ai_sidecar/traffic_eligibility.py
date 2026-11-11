"""#955 experimental scalar occupancy gate; thresholds are uncalibrated.

``now_s`` MUST use the observation clock. A producer-local timestamp establishes
sampling age only, not network age. The live coach remains shadow-only; replay
enforcement is explicitly selected by its caller, never by telemetry input.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_AGE_S = 0.250
MAX_CARS = 128
CLEAN_USES = frozenset({"human_progression", "live_reference", "reference_comparison", "plant_fit"})


@dataclass(frozen=True)
class TrafficEligibility:
    status: str
    reason: str
    car_index: int | None = None

    @property
    def eligible(self) -> bool:
        return self.status == "eligible"


def _finite(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _unknown(reason: str) -> TrafficEligibility:
    return TrafficEligibility("unknown", reason)


def traffic_eligibility(context: Any, *, now_s: Any) -> TrafficEligibility:
    """Require a complete, fresh scalar roster before checking 3D AND spline space."""
    if (
        not isinstance(context, Mapping)
        or type(context.get("schema_version")) is not int
        or context["schema_version"] != 1
    ):
        return _unknown("traffic_context_missing_or_invalid")
    if context.get("error"):
        return _unknown("traffic_sampling_failed")
    sampled = context.get("sampled_at_s")
    if not _finite(now_s) or not _finite(sampled) or sampled < 0:
        return _unknown("traffic_clock_invalid")
    if not 0 <= now_s - sampled <= MAX_AGE_S:
        return _unknown("traffic_observation_stale_or_future")
    count, length = context.get("cars_count"), context.get("track_length_m")
    if type(count) is not int or not 1 <= count <= MAX_CARS:
        return _unknown("traffic_car_count_invalid")
    if not _finite(length) or length <= 0:
        return _unknown("traffic_track_length_invalid")
    cars = context.get("cars")
    if not isinstance(cars, list) or len(cars) != count:
        return _unknown("traffic_roster_incomplete")
    for index, car in enumerate(cars):
        if not isinstance(car, Mapping) or type(car.get("index")) is not int:
            return _unknown("traffic_car_index_invalid")
        if car["index"] != index:
            return _unknown("traffic_car_index_invalid")
        position, spline, speed = car.get("position"), car.get("spline"), car.get("speed_kmh")
        if (
            not isinstance(position, list)
            or len(position) != 3
            or not all(_finite(value) for value in position)
            or not _finite(spline)
            or not 0 <= spline < 1
            or not _finite(speed)
            or speed < 0
            or type(car.get("is_connected")) is not bool
            or type(car.get("is_in_pitlane")) is not bool
        ):
            return _unknown("traffic_car_fields_invalid")
    ego = cars[0]
    if not ego["is_connected"] or ego["is_in_pitlane"]:
        return _unknown("traffic_player_unavailable")
    # A provisional two-second approach horizon, capped to avoid a session-wide
    # mute. No thresholds have been tuned against the held-out replay split.
    horizon = min(150.0, max(12.0, ego["speed_kmh"] / 3.6 * 2.0))
    for car in cars[1:]:
        if not car["is_connected"] or car["is_in_pitlane"]:
            continue
        gap = ((car["spline"] - ego["spline"] + 0.5) % 1.0 - 0.5) * length
        distance = math.dist(ego["position"], car["position"])
        height = abs(ego["position"][1] - car["position"][1])
        if not all(_finite(value) for value in (gap, distance, height)):
            return _unknown("traffic_geometry_invalid")
        if -8.0 <= gap <= horizon and distance <= horizon and height <= 3.0:
            return TrafficEligibility("constrained", "traffic_occupied_approach", car["index"])
    return TrafficEligibility("eligible", "traffic_clear")


def archive_traffic_eligibility(record: Mapping[str, Any]) -> TrafficEligibility | None:
    """Evaluate stored observations, never trust a permissive precomputed status.

    Missing traffic on old archives is unassessed (None), preserving their
    existing provenance policy. A new/malformed/partial capture is unknown.
    """
    if "traffic" not in record:
        return None
    traffic = record["traffic"]
    if (
        not isinstance(traffic, Mapping)
        or type(traffic.get("schema_version")) is not int
        or traffic["schema_version"] != 1
    ):
        return _unknown("traffic_archive_invalid")
    if traffic.get("complete") is not True:
        return _unknown("traffic_archive_incomplete")
    frames = traffic.get("frames")
    start, end = traffic.get("started_at_s"), traffic.get("ended_at_s")
    lap = record.get("lap")
    lap_ms = lap.get("lap_ms") if isinstance(lap, Mapping) else None
    if (
        not isinstance(frames, list)
        or not 2 <= len(frames) <= 12000
        or not _finite(start)
        or not _finite(end)
        or start < 0
        or not _finite(lap_ms)
        or lap_ms <= 0
        or abs((end - start) * 1000 - lap_ms) > MAX_AGE_S * 1000
    ):
        return _unknown("traffic_archive_coverage_invalid")
    previous = start
    aggregate = TrafficEligibility("eligible", "traffic_clear")
    for index, frame in enumerate(frames):
        at = frame.get("sampled_at_s") if isinstance(frame, Mapping) else None
        if not _finite(at) or not previous <= at <= end or at - previous > MAX_AGE_S:
            return _unknown("traffic_archive_sample_gap")
        if index and at == previous:
            return _unknown("traffic_archive_sample_gap")
        verdict = traffic_eligibility(frame, now_s=at)
        if verdict.status == "unknown":
            return verdict
        if not verdict.eligible:
            aggregate = verdict
        previous = at
    if end - previous > MAX_AGE_S:
        return _unknown("traffic_archive_sample_gap")
    return aggregate
