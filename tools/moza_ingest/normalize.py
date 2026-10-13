"""Normalize tracecore.view.v1 for inspection without inventing native channels.

Import success is not reference acceptance. All production uses are explicitly
disabled: processed steering/time/map coordinates have no universal measured
native semantics, even when a cache joins a valid producer evaluation record.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from tools.lap_qualification import USES, build_qualification
from tools.moza_ingest.reader import MozaImportError

MOZA_VIEW_SCHEMA = "tracecore.view.v1"
MOZA_IMPORT_FORMAT = "moza_tracecore_view_v1"
_POINT_CHANNELS = {
    "distance": ("moza_map_distance", "m", 1.0),
    "time": ("moza_time_s", "s", 1.0),
    "speed": ("speed", "km/h", 1.0),
    "throttle": ("throttle", "ratio", 0.01),
    "brake": ("brake", "ratio", 0.01),
    "steering": ("moza_steering", "presented_deg", 1.0),
    "gear": ("gear", "gear", 1.0),
    "x": ("moza_map_x", "chart_coordinate", 1.0),
    "y": ("moza_map_y", "chart_coordinate", 1.0),
}
_EVENT_SERIES = {
    "brake_lock_front_left",
    "brake_lock_front_right",
    "brake_lock_rear_left",
    "brake_lock_rear_right",
    "tire_slip",
    "counter_steer",
}


def _object(value: Any, reason: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MozaImportError(reason)
    return value


def _text(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise MozaImportError(reason)
    if any(ord(c) < 32 for c in value):
        raise MozaImportError(reason)
    return value


def _number(value: Any, reason: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MozaImportError(reason)
    try:
        result = float(value)
    except OverflowError as exc:
        raise MozaImportError(reason) from exc
    if not math.isfinite(result):
        raise MozaImportError(reason)
    return result


def _integer(value: Any, reason: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise MozaImportError(reason)
    return value


def _flag(value: Any, reason: str) -> bool | None:
    if value is not None and type(value) is not bool:
        raise MozaImportError(reason)
    return value


def _lap_milliseconds(value: Any, reason: str) -> int:
    seconds = _number(value, reason)
    milliseconds = seconds * 1000
    if not math.isfinite(milliseconds) or milliseconds < 1:
        raise MozaImportError(reason)
    return round(milliseconds)


def _json_values(value: Any) -> None:
    """Pure API calls get the same finite/JSON guarantee as the file reader."""
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > 100:
            raise MozaImportError("json_nesting_too_deep")
        if isinstance(current, Mapping):
            for key, item in current.items():
                if not isinstance(key, str):
                    raise MozaImportError("invalid_json_key")
                pending.append((item, depth + 1))
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
        elif isinstance(current, (int, float)) and not isinstance(current, bool):
            _number(current, "nonfinite_json_value")
        elif current is not None and not isinstance(current, (str, bool)):
            raise MozaImportError("invalid_json_value")


def _source(value: Any) -> dict[str, Any]:
    source = _object(value, "invalid_source_metadata")
    digest = source.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise MozaImportError("invalid_source_hash")
    _integer(source.get("bytes"), "invalid_source_size", 1)
    if source.get("status") != "stable_captured_bytes":
        raise MozaImportError("source_not_stable")
    timestamp = _text(source.get("captured_at"), "invalid_source_timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise MozaImportError("invalid_source_timestamp") from exc
    if parsed.tzinfo is None:
        raise MozaImportError("invalid_source_timestamp")
    if "path" in source:
        _text(source["path"], "invalid_source_path")
    for key in ("mtime_ns", "device", "inode"):
        if key in source:
            _integer(source[key], "invalid_source_metadata")
    _json_values(source)
    return dict(source)


def _points(details: Mapping[str, Any]) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    segments = details.get("segments")
    if not isinstance(segments, list) or not segments:
        raise MozaImportError("invalid_segments")
    seen: set[str | int] = set()
    points: list[dict[str, float]] = []
    metadata: list[dict[str, Any]] = []
    for segment in segments:
        segment = _object(segment, "invalid_segment")
        identity = segment.get("id")
        if type(identity) is int:
            _integer(identity, "invalid_segment_id")
        else:
            _text(identity, "invalid_segment_id")
        if identity in seen:
            raise MozaImportError("duplicate_segment_identity")
        seen.add(identity)
        bounds = {
            key: _number(segment.get(key), "invalid_segment_bounds")
            for key in ("startDistance", "endDistance", "startMapProgress", "endMapProgress")
        }
        if (
            bounds["startDistance"] < 0
            or bounds["endDistance"] <= bounds["startDistance"]
            or not 0 <= bounds["startMapProgress"] < bounds["endMapProgress"] <= 1
        ):
            raise MozaImportError("invalid_segment_bounds")
        rows = segment.get("points")
        if not isinstance(rows, list) or not rows:
            raise MozaImportError("invalid_segment_points")
        for row in rows:
            row = _object(row, "invalid_point")
            point = {}
            for key in _POINT_CHANNELS:
                value = row.get(key)
                if value is None and key not in {"distance", "time", "speed"}:
                    continue
                number = _number(value, "invalid_point_" + key)
                if key in {"distance", "time", "speed"} and number < 0:
                    raise MozaImportError("point_out_of_range_" + key)
                if key in {"throttle", "brake"} and not 0 <= number <= 100:
                    raise MozaImportError("point_out_of_range_" + key)
                if key == "gear" and (not number.is_integer() or not -1 <= number <= 20):
                    raise MozaImportError("point_out_of_range_gear")
                point[key] = number
            points.append(point)
        metadata.append({"id": identity, **bounds, "detail_points": len(rows)})
    if len(points) < 2:
        raise MozaImportError("insufficient_detail_points")
    return points, metadata


def _events(value: Any) -> dict[str, Any]:
    if value is None:
        return {"status": "unavailable", "present": False, "reason": "events_not_supplied"}
    events = _object(value, "invalid_diagnostic_events")
    if events.get("axis") != "mapDistance" or events.get("distanceUnit") != "m":
        raise MozaImportError("unsupported_event_axis_or_units")
    series = events.get("series")
    if not isinstance(series, list):
        raise MozaImportError("invalid_event_series")
    copied = []
    seen = set()
    for item in series:
        item = _object(item, "invalid_event_series")
        identity = _text(item.get("id"), "invalid_event_identity")
        if identity not in _EVENT_SERIES:
            raise MozaImportError("unsupported_event_series")
        if identity in seen:
            raise MozaImportError("duplicate_event_identity")
        seen.add(identity)
        available = _flag(item.get("available"), "invalid_event_availability")
        intervals = item.get("intervals")
        if not isinstance(intervals, list):
            raise MozaImportError("invalid_event_intervals")
        normalized = []
        for interval in intervals:
            interval = _object(interval, "invalid_event_interval")
            result = {}
            for suffix in ("Distance", "MapProgress", "Time"):
                low, high = "start" + suffix, "end" + suffix
                start = _number(interval.get(low), "invalid_event_interval")
                end = _number(interval.get(high), "invalid_event_interval")
                if start < 0 or end < start or (suffix == "MapProgress" and end > 1):
                    raise MozaImportError("invalid_event_interval")
                result.update({low: start, high: end})
            normalized.append(result)
        calibration = item.get("calibration")
        if calibration is not None:
            calibration = dict(_object(calibration, "invalid_event_calibration"))
        copied.append(
            {
                "id": identity,
                "available": available,
                "intervals": normalized,
                "calibration": calibration,
            }
        )
    return {
        "status": "unqualified",
        "present": True,
        "axis": "mapDistance",
        "distance_unit": "m",
        "series": copied,
        "reason": "producer_annotation_not_validated_causal_advice",
    }


def _evaluation(
    payload: Mapping[str, Any] | None, lap_id: str, lap_ms: int, lap_n: int
) -> tuple[dict[str, Any], str]:
    unavailable = {"status": "unavailable", "reason": "evaluation_not_selected", "advice": None}
    if payload is None:
        return unavailable, "unknown"
    payload = _object(payload, "invalid_evaluation")
    _json_values(payload)
    if type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != 1:
        raise MozaImportError("unsupported_evaluation_schema")
    algorithm = payload.get("algorithmVersion")
    if algorithm is not None:
        _text(algorithm, "invalid_evaluation_version")
    summary = payload.get("summary")
    if summary is None:
        return {**unavailable, "reason": "no_evaluation_summary"}, "unknown"
    summary = _object(summary, "invalid_evaluation_summary")
    counts = {
        key: _integer(summary.get(key), "invalid_evaluation_count")
        for key in ("observedLapCount", "completeLapCount", "evaluatedLapCount")
    }
    if not counts["evaluatedLapCount"] <= counts["completeLapCount"] <= counts["observedLapCount"]:
        raise MozaImportError("invalid_evaluation_count")
    rows = summary.get("laps")
    if isinstance(rows, Mapping):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise MozaImportError("invalid_evaluation_laps")
    session = _text(payload.get("sessionId"), "invalid_evaluation_session")
    for key in ("sessionStartedAtMs", "savedAtMs"):
        if key in payload:
            _integer(payload[key], "invalid_evaluation_timestamp")
    if "sessionStartedAtMs" in summary and summary["sessionStartedAtMs"] != payload.get(
        "sessionStartedAtMs"
    ):
        raise MozaImportError("evaluation_session_conflict")
    if payload.get("savedAtMs", math.inf) < payload.get("sessionStartedAtMs", 0):
        raise MozaImportError("evaluation_timestamp_conflict")
    matches = []
    ids: set[str] = set()
    record_uids: set[str] = set()
    for row in rows:
        row = _object(row, "invalid_evaluation_lap")
        identity = _text(row.get("id"), "invalid_evaluation_identity")
        record_uid = _text(row.get("recordUid"), "invalid_evaluation_identity")
        if identity in ids or record_uid in record_uids:
            raise MozaImportError("duplicate_evaluation_identity")
        ids.add(identity)
        record_uids.add(record_uid)
        for key in ("aiIntervened", "complete", "finalized", "isValidLap"):
            _flag(row.get(key), "invalid_evaluation_" + key)
        if identity == lap_id or record_uid == lap_id:
            if identity != lap_id or record_uid != lap_id:
                raise MozaImportError("evaluation_identity_conflict")
            if row.get("sessionId") != session:
                raise MozaImportError("evaluation_session_conflict")
            duration = _lap_milliseconds(row.get("lapTimeSeconds"), "invalid_evaluation_duration")
            producer_lap_n = _integer(row.get("lapNumber"), "invalid_evaluation_lap_number", 1)
            if abs(duration - lap_ms) > 1 or producer_lap_n != lap_n:
                raise MozaImportError("evaluation_lap_conflict")
            matches.append(row)
    if not matches:
        return {
            **unavailable,
            "reason": "evaluation_identity_unmatched",
            "counts": counts,
        }, "unknown"
    row = matches[0]
    intervened = row.get("aiIntervened")
    eligibility = row.get("eligibility")
    if eligibility is not None:
        _text(eligibility, "invalid_evaluation_eligibility")
    reason = "producer_evaluation_unqualified"
    if counts["evaluatedLapCount"] == 0:
        reason = "zero_evaluated_laps"
    elif intervened is True or eligibility == "ai-debug-only":
        reason = "ai_debug_only"
    elif row.get("complete") is not True or row.get("finalized") is not True:
        reason = "evaluation_incomplete"
    return {
        "status": "unavailable",
        "reason": reason,
        "advice": None,
        "counts": counts,
        "identity_join": "cache.lapId=evaluation.id=evaluation.recordUid",
        "producer_session_id": session,
        "producer_lap_id": lap_id,
        "ai_intervened": intervened,
        "producer_eligibility": eligibility,
        "complete": row.get("complete"),
        "finalized": row.get("finalized"),
        "is_valid": row.get("isValidLap"),
        "algorithm_version": algorithm,
        "observed_score_fields": [
            key for key in ("totalScore", "stabilityScore", "dimensions") if key in row
        ],
    }, "shared" if intervened is True else "unknown"


def normalize_view(
    view: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    evaluation: Mapping[str, Any] | None = None,
    evaluation_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an archive-shaped sparse inspection artifact, never a live reference."""
    view = _object(view, "invalid_view")
    _json_values(view)
    source = _source(source)
    if view.get("schemaVersion") != MOZA_VIEW_SCHEMA:
        raise MozaImportError("unsupported_view_schema")
    overview = _object(view.get("overview"), "invalid_overview")
    details = _object(view.get("details"), "invalid_details")
    summary = _object(details.get("summary"), "invalid_detail_summary")
    identity = _text(overview.get("lapId"), "invalid_lap_identity")
    if details.get("lapId") != identity:
        raise MozaImportError("lap_identity_mismatch")
    declared_samples = _integer(overview.get("sampleCount"), "invalid_sample_count")
    for key in ("finishedLap", "isValidLap"):
        if key in summary:
            _flag(summary[key], "invalid_detail_summary")
    for key in ("lapNumber", "sampleCount"):
        if key in summary:
            _integer(summary[key], "invalid_detail_summary")
    for key in (
        "lapId",
        "lapTime",
        "lapNumber",
        "sampleCount",
        "carModel",
        "track",
        "finishedLap",
        "isValidLap",
    ):
        if key in summary and key in overview and summary[key] != overview[key]:
            raise MozaImportError("detail_summary_conflict")
    lap_s = _number(overview.get("lapTime"), "invalid_lap_time")
    lap_ms = _lap_milliseconds(lap_s, "invalid_lap_time")
    lap_n = _integer(overview.get("lapNumber"), "invalid_lap_number", 1)
    car_name = _text(overview.get("carModel"), "invalid_car_name")
    producer_track = _object(overview.get("track"), "invalid_track_metadata")
    track_name = _text(producer_track.get("trackName"), "invalid_track_name")
    valid = _flag(overview.get("isValidLap"), "invalid_lap_validity")
    complete = _flag(overview.get("finishedLap"), "invalid_lap_completion")
    points, segments = _points(details)
    if (evaluation is None) != (evaluation_source is None):
        raise MozaImportError("evaluation_source_required")
    evidence = [{"kind": "moza_tracecore_view", "sha256": source["sha256"]}]
    sources = [source]
    if evaluation_source is not None:
        evaluation_source = _source(evaluation_source)
        evidence.append({"kind": "moza_training_evaluation", "sha256": evaluation_source["sha256"]})
        sources.append(evaluation_source)
    evaluation_result, authority = _evaluation(evaluation, identity, lap_ms, lap_n)
    if "identity_join" in evaluation_result:
        for source_flag, view_flag in (("is_valid", valid), ("complete", complete)):
            if evaluation_result.get(source_flag) is not None and view_flag is not None:
                if evaluation_result[source_flag] != view_flag:
                    raise MozaImportError("evaluation_lap_status_conflict")
    conditions = _object(view.get("conditions", {}), "invalid_conditions")
    producer_identity = {}
    for key in ("trackId", "trackConfig", "trackName", "carId"):
        if key in summary and key in producer_track and summary[key] != producer_track[key]:
            raise MozaImportError("producer_track_identity_conflict")
        value = producer_track.get(key, summary.get(key))
        if value not in (None, ""):
            _text(value, "invalid_producer_identity")
        producer_identity[key] = value
    events = _events(details.get("drivingEvents"))
    versions = {}
    for key in ("appVersion", "resourceVersion", "viewVersion"):
        value = view.get(key)
        versions[key] = None if value is None else _text(value, "invalid_source_version")
    if versions["viewVersion"] not in (None, MOZA_VIEW_SCHEMA):
        raise MozaImportError("view_version_mismatch")
    channels = {}
    selected = []
    missing = {}
    incomplete_channels = {}
    for key, (name, unit, scale) in _POINT_CHANNELS.items():
        missing[key] = sum(key not in point for point in points)
        if missing[key]:
            incomplete_channels[key] = {
                "basis": "processed",
                "normalized_unit": unit,
                "scale": scale,
                "values": [point[key] * scale if key in point else None for point in points],
            }
            continue
        selected.append(key)
        channels[name] = {"unit": unit, "basis": "processed", "source_field": key, "scale": scale}
    distances = [point["distance"] for point in points]
    times = [point["time"] for point in points]
    rows = [[point[key] * _POINT_CHANNELS[key][2] for key in selected] for point in points]
    local_id = hashlib.sha256(
        (MOZA_VIEW_SCHEMA + ":" + source["sha256"] + ":" + identity).encode()
    ).hexdigest()
    reasons = [
        "processed_view_not_measured_native_trace",
        "native_combo_layout_unverified",
        "native_steering_semantics_unavailable",
        "elapsed_origin_unverified",
        "native_world_coordinates_unavailable",
        "production_use_not_qualified",
    ]
    if authority == "shared":
        reasons.append("producer_observed_ai_intervention")
    else:
        reasons.append("control_authority_unknown")
    if complete is not True:
        reasons.append("completion_unknown_or_partial")
    if valid is not True:
        reasons.append("validity_unknown_or_invalid")
    record = {
        "schema_version": 1,
        "source": "imported",
        "import_format": MOZA_IMPORT_FORMAT,
        "import_status": "accepted_for_inspection",
        "lap_uuid": "moza-view-lap-" + local_id,
        "session_uuid": "moza-view-artifact-" + source["sha256"],
        "exported_at": source["captured_at"],
        "car": {"id": None, "displayName": car_name},
        "track": {"id": None, "displayName": track_name, "layout": None, "lengthM": None},
        "conditions": dict(conditions),
        "lap": {
            "lap_n": lap_n,
            "lap_ms": lap_ms,
            "is_pb": False,
            "is_valid": valid,
            "complete": complete,
        },
        "setup": {"hash": None, "path": None, "snapshot": {}},
        "trace": {
            "fields": [_POINT_CHANNELS[k][0] for k in selected],
            "samples": rows,
            "samples_count": len(rows),
        },
        "corners": [],
        "coaching": {"rules_hints": [], "sidecar_debrief": None, "corner_advice_used": None},
        "moza": {
            "schema_version": MOZA_VIEW_SCHEMA,
            "producer_lap_id": identity,
            "producer_identity": producer_identity,
            "local_identity_kind": "source_hash_bound_artifact_not_native_session",
            "versions": versions,
            "sources": sources,
            "declared_sample_count": declared_samples,
            "detail_point_count": len(points),
            "missing_channel_counts": missing,
            "incomplete_channels": incomplete_channels,
            "segments": segments,
            "native_identity_verified": False,
            "conditions_status": "producer_unverified" if conditions else "unknown",
            "native_coverage": "unavailable",
            "elapsed_origin": "unknown",
            "processed_extent": {
                "first_time_s": times[0],
                "last_time_s": times[-1],
                "lap_minus_last_time_s": lap_s - times[-1],
                "first_distance": distances[0],
                "last_distance": distances[-1],
                "nonforward_distance_steps": sum(
                    a >= b for a, b in zip(distances, distances[1:], strict=False)
                ),
                "nonforward_time_steps": sum(
                    a >= b for a, b in zip(times, times[1:], strict=False)
                ),
            },
            "evaluation": evaluation_result,
            "diagnostic_events": events,
        },
    }
    record["qualification"] = build_qualification(
        record,
        authority=authority,
        origin=MOZA_IMPORT_FORMAT,
        supported_uses={use: False for use in sorted(USES)},
        channels=channels,
        reasons=reasons,
        evidence=evidence,
        conditions=conditions,
    )
    return record
