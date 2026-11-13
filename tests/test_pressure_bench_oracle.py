"""Independent fixed numeric vectors; these are not real trial observations."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools import pressure_bench_oracle as oracle
from tools.lap_qualification import USES, build_qualification

BASE_UNITS = {
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
def isolated_provenance(tmp_path, monkeypatch):
    ledger = tmp_path / "attributions.json"
    ledger.write_text(json.dumps({"schema_version": 1, "entries": []}), encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))


def bind(record, authority="ai"):
    record.pop("qualification", None)
    record["qualification"] = build_qualification(
        record,
        authority=authority,
        origin="synthetic_oracle_vector",
        supported_uses={use: use == "analysis" for use in USES},
        channels={key: {"unit": unit, "basis": "measured"} for key, unit in BASE_UNITS.items()},
        evidence=[{"kind": "observed_ai_intervention", "sha256": "a" * 64}],
    )


def inputs(tmp_path, *, hot=27.2, core=80, numbers=(2, 3)):
    identity = {
        "car_id": "synthetic_car",
        "track_id": "synthetic_track",
        "layout_id": "",
        "session_id": "synthetic_session",
        "compound_index": 1,
        "setup_path": "C:/synthetic/test.ini",
    }
    targets = {
        wheel: {"pressure_ideal_psi": 26.0, "optimal_temp_c": 80.0} for wheel in oracle.WHEELS
    }
    targets["_provenance"] = {"tyres_ini_sha256": "b" * 64, "curve_sha256": {"test.lut": "c" * 64}}
    spinners = [
        {
            "section": section,
            "value": 20.0,
            "min": 10.0,
            "max": 40.0,
            "step": 1.0,
            "unit": "psi",
            "range_known": True,
        }
        for section in oracle.WHEELS.values()
    ]
    fields = list(BASE_UNITS)
    for prefix in ("wheelsPressure", "tyreCoreTemp", "wheelSlip", "wheelAngularSpeed"):
        fields.extend(f"{prefix}_{wheel}" for wheel in oracle.WHEELS)
    rows = [
        [i / 100, 100.0, i * 600.0, 0.4, 0.0, 0.0, 3, i, 0, i]
        + [hot] * 4
        + [core] * 4
        + [0.05] * 4
        + [90.0] * 4
        for i in range(101)
    ]
    archives = []
    for number in numbers:
        archives.append(
            {
                "schema_version": 1,
                "exported_at": datetime.now(UTC).isoformat(),
                "source": "in_game",
                "session_uuid": identity["session_id"],
                "lap_uuid": f"test-{number}",
                "car": {"id": identity["car_id"]},
                "track": {"id": identity["track_id"], "layout": None},
                "lap": {"lap_n": number, "lap_ms": 60_000, "is_valid": True},
                "tyres": {"compoundIndex": 1, "optimalTempC": 80.0},
                "setup": {
                    "hash": "fixed-test-setup",
                    "path": identity["setup_path"],
                    "snapshot": {section + ".VALUE": "20" for section in oracle.WHEELS.values()},
                },
                "trace": {"fields": fields, "samples": copy.deepcopy(rows)},
            }
        )
    result = (archives, spinners, identity, targets)
    return persist(tmp_path, result)


def persist(tmp_path, data):
    archives, spinners, identity, targets = data[:4]
    paths = []
    for record in archives:
        bind(record)
        path = tmp_path / f"lap_{record['lap']['lap_n']}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        paths.append(path)
    return archives, spinners, identity, targets, paths


def inspect(data, slot):
    archives, spinners, identity, targets, paths = data
    return oracle.inspect_case(archives, spinners, identity, targets, slot=slot, source_paths=paths)


@pytest.mark.parametrize(
    "hot,slot,label,direction",
    [
        (27.2, "G1", "genuine_high", -1),
        (24.8, "G4", "genuine_low", 1),
    ],
)
def test_independent_direction_and_native_one_psi_step(tmp_path, hot, slot, label, direction):
    data = inputs(tmp_path, hot=hot)
    result = inspect(data, slot)
    assert result["enrollable"], result
    assert result["label"] == label and not result["expected_abstention"]
    assert set(result["directions"].values()) == {direction}
    assert result["measurements"][0]["wheels"]["fl"]["hot_psi"] == hot
    for step in result["native_steps"].values():
        assert step["step_psi"] == 1 and step["min_clicks"] == step["max_clicks"] == 1
    assert all(
        item["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        for item, path in zip(result["sources"], data[-1], strict=True)
    )


@pytest.mark.parametrize(
    "slot,core,numbers,label",
    [
        ("T1", 40.0, (1,), "cold"),
        ("T3", 80.0, (2,), "short"),
    ],
)
def test_real_condition_labels_do_not_depend_on_candidate(tmp_path, slot, core, numbers, label):
    result = inspect(inputs(tmp_path, core=core, numbers=numbers), slot)
    assert result["enrollable"] and result["label"] == label
    assert result["expected_abstention"] and not result["native_steps"]


def test_moving_lock_scrub_sensor_event_is_required(tmp_path):
    data = inputs(tmp_path)
    assert not inspect(data, "T5")["enrollable"]
    record = data[0][-1]
    column = record["trace"]["fields"].index("wheelAngularSpeed_fl")
    record["trace"]["samples"][50][column] = 0
    result = inspect(persist(tmp_path, data), "T5")
    assert result["enrollable"] and result["label"] == "lock_scrub"
    assert result["measurements"][-1]["wheels"]["fl"]["moving_lock_events"] == 1
    assert not inspect(persist(tmp_path, data), "G1")["enrollable"]


def test_incomplete_cold_outlap_is_diagnostic_only_when_analysis_denies(tmp_path):
    data = inputs(tmp_path, core=40, numbers=(1,))
    data[0][0]["trace"]["samples"] = data[0][0]["trace"]["samples"][:51]
    result = inspect(persist(tmp_path, data), "T1")
    assert not result["enrollable"] and result["label"] == "cold"
    assert result["expected_abstention"]
    assert any(reason.startswith("canonical_analysis_denied:") for reason in result["reasons"])
    assert result["analysis_qualifications"][0]["allowed"] is False


@pytest.mark.parametrize(
    "case",
    [
        "pressure_span",
        "thermal_span",
        "quarter_trend",
        "between_pressure",
        "between_core",
        "no_target_provenance",
        "unknown_range",
        "missing_snapshot",
        "identity",
        "bad_step",
        "mixed_directions",
        "nonfinite",
        "wrong_intended_direction",
    ],
)
def test_input_only_exclusions(tmp_path, case):
    data = inputs(tmp_path)
    archives, spinners, identity, targets, _ = data
    fields = archives[-1]["trace"]["fields"]
    rows = archives[-1]["trace"]["samples"]
    if case == "pressure_span":
        rows[50][fields.index("wheelsPressure_fl")] += 1.1
    elif case == "thermal_span":
        rows[50][fields.index("tyreCoreTemp_fl")] += 11
    elif case == "quarter_trend":
        for i, row in enumerate(rows):
            row[fields.index("tyreCoreTemp_fl")] = 78 + i * 0.04
    elif case == "between_pressure":
        for row in rows:
            row[fields.index("wheelsPressure_fl")] += 0.4
    elif case == "between_core":
        for row in rows:
            row[fields.index("tyreCoreTemp_fl")] += 3
    elif case == "no_target_provenance":
        targets.pop("_provenance")
    elif case == "unknown_range":
        spinners[0]["range_known"] = False
    elif case == "missing_snapshot":
        archives[0]["setup"]["snapshot"].pop("PRESSURE_LF.VALUE")
    elif case == "identity":
        identity["session_id"] = "another-session"
    elif case == "bad_step":
        for spinner in spinners:
            spinner["step"] = 2
    elif case == "mixed_directions":
        for archive in archives:
            for row in archive["trace"]["samples"]:
                row[fields.index("wheelsPressure_fl")] = 24.8
    elif case == "nonfinite":
        targets["fl"]["pressure_ideal_psi"] = float("nan")
    slot = "G4" if case == "wrong_intended_direction" else "G1"
    result = inspect(persist(tmp_path, data), slot)
    assert not result["enrollable"] and result["reasons"], result


def test_raw_bytes_and_native_ai_authority_are_not_optional(tmp_path):
    data = inputs(tmp_path)
    assert not oracle.inspect_case(*data[:4], slot="G1")["enrollable"]
    data[0][0]["trace"]["samples"][10][10] = 20
    assert "archive_dictionary_differs_from_raw_file" in inspect(data, "G1")["reasons"]
    data = inputs(tmp_path)
    for archive, path in zip(data[0], data[-1], strict=True):
        bind(archive, authority="shared")
        path.write_text(json.dumps(archive), encoding="utf-8")
    assert "observed_native_ai_attribution_required" in inspect(data, "G1")["reasons"]


def test_loaded_fingerprint_is_path_independent_and_covers_rules(tmp_path, monkeypatch):
    path = tmp_path / "relocated_oracle.py"
    path.write_bytes(Path(oracle.__file__).read_bytes())
    spec = importlib.util.spec_from_file_location("relocated_oracle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.code_sha256() == oracle.code_sha256()
    original = module.code_sha256()
    monkeypatch.setitem(module.RULES, "change_psi_max", 10.0)
    assert module.code_sha256() != original
    loaded_after_rule_change = module.code_sha256()
    path.write_text("# source changed after module load\n", encoding="utf-8")
    assert module.code_sha256() == loaded_after_rule_change  # edited source is not attestation


def test_exclusive_sealing_freezes_candidate_and_rejects_same_lap_reuse(tmp_path):
    candidate = tmp_path / "candidate.py"
    candidate.write_text("# pinned candidate\n", encoding="utf-8")
    manifest = tmp_path / "run.json"
    run = oracle.register_run(manifest, "test-run", [candidate])
    data = inputs(tmp_path)
    directory = Path(run["case_receipt_dir"])
    output = directory / "opaque-one.json"
    arguments = dict(
        archives=data[0], spinners=data[1], identity=data[2], targets=data[3], source_paths=data[4]
    )
    result = oracle.seal_case(output, manifest, case_id=str(uuid.uuid4()), slot="G1", **arguments)
    assert result["enrollable"] and result["expires_at"] - result["sealed_at"] == 120
    with pytest.raises(FileExistsError):
        oracle.register_run(manifest, "another-run", [candidate])
    with pytest.raises(ValueError, match="overlapping_measured"):
        oracle.seal_case(
            directory / "opaque-two.json",
            manifest,
            case_id=str(uuid.uuid4()),
            slot="G2",
            **arguments,
        )
    candidate.write_text("# changed candidate\n", encoding="utf-8")
    with pytest.raises(ValueError, match="candidate_changed"):
        oracle.seal_case(
            directory / "opaque-three.json",
            manifest,
            case_id=str(uuid.uuid4()),
            slot="G3",
            **arguments,
        )


def test_one_blocked_corner_does_not_exclude_other_actionable_corners(tmp_path):
    data = inputs(tmp_path)
    data[1][0]["step"] = 2
    result = inspect(data, "G1")
    assert result["enrollable"] and len(result["native_steps"]) == 3
    assert result["blocked_corners"] == {"PRESSURE_LF": "no_meaningful_native_step"}


def test_historical_inputs_cannot_enroll_after_registration(tmp_path):
    data = inputs(tmp_path)
    for archive in data[0]:
        archive["exported_at"] = "2020-01-01T00:00:00Z"
    data = persist(tmp_path, data)
    candidate = tmp_path / "candidate.py"
    candidate.write_text("# fixed candidate\n", encoding="utf-8")
    manifest = tmp_path / "run.json"
    run = oracle.register_run(manifest, "test-run", [candidate])
    with pytest.raises(ValueError, match="not_collected_after"):
        oracle.seal_case(
            Path(run["case_receipt_dir"]) / "old.json",
            manifest,
            case_id=str(uuid.uuid4()),
            slot="G1",
            archives=data[0],
            spinners=data[1],
            identity=data[2],
            targets=data[3],
            source_paths=data[4],
        )


def test_excluded_pilot_does_not_fill_real_slot_but_its_laps_cannot_be_reused(tmp_path):
    candidate = tmp_path / "candidate.py"
    candidate.write_text("# fixed candidate\n", encoding="utf-8")
    manifest = tmp_path / "run.json"
    run = oracle.register_run(manifest, "test-run", [candidate])
    data = inputs(tmp_path, core=40, numbers=(1,))
    directory = Path(run["case_receipt_dir"])
    result = oracle.seal_case(
        directory / "pilot.json",
        manifest,
        case_id=str(uuid.uuid4()),
        slot="T1",
        pilot=True,
        archives=data[0],
        spinners=data[1],
        identity=data[2],
        targets=data[3],
        source_paths=data[4],
    )
    assert not result["scored"] and result["label"] == "cold"
    with pytest.raises(ValueError, match="overlapping_measured"):
        oracle.seal_case(
            directory / "bad-reuse.json",
            manifest,
            case_id=str(uuid.uuid4()),
            slot="T1",
            archives=data[0],
            spinners=data[1],
            identity=data[2],
            targets=data[3],
            source_paths=data[4],
        )


def test_cli_seals_only_opaque_result_on_stdout(tmp_path, capsys):
    candidate = tmp_path / "candidate.py"
    candidate.write_text("# CLI test candidate\n", encoding="utf-8")
    manifest = tmp_path / "run.json"
    assert (
        oracle.main(
            [
                "register-run",
                "--run-id",
                "cli-run",
                "--candidate",
                str(candidate),
                "--output",
                str(manifest),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True
    data = inputs(tmp_path)
    files = {}
    for name, value in zip(("spinners", "identity", "targets"), data[1:4], strict=True):
        files[name] = tmp_path / (name + ".json")
        files[name].write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "oracle-seals" / "opaque.json"
    argv = [
        "inspect",
        "--run-manifest",
        str(manifest),
        "--case-id",
        str(uuid.uuid4()),
        "--slot",
        "G1",
        "--output",
        str(output),
    ]
    for path in data[-1]:
        argv += ["--archive", str(path)]
    for name, path in files.items():
        argv += ["--" + name, str(path)]
    assert oracle.main(argv) == 0
    shown = json.loads(capsys.readouterr().out)
    assert set(shown) == {"ok", "sealed", "sha256"}
    assert json.loads(output.read_text())["label"] == "genuine_high"
    assert oracle.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_loaded_fingerprint_includes_keyword_only_defaults_and_actual_behavior():
    original_defaults = oracle._number.__kwdefaults__
    original_fingerprint = oracle.code_sha256()
    with pytest.raises(ValueError):
        oracle._number("20")
    try:
        oracle._number.__kwdefaults__ = {"ini": True}
        assert oracle._number("20") == 20.0
        assert oracle.code_sha256() != original_fingerprint
    finally:
        oracle._number.__kwdefaults__ = original_defaults
    assert oracle.code_sha256() == original_fingerprint
    with pytest.raises(ValueError):
        oracle._number("20")


def test_loaded_fingerprint_includes_positional_defaults():
    original_defaults = oracle.main.__defaults__
    original_fingerprint = oracle.code_sha256()
    try:
        oracle.main.__defaults__ = ([],)
        assert oracle.code_sha256() != original_fingerprint
    finally:
        oracle.main.__defaults__ = original_defaults
    assert oracle.code_sha256() == original_fingerprint
