"""Bound repeated policy work without weakening fresh-request qualification."""

import json
from collections import Counter

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
    snapshots = []
    original = lap_qualification.ArchiveQualificationSnapshot.qualify

    def counted(self, *, use, expected_combo=None):
        snapshots.append(self)  # Keep object identities distinct during the measurement.
        calls[(id(self), use, expected_combo)] += 1
        return original(self, use=use, expected_combo=expected_combo)

    monkeypatch.setattr(lap_qualification.ArchiveQualificationSnapshot, "qualify", counted)
    actual = report.build_session_report([session_corpus], generated_at="fixed")
    assert actual["session"]["valid_laps"] == 2
    assert max(calls.values()) == 1

    # Compare every output field with the existing policy applied without reuse.
    monkeypatch.setattr(
        report.LoadedLap,
        "qualify",
        lambda self, *, use, expected_combo=None: report.qualify_archive(
            self.record, use=use, expected_combo=expected_combo
        ),
    )
    assert report.build_session_report([session_corpus], generated_at="fixed") == actual


def test_snapshot_reuses_integrity_and_trace_checks_without_cross_call_cache(monkeypatch):
    from tests.test_lap_qualification import archive

    record = archive()
    record["qualification"] = assessment(record, authority="human", promoted=True)
    combo = lap_qualification.archive_combo(record)
    expected = {
        use: lap_qualification.qualify_archive(record, use=use, expected_combo=combo)
        for use in lap_qualification.USES
    }
    calls = Counter()
    digest = lap_qualification.payload_sha256
    trace = lap_qualification._trace_reasons

    def counted_digest(record):
        calls["digest"] += 1
        return digest(record)

    def counted_trace(record, envelope):
        calls["trace"] += 1
        return trace(record, envelope)

    monkeypatch.setattr(lap_qualification, "payload_sha256", counted_digest)
    monkeypatch.setattr(lap_qualification, "_trace_reasons", counted_trace)
    snapshot = lap_qualification.ArchiveQualificationSnapshot(record)
    for use, result in expected.items():
        assert snapshot.qualify(use=use, expected_combo=combo) == result
    assert calls == {"digest": 1, "trace": 1}
    record["trace"]["samples"][20][1] += 1
    assert (
        "qualification_payload_mismatch"
        in lap_qualification.qualify_archive(record, use="analysis").reasons
    )


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
