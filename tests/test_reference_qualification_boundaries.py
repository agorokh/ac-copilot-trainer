"""Synthetic archive-facing boundary checks for #815; no vendor or personal traces."""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy

import pytest

from tests.test_session_review import _corner_archive
from tools.ai_sidecar import protocol, server
from tools.ai_sidecar.coach_report import build_debrief, build_structured_debrief
from tools.ai_sidecar.coaching_runtime import build_coach_runtime
from tools.ai_sidecar.driver_profile import load_profile, sanitize_profile
from tools.ai_sidecar.protocol import _load_safe_archive_path, resolve_lap_archive
from tools.ai_sidecar.realtime_observer import build_observer_from_reference
from tools.ai_sidecar.track_map import (
    _reference_provenance_valid,
    _valid_trace,
    build_corner_comparison,
    build_track_map,
)
from tools.lap_qualification import USES, build_qualification, qualify_archive, register_attribution
from tools.session_review.report import SessionReviewError, build_session_report

COMBO = ("ks_porsche_911_gt3_r_2016", "magione", None)
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


@pytest.fixture(autouse=True)
def isolated_attribution_store(tmp_path, monkeypatch):
    ledger = tmp_path / "attributions.json"
    ledger.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    monkeypatch.delenv("AC_COPILOT_ALIEN_LINE", raising=False)
    monkeypatch.delenv("AC_COPILOT_DRIVER_PROFILE", raising=False)
    return ledger


def _archive(name="human", *, session="session", lap_n=1, degrade=0.0):
    record = _corner_archive(
        lap_uuid=name,
        session_uuid=session,
        lap_n=lap_n,
        exported_at="2026-10-13T00:00:00Z",
        degrade=degrade,
    )
    record["corners"][0].update(s0=0.25, s1=0.8, brakePointSpline=0.22)
    return record


def _managed(record, *, authority="human"):
    record["qualification"] = build_qualification(
        record,
        authority=authority,
        origin="synthetic_boundary_test",
        supported_uses={use: authority == "human" or use == "analysis" for use in USES},
        channels={name: {"unit": unit, "basis": "measured"} for name, unit in UNITS.items()},
        evidence=[
            {
                "kind": "verified_human_control" if authority == "human" else "observed_ai",
                "sha256": "a" * 64,
            }
        ],
    )
    return record


@pytest.mark.parametrize(
    "builder", [build_coach_runtime, build_observer_from_reference, build_track_map]
)
def test_managed_reference_needs_independent_combo(builder):
    record = _managed(_archive())
    diagnostic = {}
    assert builder(record, diagnostics=diagnostic) is None
    assert diagnostic["reason"] == "expected_combo_unavailable"
    assert builder(record, expected_combo=COMBO) is not None
    diagnostic = {}
    assert builder(record, expected_combo=(COMBO[0], "spa", None), diagnostics=diagnostic) is None
    assert diagnostic["reason"] == "combo_mismatch"


@pytest.mark.parametrize(
    "builder", [build_coach_runtime, build_observer_from_reference, build_track_map]
)
@pytest.mark.parametrize("authority", ["ai", "shared", "unknown"])
def test_control_authority_is_not_technique_reference(builder, authority):
    diagnostic = {}
    assert (
        builder(
            _managed(_archive(), authority=authority), expected_combo=COMBO, diagnostics=diagnostic
        )
        is None
    )
    assert diagnostic["reason"] == f"control_authority_not_human:{authority}"


@pytest.mark.parametrize(
    "builder", [build_coach_runtime, build_observer_from_reference, build_track_map]
)
@pytest.mark.parametrize("defect", ["units", "stale", "schema", "coverage", "nonfinite"])
def test_archive_defects_do_not_escape_through_factories(builder, defect):
    record = _archive()
    if defect == "schema":
        record["schema_version"] = 999
    if defect == "coverage":
        record["trace"]["samples"] = record["trace"]["samples"][10:]
    _managed(record)
    if defect == "units":
        record["qualification"]["channels"]["steer"]["unit"] = "unknown"
    if defect == "stale":
        record["lap"]["lap_ms"] += 10
    if defect == "nonfinite":
        record["trace"]["samples"][3][1] = float("nan")
    diagnostic = {}
    assert builder(record, expected_combo=COMBO, diagnostics=diagnostic) is None
    assert diagnostic["allowed"] is False
    assert diagnostic["reason"] not in ("eligible", "legacy_unknown")


def test_native_attribution_cannot_be_bypassed_with_raw_dictionary(tmp_path):
    raw = _archive("native-ai")
    raw["lap"]["is_pb"] = True
    path = tmp_path / "lap_native.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    assessment = _managed(deepcopy(raw), authority="ai")["qualification"]
    register_attribution(path, assessment)
    assert "qualification" not in raw
    for builder in (build_coach_runtime, build_observer_from_reference, build_track_map):
        assert builder(raw, expected_combo=COMBO) is None
    assert not _reference_provenance_valid(raw, expected_combo=COMBO)
    assert path.read_bytes() == before
    assert qualify_archive(raw, use="human_progression").authority == "ai"


def test_map_comparison_keeps_measured_checks_and_rejects_ai_reference():
    driver = _archive("driver", degrade=3)
    reference = _managed(_archive("reference", session="reference"))
    assert build_corner_comparison(driver, reference)["available"]
    ai = _managed(_archive("ai"), authority="ai")
    unavailable = build_corner_comparison(driver, ai)
    assert not unavailable["available"]
    assert "control_authority_not_human:ai" in unavailable["reason"]
    driver["lap"]["is_valid"] = False
    assert not build_corner_comparison(driver, reference)["available"]


def test_existing_multi_sample_finish_tail_is_shared_and_immutable():
    record = _archive()
    samples = record["trace"]["samples"]
    last = samples[-1]
    samples.extend(
        [
            [s, *last[1:2], last[2] + n * 20, *last[3:]]
            for n, s in enumerate((0.001, 0.002, 0.003), 1)
        ]
    )
    record["lap"]["lap_ms"] = int(samples[-1][2])
    _managed(record)
    before = deepcopy(record)
    assert qualify_archive(record, use="reference_comparison", expected_combo=COMBO).allowed
    assert len(_valid_trace(record)) == len(samples) - 3
    assert record == before


def test_direct_debrief_rejects_disqualified_reference_and_unknown_channels():
    driver = _archive("driver")
    ai = _managed(_archive("ai"), authority="ai")
    diagnostic = {}
    assert build_structured_debrief(driver, reference_archive=ai, diagnostics=diagnostic) is None
    assert "control_authority_not_human:ai" in diagnostic["reason"]
    with pytest.raises(ValueError, match="control_authority_not_human:ai"):
        build_debrief(driver, reference_archive=ai)
    ai["qualification"]["channels"]["steer"]["unit"] = "unknown"
    assert build_structured_debrief(ai, diagnostics=diagnostic) is None
    assert "unsupported_channel_unit:steer" in diagnostic["reason"]


def test_session_report_excludes_attributed_ai_from_pb_and_reference(tmp_path):
    human = _archive("human", degrade=5)
    ai = _archive("ai", lap_n=2, degrade=-3)
    ai["lap"]["is_pb"] = True
    human_path, ai_path = tmp_path / "lap_human.json", tmp_path / "lap_ai.json"
    human_path.write_text(json.dumps(human), encoding="utf-8")
    ai_path.write_text(json.dumps(ai), encoding="utf-8")
    digest = hashlib.sha256(ai_path.read_bytes()).hexdigest()
    register_attribution(ai_path, _managed(deepcopy(ai), authority="ai")["qualification"])
    report = build_session_report([human_path, ai_path], session="session")
    assert ai["lap"]["lap_ms"] < human["lap"]["lap_ms"]
    assert report["session"]["best_lap_uuid"] == "human"
    assert report["reference"]["lap_uuid"] == "human"
    assert {lap["lap_uuid"] for lap in report["comparison"]["laps"]} == {"human"}
    ai_row = next(lap for lap in report["history"]["laps"] if lap["lap_uuid"] == "ai")
    assert ai_row["reference_kind"] == "ai-control"
    assert ai_row["human_progression_allowed"] is False
    assert hashlib.sha256(ai_path.read_bytes()).hexdigest() == digest
    with pytest.raises(SessionReviewError, match="control_authority_not_human:ai"):
        build_session_report([human_path, ai_path], session="session", reference_path=ai_path)


def test_rewire_rejected_managed_reference_clears_previous_runtime(tmp_path, monkeypatch):
    for name in ("_observer", "_coach_runtime", "_map_reference_archive", "_track_map_frame"):
        monkeypatch.setattr(server, name, None)
    monkeypatch.setenv("AC_COPILOT_COACH_V2", "1")
    monkeypatch.setattr(server, "_voice_runtime_status", {})
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(_archive()), encoding="utf-8")
    config = server.VoiceRuntimeConfig(reference_path=str(path), bank_dir=None)
    server._wire_voice(config)
    assert server._observer is not None
    assert server._coach_runtime is not None
    assert server._track_map_frame is not None
    path.write_text(json.dumps(_managed(_archive("ai"), authority="ai")), encoding="utf-8")
    server._wire_voice(config)
    assert server._observer is None
    assert server._coach_runtime is None
    assert server._map_reference_archive is None
    assert server._track_map_frame is None
    assert "control_authority_not_human:ai" in server.voice_runtime_status()["disabled_reason"]


def test_ai_lap_cannot_calibrate_human_brake_marks(monkeypatch):
    class Observer:
        calls = 0

        def calibrate_from_driver_lap(self, *args, **kwargs):
            self.calls += 1
            return 1

    observer = Observer()
    monkeypatch.setattr(server, "_observer", observer)
    monkeypatch.setattr(server, "_coach_runtime", None)
    monkeypatch.setattr(server, "_recent_brake_cal_keys", [])
    ai = _managed(_archive("ai"), authority="ai")
    monkeypatch.setattr(server, "resolve_lap_archive", lambda inbound: ai)
    asyncio.run(
        server._calibrate_brake_marks_from_lap(
            {"lap": 1, "lapTimeMs": ai["lap"]["lap_ms"], "trace": ai["trace"]}
        )
    )
    assert observer.calls == 0


@pytest.mark.parametrize("value", [None, [], "invalid", 1])
def test_malformed_archive_factories_are_unavailable(value):
    for builder in (build_coach_runtime, build_observer_from_reference, build_track_map):
        assert builder(value) is None


def test_partial_tt_guard_still_applies_to_coach_and_observer():
    partial = _archive()
    partial["generator"] = {"tt_reference": {"partial": True}}
    assert build_coach_runtime(partial) is None
    assert build_observer_from_reference(partial) is None


def test_managed_duplicate_corpus_identity_rejects_every_copy(tmp_path):
    record = _managed(_archive())
    paths = [tmp_path / "lap_first.json", tmp_path / "lap_second.json"]
    for path in paths:
        path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(SessionReviewError, match="duplicate_archive_identity"):
        build_session_report(paths, session="session")


def test_protocol_safe_loader_enforces_original_byte_binding(tmp_path):
    root = tmp_path / "journal" / "laps"
    root.mkdir(parents=True)
    path = root / "lap_native.json"
    record = _archive("native-ai")
    path.write_text(json.dumps(record), encoding="utf-8")
    register_attribution(path, _managed(deepcopy(record), authority="ai")["qualification"])
    loaded = _load_safe_archive_path(str(path))
    assert loaded["qualification"]["authority"] == "ai"
    assert not qualify_archive(loaded, use="human_progression").allowed
    # Canonical values still match; a path reader must nevertheless detect changed bytes.
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    changed = _load_safe_archive_path(str(path))
    assert changed["qualification"]["resolution_error"] == "attribution_source_hash_mismatch"
    assert qualify_archive(changed, use="analysis").reason == "attribution_source_hash_mismatch"
    assert _load_safe_archive_path(str(root / ".." / ".." / "lap_native.json")) is None


def test_ai_lap_never_folds_rolling_best_or_emits_between_lap_advice(monkeypatch):
    from tools.ai_sidecar.coaching import between_lap

    class Coach:
        calls = 0

        def note_completed_lap(self, *args, **kwargs):
            self.calls += 1

    coach = Coach()
    ai = _managed(_archive("ai"), authority="ai")
    monkeypatch.setattr(server, "_coach_runtime", coach)
    monkeypatch.setattr(server, "resolve_lap_archive", lambda inbound: ai)
    monkeypatch.setattr(server, "_recent_between_lap_fold_keys", [])
    monkeypatch.setattr(server, "_recent_between_lap_advice_keys", [])

    def unexpected_advice(**kwargs):
        pytest.fail("AI completed lap reached human between-lap advice")

    monkeypatch.setattr(between_lap, "select_between_lap_advice", unexpected_advice)
    asyncio.run(
        server._coach_v2_between_lap(
            None,
            {"lap": 1, "lapTimeMs": ai["lap"]["lap_ms"], "trace": ai["trace"]},
            reply_coaching=True,
        )
    )
    assert coach.calls == 0
    assert not server._recent_between_lap_fold_keys
    assert not server._recent_between_lap_advice_keys


def _advanced_profile(lap_uuid):
    combo = {"car_id": COMBO[0], "track_id": COMBO[1], "track_layout": ""}
    return {
        "schema_version": 1,
        "preferences": {"verbosity": "low"},
        "focus_corners": {"T1": "manual focus"},
        "corner_history": {
            "corner": {
                **combo,
                "lap_uuids": [lap_uuid],
                "valid_laps": 8,
                "delta_min_speed_kmh": 3.0,
                "avg_trail_brake_ratio": 0.4,
                "avg_throttle": 0.7,
                "avg_steer_reversals": 1.0,
            }
        },
        "consistency": {
            "combo": {
                **combo,
                "session_count": 3,
                "valid_laps": 12,
                "median_session_best_ms": 100000,
                "consistency_ms": 1000.0,
            }
        },
    }


def test_direct_profile_uses_same_contamination_gate_as_file_load(tmp_path):
    ai = _archive("known-ai", session="assisted", lap_n=2)
    archive_path = tmp_path / "lap_ai.json"
    archive_path.write_text(json.dumps(ai), encoding="utf-8")
    register_attribution(archive_path, _managed(deepcopy(ai), authority="ai")["qualification"])
    profile = _advanced_profile("known-ai")
    before = deepcopy(profile)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    profile_bytes = path.read_bytes()
    reference = _archive("reference", session="clean")
    diagnostics = {}
    runtime = build_coach_runtime(reference, driver_profile=profile, diagnostics=diagnostics)
    assert runtime.cue_policy.level == "unknown"
    assert runtime.ledger.lap_budget == 4
    assert diagnostics["driver_profile"]["rebuild_required"] is True
    assert "attributed_lap_or_session_overlap" in diagnostics["driver_profile"]["reasons"][0]
    direct, loaded = sanitize_profile(profile), load_profile(path)
    for parked in (direct, loaded):
        assert parked["source"]["rebuild_required"] is True
        assert parked["corner_history"] == {}
        assert parked["consistency"] == {}
        assert parked["preferences"] == profile["preferences"]
        assert parked["focus_corners"] == profile["focus_corners"]
    assert profile == before
    assert path.read_bytes() == profile_bytes


def test_clean_direct_profile_retains_policy_and_manual_fields():
    profile = _advanced_profile("clean-lap")
    before = deepcopy(profile)
    clean = sanitize_profile(profile)
    runtime = build_coach_runtime(_archive("reference"), driver_profile=profile)
    assert clean == before
    assert profile == before
    assert runtime.cue_policy.level == "advanced"
    assert runtime.ledger.lap_budget == 5


@pytest.mark.parametrize("selected", ["ai", "missing", "invalid", "unsafe", 0, False])
def test_selected_archive_path_cannot_fall_back_to_inline_trace(tmp_path, monkeypatch, selected):
    from tools.ai_sidecar.coaching import between_lap

    root = tmp_path / "journal" / "laps"
    root.mkdir(parents=True)
    path = root / "lap_selected.json"
    ai = _archive("selected-ai")
    if selected == "ai":
        path.write_text(json.dumps(ai), encoding="utf-8")
        register_attribution(path, _managed(deepcopy(ai), authority="ai")["qualification"])
    elif selected == "invalid":
        path.write_text("invalid JSON", encoding="utf-8")
    elif selected == "unsafe":
        path = tmp_path / "outside.json"
        path.write_text(json.dumps(_archive()), encoding="utf-8")
    frame = {
        "lap": 1,
        "lapTimeMs": ai["lap"]["lap_ms"],
        "archivePath": str(path),
        "trace": ai["trace"],
        "isValid": True,
    }
    if not isinstance(selected, str):
        frame["archivePath"] = selected
        # Even without inline data a typed-invalid selected path is not a bare live frame.
        frame.pop("trace")
    resolved = resolve_lap_archive(frame)
    if selected == "ai":
        assert resolved["qualification"]["authority"] == "ai"
        assert not qualify_archive(resolved, use="live_reference", expected_combo=COMBO).allowed
        assert build_coach_runtime(resolved, expected_combo=COMBO) is None
    else:
        assert resolved is None
    monkeypatch.setattr(protocol, "debrief_feature_enabled", lambda: True)
    assert protocol.build_brain_followup(frame) is None

    class Coach:
        folds = 0
        calibrations = 0

        def note_completed_lap(self, *args, **kwargs):
            self.folds += 1

        def calibrate_from_driver_lap(self, *args, **kwargs):
            self.calibrations += 1
            return 1

    coach = Coach()
    monkeypatch.setattr(server, "_coach_runtime", coach)
    monkeypatch.setattr(server, "_recent_between_lap_fold_keys", [])
    monkeypatch.setattr(server, "_recent_between_lap_advice_keys", [])
    monkeypatch.setattr(server, "_recent_brake_cal_keys", [])

    def unexpected_advice(**kwargs):
        pytest.fail("selected restricted/unavailable archive reached human advice")

    monkeypatch.setattr(between_lap, "select_between_lap_advice", unexpected_advice)
    asyncio.run(server._coach_v2_between_lap(None, frame, reply_coaching=True))
    asyncio.run(server._calibrate_brake_marks_from_lap(frame))
    assert coach.folds == 0
    assert coach.calibrations == 0
    assert not server._recent_between_lap_fold_keys
    assert not server._recent_between_lap_advice_keys


@pytest.mark.parametrize("path", [None, "", "  "])
def test_bare_inline_trace_retains_legacy_resolution_and_fold(monkeypatch, path):
    frame = {"lap": 1, "lapTimeMs": 100000, "trace": _archive()["trace"]}
    frame["archivePath"] = path
    assert resolve_lap_archive(frame) is frame
    assert qualify_archive(frame, use="human_progression").reason == "legacy_unknown"
    monkeypatch.setattr(protocol, "debrief_feature_enabled", lambda: True)
    assert protocol.build_brain_followup(frame) is not None

    class Coach:
        folds = []

        def note_completed_lap(self, lap_ms, *, is_valid):
            self.folds.append((lap_ms, is_valid))

    coach = Coach()
    monkeypatch.setattr(server, "_coach_runtime", coach)
    monkeypatch.setattr(server, "_recent_between_lap_fold_keys", [])
    asyncio.run(server._coach_v2_between_lap(None, frame, reply_coaching=False))
    assert coach.folds == [(100000, True)]


def test_legacy_reference_matching_keeps_fallback_without_certifying_managed_context(tmp_path):
    driver = _archive("driver", session="selected", degrade=5)
    driver["track"].update(identity_source="csp_content_ids", layout_available=False)
    reference = _archive("legacy-ref", session="prior")
    driver_path, reference_path = tmp_path / "lap_driver.json", tmp_path / "lap_reference.json"
    driver_path.write_text(json.dumps(driver), encoding="utf-8")
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    report = build_session_report([driver_path, reference_path], session="selected")
    assert report["reference"]["lap_uuid"] == "legacy-ref"
    _managed(reference)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    with pytest.raises(SessionReviewError, match="expected_combo_unavailable"):
        build_session_report(
            [driver_path, reference_path], session="selected", reference_path=reference_path
        )
