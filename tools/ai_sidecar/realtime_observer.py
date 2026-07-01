"""Real-time observer: stream live telemetry frames → brain-grounded per-corner advisories.

The offline-buildable core of the live coaching path (north star: an AI that coaches a human in
real time). It consumes a stream of live frames — ``{spline, speed, brake, throttle, ...}`` as
``telemetry.lua`` emits per tick — and, grounded in the per-corner reference envelope from
:mod:`track_reference`, emits deduped advisories:

* **late-brake** — the car passed a corner's corpus-best brake point without braking → "brake".
* **apex deficit** — on corner exit, the min speed carried vs the corpus-best target apex.

Honesty (same guardrails as the offline brain):
* The reference is the **corpus best** of supplied laps, NOT a fabricated GGV theoretical optimum —
  ``build_observer_from_reference`` labels it accordingly and never invents a ceiling from a driven
  lap (cf. :mod:`track_reference` + the #244 frontier diagnostics).
* Advisories are *deduped per corner pass* and reset on lap wrap, so the live stream is not spammed.

Live wiring into the sidecar (consuming ``telemetry_tick`` and sending advisories back to the rig)
is issue #277 and is rig-gated; this module is pure stdlib and replay-testable offline. The live
frame contract here mirrors ``telemetry.lua``'s ``TelemetrySample``: ``speed`` is km/h.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from tools.ai_sidecar.lap_dynamics import LapTrace, lap_trace_from_archive
from tools.ai_sidecar.track_reference import (
    CornerReference,
    add_corpus_lap,
    build_references,
)

#: Spline drop between consecutive frames that signals a backward jump (wrap OR same-lap rewind).
_LAP_WRAP_DROP = 0.5
#: A backward jump is a true start/finish wrap only if it crosses the line: prev high, current low.
#: Other big backward jumps (teleport / pit reset / replay rewind) are NOT a lap completion, so we
#: clear state WITHOUT grading the abandoned corner (mirrors delta.lua's wrap-vs-rolling-reset).
_WRAP_PREV_MIN = 0.8
_WRAP_CUR_MAX = 0.25
#: km/h a corner exit must be under the target before it's worth an advisory.
_DEFICIT_MARGIN_KMH = 2.0
#: brake pedal fraction above which we consider the driver "on the brakes".
_BRAKE_ON = 0.05
#: throttle pedal fraction above which we consider the driver "on the power".
_THROTTLE_ON = 0.1

# --- Intensity model (issue #368) -----------------------------------------------------------------
# The observer computes a continuous severity scalar ``s ∈ [0,1]`` for each cue from telemetry +
# the reference envelope, then quantizes it to a tone ``register`` (calm|alert|urgent|critical) with
# hysteresis. ``register`` is what the manifest keys on; ``intensity`` (the float) rides on the
# Advisory too (logs, haptics, the timing report). These constants are documented TUNING references,
# NOT fabricated physical ceilings (the project's honesty invariant): they set how aggressively the
# tone escalates, not a claim about the car.

#: km/h above a corner's apex target that counts as "fully hot" (severity closing term saturates).
_CLOSING_REF_KMH = 35.0
#: km/h of apex-speed deficit that counts as "egregious" (apex_deficit severity saturates).
_DEFICIT_REF_KMH = 18.0
#: brake fraction past the apex that flags over-braking (the ``brake_release`` cue).
_RELEASE_BRAKE_MIN = 0.45
#: seconds of anticipatory lead — a cue fires this far (in time, converted to spline) BEFORE its
#: mark so the audio ONSET lands before/at the control point, not after (issue #368 AC a).
_LEAD_S = 0.8
#: default track length (m) for the lead-time → spline conversion when a track length is not
#: supplied.
_DEFAULT_TRACK_LENGTH_M = 2500.0
#: public constructor default for the configurable brake lead.
_BRAKE_PREPARE_LEAD_S = _LEAD_S
#: cap on the anticipatory lead in spline units, so a very fast straight cannot fire a corner cue
#: half a lap early.
_MAX_LEAD_SPLINE = 0.05
#: Schmitt-trigger thresholds for register quantization (rising / falling) — the falling edge
#: sits below the rising edge so a severity hovering near a boundary does not flicker tone
#: frame-to-frame.
_REG_ALERT_RISE, _REG_ALERT_FALL = 0.25, 0.18
_REG_URGENT_RISE, _REG_URGENT_FALL = 0.55, 0.46
_REG_CRIT_RISE, _REG_CRIT_FALL = 0.82, 0.72


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _register_for(s: float, prev: str, *, cap: str = "critical") -> str:
    """Quantize a severity scalar ``s ∈ [0,1]`` to a tone register, with hysteresis + a per-kind
    cap.

    Pure function (``prev`` register in → next register out), mirroring the scheduler's pure-core
    discipline so it is unit-testable with no telemetry. Hysteresis: the rising thresholds are above
    the falling ones, so a severity hovering on a boundary holds its tier instead of flickering. The
    ``cap`` clamps the result for cues whose tone must not reach the top tier (e.g. a slow-loss cue
    that should never sound like an alarm).
    """
    prev = "urgent" if prev == "firm" else prev
    cap = "urgent" if cap == "firm" else cap
    cap_rank = REGISTER_RANK.get(cap, REGISTER_RANK["critical"])
    prev_rank = REGISTER_RANK.get(prev, 0)
    if s >= _REG_CRIT_RISE or (prev_rank >= REGISTER_RANK["critical"] and s >= _REG_CRIT_FALL):
        out = "critical"
    elif s >= _REG_URGENT_RISE or (prev_rank >= REGISTER_RANK["urgent"] and s >= _REG_URGENT_FALL):
        out = "urgent"
    elif s >= _REG_ALERT_RISE or (prev_rank >= REGISTER_RANK["alert"] and s >= _REG_ALERT_FALL):
        out = "alert"
    else:
        out = "calm"
    if REGISTER_RANK[out] > cap_rank:
        out = cap
    return out


#: Register ordering (low → high) for the cap/hysteresis comparisons above.
REGISTER_RANK: dict[str, int] = {"calm": 0, "alert": 1, "urgent": 2, "critical": 3}
#: urgency a given register rides on: a calm heads-up is anticipatory (``prepare``);
#: alert/urgent/critical correction must be acted on now (``act``). Keeps tone and scheduling
#: correlated but distinct — the scheduler still arbitrates on urgency alone.
_URGENCY_FOR_REGISTER: dict[str, str] = {
    "calm": "prepare",
    "alert": "act",
    "urgent": "act",
    "critical": "act",
}


def _target_source(ref: CornerReference) -> str:
    """Honest provenance of a corner's target apex (mirrors track_reference.score_lap).

    The realistic, demonstrated corpus best when one exists; otherwise the GGV theoretical optimum
    (a *ceiling*, not a guaranteed-achievable number). Never label a GGV optimum as corpus-observed.
    """
    return "corpus_best" if ref.best_observed_apex_kmh is not None else "ggv_optimum"


@dataclass
class Advisory:
    """One real-time coaching cue, machine-readable + human string.

    ``intensity`` / ``register`` (issue #368): ``intensity`` is the continuous severity scalar
    ``s ∈ [0,1]`` the observer computed for the situation; ``register`` is its quantized tone tier
    (calm|alert|urgent|critical), which the voice path keys on so the SPOKEN TONE reflects the
    situation ("not just 'turn left'"). Both default to the calm/zero base so every existing
    construction and the server's ``_advisory_to_payload`` keep working.
    """

    kind: str  # "late_brake" | "brake_release" | "turn_in" | "apex_deficit"
    corner: int
    spline: float
    urgency: str  # "info" | "prepare" | "act"
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    intensity: float = 0.0
    register: str = "calm"


@dataclass
class _CornerPass:
    """Mutable per-corner state for the current lap pass (reset on wrap)."""

    inside: bool = False
    min_speed_kmh: float | None = None
    has_braked: bool = False  # any braking seen this pass — suppresses a false late-brake cue
    #: rank of the HIGHEST brake-cue register emitted this pass (-1 = none). A cue re-fires only
    #: when severity escalates to a strictly higher tier (calm→alert→urgent→critical), so a calm
    #: lead-in never locks out the later critical alarm (issue #368 escalation; codex review #371).
    brake_cue_rank: int = -1
    #: rank of the highest brake-release register emitted this pass. A barely-over-threshold
    #: release warning can still escalate to urgent if the driver stays hard on the brake.
    release_cue_rank: int = -1
    exit_emitted: bool = False
    #: last tone register spoken for this corner pass — feeds register hysteresis (issue #368).
    last_register: str = "calm"


def _num(value: Any) -> float | None:
    """Parse to a finite float, else None (rejects NaN/±inf and bools)."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _normalize_frame(
    frame: dict[str, Any],
) -> tuple[float | None, float | None, float, float, float | None]:
    """Extract ``(spline, speed_kmh, brake, throttle, lap)`` from the offline replay or the live
    ``telemetry_tick`` shape.

    The replay/test shape carries ``spline``/``speed``/``brake``/``throttle`` at the top level; the
    live high-rate frame (``external_protocol._validate_telemetry_tick``) nests values under
    ``payload`` with speed named ``speed_kmh``. We accept both so the live wiring hands us the real
    frame without a translation shim. The live producer (``telemetry_publisher.lua``) DOES emit
    ``spline`` (and ``throttle``) in the payload (validated by
    ``external_protocol._validate_telemetry_tick`` as ``spline`` 0..1, ``throttle`` required), so
    the observer locates corners on the live rig today — ``throttle`` was the only field the
    producer sent that this normalizer previously dropped (issue #368). ``lap`` (the completed-lap
    counter, when present) disambiguates a real lap completion from a pit/teleport.
    """
    payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}

    def pick(*keys: str) -> Any:
        for src in (frame, payload):
            for k in keys:
                if k in src:
                    return src[k]
        return None

    spline = _num(pick("spline", "normalizedSplinePosition"))
    speed = _num(pick("speed", "speed_kmh"))
    brake = _num(pick("brake")) or 0.0
    throttle = _num(pick("throttle", "gas")) or 0.0
    lap = _num(pick("lap", "lapCount", "lap_count", "completedLaps", "completed_laps"))
    return spline, speed, brake, throttle, lap


def _forward_spline_delta(current: float, target: float) -> float:
    """Forward normalized distance from ``current`` to ``target`` in [0, 1)."""
    return (target - current) % 1.0


def _in_arc(x: float, lo: float, hi: float) -> bool:
    """True if normalized spline ``x`` is in the arc ``[lo, hi]``, wrap-aware (``lo`` may exceed
    ``hi`` when the arc crosses the start/finish line)."""
    if lo <= hi:
        return lo <= x <= hi
    return x >= lo or x <= hi


def _lead_spline_fraction(speed_kmh: float, track_length_m: float, lead_s: float) -> float:
    """Convert a speed/time lead into normalized spline distance."""
    if speed_kmh <= 0.0 or lead_s <= 0.0:
        return 0.0
    if track_length_m <= 0.0:
        track_length_m = _DEFAULT_TRACK_LENGTH_M
    return max(0.002, min(_MAX_LEAD_SPLINE, (speed_kmh / 3.6) * lead_s / track_length_m))


def _positive_track_length_m(value: Any) -> float:
    if isinstance(value, bool):
        return _DEFAULT_TRACK_LENGTH_M
    try:
        track_length_m = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_TRACK_LENGTH_M
    return (
        track_length_m
        if math.isfinite(track_length_m) and track_length_m > 0.0
        else _DEFAULT_TRACK_LENGTH_M
    )


class RealtimeObserver:
    """Stateful streaming observer over the per-corner reference envelope.

    Feed it one live frame at a time via :meth:`observe`; it returns the advisories (0+) triggered
    by that frame. State is per-corner-pass and resets automatically on lap wrap (or via
    :meth:`reset`). The observer never raises on a malformed frame — it skips frames whose spline or
    speed cannot be read.
    """

    def __init__(
        self,
        references: list[CornerReference],
        *,
        deficit_margin_kmh: float = _DEFICIT_MARGIN_KMH,
        brake_on: float = _BRAKE_ON,
        track_length_m: float | None = _DEFAULT_TRACK_LENGTH_M,
        brake_prepare_lead_s: float = _BRAKE_PREPARE_LEAD_S,
        lap_length_m: float | None = None,
    ) -> None:
        # sorted by entry so the in/out-of-window scan is stable
        self._refs = sorted(references, key=lambda r: r.spline_lo)
        self._deficit_margin = deficit_margin_kmh
        self._brake_on = brake_on
        # Track length lets us convert an anticipatory time-lead into a spline distance so a cue's
        # audio onset lands before/at its mark (issue #368 AC a). ``lap_length_m`` is kept as a
        # keyword alias for PR-branch callers; current main uses ``track_length_m``.
        self._track_length_m = _positive_track_length_m(
            lap_length_m if lap_length_m is not None else track_length_m
        )
        self._brake_prepare_lead_s = max(0.0, brake_prepare_lead_s)
        self._passes: dict[int, _CornerPass] = {r.index: _CornerPass() for r in self._refs}
        self._last_spline: float | None = None
        self._last_lap: float | None = None  # monotonic lap counter (when the stream supplies it)
        # end-of-lap grading held across the wrap when a known lapCount may lag the spline drop by
        # a frame (delta.lua defers); confirmed on a later counter advance, discarded on drive-on.
        self._pending_wrap: list[Advisory] = []
        self._pending_pre_lap: float | None = None

    def reset(self) -> None:
        """Clear per-corner pass state (start of a fresh lap). The lap counter persists."""
        self._passes = {r.index: _CornerPass() for r in self._refs}
        self._last_spline = None
        self._pending_wrap = []
        self._pending_pre_lap = None

    def observe(self, frame: dict[str, Any]) -> list[Advisory]:
        """Process one live frame; return the advisories it triggers (possibly empty)."""
        spline, speed, brake, throttle, lap = _normalize_frame(frame)
        if spline is None or speed is None:
            return []

        out: list[Advisory] = []
        # Resolve a wrap whose grading we deferred (a true wrap's lapCount can lag the drop by a
        # frame). Confirm the moment the counter advances; discard once the car has driven on past
        # the wrap zone without an advance (that was a pit/teleport, not a lap).
        if self._pending_wrap:
            if (
                lap is not None
                and self._pending_pre_lap is not None
                and lap > self._pending_pre_lap
            ):
                out.extend(self._pending_wrap)
                self._pending_wrap = []
                self._pending_pre_lap = None
            elif spline > _WRAP_CUR_MAX:
                self._pending_wrap = []
                self._pending_pre_lap = None
        # A backward spline jump is either a true start/finish wrap or a same-lap rewind
        # (pit/teleport/replay). Shape alone is ambiguous — a return-to-pits also lands near the
        # line — so grade end-of-lap ONLY on real lap-completion evidence: an authoritative
        # lap-counter advance, or, when no counter is supplied, a wrap-shaped jump. A wrap-shaped
        # jump with a KNOWN counter that hasn't advanced YET is deferred (the advance may arrive a
        # frame late, per delta.lua); a real pit/teleport never advances it and is discarded above.
        if self._last_spline is not None and self._last_spline - spline > _LAP_WRAP_DROP:
            lap_known = lap is not None and self._last_lap is not None
            lap_advanced = lap_known and lap > self._last_lap
            wrap_shaped = self._last_spline >= _WRAP_PREV_MIN and spline <= _WRAP_CUR_MAX
            graded: list[Advisory] = []
            for ref in self._refs:
                st = self._passes[ref.index]
                if st.inside and not st.exit_emitted:
                    a = self._apex_deficit(ref, st)
                    if a is not None:
                        graded.append(a)
            pre_lap = self._last_lap
            self.reset()
            if lap_advanced or (wrap_shaped and not lap_known):
                out.extend(graded)  # definite lap completion → grade now
            elif wrap_shaped and lap_known:
                self._pending_wrap = graded  # ambiguous → defer until the counter advances
                self._pending_pre_lap = pre_lap
        self._last_spline = spline
        if lap is not None:
            self._last_lap = lap

        for ref in self._refs:
            st = self._passes[ref.index]
            # Braking-evaluation region: from the (corpus/GGV) brake point to the apex — which may
            # begin UPSTREAM of the lateral-g corner window, so a driver coasting past the real
            # brake point is cued there, not only once the window starts (codex #294 @176). The
            # window now opens a tone-register-independent anticipatory LEAD before the brake point
            # so the cue's audio onset lands before/at the mark (issue #368 AC a).
            bp = ref.best_brake_point_spline
            if bp is not None:
                lead = _lead_spline_fraction(
                    speed, self._track_length_m, self._brake_prepare_lead_s
                )
                lead_start = (bp - lead) % 1.0
                wrapped_lead = bp - lead < 0.0 and spline >= lead_start
                if wrapped_lead and (
                    st.inside
                    or st.has_braked
                    or st.brake_cue_rank >= 0
                    or st.release_cue_rank >= 0
                    or st.exit_emitted
                ):
                    # For a first-corner brake point near 0.0, the next lap's lead window starts
                    # before the spline wrap is observed (for example at s=0.995). Reset this
                    # corner's previous-lap cue state now so the anticipatory cue can still lead
                    # the mark instead of being suppressed until after start/finish.
                    self._passes[ref.index] = st = _CornerPass()
                if bp <= spline <= ref.apex_spline and brake >= self._brake_on:
                    st.has_braked = True  # so a later release before apex isn't "late to brake"
                # The actionable window runs from the anticipatory lead (which can wrap over
                # start/finish for a first corner with bp≈0) through the apex (codex review #371).
                if _in_arc(spline, lead_start, ref.apex_spline):
                    a = self._brake_cue(ref, st, spline, speed, brake)
                    if a is not None:
                        out.append(a)
            # Over-braking past the apex while still off-throttle → "release / ease" (#368). Needs
            # only the apex/window + brake/throttle, NOT a brake point — so it fires for GGV-only
            # references (no corpus brake point) too (codex review #371).
            a = self._brake_release(ref, st, spline, speed, brake, throttle)
            if a is not None:
                out.append(a)
            in_window = ref.spline_lo <= spline <= ref.spline_hi
            if in_window:
                st.inside = True
                st.min_speed_kmh = (
                    speed if st.min_speed_kmh is None else min(st.min_speed_kmh, speed)
                )
                if brake >= self._brake_on:
                    st.has_braked = True
            elif st.inside and spline > ref.spline_hi and not st.exit_emitted:
                # just left the corner (downstream of exit) → grade the apex
                a = self._apex_deficit(ref, st)
                st.inside = False
                if a is not None:
                    out.append(a)
        return out

    def _brake_severity(self, ref: CornerReference, spline: float, speed: float) -> float:
        """Severity ``s ∈ [0,1]`` for a brake cue — how urgent the "brake" should sound (issue
        #368).

        Two grounded terms: how far through the braking zone the car is without braking (proximity /
        lateness, 0 at the brake point → 1 at the apex; clamped to 0 before the point during the
        anticipatory lead) and the closing speed above the corner's apex target (a car arriving much
        faster than the reference apex needs a firmer cue). Both come from real telemetry + the
        reference envelope — no fabricated ceiling.
        """
        bp = ref.best_brake_point_spline
        if bp is None:
            return 0.0
        zone = max(ref.apex_spline - bp, 1e-6)
        progress = _clamp01((spline - bp) / zone)  # 0 at/before bp, 1 at apex
        closing = _clamp01((speed - ref.target_apex_kmh) / _CLOSING_REF_KMH)
        return _clamp01(0.45 * progress + 0.55 * closing)

    def _brake_cue(
        self, ref: CornerReference, st: _CornerPass, spline: float, speed: float, brake: float
    ) -> Advisory | None:
        """Fire an anticipatory brake cue whose TONE register reflects the situation (#368).

        Fires when the car is within the actionable brake window (from the anticipatory lead before
        the brake point through the apex) and is not yet braking. The register
        (calm|alert|urgent|critical) comes from :meth:`_brake_severity`, so a car arriving on pace
        gets a calm anticipatory
        "brake point" while a car carrying far too much speed — or coasting past the point — gets a
        alert/urgent/critical "Brake." / "Brake!".

        **Escalation (codex review #371):** the cue re-fires within one pass only when severity
        rises to a *strictly higher* register (calm→alert→urgent→critical), so a calm lead-in never
        suppresses the later urgent alarm; the scheduler's register-keyed dedup + act barge-in
        deliver the escalation. A same- or lower-tier repeat is dropped.

        Suppressed once the driver has braked anywhere in this pass (``has_braked``): braking early
        and trailing off before the apex — normal trail-brake / rotation — is not a fault and must
        not draw a cue (codex #294).
        """
        bp = ref.best_brake_point_spline
        if bp is None or st.has_braked:
            return None
        if brake >= self._brake_on:
            # Braking inside the anticipatory lead (before the brake point) IS braking this pass —
            # record it so a later release-and-coast does not draw a false late-brake alarm
            # (codex review #371). Mirrors the in-window has_braked latch.
            st.has_braked = True
            return None
        s = self._brake_severity(ref, spline, speed)
        # "anticipatory" = the car has not yet reached the brake point — robust to a lead window
        # wraps over start/finish (a first corner with bp≈0): the forward distance to bp is a small
        # positive value (≤ lead), not a negative linear delta (codex review #371).
        anticipatory = 0.0 < _forward_spline_delta(spline, bp) <= _LAP_WRAP_DROP
        # BEFORE the brake point it is a calm anticipatory heads-up regardless of closing speed (the
        # driver hasn't missed anything yet — main's `brake_prepare` contract). Severity-based
        # escalation (alert/urgent/critical) applies only AT/PAST the point, where coasting on is a
        # real fault (#368 escalation; preserves the merged main brake_prepare semantics).
        register = "calm" if anticipatory else _register_for(s, st.last_register, cap="critical")
        rank = REGISTER_RANK[register]
        if rank <= st.brake_cue_rank:
            return None  # not an escalation — already cued this tier (or higher) this pass
        st.brake_cue_rank = rank
        urgency = _URGENCY_FOR_REGISTER[register]
        st.last_register = register
        lead_s = (
            _forward_spline_delta(spline, bp) * self._track_length_m / max(speed / 3.6, 0.1)
            if anticipatory
            else 0.0
        )
        return Advisory(
            kind="late_brake",
            corner=ref.index,
            spline=round(bp if anticipatory else spline, 4),
            urgency=urgency,
            intensity=round(s, 3),
            register=register,
            # +1: CornerReference.index is 0-based; user-facing turn labels are 1-based (T1..)
            message=(
                f"Brake point for T{ref.index + 1} coming up — brake."
                if anticipatory
                else f"Past your brake point for T{ref.index + 1} and still coasting — brake."
            ),
            detail={
                "brake_point_spline": round(bp, 4),
                "lead_s": round(lead_s, 2),
                "current_kmh": round(speed, 1),
                "anticipatory": anticipatory,
                "source": _target_source(ref),
            },
        )

    def _brake_release(
        self,
        ref: CornerReference,
        st: _CornerPass,
        spline: float,
        speed: float,
        brake: float,
        throttle: float,
    ) -> Advisory | None:
        """Fire once when the car is over-braking PAST the apex while still off-throttle (issue
        #368).

        Heavy braking after the apex (still off the power) scrubs exit speed instead of releasing
        toward the throttle. Gated conservatively on a HIGH brake level and no throttle so a normal
        trail-brake release is not flagged. Register caps at urgent (a clear correction, never an
        alarm), but can start calm near the threshold and escalate if braking stays heavy.
        """
        past_apex = ref.apex_spline < spline <= ref.spline_hi
        if not past_apex or brake < _RELEASE_BRAKE_MIN or throttle >= _THROTTLE_ON:
            return None
        s = _clamp01((brake - _RELEASE_BRAKE_MIN) / max(1.0 - _RELEASE_BRAKE_MIN, 1e-6))
        register = _register_for(s, st.last_register, cap="urgent")  # a correction, never an alarm
        rank = REGISTER_RANK[register]
        if rank <= st.release_cue_rank:
            return None
        st.release_cue_rank = rank
        st.last_register = register
        return Advisory(
            kind="brake_release",
            corner=ref.index,
            spline=round(spline, 4),
            urgency=_URGENCY_FOR_REGISTER[register],
            intensity=round(s, 3),
            register=register,
            message=f"Still hard on the brakes past the T{ref.index + 1} apex — ease off.",
            detail={"brake": round(brake, 3), "current_kmh": round(speed, 1)},
        )

    def _apex_deficit(self, ref: CornerReference, st: _CornerPass) -> Advisory | None:
        """On corner exit, compare the min speed carried to the target apex (corpus best / GGV)."""
        st.exit_emitted = True
        if st.min_speed_kmh is None:
            return None
        target = ref.target_apex_kmh
        deficit = round(target - st.min_speed_kmh, 1)
        if deficit < self._deficit_margin:
            return None
        source = _target_source(ref)
        # be honest about what the target IS: a demonstrated corpus best vs a GGV theoretical
        # ceiling (which the live TC-off car may not reach — see the #244 frontier diagnostics).
        target_label = "the best lap" if source == "corpus_best" else "the GGV optimum (a ceiling)"
        # Severity from the magnitude of the deficit; register capped at calm (a slow-loss verdict
        # is never an alarm). This is the suppressible heads-up — it rides `info` urgency so LOW
        # verbosity drops it from voice (issue #368 AC e: no post-fact narration in low verbosity).
        s = _clamp01(deficit / _DEFICIT_REF_KMH)
        register = _register_for(s, st.last_register, cap="calm")  # a verdict, never an alarm
        st.last_register = register
        return Advisory(
            kind="apex_deficit",
            corner=ref.index,
            spline=round(ref.apex_spline, 4),
            urgency="info",
            intensity=round(s, 3),
            register=register,
            message=(
                f"T{ref.index + 1}: carried {deficit:.0f} km/h under {target_label} "
                f"({st.min_speed_kmh:.0f} vs {target:.0f}) — more entry speed if grip allows."
            ),
            detail={
                "min_speed_kmh": round(st.min_speed_kmh, 1),
                "target_apex_kmh": round(target, 1),
                "deficit_kmh": deficit,
                "source": source,
            },
        )


def _frames_from_lap_trace(lap: LapTrace) -> list[dict[str, Any]]:
    """Replay a LapTrace as a frame stream (offline harness for the observer)."""
    return [
        {
            "spline": lap.spline[i],
            "speed": lap.v_kmh[i],
            "brake": lap.brake[i],
            "throttle": lap.throttle[i],
        }
        for i in range(len(lap))
    ]


def build_observer_from_reference(reference_archive: dict) -> RealtimeObserver | None:
    """Build an observer whose target envelope is the corpus best of a (faster) reference lap.

    The reference lap is treated as the corpus best — the realistic, demonstrated target — NOT a
    GGV theoretical ceiling (we never fabricate one from a driven lap). Returns None when the
    archive has no usable trace or no segmentable corners.
    """
    if not isinstance(reference_archive, dict):
        return None
    generator = reference_archive.get("generator")
    tt_reference = generator.get("tt_reference") if isinstance(generator, dict) else None
    if isinstance(tt_reference, dict) and tt_reference.get("partial") is True:
        return None
    try:
        ref_lap = lap_trace_from_archive(reference_archive)
    except ValueError:
        return None
    refs = build_references(ref_lap)
    if not refs:
        return None
    add_corpus_lap(refs, ref_lap)  # the reference lap IS the corpus best
    track_obj = reference_archive.get("track")
    track = track_obj if isinstance(track_obj, dict) else {}
    return RealtimeObserver(refs, track_length_m=_positive_track_length_m(track.get("lengthM")))
