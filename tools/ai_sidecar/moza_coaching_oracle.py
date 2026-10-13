"""Optional, offline MOZA oracle status over explicitly selected processed views.

The observed tracecore/evaluation schemas contain scores and producer event
annotations, not a validated coaching-advice contract. They cannot produce a
CoachingSnapshot yet. This provider reports why advice is unavailable through
the existing CoachingOracle interface without changing Track Titan or voice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tools.ai_sidecar.coaching_oracle import CoachingOracle, CoachingSnapshot
from tools.moza_ingest.normalize import normalize_view
from tools.moza_ingest.reader import MozaImportError, read_selected_json

SOURCE = "moza_racing_lab"
_NO_ADVICE = "producer_advice_schema_unsupported"


@dataclass(frozen=True)
class MozaOracleResult:
    """Advice availability and evidence quality, separate from numeric eligibility."""

    status: str
    reason: str
    reasons: tuple[str, ...]
    source: str = SOURCE
    snapshot: CoachingSnapshot | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_dict(self) -> dict[str, Any]:
        return self.to_dict()


def _unavailable(reason: str, **metadata: Any) -> MozaOracleResult:
    return MozaOracleResult(
        status="unavailable",
        reason=reason,
        reasons=(reason,),
        metadata={"offline_only": True, "coaching_confidence": "unknown", **metadata},
    )


def _selected_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 512
        and not any(ord(c) < 32 for c in value)
    )


def inspect_moza_view(
    view: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    selected_lap_id: str,
    evaluation: Mapping[str, Any] | None = None,
    evaluation_source: Mapping[str, Any] | None = None,
) -> MozaOracleResult:
    """Inspect captured inputs through the existing importer; never invent advice.

    Callers with only a native or normalized archive must retain
    ``original_moza_view_unavailable`` rather than reconstruct producer inputs.
    Exact source receipts come from moza_ingest.read_selected_json. Cross-file
    reads are individually stable, not an atomic producer snapshot.
    """
    if not _selected_id(selected_lap_id):
        return _unavailable("selected_lap_identity_required")
    if (
        isinstance(view, Mapping)
        and "schemaVersion" not in view
        and ("import_format" in view or "session_uuid" in view or "lap_ms" in view)
    ):
        # Archive identity/timing is not a producer cache identity. A normalized
        # archive also cannot reconstruct its original captured producer view.
        return _unavailable("original_moza_view_unavailable", input_status="rejected")
    try:
        record = normalize_view(
            view,
            source=source,
            evaluation=evaluation,
            evaluation_source=evaluation_source,
        )
    except MozaImportError as exc:
        return _unavailable(str(exc), input_status="rejected")
    moza = record["moza"]
    if moza["producer_lap_id"] != selected_lap_id:
        return _unavailable("selected_lap_identity_mismatch", input_status="rejected")
    evaluation_info = moza["evaluation"]
    counts = dict(evaluation_info.get("counts", {}))
    joined = "identity_join" in evaluation_info
    evaluation_state = "unavailable"
    reason = evaluation_info["reason"]
    if joined:
        if counts.get("evaluatedLapCount") == 0:
            evaluation_state, reason = "none_evaluated", "zero_evaluated_laps"
        elif (
            evaluation_info.get("ai_intervened") is True
            or evaluation_info.get("producer_eligibility") == "ai-debug-only"
        ):
            evaluation_state, reason = "ai_assisted_ineligible", "ai_debug_only"
        elif evaluation_info.get("complete") is False or evaluation_info.get("finalized") is False:
            evaluation_state, reason = "incomplete", "evaluation_incomplete"
        elif evaluation_info.get("is_valid") is False:
            evaluation_state, reason = "invalid", "evaluation_invalid"
        else:
            # An aggregate count and an opaque eligibility string do not certify
            # this selected lap as evaluated, or define an expert-advice schema.
            evaluation_state, reason = "selected_eligibility_unverified", _NO_ADVICE
    events = moza["diagnostic_events"]
    reasons = [reason]
    if events.get("present"):
        reasons.append("producer_events_not_causal_advice")
    reasons.append(_NO_ADVICE)
    return MozaOracleResult(
        status="unavailable",
        reason=reason,
        reasons=tuple(dict.fromkeys(reasons)),
        metadata={
            "offline_only": True,
            "input_status": record["import_status"],
            "schema_version": moza["schema_version"],
            "selected_lap_id": selected_lap_id,
            "source_hashes": [item["sha256"] for item in moza["sources"]],
            "source_identity_confidence": "exact_producer_join" if joined else "view_only",
            "coaching_confidence": "unknown",
            "cross_file_atomic": False,
            "control_authority": record["qualification"]["authority"],
            "evaluation": {
                "state": evaluation_state,
                "counts": counts,
                "identity_join": evaluation_info.get("identity_join"),
                "producer_eligibility": evaluation_info.get("producer_eligibility"),
                "ai_intervened": evaluation_info.get("ai_intervened"),
                "complete": evaluation_info.get("complete"),
                "finalized": evaluation_info.get("finalized"),
                "is_valid": evaluation_info.get("is_valid"),
                "algorithm_version": evaluation_info.get("algorithm_version"),
                "observed_score_fields": evaluation_info.get("observed_score_fields", []),
                "advice_available": False,
            },
            # Keep producer annotations visibly unqualified. They never enter
            # snapshot.advisories, debrief text, the TT parser or the scheduler.
            "event_annotations": events,
        },
    )


def _expected_hash_matches(expected: str | None, actual: str) -> bool:
    return expected is None or (
        isinstance(expected, str)
        and len(expected) == 64
        and all(char in "0123456789abcdef" for char in expected)
        and expected == actual
    )


class MozaOfflineOracle(CoachingOracle):
    """Read only selected files on demand; no discovery, cloud, capture or activation."""

    def __init__(
        self,
        *,
        cache_path: Path,
        selected_lap_id: str,
        evaluation_path: Path | None = None,
        expected_cache_sha256: str | None = None,
        expected_evaluation_sha256: str | None = None,
    ) -> None:
        self.cache_path = cache_path
        self.selected_lap_id = selected_lap_id
        self.evaluation_path = evaluation_path
        self.expected_cache_sha256 = expected_cache_sha256
        self.expected_evaluation_sha256 = expected_evaluation_sha256

    def inspect(self) -> MozaOracleResult:
        """Return explicit source/eligibility status; file errors are unavailable."""
        if not _selected_id(self.selected_lap_id):
            return _unavailable("selected_lap_identity_required")
        if self.evaluation_path is None and self.expected_evaluation_sha256 is not None:
            return _unavailable("evaluation_file_required")
        try:
            cache = read_selected_json(self.cache_path)
        except MozaImportError as exc:
            return _unavailable(str(exc), input_status="rejected", input_role="cache")
        if not _expected_hash_matches(self.expected_cache_sha256, cache.receipt["sha256"]):
            return _unavailable("selected_cache_hash_mismatch", input_status="rejected")
        evaluation = None
        if self.evaluation_path is not None:
            try:
                evaluation = read_selected_json(self.evaluation_path)
            except MozaImportError as exc:
                return _unavailable(str(exc), input_status="rejected", input_role="evaluation")
            if not _expected_hash_matches(
                self.expected_evaluation_sha256, evaluation.receipt["sha256"]
            ):
                return _unavailable("selected_evaluation_hash_mismatch", input_status="rejected")
        return inspect_moza_view(
            cache.payload,
            source=cache.receipt,
            selected_lap_id=self.selected_lap_id,
            evaluation=evaluation.payload if evaluation is not None else None,
            evaluation_source=evaluation.receipt if evaluation is not None else None,
        )

    def get_coaching(self) -> CoachingSnapshot | None:
        return self.inspect().snapshot
