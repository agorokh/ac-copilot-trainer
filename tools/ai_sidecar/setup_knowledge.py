"""Verified car-setup → handling knowledge base (GT3 class, Assetto Corsa).

Distilled from an adversarially-verified research pass (the ``setup-coaching-physics`` workflow:
four expert lenses → synthesis → a skeptical vehicle-dynamics red-team that corrected 7 rules). This
module is **data**: the per-parameter effects the coaching layer cites, plus the channel map that
says which *live* telemetry would upgrade an archive-suspicion into a confirmed verdict.

Key verified principles encoded here (do not "simplify" these away — each was a red-team finding):
  * **Aero is speed-gated (∝ v²); mechanical balance is speed-flat.** Binning a symptom by corner
    speed is the single strongest, archive-computable SETUP-vs-SETUP discriminator (wings/rake vs
    ARB/springs). See :data:`ParamEffect.speed_dependence`.
  * **Rake direction is car-dependent** — do NOT assume "more rake = more front grip"; on ground-
    effect cars more rake usually adds REAR load. Prefer a wing change for an unambiguous front/rear
    shift. (Flagged ``car_dependent=True``.)
  * **The 911 GT3 R (rear-engine) wants LOWER front brake bias** (~50-56%) than a typical GT3.
  * Archive channels localize a loss to a *phase* and a *speed band*; they cannot, alone, attribute
    a lockup to an axle (needs per-wheel slip) or grip loss to tyre pressure/temp (needs live
    pressure/core temp). Honesty about that split is the whole point — see :data:`TIER_B_CHANNELS`.
"""

from __future__ import annotations

from dataclasses import dataclass

# speed-dependence classes (the aero-vs-mechanical discriminator)
AERO = "aero"  # effect scales with v^2 — shows up in HIGH-speed corners
MECHANICAL = "mechanical"  # roughly speed-flat — shows at ALL speeds, isolate at LOW speed
NEUTRAL = "n/a"  # not a cornering-balance lever in the speed-bin sense (brakes, diff, gearing)


@dataclass(frozen=True)
class ParamEffect:
    """Verified handling effect of one AC setup section."""

    section: str
    human_name: str
    lens: str  # brakes | tires | aero | drivetrain
    units: str
    speed_dependence: str  # AERO | MECHANICAL | NEUTRAL
    increase_does: str
    decrease_does: str
    lever_for: tuple[str, ...]
    confidence: str  # high | medium | low
    car_dependent: bool = False  # the DIRECTION of effect depends on the specific car


# Per the verified param_table (effects condensed; directions are the red-team-corrected ones).
PARAM_EFFECTS: dict[str, ParamEffect] = {
    "FRONT_BIAS": ParamEffect(
        "FRONT_BIAS", "Brake bias (front %)", "brakes", "% front", NEUTRAL,
        "More entry stability, shifts lockup to FRONT, adds entry understeer; lengthens braking if "
        "fronts lock.",
        "Frees rotation / trail-brake yaw, shifts lockup to REAR (snap-spin risk).",
        ("front lock", "rear lock", "entry rotation under braking"), "high",
    ),
    "ABS": ParamEffect(
        "ABS", "ABS level", "brakes", "level (0=off)", NEUTRAL,
        "Prevents lockups but intervenes early — longer distance, peak braking grip left on table.",
        "Brake nearer the true limit (shorter if done well) but lockups/flat-spots are yours.",
        ("braking distance ceiling", "lockup safety net"), "medium",
    ),
    "BRAKE_POWER_MULT": ParamEffect(
        "BRAKE_POWER_MULT", "Brake power", "brakes", "%", NEUTRAL,
        "Bites harder, easier to reach max decel and to lock with less pedal travel.",
        "Softer pedal, harder to lock, finer modulation; may not reach max decel on high grip.",
        ("pedal sensitivity", "lockup tendency"), "medium",
    ),
    "PRESSURE": ParamEffect(
        "PRESSURE", "Cold tyre pressure", "tires", "psi", MECHANICAL,
        "Higher hot psi: patch shrinks to centre, peak grip drops, overheats in the MIDDLE, "
        "skittish, more lockup.",
        "Lower hot psi: patch grows but squirms (vague), SHOULDERS hotter, slow warm-up, draggy.",
        ("mechanical grip", "tyre thermal centre-vs-shoulder", "lockup tendency"), "high",
    ),
    "TYRES": ParamEffect(
        "TYRES", "Tyre compound", "tires", "index", NEUTRAL,
        "Softer (usually): higher peak grip, wider/lower-temp window, faster wear. Index→name is "
        "car-specific.",
        "Harder (usually): lower peak grip, slower warm-up, far more consistent over a stint.",
        ("qual-vs-race grip/consistency", "temp window match"), "medium", car_dependent=True,
    ),
    "CAMBER": ParamEffect(
        "CAMBER", "Camber", "tires", "deg", MECHANICAL,
        "More negative: better MID-corner/high-speed grip, less braking/traction grip, INNER edge "
        "hotter.",
        "Less negative: even temps, better braking/traction, OUTER shoulder rolls under mid-corner "
        "load.",
        ("mid-corner grip", "braking grip", "edge-temp balance"), "high",
    ),
    "TOE_OUT": ParamEffect(
        "TOE_OUT", "Toe", "tires", "deg", MECHANICAL,
        "Front toe-out: sharper turn-in but darty/scrubs top speed. Rear toe-in: stable but "
        "draggy/hot.",
        "Toward zero: less scrub (cooler, faster straights) but slower turn-in / looser rear.",
        ("turn-in response", "straight-line stability", "scrub heat/wear"), "high",
    ),
    "WING_1": ParamEffect(
        "WING_1", "Front wing / splitter", "aero", "clicks", AERO,
        "More front downforce → front grip in HIGH-speed corners; cuts high-speed understeer; adds "
        "front drag.",
        "Less front downforce → high-speed understeer; low-speed unchanged.",
        ("high-speed front grip / aero balance",), "high", car_dependent=True,
    ),
    "WING_2": ParamEffect(
        "WING_2", "Rear wing", "aero", "clicks", AERO,
        "More rear downforce → HIGH-speed rear stability, cuts snap-oversteer; starves front "
        "(high-speed understeer); costs top speed.",
        "Less rear downforce → more rotation, high-speed snap-oversteer risk; higher top speed.",
        ("high-speed rear stability / aero balance", "top speed"), "high",
    ),
    "ARB_FRONT": ParamEffect(
        "ARB_FRONT", "Anti-roll bar (front)", "aero", "level", MECHANICAL,
        "Stiffer → less front grip → MORE understeer at ALL speeds (isolate at low/medium).",
        "Softer → more front grip → less understeer / more entry rotation at all speeds.",
        ("all-speed mechanical front balance", "understeer"), "high",
    ),
    "ARB_REAR": ParamEffect(
        "ARB_REAR", "Anti-roll bar (rear)", "aero", "level", MECHANICAL,
        "Stiffer → less rear grip → MORE oversteer/rotation, snap risk, worse exit traction.",
        "Softer → more rear grip → more stable/understeer, better exit traction, less snap.",
        ("all-speed mechanical rear balance", "entry rotation", "exit traction"), "high",
    ),
    "ROD_LENGTH": ParamEffect(
        "ROD_LENGTH", "Ride height / rake", "aero", "mm", AERO,
        "Raising rear (more rake) shifts aero balance — direction is CAR-DEPENDENT (often more "
        "REAR load on ground-effect cars). Prefer a wing change for an unambiguous shift.",
        "Lowering lowers CG (more mechanical grip until it bottoms); rake direction is car-spec.",
        ("speed-dependent aero balance (rake)", "CG / mechanical balance"), "medium",
        car_dependent=True,
    ),
    "SPRING_RATE": ParamEffect(
        "SPRING_RATE", "Spring rate", "aero", "N/mm", MECHANICAL,
        "Stiffer fronts → entry/mid understeer; stiffer rears → oversteer bias; steadies aero "
        "platform.",
        "Softer → more mechanical grip on bumps/low-speed but more dive/pitch (aero moves).",
        ("mechanical balance", "aero platform / dynamic ride height"), "medium",
    ),
    "TRACTION_CONTROL": ParamEffect(
        "TRACTION_CONTROL", "Traction control", "drivetrain", "level", NEUTRAL,
        "Earlier power cut → cleaner/safer exits but bleeds exit acceleration (worst in slow "
        "corners).",
        "Lets you use more grip before it cuts → more exit accel if traction is there, more "
        "wheelspin/snap risk.",
        ("exit wheelspin safety net vs exit acceleration",), "high",
    ),
    "DIFF_POWER": ParamEffect(
        "DIFF_POWER", "Differential (power)", "drivetrain", "%", NEUTRAL,
        "More on-throttle lock → better straight-line drive off the corner but corner-exit power "
        "UNDERSTEER.",
        "Freer → more exit rotation/agility but more inside-rear wheelspin on slow exits.",
        ("exit power-on balance", "exit traction vs rotation"), "high",
    ),
    "DIFF_COAST": ParamEffect(
        "DIFF_COAST", "Differential (coast)", "drivetrain", "%", NEUTRAL,
        "More off-throttle lock → mid-corner stability on a trailing throttle but adds entry/mid "
        "understeer.",
        "Freer → more entry rotation / trail-brake agility but lift-off oversteer risk.",
        ("entry/mid off-throttle balance", "lift-off stability vs rotation"), "high",
    ),
    "FINAL_RATIO": ParamEffect(
        "FINAL_RATIO", "Final drive / gearing", "drivetrain", "ratio", NEUTRAL,
        "Shorter → stronger slow-corner accel but more torque-spike wheelspin and earlier rev "
        "limit.",
        "Longer → smoother delivery, less slow-corner wheelspin, higher top speed, lazier accel.",
        ("acceleration vs top speed", "torque-spike wheelspin"), "high",
    ),
}


def effect_for(section: str) -> ParamEffect | None:
    """Resolve a :class:`ParamEffect` for an AC section (corner-suffix aware)."""
    sec = section.strip().upper()
    if sec in PARAM_EFFECTS:
        return PARAM_EFFECTS[sec]
    for suffix in ("_LF", "_RF", "_LR", "_RR"):
        if sec.endswith(suffix) and sec[: -len(suffix)] in PARAM_EFFECTS:
            return PARAM_EFFECTS[sec[: -len(suffix)]]
    return None


# --- Tier-B: which LIVE channel upgrades which archive-suspicion to a verdict ---
# (acpmf_physics channels are live-mmap only; the saved archive does not carry them.)
TIER_B_CHANNELS: dict[str, str] = {
    "wheelSlip": "per-wheel slip ratio → confirms WHICH AXLE locks (brake bias) and exit wheelspin "
                 "(TC/diff). Promotes every brake-lockup + exit-traction rule from suspicion to "
                 "verdict.",
    "wheelAngularSpeed": "a wheel collapsing below ground speed = true lock; on driven wheels "
                         "separates TC-cut (slip clamped) from over-throttle (slip overshoot) from "
                         "diff push (RL≈RR).",
    "accG_long": "measures the braking decel ceiling directly → ABS-too-high (flat plateau below "
                 "grip) vs BRAKE_POWER_MULT-too-low becomes measured, not a d(v)/d(x) guess.",
    "accG_lat": "with yaw, separates an understeer push from an oversteer snap unambiguously "
                "(replaces the noisy position-derived heading proxy).",
    "yaw_rate": "the clean rotation signal; upgrades all balance rules from medium to high "
                "confidence.",
    "wheelsPressure": "live HOT pressure — the ONLY way to attribute grip loss/lockup to "
                      "PRESSURE_* rather than a confounded proxy.",
    "tyreCoreTemp": "confirms the compound temp window and separates under-driving from "
                    "under-pressure; needed for toe-scrub-wear.",
    "rpm": "confirms an electronic TORQUE CUT (TC) invisible in the throttle-pedal channel; "
           "validates gearing.",
}

# The two channels with the highest attribution-per-byte if persisted to the archive.
PRIORITY_PERSIST_CHANNELS: tuple[str, ...] = ("wheelSlip", "wheelAngularSpeed")

# Channel that is unavailable even on the live mmap (so camber attribution can only be inferred).
UNAVAILABLE_CHANNEL = "band-resolved tyre temp (inner/centre/outer edge)"

PROVENANCE = (
    "adversarially-verified research (setup-coaching-physics workflow): 4 expert lenses → "
    "synthesis → skeptical red-team correcting 7 rules (rake car-dependence, archive over-claims "
    "on axle/toe/compound attribution)."
)
