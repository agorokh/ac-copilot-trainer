"""Synthetic archive/attribution boundaries; never read a rig's real journal."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools.ac_harness.ggv_profile import observe_lap_tyre_state
from tools.ai_sidecar.driver_profile import (
    ProfileLoadError,
    _is_driver_lap,
    build_profile,
    load_profile,
)
from tools.lap_archive_export import LapArchiveExportError, load_lap_archive
from tools.lap_qualification import (
    ATTRIBUTIONS_ENV,
    USES,
    AttributionError,
    _stable_bytes,
    archive_combo,
    build_qualification,
    default_attribution_path,
    duplicate_identity_reasons,
    main,
    qualify_archive,
    register_attribution,
    restricted_lap_identities,
)

UNITS = {
    "spline": "normalized",
    "speed": "km/h",
    "eMs": "ms",
    "throttle": "ratio",
    "brake": "ratio",
    "steer": "steering_wheel_deg",
    "gear": "gear",
    "px": "m",
    "py": "m",
    "pz": "m",
}
EVIDENCE_HASH = hashlib.sha256(b"synthetic control observation").hexdigest()


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "lap-attributions.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv(ATTRIBUTIONS_ENV, str(path))
    return path


def archive() -> dict:
    return {
        "schema_version": 1,
        "source": "in_game",
        "lap_uuid": "synthetic-lap",
        "session_uuid": "synthetic-session",
        "car": {"id": "synthetic-car"},
        "track": {"id": "synthetic-track", "layout": None},
        "lap": {"lap_n": 2, "lap_ms": 60000, "is_valid": True, "is_pb": True},
        "trace": {
            "fields": list(UNITS),
            "samples": [[i / 100, 100, i * 600, 0.7, 0.1, 5, 3, i, 0, i] for i in range(101)],
        },
    }


def assessment(record, *, authority="shared", promoted=False):
    return build_qualification(
        record,
        authority=authority,
        origin="synthetic_test",
        supported_uses={use: promoted or use == "analysis" for use in USES},
        channels={name: {"unit": unit, "basis": "measured"} for name, unit in UNITS.items()},
        evidence=[
            {
                "kind": "verified_human_control"
                if authority == "human"
                else "observed_ai_intervention",
                "sha256": EVIDENCE_HASH,
            }
        ],
        reasons=["Synthetic data only; observed intervention does not prove exclusive control."],
    )


def write_native(tmp_path, record=None):
    path = tmp_path / "lap_synthetic.json"
    path.write_text(json.dumps(record or archive()), encoding="utf-8")
    return path


def native_control_report(record):
    identity = {
        "lap_n": record["lap"]["lap_n"],
        "lap_ms": record["lap"]["lap_ms"],
    }
    return {
        "ok": True,
        "session_uuid": record["session_uuid"],
        "car_id": record["car"]["id"],
        "track_id": record["track"]["id"],
        "timed_laps": [identity],
        "drive": {
            "drove": True,
            "sim_dead": False,
            "session_replaced": False,
            "recoveries": 0,
            "recovery_capped": False,
            "unexpected_sim_pids": [],
        },
    }


def register_native_test(tmp_path, record=None, *, report_change=None, app_change=None):
    from tools.ac_harness.native_attribution import attribute_native_control

    record = archive() if record is None else record
    path = write_native(tmp_path, record)
    report = native_control_report(record)
    if report_change:
        report_change(report)
    app = {"status": "match", "harness_digest": EVIDENCE_HASH, "installed_digest": EVIDENCE_HASH}
    if app_change:
        app_change(app)
    receipt = attribute_native_control(
        [path], report=report, driver="alien", app_install=app, evidence_dir=tmp_path / "evidence"
    )
    return path, receipt


def test_native_ai_opt_in_is_plant_only_and_preserves_raw_bytes(tmp_path, ledger):
    record = archive()
    expected = json.dumps(record).encode()
    path, receipt = register_native_test(tmp_path, record)
    assert path.read_bytes() == expected
    assert receipt["sha256"] == hashlib.sha256(Path(receipt["witness"]).read_bytes()).hexdigest()
    assert len(json.loads(ledger.read_bytes())["entries"]) == 1
    assert restricted_lap_identities(use="plant_fit") == []
    assert len(restricted_lap_identities(use="human_progression")) == 1
    for use in USES:
        decision = qualify_archive(record, use=use, expected_combo=archive_combo(record))
        assert decision.authority == "ai"
        assert decision.allowed is (use in {"analysis", "plant_fit"}), (use, decision)


def test_old_restrictive_native_entry_cannot_be_broadened(tmp_path, ledger):
    record = archive()
    path = write_native(tmp_path, record)
    register_attribution(path, assessment(record, authority="ai"))
    before = ledger.read_bytes()
    with pytest.raises(AttributionError, match="conflicting_attribution_identity"):
        register_native_test(tmp_path, record)
    assert ledger.read_bytes() == before
    assert not qualify_archive(record, use="plant_fit").allowed


@pytest.mark.parametrize(
    "change",
    [
        lambda w: w.update(session_uuid="other-session"),
        lambda w: w.update(driver="moza"),
        lambda w: w.update(clean_run=False),
        lambda w: w["report"].update(ok=False),
        lambda w: w["report"].update(session_uuid="other-session"),
        lambda w: w["report"]["drive"].update(recoveries=1),
        lambda w: w["report"]["drive"].update(sim_dead=True),
        lambda w: w["report"]["drive"].update(session_replaced=True),
        lambda w: w.update(timed_laps=[]),
        lambda w: w["app_install"].update(installed_digest="0" * 64),
        lambda w: w["archives"][0].update(source="imported"),
        lambda w: w["archives"][0].update(import_format="moza_tracecore_view_v1"),
        lambda w: w["archives"][0].update(payload_sha256="0" * 64),
        lambda w: w["archives"][0].update(source_sha256="0" * 64),
        lambda w: w["archives"][0]["identity"].update(lap_uuid="other-lap"),
    ],
)
def test_native_witness_fields_are_enforced_even_with_a_recomputed_hash(tmp_path, ledger, change):
    path, _ = register_native_test(tmp_path)
    data = json.loads(ledger.read_bytes())
    item = data["entries"][0]["qualification"]["evidence"][0]
    change(item["witness"])
    encoded = json.dumps(item["witness"], sort_keys=True, separators=(",", ":"), allow_nan=False)
    item["sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
    ledger.write_text(json.dumps(data), encoding="utf-8")
    decision = qualify_archive(json.loads(path.read_bytes()), use="plant_fit")
    assert not decision.allowed and decision.reason == "attribution_store_invalid"


def test_changed_native_witness_without_rehash_fails_closed(tmp_path, ledger):
    path, _ = register_native_test(tmp_path)
    data = json.loads(ledger.read_bytes())
    data["entries"][0]["qualification"]["evidence"][0]["witness"]["driver"] = "handshake"
    ledger.write_text(json.dumps(data), encoding="utf-8")
    assert (
        qualify_archive(json.loads(path.read_bytes()), use="plant_fit").reason
        == "attribution_store_invalid"
    )


@pytest.mark.parametrize(
    "report_change,app_change",
    [
        (lambda r: r.update(ok=False), None),
        (lambda r: r["drive"].update(recoveries=1), None),
        (lambda r: r["drive"].update(session_replaced=True), None),
        (None, lambda a: a.update(status="mismatch")),
    ],
)
def test_rejected_native_run_still_gets_restrictive_ai_attribution(
    tmp_path, report_change, app_change
):
    path, _ = register_native_test(tmp_path, report_change=report_change, app_change=app_change)
    record = json.loads(path.read_bytes())
    for use in USES - {"analysis"}:
        decision = qualify_archive(record, use=use, expected_combo=archive_combo(record))
        assert not decision.allowed and decision.authority == "ai"


@pytest.mark.parametrize("field,value", [("source", "imported"), ("import_format", "motec_csv")])
def test_native_producer_cannot_opt_imported_data_in(tmp_path, ledger, field, value):
    record = archive()
    record[field] = value
    before = ledger.read_bytes()
    with pytest.raises(AttributionError, match="native_harness_(source|schema)_required"):
        register_native_test(tmp_path, record)
    assert ledger.read_bytes() == before


def test_native_producer_requires_exact_observed_session_and_lap(tmp_path, ledger):
    before = ledger.read_bytes()
    with pytest.raises(AttributionError, match="native_harness_report_identity_mismatch"):
        register_native_test(
            tmp_path, report_change=lambda r: r.update(session_uuid="other-session")
        )
    assert ledger.read_bytes() == before


def test_native_plant_opt_in_defaults_off():
    from tools.ac_harness.auto_drive import _build_arg_parser

    parser = _build_arg_parser()
    assert not parser.parse_args(["--track", "synthetic"]).native_ai_plant_fit
    assert parser.parse_args(["--track", "synthetic", "--native-ai-plant-fit"]).native_ai_plant_fit


def test_incomplete_native_archive_window_is_attributed_but_not_fit(tmp_path):
    path, _ = register_native_test(
        tmp_path,
        report_change=lambda report: report["timed_laps"].append({"lap_n": 3, "lap_ms": 61000}),
    )
    decision = qualify_archive(json.loads(path.read_bytes()), use="plant_fit")
    assert not decision.allowed and decision.authority == "ai"


def test_original_native_and_direct_dict_follow_same_restriction(tmp_path):
    record = archive()
    path = write_native(tmp_path, record)
    before = path.read_bytes()
    assert register_attribution(path, assessment(record))["registered"]
    loaded = load_lap_archive(path)
    for candidate in (record, loaded):
        assert candidate["source"] == "in_game" and candidate["lap"]["is_pb"] is True
        assert qualify_archive(candidate, use="analysis").allowed
        for use in USES - {"analysis"}:
            decision = qualify_archive(
                candidate, use=use, expected_combo=("synthetic-car", "synthetic-track", None)
            )
            assert not decision.allowed
            assert decision.reason == "control_authority_not_human:shared"
        assert not _is_driver_lap(candidate)
        assert not observe_lap_tyre_state(candidate)["fit_eligible"]
        assert "control_authority_not_human" in observe_lap_tyre_state(candidate)["reason"]
    profile = build_profile([path])
    assert not profile["personal_bests"] and not profile["session_rollups"]
    assert "archive_qualification:control_authority_not_human" in profile["source"]["skipped"][0]
    assert path.read_bytes() == before
    assert "qualification" not in record


def test_byte_mismatch_remains_denied_after_loader_then_direct_check(tmp_path):
    record = archive()
    path = write_native(tmp_path, record)
    register_attribution(path, assessment(record))
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    # Canonical values are unchanged; only a byte-aware path reader can reject serialization drift.
    assert qualify_archive(record, use="analysis").allowed
    loaded = load_lap_archive(path)
    for _ in range(2):
        assert qualify_archive(loaded, use="analysis").reason == "attribution_source_hash_mismatch"


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda r: r["trace"]["samples"][0].__setitem__(1, 200), "attribution_payload_mismatch"),
        (lambda r: r.__setitem__("session_uuid", "different"), "attribution_identity_mismatch"),
        (lambda r: r["lap"].__setitem__("lap_n", 3), "attribution_identity_mismatch"),
        (lambda r: r.__setitem__("lap_uuid", "relabelled"), "attribution_identity_mismatch"),
        (lambda r: r["car"].__setitem__("id", "wrong-car"), "attribution_identity_mismatch"),
    ],
)
def test_selected_identity_never_falls_back_to_legacy(tmp_path, change, reason):
    record = archive()
    register_attribution(write_native(tmp_path, record), assessment(record))
    changed = copy.deepcopy(record)
    change(changed)
    assert qualify_archive(changed, use="human_progression").reason == reason


def test_ledger_wins_over_permissive_embedded_metadata(tmp_path):
    record = archive()
    register_attribution(write_native(tmp_path, record), assessment(record))
    record["qualification"] = assessment(record, authority="human", promoted=True)
    assert (
        qualify_archive(record, use="human_progression").reason
        == "control_authority_not_human:shared"
    )


def test_duplicate_ledger_identity_fails_closed(tmp_path, ledger):
    record = archive()
    register_attribution(write_native(tmp_path, record), assessment(record))
    saved = json.loads(ledger.read_text())
    saved["entries"].append(saved["entries"][0])
    ledger.write_text(json.dumps(saved), encoding="utf-8")
    assert qualify_archive(record, use="analysis").reason == "duplicate_attribution_identity"


def test_registration_is_idempotent_append_only_and_conflict_safe(tmp_path, ledger):
    record = archive()
    path = write_native(tmp_path, record)
    envelope = assessment(record)
    register_attribution(path, envelope)
    before = ledger.read_bytes()
    assert register_attribution(path, envelope)["reason"] == "already_registered"
    assert ledger.read_bytes() == before
    conflict = assessment(record, authority="ai")
    with pytest.raises(AttributionError, match="conflicting_attribution_identity"):
        register_attribution(path, conflict)
    assert ledger.read_bytes() == before


def test_concurrent_writer_lock_refuses_instead_of_lost_update(tmp_path, ledger):
    record = archive()
    path = write_native(tmp_path, record)
    before = ledger.read_bytes()
    lock = ledger.with_name(ledger.name + ".lock")
    lock.write_text("synthetic owner", encoding="utf-8")
    with pytest.raises(AttributionError, match="attribution_writer_busy"):
        register_attribution(path, assessment(record))
    assert ledger.read_bytes() == before and lock.exists()


def test_atomic_replace_failure_preserves_prior_ledger(tmp_path, ledger, monkeypatch):
    import tools.lap_qualification as module

    record = archive()
    path = write_native(tmp_path, record)
    before = ledger.read_bytes()

    def fail_replace(*args):
        raise OSError("synthetic atomic replacement refusal")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="synthetic"):
        register_attribution(path, assessment(record))
    assert ledger.read_bytes() == before
    assert not ledger.with_name(ledger.name + ".lock").exists()


@pytest.mark.parametrize(
    "authority,promoted,reason",
    [
        ("human", False, "registration_cannot_certify_human_control"),
        ("shared", True, "registration_cannot_promote_production_use"),
    ],
)
def test_native_registration_cannot_manufacture_promotion(tmp_path, authority, promoted, reason):
    record = archive()
    with pytest.raises(AttributionError, match=reason):
        register_attribution(
            write_native(tmp_path, record),
            assessment(record, authority=authority, promoted=promoted),
        )


def test_reader_refuses_changed_bytes_even_with_unchanged_metadata(tmp_path, monkeypatch):
    path = write_native(tmp_path)
    real_read = Path.read_bytes
    calls = 0

    def changing_read(current):
        nonlocal calls
        data = real_read(current)
        if current == path:
            calls += 1
            if calls == 2:
                return data[:-1] + b" "
        return data

    monkeypatch.setattr(Path, "read_bytes", changing_read)
    with pytest.raises(AttributionError, match="input_changed_during_read"):
        _stable_bytes(path)


def test_explicit_store_missing_or_invalid_is_not_legacy(ledger):
    ledger.unlink()
    assert qualify_archive(archive(), use="analysis").reason == "attribution_store_unavailable"
    ledger.write_text("not json", encoding="utf-8")
    assert qualify_archive(archive(), use="analysis").reason == "attribution_store_invalid"


def test_default_absence_preserves_legacy_unknown(tmp_path, monkeypatch):
    monkeypatch.delenv(ATTRIBUTIONS_ENV)
    monkeypatch.setenv("AC_COPILOT_LAP_ARCHIVE_DIR", str(tmp_path / "other" / "laps"))
    decision = qualify_archive(archive(), use="human_progression")
    assert decision.allowed and not decision.managed and decision.authority == "legacy_unknown"
    assert default_attribution_path() == tmp_path / "other" / "lap-attributions.json"


@pytest.mark.parametrize("authority", ["ai", "shared", "unknown"])
def test_claimed_support_does_not_override_authority(authority):
    record = archive()
    record["qualification"] = assessment(record, authority=authority, promoted=True)
    for use in USES - {"analysis"}:
        assert not qualify_archive(
            record, use=use, expected_combo=("synthetic-car", "synthetic-track", None)
        ).allowed


def test_explicit_synthetic_human_evidence_passes_only_correct_context():
    record = archive()
    record["qualification"] = assessment(record, authority="human", promoted=True)
    assert qualify_archive(
        record, use="live_reference", expected_combo=("synthetic-car", "synthetic-track", "")
    ).allowed
    assert qualify_archive(record, use="live_reference").reason == "expected_combo_unavailable"
    assert (
        qualify_archive(
            record, use="live_reference", expected_combo=("other-car", "synthetic-track", None)
        ).reason
        == "combo_mismatch"
    )
    record["qualification"]["evidence"] = None
    assert (
        qualify_archive(record, use="human_progression").reason == "human_control_evidence_missing"
    )


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (
            lambda r: r["qualification"]["channels"]["steer"].__setitem__("unit", "degrees"),
            "unsupported_channel_unit:steer",
        ),
        (
            lambda r: r["qualification"]["channels"]["eMs"].__setitem__("basis", "reconstructed"),
            "unmeasured_channel:eMs",
        ),
        (
            lambda r: r["qualification"].__setitem__("schema_version", 99),
            "qualification_schema_unsupported",
        ),
    ],
)
def test_support_flags_cannot_override_metadata_defects(mutation, reason):
    record = archive()
    record["qualification"] = assessment(record, authority="human", promoted=True)
    mutation(record)
    assert reason in qualify_archive(record, use="analysis").reasons


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda r: r["lap"].__setitem__("is_valid", None), "lap_validity_unproved"),
        (lambda r: r.__setitem__("schema_version", 99), "archive_schema_unsupported"),
        (
            lambda r: r["trace"]["samples"].__setitem__(50, r["trace"]["samples"][49]),
            "nonmonotonic_trace",
        ),
        (lambda r: r["trace"]["samples"].pop(0), "incomplete_lap_coverage"),
        (
            lambda r: r["trace"]["samples"][50].__setitem__(3, 2),
            "trace_value_out_of_range:throttle",
        ),
    ],
)
def test_bound_but_structurally_bad_record_is_denied(mutation, reason):
    record = archive()
    mutation(record)
    # First sample exactly .01 is intentionally allowed; remove one more for the coverage case.
    if reason == "incomplete_lap_coverage":
        record["trace"]["samples"].pop(0)
    record["qualification"] = assessment(record, authority="human", promoted=True)
    assert reason in qualify_archive(record, use="analysis").reasons


@pytest.mark.parametrize("bad", [None, [], "record"])
def test_malformed_root_yields_reason(bad):
    assert qualify_archive(bad, use="analysis").reason == "archive_root_invalid"


@pytest.mark.parametrize("number", [float("nan"), float("inf"), 10**400])
def test_nonfinite_and_overflow_values_never_escape_as_exception(number):
    record = archive()
    record["qualification"] = assessment(record)
    record["trace"]["samples"][0][1] = number
    assert not qualify_archive(record, use="analysis").allowed


def test_measured_multisample_finish_tail_is_not_raw_repaired():
    record = archive()
    record["trace"]["samples"].extend(
        [
            [0.001, 100, 60100, 0.7, 0.1, 5, 3, 0, 0, 0],
            [0.002, 100, 60200, 0.7, 0.1, 5, 3, 0, 0, 0],
        ]
    )
    before = copy.deepcopy(record)
    record["qualification"] = assessment(record)
    assert qualify_archive(record, use="analysis").allowed
    assert record["trace"] == before["trace"]


def test_tt_partial_stays_rejected_without_relabelling_complete_tt():
    record = archive()
    record.update(source="imported", import_format="track_titan_reference_v1")
    assert qualify_archive(record, use="analysis").allowed
    assert qualify_archive(record, use="live_reference").allowed
    assert qualify_archive(record, use="human_progression").reason == "non_driver_source:imported"
    record["generator"] = {"tt_reference": {"partial": True}}
    assert qualify_archive(record, use="live_reference").reason == "partial_tt_reference"


def test_combo_suffix_conflict_and_unavailable_layout():
    record = archive()
    record["track"] = {"id": "track/layout"}
    assert archive_combo(record) == ("synthetic-car", "track", "layout")
    record["track"]["layout"] = "different"
    assert archive_combo(record) is None
    record["track"] = {
        "id": "track",
        "identity_source": "csp_content_ids",
        "layout_available": False,
    }
    assert archive_combo(record) is None


def test_existing_compacted_profile_is_parked_without_overwriting_it(tmp_path):
    record = archive()
    path = write_native(tmp_path, record)
    existing = build_profile([path])
    existing["preferences"] = {"voice_verbosity": "low"}
    register_attribution(path, assessment(record))
    with pytest.raises(ProfileLoadError, match="profile_rebuild_required"):
        build_profile([], existing=existing)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(existing), encoding="utf-8")
    before = profile_path.read_bytes()
    with pytest.raises(ProfileLoadError, match="profile_rebuild_required"):
        load_profile(profile_path, strict=True)
    parked = load_profile(profile_path)
    assert parked["source"]["rebuild_required"]
    assert parked["preferences"] == existing["preferences"]
    assert parked["personal_bests"] == {}
    assert profile_path.read_bytes() == before


def test_unrelated_compacted_history_and_same_session_exact_other_lap_survive(tmp_path):
    known = archive()
    path = write_native(tmp_path, known)
    other = archive()
    other["lap_uuid"] = "other-lap"
    other["lap"]["lap_n"] = 3
    other_path = tmp_path / "lap_other.json"
    other_path.write_text(json.dumps(other), encoding="utf-8")
    existing = build_profile([other_path])
    register_attribution(path, assessment(known))
    rebuilt = build_profile([other_path], existing=existing)
    assert next(iter(rebuilt["personal_bests"].values()))["lap_uuid"] == "other-lap"


def test_register_cli_reports_receipt_without_changing_archive(tmp_path, capsys):
    record = archive()
    path = write_native(tmp_path, record)
    evidence = tmp_path / "qualification.json"
    evidence.write_text(json.dumps(assessment(record)), encoding="utf-8")
    before = path.read_bytes()
    assert main(["register", "--archive", str(path), "--qualification", str(evidence)]) == 0
    assert json.loads(capsys.readouterr().out)["registered"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("schema", [True, 99, "1", None])
def test_explicit_bad_schema_is_not_legacy(schema):
    record = archive()
    record["schema_version"] = schema
    assert qualify_archive(record, use="live_reference").reason == "archive_schema_unsupported"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"source": "garbage"}, "archive_source_unsupported"),
        (
            {"source": "imported", "import_format": "moza_tracecore_view_v999"},
            "import_format_unsupported",
        ),
        ({"import_format": "motec_csv"}, "native_import_format_conflict"),
        ({"session_uuid": None}, "archive_identity_unavailable"),
        ({"lap_uuid": 42}, "archive_identity_unavailable"),
    ],
)
def test_managed_source_and_identity_types_are_required(change, reason):
    record = archive()
    record.update(change)
    record["qualification"] = assessment(record, authority="human", promoted=True)
    assert reason in qualify_archive(record, use="analysis").reasons


@pytest.mark.parametrize("value", [True, 2.5, "2", None, 0])
def test_managed_lap_identity_types_are_required(value):
    record = archive()
    record["lap"]["lap_n"] = value
    record["qualification"] = assessment(record)
    assert "archive_lap_identity_invalid" in qualify_archive(record, use="analysis").reasons


def test_collection_rejects_both_managed_duplicates_before_profile_selection(tmp_path):
    first = archive()
    first["qualification"] = assessment(first, authority="human", promoted=True)
    second = copy.deepcopy(first)
    second["lap_uuid"] = "competing-id"
    second["qualification"] = assessment(second, authority="human", promoted=True)
    assert duplicate_identity_reasons([first, second]) == {
        0: "duplicate_archive_identity",
        1: "duplicate_archive_identity",
    }
    assert duplicate_identity_reasons([first, first]) == {
        0: "duplicate_archive_identity",
        1: "duplicate_archive_identity",
    }
    assert duplicate_identity_reasons([archive(), archive()]) == {}
    first_path = write_native(tmp_path, first)
    second_path = tmp_path / "lap_second.json"
    second_path.write_text(json.dumps(second), encoding="utf-8")
    profile = build_profile([first_path, second_path])
    assert not profile["personal_bests"]
    assert all("duplicate_archive_identity" in item for item in profile["source"]["skipped"])


@pytest.mark.parametrize(
    "corruption",
    [
        lambda e: e.__setitem__("identity", {}),
        lambda e: e["identity"].__setitem__("lap_uuid", []),
        lambda e: e["identity"].__setitem__("lap_n", True),
        lambda e: e["identity"].__setitem__("lap_ms", 10**400),
        lambda e: e["qualification"].__setitem__("schema_version", True),
        lambda e: e["qualification"].__setitem__("authority", "human"),
        lambda e: e["qualification"].__setitem__("evidence", None),
        lambda e: e["qualification"]["binding"].__setitem__("payload_sha256", "wrong"),
        lambda e: e["qualification"]["supported_uses"].__setitem__("plant_fit", True),
    ],
)
def test_corrupt_ledger_entry_parks_profile_instead_of_crashing(tmp_path, ledger, corruption):
    record = archive()
    path = write_native(tmp_path, record)
    existing = build_profile([path])
    register_attribution(path, assessment(record))
    data = json.loads(ledger.read_text())
    corruption(data["entries"][0])
    ledger.write_text(json.dumps(data), encoding="utf-8")
    assert qualify_archive(record, use="analysis").reason == "attribution_store_invalid"
    with pytest.raises(
        ProfileLoadError, match="profile_rebuild_required:attribution_store_invalid"
    ):
        build_profile([], existing=existing)
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(existing), encoding="utf-8")
    assert load_profile(profile_path)["source"]["rebuild_required"]


def test_loader_does_not_accept_bool_schema_as_integer_one(tmp_path):
    record = archive()
    record["schema_version"] = True
    path = write_native(tmp_path, record)
    with pytest.raises(LapArchiveExportError, match="schema_version"):
        load_lap_archive(path, allow_legacy_schema=True)


@pytest.mark.parametrize("completion", [{"complete": False}, {"partial": True}])
def test_explicit_partial_cannot_be_promoted_by_complete_looking_trace(completion):
    record = archive()
    record["lap"].update(completion)
    record["qualification"] = assessment(record, authority="human", promoted=True)
    for use in USES:
        assert (
            "lap_incomplete"
            in qualify_archive(
                record, use=use, expected_combo=("synthetic-car", "synthetic-track", None)
            ).reasons
        )


def test_negative_elapsed_origin_is_not_hidden_by_correct_duration_delta():
    record = archive()
    for row in record["trace"]["samples"]:
        row[2] -= 1000
    record["qualification"] = assessment(record, authority="human", promoted=True)
    assert "negative_elapsed_time" in qualify_archive(record, use="analysis").reasons


@pytest.mark.parametrize("uses", [None, {"analysis": "true"}, {"invented_use": False}])
def test_registration_refuses_malformed_envelope_before_publishing(tmp_path, ledger, uses):
    record = archive()
    envelope = assessment(record)
    envelope["supported_uses"] = uses
    before = ledger.read_bytes()
    with pytest.raises(AttributionError, match="attribution_store_invalid"):
        register_attribution(write_native(tmp_path, record), envelope)
    assert ledger.read_bytes() == before
