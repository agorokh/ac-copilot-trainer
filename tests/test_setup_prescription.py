"""Synthetic safety checks; these do NOT satisfy the real twelve-case experiment."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.ai_sidecar.setup_optimizer import load_records, rebuild_experiments, upsert_records
from tools.ai_sidecar.setup_prescription import WHEELS, PrescriptionJournal, build_prescription
from tools.lap_qualification import USES, build_qualification

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
def isolated_ledger(tmp_path, monkeypatch):
    path = tmp_path / "attributions.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(path))


def bind(record):
    record.pop("qualification", None)
    record["qualification"] = build_qualification(
        record,
        authority="human",
        origin="synthetic_test",
        supported_uses={use: True for use in USES},
        channels={key: {"unit": unit, "basis": "measured"} for key, unit in UNITS.items()},
        evidence=[{"kind": "verified_human_control", "sha256": "a" * 64}],
    )
    return record


def inputs(hot=28.0):
    identity = {
        "car_id": "test_car",
        "track_id": "test_track",
        "layout_id": "",
        "session_id": "test_session",
        "compound_index": 1,
        "setup_path": "C:/setups/test.ini",
    }
    targets = {w: {"pressure_ideal_psi": 26.0, "optimal_temp_c": 80.0} for w in WHEELS}
    spinners = [
        {
            "section": section,
            "value": 20.0,
            "min": 10.0,
            "max": 40.0,
            "step": 1.0,
            "unit": "psi",
            "range_known": True,
            "read_only": False,
        }
        for section in WHEELS.values()
    ]
    fields = list(UNITS)
    for prefix in ("wheelsPressure", "tyreCoreTemp", "wheelSlip", "wheelAngularSpeed"):
        fields += [f"{prefix}_{w}" for w in WHEELS]
    samples = []
    for i in range(101):
        row = [i / 100, 100.0, i * 600, 0.5, 0.0, 0.0, 3, i, 0, i]
        row += [hot] * 4 + [80.0] * 4 + [0.1] * 4 + [90.0] * 4
        samples.append(row)
    laps = []
    for number in (2, 3):
        laps.append(
            bind(
                {
                    "schema_version": 1,
                    "source": "in_game",
                    "session_uuid": "test_session",
                    "lap_uuid": f"test_lap_{number}",
                    "car": {"id": "test_car"},
                    "track": {"id": "test_track", "layout": None},
                    "lap": {"lap_n": number, "lap_ms": 60_000, "is_valid": True},
                    "tyres": {"compoundIndex": 1, "optimalTempC": 80.0},
                    "setup": {
                        "hash": "test_setup_hash",
                        "path": identity["setup_path"],
                        "snapshot": {section + ".VALUE": "20" for section in WHEELS.values()},
                    },
                    "trace": {"fields": fields, "samples": copy.deepcopy(samples)},
                }
            )
        )
    return laps, spinners, identity, targets


def card_for(data):
    laps, spinners, identity, targets = data
    return build_prescription(laps, spinners, identity=identity, targets=targets)


@pytest.mark.parametrize("hot,sign", [(28.0, -1), (24.0, 1)])
def test_measured_stable_deviation_direction_and_supported_step(hot, sign):
    data = inputs(hot)
    card = card_for(data)
    assert card["status"] == "proposed", card
    assert len(card["changes"]) == 4
    assert card["lap_window"] == [2, 3]
    for change in card["changes"]:
        assert change["delta_psi"] == sign
        assert change["to"] == 20 + sign
    assert "measured" in card["evidence"] and "psi" in card["evidence"]
    assert card_for(data)["prescription_id"] == card["prescription_id"]


@pytest.mark.parametrize(
    "case",
    [
        "short",
        "outlap",
        "lockup",
        "cold",
        "warmup",
        "spike",
        "target",
        "range",
        "unit",
        "nan",
        "changed_setup",
        "session",
        "thermal_target",
        "legacy",
        "partial",
        "opposite_last_lap",
    ],
)
def test_abstains_on_traps_and_uncertain_provenance(case):
    data = inputs()
    laps, spinners, identity, targets = data
    fields = laps[-1]["trace"]["fields"]
    samples = laps[-1]["trace"]["samples"]
    if case == "short":
        laps.pop(0)
    elif case == "outlap":
        laps[0]["lap"]["lap_n"] = 1
    elif case == "lockup":
        samples[50][fields.index("wheelAngularSpeed_fl")] = 0
    elif case == "cold":
        for row in samples:
            row[fields.index("tyreCoreTemp_fl")] = 40.0
    elif case == "warmup":
        for i, row in enumerate(samples):
            row[fields.index("tyreCoreTemp_fl")] = 75.0 + i / 10
    elif case == "spike":
        samples[50][fields.index("wheelsPressure_fl")] = 40
    elif case == "target":
        targets.clear()
    elif case == "range":
        spinners[0]["range_known"] = False
    elif case == "unit":
        spinners[0]["unit"] = "kPa"
    elif case == "nan":
        samples[50][fields.index("wheelsPressure_fl")] = float("nan")
    elif case == "changed_setup":
        spinners[0]["value"] = 21
    elif case == "session":
        identity["session_id"] = "other_session"
    elif case == "thermal_target":
        targets["fl"]["optimal_temp_c"] = 70
    elif case == "partial":
        laps[-1]["trace"]["samples"] = samples[:70]
    elif case == "opposite_last_lap":
        for row in samples:
            row[fields.index("wheelsPressure_fl")] = 24
    for lap in laps:
        if case == "legacy":
            lap.pop("qualification", None)
        elif case != "nan":
            bind(lap)
    card = card_for(data)
    assert card["status"] == "abstained", card
    assert card["changes"] == [] and card["reason"]


def test_range_cap_cannot_create_micro_nudge_or_reverse_delta():
    data = inputs()
    for row in data[1]:
        row["min"] = row["value"]
    assert card_for(data)["status"] == "abstained"


def test_journal_deduplicates_restart_and_verifies_every_cold_readback(tmp_path):
    path = tmp_path / "experiments.jsonl"
    journal = PrescriptionJournal(path)
    card = journal.remember(card_for(inputs()))
    key = card["prescription_id"]
    accepted = journal.decide(key, "accept")
    assert accepted["new_decision"] and accepted["status"] == "accepted_unverified"
    restarted = PrescriptionJournal(path)
    assert not restarted.decide(key, "accept")["new_decision"]
    assert restarted.decide(key, "reject")["decision"] == "accept"
    assert restarted.verify(key, {"PRESSURE_LF": 19})["status"] == "accepted_unverified"
    readback = {change["section"]: change["to"] for change in card["changes"]}
    readback["PRESSURE_RR"] = 20
    assert restarted.verify(key, readback)["status"] == "accepted_unverified"
    readback["PRESSURE_RR"] = 19
    assert restarted.verify(key, readback)["status"] == "verified_applied"
    assert len(load_records(path)) == 1


@pytest.mark.parametrize("decision,status", [("reject", "rejected"), ("accept", "expired")])
def test_reject_expiry_never_authorizes_mutation(tmp_path, decision, status):
    card = card_for(inputs())
    if status == "expired":
        card["created_at"] -= 121
    journal = PrescriptionJournal(tmp_path / "experiments.jsonl")
    journal.remember(card)
    result = journal.decide(card["prescription_id"], decision)
    assert result["status"] == status
    assert journal.remember(card)["status"] == status
    assert journal.verify(card["prescription_id"], {"PRESSURE_LF": 19})["status"] == status


def test_concurrent_bounces_only_one_claim_and_optimizer_rebuild_preserves_decision(tmp_path):
    path = tmp_path / "experiments.jsonl"
    journal = PrescriptionJournal(path)
    card = journal.remember(card_for(inputs()))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: journal.decide(card["prescription_id"], "accept"), range(20))
        )
    assert sum(row["new_decision"] for row in results) == 1
    lap_record = {"experiment_id": "a_lap", "car": {"id": "test_car"}}
    upsert_records([lap_record], path)
    assert len(load_records(path)) == 2
    lap_dir = tmp_path / "laps"
    lap_dir.mkdir()
    rebuild_experiments(lap_dir, store_path=path)
    assert len(load_records(path)) == 1
    assert journal.get(card["prescription_id"])["decision"] == "accept"
    assert len([json.loads(line) for line in path.read_text().splitlines()]) == 1
