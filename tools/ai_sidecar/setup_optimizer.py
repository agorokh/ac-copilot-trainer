"""Setup experiment store, A/B comparison, and deterministic next-setup suggestions.

The Lua app already writes rich per-lap archives under ``journal/laps``.  This
module turns those lap archives into a compact JSONL experiment table and keeps
all optimizer math stdlib-only so the default sidecar install stays lightweight.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from tools.ai_sidecar.car_schema import load_latest_schema

SCHEMA_VERSION = 1
DEFAULT_STORE_NAME = "experiments.jsonl"
DEFAULT_STORE_DIR = "setup_experiments"
MAX_TUNABLE_PARAMS = 6
MIN_EXPERIMENTS_FOR_SUGGESTION = 2

COMMON_PARAM_PRIORITY: tuple[str, ...] = (
    "FRONT_BIAS.VALUE",
    "BRAKE_POWER_MULT.VALUE",
    "ABS.VALUE",
    "TRACTION_CONTROL.VALUE",
    "WING_1.VALUE",
    "WING_2.VALUE",
    "ARB_FRONT.VALUE",
    "ARB_REAR.VALUE",
    "DIFF_POWER.VALUE",
    "DIFF_COAST.VALUE",
    "PRESSURE_LF.VALUE",
    "PRESSURE_RF.VALUE",
    "PRESSURE_LR.VALUE",
    "PRESSURE_RR.VALUE",
    "CAMBER_LF.VALUE",
    "CAMBER_RF.VALUE",
    "CAMBER_LR.VALUE",
    "CAMBER_RR.VALUE",
    "TOE_OUT_LF.VALUE",
    "TOE_OUT_RF.VALUE",
    "TOE_OUT_LR.VALUE",
    "TOE_OUT_RR.VALUE",
)


class SetupExperimentError(ValueError):
    """Raised when a lap archive cannot become a setup experiment."""


def _as_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _as_nonempty_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _path_text(path: str | os.PathLike[str] | None) -> str | None:
    if path is None:
        return None
    text = str(path).strip()
    return text or None


def _stable_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stable_hash(data: Any, *, length: int = 16) -> str:
    return hashlib.sha1(_stable_json(data).encode("utf-8")).hexdigest()[:length]


def _setup_name(setup: dict[str, Any]) -> str | None:
    path = _as_nonempty_str(setup.get("path"))
    if path:
        stem = Path(path.replace("\\", "/")).stem
        if stem:
            return stem
    snapshot = setup.get("snapshot")
    if isinstance(snapshot, dict):
        for key in ("NAME", "ABOUT.NAME"):
            name = _as_nonempty_str(snapshot.get(key))
            if name:
                return name
    return None


def _numeric_params(snapshot: Any) -> dict[str, float]:
    if not isinstance(snapshot, dict):
        return {}
    out: dict[str, float] = {}
    for raw_key, raw_value in sorted(snapshot.items(), key=lambda item: str(item[0])):
        key = str(raw_key)
        val = _as_finite_float(raw_value)
        if val is not None:
            out[key] = val
    return out


def _jsonable_conditions(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or value is None:
            out[str(key)] = value
        elif isinstance(value, str):
            out[str(key)] = value
        else:
            num = _as_finite_float(value)
            if num is not None:
                out[str(key)] = num
    return out


def default_store_path_for_lap(lap_path: str | os.PathLike[str]) -> Path:
    """Return the canonical experiment JSONL path for a lap archive path."""
    p = Path(lap_path)
    parts = [part.lower() for part in p.parts]
    if len(parts) >= 2 and parts[-2:] == ["laps", p.name.lower()]:
        journal_dir = p.parent.parent
        if journal_dir.name.lower() == "journal":
            return journal_dir / DEFAULT_STORE_DIR / DEFAULT_STORE_NAME
    return p.parent / DEFAULT_STORE_DIR / DEFAULT_STORE_NAME


def default_store_path_for_lap_dir(lap_dir: str | os.PathLike[str]) -> Path:
    p = Path(lap_dir)
    if p.name.lower() == "laps" and p.parent.name.lower() == "journal":
        return p.parent / DEFAULT_STORE_DIR / DEFAULT_STORE_NAME
    return p / DEFAULT_STORE_DIR / DEFAULT_STORE_NAME


def is_supported_lap_archive_path(path: str | os.PathLike[str]) -> bool:
    """Conservative guard for sidecar-triggered lap imports."""
    text = str(path).replace("\\", "/")
    low = text.lower()
    name = low.rsplit("/", 1)[-1]
    return "/journal/laps/" in low and name.startswith("lap_") and name.endswith(".json")


def is_supported_experiment_store_path(path: str | os.PathLike[str]) -> bool:
    """Conservative guard for Lua-registered setup experiment store paths."""
    low = str(path).replace("\\", "/").lower()
    suffix = "journal/setup_experiments/experiments.jsonl"
    return low == suffix or low.endswith("/" + suffix)


def load_lap_archive(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise SetupExperimentError(f"cannot read lap archive: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SetupExperimentError(
            f"invalid lap archive JSON: {exc.msg} at char {exc.pos}"
        ) from exc
    if not isinstance(data, dict):
        raise SetupExperimentError("lap archive root must be a JSON object")
    return data


def record_from_lap_archive(
    lap_archive: dict[str, Any],
    *,
    source_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(lap_archive, dict):
        raise SetupExperimentError("lap archive must be a JSON object")
    lap = lap_archive.get("lap")
    if not isinstance(lap, dict):
        raise SetupExperimentError("lap archive missing lap object")
    lap_ms = _as_finite_float(lap.get("lap_ms"))
    if lap_ms is None or lap_ms <= 0:
        raise SetupExperimentError("lap archive missing positive lap.lap_ms")

    setup = lap_archive.get("setup")
    if not isinstance(setup, dict):
        raise SetupExperimentError("lap archive missing setup object")
    snapshot = setup.get("snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        raise SetupExperimentError("lap archive missing setup.snapshot")

    setup_hash = _as_nonempty_str(setup.get("hash")) or _stable_hash(snapshot, length=12)
    params = _numeric_params(snapshot)
    if not params:
        raise SetupExperimentError("setup.snapshot has no numeric parameters")

    car = lap_archive.get("car") if isinstance(lap_archive.get("car"), dict) else {}
    track = lap_archive.get("track") if isinstance(lap_archive.get("track"), dict) else {}
    lap_uuid = _as_nonempty_str(lap_archive.get("lap_uuid"))
    source_text = _path_text(source_path)
    identity_seed = {
        "lap_uuid": lap_uuid,
        "source_path": source_text,
        "session_uuid": lap_archive.get("session_uuid"),
        "lap_n": lap.get("lap_n"),
        "lap_ms": lap_ms,
        "setup_hash": setup_hash,
    }
    experiment_id = lap_uuid or _stable_hash(identity_seed)

    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "source_lap_path": source_text,
        "source_lap_schema_version": lap_archive.get("schema_version"),
        "session_uuid": lap_archive.get("session_uuid"),
        "lap_uuid": lap_uuid,
        "exported_at": lap_archive.get("exported_at"),
        "car": {
            "id": _as_nonempty_str(car.get("id")) or "unknown",
            "displayName": car.get("displayName"),
        },
        "track": {
            "id": _as_nonempty_str(track.get("id")) or "unknown",
            "layout": track.get("layout"),
            "lengthM": _as_finite_float(track.get("lengthM")),
        },
        "conditions": _jsonable_conditions(lap_archive.get("conditions")),
        "lap": {
            "lap_n": int(_as_finite_float(lap.get("lap_n")) or 0),
            "lap_ms": int(round(lap_ms)),
            "is_pb": lap.get("is_pb") is True,
            "is_valid": lap.get("is_valid") is not False,
        },
        "setup": {
            "hash": setup_hash,
            "name": _setup_name(setup),
            "path": _as_nonempty_str(setup.get("path")),
            "params": params,
            "param_count": len(params),
        },
    }


def load_records(store_path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    path = Path(store_path)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as e:
                raise SetupExperimentError(
                    f"invalid experiment store JSON at {path}:{line_no}: {e.msg}"
                ) from e
            if not isinstance(item, dict):
                raise SetupExperimentError(
                    f"invalid experiment store record at {path}:{line_no}: expected object"
                )
            out.append(item)
    return out


def save_records(records: list[dict[str, Any]], store_path: str | os.PathLike[str]) -> None:
    path = Path(store_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records_sorted = sorted(
        records,
        key=lambda r: (
            str(r.get("car", {}).get("id", "")),
            str(r.get("track", {}).get("id", "")),
            str(r.get("exported_at") or ""),
            str(r.get("experiment_id") or ""),
        ),
    )
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records_sorted:
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")))
            fh.write("\n")
    tmp.replace(path)


def upsert_records(
    records: list[dict[str, Any]],
    store_path: str | os.PathLike[str],
) -> tuple[int, int]:
    existing = load_records(store_path)
    by_id: dict[str, dict[str, Any]] = {}
    for rec in existing:
        rid = _as_nonempty_str(rec.get("experiment_id"))
        if rid:
            by_id[rid] = rec
    inserted = 0
    updated = 0
    for rec in records:
        rid = _as_nonempty_str(rec.get("experiment_id"))
        if not rid:
            continue
        if rid in by_id:
            updated += 1
        else:
            inserted += 1
        by_id[rid] = rec
    save_records(list(by_id.values()), store_path)
    return inserted, updated


def record_lap_archive(
    lap_path: str | os.PathLike[str],
    *,
    store_path: str | os.PathLike[str] | None = None,
    require_safe_path: bool = False,
) -> dict[str, Any]:
    if require_safe_path and not is_supported_lap_archive_path(lap_path):
        raise SetupExperimentError("archive_path must point under journal/laps/lap_*.json")
    lap = load_lap_archive(lap_path)
    rec = record_from_lap_archive(lap, source_path=lap_path)
    store = Path(store_path) if store_path is not None else default_store_path_for_lap(lap_path)
    inserted, updated = upsert_records([rec], store)
    return {
        "ok": True,
        "store_path": str(store),
        "experiment_id": rec["experiment_id"],
        "setup_hash": rec["setup"]["hash"],
        "lap_ms": rec["lap"]["lap_ms"],
        "inserted": inserted,
        "updated": updated,
    }


def rebuild_experiments(
    lap_dir: str | os.PathLike[str],
    *,
    store_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    root = Path(lap_dir)
    store = Path(store_path) if store_path is not None else default_store_path_for_lap_dir(root)
    if not root.is_dir():
        raise SetupExperimentError(f"lap_dir must be an existing directory: {root}")
    by_id: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(root.glob("lap_*.json")):
        try:
            rec = record_from_lap_archive(load_lap_archive(path), source_path=path)
        except SetupExperimentError as exc:
            skipped.append({"path": str(path), "error": str(exc)})
            continue
        rid = _as_nonempty_str(rec.get("experiment_id"))
        if rid is None:
            skipped.append({"path": str(path), "error": "missing experiment_id"})
            continue
        if rid in by_id:
            duplicates.append({"path": str(path), "experiment_id": rid})
        by_id[rid] = rec
    records = list(by_id.values())
    save_records(records, store)
    return {
        "ok": True,
        "store_path": str(store),
        "records": len(records),
        "duplicates": duplicates,
        "skipped": skipped,
    }


def _setup_identifiers(record: dict[str, Any]) -> set[str]:
    setup = record.get("setup")
    if not isinstance(setup, dict):
        return set()
    out = set()
    for key in ("hash", "name", "path"):
        value = _as_nonempty_str(setup.get(key))
        if value:
            out.add(value)
            out.add(value.lower())
            out.add(value.replace("\\", "/").lower())
            if key == "path":
                stem = Path(value.replace("\\", "/")).stem
                if stem:
                    out.add(stem)
                    out.add(stem.lower())
    return out


def _matches_setup(record: dict[str, Any], ident: str) -> bool:
    raw = ident.strip()
    if not raw:
        return False
    keys = {raw, raw.lower(), raw.replace("\\", "/").lower()}
    return bool(_setup_identifiers(record) & keys)


def _valid_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for rec in records:
        lap = rec.get("lap")
        setup = rec.get("setup")
        if not isinstance(lap, dict) or not isinstance(setup, dict):
            continue
        lap_ms = _as_finite_float(lap.get("lap_ms"))
        if lap_ms is None or lap_ms <= 0:
            continue
        if lap.get("is_valid") is False:
            continue
        if not isinstance(setup.get("params"), dict) or not setup.get("params"):
            continue
        out.append(rec)
    return out


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sample_variance(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def compare_setups(
    records: list[dict[str, Any]],
    *,
    baseline_setup: str,
    candidate_setup: str,
    alpha: float = 0.05,
) -> dict[str, Any]:
    valid = _valid_records(records)
    baseline = [float(rec["lap"]["lap_ms"]) for rec in valid if _matches_setup(rec, baseline_setup)]
    candidate = [
        float(rec["lap"]["lap_ms"]) for rec in valid if _matches_setup(rec, candidate_setup)
    ]
    if not baseline or not candidate:
        return {
            "ok": False,
            "error": "both baseline_setup and candidate_setup need at least one valid lap",
            "baseline_n": len(baseline),
            "candidate_n": len(candidate),
        }

    b_mean = _mean(baseline)
    c_mean = _mean(candidate)
    b_var = _sample_variance(baseline, b_mean)
    c_var = _sample_variance(candidate, c_mean)
    improvement_ms = b_mean - c_mean
    se = math.sqrt((b_var / len(baseline)) + (c_var / len(candidate)))
    confidence = 0.5
    p_value = None
    z_score = None
    if se > 0:
        z_score = improvement_ms / se
        confidence = _normal_cdf(z_score)
        p_value = 1.0 - confidence
    elif len(baseline) >= 2 and len(candidate) >= 2 and improvement_ms != 0:
        confidence = 1.0 if improvement_ms > 0 else 0.0
        p_value = 0.0 if improvement_ms > 0 else 1.0
    significant = confidence >= (1.0 - alpha) and improvement_ms > 0

    return {
        "ok": True,
        "baseline_setup": baseline_setup,
        "candidate_setup": candidate_setup,
        "baseline": {
            "n": len(baseline),
            "mean_ms": round(b_mean, 3),
            "stdev_ms": round(math.sqrt(b_var), 3),
        },
        "candidate": {
            "n": len(candidate),
            "mean_ms": round(c_mean, 3),
            "stdev_ms": round(math.sqrt(c_var), 3),
        },
        "improvement_ms": round(improvement_ms, 3),
        "improvement_pct": round((improvement_ms / b_mean) * 100.0, 4),
        "confidence": round(confidence, 4),
        "p_value_one_sided": None if p_value is None else round(p_value, 6),
        "z_score": None if z_score is None else round(z_score, 4),
        "significant": significant,
        "method": "welch_normal_approximation",
    }


def _filter_records(
    records: list[dict[str, Any]],
    *,
    car_id: str | None = None,
    track_id: str | None = None,
) -> list[dict[str, Any]]:
    valid = _valid_records(records)
    if car_id:
        valid = [r for r in valid if r.get("car", {}).get("id") == car_id]
    if track_id:
        valid = [r for r in valid if r.get("track", {}).get("id") == track_id]
    return valid


def _scope_ids(records: list[dict[str, Any]], group: str) -> list[str]:
    ids: set[str] = set()
    for rec in records:
        obj = rec.get(group) if isinstance(rec.get(group), dict) else {}
        value = obj.get("id")
        if isinstance(value, str) and value.strip() and value.strip().lower() != "unknown":
            ids.add(value.strip())
    return sorted(ids)


def _infer_closed_loop_scope(
    records: list[dict[str, Any]],
    *,
    car_id: str | None,
    track_id: str | None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    effective_car_id = car_id
    valid = _valid_records(records)
    track_scoped = _filter_records(valid, track_id=track_id)
    if effective_car_id is None:
        car_ids = _scope_ids(track_scoped, "car")
        if len(car_ids) > 1:
            return (
                None,
                None,
                {
                    "ok": False,
                    "status": "ambiguous_scope",
                    "scope": "car_id",
                    "car_ids": car_ids,
                    "error": "setup.closed_loop requires a single car scope",
                },
            )
        if len(car_ids) == 1:
            effective_car_id = car_ids[0]

    car_scoped = _filter_records(valid, car_id=effective_car_id)
    effective_track_id = track_id
    if effective_track_id is None:
        track_ids = _scope_ids(car_scoped, "track")
        if len(track_ids) > 1:
            return (
                effective_car_id,
                None,
                {
                    "ok": False,
                    "status": "ambiguous_scope",
                    "scope": "track_id",
                    "car_id": effective_car_id,
                    "track_ids": track_ids,
                    "error": "setup.closed_loop requires a single track scope",
                },
            )
        if len(track_ids) == 1:
            effective_track_id = track_ids[0]
    return effective_car_id, effective_track_id, None


def _select_params(records: list[dict[str, Any]], best: dict[str, Any]) -> list[str]:
    best_params = best["setup"]["params"]
    all_keys = {key for rec in records for key in rec["setup"]["params"]}
    varied: set[str] = set()
    for key in all_keys:
        vals = {_as_finite_float(rec["setup"]["params"].get(key)) for rec in records}
        vals.discard(None)
        if len(vals) > 1:
            varied.add(key)
    priority = {key: i for i, key in enumerate(COMMON_PARAM_PRIORITY)}
    ranked = sorted(
        [key for key in best_params if key in all_keys],
        key=lambda key: (
            0 if key in varied else 1,
            priority.get(key, len(priority)),
            key,
        ),
    )
    return ranked[:MAX_TUNABLE_PARAMS]


def _param_step(records: list[dict[str, Any]], key: str) -> float:
    vals = sorted(
        {
            v
            for rec in records
            if (v := _as_finite_float(rec["setup"]["params"].get(key))) is not None
        }
    )
    diffs = [b - a for a, b in zip(vals, vals[1:], strict=False) if b > a]
    if diffs:
        return max(min(diffs), 1.0 if all(float(v).is_integer() for v in vals) else 0.01)
    return 1.0


def _candidate_value(records: list[dict[str, Any]], key: str, value: float) -> float:
    observed = [
        v for rec in records if (v := _as_finite_float(rec["setup"]["params"].get(key))) is not None
    ]
    if observed and min(observed) >= 0 and value < 0:
        return 0.0
    return value


def _normalize_param_key(param: str) -> str:
    text = param.strip().upper()
    if not text:
        raise SetupExperimentError("param is required")
    return text if text.endswith(".VALUE") else f"{text}.VALUE"


def _candidate_grid(
    records: list[dict[str, Any]], best: dict[str, Any], keys: list[str]
) -> list[dict[str, float]]:
    base = {key: float(best["setup"]["params"][key]) for key in keys}
    candidates: dict[str, dict[str, float]] = {}

    def add(params: dict[str, float]) -> None:
        frozen = tuple((key, round(params[key], 6)) for key in keys)
        candidates[str(frozen)] = dict(params)

    for key in keys:
        step = _param_step(records, key)
        for sign in (-1.0, 1.0):
            nxt = dict(base)
            nxt[key] = _candidate_value(records, key, base[key] + sign * step)
            add(nxt)

    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1 :]:
            step_a = _param_step(records, key_a)
            step_b = _param_step(records, key_b)
            for sign_a, sign_b in ((-1.0, -1.0), (-1.0, 1.0), (1.0, -1.0), (1.0, 1.0)):
                nxt = dict(base)
                nxt[key_a] = _candidate_value(records, key_a, base[key_a] + sign_a * step_a)
                nxt[key_b] = _candidate_value(records, key_b, base[key_b] + sign_b * step_b)
                add(nxt)
    return list(candidates.values())


def _distance(a: dict[str, float], b: dict[str, float], ranges: dict[str, float]) -> float:
    total = 0.0
    for key, scale in ranges.items():
        total += ((a[key] - b[key]) / scale) ** 2
    return math.sqrt(total)


def _expected_improvement(best_y: float, mu: float, sigma: float) -> float:
    if sigma <= 1e-9:
        return max(best_y - mu, 0.0)
    z = (best_y - mu) / sigma
    phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return (best_y - mu) * _normal_cdf(z) + sigma * phi


def _schema_allows(
    candidate: dict[str, float], schema: Any, *, base: dict[str, float] | None = None
) -> bool:
    """True iff every candidate knob is in-range/on-step per a CarSetupSchema (duck-typed)."""
    spinners = getattr(schema, "spinners", None)
    if not isinstance(spinners, dict):
        return True
    for key, val in candidate.items():
        name = key[:-6] if key.endswith(".VALUE") else key
        sp = spinners.get(name)
        if sp is None:
            continue
        if getattr(sp, "read_only", False):
            if base is not None and key in base and abs(float(val) - float(base[key])) <= 1e-9:
                continue
            return False
        if not sp.is_valid(val):
            return False
    return True


def _chronological_key(record: dict[str, Any]) -> tuple[str, str, int, str]:
    lap = record.get("lap") if isinstance(record.get("lap"), dict) else {}
    return (
        str(record.get("exported_at") or ""),
        str(record.get("session_uuid") or ""),
        int(_as_finite_float(lap.get("lap_n")) or 0),
        str(record.get("experiment_id") or ""),
    )


def _finite_setup_params(record: dict[str, Any]) -> dict[str, float]:
    setup = record.get("setup") if isinstance(record.get("setup"), dict) else {}
    params = setup.get("params") if isinstance(setup.get("params"), dict) else {}
    out: dict[str, float] = {}
    for raw_key, value in params.items():
        val = _as_finite_float(value)
        if val is not None:
            out[_normalize_param_key(str(raw_key))] = val
    return out


def _changed_param_keys(
    prev_params: dict[str, float],
    curr_params: dict[str, float],
) -> list[str]:
    changed: list[str] = []
    for key in sorted(set(prev_params) | set(curr_params)):
        before = prev_params.get(key)
        after = curr_params.get(key)
        if before is None or after is None or abs(after - before) > 1e-9:
            changed.append(key)
    return changed


def _latest_param_changed_pair(
    ordered: list[dict[str, Any]], key: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for idx in range(len(ordered) - 1, 0, -1):
        prev = ordered[idx - 1]
        curr = ordered[idx]
        prev_params = _finite_setup_params(prev)
        curr_params = _finite_setup_params(curr)
        prev_value = prev_params.get(key)
        curr_value = curr_params.get(key)
        if prev_value is None or curr_value is None:
            continue
        if abs(curr_value - prev_value) > 1e-9:
            return prev, curr
    return None


def suggest_closed_loop(
    records: list[dict[str, Any]],
    *,
    param: str,
    car_id: str | None = None,
    track_id: str | None = None,
    schema: Any = None,
) -> dict[str, Any]:
    """Suggest the next one-parameter move from the measured previous move.

    This is deliberately simple and auditable: compare the latest two valid laps
    where ``param`` exists, measure whether the previous value change improved
    lap time, then continue in the same direction or reverse by one observed
    step.  The broader surrogate optimizer remains available for exploratory
    multi-param moves; this function is the closed suggest -> test -> measure
    loop a driver can reason about at the rig.
    """

    key = _normalize_param_key(param)
    effective_car_id, effective_track_id, scope_error = _infer_closed_loop_scope(
        records,
        car_id=car_id,
        track_id=track_id,
    )
    if scope_error is not None:
        return {
            **scope_error,
            "param": key,
            "experiments_used": len(_valid_records(records)),
        }
    if schema is None:
        schema = load_latest_schema(effective_car_id)
    scoped = _filter_records(records, car_id=effective_car_id, track_id=effective_track_id)
    complete = [
        rec
        for rec in scoped
        if _as_finite_float(rec.get("setup", {}).get("params", {}).get(key)) is not None
    ]
    if len(complete) < 2:
        return {
            "ok": False,
            "status": "not_enough_param_experiments",
            "param": key,
            "experiments_used": len(complete),
            "min_required": 2,
        }
    ordered = sorted(complete, key=_chronological_key)
    pair = _latest_param_changed_pair(ordered, key)
    if pair is None:
        prev, curr = ordered[-2], ordered[-1]
    else:
        prev, curr = pair
    prev_params = _finite_setup_params(prev)
    curr_params = _finite_setup_params(curr)
    prev_value = prev_params[key]
    curr_value = curr_params[key]
    prev_lap_ms = float(prev["lap"]["lap_ms"])
    curr_lap_ms = float(curr["lap"]["lap_ms"])
    value_delta = curr_value - prev_value
    measured_delta_ms = prev_lap_ms - curr_lap_ms
    previous_result = {
        "from": prev_value,
        "to": curr_value,
        "delta": round(value_delta, 6),
        "lap_ms_before": int(round(prev_lap_ms)),
        "lap_ms_after": int(round(curr_lap_ms)),
        "measured_delta_ms": round(measured_delta_ms, 3),
    }
    changed_keys = _changed_param_keys(prev_params, curr_params)
    if pair is None:
        return {
            "ok": False,
            "status": "latest_laps_did_not_change_param",
            "param": key,
            "experiments_used": len(complete),
            "changed_params": changed_keys,
            "previous_result": previous_result,
        }
    if changed_keys != [key]:
        return {
            "ok": False,
            "status": "latest_pair_changed_multiple_params",
            "param": key,
            "experiments_used": len(complete),
            "changed_params": changed_keys,
            "previous_result": previous_result,
        }
    if abs(measured_delta_ms) <= 1e-9:
        return {
            "ok": False,
            "status": "inconclusive_no_lap_delta",
            "param": key,
            "experiments_used": len(complete),
            "previous_result": {
                **previous_result,
                "improved": False,
            },
        }

    step = _param_step(scoped, key)
    previous_direction = 1.0 if value_delta > 0 else -1.0
    next_direction = previous_direction if measured_delta_ms > 0 else -previous_direction
    raw_target = _candidate_value(scoped, key, curr_value + next_direction * step)
    candidate = {key: raw_target}
    if schema is not None and hasattr(schema, "constrain_params"):
        candidate = schema.constrain_params(candidate)
    target_value = float(candidate[key])
    if schema is not None and not _schema_allows(candidate, schema, base={key: curr_value}):
        return {
            "ok": False,
            "status": "candidate_out_of_schema",
            "param": key,
            "candidate": candidate,
            "previous_result": {
                **previous_result,
            },
        }
    if abs(target_value - curr_value) <= 1e-9:
        return {
            "ok": False,
            "status": "at_param_bound",
            "param": key,
            "experiments_used": len(complete),
            "current": curr_value,
            "previous_result": {
                **previous_result,
                "improved": measured_delta_ms > 0,
            },
        }

    improved = measured_delta_ms > 0
    direction_word = "continue" if improved else "reverse"
    change = {"from": curr_value, "to": target_value}
    return {
        "ok": True,
        "status": "suggested",
        "method": "one_param_measured_delta",
        "param": key,
        "experiments_used": len(complete),
        "previous_result": {
            **previous_result,
            "improved": improved,
        },
        "candidate": {
            "params": {key: target_value},
            "changed_params": {key: change},
        },
        "rationale": [
            (
                f"Previous {key} move {'improved' if improved else 'hurt'} lap time by "
                f"{abs(measured_delta_ms):.0f} ms."
            ),
            f"Next suggestion: {direction_word} that one-parameter direction by one step.",
        ],
    }


def suggest_next_setup(
    records: list[dict[str, Any]],
    *,
    car_id: str | None = None,
    track_id: str | None = None,
    schema: Any = None,
) -> dict[str, Any]:
    scoped = _filter_records(records, car_id=car_id, track_id=track_id)
    if len(scoped) < MIN_EXPERIMENTS_FOR_SUGGESTION:
        return {
            "ok": False,
            "status": "not_enough_experiments",
            "experiments_used": len(scoped),
            "min_required": MIN_EXPERIMENTS_FOR_SUGGESTION,
        }
    best = min(scoped, key=lambda rec: float(rec["lap"]["lap_ms"]))
    keys = _select_params(scoped, best)
    if not keys:
        return {"ok": False, "status": "no_tunable_numeric_params", "experiments_used": len(scoped)}

    vectors = []
    for rec in scoped:
        params = rec["setup"]["params"]
        if all(_as_finite_float(params.get(key)) is not None for key in keys):
            vectors.append(
                (
                    {key: float(params[key]) for key in keys},
                    float(rec["lap"]["lap_ms"]),
                    rec,
                )
            )
    if len(vectors) < MIN_EXPERIMENTS_FOR_SUGGESTION:
        return {
            "ok": False,
            "status": "not_enough_complete_param_vectors",
            "experiments_used": len(vectors),
        }

    ranges: dict[str, float] = {}
    for key in keys:
        vals = [vec[0][key] for vec in vectors]
        ranges[key] = max(max(vals) - min(vals), _param_step(scoped, key), 1.0)
    global_mean = _mean([y for _, y, _ in vectors])
    global_var = _sample_variance([y for _, y, _ in vectors], global_mean)
    global_std = max(math.sqrt(global_var), 1.0)
    best_y = float(best["lap"]["lap_ms"])
    base_params = {key: float(best["setup"]["params"][key]) for key in keys}
    observed = {tuple((key, round(vec[key], 6)) for key in keys) for vec, _, _ in vectors}

    scored = []
    seen_candidates: set[tuple[tuple[str, float], ...]] = set()
    for raw_candidate in _candidate_grid(scoped, best, keys):
        candidate = (
            schema.constrain_params(raw_candidate)
            if schema is not None and hasattr(schema, "constrain_params")
            else raw_candidate
        )
        frozen = tuple((key, round(candidate[key], 6)) for key in keys)
        if frozen in observed:
            continue
        if frozen in seen_candidates:
            continue
        seen_candidates.add(frozen)
        if schema is not None and not _schema_allows(candidate, schema, base=base_params):
            continue
        weights = []
        for vec, lap_ms, _ in vectors:
            d = _distance(candidate, vec, ranges)
            weights.append((math.exp(-0.5 * d * d), lap_ms))
        weight_sum = sum(w for w, _ in weights)
        if weight_sum <= 1e-9:
            mu = global_mean
            sigma = global_std
        else:
            mu = sum(w * y for w, y in weights) / weight_sum
            local_var = sum(w * (y - mu) ** 2 for w, y in weights) / weight_sum
            novelty = 1.0 / math.sqrt(1.0 + weight_sum)
            sigma = math.sqrt(max(local_var, 0.0) + (global_std * novelty) ** 2)
        ei = _expected_improvement(best_y, mu, sigma)
        scored.append((ei, mu, sigma, candidate))
    if not scored:
        return {"ok": False, "status": "no_untried_candidate", "experiments_used": len(vectors)}

    ei, mu, sigma, candidate = max(scored, key=lambda item: (item[0], -item[1]))
    changed = {
        key: {"from": base_params[key], "to": candidate[key]}
        for key in keys
        if abs(candidate[key] - base_params[key]) > 1e-9
    }
    return {
        "ok": True,
        "status": "suggested",
        "method": "rbf_surrogate_expected_improvement",
        "experiments_used": len(vectors),
        "base_setup": {
            "hash": best["setup"]["hash"],
            "name": best["setup"].get("name"),
            "path": best["setup"].get("path"),
            "lap_ms": best["lap"]["lap_ms"],
        },
        "candidate": {
            "params": candidate,
            "changed_params": changed,
        },
        "surrogate": {
            "predicted_lap_ms": round(mu, 3),
            "uncertainty_ms": round(sigma, 3),
            "expected_improvement_ms": round(ei, 3),
            "best_observed_lap_ms": int(round(best_y)),
            "tunable_params": keys,
        },
        "rationale": [
            f"Best observed setup {best['setup']['hash']} ran {int(round(best_y))} ms.",
            "Candidates are one- or two-parameter moves around that setup.",
            "The selected move maximizes expected improvement under a Gaussian-kernel surrogate.",
        ],
    }
