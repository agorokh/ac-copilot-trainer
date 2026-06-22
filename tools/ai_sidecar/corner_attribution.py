"""Per-corner pace attribution: WHY was a corner slow — setup or technique? (stdlib-only)

Combines three grounded inputs:
  * :class:`~tools.ai_sidecar.lap_dynamics.CornerSignature` — observable per-corner facts,
  * :class:`~tools.ai_sidecar.setup_model.CarSetup` — the car's setup knobs (semantic),
  * an optional reference lap — to localize *where* time was lost (:func:`compare_laps`),

and applies the adversarially-verified knowledge in ``setup_knowledge`` to produce pro-engineer
coaching that **distinguishes a setup change from a driver-technique change**.

Honesty about data (enforced by the red-team review behind ``setup_knowledge``):
  * Archive channels (speed/brake/throttle/steer/position/lap_ms) localize a loss to a *phase* and a
    *speed band*. That is the robust, archive-computable signal.
  * They CANNOT, alone, attribute a lockup to an axle (needs per-wheel slip), grip loss to tyre
    pressure/temp, or a torque cut to TC. Those conclusions are emitted as **suspicions** and, when
    the live channels are supplied via :attr:`CornerContext.extra`, upgraded to confirmed verdicts
    (``advisory`` flips to False). Every rule names the channel that would confirm it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tools.ai_sidecar.lap_dynamics import (
    CornerSignature,
    LapTrace,
    corner_signatures,
    segment_corners,
)
from tools.ai_sidecar.setup_knowledge import AERO, MECHANICAL
from tools.ai_sidecar.setup_model import CarSetup


# --- lap comparison: localize where time is lost ----------------------------
@dataclass(frozen=True)
class CornerDelta:
    """Time/speed difference of one corner window vs a reference lap (candidate - reference)."""

    index: int
    spline_lo: float
    spline_hi: float
    cand_time_s: float
    ref_time_s: float
    delta_s: float  # >0 means the candidate LOST time here
    cand_min_kmh: float
    ref_min_kmh: float
    min_speed_delta_kmh: float  # >0 means candidate carried MORE apex speed


def _interp_time(lap: LapTrace, spline: float) -> float:
    """Time (s) at a spline position via linear interpolation over the monotone spline channel."""
    sp = lap.spline
    if spline <= sp[0]:
        return lap.t_s[0]
    if spline >= sp[-1]:
        return lap.t_s[-1]
    lo, hi = 0, len(sp) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if sp[mid] <= spline:
            lo = mid
        else:
            hi = mid
    span = sp[hi] - sp[lo]
    frac = 0.0 if span <= 1e-9 else (spline - sp[lo]) / span
    return lap.t_s[lo] + frac * (lap.t_s[hi] - lap.t_s[lo])


def _min_speed_in_window(lap: LapTrace, lo: float, hi: float) -> float:
    vals = [lap.v_ms[i] for i in range(len(lap)) if lo <= lap.spline[i] <= hi]
    return (min(vals) if vals else 0.0) * 3.6


def compare_laps(
    candidate: LapTrace,
    reference: LapTrace,
    *,
    corners: list[tuple[int, int, int]] | None = None,
) -> list[CornerDelta]:
    """Per-corner time/speed deltas of ``candidate`` vs ``reference`` (corners from the reference).

    Both laps are assumed to cover the same track with a monotone ``spline`` 0..1. Time is compared
    over each corner's spline window, so the deltas localize where the candidate gained/lost time.
    """
    if corners is None:
        corners = segment_corners(reference)
    out: list[CornerDelta] = []
    for idx, (entry_i, _apex_i, exit_i) in enumerate(corners):
        lo = reference.spline[entry_i]
        hi = reference.spline[exit_i]
        c_t = _interp_time(candidate, hi) - _interp_time(candidate, lo)
        r_t = _interp_time(reference, hi) - _interp_time(reference, lo)
        c_min = _min_speed_in_window(candidate, lo, hi)
        r_min = _min_speed_in_window(reference, lo, hi)
        out.append(
            CornerDelta(
                index=idx,
                spline_lo=round(lo, 4),
                spline_hi=round(hi, 4),
                cand_time_s=round(c_t, 3),
                ref_time_s=round(r_t, 3),
                delta_s=round(c_t - r_t, 3),
                cand_min_kmh=round(c_min, 1),
                ref_min_kmh=round(r_min, 1),
                min_speed_delta_kmh=round(c_min - r_min, 1),
            )
        )
    return out


# --- aero-vs-mechanical balance discriminator (the #1 verified rule) ---------
@dataclass(frozen=True)
class BalanceFinding:
    """Where a handling limitation lives across the speed range, and which lever class fixes it.

    The verified master discriminator: aero scales with v^2 (shows in HIGH-speed corners),
    mechanical balance is speed-flat (shows at ALL speeds, cleanest at LOW speed). A deficit in the
    high-speed band routes to AERO levers (wings; rake is car-dependent); one flat across the range
    routes to MECHANICAL levers (ARB / springs / diff). The under-vs-oversteer *direction* needs yaw
    and is NOT asserted from the archive — only the lever CLASS and speed band are.
    """

    verdict: str  # 'aero_limited_high_speed' | 'mechanical_all_speed' | 'balanced' | 'insufficient'
    lever_class: str  # AERO | MECHANICAL | ''
    low_band_grip_used: float | None
    high_band_grip_used: float | None
    low_band_time_lost_s: float | None
    high_band_time_lost_s: float | None
    n_low: int
    n_high: int
    coaching: str
    caveat: str


def analyze_balance(
    lap: LapTrace,
    sigs: list[CornerSignature] | None = None,
    *,
    deltas: list[CornerDelta] | None = None,
    grip_ceiling_g: float | None = None,
    speed_split_kmh: float = 120.0,
    saturation: float = 0.90,
) -> BalanceFinding:
    """Bin corners by apex speed and route a grip LIMITATION to the aero vs mechanical lever class.

    Primary signal is grip *saturation* (peak_lat_g / ceiling near 1.0 = the car is AT its limit in
    that band). The band that saturates sets the lever class: saturating in HIGH-speed corners → the
    limit is downforce-set → AERO; saturating in LOW-speed corners (aero negligible) → MECHANICAL.
    If a band is NOT saturated the car has grip in hand, so a deficit is technique, not balance.
    Time-loss per band is reported as context and is the fallback when no grip ceiling is given.
    Robust because it never asserts the (yaw-dependent) under-vs-oversteer direction.
    """
    if sigs is None:
        sigs = corner_signatures(lap)
    low = [s for s in sigs if s.min_speed_kmh < speed_split_kmh]
    high = [s for s in sigs if s.min_speed_kmh >= speed_split_kmh]
    dmap = {d.index: d for d in (deltas or [])}

    def grip_used(group: list[CornerSignature]) -> float | None:
        if not group or grip_ceiling_g is None or grip_ceiling_g <= 0:
            return None
        return round(sum(s.peak_lat_g for s in group) / len(group) / grip_ceiling_g, 3)

    def time_lost(group: list[CornerSignature]) -> float | None:
        ds = [dmap[s.index].delta_s for s in group if s.index in dmap]
        return round(sum(ds), 3) if ds else None

    lu, hu = grip_used(low), grip_used(high)
    lt, ht = time_lost(low), time_lost(high)
    caveat = (
        "Speed-band routing is robust; the under-vs-oversteer DIRECTION needs yaw (live yaw_rate "
        "or noisy position-derived heading) before naming front vs rear."
    )
    if not low or not high:
        return BalanceFinding(
            "insufficient",
            "",
            lu,
            hu,
            lt,
            ht,
            len(low),
            len(high),
            "Need corners in both speed bands to separate aero from mechanical.",
            caveat,
        )

    def finding(verdict: str, lever: str, coaching: str) -> BalanceFinding:
        return BalanceFinding(verdict, lever, lu, hu, lt, ht, len(low), len(high), coaching, caveat)

    # primary: which band is the car grip-limited (saturated) in?
    if lu is not None and hu is not None:
        low_sat, high_sat = lu >= saturation, hu >= saturation
        if high_sat and not low_sat:
            return finding(
                "aero_limited_high_speed",
                AERO,
                "Car is grip-limited in HIGH-speed corners (low-speed has grip in hand) → the "
                "limit is downforce-set. Use wings for an unambiguous shift (front wing up cuts "
                "high-speed understeer; rear wing up cuts high-speed snap); rake is car-dependent.",
            )
        if low_sat and not high_sat:
            return finding(
                "mechanical_all_speed",
                MECHANICAL,
                "Car is grip-limited in LOW-speed corners (aero negligible) → the limit is "
                "mechanical. If you're AT the limit there, use ARB/springs/diff (softer front cuts "
                "understeer; softer rear aids rotation/exit) — not wings. If you're NOT at the "
                "limit, it's technique (see the per-corner notes).",
            )
        if low_sat and high_sat:
            return finding(
                "grip_limited_all_speed",
                "",
                "Car reaches its grip limit across the speed range — well balanced; gains need "
                "more overall grip (tyres/compound/pressures) or driving closer to the limit.",
            )
        return finding(
            "not_grip_limited",
            "",
            "Grip is in hand in both speed bands — the time is in TECHNIQUE, not balance (carry "
            "more speed / brake later / get to power sooner — see per-corner notes).",
        )

    # fallback (no grip ceiling): use time-loss localization only, clearly hedged
    if ht is not None and lt is not None:
        if ht > lt + 0.05:
            return finding(
                "time_lost_high_speed",
                AERO,
                "Most time lost in HIGH-speed corners (no grip ceiling given, so this "
                "is localization, not a grip-limit verdict). Suspect aero if at limit.",
            )
        if lt > ht + 0.05:
            return finding(
                "time_lost_low_speed",
                MECHANICAL,
                "Most time lost in LOW-speed corners (no grip ceiling given). Suspect "
                "mechanical/technique; supply a grip ceiling to separate them.",
            )
    return finding(
        "balanced",
        "",
        "No clear speed-gating of the deficit. Supply a grip ceiling for a grip-limit verdict.",
    )


# --- diagnostic engine ------------------------------------------------------
@dataclass
class CornerContext:
    """Everything a rule needs to judge one corner."""

    sig: CornerSignature
    setup: CarSetup
    delta: CornerDelta | None = None  # vs a reference lap, if available
    grip_ceiling_g: float | None = None  # GGV/known lateral ceiling at this corner
    extra: dict[str, Any] = field(default_factory=dict)  # richer live signals (Tier-B)


@dataclass(frozen=True)
class DiagnosticRule:
    """One symptom→cause rule. ``test`` returns a confidence in [0, 1] (0 = no match)."""

    key: str
    symptom: str
    phase: str
    tier: str  # 'A' fires from archive; 'B' needs richer telemetry to fire at all
    channels_needed: tuple[str, ...]  # live channels that CONFIRM (flip advisory→verdict)
    test: Callable[[CornerContext], float]
    setup_causes: Callable[[CornerContext], list[str]]
    technique_causes: tuple[str, ...]
    coaching: Callable[[CornerContext], str]


@dataclass(frozen=True)
class Attribution:
    """A matched diagnosis for one corner."""

    key: str
    symptom: str
    phase: str
    tier: str
    confidence: float
    setup_causes: list[str]
    technique_causes: list[str]
    coaching: str
    advisory: bool  # True when the confirming live channels are absent (a suspicion, not a verdict)


def attribute_corner(
    ctx: CornerContext, rules: list[DiagnosticRule] | None = None, *, min_confidence: float = 0.25
) -> list[Attribution]:
    """Run the rule table over one corner; return matched diagnoses, most confident first."""
    if rules is None:
        rules = RULES
    out: list[Attribution] = []
    for rule in rules:
        # Let a rule's exceptions propagate (repo Rule 14: explicit errors over silent fallbacks).
        # Rules are pure functions over a well-typed CornerContext; a raise is a defect to fix, not
        # to hide behind a 0.0 confidence that would mask an incomplete diagnosis.
        conf = float(rule.test(ctx))
        if conf < min_confidence:
            continue
        have_channels = bool(rule.channels_needed) and all(
            c in ctx.extra for c in rule.channels_needed
        )
        advisory = bool(rule.channels_needed) and not have_channels
        out.append(
            Attribution(
                key=rule.key,
                symptom=rule.symptom,
                phase=rule.phase,
                tier=rule.tier,
                confidence=round(min(1.0, conf), 3),
                setup_causes=rule.setup_causes(ctx),
                technique_causes=list(rule.technique_causes),
                coaching=rule.coaching(ctx),
                advisory=advisory,
            )
        )
    out.sort(key=lambda a: a.confidence, reverse=True)
    return out


@dataclass
class CornerCoaching:
    """The coaching verdict for one corner."""

    index: int
    apex_spline: float
    min_speed_kmh: float
    delta_s: float | None
    headline: str
    attributions: list[Attribution]


def coach_lap(
    lap: LapTrace,
    setup: CarSetup,
    *,
    reference: LapTrace | None = None,
    grip_ceiling_g: float | None = None,
    extra_by_corner: dict[int, dict[str, Any]] | None = None,
    rules: list[DiagnosticRule] | None = None,
) -> list[CornerCoaching]:
    """Full per-corner coaching pass over a lap (optionally vs reference, optionally with setup)."""
    corners = segment_corners(lap)
    sigs = corner_signatures(lap, corners)
    deltas = compare_laps(lap, reference, corners=corners) if reference is not None else []
    by_idx = {d.index: d for d in deltas}
    out: list[CornerCoaching] = []
    for sig in sigs:
        # explicit caller-supplied signals win; else auto-compute Tier-B signals from per-wheel data
        extra = (extra_by_corner or {}).get(sig.index)
        if extra is None:
            extra = corner_live_signals(lap, sig) if lap.has_wheel_data else {}
        ctx = CornerContext(
            sig=sig,
            setup=setup,
            delta=by_idx.get(sig.index),
            grip_ceiling_g=grip_ceiling_g,
            extra=extra,
        )
        attrs = attribute_corner(ctx, rules)
        out.append(
            CornerCoaching(
                index=sig.index,
                apex_spline=sig.apex_spline,
                min_speed_kmh=round(sig.min_speed_kmh, 1),
                delta_s=ctx.delta.delta_s if ctx.delta else None,
                headline=_headline(ctx, attrs),
                attributions=attrs,
            )
        )
    return out


def _headline(ctx: CornerContext, attrs: list[Attribution]) -> str:
    where = f"C{ctx.sig.index} (apex {ctx.sig.apex_spline:.2f})"
    if ctx.delta is not None and ctx.delta.delta_s > 0.03:
        where += f": -{ctx.delta.delta_s:.2f}s vs reference"
    if not attrs:
        return f"{where}: on the pace — no clear deficit."
    top = attrs[0]
    tag = " (suspected — needs live telemetry)" if top.advisory else ""
    return f"{where}: {top.symptom}{tag} — {top.coaching}"


# --- grip helper ------------------------------------------------------------
def _grip_used_frac(ctx: CornerContext) -> float | None:
    if ctx.grip_ceiling_g is None or ctx.grip_ceiling_g <= 0:
        return None
    return ctx.sig.peak_lat_g / ctx.grip_ceiling_g


# --- Tier-B live signals: turn per-wheel data into CONFIRMED attribution ------
WHEEL_RADIUS_M = 0.347  # GT3 R effective rolling radius (session plant-ID)


def _slip(omega: float, r: float, v: float) -> float:
    """Longitudinal slip ratio (omega*r - v)/v: <0 = lock (braking), >0 = spin (power)."""
    return 0.0 if v < 0.5 else (omega * r - v) / v


def corner_live_signals(
    lap: LapTrace,
    sig: CornerSignature,
    *,
    wheel_radius_m: float = WHEEL_RADIUS_M,
    brake_thresh: float = 0.05,
    throttle_thresh: float = 0.2,
    lock_thresh: float = -0.06,
    spin_thresh: float = 0.10,
) -> dict[str, Any]:
    """Per-corner Tier-B signals from ``wheelAngularSpeed`` — which axle locks, exit wheelspin.

    Returns ``{}`` when the lap has no per-wheel data. When present, returns a dict carrying the
    confirming channel marker(s) plus ``lock_axle`` ('front'|'rear'|'both'|None) and ``wheelspin``,
    so the braking/exit rules graduate from a suspicion to a confirmed verdict. Slip is computed
    from angular speed (the canonical longitudinal signal), not AC's combined ``wheelSlip``.
    """
    if lap.wheel_omega is None:
        return {}
    extra: dict[str, Any] = {"wheelAngularSpeed": True}
    if lap.wheel_slip is not None:
        extra["wheelSlip"] = True

    def _axle_slip(om: list[float], a: int, b: int, v: float) -> float | None:
        # A 0.0 omega among real readings is the "unread wheel" sentinel (telemetry serializes a nil
        # read as 0), NOT a lock — a truly locked wheel at speed still has a small POSITIVE omega.
        # Exclude unread wheels so one failed corner can't fake a lockup (codex partial-read guard).
        vals = [_slip(om[i], wheel_radius_m, v) for i in (a, b) if om[i] > 0.0]
        return min(vals) if vals else None

    # braking phase (turn-in..apex with brake on): which axle reaches lock first?
    front, rear = [], []
    for k in range(sig.entry_i, sig.apex_i + 1):
        if lap.brake[k] > brake_thresh:
            v, om = lap.v_ms[k], lap.wheel_omega[k]
            f = _axle_slip(om, 0, 1, v)
            r = _axle_slip(om, 2, 3, v)
            if f is not None:
                front.append(f)
            if r is not None:
                rear.append(r)
    if front and rear:
        fl, rl = min(front), min(rear)
        extra["front_lock"], extra["rear_lock"] = round(fl, 3), round(rl, 3)
        if min(fl, rl) <= lock_thresh:
            extra["lock_axle"] = "front" if fl < rl - 0.02 else "rear" if rl < fl - 0.02 else "both"
        else:
            extra["lock_axle"] = None
    # exit phase (apex..exit with throttle on): rear wheelspin?
    spins = []
    for k in range(sig.apex_i, sig.exit_i + 1):
        if lap.throttle[k] > throttle_thresh:
            v, om = lap.v_ms[k], lap.wheel_omega[k]
            rear_spin = [_slip(om[i], wheel_radius_m, v) for i in (2, 3) if om[i] > 0.0]
            if rear_spin:
                spins.append(max(rear_spin))
    if spins:
        rmax = max(spins)
        extra["rear_exit_slip"] = round(rmax, 3)
        extra["wheelspin"] = rmax >= spin_thresh
    return extra


# ---------------------------------------------------------------------------
# Diagnostic rules — each is the adversarially-verified, red-team-corrected form.
# Conservatism is deliberate: archive localizes phase/speed-band; axle/pressure/TC
# attributions are suspicions until the named live channel is supplied.
# ---------------------------------------------------------------------------
def _r_grip_limited(ctx: CornerContext) -> float:
    used = _grip_used_frac(ctx)
    if used is None:
        return 0.0
    return 1.0 if used >= 0.97 else 0.6 if used >= 0.92 else 0.0


def _r_entry_speed_left(ctx: CornerContext) -> float:
    if ctx.delta is None or ctx.delta.min_speed_delta_kmh >= -2.0:
        return 0.0
    used = _grip_used_frac(ctx)
    if used is not None and used >= 0.95:
        return 0.0  # grip-limited, not a technique miss
    return min(1.0, 0.4 + (-ctx.delta.min_speed_delta_kmh) / 20.0)


def _r_braking_phase_loss(ctx: CornerContext) -> float:
    # lost time + the loss is in the braking phase (hard decel reached, steer still ~straight)
    if ctx.delta is None or ctx.delta.delta_s <= 0.05:
        return 0.0
    if ctx.sig.peak_brake_g < 0.6:
        return 0.0
    bp = ctx.sig.brake_point_spline
    # confirmed when per-wheel slip is present (axle attribution); else a localized suspicion
    return 0.7 if bp is not None else 0.4


def _r_exit_traction(ctx: CornerContext) -> float:
    a2t = ctx.sig.apex_to_throttle_m
    if a2t is None or a2t <= 14.0:
        return 0.0
    lost = ctx.delta is None or ctx.delta.delta_s > 0.03
    return min(1.0, 0.3 + (a2t - 8.0) / 30.0) if lost else 0.0


def _r_turn_in_lag(ctx: CornerContext) -> float:
    # very high steer for a modest-speed corner with grip in hand → sluggish turn-in (non-specific)
    if ctx.sig.max_abs_steer < 0.45:
        return 0.0
    used = _grip_used_frac(ctx)
    if used is not None and used >= 0.95:
        return 0.0
    return 0.35


def _exit_setup_causes(ctx: CornerContext) -> list[str]:
    spin = ctx.extra.get("wheelspin")
    if spin is True:  # CONFIRMED by per-wheel slip
        rs = ctx.extra.get("rear_exit_slip")
        out = [
            f"CONFIRMED rear wheelspin on exit (slip {rs}) → it's a TRACTION problem: squeeze the "
            "throttle later/softer, raise TC, or reduce DIFF_POWER lock.",
        ]
        if ctx.setup.tc_level is not None:
            out.append(f"TC is {ctx.setup.tc_level:.0f} — a notch up would catch this spin.")
        out.append("Rear wing only if the spin is at genuinely HIGH exit speed.")
        return out
    if spin is False:  # channel present, NO spin -> NOT traction
        return [
            "Per-wheel slip shows NO rear wheelspin — the exit loss is DIFF/TECHNIQUE, not "
            "traction: get to power earlier; if it pushes wide on power, open DIFF_POWER a touch.",
        ]
    # no per-wheel data -> ranked suspicion (the honest archive default)
    out = [
        "Lead with throttle technique + DIFF_POWER (on-throttle lock) — these dominate exit drive.",
        "Rear springs/dampers next; ARB_REAR matters mid-corner, not once you're straightening.",
    ]
    if ctx.setup.tc_level is not None:
        out.append(
            f"TC level {ctx.setup.tc_level:.0f}: if it is cutting power, lower it — needs live RPM/"
            "slip to confirm a torque cut vs over-throttle vs diff."
        )
    out.append("Rear wing only if the spin is at genuinely HIGH exit speed.")
    return out


def _braking_setup_causes(ctx: CornerContext) -> list[str]:
    bias = ctx.setup.brake_bias_pct
    bias_txt = (
        f"FRONT_BIAS is {bias:.0f}% front"
        + (
            " (a rear-engine 911 GT3 R usually wants ~50-56%)"
            if bias is not None and bias > 58
            else ""
        )
        if bias is not None
        else "brake bias not in this setup snapshot"
    )
    axle = ctx.extra.get("lock_axle", "__none__")
    if axle == "front":
        return [
            f"CONFIRMED: the FRONT axle locks first (slip {ctx.extra.get('front_lock')}) → bias is "
            f"too far forward. Move FRONT_BIAS rearward — {bias_txt}.",
        ]
    if axle == "rear":
        return [
            f"CONFIRMED: the REAR axle locks first (slip {ctx.extra.get('rear_lock')}) → bias is "
            f"too far rearward (snap-spin risk). Move FRONT_BIAS forward — {bias_txt}.",
        ]
    if axle in ("both", None):  # per-wheel data present, lock state known
        if axle == "both":
            return [
                f"CONFIRMED: both axles lock → reduce BRAKE_POWER_MULT / brake softer ({bias_txt})."
            ]
        return [
            "Per-wheel slip shows NO axle lock — the braking loss is a braking-POINT/modulation "
            f"TECHNIQUE issue, not bias ({bias_txt}).",
        ]
    # no per-wheel data -> honest suspicion
    return [
        "Investigate brake bias + brake modulation. Archive localizes the loss to the braking zone "
        "but CANNOT prove which axle locks — that needs per-wheel slip.",
        f"{bias_txt[0].upper()}{bias_txt[1:]}.",
    ]


def _braking_coaching(ctx: CornerContext) -> str:
    axle = ctx.extra.get("lock_axle", "__none__")
    if axle == "front":
        return "Front locking under braking (confirmed) — move brake bias rearward."
    if axle == "rear":
        return "Rear locking under braking (confirmed) — move brake bias forward."
    if axle == "both":
        return "Both axles lock (confirmed) — brake softer / lower brake power."
    if axle is None:
        return (
            "No axle lock (confirmed) — it's the braking POINT/modulation, not bias. Brake later."
        )
    return (
        "Losing time braking — investigate brake bias + modulation. Add live per-wheel slip to "
        "confirm which axle locks."
    )


def _exit_coaching(ctx: CornerContext) -> str:
    spin = ctx.extra.get("wheelspin")
    a2t = ctx.sig.apex_to_throttle_m or 0.0
    if spin is True:
        return "Rear wheelspin on exit (confirmed) — squeeze later/softer, raise TC or open diff."
    if spin is False:
        return (
            f"No wheelspin (confirmed) — {a2t:.0f} m apex-to-throttle is technique; "
            "get to power earlier."
        )
    return (
        f"{a2t:.0f} m from apex to throttle — get back to power earlier. Live per-wheel slip "
        "separates wheelspin from a TC cut from a diff push."
    )


RULES: list[DiagnosticRule] = [
    DiagnosticRule(
        key="grip_limited",
        symptom="at the grip limit",
        phase="mid",
        tier="A",
        channels_needed=("wheelsPressure",),  # pressure/compound confirmation
        test=_r_grip_limited,
        setup_causes=lambda c: [
            "Mechanical/aero grip is the ceiling — gains come from SETUP, not the line:",
            "tyre pressures toward the optimal hot window, a softer compound"
            + (
                f" (current idx {int(c.setup.compound_index)})"
                if c.setup.compound_index is not None
                else ""
            )
            + ", or more wing for fast corners.",
        ],
        technique_causes=("Driver is already using the available grip — little to gain here.",),
        coaching=lambda c: (
            "Car's at the limit mid-corner; to go faster change the setup (pressures/compound/"
            "wing), not the line. Confirm pressure/compound with live hot-pressure + core-temp."
        ),
    ),
    DiagnosticRule(
        key="entry_speed_left",
        symptom="carried too little apex speed",
        phase="entry",
        tier="A",
        channels_needed=(),  # pure kinematics — a verdict from the archive
        test=_r_entry_speed_left,
        setup_causes=lambda c: [],
        technique_causes=(
            "Grip was available — brake later / release sooner and carry more entry speed.",
        ),
        coaching=lambda c: (
            f"Apex {(-c.delta.min_speed_delta_kmh):.0f} km/h down with grip in hand — brake later "
            "and carry more speed in."
            if c.delta
            else "Grip available at apex — carry more speed."
        ),
    ),
    DiagnosticRule(
        key="braking_phase_loss",
        symptom="time lost under braking",
        phase="braking",
        tier="A",
        # 'lock_axle' is the COMPUTED signal (from wheelAngularSpeed) — present only when braking
        # was actually observed here, so confirmation never outruns the data (gemini #268).
        channels_needed=("lock_axle",),
        test=_r_braking_phase_loss,
        setup_causes=_braking_setup_causes,
        technique_causes=(
            "Threshold-brake: press harder at the top of the zone, then trail off smoothly.",
        ),
        coaching=_braking_coaching,
    ),
    DiagnosticRule(
        key="exit_traction",
        symptom="slow back to power on exit",
        phase="exit",
        tier="A",
        # 'wheelspin' is the COMPUTED signal (from wheelAngularSpeed) — present only when throttle
        # was actually observed on exit, so confirmation never outruns the data (gemini #268).
        channels_needed=("wheelspin",),
        test=_r_exit_traction,
        setup_causes=_exit_setup_causes,
        technique_causes=(
            "Squeeze the throttle progressively from the apex — pick the car up, then full power.",
        ),
        coaching=_exit_coaching,
    ),
    DiagnosticRule(
        key="turn_in_lag",
        symptom="sluggish turn-in",
        phase="entry",
        tier="A",
        channels_needed=("yaw_rate",),  # clean rotation signal confirms the lag
        test=_r_turn_in_lag,
        setup_causes=lambda c: [
            "Turn-in lag is NON-SPECIFIC. Rule out, in order: entry technique (no trail-brake, "
            "slow hands), cold / under-pressure fronts, then caster / front springs.",
            "Front toe-out is a LAST, small lever (it scrubs top speed) — not the first thing to "
            "change.",
        ],
        technique_causes=(
            "Trail-brake to load the front on entry and use a quicker, deliberate initial input.",
        ),
        coaching=lambda c: (
            "Sluggish turn-in (heading lags steer) — likely technique or front load, not "
            "necessarily toe. Confirm with live yaw-rate."
        ),
    ),
]
