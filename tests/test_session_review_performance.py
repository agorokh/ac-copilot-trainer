"""Bound repeated policy work without weakening fresh-request qualification."""

from collections import Counter
import json

import pytest

from tests.test_lap_qualification import assessment
from tests.test_session_review import session_corpus as session_corpus
from tools import lap_qualification
from tools.session_review import report


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "attributions.json"
    ledger.write_text(json.dumps({"schema_version": 1, "entries": []}))
    monkeypatch.setenv(lap_qualification.ATTRIBUTIONS_ENV, str(ledger))
    return ledger


def test_report_qualifies_each_snapshot_once_per_use_and_combo(session_corpus, monkeypatch):
    calls = Counter()
    original = report.qualify_archive

    def counted(record, *, use, expected_combo=None):
        calls[(record["lap_uuid"], use, expected_combo)] += 1
        return original(record, use=use, expected_combo=expected_combo)

    monkeypatch.setattr(report, "qualify_archive", counted)
    actual = report.build_session_report([session_corpus], generated_at="fixed")
    assert actual["session"]["valid_laps"] == 2
    assert max(calls.values()) == 1

    # Compare every output field with the existing policy applied without reuse.
    monkeypatch.setattr(
        report.LoadedLap,
        "qualify",
        lambda self, *, use, expected_combo=None: original(
            self.record, use=use, expected_combo=expected_combo
        ),
    )
    assert report.build_session_report([session_corpus], generated_at="fixed") == actual


def test_next_report_observes_new_restriction_and_unavailable_ledger(
    session_corpus, isolated_ledger
):
    reference = session_corpus / "lap_ref.json"
    args = {"reference_path": reference, "reference_source": "your-best"}
    first = report.build_session_report([session_corpus], **args)
    assert first["reference"]["source_file"] == reference.name
    record = json.loads(reference.read_text())
    lap_qualification.register_attribution(reference, assessment(record))
    with pytest.raises(report.SessionReviewError, match="control_authority_not_human"):
        report.build_session_report([session_corpus], **args)
    isolated_ledger.unlink()
    with pytest.raises(report.SessionReviewError, match="attribution_store_unavailable"):
        report.build_session_report([session_corpus], **args)


def test_duplicate_scan_resolves_only_colliding_identities(monkeypatch):
    from tests.test_lap_qualification import archive

    records = []
    for i in range(12):
        record = archive()
        record.update(lap_uuid=f"lap-{i}", session_uuid=f"session-{i}")
        records.append(record)
    original = lap_qualification.resolve_archive_provenance
    calls = []

    def counted(record):
        calls.append(record["lap_uuid"])
        return original(record)

    monkeypatch.setattr(lap_qualification, "resolve_archive_provenance", counted)
    assert lap_qualification.duplicate_identity_reasons(records) == {}
    assert calls == []
    records[1] = dict(records[0])
    records[1]["qualification"] = assessment(records[1])
    assert lap_qualification.duplicate_identity_reasons(records) == {
        0: "duplicate_archive_identity",
        1: "duplicate_archive_identity",
    }
    # Both lap UUID and session/lap collide; resolve each contender only once.
    assert calls == ["lap-0", "lap-0"]
