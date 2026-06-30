"""Driver skill classification, cue policy, and drill curriculum (issue #403)."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from tools.ai_sidecar.coaching_diagnosis import RootError
from tools.ai_sidecar.coaching_ledger import ASSESS_LAPS, HYSTERESIS_PASSES, LAP_CUE_BUDGET
from tools.ai_sidecar.driver_profile import DEFAULT_PROFILE_PATH, load_profile

LEVEL_UNKNOWN = "unknown"
LEVEL_NOVICE = "novice"
LEVEL_INTERMEDIATE = "intermediate"
LEVEL_ADVANCED = "advanced"
LEVEL_ORDER = {
    LEVEL_UNKNOWN: 0,
    LEVEL_NOVICE: 1,
    LEVEL_INTERMEDIATE: 2,
    LEVEL_ADVANCED: 3,
}

COACHABLE_ROOTS = frozenset(root for root in RootError if root is not RootError.NONE)


@dataclass(frozen=True)
class SkillAssessment:
    """One longitudinal skill verdict derived from the driver profile."""

    skill: str
    level: str
    samples: int
    score: float | None = None
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "level": self.level,
            "samples": self.samples,
            "score": self.score,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class DriverCuePolicy:
    """Runtime coaching density and complexity chosen for the current driver."""

    level: str
    lap_budget: int
    assess_laps: int
    hysteresis: int
    complexity: str
    allowed_roots: frozenset[RootError]

    def allows(self, root: RootError) -> bool:
        return root is RootError.NONE or root in self.allowed_roots

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "lap_budget": self.lap_budget,
            "assess_laps": self.assess_laps,
            "hysteresis": self.hysteresis,
            "complexity": self.complexity,
            "allowed_roots": sorted(root.value for root in self.allowed_roots),
        }


@dataclass(frozen=True)
class Drill:
    """One ordered curriculum step."""

    id: str
    title: str
    skill: str
    target_level: str
    laps_required: int
    success_metric: str
    roots: tuple[RootError, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "skill": self.skill,
            "target_level": self.target_level,
            "laps_required": self.laps_required,
            "success_metric": self.success_metric,
            "roots": [root.value for root in self.roots],
        }


CURRICULUM: tuple[Drill, ...] = (
    Drill(
        id="apex-foundation",
        title="Apex foundation",
        skill="apex_speed",
        target_level=LEVEL_INTERMEDIATE,
        laps_required=4,
        success_metric="Raise median corner minimum speed versus your first recorded laps.",
        roots=(RootError.SLOW_APEX,),
    ),
    Drill(
        id="throttle-to-apex",
        title="Throttle to apex",
        skill="throttle_commitment",
        target_level=LEVEL_INTERMEDIATE,
        laps_required=4,
        success_metric="Apply throttle earlier and more consistently after the apex.",
        roots=(RootError.LATE_THROTTLE,),
    ),
    Drill(
        id="trail-brake-entry",
        title="Trail-brake entry",
        skill="trail_braking",
        target_level=LEVEL_INTERMEDIATE,
        laps_required=4,
        success_metric="Carry brake overlap into rotation without destabilizing entry.",
        roots=(RootError.NO_TRAIL,),
    ),
    Drill(
        id="brake-later-with-control",
        title="Brake later with control",
        skill="consistency",
        target_level=LEVEL_ADVANCED,
        laps_required=8,
        success_metric="Keep session-best spread tight while moving the brake point later.",
        roots=(RootError.EARLY_BRAKE, RootError.LATE_BRAKE),
    ),
)


def default_cue_policy() -> DriverCuePolicy:
    """The historic Coach v2 pacing for unknown/new drivers."""
    return DriverCuePolicy(
        level=LEVEL_UNKNOWN,
        lap_budget=LAP_CUE_BUDGET,
        assess_laps=ASSESS_LAPS,
        hysteresis=HYSTERESIS_PASSES,
        complexity="baseline",
        allowed_roots=COACHABLE_ROOTS,
    )


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(median(values))


def _ratio(consistency_ms: Any, median_ms: Any) -> float | None:
    consistency = _finite(consistency_ms)
    baseline = _finite(median_ms)
    if consistency is None or baseline is None or baseline <= 0:
        return None
    return consistency / baseline


def _skill_level(score: float | None, samples: int, *, intermediate: float, advanced: float) -> str:
    if score is None or samples <= 0:
        return LEVEL_UNKNOWN
    if samples >= 8 and score >= advanced:
        return LEVEL_ADVANCED
    if samples >= 4 and score >= intermediate:
        return LEVEL_INTERMEDIATE
    return LEVEL_NOVICE


def _corner_rows(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = profile.get("corner_history") or {}
    if not isinstance(rows, Mapping):
        return []
    return [row for row in rows.values() if isinstance(row, Mapping)]


def _corner_lap_samples(corners: Sequence[Mapping[str, Any]]) -> int:
    counts = [int(row.get("valid_laps") or 0) for row in corners]
    return max(counts, default=0)


def _consistency_assessment(profile: Mapping[str, Any]) -> SkillAssessment:
    rows = [row for row in (profile.get("consistency") or {}).values() if isinstance(row, Mapping)]
    ratios = [
        ratio
        for row in rows
        if (ratio := _ratio(row.get("consistency_ms"), row.get("median_session_best_ms")))
        is not None
    ]
    if not ratios:
        return SkillAssessment("consistency", LEVEL_UNKNOWN, 0, evidence=("no session spread yet",))
    score = _median(ratios)
    sessions = max(int(row.get("session_count") or 0) for row in rows)
    valid_laps = max(int(row.get("valid_laps") or 0) for row in rows)
    if score is not None and sessions >= 3 and score <= 0.015:
        level = LEVEL_ADVANCED
    elif score is not None and sessions >= 2 and score <= 0.04:
        level = LEVEL_INTERMEDIATE
    else:
        level = LEVEL_NOVICE
    return SkillAssessment(
        "consistency",
        level,
        valid_laps,
        score=None if score is None else round(score, 4),
        evidence=(f"median session-best spread ratio {score:.3f}",),
    )


def classify_skills(profile: Mapping[str, Any] | None) -> dict[str, SkillAssessment]:
    """Classify driver skills from a persistent profile."""
    if not isinstance(profile, Mapping):
        return {
            "consistency": SkillAssessment("consistency", LEVEL_UNKNOWN, 0),
            "apex_speed": SkillAssessment("apex_speed", LEVEL_UNKNOWN, 0),
            "trail_braking": SkillAssessment("trail_braking", LEVEL_UNKNOWN, 0),
            "throttle_commitment": SkillAssessment("throttle_commitment", LEVEL_UNKNOWN, 0),
            "steering_smoothness": SkillAssessment("steering_smoothness", LEVEL_UNKNOWN, 0),
        }

    corners = _corner_rows(profile)
    corner_laps = _corner_lap_samples(corners)
    deltas = [
        value for row in corners if (value := _finite(row.get("delta_min_speed_kmh"))) is not None
    ]
    positive_share = sum(1 for value in deltas if value >= 0.5) / len(deltas) if deltas else 0.0
    apex_score = _median(deltas)
    if apex_score is not None and corner_laps >= 8 and apex_score >= 2.0 and positive_share >= 0.65:
        apex_level = LEVEL_ADVANCED
    elif (
        apex_score is not None and corner_laps >= 4 and apex_score >= 0.5 and positive_share >= 0.5
    ):
        apex_level = LEVEL_INTERMEDIATE
    elif deltas:
        apex_level = LEVEL_NOVICE
    else:
        apex_level = LEVEL_UNKNOWN

    trails = [
        value for row in corners if (value := _finite(row.get("avg_trail_brake_ratio"))) is not None
    ]
    trail_score = _median(trails)
    trail_level = _skill_level(trail_score, corner_laps, intermediate=0.18, advanced=0.34)

    throttles = [
        value for row in corners if (value := _finite(row.get("avg_throttle"))) is not None
    ]
    throttle_score = _median(throttles)
    throttle_level = _skill_level(throttle_score, corner_laps, intermediate=0.45, advanced=0.62)

    steers = [
        value for row in corners if (value := _finite(row.get("avg_steer_reversals"))) is not None
    ]
    steer_score = _median(steers)
    if steer_score is None:
        steer_level = LEVEL_UNKNOWN
    elif corner_laps >= 8 and steer_score <= 1.5:
        steer_level = LEVEL_ADVANCED
    elif corner_laps >= 4 and steer_score <= 3.0:
        steer_level = LEVEL_INTERMEDIATE
    else:
        steer_level = LEVEL_NOVICE

    return {
        "consistency": _consistency_assessment(profile),
        "apex_speed": SkillAssessment(
            "apex_speed",
            apex_level,
            corner_laps if deltas else 0,
            None if apex_score is None else round(apex_score, 3),
            evidence=(
                f"median min-speed delta {apex_score:.1f} km/h"
                if apex_score is not None
                else "no corner speed history yet",
            ),
        ),
        "trail_braking": SkillAssessment(
            "trail_braking",
            trail_level,
            corner_laps if trails else 0,
            None if trail_score is None else round(trail_score, 3),
            evidence=(
                f"median trail ratio {trail_score:.2f}"
                if trail_score is not None
                else "no trail-brake history yet",
            ),
        ),
        "throttle_commitment": SkillAssessment(
            "throttle_commitment",
            throttle_level,
            corner_laps if throttles else 0,
            None if throttle_score is None else round(throttle_score, 3),
            evidence=(
                f"median throttle average {throttle_score:.2f}"
                if throttle_score is not None
                else "no throttle history yet",
            ),
        ),
        "steering_smoothness": SkillAssessment(
            "steering_smoothness",
            steer_level,
            corner_laps if steers else 0,
            None if steer_score is None else round(steer_score, 3),
            evidence=(
                f"median steering reversals {steer_score:.1f}"
                if steer_score is not None
                else "no steering history yet",
            ),
        ),
    }


def classify_driver_level(skills: Mapping[str, SkillAssessment]) -> str:
    if not skills or all(skill.level == LEVEL_UNKNOWN for skill in skills.values()):
        return LEVEL_UNKNOWN
    core = (skills.get("apex_speed"), skills.get("consistency"))
    if any(skill is not None and skill.level == LEVEL_NOVICE for skill in core):
        return LEVEL_NOVICE
    known = [skill for skill in skills.values() if skill.level != LEVEL_UNKNOWN]
    if not known:
        return LEVEL_UNKNOWN
    if all(LEVEL_ORDER[skill.level] >= LEVEL_ORDER[LEVEL_INTERMEDIATE] for skill in known):
        advanced_count = sum(skill.level == LEVEL_ADVANCED for skill in known)
        return LEVEL_ADVANCED if advanced_count >= 2 else LEVEL_INTERMEDIATE
    return LEVEL_NOVICE


def cue_policy_from_profile(profile: Mapping[str, Any] | None) -> DriverCuePolicy:
    """Return a live Coach v2 policy tailored to the persistent driver profile."""
    skills = classify_skills(profile)
    level = classify_driver_level(skills)
    if level == LEVEL_UNKNOWN:
        return default_cue_policy()
    if level == LEVEL_NOVICE:
        return DriverCuePolicy(
            level=level,
            lap_budget=2,
            assess_laps=3,
            hysteresis=3,
            complexity="foundation",
            allowed_roots=frozenset(
                {
                    RootError.EARLY_BRAKE,
                    RootError.LATE_BRAKE,
                    RootError.SLOW_APEX,
                    RootError.LATE_THROTTLE,
                }
            ),
        )
    if level == LEVEL_INTERMEDIATE:
        return DriverCuePolicy(
            level=level,
            lap_budget=3,
            assess_laps=2,
            hysteresis=2,
            complexity="technique",
            allowed_roots=COACHABLE_ROOTS,
        )
    return DriverCuePolicy(
        level=level,
        lap_budget=5,
        assess_laps=1,
        hysteresis=1,
        complexity="precision",
        allowed_roots=COACHABLE_ROOTS,
    )


def progression_trends(profile: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(profile, Mapping):
        return []
    out: list[dict[str, Any]] = []
    for key, row in sorted((profile.get("corner_history") or {}).items()):
        if not isinstance(row, Mapping):
            continue
        delta = _finite(row.get("delta_min_speed_kmh"))
        if delta is None:
            trend = LEVEL_UNKNOWN
        elif delta >= 1.0:
            trend = "improving"
        elif delta <= -1.0:
            trend = "regressing"
        else:
            trend = "plateau"
        out.append(
            {
                "key": key,
                "track_id": row.get("track_id"),
                "corner_index": row.get("corner_index"),
                "label": row.get("label"),
                "valid_laps": row.get("valid_laps"),
                "delta_min_speed_kmh": delta,
                "trend": trend,
            }
        )
    return out


def evaluate_curriculum(profile: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    skills = classify_skills(profile)
    rows: list[dict[str, Any]] = []
    locked = False
    for drill in CURRICULUM:
        assessment = skills.get(drill.skill)
        skill_level = assessment.level if assessment is not None else LEVEL_UNKNOWN
        samples = assessment.samples if assessment is not None else 0
        graduated = (
            LEVEL_ORDER.get(skill_level, 0) >= LEVEL_ORDER[drill.target_level]
            and samples >= drill.laps_required
        )
        status = "graduated" if graduated else ("locked" if locked else "active")
        rows.append(
            {
                **drill.to_dict(),
                "status": status,
                "skill_level": skill_level,
                "skill_samples": samples,
            }
        )
        if not graduated:
            locked = True
    return rows


def next_drill(profile: Mapping[str, Any] | None) -> dict[str, Any] | None:
    for row in evaluate_curriculum(profile):
        if row["status"] == "active":
            return row
    return None


def build_progression_report(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    profile = profile if isinstance(profile, Mapping) else {}
    skills = classify_skills(profile)
    policy = cue_policy_from_profile(profile)
    return {
        "driver_id": profile.get("driver_id"),
        "updated_at": profile.get("updated_at"),
        "level": policy.level,
        "cue_policy": policy.to_dict(),
        "skills": {key: value.to_dict() for key, value in sorted(skills.items())},
        "drills": evaluate_curriculum(profile),
        "next_drill": next_drill(profile),
        "trends": progression_trends(profile),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument(
        "--json", action="store_true", help="Emit the full progression report JSON."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    profile = load_profile(args.profile)
    report = build_progression_report(profile)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    nxt = report.get("next_drill") or {}
    print(
        "driver progression: "
        f"driver={report.get('driver_id') or '<unknown>'} "
        f"level={report['level']} "
        f"budget={report['cue_policy']['lap_budget']} "
        f"next_drill={nxt.get('id') or 'none'}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
