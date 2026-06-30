"""Root-error diagnosis: turn a corner's technique (vs the reference) into ONE actionable
imperative — the heart of Coach v2 (telemetry-transcriber → race engineer).

A real coach does not read out numbers; it names the **single root mistake** the driver made and
tells them what to DO next lap. This module is the pure, testable classifier: given the driver's
:class:`~tools.ai_sidecar.lap_dynamics.CornerSignature` for a corner pass and the reference lap's
signature for the same corner, it returns the earliest-in-the-causal-chain root error that clears a
noise floor — or :data:`RootError.NONE` when the driver is on the reference's technique.

**Why earliest-in-chain, not biggest loss** (council, Mistral 6A): errors compound forward —
braking early bleeds entry speed, which lowers the apex, which delays throttle. The biggest *time*
loss is usually the downstream exit, but coaching the exit is treating a symptom. We coach the
*cause*: brake → line/trail → apex → throttle, returning the first link that is broken.

Pure stdlib; no telemetry, no I/O — unit-tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tools.ai_sidecar.lap_dynamics import CornerSignature


class RootError(StrEnum):
    """The one root mistake coached per pass (verb-first imperative in :data:`PHRASE`)."""

    EARLY_BRAKE = "early_brake"
    LATE_BRAKE = "late_brake"
    NO_TRAIL = "no_trail"
    SLOW_APEX = "slow_apex"
    LATE_THROTTLE = "late_throttle"
    NONE = "none"  # on the reference's technique — coach nothing (silence is the default)


#: The exact short, verb-first phrase spoken for each root (pre-baked into the voice bank).
PHRASE: dict[RootError, str] = {
    RootError.EARLY_BRAKE: "Brake later.",
    RootError.LATE_BRAKE: "Brake earlier.",
    RootError.NO_TRAIL: "Trail it.",
    RootError.SLOW_APEX: "Carry more.",
    RootError.LATE_THROTTLE: "Power.",
}

#: Which reference action point a root's PRIME cue is timed against (``track_reference`` anchors):
#: ``brake`` = before the braking zone; ``turn_in`` = before turn-in; ``apex`` = at the apex.
ANCHOR: dict[RootError, str] = {
    RootError.EARLY_BRAKE: "brake",
    RootError.LATE_BRAKE: "brake",
    RootError.NO_TRAIL: "turn_in",
    RootError.SLOW_APEX: "turn_in",
    RootError.LATE_THROTTLE: "apex",
}

# --- diagnosis floors (spline is normalized 0..1; Magione ≈ 2455 m so 0.004 ≈ 10 m) ---
#: Brake-onset spline difference that counts as braking early/late (below this = on the reference).
BRAKE_SPLINE_FLOOR = 0.004
#: Apex min-speed deficit (km/h) that counts as a slow apex.
APEX_KMH_FLOOR = 3.0
#: Throttle-application spline difference (after apex) that counts as late to power.
THROTTLE_SPLINE_FLOOR = 0.006
#: How much LESS trail-brake overlap than the reference counts as "not trailing" — and the reference
#: must itself trail meaningfully (``ref.trail_brake_frac`` above :data:`_REF_TRAIL_MIN`).
TRAIL_FRAC_FLOOR = 0.15
_REF_TRAIL_MIN = 0.20


@dataclass
class Diagnosis:
    """The single root error for a corner pass plus the measured margins that picked it."""

    root: RootError
    detail: dict[str, float] = field(default_factory=dict)

    @property
    def phrase(self) -> str | None:
        return PHRASE.get(self.root)

    @property
    def anchor(self) -> str | None:
        return ANCHOR.get(self.root)


def classify_root_error(cand: CornerSignature, ref: CornerSignature) -> Diagnosis:
    """Earliest-in-causal-chain root error of ``cand`` vs ``ref``; :data:`RootError.NONE` if clean.

    Chain order (cause → effect): **brake timing → line/trail → apex speed → throttle**. The first
    link whose deviation clears its floor wins; everything downstream is treated as its consequence
    and left unspoken.
    """
    # 1. BRAKE TIMING (entry — earliest link). Both points are just before the apex; no wrap.
    if cand.brake_point_spline is not None and ref.brake_point_spline is not None:
        brake_delta = cand.brake_point_spline - ref.brake_point_spline  # <0 = braked earlier
        if brake_delta < -BRAKE_SPLINE_FLOOR:
            return Diagnosis(RootError.EARLY_BRAKE, {"brake_delta_spline": round(brake_delta, 4)})
        if brake_delta > BRAKE_SPLINE_FLOOR:
            return Diagnosis(RootError.LATE_BRAKE, {"brake_delta_spline": round(brake_delta, 4)})

    # 2. LINE / TRAIL-BRAKE (the reference trails into the corner; the driver brakes straight then
    #    coasts to turn-in). Only when the reference itself meaningfully trail-brakes.
    trail_deficit = ref.trail_brake_frac - cand.trail_brake_frac
    if ref.trail_brake_frac >= _REF_TRAIL_MIN and trail_deficit >= TRAIL_FRAC_FLOOR:
        return Diagnosis(RootError.NO_TRAIL, {"trail_deficit": round(trail_deficit, 3)})

    # 3. APEX SPEED (mid-corner). Carried less minimum speed than the reference.
    apex_deficit = ref.min_speed_kmh - cand.min_speed_kmh  # >0 = slower than reference
    if apex_deficit >= APEX_KMH_FLOOR:
        return Diagnosis(RootError.SLOW_APEX, {"apex_deficit_kmh": round(apex_deficit, 1)})

    # 4. THROTTLE APPLICATION (exit — latest link). Got to power later than the reference.
    if cand.throttle_on_spline is not None and ref.throttle_on_spline is not None:
        thr_delta = cand.throttle_on_spline - ref.throttle_on_spline  # >0 = later to throttle
        if thr_delta > THROTTLE_SPLINE_FLOOR:
            return Diagnosis(RootError.LATE_THROTTLE, {"throttle_delta": round(thr_delta, 4)})

    return Diagnosis(RootError.NONE)
