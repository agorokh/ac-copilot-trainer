"""Explicit-file MOZA inspection in the existing offline session-review product.

Selecting this workflow does not attribute control. Processed caches stay
inspection-only; qualified native analysis uses the existing diagnosis engine.
No archive, attribution ledger, profile, runtime or voice state is written here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tools.ai_sidecar.track_map import _channel_valid, _valid_trace, build_corner_comparison
from tools.lap_qualification import (
    _UNITS as _EXPECTED_CHANNEL_UNITS,
)
from tools.lap_qualification import (
    USES,
    archive_combo,
    duplicate_identity_reasons,
    qualify_archive,
    resolve_archive_provenance,
)
from tools.moza_ingest import (
    MOZA_IMPORT_FORMAT,
    MozaImportError,
    normalize_view,
    read_selected_json,
)
from tools.session_review.report import (
    REPORT_SCHEMA_VERSION,
    SessionReviewError,
    _build_report_from_laps,
    _iso_now,
    _loaded_lap,
    _num_ms,
)

_CANONICAL = tuple(_EXPECTED_CHANNEL_UNITS)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _receipt(receipt: Mapping[str, Any], path: Path) -> dict[str, Any]:
    # Saved/shared reports use basenames, never the source's absolute host path.
    return {key: value for key, value in receipt.items() if key != "path"} | {"file": path.name}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "corners": []}


def _channels(record: Mapping[str, Any], *, inspection: bool) -> list[dict[str, Any]]:
    fields = _mapping(record.get("trace")).get("fields", [])
    fields = fields if isinstance(fields, list) else []
    metadata = _mapping(_mapping(record.get("qualification")).get("channels"))
    managed = "qualification" in record or inspection
    names = list(dict.fromkeys([*_CANONICAL, *(name for name in fields if isinstance(name, str))]))
    result = []
    for name in names:
        channel = _mapping(metadata.get(name))
        present = name in fields
        try:
            valid = present and _channel_valid(dict(record), name)
        except (AttributeError, OverflowError):
            valid = False
        basis = channel.get("basis") or ("legacy_unverified" if present else "unavailable")
        semantics_known = (
            name in _EXPECTED_CHANNEL_UNITS
            and channel.get("unit") == _EXPECTED_CHANNEL_UNITS[name]
            and channel.get("basis") == "measured"
        ) or (not managed and name in _CANONICAL)
        reason = (
            "missing_channel"
            if not present
            else (
                "processed_inspection_only"
                if inspection
                else (
                    "nonfinite_or_missing_channel_values"
                    if not valid
                    else (
                        "channel_semantics_unverified"
                        if not semantics_known
                        else "present_in_archive"
                    )
                )
            )
        )
        result.append(
            {
                "name": name,
                "present": present,
                "available": bool(valid and semantics_known and not inspection),
                "unit": channel.get("unit"),
                "basis": basis,
                "reason": reason,
            }
        )
    return result


def _base_report(path: Path, *, generated_at: str | None, driver_id: str) -> dict[str, Any]:
    identity = hashlib.sha256(str(path.absolute()).encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at or _iso_now(),
        "driver_id": driver_id,
        "session": {
            "session_uuid": "offline-selection-" + identity,
            "car_id": None,
            "track_id": None,
            "track_layout": None,
            "lap_count": 0,
            "valid_laps": 0,
            "best_lap_ms": None,
            "median_lap_ms": None,
            "consistency_ms": None,
        },
        "reference": None,
        "reference_selection": {"requested_source": "none", "reason": "offline inspection"},
        "problems": [],
        "next_session_prep": [],
        "history": {},
        "comparison": {"laps": [], "default_pair": {"a": None, "b": None}},
        "map_comparison": _unavailable("matched_native_not_selected"),
        "share": {
            "formats": ["html", "markdown", "json"],
            "self_contained_html": True,
            "host_paths_in_broadcasts": False,
        },
        "spoken_summary": "",
        "screen_summary": [],
        "source": {"lap_files": 0, "selected_lap_files": [path.name], "skipped": []},
    }


def _capture_archive(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    captured = read_selected_json(path)
    _require_archive_schema(captured.payload)
    record = resolve_archive_provenance(captured.payload, source_sha256=captured.receipt["sha256"])
    return record, _receipt(captured.receipt, path)


def _require_archive_schema(record: Mapping[str, Any]) -> None:
    # Match the ordinary report's strict path-loader contract. The permissive
    # direct-constructor legacy policy is not a file-ingest schema validator.
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise MozaImportError("unsupported_archive_schema")
    trace = record.get("trace")
    if (
        not isinstance(trace, dict)
        or not isinstance(trace.get("fields"), list)
        or not isinstance(trace.get("samples"), list)
    ):
        raise MozaImportError("invalid_archive_trace")


def _numeric_reason(record: dict[str, Any], channels: list[dict[str, Any]]) -> str | None:
    decision = qualify_archive(record, use="analysis")
    if not decision.allowed:
        return decision.reason
    if record.get("source") != "in_game":
        return "selected_native_source_required"
    missing = [
        row["name"] for row in channels if row["name"] in _CANONICAL and not row["available"]
    ]
    if missing:
        return "analysis_channels_unavailable:" + ",".join(missing)
    if _valid_trace(record) is None:
        return "completed_measured_trace_unavailable"
    return None


def _comparison(
    record: dict[str, Any],
    receipt: Mapping[str, Any],
    matched_path: Path | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if matched_path is None:
        return _unavailable("matched_native_not_selected"), None
    try:
        matched, matched_receipt = _capture_archive(matched_path)
    except MozaImportError as exc:
        return _unavailable("matched_native:" + str(exc)), {"file": matched_path.name}
    info = {
        **matched_receipt,
        "source": matched.get("source"),
        "authority": qualify_archive(matched, use="analysis").authority,
        "association": "user_selected_comparison_not_recording_identity_proof",
    }
    if matched.get("source") != "in_game":
        return _unavailable("matched_native_source_required"), info
    if receipt.get("sha256") == matched_receipt.get("sha256"):
        return _unavailable("same_artifact_not_independent_comparison"), info
    if duplicate_identity_reasons([record, matched]):
        return _unavailable("duplicate_archive_identity"), info
    for prefix, candidate in (("selected_analysis", record), ("matched_native_analysis", matched)):
        reason = _numeric_reason(
            candidate,
            _channels(candidate, inspection=candidate.get("import_format") == MOZA_IMPORT_FORMAT),
        )
        if reason:
            return _unavailable(prefix + ":" + reason), info
    combo = archive_combo(record)
    if combo is None or archive_combo(matched) != combo:
        return _unavailable("matched_native_combo_mismatch_or_unavailable"), info
    reference = qualify_archive(matched, use="reference_comparison", expected_combo=combo)
    if not reference.allowed:
        return _unavailable("matched_native_reference:" + reference.reason), info
    comparison = build_corner_comparison(record, matched)
    comparison["interpretation"] = (
        "offline_numeric_comparison_not_human_achievement_or_control_proof"
    )
    return comparison, info


def build_moza_session_report(
    selected_file: str | Path,
    *,
    matched_native_file: str | Path | None = None,
    evaluation_file: str | Path | None = None,
    oracle_enabled: bool = False,
    driver_id: str = "local-driver",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the existing report shape, including truthful unavailable selections.

    Only the explicitly supplied files are captured. An evaluation failure does
    not destroy valid numeric inspection; it remains a separate unavailable lane.
    """
    path = Path(selected_file)
    report = _base_report(path, generated_at=generated_at, driver_id=driver_id)
    review: dict[str, Any] = {
        "schema_version": 1,
        "workflow": "moza_offline_review",
        "status": "input_unavailable",
        "available": False,
        "reason": "input_unavailable",
        "authority": "unknown",
        "selected": {"file": path.name},
        "qualification": {},
        "channels": [],
        "numeric_analysis": _unavailable("input_unavailable"),
        "matched_native": None,
        "native_comparison": _unavailable("matched_native_not_selected"),
        "oracle": {
            "enabled": oracle_enabled,
            "status": "unavailable",
            "reason": "oracle_disabled" if not oracle_enabled else "original_moza_view_unavailable",
        },
        "evaluation": {"status": "unavailable", "reason": "evaluation_not_selected"},
    }
    report["moza_review"] = review
    try:
        captured = read_selected_json(path)
    except MozaImportError as exc:
        review["reason"] = str(exc)
        review["numeric_analysis"] = _unavailable(str(exc))
        report["screen_summary"] = ["Offline review unavailable: " + str(exc)]
        return report
    source = captured.receipt
    review["selected"].update(_receipt(source, path))
    raw_view = None
    evaluation = None
    evaluation_source = None
    evaluation_error = None
    if evaluation_file is not None:
        try:
            evaluated = read_selected_json(Path(evaluation_file))
            evaluation, evaluation_source = evaluated.payload, evaluated.receipt
            review["evaluation"] = {
                "status": "captured",
                **_receipt(evaluation_source, Path(evaluation_file)),
            }
        except MozaImportError as exc:
            evaluation_error = str(exc)
            review["evaluation"] = {"status": "unavailable", "reason": evaluation_error}
    payload = captured.payload
    try:
        if "schemaVersion" in payload or "overview" in payload or "details" in payload:
            raw_view = payload
            kind = "moza_processed_view"
            # Parse cache independently, retaining its inspection even if the optional join fails.
            record = normalize_view(raw_view, source=source)
            if evaluation is not None:
                try:
                    record = normalize_view(
                        raw_view,
                        source=source,
                        evaluation=evaluation,
                        evaluation_source=evaluation_source,
                    )
                except MozaImportError as exc:
                    evaluation_error = str(exc)
                    review["evaluation"].update(status="unavailable", reason=evaluation_error)
        else:
            _require_archive_schema(payload)
            record = resolve_archive_provenance(payload, source_sha256=source["sha256"])
            kind = (
                "moza_inspection_archive"
                if record.get("import_format") == MOZA_IMPORT_FORMAT
                else ("native_archive" if record.get("source") == "in_game" else "lap_archive")
            )
    except MozaImportError as exc:
        review.update(reason=str(exc))
        review["numeric_analysis"] = _unavailable(str(exc))
        report["screen_summary"] = ["Offline review unavailable: " + str(exc)]
        return report
    inspection = record.get("import_format") == MOZA_IMPORT_FORMAT
    decisions = {use: asdict(qualify_archive(record, use=use)) for use in sorted(USES)}
    review["qualification"] = decisions
    review["authority"] = decisions["analysis"]["authority"]
    review["channels"] = _channels(record, inspection=inspection)
    review["selected"].update(
        kind=kind, source=record.get("source"), import_format=record.get("import_format")
    )
    lap, car, track = (_mapping(record.get(key)) for key in ("lap", "car", "track"))
    review["observed_lap"] = {
        "lap_n": lap.get("lap_n"),
        "lap_ms": _num_ms(lap.get("lap_ms")),
        "is_valid": lap.get("is_valid"),
        "complete": lap.get("complete"),
    }
    report["session"].update(
        session_uuid=record.get("session_uuid") or report["session"]["session_uuid"],
        car_id=car.get("id") or car.get("displayName"),
        track_id=track.get("id") or track.get("displayName"),
        track_layout=track.get("layout"),
        lap_count=1,
    )
    if inspection:
        metadata = _mapping(record.get("moza"))
        review["inspection"] = {
            key: metadata.get(key)
            for key in (
                "versions",
                "declared_sample_count",
                "detail_point_count",
                "missing_channel_counts",
                "processed_extent",
                "conditions_status",
                "native_coverage",
                "elapsed_origin",
            )
        }
        review["inspection"]["producer_identity_status"] = "not_native_identity_proof"
        if evaluation_error is None:
            review["evaluation"].update(_mapping(metadata.get("evaluation")))
    elif evaluation is not None:
        review["evaluation"].update(status="unavailable", reason="original_moza_view_unavailable")
    numeric_reason = _numeric_reason(record, review["channels"])
    available = numeric_reason is None
    if available:
        try:
            report = _build_report_from_laps(
                [_loaded_lap(path, record)],
                [],
                session=str(record.get("session_uuid") or "unknown_session"),
                driver_id=driver_id,
                generated_at=generated_at,
                reference_source="none",
                include_corner_observations=True,
            )
            report["moza_review"] = review
            review["corner_observations"] = report.pop("corner_observations", [])
        except SessionReviewError as exc:
            available, numeric_reason = False, "native_analysis_unavailable:" + str(exc)
    review.update(
        available=available,
        status="analysis_available" if available else "inspection_only",
        reason="qualified_numeric_analysis" if available else numeric_reason,
    )
    review["numeric_analysis"] = {"available": available, "reason": review["reason"]}
    if not available:
        for channel in review["channels"]:
            if channel["available"]:
                channel.update(available=False, reason="analysis_unavailable:" + review["reason"])
    matched_path = Path(matched_native_file) if matched_native_file is not None else None
    comparison, matched_info = _comparison(record, source, matched_path)
    review["native_comparison"], review["matched_native"] = comparison, matched_info
    report["map_comparison"] = comparison
    if oracle_enabled:
        if evaluation_error is not None:
            review["oracle"].update(reason=evaluation_error)
        elif raw_view is not None:
            from tools.ai_sidecar.moza_coaching_oracle import inspect_moza_view

            result = inspect_moza_view(
                raw_view,
                source=source,
                selected_lap_id=_mapping(raw_view.get("overview")).get("lapId"),
                evaluation=evaluation,
                evaluation_source=evaluation_source,
            )
            review["oracle"] = {"enabled": True, **result.to_dict()}
    # Workflow choice never turns legacy unknown or assisted control into human progress.
    report["session"].update(
        best_lap_ms=None,
        best_lap_uuid=None,
        best_source_file=None,
        median_lap_ms=None,
        consistency_ms=None,
    )
    report.update(history={}, spoken_summary="", next_session_prep=[], problems=[])
    report["comparison"] = {"laps": [], "default_pair": {"a": None, "b": None}}
    report["screen_summary"] = [
        f"Selected source: {record.get('source') or 'unknown'}; control: {review['authority']}",
        f"Numeric analysis: {review['reason']}",
        f"Native comparison: {comparison['reason']}",
    ]
    return report
