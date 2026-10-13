"""Synthetic archive-facing boundary checks for #815; no vendor or personal traces."""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy

import pytest

from tests.test_session_review import _corner_archive
from tools.ai_sidecar import server
from tools.ai_sidecar.coach_report import build_debrief, build_structured_debrief
from tools.ai_sidecar.coaching_runtime import build_coach_runtime
from tools.ai_sidecar.protocol import _load_safe_archive_path
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
