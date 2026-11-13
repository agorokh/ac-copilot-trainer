"""Independent sensor oracle and immutable enrollment receipts for issue956.

This module never imports the prescription evaluator. Its labels are hidden
bench evidence, not production admission or permission to actuate a setup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import median
from types import CodeType, FunctionType
from typing import Any

from tools.lap_qualification import ArchiveQualificationSnapshot, payload_sha256

WHEELS = {"fl": "PRESSURE_LF", "fr": "PRESSURE_RF", "rl": "PRESSURE_LR", "rr": "PRESSURE_RR"}
SLOTS = {
    **{f"G{i}": "genuine_high" for i in range(1, 4)},
    **{f"G{i}": "genuine_low" for i in range(4, 7)},
    "T1": "cold",
    "T2": "cold",
    "T3": "short",
    "T4": "short",
    "T5": "lock_scrub",
    "T6": "lock_scrub",
}
RULES = {
    "version": 1,
    "pressure_span_psi_max": 1.0,
    "core_span_c_max": 10.0,
    "quarter_core_trend_c_max": 2.0,
    "between_lap_pressure_psi_max": 0.3,
    "between_lap_core_c_max": 2.0,
    "thermal_below_optimum_c": 20.0,
    "thermal_above_optimum_c": 10.0,
    "genuine_distance_from_ideal_psi_min": 0.85,
    "change_psi_min": 0.5,
    "change_psi_max": 1.5,
    "slip_ratio_abs_max": 0.2,
    "slip_angle_degrees_abs_max": 12.0,
    "legacy_slip_abs_max": 1.5,
    "wheel_to_roster_median_min": 0.6,
    "moving_kmh_min": 30.0,
    "samples_min": 30,
    "lap_ms_min": 30_000,
    "elapsed_gap_ms_max": 5000,
    "raw_source_required": True,
    "authority_required": "ai",
    "canonical_analysis_allowed_required": True,
    "target_content_hashes_required": True,
    "ambiguous_mixed_genuine_directions": "exclude",
    "trap_overlap": "fixed_slot_condition_wins; all observed conditions retained",
    "source_reuse": "exclude any source hash or session/lap already enrolled",
}
_HASH = re.compile(r"^[0-9a-f]{64}$")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _code_material(value: Any) -> Any:
    if isinstance(value, CodeType):
        return {
            "code": value.co_code.hex(),
            "consts": [_code_material(x) for x in value.co_consts],
            "names": value.co_names,
            "varnames": value.co_varnames,
            "freevars": value.co_freevars,
            "cellvars": value.co_cellvars,
            "argcount": value.co_argcount,
            "posonly": value.co_posonlyargcount,
            "kwonly": value.co_kwonlyargcount,
            "flags": value.co_flags,
            "nlocals": value.co_nlocals,
            "stacksize": value.co_stacksize,
            "exceptiontable": value.co_exceptiontable.hex(),
        }
    if isinstance(value, (tuple, frozenset)):
        items = [_code_material(x) for x in value]
        if isinstance(value, frozenset):
            items.sort(key=lambda x: json.dumps(x, sort_keys=True))
        return {type(value).__name__: items}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if value is Ellipsis:
        return {"ellipsis": True}
    return {type(value).__name__: value}


def _state_material(value: Any) -> Any:
    if isinstance(value, dict):
        return {"dict": [[str(k), _state_material(v)] for k, v in sorted(value.items())]}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_state_material(v) for v in value]
        if isinstance(value, (set, frozenset)):
            items.sort(key=lambda v: json.dumps(v, sort_keys=True))
        return {type(value).__name__: items}
    if isinstance(value, re.Pattern):
        return {"regex": value.pattern, "flags": value.flags}
    return _code_material(value)


def code_sha256() -> str:
    """Fingerprint actual loaded functions/state, independent of install paths.

    Reading source/loader code would incorrectly attest a file edited after the
    running module loaded. Function objects preserve the actual running code in
    both Python and PyInstaller; nested code and exception tables are included.
    """
    functions = {
        name: {
            "code": _code_material(value.__code__),
            "defaults": _state_material(value.__defaults__),
            "kwdefaults": _state_material(value.__kwdefaults__),
        }
        for name, value in globals().items()
        if isinstance(value, FunctionType) and value.__module__ == __name__
    }
    if not functions:
        raise RuntimeError("Oracle loaded code is unavailable")
    scalars = (str, int, float, bool, bytes, dict, list, tuple, set, frozenset, re.Pattern)
    state = {
        name: _state_material(value)
        for name, value in globals().items()
        if not name.startswith("__") and (value is None or isinstance(value, scalars))
    }
    return canonical_sha256({"functions": functions, "constants": state})


def source_sha256() -> str | None:
    path = Path(__file__)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def pressure_spinners_sha256(spinners: list[dict[str, Any]]) -> str:
    keys = ("section", "value", "min", "max", "step", "unit", "range_known")
    rows = []
    for row in spinners:
        if row.get("section") in WHEELS.values():
            rows.append(
                {
                    **{key: row.get(key) for key in keys},
                    "read_only": row.get("read_only", False),
                    "display_multiplier": row.get("display_multiplier", 1),
                }
            )
    return canonical_sha256(sorted(rows, key=lambda row: row["section"]))


def _number(value: Any, *, ini: bool = False) -> float:
    if ini and isinstance(value, str):
        try:
            value = float(value)
        except ValueError as exc:
            raise ValueError("cold_snapshot_not_numeric") from exc
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("missing_or_nonfinite_number")
    return float(value)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _normal_path(value: Any) -> str:
    _require(isinstance(value, str) and bool(value.strip()), "setup_path_missing")
    return value.replace("\\", "/").casefold()


def _stable_file(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    file = Path(path)
    before = file.stat()
    raw = file.read_bytes()
    after = file.stat()
    _require(
        (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        and raw == file.read_bytes(),
        "source_changed_during_read",
    )
    value = json.loads(raw)
    _require(isinstance(value, dict), "source_root_not_object")
    return raw, value


def _targets(targets: dict[str, Any]) -> None:
    provenance = targets.get("_provenance", {})
    _require(
        isinstance(provenance, dict)
        and bool(_HASH.fullmatch(str(provenance.get("tyres_ini_sha256", "")))),
        "target_tyres_content_hash_missing",
    )
    curves = provenance.get("curve_sha256")
    _require(
        isinstance(curves, dict)
        and bool(curves)
        and all(isinstance(k, str) and k and _HASH.fullmatch(str(v)) for k, v in curves.items()),
        "target_curve_content_hash_missing",
    )
    for wheel in WHEELS:
        target = targets.get(wheel)
        _require(isinstance(target, dict), "wheel_target_missing")
        _require(
            0 < _number(target.get("pressure_ideal_psi")) <= 100, "pressure_target_out_of_range"
        )
        _require(0 < _number(target.get("optimal_temp_c")) <= 250, "thermal_target_out_of_range")


def _spinner_rows(spinners: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    _require(isinstance(spinners, list), "spinner_list_missing")
    rows = [
        row for row in spinners if isinstance(row, dict) and row.get("section") in WHEELS.values()
    ]
    _require(
        len(rows) == 4 and len({row["section"] for row in rows}) == 4,
        "four_unique_cold_spinners_required",
    )
    result = {row["section"]: row for row in rows}
    for row in rows:
        _require(
            row.get("range_known") is True
            and row.get("read_only") is not True
            and str(row.get("unit", "")).strip().lower() == "psi"
            and _number(row.get("display_multiplier", 1)) == 1,
            "native_psi_bounds_required",
        )
        value, lo, hi, step = (_number(row.get(k)) for k in ("value", "min", "max", "step"))
        _require(step > 0 and lo <= value <= hi, "invalid_cold_bounds")
        _require(
            abs((value - lo) / step - round((value - lo) / step)) <= 1e-6,
            "cold_value_off_native_grid",
        )
    return result


def _measure(archive: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    trace = archive.get("trace", {})
    fields, samples = trace.get("fields"), trace.get("samples")
    _require(
        isinstance(fields, list)
        and all(isinstance(x, str) for x in fields)
        and len(fields) == len(set(fields)),
        "invalid_trace_fields",
    )
    required = ["spline", "speed", "eMs"] + [
        f"{prefix}_{wheel}"
        for prefix in ("wheelsPressure", "tyreCoreTemp", "wheelSlip", "wheelAngularSpeed")
        for wheel in WHEELS
    ]
    _require(all(name in fields for name in required), "sensor_channel_missing")
    _require(isinstance(samples, list) and len(samples) >= 2, "sensor_samples_missing")
    for row in samples:
        _require(isinstance(row, list) and len(row) == len(fields), "sensor_row_incomplete")
        for value in row:
            _number(value)
    data = {name: [_number(row[i]) for row in samples] for i, name in enumerate(fields)}
    lap = archive["lap"]
    lap_ms = _number(lap.get("lap_ms"))
    s, t = data["spline"], data["eMs"]
    complete = (
        len(samples) >= 30
        and lap_ms >= 30_000
        and s[0] <= 0.05
        and s[-1] >= 0.95
        and min(s) >= 0
        and max(s) <= 1
        and t[0] >= 0
        and t[-1] <= lap_ms * 1.05
        and t[-1] - t[0] >= lap_ms * 0.85
        and min(data["speed"]) >= 30
        and all(b >= a for a, b in zip(s, s[1:], strict=False))
        and all(0 < b - a <= 5000 for a, b in zip(t, t[1:], strict=False))
    )
    quarter = max(1, len(samples) // 4)
    wheels = {}
    conditions: set[str] = set()
    for wheel in WHEELS:
        pressure, core = data[f"wheelsPressure_{wheel}"], data[f"tyreCoreTemp_{wheel}"]
        _require(
            min(pressure) > 0 and max(pressure) <= 100 and min(core) > 0 and max(core) <= 250,
            "unread_pressure_or_temperature",
        )
        optimal = _number(targets[wheel]["optimal_temp_c"])
        moving = [i for i, speed in enumerate(data["speed"]) if speed >= 30]
        slip_count = sum(abs(data[f"wheelSlip_{wheel}"][i]) > 1.5 for i in moving)
        for name, threshold in ((f"slipRatio_{wheel}", 0.2), (f"slipAngle_{wheel}", 12.0)):
            if name in data:
                slip_count += sum(abs(data[name][i]) > threshold for i in moving)
        lock_count = 0
        for i in moving:
            rotation = [abs(data[f"wheelAngularSpeed_{w}"][i]) for w in WHEELS]
            angular = abs(data[f"wheelAngularSpeed_{wheel}"][i])
            lock_count += angular < 0.6 * median(rotation) or angular < 1
        spike_count = sum(
            abs(pressure[b] - pressure[a]) > 1 or abs(core[b] - core[a]) > 10
            for a, b in zip(moving, moving[1:], strict=False)
            if 0 < t[b] - t[a] <= 1000
        )
        temp = median(core)
        cold = median(core[:quarter]) < optimal - 20
        if cold:
            conditions.add("measured_cold")
        if slip_count or lock_count or spike_count:
            conditions.add("lock_scrub")
        wheels[wheel] = {
            "hot_psi": median(pressure),
            "core_c": temp,
            "pressure_span_psi": max(pressure) - min(pressure),
            "core_span_c": max(core) - min(core),
            "quarter_core_trend_c": abs(median(core[-quarter:]) - median(core[:quarter])),
            "in_thermal_window": optimal - 20 <= temp <= optimal + 10,
            "moving_slip_events": slip_count,
            "moving_lock_events": lock_count,
            "moving_spike_events": spike_count,
        }
    return {
        "lap_n": lap["lap_n"],
        "complete_flying": complete and lap["lap_n"] >= 2,
        "samples": len(samples),
        "wheels": wheels,
        "conditions": sorted(conditions),
    }


def _admissible_steps(row: dict[str, Any], direction: int, hot: float, ideal: float) -> dict:
    value, lo, hi, step = (_number(row[k]) for k in ("value", "min", "max", "step"))
    minimum = max(1, math.ceil(0.5 / step - 1e-9))
    maximum = math.floor(1.5 / step + 1e-9)
    boundary = (hi - value) if direction > 0 else (value - lo)
    maximum = min(maximum, math.floor(boundary / step + 1e-9))
    # A step must reduce distance to authored ideal, including a possible overshoot.
    maximum = min(maximum, math.ceil(2 * abs(ideal - hot) / step - 1e-9) - 1)
    _require(maximum >= minimum, "no_meaningful_native_step")
    return {
        "direction": direction,
        "step_psi": step,
        "min_clicks": minimum,
        "max_clicks": maximum,
        "from": value,
        "min_abs_delta_psi": minimum * step,
        "max_abs_delta_psi": maximum * step,
    }


def inspect_case(
    archives: list[dict[str, Any]],
    spinners: list[dict[str, Any]],
    identity: dict[str, Any],
    targets: dict[str, Any],
    *,
    slot: str | None = None,
    source_paths: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Measure independently; no real slot enrolls without file-backed AI inputs."""
    result: dict[str, Any] = {
        "enrollable": False,
        "label": "indeterminate",
        "reasons": [],
        "expected_abstention": True,
        "directions": {},
        "native_steps": {},
        "measurements": [],
        "sources": [],
        "archive_hashes": [],
        "slot": slot,
        "authority": "ai",
    }
    qualifications = []
    snapshots = []
    try:
        _require(
            isinstance(archives, list) and 1 <= len(archives) <= 2, "one_or_two_raw_laps_required"
        )
        _require(isinstance(identity, dict), "identity_missing")
        _require(
            all(
                isinstance(identity.get(k), str) and identity[k]
                for k in ("car_id", "track_id", "session_id", "setup_path")
            ),
            "identity_incomplete",
        )
        compound = _number(identity.get("compound_index"))
        _require(compound >= 0 and compound == int(compound), "compound_identity_invalid")
        _targets(targets)
        rows = _spinner_rows(spinners)
        result["identity"] = identity
        result["targets_sha256"] = canonical_sha256(targets)
        result["spinners_sha256"] = pressure_spinners_sha256(spinners)
        _require(
            source_paths is not None and len(source_paths) == len(archives),
            "source_file_binding_missing",
        )
        numbers, setup_hashes, lap_ids = [], [], []
        for archive, path in zip(archives, source_paths, strict=True):
            raw, original = _stable_file(path)
            _require(
                canonical_sha256(original) == canonical_sha256(archive),
                "archive_dictionary_differs_from_raw_file",
            )
            sha = hashlib.sha256(raw).hexdigest()
            snapshot = ArchiveQualificationSnapshot(archive, source_path=path, source_sha256=sha)
            q = snapshot.qualify(
                use="analysis",
                expected_combo=(
                    identity["car_id"],
                    identity["track_id"],
                    identity.get("layout_id") or None,
                ),
            )
            qualifications.append(q)
            snapshots.append(snapshot)
            _require(q.authority == "ai" and q.managed, "observed_native_ai_attribution_required")
            _require(archive.get("source") == "in_game", "native_source_required")
            lap = archive.get("lap", {})
            n = _number(lap.get("lap_n"))
            _require(
                n >= 1 and n == int(n) and lap.get("is_valid") is True,
                "valid_native_lap_identity_required",
            )
            numbers.append(int(n))
            lap_ids.append(archive.get("lap_uuid"))
            _require(
                archive.get("session_uuid") == identity["session_id"]
                and archive.get("car", {}).get("id") == identity["car_id"]
                and archive.get("track", {}).get("id") == identity["track_id"]
                and (archive.get("track", {}).get("layout") or "")
                == (identity.get("layout_id") or "")
                and _number(archive.get("tyres", {}).get("compoundIndex")) == compound,
                "native_identity_changed",
            )
            setup = archive.get("setup", {})
            _require(
                isinstance(setup.get("hash"), str)
                and bool(setup["hash"])
                and _normal_path(setup.get("path")) == _normal_path(identity["setup_path"]),
                "historical_cold_setup_provenance_missing",
            )
            setup_hashes.append(setup["hash"])
            cold = setup.get("snapshot")
            _require(isinstance(cold, dict), "four_cold_snapshots_required")
            for section in WHEELS.values():
                _require(
                    abs(
                        _number(cold.get(section + ".VALUE"), ini=True)
                        - _number(rows[section]["value"])
                    )
                    <= 0.001,
                    "cold_pressure_changed_since_stint",
                )
            thermal = _number(archive.get("tyres", {}).get("optimalTempC"))
            front = targets["fl"]
            lower = _number(front.get("peak_temp_min_c", front["optimal_temp_c"]))
            upper = _number(front.get("peak_temp_max_c", front["optimal_temp_c"]))
            _require(lower - 1 <= thermal <= upper + 1, "historical_thermal_target_changed")
            measurements = _measure(archive, targets)
            result["measurements"].append(measurements)
            canonical = canonical_sha256(original)
            result["archive_hashes"].append(canonical)
            result["sources"].append(
                {
                    "path": str(Path(path).resolve()),
                    "sha256": sha,
                    "canonical_sha256": canonical,
                    "payload_sha256": payload_sha256(original),
                    "session_id": archive["session_uuid"],
                    "lap_uuid": archive["lap_uuid"],
                    "lap_n": int(n),
                }
            )
        _require(len(set(lap_ids)) == len(lap_ids), "duplicate_lap_identity")
        _require(len(set(setup_hashes)) == 1, "setup_changed_between_laps")
        _require(len(numbers) == 1 or numbers[1] == numbers[0] + 1, "laps_not_consecutive")
        observed = {condition for m in result["measurements"] for condition in m["conditions"]}
        if 1 in numbers and "measured_cold" in observed:
            observed.add("cold")
        if sum(m["complete_flying"] for m in result["measurements"]) < 2:
            observed.add("short")
        result["observed_conditions"] = sorted(observed)
        desired = SLOTS.get(slot) if slot is not None else None
        _require(slot is None or desired is not None, "slot_not_registered")
        if desired in {"cold", "short", "lock_scrub"}:
            _require(desired in observed, "intended_trap_not_observed")
            label = desired
        elif desired is None and any(k in observed for k in ("cold", "short", "lock_scrub")):
            label = next(k for k in ("cold", "short", "lock_scrub") if k in observed)
        else:
            _require(len(numbers) == 2 and min(numbers) >= 2, "two_flying_laps_required")
            _require(
                all(m["complete_flying"] for m in result["measurements"]),
                "complete_moving_flying_laps_required",
            )
            _require("lock_scrub" not in observed, "technique_confounded")
            for wheel, section in WHEELS.items():
                a, b = [m["wheels"][wheel] for m in result["measurements"]]
                _require(
                    all(
                        w["pressure_span_psi"] <= 1
                        and w["core_span_c"] <= 10
                        and w["quarter_core_trend_c"] <= 2
                        and w["in_thermal_window"]
                        for w in (a, b)
                    ),
                    "unstable_or_out_of_window",
                )
                _require(
                    abs(a["hot_psi"] - b["hot_psi"]) <= 0.3 + 1e-9
                    and abs(a["core_c"] - b["core_c"]) <= 2,
                    "between_lap_instability",
                )
                ideal = _number(targets[wheel]["pressure_ideal_psi"])
                deviations = [w["hot_psi"] - ideal for w in (a, b)]
                direction = (
                    -1
                    if min(deviations) >= 0.85 - 1e-8
                    else (1 if max(deviations) <= -0.85 + 1e-8 else 0)
                )
                result["directions"][section] = direction
                if direction:
                    try:
                        result["native_steps"][section] = _admissible_steps(
                            rows[section], direction, (a["hot_psi"] + b["hot_psi"]) / 2, ideal
                        )
                    except ValueError:
                        result.setdefault("blocked_corners", {})[section] = (
                            "no_meaningful_native_step"
                        )
            active = {v for v in result["directions"].values() if v}
            _require(len(active) == 1, "no_unambiguous_genuine_deviation")
            label = "genuine_high" if active == {-1} else "genuine_low"
            _require(desired is None or desired == label, "intended_genuine_direction_not_observed")
            _require(bool(result["native_steps"]), "no_meaningful_native_step")
            result["expected_abstention"] = False
        # A measured trap remains diagnostic evidence when canonical analysis
        # denies the source. It never becomes an enrollable bench input.
        result["label"] = label
        result["analysis_qualifications"] = [
            {"allowed": q.allowed, "authority": q.authority, "reasons": list(q.reasons)}
            for q in qualifications
        ]
        for q in qualifications:
            _require(q.allowed, "canonical_analysis_denied:" + ",".join(q.reasons))
        for snapshot in snapshots:
            snapshot.assert_current()
        result.update(enrollable=True, label=label)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, OverflowError) as exc:
        result["reasons"].append(str(exc))
    return result


def _exclusive(path: str | Path, value: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def register_run(path: str | Path, run_id: str, candidate_paths: list[str | Path]) -> dict:
    _require(bool(candidate_paths) and bool(run_id), "candidate_paths_and_run_id_required")
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "registered_at": time.time(),
        "oracle_sha256": code_sha256(),
        "oracle_source_sha256": source_sha256(),
        "rule_sha256": canonical_sha256(RULES),
        "rules": RULES,
        "slots": SLOTS,
        "case_receipt_dir": str((Path(path).resolve().parent / "oracle-seals").resolve()),
        "candidate_hashes": {
            str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
            for p in candidate_paths
        },
    }
    _exclusive(path, record)
    return record


def seal_case(
    path: str | Path,
    run_manifest: str | Path,
    *,
    case_id: str,
    slot: str,
    archives: list[dict[str, Any]],
    spinners: list[dict[str, Any]],
    identity: dict[str, Any],
    targets: dict[str, Any],
    source_paths: list[str | Path],
    previous_receipts: list[str | Path] = (),
    pilot: bool = False,
) -> dict:
    run_raw, run = _stable_file(run_manifest)
    _require(
        run.get("oracle_sha256") == code_sha256()
        and run.get("oracle_source_sha256") == source_sha256()
        and run.get("rule_sha256") == canonical_sha256(RULES)
        and run.get("slots") == SLOTS,
        "registered_oracle_or_rules_changed",
    )
    for file, expected in run["candidate_hashes"].items():
        _require(
            hashlib.sha256(Path(file).read_bytes()).hexdigest() == expected,
            "candidate_changed_after_registration",
        )
    _require(bool(re.fullmatch(r"[a-fA-F0-9-]{32,36}", case_id)), "opaque_case_uuid_required")
    now = time.time()
    for archive in archives:
        exported = archive.get("exported_at")
        _require(isinstance(exported, str), "native_export_timestamp_missing")
        at = datetime.fromisoformat(exported.replace("Z", "+00:00"))
        _require(at.tzinfo is not None, "native_export_timestamp_not_utc_bound")
        _require(
            _number(run.get("registered_at")) <= at.timestamp() <= now + 1,
            "native_case_not_collected_after_registration",
        )
    result = inspect_case(
        archives, spinners, identity, targets, slot=slot, source_paths=source_paths
    )
    _require(result["enrollable"], "case_not_enrollable:" + ";".join(result["reasons"]))
    receipt_dir = Path(run["case_receipt_dir"]).resolve()
    _require(Path(path).resolve().parent == receipt_dir, "receipt_outside_frozen_directory")
    prior_paths = set(receipt_dir.glob("*.json")) | {Path(p) for p in previous_receipts}
    occupied_slots = set()
    for prior_path in sorted(prior_paths):
        _, prior = _stable_file(prior_path)
        _require(prior.get("run_id") == run["run_id"], "prior_receipt_run_mismatch")
        _require(prior.get("case_id") != case_id, "case_already_enrolled")
        if prior.get("scored") is True:
            occupied_slots.add(prior.get("slot"))
        _require(
            pilot or prior.get("scored") is not True or prior.get("slot") != slot,
            "slot_already_enrolled",
        )
        prior_sources = prior.get("sources", [])
        used_bytes = {s["sha256"] for s in prior_sources}
        used_ids = {(s["session_id"], s["lap_uuid"]) for s in prior_sources}
        _require(
            not any(
                s["sha256"] in used_bytes or (s["session_id"], s["lap_uuid"]) in used_ids
                for s in result["sources"]
            ),
            "overlapping_measured_lap_window",
        )
    if not pilot:
        available = [
            registered_slot for registered_slot in SLOTS if registered_slot not in occupied_slots
        ]
        _require(bool(available) and slot == available[0], "fixed_enrollment_order_required")
    result.update(
        schema_version=1,
        scored=not pilot,
        run_id=run["run_id"],
        case_id=case_id,
        mode="956_ai_bench_oracle",
        oracle_sha256=code_sha256(),
        oracle_source_sha256=source_sha256(),
        rule_sha256=canonical_sha256(RULES),
        run_manifest_sha256=hashlib.sha256(run_raw).hexdigest(),
        sealed_at=now,
        expires_at=now + 120,
    )
    _exclusive(path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    register = sub.add_parser("register-run")
    register.add_argument("--run-id", required=True)
    register.add_argument("--candidate", action="append", required=True)
    register.add_argument("--output", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--run-manifest", required=True)
    inspect.add_argument("--case-id", required=True)
    inspect.add_argument("--slot", choices=SLOTS, required=True)
    inspect.add_argument("--archive", action="append", required=True)
    for name in ("spinners", "identity", "targets", "output"):
        inspect.add_argument("--" + name, required=True)
    inspect.add_argument("--previous-receipt", action="append", default=[])
    inspect.add_argument("--pilot", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "register-run":
            register_run(args.output, args.run_id, args.candidate)
        else:

            def read(p):
                return json.loads(Path(p).read_bytes())

            seal_case(
                args.output,
                args.run_manifest,
                case_id=args.case_id,
                slot=args.slot,
                archives=[read(p) for p in args.archive],
                spinners=read(args.spinners),
                identity=read(args.identity),
                targets=read(args.targets),
                source_paths=args.archive,
                previous_receipts=args.previous_receipt,
                pilot=args.pilot,
            )
        print(
            json.dumps(
                {
                    "ok": True,
                    "sealed": str(Path(args.output).resolve()),
                    "sha256": hashlib.sha256(Path(args.output).read_bytes()).hexdigest(),
                }
            )
        )
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
