"""Exercise the offline progression gate with fabricated sessions and conditions."""

from __future__ import annotations

import json
from datetime import date

import pytest
from test_lap_qualification import archive, assessment
from test_traffic_eligibility import _capture

from tools.coaching_lake.progression_audit import audit_archives, main
from tools.session_review.report import build_session_report

COMBO = ("synthetic-car", "synthetic-track", None)
SPLIT = date(2026, 11, 15)


def _record(uid, *, day=14, lap_n=2, lap_ms=60_000, track_temp=30.0, authority="human", **changes):
    row = archive()
    row.update(
        session_uuid=uid,
        lap_uuid=f"{uid}-{lap_n}",
        exported_at=f"2026-11-{day:02d}T12:00:00Z",
        setup={"hash": "fixture-setup"},
        tyres={"name": "Soft"},
        conditions={
            "trackTempC": track_temp,
            "ambientTempC": 20,
            "assists": {
                "abs": 1,
                "traction_control": 1,
                "stability_control": 0,
                "auto_clutch": False,
            },
        },
        traffic=_capture(),
    )
    row["lap"].update(lap_n=lap_n, lap_ms=lap_ms)
    row["trace"]["fields"] += [
        "fuel",
        "tyreCoreTemp_fl",
        "tyreCoreTemp_fr",
        "tyreCoreTemp_rl",
        "tyreCoreTemp_rr",
    ]
    for index, sample in enumerate(row["trace"]["samples"]):
        sample[2] = index * lap_ms / 100
        sample.extend([32.2, 80, 80, 80, 80])
    row.update(changes)
    row["qualification"] = assessment(row, authority=authority, promoted=True)
    return row


def _write(root, row, *, suffix=""):
    path = root / f"lap_{row['lap_uuid']}{suffix}.json"
    path.write_text(json.dumps(row), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    path = tmp_path / "lap-attributions.json"
    path.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(path))


def test_supported_comparison_calibrates_and_estimates_from_real_entrypoints(tmp_path, capsys):
    for day, adjustment in ((14, 0), (15, -200)):
        for index in range(4):
            _write(tmp_path, _record(f"{day}-{index}", day=day, lap_ms=60_000 + index + adjustment))
    assert (
        main(
            [
                "--lap-dir",
                str(tmp_path),
                "--car",
                COMBO[0],
                "--track",
                COMBO[1],
                "--split",
                SPLIT.isoformat(),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "estimated", report["calibration"]
    assert report["improvement_ms"] == 200
    assert report["session_bootstrap_interval_95_ms"][0] > 195
    assert report["improvement_detected"]
    assert report["calibration"]["trials_per_scenario"] == 1000
    assert report["calibration"]["detection_power_by_shift_ms"]["300"] >= 0.8
    assert len(report["included_sessions"]) == 8

    session = build_session_report(
        iter([tmp_path]), reference_source="none", progression_split=SPLIT
    )
    assert session["progression"] == report


def test_laps_are_never_counted_as_independent_sessions(tmp_path):
    for day, count in ((14, 3), (15, 2)):
        for index in range(count):
            for lap_n in range(2, 6):
                _write(tmp_path, _record(f"{day}-{index}", day=day, lap_n=lap_n))
    report = audit_archives([tmp_path], combo=COMBO, split=SPLIT)
    assert report["status"] == "cannot_identify"
    assert report["calibration"]["status"] == "inconclusive"
    assert report["included_sessions"] == []
    assert report["strata"][0]["excluded_reasons"] == ["later_has_2_sessions_minimum_3"]
    assert len(report["excluded_sessions"]) == 5


def test_missing_different_and_unqualified_conditions_are_reported(tmp_path):
    _write(tmp_path, _record("missing-assists", conditions={"trackTempC": 30, "ambientTempC": 20}))
    _write(tmp_path, _record("invalid-temp", conditions={"trackTempC": "NaN"}))
    _write(tmp_path, _record("different", track_temp=40))
    _write(tmp_path, _record("baseline"))
    _write(tmp_path, _record("shared", authority="shared"))
    _write(tmp_path, _record("occupied", traffic=_capture(constrained=True)))
    no_traffic = _record("unknown-traffic")
    del no_traffic["traffic"]
    no_traffic["qualification"] = assessment(no_traffic, authority="human", promoted=True)
    _write(tmp_path, no_traffic)
    duplicated = _record("duplicate")
    _write(tmp_path, duplicated)
    _write(tmp_path, duplicated, suffix="-copy")
    _write(tmp_path, _record("crosses-cutoff"))
    _write(tmp_path, _record("crosses-cutoff", day=15, lap_n=3))
    (tmp_path / "lap_unreadable.json").write_text("invalid", encoding="utf-8")

    report = audit_archives([tmp_path], combo=COMBO, split=SPLIT)
    assert report["status"] == "cannot_identify"
    assert "improvement_ms" not in report
    assert len(report["strata"]) == 2
    assert report["unreadable_archives"] == ["lap_unreadable.json"]
    assert report["missing_by_dimension"]["assists"] == 2
    assert report["missing_by_dimension"]["thermal_band"] == 1
    assert report["missing_by_dimension"]["traffic_eligibility"] == 1
    assert report["excluded_sessions"]["duplicate"] == ["duplicate_archive_identity"]
    assert report["excluded_sessions"]["crosses-cutoff"] == [
        "session_spans_cutoff_or_has_missing_timestamp"
    ]
    assert report["excluded_sessions"]["occupied"] == ["traffic_occupied_approach"]
    assert report["excluded_sessions"]["shared"] == ["control_authority_not_human:shared"]


def test_supported_stratum_abstains_when_nuisance_can_mimic_improvement(tmp_path):
    for day, track_temp in ((14, 34.9), (15, 30)):
        for index in range(4):
            _write(tmp_path, _record(f"{day}-{index}", day=day, track_temp=track_temp))
    report = audit_archives([tmp_path], combo=COMBO, split=SPLIT)
    assert report["status"] == "cannot_identify"
    assert report["reason"] == "calibration_failed"
    assert report["calibration"]["nuisance_false_improvement_rate"] > 0.05
    assert "improvement_ms" not in report
