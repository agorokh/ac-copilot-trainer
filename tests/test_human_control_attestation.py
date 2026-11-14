"""Offline acceptance coverage for capture-time human-control attestation (#988).

All inputs are synthetic. These tests prove the producer's rule; they are not the
operator-attended bench session and do not certify any real lap.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

import tools.human_control_attestation as producer
from tests.human_attestation_helpers import (
    CAPTURE_END,
    CAPTURE_START,
    DECLARED_MS,
    EXPORTED_MS,
    LAP_END,
    LAP_MS,
    LAP_START,
    VENDOR_READ_MS,
    attest,
    capture_inputs,
    declaration,
    encode,
    journal,
    native_record,
    probe,
    probes,
    vendor_payload,
)
from tools.ac_harness.custom_ai import car_controls_name, car_data_name
from tools.human_control_attestation import (
    DECLARATION_ACTIONS,
    DISABLED,
    attest_archive,
    bench_verdict,
    certify_archive,
    classify_open_result,
    declaration_sink,
    main,
    parse_journal,
    probe_sample,
    run_monitor,
    scorecard,
)
from tools.lap_qualification import (
    ATTRIBUTIONS_ENV,
    HUMAN_ATTESTATION_DECLARATION_TTL_MS,
    HUMAN_ATTESTATION_ENV,
    HUMAN_ATTESTATION_REFERENCE_SECTION,
    HUMAN_ATTESTATION_SECTIONS,
    USES,
    AttributionError,
    archive_identity,
    build_qualification,
    human_control_attestation_evidence,
    payload_sha256,
    qualify_archive,
    register_attribution,
    register_human_attestation,
    restricted_lap_identities,
)
from tools.rig_controls.profiles import ATTEST_ACTIONS, Binding, parse_config
from tools.rig_controls.windows import Actions

EVIDENCE_HASH = hashlib.sha256(b"synthetic control observation").hexdigest()


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "lap-attributions.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv(ATTRIBUTIONS_ENV, str(path))
    monkeypatch.setenv(HUMAN_ATTESTATION_ENV, "1")
    return path


def write_archive(tmp_path, record=None, name="lap_synthetic.json"):
    path = tmp_path / name
    path.write_text(json.dumps(record or native_record()), encoding="utf-8")
    return path


def write_capture(tmp_path, **changes):
    inputs = capture_inputs(**changes)
    root = tmp_path / "capture"
    (root / "vendor").mkdir(parents=True)
    (root / "capture.jsonl").write_bytes(inputs["capture_journal"])
    (root / "declarations.jsonl").write_bytes(inputs["declaration_journal"])
    for digest, raw in inputs["vendor"].items():
        (root / "vendor" / f"{digest}.json").write_bytes(raw)
    return root


def shared_assessment(record):
    return build_qualification(
        record,
        authority="shared",
        origin="synthetic_test",
        supported_uses={use: use == "analysis" for use in USES},
        evidence=[{"kind": "observed_ai_intervention", "sha256": EVIDENCE_HASH}],
    )


# -- certification and hash binding ----------------------------------------------------
def test_clean_capture_certifies_with_evidence_bound_to_the_payload_hash():
    record = native_record()
    result = attest(record)
    assert result.verified and result.reason == "verified_human_control" and not result.reasons
    envelope = result.qualification
    assert envelope["authority"] == "human"
    assert envelope["supported_uses"] == {
        use: use in {"analysis", "human_progression"} for use in USES
    }
    assert envelope["binding"]["payload_sha256"] == payload_sha256(record)
    [item] = envelope["evidence"]
    witness = item["witness"]
    encoded = json.dumps(witness, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert item["kind"] == "verified_human_control"
    assert item["sha256"] == hashlib.sha256(encoded).hexdigest() == result.witness_sha256
    assert witness["archive"]["payload_sha256"] == payload_sha256(record)
    assert witness["archive"]["identity"] == archive_identity(record)
    assert witness["control_map"]["present_count"] == 0
    assert witness["control_map"]["first_ms"] <= DECLARED_MS
    assert witness["vendor_practice"]["lap"]["ai_intervened"] is False


def test_producer_is_default_off(monkeypatch, tmp_path, ledger):
    record = native_record()
    envelope = attest(record).qualification
    monkeypatch.delenv(HUMAN_ATTESTATION_ENV)
    assert attest(record).reasons == (DISABLED,)
    assert attest_archive(write_archive(tmp_path, record), None).reasons == (DISABLED,)
    assert declaration_sink() is None
    before = ledger.read_bytes()
    with pytest.raises(AttributionError, match=DISABLED):
        register_human_attestation(write_archive(tmp_path, record), envelope)
    assert ledger.read_bytes() == before
    assert main(["monitor", "--capture-dir", str(tmp_path / "capture")]) == 2
    monkeypatch.setenv(HUMAN_ATTESTATION_ENV, "true")
    assert attest(record).reasons == (DISABLED,)


# -- abstention: every missing, stale, unreadable or ambiguous signal ------------------
def _mid_lap(state="absent", reference="present"):
    events = probes()
    for event in events:
        if LAP_START + 20_000 <= event["t_ms"] <= LAP_START + 30_000:
            event.update(probe(event["t_ms"], state=state, reference=reference))
    return events


def _vendor(**changes):
    payload = vendor_payload(**changes)
    return {"vendor": payload}


ABSTENTIONS = {
    "capture_journal_missing": (
        {"capture_journal": None},
        {"control_map_probe_missing", "vendor_record_missing"},
    ),
    "capture_journal_torn": (
        {"capture_journal": capture_inputs()["capture_journal"] + b'{"kind":"probe","t_'},
        {"capture_journal_invalid"},
    ),
    "capture_clock_regression": (
        {"capture_journal": capture_inputs()["capture_journal"] + encode(probe(1)) + b"\n"},
        {"capture_journal_invalid"},
    ),
    "declaration_journal_missing": ({"declaration_journal": None}, {"declaration_missing"}),
    "declaration_journal_empty": ({"declaration_journal": b""}, {"declaration_missing"}),
    "declaration_journal_invalid": (
        {"declaration_journal": journal([{**declaration(), "surface": "keyboard"}])},
        {"declaration_journal_invalid", "declaration_missing"},
    ),
    "declaration_after_lap_start": (
        {"declaration_journal": journal([declaration(LAP_START + 5000)])},
        {"declaration_after_lap_start"},
    ),
    "declaration_cleared_mid_lap": (
        {
            "declaration_journal": journal(
                [declaration(), declaration(LAP_START + 10_000, "human_control.clear")]
            )
        },
        {"declaration_cleared"},
    ),
    "probe_gap_mid_lap": (
        capture_inputs(
            probe_events=[
                event
                for event in probes()
                if not LAP_START + 20_000 < event["t_ms"] < LAP_START + 21_000
            ]
        ),
        {"control_map_probe_gap"},
    ),
    "probe_stops_before_lap_end": (
        capture_inputs(probe_events=probes(end=LAP_END - 2000)),
        {"control_map_probe_gap"},
    ),
    "probe_starts_after_declaration": (
        capture_inputs(probe_events=probes(start=LAP_START + 1000)),
        {"control_map_probe_gap"},
    ),
    "probe_error_is_not_absence": (
        capture_inputs(probe_events=_mid_lap(state="error")),
        {"control_map_probe_error"},
    ),
    "probe_namespace_unproved": (
        capture_inputs(probe_events=_mid_lap(reference="absent")),
        {"control_map_reference_unavailable"},
    ),
    "project_autonomous_enabled_mid_lap": (
        capture_inputs(probe_events=_mid_lap(state="present")),
        {"control_map_present"},
    ),
    "vendor_record_not_captured": (
        {"capture_journal": journal(probes())},
        {"vendor_record_missing"},
    ),
    "vendor_record_only_read_before_lap_end": (
        capture_inputs(vendor_read_ms=LAP_END - 5000),
        {"vendor_record_stale"},
    ),
    "vendor_ai_enabled_mid_lap": (
        capture_inputs(**_vendor(aiIntervened=True, eligibility="ai-debug-only")),
        {"vendor_ai_intervened"},
    ),
    "vendor_ai_debug_only_label": (
        capture_inputs(**_vendor(eligibility="ai-debug-only")),
        {"vendor_ai_intervened"},
    ),
    "vendor_ai_label_missing": (
        capture_inputs(**_vendor(aiIntervened=None)),
        {"vendor_ai_label_unreadable"},
    ),
    "vendor_lap_not_finalized": (
        capture_inputs(**_vendor(finalized=False)),
        {"vendor_lap_incomplete"},
    ),
    "vendor_duration_unmatched": (
        capture_inputs(**_vendor(lapTimeSeconds=LAP_MS / 1000 + 0.5)),
        {"vendor_lap_unmatched"},
    ),
    "vendor_other_combo": (
        capture_inputs(**_vendor(referenceKey="AC|other-track|synthetic-car|0")),
        {"vendor_combo_mismatch"},
    ),
    "vendor_combo_unreadable": (
        capture_inputs(**_vendor(referenceKey=7)),
        {"vendor_combo_unreadable"},
    ),
    "vendor_other_lap_number": (
        capture_inputs(**_vendor(lapNumber=1)),
        {"vendor_lap_unmatched"},
    ),
    "vendor_lap_number_missing": (
        capture_inputs(**_vendor(lapNumber=None)),
        {"vendor_lap_unmatched"},
    ),
    "vendor_eligibility_missing": (
        capture_inputs(**_vendor(eligibility=None)),
        {"vendor_lap_not_eligible"},
    ),
    "vendor_eligibility_unrecognized": (
        capture_inputs(**_vendor(eligibility="pending-review")),
        {"vendor_lap_not_eligible"},
    ),
    "vendor_lap_time_mistyped": (
        capture_inputs(**_vendor(lapTimeSeconds=True)),
        {"vendor_record_unreadable"},
    ),
    "vendor_lap_time_absurd": (
        capture_inputs(**_vendor(lapTimeSeconds=1e306)),
        {"vendor_lap_unmatched"},
    ),
    "vendor_lap_not_timed_yet": (
        capture_inputs(**_vendor(lapTimeSeconds=None)),
        {"vendor_lap_unmatched"},
    ),
}


@pytest.mark.parametrize("case", sorted(ABSTENTIONS))
def test_degraded_signal_abstains_with_its_specific_reason(case):
    inputs, expected = ABSTENTIONS[case]
    result = attest(**inputs)
    assert not result.verified and result.qualification is None
    assert expected <= set(result.reasons), result.reasons
    assert result.reason == result.reasons[0]


def test_ambiguous_vendor_join_abstains():
    payload = vendor_payload()
    twin = dict(payload["summary"]["laps"][0], id="twin", recordUid="twin", aiIntervened=True)
    payload["summary"]["laps"].append(twin)
    result = attest(**capture_inputs(vendor=payload))
    assert not result.verified and "vendor_join_ambiguous" in result.reasons

    # Two different records read after the lap that both claim it but disagree.
    first, second = encode(vendor_payload()), encode(vendor_payload(aiIntervened=True))
    digests = [hashlib.sha256(raw).hexdigest() for raw in (first, second)]
    events = probes() + [
        {"kind": "vendor_snapshot", "t_ms": VENDOR_READ_MS + i * 2000, "sha256": digest}
        for i, digest in enumerate(digests)
    ]
    result = attest(
        capture_journal=journal(events), vendor=dict(zip(digests, (first, second), strict=True))
    )
    assert not result.verified and "vendor_join_ambiguous" in result.reasons


def test_vendor_record_from_another_session_window_does_not_cover_the_lap():
    payload = vendor_payload()
    payload["sessionStartedAtMs"] = LAP_END + 60_000
    payload["savedAtMs"] = LAP_END + 120_000
    assert "vendor_record_not_covering_lap" in attest(**capture_inputs(vendor=payload)).reasons
    for key, value in (("savedAtMs", None), ("sessionStartedAtMs", 1.5), ("savedAtMs", True)):
        payload = vendor_payload()
        payload[key] = value
        assert "vendor_record_unreadable" in attest(**capture_inputs(vendor=payload)).reasons
    # A session that began a few seconds into the lap cannot have recorded all of it.
    payload = vendor_payload()
    payload["sessionStartedAtMs"] = LAP_START + 4000
    assert "vendor_record_not_covering_lap" in attest(**capture_inputs(vendor=payload)).reasons


def _reads(*records):
    """Capture inputs where each (read_ms, payload) is one preserved vendor read."""
    raws = [(read_ms, encode(payload)) for read_ms, payload in records]
    digests = [hashlib.sha256(raw).hexdigest() for _, raw in raws]
    events = probes() + [
        {"kind": "vendor_snapshot", "t_ms": read_ms, "sha256": digest}
        for (read_ms, _), digest in zip(raws, digests, strict=True)
    ]
    return {
        "capture_journal": journal(events),
        "vendor": {digest: raw for digest, (_, raw) in zip(digests, raws, strict=True)},
    }


def test_record_saved_before_the_finish_can_never_vouch_for_the_lap():
    """A row of equal duration in an earlier save is a different lap, not this one."""
    early = vendor_payload()
    early["savedAtMs"] = EXPORTED_MS - 5000
    result = attest(**_reads((LAP_END, early)))
    assert not result.verified and "vendor_record_not_covering_lap" in result.reasons
    # The later save shows this lap as AI-intervened beside an earlier clean lap of
    # the same duration: still no certification.
    late = vendor_payload(lapNumber=1)
    late["summary"]["laps"].append(
        dict(
            vendor_payload()["summary"]["laps"][0],
            id="ai-lap",
            recordUid="ai-lap",
            aiIntervened=True,
            eligibility="ai-debug-only",
        )
    )
    result = attest(**_reads((LAP_END, early), (LAP_END + 2000, late)))
    assert not result.verified and "vendor_join_ambiguous" in result.reasons
    # exported_at is truncated to the second, so the finish may be up to 999 ms later.
    for saved in (EXPORTED_MS - 1, EXPORTED_MS, LAP_END - 1):
        early["savedAtMs"] = saved
        assert not attest(**_reads((LAP_END, early))).verified
    early["savedAtMs"] = LAP_END
    assert attest(**_reads((LAP_END, early))).verified


def test_a_later_contradicting_or_malformed_vendor_read_is_never_skipped():
    clean = vendor_payload()
    malformed = vendor_payload(aiIntervened=True)
    malformed["sessionStartedAtMs"] = float(LAP_START - 60_000)
    result = attest(**_reads((LAP_END + 500, clean), (LAP_END + 2000, malformed)))
    assert not result.verified and "vendor_record_unreadable" in result.reasons
    revised = vendor_payload(aiIntervened=True, lapTimeSeconds=LAP_MS / 1000 + 0.002)
    result = attest(**_reads((LAP_END + 500, clean), (LAP_END + 2000, revised)))
    assert not result.verified and "vendor_lap_unmatched" in result.reasons
    flipped = vendor_payload(aiIntervened=True)
    result = attest(**_reads((LAP_END + 500, clean), (LAP_END + 2000, flipped)))
    assert {"vendor_ai_intervened", "vendor_join_ambiguous"} <= set(result.reasons)
    # An earlier read that simply had not caught up yet does not block the lap.
    pending = vendor_payload(lapTimeSeconds=None, finalized=False)
    assert attest(**_reads((LAP_END + 500, pending), (LAP_END + 2000, clean))).verified


def _with_snapshot_event(inputs, event):
    events = parse_journal(inputs["capture_journal"]) + [event]
    return {**inputs, "capture_journal": journal(events)}


def test_a_failed_last_look_at_the_vendor_file_abstains():
    """The label may have changed in the very write the monitor could not read."""
    inputs = _reads((LAP_END + 500, vendor_payload()))
    for status in ("unreadable", "missing"):
        failed = {"kind": "vendor_snapshot", "t_ms": LAP_END + 2000, "status": status}
        result = attest(**_with_snapshot_event(inputs, failed))
        assert not result.verified and "vendor_record_unreadable" in result.reasons
    # A failed read followed by a successful one is decided by the successful one.
    recovered = _reads((LAP_END + 500, vendor_payload()), (LAP_END + 4000, vendor_payload()))
    failed = {"kind": "vendor_snapshot", "t_ms": LAP_END + 2000, "status": "unreadable"}
    assert attest(**_with_snapshot_event(recovered, failed)).verified


def test_any_read_of_the_session_that_flags_this_lap_number_blocks_it():
    clean = vendor_payload()
    twin = vendor_payload()
    twin["summary"]["laps"].append(
        dict(clean["summary"]["laps"][0], id="twin", recordUid="twin", aiIntervened=True)
    )
    # An earlier covering read listed an AI twin that the latest read no longer shows.
    result = attest(**_reads((LAP_END + 500, twin), (LAP_END + 2000, clean)))
    assert not result.verified and "vendor_join_ambiguous" in result.reasons
    # Same lap number, AI label, different duration, in an earlier covering read.
    revised = vendor_payload(aiIntervened=True, lapTimeSeconds=LAP_MS / 1000 + 0.002)
    result = attest(**_reads((LAP_END + 500, revised), (LAP_END + 2000, clean)))
    assert not result.verified and "vendor_join_ambiguous" in result.reasons
    # Saved before the finish (so never a candidate), but it flagged the lap as AI.
    in_progress = vendor_payload(aiIntervened=True, lapTimeSeconds=None, finalized=False)
    in_progress["savedAtMs"] = LAP_START + 30_000
    for read_ms in (LAP_START + 31_000, LAP_END + 500):
        result = attest(**_reads((read_ms, in_progress), (LAP_END + 2000, clean)))
        assert not result.verified and "vendor_join_ambiguous" in result.reasons
    # The same label in a different vendor session, or for another lap number, is not
    # evidence about this lap.
    other_session = vendor_payload(aiIntervened=True)
    other_session["sessionId"] = "another-vendor-session"
    other_session["sessionStartedAtMs"] = LAP_END + 60_000
    other_session["savedAtMs"] = LAP_END + 90_000
    assert attest(**_reads((LAP_END + 2000, clean), (LAP_END + 95_000, other_session))).verified
    other_lap = vendor_payload()
    other_lap["summary"]["laps"].append(
        dict(
            clean["summary"]["laps"][0],
            id="lap3",
            recordUid="lap3",
            lapNumber=3,
            lapTimeSeconds=71.5,
            aiIntervened=True,
        )
    )
    assert attest(**_reads((LAP_END + 2000, other_lap))).verified
    nameless = vendor_payload()
    nameless["sessionId"] = ""
    assert "vendor_record_unreadable" in attest(**_reads((LAP_END + 2000, nameless))).reasons


def test_unreadable_vendor_bytes_abstain_instead_of_meaning_no_ai():
    inputs = capture_inputs()
    [digest] = inputs["vendor"]
    for corrupt in (b"{not json", inputs["vendor"][digest] + b" ", b""):
        result = attest(**{**inputs, "vendor": {digest: corrupt}})
        assert not result.verified and "vendor_record_unreadable" in result.reasons
    assert "vendor_record_unreadable" in attest(**{**inputs, "vendor": {}}).reasons


def test_stale_declaration_abstains_even_with_continuous_probing():
    declared = LAP_END - HUMAN_ATTESTATION_DECLARATION_TTL_MS - 5000
    inputs = capture_inputs(
        probe_events=probes(start=declared - 1000),
        declarations=[declaration(declared)],
    )
    result = attest(**inputs)
    assert result.reasons == ("declaration_stale",)


@pytest.mark.parametrize(
    "change,reason",
    [
        (None, "native_ai_observation_missing"),
        ({"ai_controlled_count": 40}, "native_ai_controlled"),
        ({"unknown_count": 1, "user_controlled_count": 5999}, "native_ai_state_unknown"),
        ({"complete": False}, "native_ai_observation_incomplete"),
        ({"user_controlled_count": 5990}, "native_user_control_absent"),
        ({"source": "car.other"}, "native_ai_observation_missing"),
        ({"not_live_count": 3}, "native_lap_not_live"),
        ({"wall_elapsed_s": 95}, "native_lap_wall_clock_mismatch"),
        ({"wall_elapsed_s": 57}, "native_lap_wall_clock_mismatch"),
        ({"sample_count": 2, "user_controlled_count": 2}, "native_ai_observation_sparse"),
        ({"wall_elapsed_s": None}, "native_ai_observation_missing"),
        ({"sample_count": 6000.0}, "native_ai_observation_missing"),
        ({"sample_count": True}, "native_ai_observation_missing"),
    ],
)
def test_native_game_ai_state_must_be_read_clear_for_the_whole_lap(change, reason):
    record = native_record()
    if change is None:
        del record["trace"]["control_observation"]
    else:
        record["trace"]["control_observation"].update(change)
    result = attest(record)
    assert not result.verified and reason in result.reasons


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda r: r.update(source="imported", import_format="motec_csv"), "archive_source_un"),
        (lambda r: r.update(schema_version=2), "archive_schema_unsupported"),
        (lambda r: r.update(exported_at="2026-11-14 12:00:00"), "attestation_lap_window_un"),
        (lambda r: r.pop("exported_at"), "attestation_lap_window_unavailable"),
        (lambda r: r["lap"].update(lap_ms=float("nan")), "archive_lap_identity_invalid"),
        (lambda r: r["trace"]["samples"][0].__setitem__(1, float("inf")), "nonfinite_or_un"),
        (lambda r: r.update(session_uuid=""), "archive_identity_unavailable"),
    ],
)
def test_unusable_archive_abstains(mutate, reason):
    record = native_record()
    mutate(record)
    result = attest(record)
    assert not result.verified and any(item.startswith(reason) for item in result.reasons)
    assert not attest([]).verified  # type: ignore[arg-type]


# -- probe: a failure is never "not present" -------------------------------------------
def test_only_file_not_found_reads_as_absent():
    assert classify_open_result(True, 0) == "present"
    assert classify_open_result(False, 2) == "absent"
    for error in (0, 5, 6, 87, 1314):
        assert classify_open_result(False, error) == "error"

    def denied(_name):
        return False, 5

    def broken(_name):
        raise OSError("synthetic probe failure")

    def mistyped(_name):
        return None, "2"

    for opener in (denied, broken, mistyped):
        sample = probe_sample(opener, 1000)
        assert set(sample["sections"].values()) == {"error"} and sample["reference"] == "error"
    sample = probe_sample(lambda name: (name == HUMAN_ATTESTATION_REFERENCE_SECTION, 2), 1000)
    assert set(sample["sections"].values()) == {"absent"} and sample["reference"] == "present"


def test_probed_sections_are_the_autonomous_drivers_own_and_actions_stay_pinned():
    names = {car_data_name(0), car_controls_name(0)}
    assert set(HUMAN_ATTESTATION_SECTIONS) == names | {f"Local\\{name}" for name in names}
    assert set(ATTEST_ACTIONS) == set(DECLARATION_ACTIONS)


def test_journal_reader_rejects_duplicate_keys_nonfinite_and_mistyped_events():
    for raw in (
        b'{"kind":"probe","t_ms":5,"t_ms":6}\n',
        b'{"kind":"probe","t_ms":NaN}\n',
        b'{"kind":"probe","t_ms":true}\n',
        b'{"kind":"probe","t_ms":1.5}\n',
        b'{"kind":7,"t_ms":5}\n',
        b"[]\n",
        b"\xff\n",
    ):
        with pytest.raises(ValueError):
            parse_journal(raw)
    assert parse_journal(b"\n" + encode(probe(5)) + b"\n\n")[0]["t_ms"] == 5


def test_monitor_journal_feeds_a_certification_end_to_end(tmp_path):
    record = native_record()
    snapshot = tmp_path / "vendor-snapshot.json"
    snapshot.write_bytes(encode(vendor_payload()))
    capture = tmp_path / "capture"
    now = [CAPTURE_START / 1000]

    def sleep(seconds):
        now[0] += seconds

    written = run_monitor(
        capture,
        open_existing=lambda name: (name == HUMAN_ATTESTATION_REFERENCE_SECTION, 2),
        vendor_snapshot=snapshot,
        clock=lambda: now[0],
        sleep=sleep,
        should_stop=lambda: now[0] * 1000 > CAPTURE_END,
    )
    assert written > 900
    (capture / "declarations.jsonl").write_bytes(journal([declaration()]))
    path = write_archive(tmp_path, record)
    assert attest_archive(path, capture).verified

    # The same monitor with an unreadable control map can never certify.
    blind = tmp_path / "blind"
    now[0] = CAPTURE_START / 1000
    run_monitor(
        blind,
        open_existing=lambda name: (False, 5),
        vendor_snapshot=tmp_path / "missing.json",
        clock=lambda: now[0],
        sleep=sleep,
        should_stop=lambda: now[0] * 1000 > CAPTURE_END,
    )
    (blind / "declarations.jsonl").write_bytes(journal([declaration()]))
    reasons = attest_archive(path, blind).reasons
    assert {"control_map_probe_error", "vendor_record_missing"} <= set(reasons)
    with pytest.raises(ValueError):
        run_monitor(tmp_path / "slow", open_existing=lambda name: (False, 2), period_s=0.4)


def test_unreadable_capture_file_abstains(tmp_path, monkeypatch):
    path = write_archive(tmp_path)
    capture = write_capture(tmp_path)
    real = producer._stable_bytes

    def flaky(target):
        if target.name == "capture.jsonl":
            raise OSError("synthetic sharing violation")
        return real(target)

    monkeypatch.setattr(producer, "_stable_bytes", flaky)
    result = attest_archive(path, capture)
    assert not result.verified and result.reason == "capture_journal_unreadable"
    monkeypatch.setattr(producer, "_stable_bytes", real)
    assert attest_archive(path, capture).verified
    assert attest_archive(tmp_path / "absent.json", capture).reasons == ("archive_unreadable",)
    assert "control_map_probe_missing" in attest_archive(path, None).reasons


# -- no relabelling, no promotion ------------------------------------------------------
def test_existing_attribution_is_never_attested_or_promoted(tmp_path, ledger):
    record = native_record()
    path = write_archive(tmp_path, record)
    envelope = attest(record).qualification
    register_attribution(path, shared_assessment(record))
    before = ledger.read_bytes()
    assert attest(record).reasons == ("existing_attribution:shared",)
    receipt = certify_archive(path, write_capture(tmp_path), register=True)
    assert not receipt["verified"] and receipt["registered"] is None
    with pytest.raises(AttributionError, match="conflicting_attribution_identity"):
        register_human_attestation(path, envelope)
    assert ledger.read_bytes() == before
    assert qualify_archive(record, use="human_progression").authority == "shared"

    embedded = native_record()
    embedded.update(lap_uuid="embedded-lap", session_uuid="embedded-session")
    embedded["qualification"] = shared_assessment(embedded)
    assert attest(embedded).reasons == ("existing_attribution:shared",)
    for placeholder in (None, {}, [], 0, ""):
        embedded["qualification"] = placeholder
        result = attest(embedded)
        assert not result.verified and result.reason == "existing_attribution:unknown"


def test_paused_lap_cannot_hide_an_earlier_autonomous_stint():
    """Lap time excludes a pause, so the wall-clock start lies before the window."""
    record = native_record()
    record["trace"]["control_observation"]["wall_elapsed_s"] = 60 + 40
    autonomous_until = LAP_START - 20_000
    events = [
        probe(event["t_ms"], state="present") if event["t_ms"] <= autonomous_until else event
        for event in probes(start=LAP_START - 60_000)
    ]
    inputs = capture_inputs(probe_events=events, declarations=[declaration(LAP_START - 8000)])
    result = attest(record, **inputs)
    assert not result.verified and "native_lap_wall_clock_mismatch" in result.reasons


def test_restrictive_fact_revokes_one_certified_lap(tmp_path, ledger):
    record = native_record()
    path = write_archive(tmp_path, record)
    certify_archive(path, write_capture(tmp_path), register=True)
    assert qualify_archive(record, use="human_progression").authority == "human"
    receipt = register_attribution(path, shared_assessment(record))
    assert receipt["reason"] == "superseded_human_attestation"
    [entry] = json.loads(ledger.read_text(encoding="utf-8"))["entries"]
    assert entry["qualification"]["authority"] == "shared"
    decision = qualify_archive(record, use="human_progression")
    assert not decision.allowed and decision.authority == "shared"
    # The revocation is final: the lap can never be certified again.
    again = certify_archive(path, write_capture(tmp_path / "again"), register=True)
    assert again["reasons"] == ["existing_attribution:shared"]


def test_revocation_needs_the_exact_lap_and_strict_archive_bytes(tmp_path, ledger):
    record = native_record()
    path = write_archive(tmp_path, record)
    certify_archive(path, write_capture(tmp_path), register=True)
    before = ledger.read_bytes()
    # Another archive that only shares the session and lap number cannot revoke it.
    lookalike = native_record()
    lookalike["lap_uuid"] = "lookalike-lap"
    with pytest.raises(AttributionError, match="conflicting_attribution_identity"):
        register_attribution(
            write_archive(tmp_path, lookalike, name="lookalike.json"), shared_assessment(lookalike)
        )
    assert ledger.read_bytes() == before
    assert qualify_archive(record, use="human_progression").allowed

    fresh = native_record()
    fresh.update(lap_uuid="fresh-lap", session_uuid="fresh-session")
    envelope = attest(fresh).qualification
    text = json.dumps(fresh)
    shadowed = tmp_path / "shadowed.json"
    shadowed.write_text(
        text.replace('"session_uuid"', '"session_uuid": "ignored", "session_uuid"', 1),
        encoding="utf-8",
    )
    assert json.loads(shadowed.read_text(encoding="utf-8")) == fresh
    with pytest.raises(AttributionError, match="archive_unreadable"):
        register_human_attestation(shadowed, envelope)
    assert ledger.read_bytes() == before


def test_named_ledger_is_used_for_the_guard_and_the_append(tmp_path, ledger):
    record = native_record()
    path = write_archive(tmp_path, record)
    scratch = tmp_path / "scratch-ledger.json"
    scratch.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    register_attribution(path, shared_assessment(record), ledger_path=scratch)
    receipt = certify_archive(path, write_capture(tmp_path), register=True, ledger_path=scratch)
    assert receipt["reasons"] == ["existing_attribution:shared"]
    assert json.loads(ledger.read_text(encoding="utf-8"))["entries"] == []


def test_archive_with_a_duplicate_key_is_unreadable(tmp_path):
    clean = json.dumps(native_record())
    dirty = clean.replace('"lap_uuid"', '"session_uuid": "shadowed", "lap_uuid"', 1)
    path = tmp_path / "duplicate.json"
    path.write_text(dirty, encoding="utf-8")
    assert json.loads(dirty)["session_uuid"] == "synthetic-session"
    assert attest_archive(path, write_capture(tmp_path)).reasons == ("archive_unreadable",)


def test_unreadable_ledger_blocks_attestation(ledger):
    ledger.write_text("{not json", encoding="utf-8")
    assert attest().reasons == ("attribution_unavailable:attribution_store_invalid",)


def test_generic_registration_still_cannot_certify_human_control(tmp_path, ledger):
    record = native_record()
    path = write_archive(tmp_path, record)
    envelope = attest(record).qualification
    before = ledger.read_bytes()
    with pytest.raises(AttributionError, match="registration_cannot_certify_human_control"):
        register_attribution(path, envelope)
    forged = build_qualification(
        record,
        authority="human",
        origin="synthetic_test",
        supported_uses={use: True for use in USES},
        evidence=[{"kind": "verified_human_control", "sha256": EVIDENCE_HASH}],
    )
    with pytest.raises(AttributionError, match="human_control_evidence_invalid"):
        register_human_attestation(path, forged)
    assert ledger.read_bytes() == before


# -- policy: the certified lap reaches qualify_archive, and only that lap --------------
def test_certified_lap_is_allowed_human_progression_and_nothing_else(tmp_path, ledger):
    record = native_record()
    path = write_archive(tmp_path, record)
    raw_before = path.read_bytes()
    assert qualify_archive(record, use="human_progression").authority == "legacy_unknown"
    receipt = certify_archive(path, write_capture(tmp_path), register=True)
    assert receipt["verified"] and receipt["registered"]["registered"] is True
    assert path.read_bytes() == raw_before
    decision = qualify_archive(json.loads(raw_before), use="human_progression")
    assert decision.allowed and decision.managed and decision.authority == "human"
    assert qualify_archive(record, use="analysis").allowed
    combo = ("synthetic-car", "synthetic-track", None)
    for use in USES - {"analysis", "human_progression"}:
        denied = qualify_archive(record, use=use, expected_combo=combo)
        assert not denied.allowed and f"unsupported_use:{use}" in denied.reasons
    assert restricted_lap_identities(use="human_progression") == []
    again = certify_archive(path, write_capture(tmp_path / "again"), register=True)
    assert again["reasons"] == ["existing_attribution:human"]
    assert register_human_attestation(path, attest_stored(ledger))["reason"] == "already_registered"


def attest_stored(ledger):
    [entry] = json.loads(ledger.read_text(encoding="utf-8"))["entries"]
    return entry["qualification"]


def test_disabling_the_producer_revokes_human_use_without_corrupting_the_ledger(
    tmp_path, ledger, monkeypatch
):
    record = native_record()
    certify_archive(write_archive(tmp_path, record), write_capture(tmp_path), register=True)
    monkeypatch.delenv(HUMAN_ATTESTATION_ENV)
    denied = qualify_archive(record, use="human_progression")
    assert not denied.allowed and denied.reason == "human_control_attestation_disabled"
    assert qualify_archive(record, use="analysis").allowed
    assert restricted_lap_identities(use="human_progression") == [archive_identity(record)]


def test_changed_archive_or_witness_loses_certification(tmp_path, ledger):
    record = native_record()
    certify_archive(write_archive(tmp_path, record), write_capture(tmp_path), register=True)
    edited = copy.deepcopy(record)
    edited["lap"]["is_pb"] = False
    assert qualify_archive(edited, use="human_progression").reason == (
        "attribution_payload_mismatch"
    )
    stored = json.loads(ledger.read_text(encoding="utf-8"))
    original = copy.deepcopy(stored)
    witness = stored["entries"][0]["qualification"]["evidence"][0]["witness"]
    witness["vendor_practice"]["lap"]["ai_intervened"] = True
    for rehash in (False, True):
        if rehash:
            encoded = json.dumps(witness, sort_keys=True, separators=(",", ":")).encode()
            stored["entries"][0]["qualification"]["evidence"][0]["sha256"] = hashlib.sha256(
                encoded
            ).hexdigest()
        ledger.write_text(json.dumps(stored), encoding="utf-8")
        decision = qualify_archive(record, use="human_progression")
        assert not decision.allowed and decision.reason == "attribution_store_invalid"
    # Broadening a certified entry's uses is equally invalid.
    original["entries"][0]["qualification"]["supported_uses"]["live_reference"] = True
    ledger.write_text(json.dumps(original), encoding="utf-8")
    assert qualify_archive(record, use="human_progression").reason == "attribution_store_invalid"


def test_envelope_cannot_be_replayed_onto_another_lap_or_embedded_edit():
    record = native_record()
    envelope = attest(record).qualification
    other = native_record()
    other["lap_uuid"] = "another-lap"
    other["qualification"] = copy.deepcopy(envelope)
    assert qualify_archive(other, use="human_progression").reason == (
        "qualification_identity_mismatch"
    )
    rebound = build_qualification(
        other,
        authority="human",
        origin=envelope["origin"],
        supported_uses=envelope["supported_uses"],
        channels=envelope["channels"],
        evidence=envelope["evidence"],
    )
    other["qualification"] = rebound
    decision = qualify_archive(other, use="human_progression")
    assert not decision.allowed and "human_control_evidence_invalid" in decision.reasons
    assert not human_control_attestation_evidence(
        rebound, identity=archive_identity(other), payload_digest=payload_sha256(other)
    )
    # The in-archive native state is rechecked against the record at the boundary.
    drifted = native_record()
    drifted["qualification"] = copy.deepcopy(envelope)
    drifted["qualification"]["evidence"][0]["witness"]["native_ai"]["sample_count"] = 5999
    assert "human_control_evidence_invalid" in (
        qualify_archive(drifted, use="human_progression").reasons
    )


# -- offline scorecard over already-attributed laps ------------------------------------
def test_scorecard_certifies_none_of_the_attributed_laps(tmp_path, ledger, capsys):
    laps = tmp_path / "laps"
    laps.mkdir()
    for index in range(5):
        record = native_record()
        record["lap_uuid"] = f"attributed-{index}"
        record["lap"]["lap_n"] = index + 1
        if index % 2:
            del record["trace"]["control_observation"]
        path = write_archive(laps, record, name=f"lap_{index}.json")
        register_attribution(path, shared_assessment(record))
    (laps / "lap_3.json").unlink()
    (laps / "torn.json").write_text("{", encoding="utf-8")
    write_archive(laps, native_record(), name="unattributed.json")
    report = scorecard(ledger, laps)
    assert report["ledger_entries"] == 5 and report["archives_evaluated"] == 4
    assert report["archives_missing"] == 1 and report["archives_unreadable"] == 1
    assert report["certified"] == 0 and report["signals_clear_without_ledger_guard"] == 0
    assert all(
        row["reasons"] == ["existing_attribution:shared"]
        for row in report["laps"]
        if row["archive"]
    )
    assert report["signal_reason_histogram"]["control_map_probe_missing"] == 4
    assert report["signal_reason_histogram"]["native_ai_observation_missing"] == 1
    assert scorecard(ledger, laps, first=2)["selected_entries"] == 2
    assert main(["scorecard", "--ledger", str(ledger), "--laps", str(laps)]) == 0
    assert json.loads(capsys.readouterr().out)["certified"] == 0
    assert main(["scorecard", "--ledger", str(tmp_path / "none.json"), "--laps", str(laps)]) == 2


# -- bench acceptance rule -------------------------------------------------------------
def _bench(human_certified=6, false_arm=None, **arm_counts):
    arms = {
        "human": 6,
        "project_autonomous": 4,
        "vendor_ai": 1,
        "vendor_ai_mid_lap": 2,
        "vendor_ai_record_missing": 1,
        **arm_counts,
    }
    laps, results = [], []
    for arm, count in arms.items():
        for index in range(count):
            lap_n = len(laps) + 1
            laps.append({"session_uuid": "bench", "lap_n": lap_n, "arm": arm})
            verified = (arm == "human" and index < human_certified) or arm == false_arm
            results.append(
                {
                    "identity": {"session_uuid": "bench", "lap_n": lap_n},
                    "verified": verified,
                    "witness_sha256": EVIDENCE_HASH if verified else None,
                }
            )
    return {"vendor_record_available": True, "laps": laps}, results


def test_bench_verdict_applies_the_fixed_acceptance_rule():
    assert bench_verdict(*_bench())["verdict"] == "PASS"
    assert bench_verdict(*_bench(human_certified=5))["verdict"] == "PASS"
    low = bench_verdict(*_bench(human_certified=4))
    assert low["verdict"] == "FAIL" and low["reasons"] == ["fewer_than_5_of_6_human_laps_certified"]
    for arm in ("project_autonomous", "vendor_ai_mid_lap", "vendor_ai_record_missing"):
        failed = bench_verdict(*_bench(false_arm=arm))
        assert failed["verdict"] == "FAIL" and failed["reasons"] == ["non_human_lap_certified"]
    # A false certification fails even when the session is otherwise too small.
    assert bench_verdict(*_bench(false_arm="vendor_ai", human=2))["verdict"] == "FAIL"
    for change, reason in (
        ({"human": 5}, "fewer_than_6_human_laps"),
        ({"project_autonomous": 3}, "fewer_than_4_project_autonomous_laps"),
        ({"vendor_ai": 0}, "fewer_than_4_vendor_ai_laps"),
        ({"vendor_ai_mid_lap": 1, "vendor_ai": 2}, "fewer_than_2_vendor_ai_mid_lap_laps"),
        ({"vendor_ai_record_missing": 0, "vendor_ai": 2}, "no_vendor_record_missing_lap"),
    ):
        result = bench_verdict(*_bench(**change))
        assert result["verdict"] == "INCONCLUSIVE" and reason in result["reasons"]
    manifest, results = _bench()
    results[-1]["verified"] = 1
    assert bench_verdict(manifest, results)["reasons"] == ["results_invalid"]
    manifest, results = _bench()
    results[0]["witness_sha256"] = None
    assert bench_verdict(manifest, results)["reasons"] == ["certification_without_hash_binding"]
    manifest, results = _bench()
    manifest["vendor_record_available"] = False
    assert bench_verdict(manifest, results)["reasons"] == ["vendor_record_unavailable_for_session"]
    manifest, results = _bench()
    assert bench_verdict(manifest, results[:-1])["verdict"] == "INCONCLUSIVE"
    results.append(
        {
            "identity": {"session_uuid": "bench", "lap_n": 99},
            "verified": True,
            "witness_sha256": EVIDENCE_HASH,
        }
    )
    assert "unlabelled_results" in bench_verdict(manifest, results)["reasons"]
    manifest["laps"].append(dict(manifest["laps"][0]))
    assert bench_verdict(manifest, results)["reasons"] == ["manifest_duplicate_lap"]
    assert bench_verdict({"laps": [{"arm": "robot"}]}, [])["reasons"] == ["manifest_invalid"]


def test_attest_and_verdict_cli_round_trip(tmp_path, ledger, capsys, monkeypatch):
    path = write_archive(tmp_path)
    capture = write_capture(tmp_path)
    scratch = tmp_path / "bench-ledger.json"
    arguments = ["attest", "--archive", str(path), "--capture-dir", str(capture)]
    # A named ledger that does not exist is an unavailable store, never an empty one.
    assert main([*arguments, "--register", "--ledger", str(scratch)]) == 0
    missing = json.loads(capsys.readouterr().out)["results"][0]
    assert missing["reasons"] == ["attribution_unavailable:attribution_store_unavailable"]
    assert not scratch.exists()
    monkeypatch.setenv(ATTRIBUTIONS_ENV, str(ledger))
    scratch.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    assert main(["attest", "--archive", str(path), "--capture-dir", str(capture)]) == 0
    printed = json.loads(capsys.readouterr().out)
    [row] = printed["results"]
    assert row["verified"] and row["registered"] is None
    assert row["identity"] == archive_identity(native_record())
    assert json.loads(ledger.read_text(encoding="utf-8"))["entries"] == []
    assert main([*arguments, "--register", "--ledger", str(scratch)]) == 0
    assert json.loads(capsys.readouterr().out)["results"][0]["registered"]["registered"] is True
    assert len(json.loads(scratch.read_text(encoding="utf-8"))["entries"]) == 1
    assert json.loads(ledger.read_text(encoding="utf-8"))["entries"] == []
    results = tmp_path / "results.json"
    results.write_text(json.dumps(printed), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"laps": [{"session_uuid": "synthetic-session", "lap_n": 2, "arm": "human"}]}),
        encoding="utf-8",
    )
    assert main(["verdict", "--manifest", str(manifest), "--results", str(results)]) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "INCONCLUSIVE"
    manifest.write_text("{", encoding="utf-8")
    assert main(["verdict", "--manifest", str(manifest), "--results", str(results)]) == 2


# -- operator declaration from a rig button --------------------------------------------
def _profiles(binding, control="button_2"):
    bindings = {
        name: {"action": "noop"}
        for name in ("button_1", "button_2", "button_3", "knob_cw", "knob_ccw", "knob_press")
    }
    bindings[control] = binding
    return {
        "version": 1,
        "default": "racing",
        "profiles": [{"name": "racing", "rgb": [255, 0, 0], "bindings": bindings}],
    }


def test_rig_button_declaration_is_recorded_only_when_enabled(tmp_path, monkeypatch):
    target = tmp_path / "capture" / "declarations.jsonl"
    config = parse_config(_profiles({"action": "attest", "name": "human_control.declare"}))
    binding = config.profiles[0].bindings[1]
    assert binding == Binding("attest", name="human_control.declare")
    actions = Actions(sender=lambda *_: pytest.fail("a declaration must not inject keys"))
    actions.perform(binding, True)
    assert actions.last_unavailable == "human_control.declare: attestation not enabled"
    assert not target.exists()
    monkeypatch.setenv(producer.DECLARATION_JOURNAL_ENV, str(target))
    actions.perform(binding, True)
    actions.perform(binding, False)
    actions.perform(Binding("attest", name="human_control.clear"), True)
    events = parse_journal(target.read_bytes())
    assert [event["action"] for event in events] == [
        "human_control.declare",
        "human_control.clear",
    ]
    assert all(event["surface"] == "rig_controls" for event in events)
    monkeypatch.delenv(HUMAN_ATTESTATION_ENV)
    actions.perform(binding, True)
    assert len(parse_journal(target.read_bytes())) == 2

    def refuse(_action):
        raise OSError("synthetic full disk")

    failing = Actions(declare=refuse)
    failing.perform(binding, True)
    assert "declaration not recorded" in failing.last_error
    with pytest.raises(ValueError):
        producer.record_declaration(target, "human_control.other")


@pytest.mark.parametrize(
    "binding,control",
    [
        ({"action": "attest", "name": "human_control.declare"}, "knob_cw"),
        ({"action": "attest", "name": "human_control.clear"}, "knob_ccw"),
        ({"action": "attest", "name": "human_control.certify"}, "button_2"),
        ({"action": "attest", "name": "human_control.declare", "keys": ["A"]}, "button_2"),
    ],
)
def test_declaration_binding_is_strict(binding, control):
    with pytest.raises(ValueError):
        parse_config(_profiles(binding, control))
