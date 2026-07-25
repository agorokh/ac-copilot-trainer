"""Evidence-gated setup scientist for the alien self-play pipeline (#529 P4 / #674 META).

The scientist proposes physical hypotheses; deterministic code validates the proposal, creates
one-parameter setup candidates, and judges measured batches.  Model prose never writes a setup.
Durable records live under Assetto Corsa Documents and suppress already-falsified constraints for
the same META scope (mechanical × aero × tyre family × track archetype). Cross-combo transfer
reuses that single ``scope_key`` ledger — never a second prior store (#674).
"""

from __future__ import annotations

import configparser
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.ai_sidecar.car_schema import CarSetupSchema
from tools.ai_sidecar.setup_optimizer import (
    SetupExperimentError,
    compare_setups,
    record_from_lap_archive,
)

SCHEMA_VERSION = 1
MAX_HYPOTHESES = 3
MAX_BATCH_SIZE = 3
STATE_DIR = Path("journal") / "alien_scientist"
LEDGER_NAME = "experiments.jsonl"
_HYPOTHESIS_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_UTC_STAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")


class ScientistError(ValueError):
    """A scientist plan or experiment is unsafe or unverifiable."""


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any, *, length: int = 16) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()[:length]


def state_root(user_dir: str | Path) -> Path:
    """Canonical scientist state root below the operator's AC Documents directory."""
    return Path(user_dir) / STATE_DIR


def ensure_state_root(user_dir: str | Path) -> Path:
    """Create the state root while refusing symlinks/junctions below AC Documents."""
    try:
        base = Path(user_dir).resolve(strict=True)
    except OSError as exc:
        raise ScientistError("scientist_user_dir_unavailable") from exc
    if not base.is_dir():
        raise ScientistError("scientist_user_dir_unavailable")
    current = base
    for part in STATE_DIR.parts:
        child = current / part
        try:
            child.mkdir()
        except FileExistsError:
            pass
        except OSError as exc:
            raise ScientistError("scientist_state_path_unavailable") from exc
        try:
            if child.is_symlink() or not child.is_dir() or child.resolve(strict=True) != child:
                raise ScientistError("scientist_state_path_unsafe")
        except OSError as exc:
            raise ScientistError("scientist_state_path_unsafe") from exc
        current = child
    return current


def _validate_state_destination(path: Path, allowed_root: Path | None = None) -> Path:
    """Return an absolute state path only when no existing component redirects elsewhere."""
    logical = Path(os.path.abspath(path))
    boundary = Path(os.path.abspath(allowed_root or logical.parent))
    try:
        resolved_boundary = boundary.resolve(strict=True)
        resolved_parent = logical.parent.resolve(strict=True)
        resolved_parent.relative_to(resolved_boundary)
    except (OSError, ValueError) as exc:
        raise ScientistError("scientist_state_path_unsafe") from exc
    if (
        resolved_boundary != boundary
        or resolved_parent != logical.parent
        or not logical.parent.is_dir()
    ):
        raise ScientistError("scientist_state_path_unsafe")
    if logical.is_symlink():
        raise ScientistError("scientist_state_path_unsafe")
    if logical.exists():
        try:
            if not logical.is_file() or logical.resolve(strict=True) != logical:
                raise ScientistError("scientist_state_path_unsafe")
        except OSError as exc:
            raise ScientistError("scientist_state_path_unsafe") from exc
    return logical


def normalized_scope(scope: Mapping[str, Any]) -> dict[str, str]:
    """Validate and normalize the four META dimensions used for prior transfer."""
    required = ("mechanical_platform", "aero_platform", "tyre_family", "track_archetype")
    normalized: dict[str, str] = {}
    for key in required:
        value = str(scope.get(key) or "").strip()
        if not value or len(value) > 128:
            raise ScientistError(f"scientist_scope_missing_{key}")
        normalized[key] = value
    return normalized


def scope_key(scope: Mapping[str, Any]) -> str:
    """Digest of the four META dimensions — the single key for same-scope and cross-combo priors."""
    return _digest(normalized_scope(scope))


def _combo_identity(combo: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(combo, Mapping):
        return None
    car = str(combo.get("car") or "").strip()
    track = str(combo.get("track") or "").strip()
    if not car or not track:
        return None
    layout = combo.get("layout")
    if layout is not None:
        layout = str(layout).strip() or None
    return {"car": car, "track": track, "layout": layout}


def meta_priors(
    ledger: Sequence[Mapping[str, Any]],
    *,
    scope: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Falsified qualitative constraints transferable to any combo sharing ``scope``'s META key.

    Legacy ledger rows that only carry ``scope_key`` remain usable; newer rows may also carry
    ``scope`` / ``combo`` for provenance. One bookkeeping store — the experiments ledger.
    """
    scoped = scope_key(scope)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ledger:
        if row.get("scope_key") != scoped or row.get("verdict") != "falsified":
            continue
        constraint = str(row.get("constraint_key") or "")
        if not constraint or constraint in seen:
            continue
        seen.add(constraint)
        source_combo = _combo_identity(row.get("combo") if isinstance(row.get("combo"), Mapping) else None)
        out.append(
            {
                "constraint_key": constraint,
                "scope_key": scoped,
                "source_experiment_id": row.get("experiment_id"),
                "source_combo": source_combo,
                "reason": row.get("reason"),
            }
        )
    return out


def _transfer_mode(
    *,
    plan_combo: Mapping[str, Any] | None,
    source_combo: Mapping[str, Any] | None,
) -> str:
    plan_id = _combo_identity(plan_combo)
    source_id = _combo_identity(source_combo)
    if plan_id is None or source_id is None:
        return "same_scope"
    if plan_id == source_id:
        return "same_scope"
    return "cross_combo"


def load_ledger(
    path: str | Path, *, allowed_root: str | Path | None = None
) -> list[dict[str, Any]]:
    ledger = Path(path)
    if not ledger.exists():
        return []
    ledger = _validate_state_destination(
        ledger, Path(allowed_root) if allowed_root is not None else None
    )
    rows: list[dict[str, Any]] = []
    try:
        with ledger.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ScientistError(f"scientist_ledger_invalid_json_line_{line_no}") from exc
                if not isinstance(row, dict):
                    raise ScientistError(f"scientist_ledger_invalid_record_line_{line_no}")
                rows.append(row)
    except (OSError, UnicodeError) as exc:
        raise ScientistError("scientist_ledger_unreadable") from exc
    return rows


def _exclusive_write_text(path: Path, text: str, *, allowed_root: Path) -> None:
    """Publish a new immutable artifact without replacing an existing peer artifact."""
    path = _validate_state_destination(path, allowed_root)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise ScientistError("scientist_run_already_exists") from None
        tmp.unlink()
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def append_ledger(
    path: str | Path,
    row: Mapping[str, Any],
    *,
    allowed_root: str | Path | None = None,
) -> None:
    """Append one completed experiment without rewriting peer/manual history."""
    boundary = Path(allowed_root) if allowed_root is not None else None
    ledger = _validate_state_destination(Path(path), boundary)
    rows = load_ledger(ledger, allowed_root=boundary)
    experiment_id = str(row.get("experiment_id") or "")
    if not experiment_id:
        raise ScientistError("scientist_experiment_id_missing")
    if any(str(existing.get("experiment_id") or "") == experiment_id for existing in rows):
        raise ScientistError("scientist_experiment_already_recorded")
    data = (_stable_json(dict(row)) + "\n").encode("utf-8")
    try:
        fd = os.open(ledger, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ScientistError("scientist_ledger_append_failed") from exc


def _normalized_params(payload: Mapping[str, Any]) -> dict[str, float]:
    setup = payload.get("setup") if isinstance(payload.get("setup"), Mapping) else {}
    snapshot = setup.get("snapshot") if isinstance(setup.get("snapshot"), Mapping) else {}
    params: dict[str, float] = {}
    for raw_key, raw_value in snapshot.items():
        value = _finite(raw_value)
        if value is not None:
            key = str(raw_key).strip().upper()
            params[key if key.endswith(".VALUE") else f"{key}.VALUE"] = value
    return params


def _default_hypotheses(trigger: str) -> list[dict[str, Any]]:
    text = trigger.lower()
    if "brak" in text or "entry" in text:
        return [
            {
                "id": "braking_stability_front_bias",
                "mechanism": "braking instability may respond to a one-click front-bias change",
                "parameter": "FRONT_BIAS.VALUE",
                "direction": 1,
            }
        ]
    if "spin" in text or "oversteer" in text or "exit" in text:
        return [
            {
                "id": "exit_stability_diff_power",
                "mechanism": "power-exit instability may respond to one click of diff power",
                "parameter": "DIFF_POWER.VALUE",
                "direction": -1,
            }
        ]
    if "understeer" in text:
        return [
            {
                "id": "rotation_arb_front",
                "mechanism": "persistent understeer may respond to one click less front ARB",
                "parameter": "ARB_FRONT.VALUE",
                "direction": -1,
            }
        ]
    return [
        {
            "id": "plateau_rear_wing",
            "mechanism": "a pace plateau may respond to one click less rear wing",
            "parameter": "WING_2.VALUE",
            "direction": -1,
        }
    ]


def build_plan(
    *,
    trigger: str,
    combo: Mapping[str, Any],
    scope: Mapping[str, Any],
    baseline_payloads: Sequence[Mapping[str, Any]],
    schema: CarSetupSchema,
    ledger: Sequence[Mapping[str, Any]] = (),
    proposed_hypotheses: Sequence[Mapping[str, Any]] | None = None,
    batch_size: int = 1,
) -> dict[str, Any]:
    """Validate scientist prose and produce bounded, schema-valid one-parameter experiments."""
    named_trigger = str(trigger or "").strip()
    if not named_trigger:
        raise ScientistError("scientist_trigger_missing")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ScientistError("scientist_batch_size_out_of_range")
    if not baseline_payloads:
        raise ScientistError("scientist_baseline_missing")
    baseline_params = _normalized_params(baseline_payloads[0])
    if not baseline_params:
        raise ScientistError("scientist_baseline_setup_missing")
    for payload in baseline_payloads[1:]:
        if _normalized_params(payload) != baseline_params:
            raise ScientistError("scientist_baseline_setup_confounded")

    explicit_proposals = proposed_hypotheses is not None
    raw = list(proposed_hypotheses if explicit_proposals else _default_hypotheses(named_trigger))
    if not raw or len(raw) > MAX_HYPOTHESES:
        raise ScientistError("scientist_hypothesis_count_out_of_range")
    scope_norm = normalized_scope(scope)
    scoped = scope_key(scope_norm)
    plan_combo = _combo_identity(combo) or dict(combo)
    priors = meta_priors(ledger, scope=scope_norm)
    prior_by_constraint = {str(row["constraint_key"]): row for row in priors}
    hypotheses: list[dict[str, Any]] = []
    experiments: list[dict[str, Any]] = []
    suppressed_rows: list[dict[str, Any]] = []
    seen_constraints: set[str] = set()
    for proposal in raw:
        hypothesis_id = str(proposal.get("id") or "").strip()
        mechanism = str(proposal.get("mechanism") or "").strip()
        parameter = str(proposal.get("parameter") or "").strip().upper()
        if parameter and not parameter.endswith(".VALUE"):
            parameter += ".VALUE"
        direction = _finite(proposal.get("direction"))
        if (
            not _HYPOTHESIS_ID_RE.fullmatch(hypothesis_id)
            or not mechanism
            or len(mechanism) > 240
            or not parameter
            or len(parameter) > 80
            or direction not in (-1.0, 1.0)
        ):
            raise ScientistError("scientist_hypothesis_malformed")
        constraint_key = _digest({"parameter": parameter, "direction": direction})
        if constraint_key in seen_constraints:
            raise ScientistError("scientist_hypothesis_duplicate")
        seen_constraints.add(constraint_key)
        hypothesis = {
            "id": hypothesis_id,
            "mechanism": mechanism,
            "parameter": parameter,
            "direction": int(direction),
            "constraint_key": constraint_key,
        }
        hypotheses.append(hypothesis)
        prior = prior_by_constraint.get(constraint_key)
        if prior is not None:
            mode = _transfer_mode(plan_combo=plan_combo, source_combo=prior.get("source_combo"))
            suppressed_rows.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "constraint_key": constraint_key,
                    "transfer": {
                        "scope_key": scoped,
                        "mode": mode,
                        "source_experiment_id": prior.get("source_experiment_id"),
                        "source_combo": prior.get("source_combo"),
                    },
                }
            )
            continue
        current = baseline_params.get(parameter)
        spinner = schema.get(parameter)
        if current is None or spinner is None or spinner.read_only:
            if explicit_proposals:
                raise ScientistError("scientist_hypothesis_outside_schema")
            continue
        step = spinner.step if spinner.step is not None and spinner.step > 0 else 1.0
        target = current + float(direction) * step
        if not spinner.is_valid(target):
            if explicit_proposals:
                raise ScientistError("scientist_hypothesis_target_out_of_range")
            continue
        experiments.append(
            {
                "hypothesis_id": hypothesis_id,
                "constraint_key": constraint_key,
                "parameter": parameter,
                "from": current,
                "to": target,
                "changed_params": {parameter: {"from": current, "to": target}},
            }
        )
    if not experiments:
        reason = (
            "scientist_constraints_suppressed"
            if suppressed_rows
            else "scientist_no_safe_experiment"
        )
        raise ScientistError(reason)
    experiments = experiments[:batch_size]

    plan_core = {
        "schema_version": SCHEMA_VERSION,
        "trigger": named_trigger,
        "combo": plan_combo,
        "scope": scope_norm,
        "scope_key": scoped,
        "meta_priors": priors,
        "baseline_provenance": [
            {
                "lap_uuid": payload.get("lap_uuid"),
                "session_uuid": payload.get("session_uuid"),
                "lap_n": (
                    payload.get("lap", {}).get("lap_n")
                    if isinstance(payload.get("lap"), Mapping)
                    else None
                ),
                "setup_hash": (
                    payload.get("setup", {}).get("hash")
                    if isinstance(payload.get("setup"), Mapping)
                    else None
                ),
            }
            for payload in baseline_payloads
        ],
        "hypotheses": hypotheses,
        "suppressed": suppressed_rows,
        "experiments": experiments,
    }
    return {**plan_core, "plan_id": _digest(plan_core)}


def write_candidate_setup(
    baseline_path: str | Path,
    *,
    user_dir: str | Path,
    plan_id: str,
    experiment: Mapping[str, Any],
) -> Path:
    """Create an immutable one-parameter candidate beside the baseline under AC Documents."""
    baseline = Path(baseline_path).resolve(strict=True)
    if not re.fullmatch(r"[0-9a-f]{16}", plan_id):
        raise ScientistError("scientist_plan_id_invalid")
    setups_root = (Path(user_dir) / "setups").resolve(strict=True)
    try:
        baseline.relative_to(setups_root)
    except ValueError:
        raise ScientistError("scientist_baseline_outside_setups_root") from None
    changed = experiment.get("changed_params")
    if not isinstance(changed, Mapping) or len(changed) != 1:
        raise ScientistError("scientist_candidate_not_one_parameter")
    parameter, delta = next(iter(changed.items()))
    if not isinstance(delta, Mapping) or _finite(delta.get("to")) is None:
        raise ScientistError("scientist_candidate_value_invalid")
    section = str(parameter).upper().removesuffix(".VALUE")

    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    try:
        with baseline.open("r", encoding="utf-8-sig") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise ScientistError("scientist_baseline_setup_unreadable") from exc
    if not parser.has_section(section) or not parser.has_option(section, "VALUE"):
        raise ScientistError("scientist_parameter_missing_from_setup")
    source_value = _finite(parser.get(section, "VALUE"))
    expected_source = _finite(delta.get("from"))
    if source_value is None or expected_source is None or source_value != expected_source:
        raise ScientistError("scientist_baseline_setup_drifted")
    target = float(delta["to"])
    parser.set(section, "VALUE", str(int(target)) if target.is_integer() else f"{target:g}")

    constraint_key = str(experiment.get("constraint_key") or "")
    if not re.fullmatch(r"[0-9a-f]{16}", constraint_key):
        constraint_key = _digest(experiment)
    filename = f"Copilot_Scientist_{plan_id}_{constraint_key}.ini"
    candidate = baseline.parent / filename
    try:
        candidate.resolve().relative_to(setups_root)
    except ValueError:
        raise ScientistError("scientist_candidate_outside_setups_root") from None
    candidate.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{candidate.name}.", suffix=".tmp", dir=candidate.parent
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            parser.write(handle, space_around_delimiters=False)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, candidate)
        except FileExistsError:
            if candidate.is_symlink() or not candidate.is_file():
                raise ScientistError("scientist_candidate_conflicts") from None
            try:
                candidate.resolve(strict=True).relative_to(setups_root)
            except (OSError, ValueError):
                raise ScientistError("scientist_candidate_conflicts") from None
            try:
                identical = candidate.read_bytes() == tmp.read_bytes()
            except OSError as exc:
                raise ScientistError("scientist_candidate_existing_unreadable") from exc
            if not identical:
                raise ScientistError("scientist_candidate_conflicts") from None
        tmp.unlink()
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return candidate


def evaluate_experiment(
    *,
    plan: Mapping[str, Any],
    experiment: Mapping[str, Any],
    baseline_payloads: Sequence[Mapping[str, Any]],
    candidate_payloads: Sequence[Mapping[str, Any]],
    candidate_valid: bool,
    candidate_reason: str,
) -> dict[str, Any]:
    """Measure a completed candidate batch and return its fail-closed promotion verdict."""
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan.get("plan_id"),
        "scope_key": plan.get("scope_key"),
        "constraint_key": experiment.get("constraint_key"),
        "experiment": dict(experiment),
        "candidate_oracle": {"valid": candidate_valid, "reason": candidate_reason},
        "verdict": "rejected",
        "promoted": False,
    }
    if not candidate_valid:
        result["reason"] = "candidate_batch_invalid"
        return result
    try:
        baseline = [record_from_lap_archive(dict(payload)) for payload in baseline_payloads]
        candidate = [record_from_lap_archive(dict(payload)) for payload in candidate_payloads]
    except SetupExperimentError as exc:
        result["reason"] = f"candidate_batch_unrecordable:{exc}"
        return result
    if not baseline or not candidate:
        result["reason"] = "candidate_batch_missing_records"
        return result
    baseline_params = _normalized_params(baseline_payloads[0])
    candidate_params = _normalized_params(candidate_payloads[0])
    for payload in baseline_payloads:
        if _normalized_params(payload) != baseline_params:
            result["reason"] = "batch_setup_changed_within_window"
            return result
    for payload in candidate_payloads:
        if _normalized_params(payload) != candidate_params:
            result["reason"] = "batch_setup_changed_within_window"
            return result
    changed = sorted(
        key
        for key in set(baseline_params) | set(candidate_params)
        if baseline_params.get(key) != candidate_params.get(key)
    )
    expected_parameter = str(experiment.get("parameter") or "")
    if changed != [expected_parameter]:
        result["reason"] = "candidate_batch_confounded"
        result["changed_params"] = changed
        return result

    baseline_id = str(baseline[0]["setup"]["hash"])
    candidate_id = str(candidate[0]["setup"]["hash"])
    comparison = compare_setups(
        [*baseline, *candidate],
        baseline_setup=baseline_id,
        candidate_setup=candidate_id,
    )
    result["comparison"] = comparison
    result["baseline_records"] = len(baseline)
    result["candidate_records"] = len(candidate)
    if not comparison.get("ok"):
        result["reason"] = "candidate_comparison_failed"
        return result
    if not comparison.get("significant"):
        result["reason"] = "candidate_not_significantly_faster"
        result["verdict"] = "falsified"
        return result
    result["reason"] = "candidate_significantly_faster"
    result["verdict"] = "promoted"
    result["promoted"] = True
    return result


def persist_completed_run(
    user_dir: str | Path,
    *,
    plan: Mapping[str, Any],
    outcomes: Sequence[Mapping[str, Any]],
    created_utc: str,
) -> Path:
    """Persist plan, batch outcomes, and promotion verdict after the measured batch completes."""
    if not _UTC_STAMP_RE.fullmatch(created_utc):
        raise ScientistError("scientist_created_utc_invalid")
    if not outcomes:
        raise ScientistError("scientist_completed_outcomes_missing")
    root = ensure_state_root(user_dir)
    runs_dir = root / "runs"
    try:
        runs_dir.mkdir()
    except FileExistsError:
        pass
    except OSError as exc:
        raise ScientistError("scientist_state_path_unavailable") from exc
    _validate_state_destination(runs_dir / ".boundary", root)
    ledger_path = _validate_state_destination(root / LEDGER_NAME, root)
    run = {
        "schema_version": SCHEMA_VERSION,
        "created_utc": created_utc,
        "plan": dict(plan),
        "outcomes": [dict(row) for row in outcomes],
    }
    run_id = _digest(run)
    run["run_id"] = run_id
    destination = runs_dir / f"{created_utc}_{run_id}.json"
    _exclusive_write_text(
        destination,
        json.dumps(run, indent=2, ensure_ascii=False) + "\n",
        allowed_root=root,
    )
    scope_payload = (
        normalized_scope(plan["scope"])
        if isinstance(plan.get("scope"), Mapping)
        else None
    )
    combo_payload = _combo_identity(plan.get("combo") if isinstance(plan.get("combo"), Mapping) else None)
    for index, outcome in enumerate(outcomes):
        row: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": f"{run_id}:{index}",
            "created_utc": created_utc,
            "run_path": str(destination),
            "plan_id": plan.get("plan_id"),
            "scope_key": plan.get("scope_key"),
            "constraint_key": outcome.get("constraint_key"),
            "verdict": outcome.get("verdict"),
            "promoted": bool(outcome.get("promoted")),
            "reason": outcome.get("reason"),
        }
        if scope_payload is not None:
            row["scope"] = scope_payload
        if combo_payload is not None:
            row["combo"] = combo_payload
        append_ledger(
            ledger_path,
            row,
            allowed_root=root,
        )
    return destination
