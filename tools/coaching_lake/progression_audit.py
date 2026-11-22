"""Offline condition-matched session progression over retained coaching-lake archives."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import combinations, product
from pathlib import Path
from statistics import mean, quantiles
from typing import Any

from tools.ai_sidecar.traffic_eligibility import archive_traffic_eligibility
from tools.coaching_lake.build_analytics import (
    DEFAULT_FUEL_EFFECT_S_PER_KG,
    _compute_lap_scalars,
)
from tools.lap_archive_export import (
    LapArchiveExportError,
    iter_lap_archive_paths,
    load_lap_archive_snapshot,
)
from tools.lap_qualification import (
    ArchiveQualificationSnapshot,
    AttributionError,
    archive_combo,
    duplicate_identity_reasons,
)

MIN_SESSIONS = 3
TRIALS = 1000
PERMUTATIONS = 999
ALPHA = 0.05
SEED = 957
SHIFTS_MS = (200, 300, 400, 500)
DIMENSIONS = (
    "setup_hash",
    "tyre_compound",
    "thermal_band",
    "fuel_band",
    "assists",
    "traffic_eligibility",
)
Combo = tuple[str, str, str | None]
Stratum = tuple[str, ...]
Assignment = tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class Conditions:
    stratum: Stratum
    track_temp: float
    tyre_temp: float
    fuel: float


@dataclass(frozen=True)
class Session:
    uid: str
    later: bool
    lap_ms: float
    nuisance_ms: float


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if type(value) in (float, int) and -1e9 <= value <= 1e9:
        return float(value)
    return None


def _record_time(record: dict) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(_text(record.get("exported_at")))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.utcoffset() is not None else None


def _conditions(record: dict, traffic_clear: bool) -> tuple[Conditions | None, list[str]]:
    """Use the same native tyre and fuel reductions as the lake. Never use corrected lap time."""
    setup_data = _mapping(record.get("setup"))
    setup = _text(setup_data.get("hash"))
    tyres = _mapping(record.get("tyres"))
    compound = _text(tyres.get("name")) or _text(tyres.get("longName"))
    recorded = _mapping(record.get("conditions"))
    features = _compute_lap_scalars(
        {
            "trace": record["trace"],
            "tyres": {"name": compound},
        },
        fuel_effect_s_per_kg=DEFAULT_FUEL_EFFECT_S_PER_KG,
    )
    # Match the complete recorded configuration. Empty and partial modes are unknown.
    assists = _mapping(recorded.get("assists"))
    assists_complete = set(assists) >= {
        "abs",
        "traction_control",
        "stability_control",
        "auto_clutch",
    } and all(type(v) in (bool, int) or _number(v) is not None for v in assists.values())
    track = _number(recorded.get("trackTempC"))
    ambient = _number(recorded.get("ambientTempC"))
    wheels = [_number(features[f"core_temp_avg_{wheel}"]) for wheel in ("fl", "fr", "rl", "rr")]
    fuel = _number(features["fuel_start_kg"])
    missing = [
        name
        for name, absent in zip(
            DIMENSIONS,
            (
                not setup,
                not compound,
                track is None or ambient is None or any(value is None for value in wheels),
                fuel is None or fuel < 0,
                not assists_complete,
                not traffic_clear,
            ),
            strict=True,
        )
        if absent
    ]
    if missing:
        return None, missing
    assert track is not None and ambient is not None and fuel is not None
    tyre = mean(value for value in wheels if value is not None)
    thermal_band = "/".join(str(5 * math.floor(value / 5)) for value in (ambient, track, tyre))
    stratum = (
        setup,
        compound,
        thermal_band,
        str(math.floor(fuel)),
        json.dumps(assists, sort_keys=True, separators=(",", ":")),
        "clear",
    )
    return Conditions(stratum, track, tyre, fuel), []


def _nuisance(row: Conditions) -> float:
    """Frozen synthetic challenge in ms, including within-band drift."""
    return 30 * row.track_temp + 20 * row.tyre_temp + 30 * row.fuel


def _assignment(rng: random.Random, sizes: list[tuple[int, int]]) -> Assignment:
    return tuple(tuple(sorted(rng.sample(range(total), later))) for total, later in sizes)


def _reference_assignments(sizes: list[tuple[int, int]]) -> tuple[list[Assignment], bool]:
    possible = math.prod(math.comb(total, later) for total, later in sizes)
    if possible <= PERMUTATIONS:
        return list(product(*(combinations(range(total), later) for total, later in sizes))), True
    rng = random.Random(SEED)
    return [_assignment(rng, sizes) for _ in range(PERMUTATIONS)], False


def _contrast(values: list[list[float]], assignment: Assignment, weights: list[int]) -> float:
    """Positive means faster in the later period."""
    result = 0.0
    for cell, later, weight in zip(values, assignment, weights, strict=True):
        total = sum(cell)
        later_sum = sum(cell[i] for i in later)
        result += weight * ((total - later_sum) / (len(cell) - len(later)) - later_sum / len(later))
    return result / sum(weights)


def _p_value(exceedances: int, count: int, exact: bool) -> float:
    return exceedances / count if exact else (exceedances + 1) / (count + 1)


def _calibrate(
    cells: list[list[Session]],
    sizes: list[tuple[int, int]],
    references: list[Assignment],
    exact: bool,
    weights: list[int],
) -> dict:
    rng = random.Random(SEED + 1)
    null_claims = nuisance_claims = 0
    detections = dict.fromkeys(SHIFTS_MS, 0)
    for trial in range(TRIALS):
        labels = _assignment(rng, sizes)
        null = [[row.lap_ms for row in cell] for cell in cells]
        # Shuffle the pace baseline independently of the recorded temperatures/fuel.
        # Keep the original period memberships for the nuisance-only challenge.
        nuisance = []
        nuisance_labels = []
        for baseline, cell in zip(null, cells, strict=True):
            shuffled = rng.sample(baseline, len(baseline))
            sign = (-1) ** trial
            nuisance.append(
                [ms + sign * row.nuisance_ms for ms, row in zip(shuffled, cell, strict=True)]
            )
            nuisance_labels.append(tuple(i for i, row in enumerate(cell) if row.later))
        nuisance_assignment = tuple(nuisance_labels)
        null_observed = _contrast(null, labels, weights)
        nuisance_observed = _contrast(nuisance, nuisance_assignment, weights)
        injection = [
            [-float(i in assigned) for i in range(len(cell))]
            for cell, assigned in zip(cells, map(set, labels), strict=True)
        ]
        null_tail = nuisance_tail = 0
        shift_tails = dict.fromkeys(SHIFTS_MS, 0)
        for reference in references:
            base_delta = _contrast(null, reference, weights)
            injection_delta = _contrast(injection, reference, weights)
            null_tail += base_delta >= null_observed - 1e-8
            nuisance_tail += _contrast(nuisance, reference, weights) >= nuisance_observed - 1e-8
            for shift in SHIFTS_MS:
                shift_tails[shift] += (
                    base_delta + shift * injection_delta >= null_observed + shift - 1e-8
                )
        null_claims += null_observed > 0 and _p_value(null_tail, len(references), exact) <= ALPHA
        nuisance_claims += (
            nuisance_observed > 0 and _p_value(nuisance_tail, len(references), exact) <= ALPHA
        )
        for shift in SHIFTS_MS:
            detections[shift] += (
                null_observed + shift > 0
                and _p_value(shift_tails[shift], len(references), exact) <= ALPHA
            )
    errors = {
        "null_false_improvement_rate": null_claims / TRIALS,
        "nuisance_false_improvement_rate": nuisance_claims / TRIALS,
    }
    power = {str(shift): count / TRIALS for shift, count in detections.items()}
    return {
        "status": "pass" if max(errors.values()) <= ALPHA and power["300"] >= 0.8 else "fail",
        "seed": SEED,
        "trials_per_scenario": TRIALS,
        "reference_permutations": len(references),
        "exact_reference": exact,
        **errors,
        "detection_power_by_shift_ms": power,
    }


def _evaluate(cells: list[list[Session]]) -> dict:
    if not cells:
        return {
            "status": "cannot_identify",
            "reason": "no_stratum_has_three_independent_sessions_per_period",
            "calibration": {"status": "inconclusive"},
        }
    observed = tuple(tuple(i for i, row in enumerate(cell) if row.later) for cell in cells)
    sizes = [(len(cell), len(later)) for cell, later in zip(cells, observed, strict=True)]
    weights = [min(later, total - later) for total, later in sizes]
    references, exact = _reference_assignments(sizes)
    calibration = _calibrate(cells, sizes, references, exact, weights)
    if calibration["status"] != "pass":
        return {
            "status": "cannot_identify",
            "reason": "calibration_failed",
            "calibration": calibration,
        }
    values = [[row.lap_ms for row in cell] for cell in cells]
    delta = _contrast(values, observed, weights)
    tail = sum(_contrast(values, assignment, weights) >= delta - 1e-8 for assignment in references)
    rng = random.Random(SEED + 2)
    # Resample complete sessions within period and stratum; interval is descriptive.
    draws = []
    for _ in range(TRIALS):
        effect = 0.0
        for cell, weight in zip(cells, weights, strict=True):
            earlier = [row.lap_ms for row in cell if not row.later]
            later = [row.lap_ms for row in cell if row.later]
            effect += weight * (
                mean(rng.choices(earlier, k=len(earlier))) - mean(rng.choices(later, k=len(later)))
            )
        draws.append(effect / sum(weights))
    quantile = quantiles(draws, n=40, method="inclusive")
    p_value = _p_value(tail, len(references), exact)
    return {
        "status": "estimated",
        "improvement_ms": delta,
        "session_bootstrap_interval_95_ms": [quantile[0], quantile[-1]],
        "one_sided_p_value": p_value,
        "improvement_detected": delta > 0 and p_value <= ALPHA,
        "calibration": calibration,
    }


def _project(
    snapshots: list[ArchiveQualificationSnapshot],
    combo: Combo,
    cutoff: datetime,
) -> tuple[dict[Stratum, list[Session]], dict, dict]:
    """Project the immutable lake inputs at one row per independent session."""
    import duckdb

    records = [snapshot.record for snapshot in snapshots]
    duplicates = duplicate_identity_reasons(records)
    timestamps: dict[str, set[bool | None]] = defaultdict(set)
    for record in records:
        uid = _text(record.get("session_uuid"))
        stamp = _record_time(record)
        if uid:
            timestamps[uid].add(None if stamp is None else stamp >= cutoff)
            lap_ms = _number(_mapping(record.get("lap")).get("lap_ms"))
            if stamp is not None and lap_ms is not None and lap_ms > 0:
                # Avoid assigning a lap that started just before the cutoff to the later period.
                timestamps[uid].add(stamp - cutoff >= timedelta(milliseconds=lap_ms))

    missing: Counter[str] = Counter()
    rejected: dict[str, set[str]] = defaultdict(set)
    projected = []
    for index, (snapshot, record) in enumerate(zip(snapshots, records, strict=True)):
        if archive_combo(record) != combo:
            continue
        uid = _text(record.get("session_uuid"))
        qualified = snapshot.qualify(use="human_progression", expected_combo=combo)
        traffic = archive_traffic_eligibility(record)
        if (
            not uid
            or index in duplicates
            or not qualified.allowed
            or qualified.authority != "human"
        ):
            rejected[uid].add(
                duplicates.get(index) or ("session_uuid_missing" if not uid else qualified.reason)
            )
            if traffic is None or traffic.status == "unknown":
                missing["traffic_eligibility"] += 1
            continue
        if len(timestamps[uid]) != 1 or None in timestamps[uid]:
            rejected[uid].add("session_spans_cutoff_or_has_missing_timestamp")
            continue
        condition, absent = _conditions(record, traffic is not None and traffic.eligible)
        if condition is None:
            missing.update(absent)
            rejected[uid].update(f"missing:{field}" for field in absent)
            continue
        lap_ms = _number(_mapping(record.get("lap")).get("lap_ms"))
        if lap_ms is None or lap_ms <= 0:
            rejected[uid].add("lap_ms_invalid")
            continue
        projected.append(
            (
                uid,
                next(iter(timestamps[uid])),
                list(condition.stratum),
                lap_ms,
                _nuisance(condition),
            )
        )

    cells: dict[Stratum, list[Session]] = defaultdict(list)
    if projected:
        # Choose the most-observed stratum per session before looking at the outcome.
        with duckdb.connect() as connection:
            connection.execute(
                "CREATE TABLE qualified (uid VARCHAR, later BOOLEAN, stratum VARCHAR[], "
                "lap_ms DOUBLE, nuisance_ms DOUBLE)"
            )
            connection.executemany("INSERT INTO qualified VALUES (?, ?, ?, ?, ?)", projected)
            rows = connection.execute(
                """
                SELECT uid, later, stratum, median(lap_ms), median(nuisance_ms)
                FROM qualified
                GROUP BY uid, later, stratum
                QUALIFY row_number() OVER (
                    PARTITION BY uid ORDER BY count(*) DESC, stratum
                ) = 1
                ORDER BY uid
                """
            ).fetchall()
        for uid, later, stratum, lap_ms, nuisance_ms in rows:
            cells[tuple(stratum)].append(Session(uid, later, lap_ms, nuisance_ms))
    return cells, dict(rejected), {name: missing[name] for name in DIMENSIONS}


def audit_archives(inputs: Iterable[str | Path], *, combo: Combo, split: date) -> dict:
    """Compare sessions entirely before/after a predeclared midnight UTC cutoff."""
    snapshots = []
    unreadable = []
    for path in sorted({path.resolve() for path in iter_lap_archive_paths(inputs)}):
        try:
            snapshots.append(load_lap_archive_snapshot(path))
        except (LapArchiveExportError, UnicodeError):
            unreadable.append(path.name)
    cutoff = datetime.combine(split, time.min, tzinfo=UTC)
    cells, rejected, missing = _project(snapshots, combo, cutoff)
    matched = []
    strata = []
    for key, cell in sorted(cells.items()):
        later = [row.uid for row in cell if row.later]
        earlier = [row.uid for row in cell if not row.later]
        reasons = [
            f"{period}_has_{len(sessions)}_sessions_minimum_{MIN_SESSIONS}"
            for period, sessions in (("earlier", earlier), ("later", later))
            if len(sessions) < MIN_SESSIONS
        ]
        if not reasons:
            matched.append(cell)
        strata.append(
            {
                "dimensions": dict(zip(DIMENSIONS, key, strict=True)),
                "earlier_sessions": earlier,
                "later_sessions": later,
                "excluded_reasons": reasons,
            }
        )
    verdict = _evaluate(matched)
    if not cells:
        verdict["reason"] = (
            "mandatory_confounders_missing"
            if any(
                reason.startswith("missing:") for reasons in rejected.values() for reason in reasons
            )
            else "no_complete_human_qualified_traffic_clean_sessions"
        )
    try:
        for snapshot in snapshots:
            snapshot.assert_current()
    except AttributionError as exc:
        return {"status": "cannot_identify", "reason": str(exc)}
    included = sorted(row.uid for cell in matched for row in cell)
    projected = {row.uid for cell in cells.values() for row in cell}
    matched_ids = set(included)
    return {
        "schema_version": 1,
        "combo": dict(zip(("car_id", "track_id", "layout"), combo, strict=True)),
        "split_utc": cutoff.isoformat(),
        "archive_count": len(snapshots),
        "unreadable_archives": unreadable,
        "missing_by_dimension": missing,
        "included_sessions": included,
        "excluded_sessions": {
            uid: sorted(
                rejected.get(uid, set()) | ({"unmatched_stratum"} if uid in projected else set())
            )
            for uid in sorted((set(rejected) | projected) - matched_ids)
        },
        "strata": strata,
        **verdict,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lap-dir", action="append", type=Path, required=True)
    parser.add_argument("--car", required=True)
    parser.add_argument("--track", required=True)
    parser.add_argument("--layout")
    parser.add_argument("--split", type=date.fromisoformat, required=True, help="UTC date")
    args = parser.parse_args(argv)
    combo = archive_combo(
        {"car": {"id": args.car}, "track": {"id": args.track, "layout": args.layout}}
    )
    if combo is None:
        parser.error("invalid car, track or layout combination")
    try:
        result = audit_archives(args.lap_dir, combo=combo, split=args.split)
    except (LapArchiveExportError, ImportError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
