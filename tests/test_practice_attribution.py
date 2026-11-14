"""Attestation is prospective, scoped, source-bound and subordinate to restrictions."""

from __future__ import annotations

import copy
import json
import threading
from types import SimpleNamespace

import pytest

from tests.test_human_session import complete_native_lap, session_fixture
from tests.test_lap_qualification import archive, assessment
from tools.human_session import PRACTICE_COMBO, HumanSessionError
from tools.lap_archive_export import load_lap_archive
from tools.lap_qualification import (
    SCOPED_USES,
    USES,
    AttributionError,
    is_practice_human,
    qualify_archive,
    qualify_practice_archive,
    register_attribution,
    register_practice_attribution,
)


def raw_archive(ordinal=1):
    record = archive()
    record.update(session_uuid="synthetic-native-session", lap_uuid=f"synthetic-live-lap-{ordinal}")
    record["car"]["id"] = PRACTICE_COMBO[0]
    record["track"].update(id=PRACTICE_COMBO[1], layout=None)
    record["lap"]["lap_n"] = ordinal
    return record


def setup_native(tmp_path, monkeypatch):
    ledger = tmp_path / "journal" / "lap-attributions.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    permit, root = session_fixture(tmp_path)
    return permit, root, ledger


def complete_archive(permit, root, ordinal=1, record=None):
    complete_native_lap(permit, ordinal, begin=ordinal == 1)
    path = root / f"lap_synthetic_{ordinal}.json"
    path.write_text(
        json.dumps(raw_archive(ordinal) if record is None else record), encoding="utf-8"
    )
    return path


def test_scoped_native_attestation_preserves_raw_and_never_grants_generic_use(
    tmp_path, monkeypatch
):
    permit, root, ledger = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    before = path.read_bytes()
    receipt = register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    assert receipt["registered"] and path.read_bytes() == before
    record = load_lap_archive(path)
    envelope = record["qualification"]
    assert envelope["authority"] == "attested_human"
    assert [item["kind"] for item in envelope["evidence"]] == ["operator_attested_human_control"]
    for use in SCOPED_USES:
        q = qualify_practice_archive(record, use=use, permit=permit, expected_combo=PRACTICE_COMBO)
        assert q.allowed and q.authority == "attested_human" and is_practice_human(q)
        assert not qualify_archive(record, use=use, expected_combo=PRACTICE_COMBO).allowed
    for use in USES - SCOPED_USES - {"analysis"}:
        q = qualify_archive(record, use=use, expected_combo=PRACTICE_COMBO)
        assert not q.allowed and q.authority == "attested_human"
    assert qualify_archive(record, use="analysis").allowed
    assert len(json.loads(ledger.read_bytes())["entries"]) == 1
    again = register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    assert not again["registered"] and again["reason"] == "already_registered"
    with pytest.raises(AttributionError, match="registration_cannot_certify_human_control"):
        register_attribution(path, envelope)


@pytest.mark.parametrize("authority", ["ai", "shared", "unknown"])
def test_existing_restrictive_entry_wins_and_remains_unchanged(tmp_path, monkeypatch, authority):
    permit, root, ledger = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    record = json.loads(path.read_bytes())
    register_attribution(path, assessment(record, authority=authority))
    original = ledger.read_bytes()
    with pytest.raises(AttributionError, match="conflicting_attribution_identity"):
        register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    assert ledger.read_bytes() == original
    assert permit.status()["reason"] == "restrictive_attribution_conflict"
    q = qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    )
    assert not q.allowed and q.authority == authority


@pytest.mark.parametrize(
    "revoke", ["native_session_changed", "native_control_unproved", "native_session_disconnected"]
)
def test_every_scoped_decision_rechecks_current_permit_after_registration(
    tmp_path, monkeypatch, revoke
):
    permit, root, ledger = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    record = load_lap_archive(path)
    original = ledger.read_bytes()
    permit.revoke(revoke)
    assert not qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed
    assert ledger.read_bytes() == original


def test_source_or_payload_mutation_fails_even_when_old_record_is_cached(tmp_path, monkeypatch):
    permit, root, _ = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    record = load_lap_archive(path)
    changed = copy.deepcopy(record)
    changed["trace"]["samples"][2][1] += 1
    assert not qualify_practice_archive(
        changed, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed
    path.write_bytes(path.read_bytes() + b" ")
    q = qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    )
    assert not q.allowed and "attribution_source_hash_mismatch" in q.reasons


def test_only_first_two_attempted_ordinals_can_supply_reference(tmp_path, monkeypatch):
    permit, root, _ = setup_native(tmp_path, monkeypatch)
    for ordinal in range(1, 4):
        path = complete_archive(permit, root, ordinal)
        register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
        q = qualify_practice_archive(
            load_lap_archive(path),
            use="practice_reference",
            permit=permit,
            expected_combo=PRACTICE_COMBO,
        )
        assert q.allowed is (ordinal <= 2)
        assert qualify_practice_archive(
            load_lap_archive(path),
            use="practice_trial",
            permit=permit,
            expected_combo=PRACTICE_COMBO,
        ).allowed


def test_preexisting_file_replayed_path_and_wrong_root_cannot_be_promoted(tmp_path, monkeypatch):
    ledger = tmp_path / "journal" / "lap-attributions.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    root = ledger.parent / "laps"
    root.mkdir()
    historical = root / "lap_historical.json"
    historical.write_text(json.dumps(raw_archive()), encoding="utf-8")
    permit, _ = session_fixture(tmp_path)
    complete_native_lap(permit)
    with pytest.raises(HumanSessionError, match="archive_predates_admission"):
        permit.accept_archive(historical)
    foreign = tmp_path / "other" / "journal" / "laps" / "lap_foreign.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(historical.read_bytes())
    with pytest.raises(HumanSessionError, match="archive_outside_native_root"):
        permit.accept_archive(foreign)


def test_inline_or_handmade_embedded_attestation_never_replaces_canonical_append(
    tmp_path, monkeypatch
):
    permit, root, ledger = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    receipt = register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    record = load_lap_archive(path)
    ledger.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")
    record["qualification"] = receipt["qualification"]
    q = qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    )
    assert not q.allowed and "canonical_practice_attribution_required" in q.reasons


def test_invalid_lap_and_import_remain_ineligible_and_consume_attempts(tmp_path, monkeypatch):
    permit, root, _ = setup_native(tmp_path, monkeypatch)
    record = raw_archive()
    record["lap"]["is_valid"] = False
    path = complete_archive(permit, root, record=record)
    register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    q = qualify_practice_archive(
        load_lap_archive(path), use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    )
    assert not q.allowed and "lap_validity_unproved" in q.reasons
    assert permit.status(private=True)["attempted_laps"] == 2
    record = raw_archive(2)
    record.update(source="imported", import_format="motec_csv")
    path = complete_archive(permit, root, 2, record=record)
    with pytest.raises(HumanSessionError, match="native_archive_required"):
        register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)


def test_stale_native_context_cannot_qualify_cached_attestation(tmp_path, monkeypatch):
    permit, root, _ = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    record = load_lap_archive(path)
    permit._last_native_seen = 0
    q = qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    )
    assert not q.allowed and "native_session_stale" in q.reasons
    assert permit.status()["phase"] == "aborted"


@pytest.mark.parametrize("disclose", [False, True])
def test_sealed_ten_lap_capture_allows_late_end_form_without_new_eligibility(
    tmp_path, monkeypatch, disclose
):
    from tests.test_human_session import ASSISTANCE

    permit, root, _ = setup_native(tmp_path, monkeypatch)
    for ordinal in range(1, 11):
        path = complete_archive(permit, root, ordinal)
        register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    record = load_lap_archive(path)
    assert qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed
    sealed = permit.seal_capture()
    assert sealed["reason"] == "awaiting_end_declaration" and not sealed["end_confirmed"]
    if disclose:
        stopped = permit.revoke("control_assistance_disclosed")
        assert stopped["phase"] == "aborted" and not stopped["end_confirmed"]
    permit._last_native_seen = 0
    assert not qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed
    end = permit.close({"driver_id": "synthetic-driver", "assistance": ASSISTANCE})
    assert end["end_confirmed"]
    assert end["reason"] == (
        "control_assistance_disclosed" if disclose else "end_declaration_matched"
    )
    assert end["phase"] == ("aborted" if disclose else "closed")
    assert not qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state.update(attempted_laps=0),
        lambda state: state.update(windows={}),
        lambda state: state.update(native={"session_uuid": "synthetic-native-session"}),
        lambda state: state.update(end_confirmed="yes"),
    ],
)
def test_accidental_campaign_field_corruption_rejects_previously_qualified_lap(
    tmp_path, monkeypatch, mutate
):
    permit, root, ledger = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    record = load_lap_archive(path)
    assert qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed
    raw_before, ledger_before = path.read_bytes(), ledger.read_bytes()
    state = json.loads(permit.path.read_bytes())
    mutate(state)
    permit.path.write_text(json.dumps(state), encoding="utf-8")
    decision = qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    )
    assert not decision.allowed and "campaign_state_invalid" in decision.reasons
    assert path.read_bytes() == raw_before and ledger.read_bytes() == ledger_before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state.update(attempted_laps=0),
        lambda state: state.update(windows={}),
        lambda state: state.update(native={"session_uuid": "synthetic-native-session"}),
        lambda state: state.update(end_confirmed=True),
        lambda state: state["owner_process"].update(pid=0),
        lambda state: state["archives"]["1"].update(declaration_sha256="0" * 64),
        lambda state: state["archives"]["1"]["identity"].update(lap_n=2),
        lambda state: state["windows"]["1"].update(closed=False),
        lambda state: state.update(schema_version=True),
    ],
)
def test_rechecksummed_cross_field_inconsistency_is_still_invalid(tmp_path, monkeypatch, mutate):
    from tools.human_session import _state_digest

    permit, root, _ = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    state = json.loads(permit.path.read_bytes())
    mutate(state)
    state["revision"] += 1
    state["state_sha256"] = _state_digest(state)
    permit.path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(HumanSessionError, match="campaign_state_invalid"):
        permit.reload()


def test_revocation_during_construction_prevents_canonical_publication(tmp_path, monkeypatch):
    from tools import lap_qualification

    permit, root, ledger = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    original = ledger.read_bytes()
    build = lap_qualification.build_qualification

    def revoke_after_build(*args, **kwargs):
        result = build(*args, **kwargs)
        permit.revoke("native_session_disconnected")
        return result

    monkeypatch.setattr(lap_qualification, "build_qualification", revoke_after_build)
    with pytest.raises(HumanSessionError, match="campaign_not_active"):
        register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    assert ledger.read_bytes() == original


def test_close_cannot_cross_the_attribution_commit_lock(tmp_path, monkeypatch):
    from tests.test_human_session import ASSISTANCE
    from tools import lap_qualification

    permit, root, _ = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    append = lap_qualification._append_attribution
    end = {"driver_id": "synthetic-driver", "assistance": ASSISTANCE}

    def interleaved_close(*args, **kwargs):
        with pytest.raises(HumanSessionError, match="campaign_writer_busy"):
            permit.close(end)
        return append(*args, **kwargs)

    monkeypatch.setattr(lap_qualification, "_append_attribution", interleaved_close)
    assert register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)[
        "registered"
    ]
    assert permit.close(end)["end_confirmed"]
    assert not qualify_practice_archive(
        load_lap_archive(path), use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed


def test_server_stop_during_registration_blocks_immediately_and_flushes_revocation(
    tmp_path, monkeypatch
):
    from tools.ai_sidecar import server
    from tools.human_session import HumanSessionPermit

    permit, root, _ = setup_native(tmp_path, monkeypatch)
    path = complete_archive(permit, root)
    register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    record = load_lap_archive(path)
    entered, release = threading.Event(), threading.Event()
    failures = []

    def registration_worker():
        try:
            with permit._registration_guard(record, expected_combo=PRACTICE_COMBO):
                entered.set()
                assert release.wait(2)
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=registration_worker)
    worker.start()
    try:
        assert entered.wait(2)
        collector = SimpleNamespace(
            abort=lambda reason: None, status=lambda: {"phase": "aborted", "observed_laps": 1}
        )
        monkeypatch.setattr(server, "_human_session_permit", permit)
        monkeypatch.setattr(server, "_human_practice_session", collector)
        monkeypatch.setattr(server, "_coach_runtime", None)
        monkeypatch.setattr(server, "_voice_coach", None)
        monkeypatch.setattr(server, "_observer", None)
        server._stop_practice_voice("native_session_disconnected")
        assert permit.status(private=True)["revocation_pending"]
        assert not permit.status()["active"]
        assert HumanSessionPermit.read_status(permit.path)["phase"] == "active"
        # The process-local fence must deny before the durable writer can acquire
        # its lock, without waiting for the five-second native freshness timeout.
        assert not qualify_practice_archive(
            record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
        ).allowed
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive() and not failures
    durable = HumanSessionPermit.read_status(permit.path)
    assert durable["phase"] == "aborted" and durable["reason"] == "native_session_disconnected"
    assert not qualify_practice_archive(
        record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed
