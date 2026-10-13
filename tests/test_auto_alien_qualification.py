"""Self-play corpus admission honors the same immutable attribution as refitting."""

import hashlib
import json

import pytest

from tools.ac_harness.auto_alien import load_archive_payloads
from tools.lap_qualification import (
    ATTRIBUTIONS_ENV,
    build_qualification,
    register_attribution,
)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    ledger = tmp_path / "attributions.json"
    ledger.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv(ATTRIBUTIONS_ENV, str(ledger))
    record = {
        "schema_version": 1,
        "source": "in_game",
        "lap_uuid": "test-lap",
        "session_uuid": "test-session",
        "car": {"id": "test-car"},
        "track": {"id": "test-track", "layout": None},
        "lap": {"lap_n": 2, "lap_ms": 90000, "is_valid": True, "is_pb": True},
        "trace": {"fields": ["eMs"], "samples": [[0], [90000]]},
    }
    path = tmp_path / "lap_synthetic.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    envelope = build_qualification(
        record,
        authority="shared",
        origin="synthetic_observation",
        supported_uses={"plant_fit": False},
        evidence=[
            {
                "kind": "observed_ai_intervention",
                "sha256": hashlib.sha256(b"synthetic evidence").hexdigest(),
            }
        ],
    )
    return path, record, envelope


def test_selfplay_loader_preserves_unselected_legacy(corpus):
    path, record, _ = corpus
    payloads, errors = load_archive_payloads([str(path)])
    assert payloads == [record] and errors == []


def test_selfplay_loader_refuses_attributed_native_before_oracle(corpus):
    path, _, envelope = corpus
    raw = path.read_bytes()
    register_attribution(path, envelope)
    payloads, errors = load_archive_payloads([str(path)])
    assert payloads == []
    assert len(errors) == 1 and "control_authority_not_human:shared" in errors[0]
    assert path.read_bytes() == raw


def test_selfplay_loader_checks_original_bytes_even_with_identical_values(corpus):
    path, record, envelope = corpus
    register_attribution(path, envelope)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    payloads, errors = load_archive_payloads([str(path)])
    assert payloads == []
    assert len(errors) == 1 and "attribution_source_hash_mismatch" in errors[0]


def test_selfplay_loader_refuses_explicit_future_schema(corpus):
    path, record, _ = corpus
    record["schema_version"] = 99
    path.write_text(json.dumps(record), encoding="utf-8")
    payloads, errors = load_archive_payloads([str(path)])
    assert payloads == []
    assert "archive_schema_unsupported" in errors[0]


def test_disqualified_managed_record_cannot_hide_duplicate_legacy_candidate(corpus):
    path, record, envelope = corpus
    managed_path = path.with_name("lap_managed.json")
    managed_path.write_text(json.dumps({**record, "qualification": envelope}), encoding="utf-8")
    payloads, errors = load_archive_payloads([str(managed_path), str(path)])
    assert payloads == []
    assert len(errors) == 2
    assert all("duplicate_archive_identity" in error for error in errors)
