"""Synthetic same-session bootstrap, without driving or real human attribution."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import replace

import pytest

from tests.test_coaching_practice_runtime import COMBO as RUNTIME_COMBO
from tests.test_coaching_practice_runtime import _reference, _thermal_record
from tests.test_coaching_practice_session import (
    COMBO,
    HUMAN,
    SESSION,
    SUMMARY,
    NativePractice,
    _archive,
)
from tests.test_coaching_v2 import _sig
from tests.test_human_session import complete_native_lap, payload, session_fixture
from tools.ai_sidecar.coachable_frontier import FrontierError, build_human_drill_target
from tools.ai_sidecar.coaching.practice import PracticeSession
from tools.ai_sidecar.coaching_ledger import CoachingLedger
from tools.ai_sidecar.coaching_runtime import (
    build_coach_runtime,
    practice_archive_conditions,
    practice_frame_conditions,
    practice_reference_usable,
)
from tools.ai_sidecar.realtime_observer import build_observer_from_reference
from tools.human_session import PRACTICE_COMBO
from tools.lap_archive_export import load_lap_archive
from tools.lap_qualification import (
    build_qualification,
    qualify_archive,
    qualify_practice_archive,
    register_practice_attribution,
)


@pytest.fixture(autouse=True)
def isolated_provenance(tmp_path, monkeypatch):
    ledger = tmp_path / "synthetic-attributions.json"
    ledger.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))


def _pending(combo=COMBO):
    return NativePractice(session=PracticeSession.pending_reference(combo, "trail-brake-entry"))


def _warmup(rig, *, record=None, eligible=True, reference_eligible=True, gap=False):
    record = copy.deepcopy(record if record is not None else _archive(rig.ordinal))
    rig.close_native_window(gap_inside=gap)
    status = rig.session.record_warmup(
        record,
        HUMAN,
        condition_eligible=eligible,
        reference_eligible=reference_eligible,
    )
    rig.ordinal += 1
    rig.start += 10
    return status


def test_bootstrap_keeps_one_collector_and_ten_lap_experiment():
    rig = _pending()
    collector, ledger = rig.session, rig.session.ledger
    assert not collector.instruction_allowed
    _warmup(rig)
    assert collector.reference_candidate() is None
    status = _warmup(rig)
    assert status["observed_laps"] == 2 and status["baseline_laps"] == 0
    candidate = collector.reference_candidate()
    assert candidate["lap_uuid"] == "immutable-lap-1"
    collector.install_reference({0: _sig()}, HUMAN, candidate["lap_uuid"])
    assert collector is rig.session and collector.ledger is ledger
    assert collector.status()["observed_laps"] == 2 and len(collector._windows) == 3
    baseline = _sig(trail_brake_frac=0.1, min_speed_kmh=70)
    for _ in range(3):
        status = rig.complete(signature=baseline)
    assert status["observed_laps"] == 5 and status["cued_attempts"] == 0
    for _ in range(3):
        rig.dispatch()
        status = rig.complete()
    assert status["phase"] == "retention"
    rig.complete()
    status = rig.complete()
    assert status["phase"] == "passed" and status["observed_laps"] == 10
    assert len(status["evidence"]) == 10 and collector.ledger is ledger


def test_earliest_native_slot_wins_even_when_archives_arrive_out_of_order():
    rig = _pending()
    rig.close_native_window()
    rig.ordinal, rig.start = 2, 110
    rig.close_native_window()
    for ordinal in (2, 1):
        rig.session.record_warmup(
            _archive(ordinal), HUMAN, condition_eligible=True, reference_eligible=True
        )
        if ordinal == 2:
            assert rig.session.reference_candidate() is None
    assert rig.session.reference_candidate()["lap_uuid"] == "immutable-lap-1"
    assert rig.session.status()["observed_laps"] == 2


@pytest.mark.parametrize(
    "defect", ["conditions", "qualification", "summary", "gap", "partial", "import"]
)
def test_ineligible_first_warmup_uses_second_without_an_extra_seed_lap(defect):
    rig = _pending()
    record = _archive(1)
    if defect == "summary":
        record["trace"]["off_track_observation"]["unknown_count"] = 1
    if defect == "partial":
        rig.session._windows[(SESSION, 1)].full_start = False
    if defect == "import":
        record.update(source="imported", import_format="motec_csv")
    _warmup(
        rig,
        record=record,
        eligible=defect != "conditions",
        reference_eligible=defect != "qualification",
        gap=defect == "gap",
    )
    _warmup(rig)
    assert rig.session.reference_candidate()["lap_uuid"] == "immutable-lap-2"
    assert rig.session.status()["observed_laps"] == 2


def test_two_ineligible_warmups_are_terminal_and_lap_three_cannot_be_a_seed():
    rig = _pending()
    _warmup(rig, eligible=False)
    status = _warmup(rig, eligible=False)
    assert status["phase"] == "aborted"
    assert status["reason"] == "eligible_warmup_reference_unavailable"
    assert status["observed_laps"] == 2
    assert rig.session.reference_candidate() is None
    status = _warmup(rig)
    assert status["observed_laps"] == 2 and status["phase"] == "aborted"
    with pytest.raises(ValueError, match="install_rejected"):
        rig.session.install_reference({0: _sig()}, HUMAN, "immutable-lap-3")


def test_late_second_warmup_cannot_replay_a_baseline_or_restart_the_block():
    rig = _pending()
    _warmup(rig)
    rig.close_native_window()  # Native lap 2 finished, but its archive is delayed.
    rig.ordinal, rig.start = 3, 120
    status = rig.complete()
    assert status["phase"] == "aborted"
    assert status["reason"] == "warmup_reference_required_before_baseline"
    assert [row["lap_n"] for row in status["evidence"]] == [1, 3]
    before = copy.deepcopy(status)
    late = rig.session.record_warmup(
        _archive(2), HUMAN, condition_eligible=True, reference_eligible=True
    )
    assert late == before and late["baseline_laps"] == 0
    assert rig.session.reference_candidate() is None
    assert not rig.session.instruction_allowed


def test_freeze_cannot_replace_reference_or_reset_budget_and_candidate_is_a_copy():
    rig = _pending()
    _warmup(rig)
    _warmup(rig)
    candidate = rig.session.reference_candidate()
    candidate["lap_uuid"] = "changed"
    assert rig.session.reference_candidate()["lap_uuid"] == "immutable-lap-1"
    rig.session.install_reference({0: _sig()}, HUMAN, "immutable-lap-1")
    before = rig.session.status()
    with pytest.raises(ValueError, match="install_rejected"):
        rig.session.install_reference({0: _sig()}, HUMAN, "immutable-lap-2")
    assert rig.session.status() == before


def _native_reference(ordinal):
    record = _thermal_record()
    record.update(session_uuid=SESSION, lap_uuid=f"native-reference-{ordinal}")
    record["lap"]["lap_n"] = ordinal
    record["trace"]["off_track_observation"] = dict(SUMMARY)
    envelope = _reference()["qualification"]
    record["qualification"] = build_qualification(
        record,
        authority="human",
        origin="synthetic-test-only",
        supported_uses=envelope["supported_uses"],
        channels=envelope["channels"],
        evidence=envelope["evidence"],
    )
    return record


def test_real_runtime_install_reuses_warmup_windows_ledger_and_count():
    rig = _pending((RUNTIME_COMBO[0], RUNTIME_COMBO[1], ""))
    records = [_native_reference(ordinal) for ordinal in (1, 2)]
    for record in records:
        assert practice_archive_conditions(record, practice_session=rig.session)
        assert qualify_archive(record, use="live_reference", expected_combo=RUNTIME_COMBO).allowed
        _warmup(rig, record=record)
    ledger = rig.session.ledger
    windows = copy.deepcopy(rig.session._windows)
    raw = copy.deepcopy(records[0])
    diagnostics = {}
    runtime = build_coach_runtime(
        rig.session.reference_candidate(),
        expected_combo=RUNTIME_COMBO,
        use_environment=False,
        practice_session=rig.session,
        diagnostics=diagnostics,
        canonical_corner_catalog={
            "available": True,
            "combo": [RUNTIME_COMBO[0], RUNTIME_COMBO[1], ""],
            "corners": [{"corner_id": "T7", "s0": 0.25, "s1": 0.8, "brake_spline": 0.22}],
        },
    )
    assert runtime is not None, diagnostics
    assert runtime.practice is rig.session and runtime.ledger is ledger
    assert runtime.practice.status()["observed_laps"] == 2
    assert runtime.practice._windows == windows
    assert runtime.practice.reference_identity == records[0]["lap_uuid"]
    assert runtime.corner_identity["ready"]
    assert set(runtime.corner_identity["labels"].values()) == {"T7"}
    assert records[0] == raw


@pytest.mark.parametrize("defect", ["thermal", "brake", "trace_gap", "off_track"])
def test_runtime_cannot_install_a_warmup_that_lacks_full_measurements(defect):
    rig = _pending((RUNTIME_COMBO[0], RUNTIME_COMBO[1], ""))
    record = _native_reference(1)
    fields = record["trace"]["fields"]
    if defect in {"thermal", "brake"}:
        name = "tyreCoreTemp_fr" if defect == "thermal" else "brakeTemp_rr"
        record["trace"]["samples"][3][fields.index(name)] = -1
    elif defect == "trace_gap":
        record["trace"]["samples"][3][fields.index("eMs")] += 500
    else:
        record["trace"]["off_track_observation"]["complete"] = False
    # Force a permissive caller flag: the runtime must independently inspect the data.
    _warmup(rig, record=record)
    _warmup(rig, record=_native_reference(2))
    candidate = rig.session.reference_candidate()
    if defect == "off_track":
        assert candidate["lap_uuid"] == "native-reference-2"
        return
    diagnostics = {}
    assert (
        build_coach_runtime(
            candidate,
            expected_combo=RUNTIME_COMBO,
            use_environment=False,
            practice_session=rig.session,
            diagnostics=diagnostics,
        )
        is None
    )
    assert not diagnostics["allowed"]


def _live_thermal():
    return {
        "tyre_temps_c": dict.fromkeys(("fl", "fr", "rl", "rr"), 90.0),
        "brake_temps_c": dict.fromkeys(("fl", "fr", "rl", "rr"), 400.0),
        "tyre_optimal_temp_c": 90.0,
        "conditions": {"weatherType": "clear", "trackGripLevel": 1.0},
    }


@pytest.mark.parametrize("nested", [False, True])
def test_pending_live_gate_requires_actual_conditions_and_full_four_wheel_measurements(nested):
    frame = _live_thermal()
    wrap = (lambda value: {"payload": value}) if nested else (lambda value: value)
    assert practice_frame_conditions(wrap(frame)) == (True, "")
    for field in ("tyre_optimal_temp_c", "conditions", "tyre_temps_c", "brake_temps_c"):
        invalid = copy.deepcopy(frame)
        del invalid[field]
        eligible, reason = practice_frame_conditions(wrap(invalid))
        assert not eligible and reason == "thermal_evidence_required"


@pytest.mark.parametrize("field", ["tyre_temps_c", "brake_temps_c"])
@pytest.mark.parametrize("value", [None, float("nan"), True, -0.1, "90"])
def test_pending_live_gate_does_not_sanitize_one_missing_or_invalid_wheel_into_eligibility(
    field, value
):
    frame = _live_thermal()
    frame[field]["rr"] = value
    assert practice_frame_conditions(frame)[0] is False


def test_pending_live_gate_reports_thermal_abort_before_any_reference_exists():
    frame = _live_thermal()
    frame["tyre_temps_c"]["fr"] = 180.0
    eligible, reason = practice_frame_conditions(frame)
    assert not eligible and reason in {"tyre_temp_overheat", "tyre_temp_critical"}


def _scoped_raw_reference(ordinal):
    """Synthetic sixty-second geometry/trace; never written to a real journal."""
    record = _thermal_record()
    record.update(session_uuid="synthetic-native-session", lap_uuid=f"scoped-warmup-{ordinal}")
    record["track"]["id"] = PRACTICE_COMBO[1]
    record["lap"].update(lap_n=ordinal, lap_ms=60000)
    trace = record["trace"]
    time_index = trace["fields"].index("eMs")
    source = trace["samples"]
    scale = 60000 / source[-1][time_index]
    dense = []
    for left, right in zip(source, source[1:], strict=False):
        pieces = math.ceil((right[time_index] - left[time_index]) * scale / 250)
        for part in range(pieces):
            fraction = part / pieces
            sample = [a + (b - a) * fraction for a, b in zip(left, right, strict=True)]
            sample[time_index] *= scale
            dense.append(sample)
    dense.append(list(source[-1]))
    dense[-1][time_index] = 60000
    trace["samples"] = dense
    trace["off_track_observation"] = {**SUMMARY, "sample_count": len(dense) * 2}
    return record


def test_canonical_scoped_attestation_bootstraps_without_generic_reference_promotion(tmp_path):
    permit, archive_root = session_fixture(tmp_path)
    combo = (PRACTICE_COMBO[0], PRACTICE_COMBO[1], "")
    practice = PracticeSession.pending_reference(combo, "trail-brake-entry", practice_permit=permit)
    practice.observe_native(payload(), condition_eligible=True, ineligible_reason="", now=0)
    original_bytes = {}
    decisions = []
    for ordinal in (1, 2):
        complete_native_lap(permit, ordinal, begin=ordinal == 1)
        origin = (ordinal - 1) * 60.25
        for elapsed in range(250, 60001, 250):
            practice.observe_native(
                payload(ordinal, elapsed, min(0.999, elapsed / 60000)),
                condition_eligible=True,
                ineligible_reason="",
                now=origin + elapsed / 1000,
            )
        practice.observe_native(
            payload(ordinal + 1),
            condition_eligible=True,
            ineligible_reason="",
            now=origin + 60.25,
        )
        path = archive_root / f"lap_scoped_{ordinal}.json"
        path.write_text(json.dumps(_scoped_raw_reference(ordinal)), encoding="utf-8")
        original_bytes[path] = path.read_bytes()
        register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
        record = load_lap_archive(path)
        trial = qualify_practice_archive(
            record, use="practice_trial", permit=permit, expected_combo=PRACTICE_COMBO
        )
        reference = qualify_practice_archive(
            record, use="practice_reference", permit=permit, expected_combo=PRACTICE_COMBO
        )
        assert trial.allowed and reference.allowed
        assert trial.authority == reference.authority == "attested_human"
        decisions.append(trial)
        practice.record_warmup(
            record,
            trial,
            condition_eligible=practice_archive_conditions(record),
            reference_eligible=practice_reference_usable(
                record, practice_permit=permit, expected_combo=PRACTICE_COMBO
            ),
        )
    candidate = practice.reference_candidate()
    assert candidate["lap_uuid"] == "scoped-warmup-1"
    for use in ("human_progression", "live_reference", "map", "reference_comparison", "plant_fit"):
        assert not qualify_archive(candidate, use=use, expected_combo=PRACTICE_COMBO).allowed
    assert (
        build_coach_runtime(candidate, expected_combo=PRACTICE_COMBO, use_environment=False) is None
    )
    assert build_observer_from_reference(candidate, expected_combo=PRACTICE_COMBO) is None
    assert (
        build_observer_from_reference(
            candidate, expected_combo=PRACTICE_COMBO, practice_permit=permit
        )
        is not None
    )
    diagnostics = {}
    assert (
        build_coach_runtime(
            candidate,
            expected_combo=PRACTICE_COMBO,
            practice_permit=permit,
            use_environment=False,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics["reason"] == "practice_session_required"
    runtime = build_coach_runtime(
        candidate,
        expected_combo=PRACTICE_COMBO,
        practice_session=practice,
        practice_permit=permit,
        use_environment=False,
    )
    assert runtime is not None and runtime.practice is practice
    assert runtime.ledger is practice.ledger and practice.status()["observed_laps"] == 2
    assert practice.reference_qualification.authority == "attested_human"
    kwargs = dict(
        reference_qualification=decisions[0],
        baseline_qualification=decisions[1],
        drill_id="trail-brake-entry",
        combo=combo,
        baseline_corner_time_s=8.0,
        reference_identity="scoped-warmup-1",
        baseline_identity="synthetic-baseline",
    )
    with pytest.raises(FrontierError, match="qualified_human_archives"):
        build_human_drill_target(_sig(), _sig(trail_brake_frac=0.1), **kwargs)
    with pytest.raises(FrontierError, match="qualified_human_archives"):
        build_human_drill_target(
            _sig(), _sig(trail_brake_frac=0.1), **kwargs, practice_permit=object()
        )
    target = build_human_drill_target(
        _sig(), _sig(trail_brake_frac=0.1), **kwargs, practice_permit=permit
    )
    assert target.to_dict()["source"] == "operator_attested_session_practice"
    ledger = CoachingLedger(drills_enabled=True)
    with pytest.raises(ValueError, match="practice_permit_required"):
        ledger.start_drill(target)
    with pytest.raises(ValueError, match="practice_permit_required"):
        ledger.start_drill(target, practice_permit=object())
    ledger.start_drill(target, practice_permit=permit)
    ledger.stage_drill_pass(_sig(), corner_time_s=8, lap_uuid="synthetic-trial")
    result = ledger.complete_drill_lap(
        lap_uuid="synthetic-trial",
        session_uuid="synthetic-native-session",
        combo=combo,
        qualification=decisions[1],
        valid=True,
        off_track=False,
        cued=True,
        condition_eligible=True,
    )
    assert result["advanced"] is True and result["cued_successes"] == 1
    ordinary = CoachingLedger(drills_enabled=True)
    ordinary.start_drill(replace(target, practice_only=False))
    ordinary.stage_drill_pass(_sig(), corner_time_s=8, lap_uuid="generic-denied-trial")
    rejected = ordinary.complete_drill_lap(
        lap_uuid="generic-denied-trial",
        session_uuid="synthetic-native-session",
        combo=combo,
        qualification=decisions[1],
        valid=True,
        off_track=False,
        cued=True,
        condition_eligible=True,
    )
    assert not rejected["advanced"]
    assert rejected["reason"] == "completed_qualified_human_lap_required"
    assert all(path.read_bytes() == raw for path, raw in original_bytes.items())


@pytest.mark.parametrize(
    "defect", ["summary", "unknown", "cold", "missing_brake", "subsecond_gap", "wrapped_anchor"]
)
def test_scoped_attribution_does_not_replace_full_reference_measurements(tmp_path, defect):
    permit, root = session_fixture(tmp_path)
    complete_native_lap(permit)
    record = _scoped_raw_reference(1)
    fields = record["trace"]["fields"]
    rows = record["trace"]["samples"]
    if defect == "summary":
        del record["trace"]["off_track_observation"]
    elif defect == "unknown":
        record["trace"]["off_track_observation"]["unknown_count"] = 1
    elif defect == "cold":
        rows[10][fields.index("tyreCoreTemp_fl")] = 30.0
    elif defect == "missing_brake":
        column = fields.index("brakeTemp_fr")
        del fields[column]
        for row in rows:
            del row[column]
    elif defect == "subsecond_gap":
        del rows[20:22]
    else:
        # Move the synthetic corner near start/finish while keeping a complete
        # monotone lap clock. Its anticipatory observation window crosses laps.
        shifted = rows[len(rows) // 4 :] + [rows[-1]] * (len(rows) // 4)
        clock = {fields.index("spline"), fields.index("eMs")}
        for row, later in zip(rows, copy.deepcopy(shifted), strict=True):
            for column in range(len(fields)):
                if column not in clock:
                    row[column] = later[column]
    path = root / "lap_unusable_reference.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    archive_bytes = path.read_bytes()
    register_practice_attribution(path, permit=permit, expected_combo=PRACTICE_COMBO)
    resolved = load_lap_archive(path)
    assert qualify_practice_archive(
        resolved, use="practice_reference", permit=permit, expected_combo=PRACTICE_COMBO
    ).allowed
    campaign_bytes = permit.path.read_bytes()
    assert not practice_reference_usable(
        resolved, practice_permit=permit, expected_combo=PRACTICE_COMBO
    )
    diagnostics = {}
    assert (
        build_coach_runtime(
            resolved,
            expected_combo=PRACTICE_COMBO,
            practice_permit=permit,
            use_environment=False,
            diagnostics=diagnostics,
        )
        is None
    )
    assert diagnostics["reason"] == "practice_reference_evidence_unavailable"
    assert (
        build_observer_from_reference(
            resolved, expected_combo=PRACTICE_COMBO, practice_permit=permit
        )
        is None
    )
    assert path.read_bytes() == archive_bytes and permit.path.read_bytes() == campaign_bytes
