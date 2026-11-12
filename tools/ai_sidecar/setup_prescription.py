"""Bounded, experimental cold-pressure cards from measured flying-lap traces.

These conservative thresholds are experiment policy, not a tyre-physics fit.
The caller supplies authenticated live context and car-authored axle targets;
this module never substitutes the thermal model's estimated hot pressure.
Application belongs exclusively to the authenticated, pit-rechecking Lua RPC.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from pathlib import Path
from statistics import median
from typing import Any

from tools.ai_sidecar.setup_optimizer import load_records, save_records, store_transaction
from tools.lap_qualification import qualify_archive

WHEELS = {"fl": "PRESSURE_LF", "fr": "PRESSURE_RF", "rl": "PRESSURE_LR", "rr": "PRESSURE_RR"}
MAX_DELTA_PSI = 1.5
TTL_S = 120.0
RECORD_TYPE = "setup_prescription"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _path(value: Any) -> str:
    return str(value or "").replace("\\", "/").casefold()


def _cold_number(value: Any) -> float | None:
    # INI snapshots preserve textual VALUE fields; live spinners use numbers.
    if isinstance(value, str):
        try:
            return _number(float(value))
        except ValueError:
            return None
    return _number(value)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _trace_summary(archive: dict[str, Any], wheel: str) -> tuple[float, float]:
    """Require complete, moving, thermally stable observations, including traps."""
    trace = archive.get("trace", {})
    fields, samples = trace.get("fields"), trace.get("samples")
    names = ["spline", "speed", "eMs"]
    names += [f"{prefix}_{wheel}" for prefix in ("wheelsPressure", "tyreCoreTemp", "wheelSlip")]
    names += [f"wheelAngularSpeed_{w}" for w in WHEELS]
    if not isinstance(fields, list) or len(set(fields)) != len(fields):
        raise ValueError("Missing or duplicate measured trace channels")
    if not all(name in fields for name in names) or not isinstance(samples, list):
        raise ValueError("Measured pressure, temperature and technique channels required")
    if len(samples) < 30:
        raise ValueError("Insufficient full-lap observations")
    indices = {name: i for i, name in enumerate(fields)}
    columns: dict[str, list[float]] = {name: [] for name in names}
    for row in samples:
        for name in names:
            index = indices[name]
            value = _number(row[index]) if isinstance(row, list) and index < len(row) else None
            if value is None:
                raise ValueError("Unread or nonfinite measured channel")
            columns[name].append(value)
        # Optional extended-physics channels are not required on stock cars;
        # when readable they can veto a lockup/scrubbing-confounded window.
        for name, limit in ((f"slipRatio_{wheel}", 0.2), (f"slipAngle_{wheel}", 12.0)):
            if name in fields:
                i = indices[name]
                value = _number(row[i]) if i < len(row) else None
                if value is not None and abs(value) > limit:
                    raise ValueError("Lockup or scrubbing evidence; no pressure trim")
    spline, elapsed = columns["spline"], columns["eMs"]
    lap_ms = _number(archive.get("lap", {}).get("lap_ms"))
    if lap_ms is None or lap_ms < 30_000:
        raise ValueError("Flying-lap duration unavailable")
    if (
        spline[0] > 0.05
        or spline[-1] < 0.95
        or min(spline) < 0
        or max(spline) > 1
        or any(b < a for a, b in zip(spline, spline[1:], strict=False))
        or elapsed[0] < 0
        or elapsed[-1] > lap_ms * 1.05
        or elapsed[-1] - elapsed[0] < lap_ms * 0.85
        or any(b <= a or b - a > 5000 for a, b in zip(elapsed, elapsed[1:], strict=False))
        or min(columns["speed"]) < 30
    ):
        raise ValueError("Incomplete, stopped or non-flying lap")
    pressure = columns[f"wheelsPressure_{wheel}"]
    core = columns[f"tyreCoreTemp_{wheel}"]
    if min(pressure) <= 0 or max(pressure) > 100 or min(core) <= 0 or max(core) > 250:
        raise ValueError("Unread pressure or temperature")
    if max(pressure) - min(pressure) > 1.0 or max(core) - min(core) > 10:
        raise ValueError("Transient pressure or thermal spike")
    quarter = max(1, len(core) // 4)
    if abs(median(core[-quarter:]) - median(core[:quarter])) > 2:
        raise ValueError("Tyres still warming or cooling")
    if any(abs(v) > 1.5 for v in columns[f"wheelSlip_{wheel}"]):
        raise ValueError("Lockup or scrubbing evidence; no pressure trim")
    for i in range(len(samples)):
        angular = [abs(columns[f"wheelAngularSpeed_{w}"][i]) for w in WHEELS]
        if min(angular) < 0.6 * median(angular) or min(angular) < 1:
            raise ValueError("Wheel-lock evidence; no pressure trim")
    return float(median(pressure)), float(median(core))


def build_prescription(
    archives: list[dict[str, Any]],
    spinners: list[dict[str, Any]],
    *,
    identity: dict[str, Any],
    targets: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate the last two consecutive laps; never skip a confounded last lap.

    Targets are per-wheel ``pressure_ideal_psi`` and ``optimal_temp_c`` from
    strict, separate FRONT/REAR car data. +/-0.25 psi is the experimental
    deadband, not an assertion that every compound has that optimal window.
    """
    card: dict[str, Any] = {
        "v": 1,
        "type": "setup.prescription.card",
        "status": "abstained",
        "summary": "No cold-pressure trim",
        "evidence": "",
        "reason": "",
        "changes": [],
        "identity": copy.deepcopy(identity),
        "created_at": time.time(),
        "ttl_s": TTL_S,
    }
    selected = archives[-2:]
    evidence_hashes: list[str] = []
    try:
        if len(selected) != 2:
            raise ValueError("Need two consecutive stabilized flying laps")
        if not all(identity.get(key) for key in ("car_id", "track_id", "session_id", "setup_path")):
            raise ValueError("Live session/setup identity unavailable")
        compound = _number(identity.get("compound_index"))
        if compound is None or compound < 0 or compound != int(compound):
            raise ValueError("Compound identity unavailable")
        numbers, hashes = [], []
        rows = {row.get("section"): row for row in spinners if isinstance(row, dict)}
        for archive in selected:
            evidence_hashes.append(_hash(archive))
            if archive.get("source") != "in_game":
                raise ValueError("Native driver laps required")
            qualification = qualify_archive(
                archive,
                use="live_reference",
                expected_combo=(
                    identity["car_id"],
                    identity["track_id"],
                    identity.get("layout_id") or None,
                ),
            )
            # Honor the canonical policy's legacy-driver allowance. Its ledger
            # can restrict AI/shared records but cannot certify a new human
            # session; experiment adjudication needs its own observed evidence.
            if not qualification.allowed:
                raise ValueError("Archive is not eligible driver telemetry")
            lap = archive.get("lap", {})
            number = _number(lap.get("lap_n"))
            if (
                number is None
                or number < 2
                or number != int(number)
                or lap.get("is_valid") is not True
            ):
                raise ValueError("Out-lap, invalid lap or unknown flying-lap state")
            numbers.append(int(number))
            if (
                archive.get("car", {}).get("id") != identity["car_id"]
                or archive.get("track", {}).get("id") != identity["track_id"]
                or (archive.get("track", {}).get("layout") or "")
                != (identity.get("layout_id") or "")
                or archive.get("session_uuid") != identity["session_id"]
                or _number(archive.get("tyres", {}).get("compoundIndex")) != compound
            ):
                raise ValueError("Session/car/track/compound changed")
            setup = archive.get("setup", {})
            if not setup.get("hash") or _path(setup.get("path")) != _path(identity["setup_path"]):
                raise ValueError("Historical cold setup provenance unavailable")
            hashes.append(setup["hash"])
            snapshot = setup.get("snapshot")
            if not isinstance(snapshot, dict):
                raise ValueError("Historical cold setup snapshot unavailable")
            for wheel, section in WHEELS.items():
                row, target = rows.get(section, {}), targets.get(wheel, {})
                cold, old = (
                    _number(row.get("value")),
                    _cold_number(snapshot.get(section + ".VALUE")),
                )
                ideal, optimal = (
                    _number(target.get("pressure_ideal_psi")),
                    _number(target.get("optimal_temp_c")),
                )
                if ideal is None or optimal is None or ideal <= 0 or optimal <= 0:
                    raise ValueError("Compound-specific axle target unavailable")
                if wheel == "fl":
                    historical = _number(archive.get("tyres", {}).get("optimalTempC"))
                    if historical is None or abs(historical - optimal) > 1:
                        raise ValueError("Car thermal target changed or is unverified")
                if cold is None or old is None or abs(cold - old) > 0.001:
                    raise ValueError("Cold setup changed since the measured stint")
        if numbers[1] != numbers[0] + 1 or hashes[0] != hashes[1]:
            raise ValueError("Need consecutive laps on one unchanged setup")
        changes, observations = [], []
        for wheel, section in WHEELS.items():
            row, target = rows[section], targets[wheel]
            ideal, optimal = target["pressure_ideal_psi"], target["optimal_temp_c"]
            a, b = (_trace_summary(archive, wheel) for archive in selected)
            if abs(a[0] - b[0]) > 0.3 or abs(a[1] - b[1]) > 2:
                raise ValueError("Pressure/temperature not stabilized across flying laps")
            if not all(optimal - 20 <= value <= optimal + 10 for value in (a[1], b[1])):
                raise ValueError("Cold or overheated tyres; thermal confounding")
            hot = (a[0] + b[0]) / 2
            observations.append(f"{section[-2:]} {hot:.1f}/{ideal:.1f} psi")
            # Require both laps to deviate on the same side, >=0.6 off deadband.
            direction = 1 if hot < ideal else -1
            if not all(direction * (ideal - value[0]) >= 0.85 - 1e-8 for value in (a, b)):
                continue
            value = _number(row.get("value"))
            lo, hi, step = (_number(row.get(key)) for key in ("min", "max", "step"))
            if (
                row.get("range_known") is not True
                or row.get("read_only") is True
                or row.get("unit", "").strip().lower() != "psi"
                or _number(row.get("display_multiplier", 1)) != 1
                or value is None
                or lo is None
                or hi is None
                or step is None
                or step <= 0
                or lo > hi
                or not lo <= value <= hi
                or abs((value - lo) / step - round((value - lo) / step)) > 1e-6
            ):
                raise ValueError("Known psi spinner range and step required")
            # Quantize toward ideal, bounded by policy and the actual supported grid.
            clicks = min(
                math.floor(MAX_DELTA_PSI / step), math.floor(abs(ideal - hot) / step + 0.5)
            )
            to = value + direction * clicks * step
            to = min(hi, max(lo, to))
            to = lo + round((to - lo) / step) * step
            delta = to - value
            if abs(delta) < 0.5 or abs(delta) > MAX_DELTA_PSI or not lo <= to <= hi:
                continue
            if delta * (ideal - hot) <= 0 or abs(ideal - (hot + delta)) >= abs(ideal - hot):
                continue
            changes.append(
                {
                    "section": section,
                    "from": value,
                    "to": round(to, 6),
                    "delta_psi": round(delta, 6),
                }
            )
        card["lap_window"] = numbers
        card["targets"] = {
            wheel: {
                key: float(targets[wheel][key]) for key in ("pressure_ideal_psi", "optimal_temp_c")
            }
            for wheel in WHEELS
        }
        card["evidence"] = f"Laps {numbers[0]}-{numbers[1]} measured; " + "; ".join(observations)
        if changes:
            card.update(
                status="proposed", summary="Stabilized hot pressure off target", changes=changes
            )
        else:
            card["reason"] = "No safe, meaningful supported cold-pressure trim"
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        card["reason"] = str(exc)
    # Invalid/nonfinite archives still abstain with a stable, JSON-safe identity.
    card["archive_hashes"] = evidence_hashes
    card["prescription_id"] = _hash(
        {
            "policy": 1,
            "identity": identity,
            "laps": evidence_hashes,
            "changes": card["changes"],
            "targets": card.get("targets", {}),
            "reason": card["reason"],
        }
    )[:32]
    return card


class PrescriptionJournal:
    """One durable row per card in the existing experiments.jsonl authority.

    OS locks serialize sidecar worker threads and CLI optimizer rebuilds.
    A decision is committed before RPC;
    an interrupted apply is never replayed by a reconnect or process restart.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def get(self, prescription_id: str) -> dict[str, Any] | None:
        with store_transaction(self.path):
            for row in load_records(self.path):
                if (
                    row.get("record_type") == RECORD_TYPE
                    and row.get("prescription_id") == prescription_id
                ):
                    return copy.deepcopy(row)
        return None

    def _put(self, record: dict[str, Any]) -> dict[str, Any]:
        rows = load_records(self.path)
        rows = [row for row in rows if row.get("experiment_id") != record["experiment_id"]]
        save_records([*rows, record], self.path)
        return copy.deepcopy(record)

    def remember(self, card: dict[str, Any]) -> dict[str, Any]:
        with store_transaction(self.path):
            existing = self.get(card["prescription_id"])
            if existing is not None:
                return existing
            record = copy.deepcopy(card)
            record.update(
                record_type=RECORD_TYPE, experiment_id="prescription:" + card["prescription_id"]
            )
            return self._put(record)

    def decide(self, prescription_id: str, decision: str) -> dict[str, Any]:
        if decision not in {"accept", "reject"}:
            raise ValueError("Unknown prescription decision")
        with store_transaction(self.path):
            row = self.get(prescription_id)
            if row is None:
                raise ValueError("Unknown prescription")
            if row.get("decision") is not None:
                return {**row, "new_decision": False}
            now = time.time()
            created = _number(row.get("created_at"))
            expired = created is None or not 0 <= now - created <= TTL_S
            if expired:
                row.update(status="expired", decision="timeout", decided_at=now)
            elif decision == "reject":
                row.update(status="rejected", decision="reject", decided_at=now)
            elif row.get("status") == "proposed" and row.get("changes"):
                row.update(status="accepted_unverified", decision="accept", decided_at=now)
            else:
                row.update(status="blocked", decision="accept", decided_at=now)
            result = self._put(row)
            return {**result, "new_decision": True}

    def verify(self, prescription_id: str, readback: dict[str, Any]) -> dict[str, Any]:
        with store_transaction(self.path):
            row = self.get(prescription_id)
            if row is None:
                raise ValueError("Unknown prescription")
            if row.get("status") != "accepted_unverified":
                return row
            matches = bool(row.get("changes")) and all(
                _number(readback.get(change["section"])) is not None
                and abs(readback[change["section"]] - change["to"]) <= 0.001
                for change in row["changes"]
            )
            row["readback"] = {
                key: value for key, value in readback.items() if _number(value) is not None
            }
            if matches:
                row.update(status="verified_applied", verified_at=time.time())
            return self._put(row)
