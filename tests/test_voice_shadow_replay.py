"""Synthetic contract evidence only; no fixture establishes observed human control."""

from __future__ import annotations

import builtins
import copy
import json
import socket
import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from _voice_support import FakeClock, build_manifest, make_advisory

from tools.ai_sidecar import coaching_runtime
from tools.ai_sidecar.realtime_observer import CornerReference
from tools.ai_sidecar.voice.config import VoiceConfig
from tools.ai_sidecar.voice.playback import RecordingPlayback
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.scheduler import Scheduler
from tools.ai_sidecar.voice.shadow_replay import _lane, build_shadow_replay
from tools.lap_qualification import (
    ATTRIBUTIONS_ENV,
    USES,
    build_qualification,
    register_attribution,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "magione_gt3r_reference.json"
_UNITS = {
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


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    path = tmp_path / "attributions.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv(ATTRIBUTIONS_ENV, str(path))
    return path


def archive(name="stimulus"):
    result = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    result.update(
        schema_version=1, source="in_game", session_uuid="synthetic-" + name, lap_uuid=name
    )
    result["track"]["layout"] = None
    result["lap"].update(lap_n=1, complete=True)
    return result


def restrict(record, authority="shared"):
    record["qualification"] = build_qualification(
        record,
        authority=authority,
        origin="synthetic_contract_test",
        supported_uses={use: use == "analysis" for use in USES},
        channels={k: {"unit": v, "basis": "measured"} for k, v in _UNITS.items()},
        evidence=[{"kind": "synthetic_intervention", "sha256": "f" * 64}],
    )
    return record


def replay(stimulus=None, reference=None, **kwargs):
    return build_shadow_replay(
        stimulus if stimulus is not None else archive(),
        reference if reference is not None else archive("reference"),
        evidence_kind="synthetic_contract_test",
        **kwargs,
    )


def test_full_silent_replay_is_nonvacuous_and_keeps_reference_uncertainty():
    report = replay(restrict(archive()))
    assert report["available"] and report["status"] == "replayed"
    assert report["stimulus"]["authority"] == "shared"
    assert report["reference"]["authority"] == "legacy_unknown"
    assert "reference:human_control_unproved" in report["decision"]["reasons"]
    assert report["decision"]["human_evaluation"] == "no_go"
    assert report["decision"]["live_activation"] == "no_go"
    assert report["evidence_kind"] == "synthetic_contract_test"
    assert not report["activation_allowed"]
    assert report["lanes"]["observer"]["dispatched_count"] > 0
    assert report["lanes"]["coach_v2"]["frames_replayed"] == 1754
    assert report["lanes"]["coach_v2"]["reason"] == "no_advisories_emitted_on_this_recording"
    assert report["lanes"]["observer"]["checks"]["non_vacuous_dispatch"]
    json.dumps(report, allow_nan=False)


def test_missing_reference_still_reports_actual_brake_events():
    source = archive()
    report = build_shadow_replay(source)
    assert not report["available"]
    assert report["reason"] == "independent_reference_unavailable"
    assert report["measured_brake_events"]
    assert report["lanes"]["observer"]["frames_replayed"] == 0
    for event in report["measured_brake_events"]:
        index = event["sample_index"]
        row = source["trace"]["samples"][index]
        assert event["t_event_ms"] == row[2]
        assert row[4] > 0.05
        assert index == 0 or source["trace"]["samples"][index - 1][4] <= 0.05


def test_measured_brake_onset_preceding_window_is_not_clipped():
    report = replay()
    events = report["measured_brake_events"]
    assert events and all(e["corner"] is not None for e in events)
    for event in events:
        # Compare to the recorded edge, not the reference window's first sample.
        i = event["sample_index"]
        assert archive()["trace"]["samples"][i - 1][4] <= 0.05
    cues = report["lanes"]["observer"]["cues"]
    timed = [c for c in cues if c["lead_to_measured_brake_ms"] is not None]
    assert timed
    for cue in timed:
        event = events[cue["measured_brake_event_id"]]
        assert cue["lead_to_measured_brake_ms"] == event["t_event_ms"] - cue["t_dispatch_ms"]
        assert cue["phrase"] and cue["clip_id"]
        assert cue["modeled_clip_finish_lead_ms"] == cue["lead_to_measured_brake_ms"] - 400
        if cue["producer_lead_budget_ms"] is not None:
            assert cue["lead_meets_producer_budget"] == (
                cue["lead_to_measured_brake_ms"] >= cue["producer_lead_budget_ms"]
            )


@pytest.mark.parametrize(
    "value", [None, True, "1", float("nan"), float("inf"), -float("inf"), 10**400]
)
def test_malformed_elapsed_values_reject_without_fake_cadence(value):
    source = archive()
    source["trace"]["samples"][12][2] = value
    report = replay(source)
    assert not report["available"]
    assert report["reason"] == "stimulus:nonfinite_or_missing_trace_value"
    assert report["measured_brake_events"] == []


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("duplicate", "nonmonotonic_elapsed_time"),
        ("backwards", "nonmonotonic_elapsed_time"),
        ("negative", "negative_elapsed_time"),
        ("gap", "trace_time_gap"),
    ],
)
def test_bad_recorded_time_rejects(mode, reason):
    source = archive()
    rows = source["trace"]["samples"]
    if mode == "duplicate":
        rows[12][2] = rows[11][2]
    elif mode == "backwards":
        rows[12][2] = rows[11][2] - 1
    elif mode == "negative":
        rows[0][2] = -1
    else:
        del rows[12:80]
    report = replay(source)
    assert not report["available"]
    assert report["reason"] == "stimulus:" + reason


@pytest.mark.parametrize("role", ["stimulus", "reference"])
def test_missing_control_channel_rejects_in_both_roles(role):
    source, reference = archive(), archive("reference")
    target = source if role == "stimulus" else reference
    fi = target["trace"]["fields"].index("brake")
    target["trace"]["fields"].pop(fi)
    for row in target["trace"]["samples"]:
        row.pop(fi)
    report = replay(source, reference)
    assert not report["available"]
    assert report["reason"] == role + ":missing_measured_channels:brake"


@pytest.mark.parametrize("field,value", [("car", "wrong-car"), ("track", "wrong-track")])
def test_legacy_reference_must_match_exact_combo(field, value):
    ref = archive("reference")
    ref[field]["id"] = value
    report = replay(reference=ref)
    assert not report["available"]
    assert report["reason"] == "reference:combo_mismatch"


@pytest.mark.parametrize("authority", ["ai", "shared", "unknown"])
def test_managed_nonhuman_reference_is_never_promoted(authority):
    report = replay(reference=restrict(archive("reference"), authority))
    assert not report["available"]
    assert f"reference:control_authority_not_human:{authority}" in report["no_go_reasons"]
    assert report["lanes"]["observer"]["dispatched_count"] == 0


def test_same_archive_cannot_serve_both_roles():
    source = archive()
    report = replay(source, copy.deepcopy(source))
    assert not report["available"]
    assert report["reason"] == "reference:not_independent_of_stimulus"


def test_same_session_lap_identity_cannot_be_made_independent_by_renaming():
    source, reference = archive(), archive("reference")
    reference["session_uuid"] = source["session_uuid"]
    report = replay(source, reference)
    assert not report["available"]
    assert report["reason"] == "reference:not_independent_of_stimulus"


def test_missing_phrase_metadata_is_explicit_suppression():
    manifest = replace(build_manifest(), clips={})
    report = replay(manifest=manifest)
    assert report["available"]
    assert report["lanes"]["observer"]["dispatched_count"] == 0
    assert {c["status"] for c in report["lanes"]["observer"]["cues"]} == {"unresolved_phrase"}


def test_finish_tail_is_excluded_without_changing_recording():
    source = archive()
    tail = list(source["trace"]["samples"][0])
    tail[0], tail[2] = 0.0001, source["trace"]["samples"][-1][2] + 50
    source["trace"]["samples"].append(tail)
    before = copy.deepcopy(source)
    report = replay(source)
    assert report["available"]
    assert report["stimulus"]["trimmed_finish_tail_samples"] == 1
    assert report["lanes"]["observer"]["frames_replayed"] == 1754
    assert source == before


def test_unmatched_or_suppressed_cues_have_no_invented_dispatch_time():
    report = replay(config=VoiceConfig(verbosity="off"))
    cues = report["lanes"]["observer"]["cues"]
    assert cues
    assert all(c["status"] == "verbosity_off" for c in cues)
    assert all(c["t_dispatch_ms"] is None and c["lead_to_measured_brake_ms"] is None for c in cues)
    assert not report["lanes"]["observer"]["checks"]["non_vacuous_dispatch"]
    assert "no_dispatched_cues;timing_not_proved" in report["no_go_reasons"]


def test_recorded_late_mistake_runs_real_coach_save_path():
    source = archive()
    for row in source["trace"]["samples"]:
        row[4], row[3] = 0.0, 0.9
    report = replay(source)
    lane = report["lanes"]["coach_v2"]
    assert lane["dispatched_count"] > 0
    assert any(c["kind"] == "save" and c["phrase"] == "Brake!" for c in lane["cues"])
    # No pedal event was recorded, so this is not evidence of a positive brake lead.
    assert report["measured_brake_events"] == []
    assert not lane["checks"]["measured_brake_timing_available"]
    assert lane["cue_timing_counts"]["reactive_save"] == lane["dispatched_count"]
    assert lane["cue_timing_counts"]["anticipatory_brake"] == 0
    assert lane["checks"]["all_dispatched_brake_cues_before_measured_onset"] is None


def test_reactive_save_after_a_real_brake_is_not_a_failed_anticipatory_instruction():
    class Producer:
        def observe(self, frame):
            return [
                make_advisory(kind="save", register="critical", corner=0, detail={"coach": "save"})
            ]

    lane = _lane(
        Producer(),
        [{"eMs": 1000}, {"eMs": 1500}],
        [{"event_id": 0, "corner": 0, "spline": 0.2, "t_event_ms": 900}],
        [CornerReference(0, 0.3, 0.1, 0.4, 80, best_brake_point_spline=0.2)],
        track_m=1000,
        manifest=build_manifest(),
        durations={},
        config=VoiceConfig(),
    )
    assert lane["dispatched_count"] > 0
    assert lane["cue_timing_counts"]["reactive_save"] == lane["dispatched_count"]
    assert all(cue["lead_to_measured_brake_ms"] is None for cue in lane["cues"])
    assert lane["late_brake_onset_count"] == 0
    assert lane["checks"]["all_dispatched_brake_cues_before_measured_onset"] is None
    assert lane["checks"]["all_brake_prepare_leads_meet_producer_budget"] is None


def test_replay_is_read_only_and_ignores_ambient_live_configuration(monkeypatch, isolated_ledger):
    source, ref = restrict(archive()), archive("reference")
    before_source, before_ref, before_ledger = (
        copy.deepcopy(source),
        copy.deepcopy(ref),
        isolated_ledger.read_bytes(),
    )
    monkeypatch.setenv("AC_COPILOT_DRIVER_PROFILE", "unselected-private-profile.json")
    monkeypatch.setenv("AC_COPILOT_ALIEN_LINE", "unselected-alien.json")
    monkeypatch.setenv("AC_COPILOT_COACH_ASSESS_LAPS", "999")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline replay attempted a live side effect")

    for target, name in [
        (socket, "socket"),
        (subprocess, "Popen"),
        (threading.Thread, "start"),
        (Path, "write_text"),
        (Path, "write_bytes"),
        (coaching_runtime, "load_profile"),
    ]:
        monkeypatch.setattr(target, name, forbidden)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name.split(".")[0] not in {"sounddevice", "rtmixer", "pyttsx3"}
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    report = replay(source, ref)
    assert report["available"] and report["coach_policy"]["assess_laps"] != 999
    assert (source, ref, isolated_ledger.read_bytes()) == (before_source, before_ref, before_ledger)


def _add_grip_fields(source, *, value, aliases=False):
    names = ["accG_lat"]
    if aliases:
        names += ["lat_g", "latg", "accG", "grip", "grip_used"]
    source["trace"]["fields"].extend(names)
    for row in source["trace"]["samples"]:
        row.extend([value] * len(names))


def _observe_grip_inputs(monkeypatch):
    inputs = []
    original = coaching_runtime.CoachRuntime.observe

    def observed(self, frame):
        inputs.append(
            {
                name: frame[name]
                for name in ("accG_lat", "lat_g", "latg", "accG", "grip", "grip_used")
                if name in frame
            }
        )
        return original(self, frame)

    monkeypatch.setattr(coaching_runtime.CoachRuntime, "observe", observed)
    return inputs


@pytest.mark.parametrize("value", [1e-12, 1e20])
@pytest.mark.parametrize("managed", [False, True])
def test_unqualified_lateral_grip_and_aliases_never_reach_coach(value, managed, monkeypatch):
    source = archive()
    _add_grip_fields(source, value=value, aliases=True)
    if managed:
        restrict(source)
    inputs = _observe_grip_inputs(monkeypatch)
    report = replay(source)
    assert report["available"]
    channel = report["optional_channels"]["lateral_grip"]
    assert channel["available"] is False
    assert channel["reason"] == "channel_semantics_unverified"
    assert inputs and all(frame == {} for frame in inputs)
    assert (
        "measured_lateral_grip_unavailable;coach_grip_gate_not_verified" in report["no_go_reasons"]
    )


@pytest.mark.parametrize(
    "unit,basis", [("m/s2", "measured"), ("G", "processed"), ("g", "measured")]
)
def test_unsupported_lateral_grip_semantics_remain_unavailable(unit, basis, monkeypatch):
    source = archive()
    _add_grip_fields(source, value=0.9)
    restrict(source)
    source["qualification"]["channels"]["accG_lat"] = {"unit": unit, "basis": basis}
    inputs = _observe_grip_inputs(monkeypatch)
    report = replay(source)
    assert report["available"]
    assert report["optional_channels"]["lateral_grip"]["available"] is False
    assert inputs and all(frame == {} for frame in inputs)


def test_bound_native_g_channel_is_passed_without_alias_override(monkeypatch):
    source = archive()
    _add_grip_fields(source, value=0.9, aliases=True)
    # These runtime aliases have no native archive contract and cannot override the measured G.
    alias_indices = [source["trace"]["fields"].index(name) for name in ("lat_g", "grip")]
    for row in source["trace"]["samples"]:
        for index in alias_indices:
            row[index] = 1e20
    restrict(source)
    source["qualification"]["channels"]["accG_lat"] = {"unit": "G", "basis": "measured"}
    before = copy.deepcopy(source)
    inputs = _observe_grip_inputs(monkeypatch)
    report = replay(source)
    assert report["available"]
    channel = report["optional_channels"]["lateral_grip"]
    assert channel["available"] is True and channel["expected_unit"] == "G"
    assert channel["reason"] == "qualified_measured_native_channel"
    assert inputs and all(frame == {"lat_g": 0.9} for frame in inputs)
    assert (
        "measured_lateral_grip_unavailable;coach_grip_gate_not_verified"
        not in report["no_go_reasons"]
    )
    assert source == before


def test_qualified_all_zero_lateral_channel_is_still_unavailable(monkeypatch):
    source = archive()
    _add_grip_fields(source, value=0.0)
    restrict(source)
    source["qualification"]["channels"]["accG_lat"] = {"unit": "G", "basis": "measured"}
    inputs = _observe_grip_inputs(monkeypatch)
    report = replay(source)
    assert report["optional_channels"]["lateral_grip"]["reason"] == "all_zero_channel_unavailable"
    assert inputs and all(frame == {} for frame in inputs)


def test_lateral_channel_uses_ledger_metadata_over_embedded_claim(
    tmp_path, isolated_ledger, monkeypatch
):
    source = archive()
    _add_grip_fields(source, value=0.9)
    raw_path = tmp_path / "raw-native.json"
    raw_path.write_text(json.dumps(source), encoding="utf-8")
    restrict(source)
    register_attribution(raw_path, source["qualification"], ledger_path=isolated_ledger)
    source["qualification"]["channels"]["accG_lat"] = {"unit": "G", "basis": "measured"}
    inputs = _observe_grip_inputs(monkeypatch)
    report = replay(source)
    assert report["available"]
    assert report["optional_channels"]["lateral_grip"]["available"] is False
    assert inputs and all(frame == {} for frame in inputs)


def test_scheduler_callback_reports_real_staleness_dedup_and_loser_decisions():
    clock, playback, events = FakeClock(), RecordingPlayback(), []
    scheduler = Scheduler(
        Resolver(build_manifest()), playback, VoiceConfig(), clock=clock, on_decision=events.append
    )
    cue = make_advisory(kind="late_brake", urgency="prepare", register="calm")
    scheduler.submit(cue)
    assert scheduler.process_pending() is not None
    playback.finish()
    scheduler.submit(cue)
    assert scheduler.process_pending() is None
    clock.advance(10)
    scheduler.submit(cue)
    clock.advance(2)
    assert scheduler.process_pending() is None
    scheduler.submit(make_advisory(kind="late_brake", urgency="act", register="urgent"))
    scheduler.submit(make_advisory(kind="apex_deficit", urgency="info", register="calm"))
    assert scheduler.process_pending() is not None
    assert {e.reason for e in events} >= {
        "resolved",
        "dispatched",
        "dedup",
        "stale",
        "arbitration_lost",
    }
    stale = next(e for e in events if e.reason == "stale")
    assert stale.now_s - stale.enqueued_at_s == 2


def test_scheduler_callback_failure_is_logged_without_mutating_arbitration(caplog):
    def broken(_event):
        raise RuntimeError("diagnostic failed")

    scheduler = Scheduler(
        Resolver(build_manifest()), RecordingPlayback(), VoiceConfig(), on_decision=broken
    )
    scheduler.submit(make_advisory())
    assert scheduler.process_pending() is not None
    assert "scheduling decision callback failed" in caplog.text
    assert scheduler.decision_error_count > 0


def test_incomplete_scheduler_diagnostics_cannot_pass_shadow_checks(monkeypatch):
    original = Scheduler.process_pending

    def inject_orphan(self, now=None):
        if self.decision_error_count == 0:
            self._decision("resolved", 0, 0, advisory=object())
        return original(self, now)

    monkeypatch.setattr(Scheduler, "process_pending", inject_orphan)
    report = replay()
    assert report["engineering_validation"] == "invalid_diagnostics"
    assert "scheduler_diagnostics_incomplete" in report["decision"]["reasons"]
    assert not report["lanes"]["observer"]["checks"]["scheduler_diagnostics_complete"]


@pytest.mark.parametrize("source", [None, "imported", "unknown", "moza_cache"])
def test_unrecognized_stimulus_source_cannot_bypass_native_report_boundary(source):
    stimulus = archive()
    stimulus["source"] = source
    report = replay(stimulus)
    assert not report["available"]
    assert report["reason"] == "stimulus:selected_native_source_required"


def test_conditions_mismatch_and_missing_assists_remain_no_go():
    stimulus, reference = archive(), archive("reference")
    stimulus["car"]["extendedPhysics"] = False
    reference["car"]["extendedPhysics"] = True
    stimulus["conditions"] = {"weatherType": 16, "ambientTempC": 26}
    reference["conditions"] = {"weatherType": 15, "ambientTempC": 26}
    report = replay(stimulus, reference)
    assert report["available"]
    by_field = {row["field"]: row["status"] for row in report["condition_comparison"]}
    assert by_field == {
        "car.extendedPhysics": "mismatch",
        "conditions.weatherType": "mismatch",
        "conditions.ambientTempC": "match",
        "assists": "unknown",
    }
    assert "reference_condition_mismatch:car.extendedPhysics" in report["decision"]["reasons"]
    assert "reference_condition_unknown:assists" in report["decision"]["reasons"]


def test_late_and_duplicate_injected_contract_cues_have_falsifiable_evidence():
    # Deliberately injected producer events test timing/report accounting, not actual-lap coaching.
    class Producer:
        def observe(self, frame):
            return [
                make_advisory(
                    corner=0,
                    urgency="prepare",
                    register="calm",
                    detail={"brake_point_spline": 0.2, "anticipatory": True},
                )
            ]

    refs = [CornerReference(0, 0.3, 0.1, 0.4, 80, best_brake_point_spline=0.2)]
    lane = _lane(
        Producer(),
        [{"eMs": 1000}, {"eMs": 1500}],
        [{"event_id": 0, "corner": 0, "spline": 0.2, "t_event_ms": 900}],
        refs,
        track_m=1000,
        manifest=build_manifest(),
        durations={},
        config=VoiceConfig(),
    )
    assert lane["cues"][0]["lead_to_measured_brake_ms"] == -100
    assert lane["cues"][1]["status"] == "dedup"
    assert lane["late_brake_onset_count"] == 1
    assert lane["checks"]["all_dispatched_brake_cues_before_measured_onset"] is False


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -1, True, "400"])
def test_invalid_duration_metadata_is_rejected(duration):
    with pytest.raises(ValueError, match="invalid_clip_duration_metadata"):
        replay(clip_durations_ms={"clip": duration})
