"""Offline oracle semantics over synthetic views, never vendor/personal fixtures."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from tools.ai_sidecar.coaching_oracle import CoachingOracle, CoachingSnapshot, parse_overlay_text
from tools.ai_sidecar.moza_coaching_oracle import MozaOfflineOracle, inspect_moza_view
from tools.moza_ingest.reader import MozaImportError


def _view():
    overview = {
        "lapId": "synthetic-selected",
        "lapNumber": 2,
        "lapTime": 10.0,
        "sampleCount": 3,
        "finishedLap": True,
        "isValidLap": True,
        "carModel": "Synthetic Car",
        "track": {"trackName": "Synthetic Track", "trackId": "synthetic", "trackConfig": ""},
    }
    points = [
        {"distance": 1, "time": 0.1, "speed": 100},
        {"distance": 990, "time": 9.9, "speed": 110},
    ]
    return {
        "schemaVersion": "tracecore.view.v1",
        "overview": overview,
        "details": {
            "lapId": "synthetic-selected",
            "summary": {},
            "segments": [
                {
                    "id": 1,
                    "startDistance": 0,
                    "endDistance": 1000,
                    "startMapProgress": 0,
                    "endMapProgress": 1,
                    "points": points,
                }
            ],
        },
    }


def _evaluation(evaluated=0, intervened=True):
    return {
        "schemaVersion": 1,
        "sessionId": "synthetic-session",
        "algorithmVersion": "synthetic",
        "summary": {
            "observedLapCount": 1,
            "completeLapCount": 1,
            "evaluatedLapCount": evaluated,
            "laps": [
                {
                    "id": "synthetic-selected",
                    "recordUid": "synthetic-selected",
                    "sessionId": "synthetic-session",
                    "lapNumber": 2,
                    "lapTimeSeconds": 10.0,
                    "complete": True,
                    "finalized": True,
                    "isValidLap": True,
                    "aiIntervened": intervened,
                    "eligibility": "ai-debug-only" if intervened else "unverified-status",
                    "totalScore": 99,
                    "dimensions": [{"score": 100}],
                }
            ],
        },
    }


def _source(value):
    raw = json.dumps(value, allow_nan=False).encode()
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "status": "stable_captured_bytes",
        "captured_at": "2026-10-13T00:00:00+00:00",
    }


def _inspect(view=None, evaluation=None, selected="synthetic-selected"):
    view = _view() if view is None else view
    return inspect_moza_view(
        view,
        source=_source(view),
        selected_lap_id=selected,
        evaluation=evaluation,
        evaluation_source=_source(evaluation) if evaluation is not None else None,
    )


def test_zero_evaluations_with_scores_remain_unavailable():
    result = _inspect(evaluation=_evaluation())
    assert result.status == "unavailable" and result.reason == "zero_evaluated_laps"
    assert result.snapshot is None
    assert result.metadata["control_authority"] == "shared"
    assert result.metadata["source_identity_confidence"] == "exact_producer_join"
    assert result.metadata["coaching_confidence"] == "unknown"
    assert result.metadata["evaluation"]["state"] == "none_evaluated"
    assert result.metadata["evaluation"]["advice_available"] is False
    assert "totalScore" in result.metadata["evaluation"]["observed_score_fields"]
    assert "advisories" not in result.to_dict()
    json.dumps(result.to_dict(), allow_nan=False)
    assert result.as_dict() == result.to_dict()


def test_positive_aggregate_count_never_certifies_selected_lap_or_expert_advice():
    ev = _evaluation(evaluated=1, intervened=False)
    ev["summary"]["laps"][0]["advice"] = "Brake later"
    result = _inspect(evaluation=ev)
    assert result.reason == "producer_advice_schema_unsupported"
    assert result.metadata["evaluation"]["state"] == "selected_eligibility_unverified"
    assert result.metadata["control_authority"] == "unknown"
    assert result.snapshot is None
    assert "Brake later" not in json.dumps(result.to_dict())


def test_events_are_annotations_not_causal_coaching():
    view = _view()
    interval = {
        "startDistance": 20,
        "endDistance": 30,
        "startMapProgress": 0.02,
        "endMapProgress": 0.03,
        "startTime": 1,
        "endTime": 2,
    }
    view["details"]["drivingEvents"] = {
        "axis": "mapDistance",
        "distanceUnit": "m",
        "series": [{"id": "tire_slip", "available": True, "intervals": [interval]}],
    }
    result = _inspect(view)
    assert result.reason == "evaluation_not_selected"
    assert "producer_events_not_causal_advice" in result.reasons
    assert result.metadata["event_annotations"]["status"] == "unqualified"
    assert result.metadata["event_annotations"]["series"][0]["intervals"] == [interval]
    assert result.snapshot is None


@pytest.mark.parametrize(
    "selected,reason",
    [
        (None, "selected_lap_identity_required"),
        ("", "selected_lap_identity_required"),
        ("other", "selected_lap_identity_mismatch"),
    ],
)
def test_exact_selected_identity_required(selected, reason):
    assert _inspect(selected=selected).reason == reason


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda v: v.update(schemaVersion="unknown"), "unsupported_view_schema"),
        (lambda v: v["details"].update(lapId="other"), "lap_identity_mismatch"),
        (lambda v: v.update(details=[]), "invalid_details"),
    ],
)
def test_source_errors_reuse_importer_rejections(mutation, reason):
    view = _view()
    mutation(view)
    result = _inspect(view)
    assert result.reason == reason and result.metadata["input_status"] == "rejected"


def test_evaluation_join_is_not_inferred_from_matching_time():
    ev = _evaluation()
    ev["summary"]["laps"][0].update(id="other", recordUid="other")
    result = _inspect(evaluation=ev)
    assert result.reason == "evaluation_identity_unmatched"
    assert result.metadata["source_identity_confidence"] == "view_only"
    assert result.metadata["control_authority"] == "unknown"


@pytest.mark.parametrize("value", [None, [], "not a view", 5])
def test_non_object_direct_input_is_rejected(value):
    result = inspect_moza_view(value, source=_source(value), selected_lap_id="synthetic-selected")
    assert result.reason == "invalid_view" and result.snapshot is None


@pytest.mark.parametrize(
    "archive",
    [
        {"session_uuid": "native-session", "lap_n": 2, "lap_ms": 10000, "source": "in_game"},
        {"import_format": "moza_tracecore_view_v1", "lap_ms": 10000},
    ],
)
def test_archive_cannot_reconstruct_producer_identity_from_same_lap_and_time(archive, tmp_path):
    selected, evaluation = tmp_path / "archive.json", tmp_path / "evaluation.json"
    selected.write_text(json.dumps(archive))
    evaluation.write_text(json.dumps(_evaluation()))
    result = MozaOfflineOracle(
        cache_path=selected,
        selected_lap_id="synthetic-selected",
        evaluation_path=evaluation,
    ).inspect()
    assert result.reason == "original_moza_view_unavailable" and result.snapshot is None
    assert "source_identity_confidence" not in result.metadata


def test_duplicate_evaluation_identity_is_rejected():
    ev = _evaluation()
    ev["summary"]["laps"].append(copy.deepcopy(ev["summary"]["laps"][0]))
    result = _inspect(evaluation=ev)
    assert result.reason == "duplicate_evaluation_identity"
    assert result.snapshot is None


def test_ai_debug_and_empty_result_do_not_create_snapshot():
    assert _inspect(evaluation=_evaluation(evaluated=1)).reason == "ai_debug_only"
    result = _inspect(evaluation={"schemaVersion": 1, "summary": None})
    assert result.reason == "no_evaluation_summary" and result.snapshot is None


def test_incomplete_and_invalid_laps_are_explicit():
    for flag, reason in (
        ("complete", "evaluation_incomplete"),
        ("isValidLap", "evaluation_invalid"),
    ):
        view, ev = _view(), _evaluation(evaluated=1, intervened=False)
        ev["summary"]["laps"][0][flag] = False
        view["overview"]["finishedLap" if flag == "complete" else "isValidLap"] = False
        result = _inspect(view, evaluation=ev)
        assert result.reason == reason and result.snapshot is None


def test_file_provider_is_optional_and_implements_existing_oracle(tmp_path):
    cache, ev_path = tmp_path / "cache.json", tmp_path / "evaluation.json"
    raw = json.dumps(_view()).encode()
    cache.write_bytes(raw)
    ev_path.write_text(json.dumps(_evaluation()))
    oracle = MozaOfflineOracle(
        cache_path=cache,
        selected_lap_id="synthetic-selected",
        evaluation_path=ev_path,
        expected_cache_sha256=hashlib.sha256(raw).hexdigest(),
    )
    assert isinstance(oracle, CoachingOracle)
    assert oracle.inspect().reason == "zero_evaluated_laps"
    assert oracle.get_coaching() is None
    assert cache.read_bytes() == raw


def test_file_errors_hashes_and_unsupported_schema_are_unavailable(tmp_path):
    cache = tmp_path / "cache.json"
    oracle = MozaOfflineOracle(cache_path=cache, selected_lap_id="synthetic-selected")
    assert oracle.inspect().reason == "input_unavailable_or_changed"
    cache.write_text(json.dumps(_view()))
    oracle.expected_cache_sha256 = "0" * 64
    assert oracle.inspect().reason == "selected_cache_hash_mismatch"
    oracle.expected_cache_sha256 = None
    oracle.evaluation_path = tmp_path / "missing.json"
    result = oracle.inspect()
    assert result.reason == "input_unavailable_or_changed"
    assert result.metadata["input_role"] == "evaluation"
    oracle.evaluation_path = None
    oracle.expected_evaluation_sha256 = "0" * 64
    assert oracle.inspect().reason == "evaluation_file_required"
    oracle.expected_evaluation_sha256 = None
    oracle.evaluation_path = tmp_path / "evaluation.json"
    oracle.evaluation_path.write_text(json.dumps(_evaluation()))
    oracle.expected_evaluation_sha256 = "0" * 64
    assert oracle.inspect().reason == "selected_evaluation_hash_mismatch"
    oracle.expected_evaluation_sha256 = hashlib.sha256(
        oracle.evaluation_path.read_bytes()
    ).hexdigest()
    assert oracle.inspect().reason == "zero_evaluated_laps"
    oracle.evaluation_path = None
    oracle.expected_evaluation_sha256 = None
    cache.write_text('{"schemaVersion":"unknown"}')
    assert oracle.inspect().reason == "unsupported_view_schema"


def test_reader_instability_propagates_without_fallback(tmp_path, monkeypatch):
    from tools.ai_sidecar import moza_coaching_oracle as module

    def changed(_path):
        raise MozaImportError("input_changed_during_read")

    monkeypatch.setattr(module, "read_selected_json", changed)
    result = MozaOfflineOracle(
        cache_path=tmp_path / "cache.json", selected_lap_id="synthetic-selected"
    ).inspect()
    assert result.reason == "input_changed_during_read" and result.snapshot is None


def test_track_titan_defaults_and_snapshot_shape_are_unchanged():
    snapshot = parse_overlay_text(["post-lap debrief: improve throttle application"])
    assert isinstance(snapshot, CoachingSnapshot)
    assert snapshot.source == "track_titan" and snapshot.advisories
    assert snapshot.suggestion_state == "post_lap_debrief"
    assert "metadata" not in snapshot.as_dict()
