"""Complaint-language setup advice and display-ready setup diffs.

This module is the thin product surface over the existing setup intelligence
building blocks: :mod:`setup_model` gives typed setup values and
:mod:`setup_knowledge` supplies the verified GT3 parameter effects.  The
functions here are deterministic and stdlib-only so the sidecar can answer a
driver's "the car is loose on exit" request without involving an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.ai_sidecar.car_schema import CarSetupSchema, load_latest_schema
from tools.ai_sidecar.external_protocol import (
    MAX_SETUP_ADVICE_COMPLAINT_LEN as MAX_COMPLAINT_LEN,
)
from tools.ai_sidecar.setup_knowledge import AERO, MECHANICAL, effect_for
from tools.ai_sidecar.setup_model import CarSetup, from_snapshot, load_setup_file, spec_for

_WORD_RE = re.compile(r"[a-z0-9]+")

_DEFAULT_STEPS: dict[str, float] = {
    "FRONT_BIAS": 1.0,
    "ABS": 1.0,
    "TRACTION_CONTROL": 1.0,
    "BRAKE_POWER_MULT": 5.0,
    "WING_1": 1.0,
    "WING_2": 1.0,
    "ARB_FRONT": 1.0,
    "ARB_REAR": 1.0,
    "DIFF_POWER": 5.0,
    "DIFF_COAST": 5.0,
    "FINAL_RATIO": 1.0,
    "PRESSURE": 0.5,
    "CAMBER": 0.1,
    "TOE_OUT": 0.05,
    "SPRING_RATE": 1.0,
    "ROD_LENGTH": 1.0,
}

_PRIORITY: tuple[str, ...] = (
    "FRONT_BIAS",
    "BRAKE_POWER_MULT",
    "ABS",
    "TRACTION_CONTROL",
    "WING_1",
    "WING_2",
    "ARB_FRONT",
    "ARB_REAR",
    "DIFF_POWER",
    "DIFF_COAST",
    "PRESSURE_LF",
    "PRESSURE_RF",
    "PRESSURE_LR",
    "PRESSURE_RR",
    "CAMBER_LF",
    "CAMBER_RF",
    "CAMBER_LR",
    "CAMBER_RR",
    "TOE_OUT_LF",
    "TOE_OUT_RF",
    "TOE_OUT_LR",
    "TOE_OUT_RR",
    "SPRING_RATE_LF",
    "SPRING_RATE_RF",
    "SPRING_RATE_LR",
    "SPRING_RATE_RR",
    "FINAL_RATIO",
)


@dataclass(frozen=True)
class ComplaintMove:
    section: str
    direction: int
    reason: str


@dataclass(frozen=True)
class ComplaintRule:
    issue: str
    phase: str
    moves: tuple[ComplaintMove, ...]


_RULES: tuple[ComplaintRule, ...] = (
    ComplaintRule(
        "understeer",
        "entry",
        (
            ComplaintMove("FRONT_BIAS", -1, "free entry rotation while trail braking"),
            ComplaintMove("DIFF_COAST", -1, "freer coast diff helps the car rotate off-throttle"),
            ComplaintMove("ARB_FRONT", -1, "softer front bar adds mechanical front grip"),
            ComplaintMove("WING_1", 1, "if it only pushes in fast entries, add front aero"),
        ),
    ),
    ComplaintRule(
        "understeer",
        "mid",
        (
            ComplaintMove("ARB_FRONT", -1, "add all-speed front mechanical grip"),
            ComplaintMove("ARB_REAR", 1, "shift mechanical balance rearward for more rotation"),
            ComplaintMove("WING_1", 1, "if the push is high-speed only, add front aero"),
            ComplaintMove("PRESSURE_LF", -1, "trim front pressure if hot pressure is high"),
            ComplaintMove("PRESSURE_RF", -1, "match the front axle pressure change"),
        ),
    ),
    ComplaintRule(
        "understeer",
        "exit",
        (
            ComplaintMove("DIFF_POWER", -1, "open the power diff to reduce power-on push"),
            ComplaintMove("ARB_FRONT", -1, "soften front bar if the push exists before throttle"),
            ComplaintMove(
                "TRACTION_CONTROL", -1, "if TC is cutting hard, reduce intervention one step"
            ),
        ),
    ),
    ComplaintRule(
        "oversteer",
        "entry",
        (
            ComplaintMove(
                "FRONT_BIAS", 1, "move bias forward if the rear is nervous under braking"
            ),
            ComplaintMove("DIFF_COAST", 1, "more coast lock calms lift/trail-brake rotation"),
            ComplaintMove("ARB_REAR", -1, "softer rear bar adds rear mechanical grip"),
            ComplaintMove("WING_2", 1, "if it snaps in fast entries, add rear aero"),
        ),
    ),
    ComplaintRule(
        "oversteer",
        "mid",
        (
            ComplaintMove("ARB_REAR", -1, "softer rear bar adds mid-corner rear grip"),
            ComplaintMove("ARB_FRONT", 1, "stiffer front bar shifts balance safer"),
            ComplaintMove("WING_2", 1, "if the snap is high-speed only, add rear aero"),
        ),
    ),
    ComplaintRule(
        "oversteer",
        "exit",
        (
            ComplaintMove("TRACTION_CONTROL", 1, "catch exit wheelspin earlier"),
            ComplaintMove("DIFF_POWER", 1, "more power lock stabilizes straight-line drive"),
            ComplaintMove("ARB_REAR", -1, "softer rear bar improves rear grip before throttle"),
            ComplaintMove("WING_2", 1, "add rear aero only for genuinely fast exits"),
        ),
    ),
    ComplaintRule(
        "lockup_front",
        "braking",
        (
            ComplaintMove("FRONT_BIAS", -1, "front lock means the bias is too far forward"),
            ComplaintMove("BRAKE_POWER_MULT", -1, "lower bite if both fronts still lock"),
            ComplaintMove("ABS", 1, "raise ABS one level as a safety net"),
        ),
    ),
    ComplaintRule(
        "lockup_rear",
        "braking",
        (
            ComplaintMove("FRONT_BIAS", 1, "rear lock means the bias is too far rearward"),
            ComplaintMove("BRAKE_POWER_MULT", -1, "reduce bite if the car locks both axles"),
            ComplaintMove("ABS", 1, "raise ABS one level as a safety net"),
        ),
    ),
    ComplaintRule(
        "lockup",
        "braking",
        (
            ComplaintMove("BRAKE_POWER_MULT", -1, "reduce bite until lockups are controllable"),
            ComplaintMove("ABS", 1, "raise ABS one level if lockups are frequent"),
            ComplaintMove("FRONT_BIAS", -1, "if the fronts lock first, move bias rearward"),
        ),
    ),
    ComplaintRule(
        "wheelspin",
        "exit",
        (
            ComplaintMove("TRACTION_CONTROL", 1, "catch drive-wheel slip earlier"),
            ComplaintMove("DIFF_POWER", 1, "more power lock reduces inside-wheel spin"),
            ComplaintMove("FINAL_RATIO", -1, "longer gearing softens torque spikes"),
            ComplaintMove("ARB_REAR", -1, "add rear mechanical grip before the power phase"),
        ),
    ),
    ComplaintRule(
        "instability",
        "kerb",
        (
            ComplaintMove("ARB_REAR", -1, "soften the rear bar for kerb compliance"),
            ComplaintMove("ARB_FRONT", -1, "soften the front bar if it skips across kerbs"),
            ComplaintMove("SPRING_RATE_LR", -1, "soften rear spring rate one click if available"),
            ComplaintMove("SPRING_RATE_RR", -1, "match the rear spring-rate move"),
        ),
    ),
)


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _has_phrase(text: str, *phrases: str) -> bool:
    low = " ".join(_WORD_RE.findall(text.lower()))
    return any(phrase in low for phrase in phrases)


def _parse_issue(text: str) -> str | None:
    words = _tokens(text)
    lock_words = {"lock", "locked", "locking", "locks", "lockup", "lockups"}
    if "front" in words and words & lock_words:
        return "lockup_front"
    if "rear" in words and words & lock_words:
        return "lockup_rear"
    if (lock_words | {"flatspot", "flatspots"}) & words:
        return "lockup"
    if "abs" in words and "lights" in words:
        return "lockup"
    if (
        _has_phrase(text, "wheel spin", "wheelspin")
        or {"traction", "spin", "spinning"} & words
        or ("lights" in words and {"tc", "traction"} & words)
    ):
        return "wheelspin"
    if {
        "understeer",
        "push",
        "pushes",
        "pushing",
        "washes",
        "wash",
        "plough",
        "plow",
    } & words or _has_phrase(
        text,
        "under steer",
        "wont turn",
        "won t turn",
        "doesnt turn",
        "doesn t turn",
    ):
        return "understeer"
    if {"kerb", "curb", "bump", "bumpy"} & words:
        return "instability"
    oversteer_words = {"oversteer", "loose", "snap", "snappy", "tail"}
    rear_instability_words = {"unstable", "nervous"}
    if (
        oversteer_words & words
        or ("rear" in words and rear_instability_words & words)
        or _has_phrase(text, "over steer", "steps out", "stepping out", "rear steps")
    ):
        return "oversteer"
    return None


def _parse_phase(text: str, issue: str | None) -> str:
    words = _tokens(text)
    if issue in {"lockup", "lockup_front", "lockup_rear"}:
        return "braking"
    if issue == "instability":
        return "kerb"
    if {"exit", "power", "throttle", "traction"} & words or _has_phrase(text, "corner exit"):
        return "exit"
    if {"mid", "apex", "middle", "center", "centre"} & words or _has_phrase(text, "mid corner"):
        return "mid"
    if {"entry", "turn", "turnin", "braking", "brake", "trail"} & words:
        return "entry"
    if issue == "wheelspin":
        return "exit"
    return "mid"


def _parse_speed_hint(text: str) -> str | None:
    words = _tokens(text)
    if {"slow", "hairpin", "low"} & words or _has_phrase(text, "low speed"):
        return "low"
    if {"fast", "high", "aero"} & words or _has_phrase(text, "high speed"):
        return "high"
    return None


def _base_section(section: str) -> str:
    sec = section.strip().upper()
    if sec.endswith(".VALUE"):
        sec = sec[:-6]
    for suffix in ("_LF", "_RF", "_LR", "_RR"):
        if sec.endswith(suffix):
            stem = sec[: -len(suffix)]
            return stem if stem in _DEFAULT_STEPS else sec
    return sec


def _param_key(section: str) -> str:
    sec = section.strip().upper()
    return sec if sec.endswith(".VALUE") else f"{sec}.VALUE"


def _step_for(section: str, schema: CarSetupSchema | None) -> float:
    if schema is not None:
        sp = schema.get(section)
        if sp is not None and sp.step is not None and sp.step > 0:
            return float(sp.step)
    return _DEFAULT_STEPS.get(_base_section(section), 1.0)


def _format_value(value: float | int | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(int(value)) if float(value).is_integer() else f"{float(value):g}"


def _decoded(
    schema: CarSetupSchema | None, section: str, value: float | None
) -> float | str | None:
    if schema is None or value is None:
        return value
    return schema.decode(section, value)


def _display_units(schema: CarSetupSchema | None, section: str, fallback: str) -> str:
    sp = schema.get(section) if schema is not None else None
    if sp is not None and sp.items:
        return sp.units or ""
    if sp is None and _base_section(section) in {"CAMBER", "TOE_OUT", "ROD_LENGTH"}:
        return "clicks"
    if sp is not None and sp.units is not None:
        return sp.units
    return fallback


def _raw_click_display(schema: CarSetupSchema | None, section: str) -> bool:
    sp = schema.get(section) if schema is not None else None
    return sp is None and _base_section(section) in {"CAMBER", "TOE_OUT", "ROD_LENGTH"}


def _spinner_read_only(schema: CarSetupSchema | None, section: str) -> bool:
    if schema is None:
        return False
    sp = schema.get(section)
    return bool(sp is not None and sp.read_only)


def _direction_from_delta(delta: float | None) -> str:
    if delta is None:
        return "unchanged"
    if delta > 0:
        return "increase"
    if delta < 0:
        return "decrease"
    return "unchanged"


def _semantic_delta(
    schema: CarSetupSchema | None,
    section: str,
    from_v: float | None,
    to_v: float | None,
) -> float | None:
    if from_v is None or to_v is None:
        return None
    before = _decoded(schema, section, from_v)
    after = _decoded(schema, section, to_v)
    if not isinstance(before, int | float) or not isinstance(after, int | float):
        return float(to_v) - float(from_v)
    delta = float(after) - float(before)
    if (
        schema is not None
        and schema.get(section) is not None
        and _base_section(section) == "CAMBER"
    ):
        return -delta
    return delta


def _diff_direction(
    schema: CarSetupSchema | None,
    section: str,
    from_v: float | None,
    to_v: float | None,
) -> str:
    if from_v is None:
        return "added"
    if to_v is None:
        return "removed"
    sp = schema.get(section) if schema is not None else None
    if sp is not None and sp.items:
        return "changed"
    return _direction_from_delta(_semantic_delta(schema, section, from_v, to_v))


def _move_to_suggestion(
    move: ComplaintMove,
    *,
    setup: CarSetup,
    schema: CarSetupSchema | None,
    rank: int,
) -> dict[str, Any] | None:
    section = move.section.strip().upper()
    if _spinner_read_only(schema, section):
        return None
    if schema is not None and _base_section(section) == "PRESSURE" and schema.get(section) is None:
        return None
    spec = spec_for(section)
    effect = effect_for(section)
    current = setup.value(section)
    if current is None:
        return None
    step = _step_for(section, schema)
    delta = move.direction * step
    target = current + delta
    if schema is not None and schema.get(section) is not None:
        target = schema.clamp(section, target)
    elif target < 0:
        target = 0.0
    if abs(target - current) <= 1e-9:
        return None
    direction = "increase" if move.direction > 0 else "decrease"
    effect_text = ""
    if effect is not None:
        effect_text = effect.increase_does if move.direction > 0 else effect.decrease_does
    caution: list[str] = []
    if effect is not None and effect.car_dependent:
        caution.append("Car-specific lever; verify this car's spinner label before applying.")
    if schema is not None:
        caution.extend(schema.caution_notes(section, direction=direction, current=current))
    return {
        "rank": rank,
        "section": section,
        "param_key": _param_key(section),
        "name": spec.human_name,
        "category": spec.category,
        "direction": direction,
        "magnitude": step,
        "units": _display_units(schema, section, spec.units or (effect.units if effect else "")),
        "current": current,
        "target": target,
        "current_display": _format_value(_decoded(schema, section, current)),
        "target_display": _format_value(_decoded(schema, section, target)),
        "reason": move.reason,
        "effect": effect_text,
        "confidence": effect.confidence if effect is not None else "low",
        "caution": caution,
    }


def _rank_moves(moves: tuple[ComplaintMove, ...], speed_hint: str | None) -> list[ComplaintMove]:
    if speed_hint is None:
        return list(moves)

    def score(indexed_move: tuple[int, ComplaintMove]) -> tuple[int, int]:
        index, move = indexed_move
        effect = effect_for(move.section)
        if effect is None:
            return (1, index)
        if speed_hint == "high" and effect.speed_dependence == AERO:
            return (0, index)
        if speed_hint == "low" and effect.speed_dependence == MECHANICAL:
            return (0, index)
        return (1, index)

    return [move for _, move in sorted(enumerate(moves), key=score)]


def advise_from_complaint(
    complaint: str,
    *,
    setup: CarSetup | None = None,
    setup_snapshot: dict[str, Any] | None = None,
    car_id: str | None = None,
    track_id: str | None = None,
    schema: CarSetupSchema | None = None,
    max_suggestions: int = 5,
) -> dict[str, Any]:
    """Return ranked setup changes for a driver handling complaint."""

    text = (complaint or "").strip()
    if not text:
        return {"ok": False, "status": "empty_complaint", "error": "complaint is required"}
    if len(text) > MAX_COMPLAINT_LEN:
        return {
            "ok": False,
            "status": "complaint_too_long",
            "error": f"complaint must be <= {MAX_COMPLAINT_LEN} characters",
        }
    issue = _parse_issue(text)
    phase = _parse_phase(text, issue)
    speed_hint = _parse_speed_hint(text)
    if setup is None:
        effective_setup = from_snapshot(setup_snapshot or {}, car_id=car_id, track_id=track_id)
    else:
        effective_setup = setup
        if car_id and effective_setup.car_id is None:
            effective_setup = CarSetup(
                params=effective_setup.params,
                car_id=car_id,
                track_id=effective_setup.track_id,
                spinner_schema=effective_setup.spinner_schema,
            )
        if track_id and effective_setup.track_id is None:
            effective_setup = CarSetup(
                params=effective_setup.params,
                car_id=effective_setup.car_id,
                track_id=track_id,
                spinner_schema=effective_setup.spinner_schema,
            )
    if schema is None:
        schema = load_latest_schema(effective_setup.car_id)
    if issue is None:
        return {
            "ok": False,
            "status": "unknown_complaint",
            "complaint": text,
            "parsed": {"issue": None, "phase": phase, "speed_hint": speed_hint},
            "error": "could not map complaint to handling vocabulary",
        }

    rule = next((r for r in _RULES if r.issue == issue and r.phase == phase), None)
    if rule is None and phase != "mid":
        rule = next((r for r in _RULES if r.issue == issue and r.phase == "mid"), None)
    if rule is None:
        return {
            "ok": False,
            "status": "unsupported_complaint",
            "complaint": text,
            "parsed": {"issue": issue, "phase": phase, "speed_hint": speed_hint},
            "error": "handling vocabulary recognized, but no setup rule is available",
        }
    moves = _rank_moves(rule.moves, speed_hint)
    suggestions: list[dict[str, Any]] = []
    for move in moves:
        suggestion = _move_to_suggestion(
            move,
            setup=effective_setup,
            schema=schema,
            rank=len(suggestions) + 1,
        )
        if suggestion is not None:
            suggestions.append(suggestion)
        if len(suggestions) >= max_suggestions:
            break
    if not suggestions:
        return {
            "ok": False,
            "status": "no_applicable_moves",
            "complaint": text,
            "parsed": {"issue": issue, "phase": phase, "speed_hint": speed_hint},
            "car_id": effective_setup.car_id,
            "track_id": effective_setup.track_id,
            "error": "recognized setup levers are unavailable or already at their bounds",
        }
    return {
        "ok": True,
        "status": "suggested",
        "complaint": text,
        "parsed": {"issue": issue, "phase": phase, "speed_hint": speed_hint},
        "car_id": effective_setup.car_id,
        "track_id": effective_setup.track_id,
        "suggestions": suggestions,
        "rationale": [
            "Complaint mapped through deterministic handling vocabulary.",
            "Lever effects are grounded in setup_knowledge.py; live telemetry still wins.",
        ],
    }


def setup_diff_summary(
    baseline: CarSetup,
    candidate: CarSetup,
    *,
    schema: CarSetupSchema | None = None,
) -> dict[str, Any]:
    """Return setup A/B changes as display-ready rows."""

    if baseline.car_id and candidate.car_id and baseline.car_id != candidate.car_id:
        return {
            "ok": False,
            "status": "car_mismatch",
            "baseline": {"car_id": baseline.car_id, "track_id": baseline.track_id},
            "candidate": {"car_id": candidate.car_id, "track_id": candidate.track_id},
            "changed_count": 0,
            "rows": [],
            "display_lines": [],
            "error": "cannot compare setup files from different cars",
        }
    if bool(baseline.car_id) != bool(candidate.car_id):
        return {
            "ok": False,
            "status": "incomplete_identity",
            "baseline": {"car_id": baseline.car_id, "track_id": baseline.track_id},
            "candidate": {"car_id": candidate.car_id, "track_id": candidate.track_id},
            "changed_count": 0,
            "rows": [],
            "display_lines": [],
            "error": "both setup files must identify the same car before diffing",
        }
    if schema is None:
        schema = load_latest_schema(candidate.car_id or baseline.car_id)

    raw = candidate.diff(baseline)
    priority = {name: i for i, name in enumerate(_PRIORITY)}
    rows: list[dict[str, Any]] = []
    for section, values in sorted(
        raw.items(), key=lambda item: (priority.get(item[0], 999), item[0])
    ):
        from_v = values.get("from")
        to_v = values.get("to")
        spec = spec_for(section)
        effect = effect_for(section)
        delta = _semantic_delta(schema, section, from_v, to_v)
        display_delta = None if delta is None else round(delta, 6)
        direction = _diff_direction(schema, section, from_v, to_v)
        effect_text = ""
        raw_click_display = _raw_click_display(schema, section)
        if effect is not None and direction in {"increase", "decrease"} and not raw_click_display:
            effect_text = effect.increase_does if direction == "increase" else effect.decrease_does
        from_display = _format_value(_decoded(schema, section, from_v))
        to_display = _format_value(_decoded(schema, section, to_v))
        unit = _display_units(schema, section, spec.units or (effect.units if effect else ""))
        arrow = f"{from_display or '-'} -> {to_display or '-'}"
        display = f"{spec.human_name}: {arrow}{(' ' + unit) if unit else ''}"
        if effect_text or (raw_click_display and direction in {"increase", "decrease"}):
            display = f"{display} ({direction})"
        rows.append(
            {
                "section": section,
                "param_key": _param_key(section),
                "name": spec.human_name,
                "category": spec.category,
                "from": from_v,
                "to": to_v,
                "delta": display_delta,
                "from_display": from_display,
                "to_display": to_display,
                "units": unit,
                "direction": direction,
                "effect": effect_text,
                "display": display,
            }
        )
    return {
        "ok": True,
        "baseline": {"car_id": baseline.car_id, "track_id": baseline.track_id},
        "candidate": {"car_id": candidate.car_id, "track_id": candidate.track_id},
        "changed_count": len(rows),
        "rows": rows,
        "display_lines": [row["display"] for row in rows],
    }


def diff_setup_files(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    schema: CarSetupSchema | None = None,
) -> dict[str, Any]:
    baseline = load_setup_file(baseline_path)
    candidate = load_setup_file(candidate_path)
    out = setup_diff_summary(baseline, candidate, schema=schema)
    out["baseline"]["path"] = str(baseline_path)
    out["candidate"]["path"] = str(candidate_path)
    return out
