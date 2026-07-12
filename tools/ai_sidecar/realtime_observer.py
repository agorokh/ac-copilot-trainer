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
from tools.ai_sidecar.registers import REGISTER_RANK, normalize_register
from tools.ai_sidecar.track_reference import (
    CornerReference,
    add_corpus_lap,
    build_references,
    sustained_brake_onsets,
)

#: Spline drop between consecutive frames that signals a backward jump (wrap OR same-lap rewind).
_LAP_WRAP_DROP = 0.5
#: A backward jump is a true start/finish wrap only if it crosses the line: prev high, current low.
#: Other big backward jumps (teleport / pit reset / replay rewind) are NOT a lap completion, so we
#: clear state WITHOUT grading the abandoned corner (mirrors delta.lua's wrap-vs-rolling-reset).
_WRAP_PREV_MIN = 0.8
_WRAP_CUR_MAX = 0.25
#: frames a deferred (ambiguous) wrap may stay unresolved before it is treated as a pit return.
#: A true wrap's lap counter advances within ~1 frame (delta.lua defers by at most one); a pit
#: return can idle near the line for many frames, and its carried first-corner state must be
#: reverted BEFORE the car reaches the mark, not only at the 0.25-spline drive-on discard
#: (PR #525 review).
_WRAP_CONFIRM_MAX_FRAMES = 3
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
#: seconds of anticipatory lead — the full AUDIBILITY BUDGET, not just an onset head start.
#: A cue is coaching only if it FINISHES SOUNDING early enough for a human to act before the
#: mark (issue #522: with the old 0.8 s lead, 0/8 brake cues in an instrumented lap were
#: actionable — every one finished after the brake point). Budget: prepare-clip duration
#: (~1.3 s) + audio-path latency (0.1 s PC / 0.45 s tablet) + auditory comprehension-and-
#: reaction (~1.2 s) + margin ≈ 3.2 s before the mark.
_LEAD_S = 3.2
#: default track length (m) for the lead-time → spline conversion when a track length is not
#: supplied.
_DEFAULT_TRACK_LENGTH_M = 2500.0
#: public constructor default for the configurable brake lead.
_BRAKE_PREPARE_LEAD_S = _LEAD_S
#: cap on the anticipatory lead in spline units, so a very fast straight cannot fire a corner cue
#: half a lap early. 0.09 ≈ 220 m on a 2.5 km track — covers the 3.2 s budget up to ~250 km/h
#: while still firmly local to the corner (issue #522 raised it with the lead).
_MAX_LEAD_SPLINE = 0.09
#: #522 design note: there is deliberately NO live brake-fault imperative. A driver braking
#: exactly at the mark is indistinguishable from one about to miss it until the mark itself,
#: so a spoken correction is either a false alarm or after-the-fact noise. The live cue is
#: the calm anticipatory heads-up above; a missed brake point is owned by corner-exit
#: grading ("brake earlier next lap") where feedback is actionable for the NEXT pass.
#: Braking observed within this many seconds of the brake point counts as braking FOR that
#: corner (suppresses its heads-up); farther out it is likely trail-braking the previous
#: corner inside an overlapping #522 lead window and must not latch (PR #523 review).
_LEAD_LATCH_TTA_S = 1.5

# --- Per-driver brake-mark calibration (issue #522 part 2) ---------------------------------------
# The shipped reference is a synthetic ideal lap whose brake points sit ~25 m from where a real
# driver on a real line brakes, so a fixed mark misclassifies an on-pace driver every pass. Each
# completed VALID lap of the driver's own folds into a per-zone EMA of their demonstrated brake
# onsets; once a zone has been observed, the cue mark (and the late/"ran deep" judgement) anchors
# on the driver's demonstrated point instead of the synthetic one. Provenance rides on the
# advisory (``mark_source: driver_calibrated``) — a calibrated mark is never passed off as the
# reference's.
#: a driver onset within this many METERS of a mark is the SAME zone; farther away it is a
#: different line/zone and does not calibrate. Metric, not normalized: a fixed spline fraction
#: would accept ~400 m on a Nordschleife-length track (PR #525 review). Converted per observer
#: via its track length (0.02 spline on the verified 2.5 km case).
_CAL_MATCH_TOL_M = 50.0
#: weight of the newest lap in the per-zone EMA (recent laps dominate, old habits decay).
_CAL_EMA_ALPHA = 0.4
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
    prev = normalize_register(prev)
    cap = normalize_register(cap)
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
    """Mutable per-corner state for the current lap pass (reset on wrap).

    Brake-cue state is PER ZONE (issue #522 coverage): a merged esses corner holds several real
    brake zones, and braking for / being cued about one zone must not consume the next zone's
    heads-up. The three parallel lists are indexed by the corner's zone ordinal.
    """

    inside: bool = False
    min_speed_kmh: float | None = None
    #: per zone: braking observed FOR that zone this pass — suppresses its heads-up.
    zone_braked: list[bool] = field(default_factory=list)
    #: per zone: the one calm anticipatory heads-up was emitted (or locked out past the mark).
    zone_cued: list[bool] = field(default_factory=list)
    #: rank of the highest brake-release register emitted this pass. A barely-over-threshold
    #: release warning can still escalate to urgent if the driver stays hard on the brake.
    release_cue_rank: int = -1
    #: the driver ran too deep past a brake mark for a spoken imperative to be actionable
    #: (issue #522) — the pass stayed silent and the miss is surfaced in exit grading instead.
    late_uncoached: bool = False
    exit_emitted: bool = False
    #: last tone register spoken for this corner pass — feeds register hysteresis (issue #368).
    last_register: str = "calm"
    #: this pass was already re-armed for the NEXT lap by a wrapped lead window (a first-corner
    #: mark near spline 0.0 whose lead opens BEFORE start/finish). One-shot: without it the
    #: re-arm check sees the state the fresh approach itself creates (its own heads-up) and
    #: resets again every frame — re-firing the first corner's cue for the rest of the lap.
    armed_prewrap: bool = False

    @property
    def any_brake_state(self) -> bool:
        """Any brake-cue/braking state accumulated this pass (drives the wrapped-lead reset)."""
        return any(self.zone_braked) or any(self.zone_cued)


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


def _signed_spline_delta(a: float, b: float) -> float:
    """Shortest signed normalized distance from ``b`` to ``a``, wrap-aware, in [-0.5, 0.5)."""
    return ((a - b + 0.5) % 1.0) - 0.5


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
        track_id: str | None = None,
        track_layout: str | None = None,
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
        # per-driver brake-mark calibration state (issue #522 part 2): zone (corner idx, zone
        # ordinal) -> (EMA of the driver's demonstrated onset spline, laps folded in). Survives
        # lap wraps and reset() — it is knowledge about the driver, not pass state.
        self._driver_marks: dict[tuple[int, int], tuple[float, int]] = {}
        # when known, guard calibration against a wrong-track (or wrong-LAYOUT — normalized
        # splines of different layouts point at unrelated features) lap.
        self._track_id = track_id
        self._track_layout = track_layout
        self._passes: dict[int, _CornerPass] = {r.index: self._new_pass(r) for r in self._refs}
        self._last_spline: float | None = None
        self._last_lap: float | None = None  # monotonic lap counter (when the stream supplies it)
        # end-of-lap grading held across the wrap when a known lapCount may lag the spline drop by
        # a frame (delta.lua defers); confirmed on a later counter advance, discarded on drive-on.
        self._pending_wrap: list[Advisory] = []
        self._pending_pre_lap: float | None = None
        # corners whose pre-wrap-armed pass was carried across an UNCONFIRMED wrap (known lap
        # counter, not yet advanced): legitimized when the counter advances, reverted to fresh
        # state when the jump turns out to be a pit/teleport (PR #525 review).
        self._pending_carried: list[int] = []
        self._pending_frames = 0  # frames the deferral has been unresolved (bounded)

    @staticmethod
    def _reference_marks(ref: CornerReference) -> list[float]:
        """All of a corner's reference brake marks (multi-zone when the corpus lap had them)."""
        if ref.brake_marks:
            return list(ref.brake_marks)
        return [] if ref.best_brake_point_spline is None else [ref.best_brake_point_spline]

    def _new_pass(self, ref: CornerReference) -> _CornerPass:
        n = len(self._reference_marks(ref))
        return _CornerPass(zone_braked=[False] * n, zone_cued=[False] * n)

    def _effective_marks(self, ref: CornerReference) -> list[tuple[float, str]]:
        """The cue marks actually in force for a corner: driver-calibrated where a zone has been
        observed on the driver's own laps, else the reference's — with honest provenance."""
        out: list[tuple[float, str]] = []
        for zi, mark in enumerate(self._reference_marks(ref)):
            cal = self._driver_marks.get((ref.index, zi))
            if cal is not None:
                out.append((cal[0] % 1.0, "driver_calibrated"))
            else:
                out.append((mark, _target_source(ref)))
        return out

    def calibrate_from_driver_lap(
        self,
        lap: LapTrace,
        *,
        track_id: str | None = None,
        track_layout: str | None = None,
    ) -> int:
        """Fold one of the driver's own completed laps into the per-zone brake-mark EMA.

        For each corner zone, the driver's sustained brake onset nearest the mark currently IN
        FORCE (within ``_CAL_MATCH_TOL_M`` meters — the same zone, not a different line) updates
        that zone's EMA. Matching is one-to-one (greedy nearest-first): a single brake
        application between two closely spaced marks calibrates ONE zone, never both — else the
        per-zone distinction #522 adds would collapse (PR #525 review). Returns the number of
        zones updated. A lap from a different track — or a different LAYOUT of the same track,
        when both sides carry one (multi-layout ids share normalized splines that point at
        unrelated features) — never calibrates.
        """
        if track_id and self._track_id and track_id != self._track_id:
            return 0
        if track_layout and self._track_layout and track_layout != self._track_layout:
            return 0
        tol = _CAL_MATCH_TOL_M / self._track_length_m  # metric tolerance in spline units
        updated = 0
        for ref in self._refs:
            ref_marks = self._reference_marks(ref)
            if not ref_marks:
                continue
            # Anchor matching on the marks currently IN FORCE (learned EMA when a zone has one,
            # else the reference): once a zone has drifted toward the driver's habit, later laps
            # near the LEARNED mark must keep adapting even when they sit outside the synthetic
            # mark's tolerance (PR #525 review — "recent laps dominate" must not stall).
            anchors = [m for m, _src in self._effective_marks(ref)]
            # Onsets are collected from each ANCHOR's ±tol neighbourhood (wrap-aware) — exactly
            # the region matching can accept — so a learned mark that drifted upstream of the
            # reference window, or one sitting just before start/finish (the archive finalizes
            # the lap before the S/F frame), keeps adapting (PR #525 review).
            onsets: list[float] = []
            seen_onsets: set[float] = set()
            for anchor in anchors:
                # +tol of body allowance past the acceptance bound: an onset just inside the
                # match window needs room for its ``min_run`` samples, or the window edge would
                # truncate the zone below detection. Acceptance stays bounded by ``tol``.
                lo_a, hi_a = anchor - tol, anchor + 2.0 * tol
                if lo_a < 0.0:
                    windows = [(lo_a % 1.0, 1.0), (0.0, hi_a)]
                elif hi_a > 1.0:
                    windows = [(lo_a, 1.0), (0.0, hi_a % 1.0)]
                else:
                    windows = [(lo_a, hi_a)]
                for w_lo, w_hi in windows:
                    for onset in sustained_brake_onsets(lap, w_lo, w_hi):
                        if onset not in seen_onsets:
                            seen_onsets.add(onset)
                            onsets.append(onset)
            if not onsets:
                continue
            pairs = sorted(
                (abs(_signed_spline_delta(onset, anchor)), zi, onset)
                for zi, anchor in enumerate(anchors)
                for onset in onsets
            )
            # forward positions from just upstream of the first mark, so "in lap order" is
            # well-defined even when a mark crosses start/finish or drifts upstream of the
            # reference window.
            origin = (anchors[0] - 2.0 * tol) % 1.0
            matched_zones: set[int] = set()
            consumed_onsets: set[float] = set()
            for dist, zi, onset in pairs:
                if dist > tol:
                    break  # sorted ascending: everything after is farther
                if zi in matched_zones or onset in consumed_onsets:
                    continue
                # Order preservation: an update that would move a zone AT or PAST a neighbour's
                # mark is ambiguous (which zone did the driver brake for?) and is skipped —
                # crossed marks would corrupt the per-zone segment arcs downstream (PR #525
                # review).
                cur = self._driver_marks.get((ref.index, zi))
                if cur is None:
                    candidate = onset % 1.0
                else:
                    ema, n = cur
                    candidate = (ema + _CAL_EMA_ALPHA * _signed_spline_delta(onset, ema)) % 1.0
                pos = _forward_spline_delta(origin, candidate)
                if zi > 0 and pos <= _forward_spline_delta(origin, anchors[zi - 1]):
                    continue
                if zi + 1 < len(anchors) and pos >= _forward_spline_delta(origin, anchors[zi + 1]):
                    continue
                matched_zones.add(zi)
                consumed_onsets.add(onset)
                self._driver_marks[(ref.index, zi)] = (
                    candidate,
                    1 if cur is None else cur[1] + 1,
                )
                updated += 1
        return updated

    def reset(self, *, carry_prewrap: bool = False) -> list[int]:
        """Clear per-corner pass state (start of a fresh lap). The lap counter — and the
        per-driver brake-mark calibration, which is knowledge about the driver — persist.

        With ``carry_prewrap`` (the start/finish-wrap path only), a pass re-armed pre-wrap (a
        first-corner lead window that opened before start/finish) already belongs to the lap
        that begins at this wrap: it carries across — heads-up and near-mark braking observed
        before the line stay valid — with its one-shot flag cleared so the NEXT lap's pre-wrap
        approach can re-arm it again. External resets (producer disconnect) and same-lap
        rewinds (pit/teleport) must NOT carry: the stream is discontinuous, and stale
        ``zone_cued`` state would suppress a fresh first-corner heads-up (PR #525 review).
        Returns the carried corner indices so an UNCONFIRMED wrap (known lap counter that has
        not advanced yet) can revert them if the jump turns out to be a pit return.
        """
        carried_ids: list[int] = []
        passes: dict[int, _CornerPass] = {}
        for r in self._refs:
            p = self._passes.get(r.index)
            if carry_prewrap and p is not None and p.armed_prewrap:
                p.armed_prewrap = False
                passes[r.index] = p
                carried_ids.append(r.index)
            else:
                passes[r.index] = self._new_pass(r)
        self._passes = passes
        self._last_spline = None
        self._pending_wrap = []
        self._pending_pre_lap = None
        self._pending_carried = []
        self._pending_frames = 0
        return carried_ids

    def observe(self, frame: dict[str, Any]) -> list[Advisory]:
        """Process one live frame; return the advisories it triggers (possibly empty)."""
        spline, speed, brake, throttle, lap = _normalize_frame(frame)
        if spline is None or speed is None:
            return []

        out: list[Advisory] = []
        # Resolve a wrap whose grading we deferred (a true wrap's lapCount can lag the drop by a
        # frame). Confirm the moment the counter advances; discard once the car has driven on past
        # the wrap zone without an advance (that was a pit/teleport, not a lap). Gate on EITHER
        # deferred artifact: a pit return after a pre-wrap first-corner cue typically has NOTHING
        # graded (no final corner in flight), so the carried-pass revert must not hide behind a
        # non-empty grading list (PR #525 review).
        if self._pending_wrap or self._pending_carried:
            self._pending_frames += 1
            if (
                lap is not None
                and self._pending_pre_lap is not None
                and lap > self._pending_pre_lap
            ):
                out.extend(self._pending_wrap)
                self._pending_wrap = []
                self._pending_pre_lap = None
                self._pending_carried = []  # wrap confirmed → the carried passes are legit
            elif spline > _WRAP_CUR_MAX or self._pending_frames > _WRAP_CONFIRM_MAX_FRAMES:
                self._pending_wrap = []
                self._pending_pre_lap = None
                # That backward jump was a pit/teleport, not a wrap (drove on, or the counter
                # stayed put past its at-most-one-frame lag): revert any pre-wrap-armed pass
                # carried across it — its stale zone_cued must not suppress the next legitimate
                # first-corner heads-up of the resumed stream, which for a pit return near the
                # line arrives BEFORE the 0.25-spline drive-on point (PR #525 review).
                for ci in self._pending_carried:
                    ref_c = next((r for r in self._refs if r.index == ci), None)
                    if ref_c is not None:
                        self._passes[ci] = self._new_pass(ref_c)
                self._pending_carried = []
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
            # A pre-wrap-armed first-corner pass carries only through a genuine start/finish
            # crossing; a same-lap rewind (pit/teleport) clears everything (PR #525 review).
            carried = self.reset(carry_prewrap=lap_advanced or wrap_shaped)
            if lap_advanced or (wrap_shaped and not lap_known):
                out.extend(graded)  # definite lap completion → grade now
            elif wrap_shaped and lap_known:
                self._pending_wrap = graded  # ambiguous → defer until the counter advances
                self._pending_pre_lap = pre_lap
                # ...and the carry is equally unconfirmed: reverted if this turns out to be a
                # pit return (resolved in the pending block above, same as the grading).
                self._pending_carried = carried
        self._last_spline = spline
        if lap is not None:
            self._last_lap = lap

        for ref in self._refs:
            st = self._passes[ref.index]
            # Braking-evaluation region PER BRAKE ZONE (issue #522 coverage: a merged esses
            # corner holds several real zones and each needs its own heads-up): from a zone's
            # mark back through its anticipatory lead — which may begin UPSTREAM of the
            # lateral-g corner window, so a driver coasting past the real brake point is cued
            # there, not only once the window starts (codex #294 @176).
            marks = self._effective_marks(ref)
            corner_cued_this_frame = False
            for zi, (bp, mark_source) in enumerate(marks):
                lead = _lead_spline_fraction(
                    speed, self._track_length_m, self._brake_prepare_lead_s
                )
                lead_start = (bp - lead) % 1.0
                # A zone's braking segment runs from its mark to the next zone's mark (last
                # zone: to the apex, or the window end for a mark past the apex) — braking
                # there is braking FOR this zone, so a later release isn't "late to brake".
                # Arc-based (wrap-aware): a driver-calibrated first-corner mark can sit just
                # BEFORE start/finish (e.g. 0.99 for a corner at 0.03), where linear compares
                # would never latch (PR #525 review).
                if zi + 1 < len(marks):
                    seg_end = marks[zi + 1][0]
                elif _in_arc(ref.apex_spline, bp, ref.spline_hi) or bp <= ref.apex_spline:
                    seg_end = ref.apex_spline
                else:
                    seg_end = ref.spline_hi
                # The first zone's ACTIVE arc [lead_start .. mark .. seg_end] straddles
                # start/finish whenever seg_end sits behind lead_start on the lap — either the
                # lead window opened before the line (mark near 0.0) or a driver-calibrated
                # mark itself sits just before the line (~0.99) with the corner beyond it
                # (PR #525 review). In the pre-line part of that arc, re-arm for the lap that
                # begins at the upcoming wrap.
                wrapped_lead = zi == 0 and seg_end < lead_start and spline >= lead_start
                if wrapped_lead:
                    # For a first-corner arc that straddles the line, the next lap's approach
                    # starts before the spline wrap is observed (for example at s=0.995). Reset
                    # this corner's previous-lap cue state now so the anticipatory cue can still
                    # lead the mark instead of being suppressed until after start/finish.
                    # ONE-SHOT per approach (``armed_prewrap``): the fresh approach's own
                    # heads-up must not read as stale state and reset/re-fire every frame.
                    if not st.armed_prewrap and (
                        st.inside
                        or st.any_brake_state
                        or st.release_cue_rank >= 0
                        or st.exit_emitted
                    ):
                        self._passes[ref.index] = st = self._new_pass(ref)
                    st.armed_prewrap = True
                if _in_arc(spline, bp, seg_end) and brake >= self._brake_on:
                    st.zone_braked[zi] = True
                # The actionable window runs from the anticipatory lead (which can wrap over
                # start/finish for a first corner with bp≈0) through the zone's segment end
                # (codex review #371). At most ONE heads-up per corner per FRAME: marks closer
                # than the lead open both arcs on the same tick, and a same-batch pair would
                # make the voice scheduler pick one and drop the imminent other — a deferred
                # zone re-fires on the next frame instead (~50 ms at 20 Hz; PR #525 review).
                if _in_arc(spline, lead_start, seg_end):
                    a = self._brake_cue(
                        ref,
                        st,
                        zi,
                        bp,
                        mark_source,
                        spline,
                        speed,
                        brake,
                        allow_cue=not corner_cued_this_frame,
                    )
                    if a is not None:
                        corner_cued_this_frame = True
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
                if brake >= self._brake_on and marks and spline < marks[0][0]:
                    # braking inside the window before the FIRST mark is early braking for this
                    # corner's first zone (normal trail-brake / rotation — codex #294); braking
                    # at/past a mark is credited per zone segment above.
                    st.zone_braked[0] = True
            elif st.inside and spline > ref.spline_hi and not st.exit_emitted:
                # just left the corner (downstream of exit) → grade the apex
                a = self._apex_deficit(ref, st)
                st.inside = False
                if a is not None:
                    out.append(a)
        return out

    def _brake_cue(
        self,
        ref: CornerReference,
        st: _CornerPass,
        zi: int,
        bp: float,
        mark_source: str,
        spline: float,
        speed: float,
        brake: float,
        *,
        allow_cue: bool = True,
    ) -> Advisory | None:
        """Fire ONE calm anticipatory heads-up per brake zone per pass — the only live brake cue.

        Issue #522 (supersedes the #368/#371 escalation ladder): the cue fires when the lead
        window opens (default ~3.2 s of audibility budget before the zone's mark) so the
        clip FINISHES with human reaction time to spare. It is always ``prepare``/``calm``
        and never re-fires within a pass — there is deliberately no second-stage live
        imperative and no register escalation: a driver braking exactly at the mark is
        indistinguishable from one about to miss it until the mark itself, so a spoken
        correction is either a false alarm or after-the-fact noise (measured on the #522
        instrumented lap: every past-point "Brake!" completed with the mark already behind
        the car). AT/PAST the mark the zone is locked out (``late_uncoached``) and
        corner-exit grading owns the feedback.

        Suppressed once the driver has braked FOR this zone (``zone_braked[zi]``): braking
        early and trailing off before the apex — normal trail-braking — is not a fault and
        must not draw a cue (codex #294). Braking for one zone of a merged esses corner
        must not consume the next zone's heads-up (issue #522 coverage).
        """
        if st.zone_braked[zi]:
            return None
        if brake >= self._brake_on:
            # Braking near the mark IS braking for this zone (codex review #371) — but with
            # the #522 lead the window can overlap the PREVIOUS corner/zone on closely spaced
            # turns, and trail-braking that one must not latch this zone (PR #523 review).
            # Discriminator: only braking within the last _LEAD_LATCH_TTA_S of the approach
            # counts as braking FOR this zone; farther out we just stay quiet on this frame
            # and let the heads-up fire once the driver is off the brakes.
            delta = _forward_spline_delta(spline, bp)
            tta_now = delta * self._track_length_m / max(speed / 3.6, 0.1)
            if not (0.0 < delta <= _LAP_WRAP_DROP) or tta_now <= _LEAD_LATCH_TTA_S:
                st.zone_braked[zi] = True
            return None
        # "anticipatory" = the car has not yet reached the brake point — robust to a lead window
        # wraps over start/finish (a first corner with bp≈0): the forward distance to bp is a small
        # positive value (≤ lead), not a negative linear delta (codex review #371).
        anticipatory = 0.0 < _forward_spline_delta(spline, bp) <= _LAP_WRAP_DROP
        if not anticipatory:
            # Issue #522: an imperative spoken AT/PAST the mark cannot complete before it —
            # measured on the instrumented lap, every past-point "Brake!" was heard with the
            # mark already behind the car. The moment has passed: stay silent, lock out
            # further imperatives for this zone, and flag it so corner-exit grading owns the
            # feedback ("brake earlier next lap") where it is actionable.
            st.zone_cued[zi] = True
            st.late_uncoached = True
            return None
        if st.zone_cued[zi]:
            return None  # already gave this zone its heads-up
        if not allow_cue:
            # another zone of this corner already cued on THIS frame: leave this zone's state
            # untouched so it emits on the next frame (PR #525 review — a same-batch pair would
            # make the voice scheduler drop one of the two).
            return None
        # One calm anticipatory heads-up per zone per pass — the ONLY live brake cue (#522). A
        # live fault imperative is unfixable in principle: a driver braking exactly at the mark
        # is indistinguishable from one about to miss it until the mark itself, so a spoken
        # correction is either a false alarm (on-pace driver) or after-the-fact (late one).
        # Real coaching splits the roles: anticipatory mark before, debrief after.
        tta_s = _forward_spline_delta(spline, bp) * self._track_length_m / max(speed / 3.6, 0.1)
        closing = _clamp01((speed - ref.target_apex_kmh) / _CLOSING_REF_KMH)
        st.zone_cued[zi] = True
        st.last_register = "calm"
        return Advisory(
            kind="late_brake",
            corner=ref.index,
            spline=round(bp, 4),
            urgency="prepare",
            intensity=round(_clamp01(0.3 * closing), 3),
            register="calm",
            # +1: CornerReference.index is 0-based; user-facing turn labels are 1-based (T1..)
            message=f"Brake point for T{ref.index + 1} coming up — brake.",
            detail={
                "brake_point_spline": round(bp, 4),
                "lead_s": round(tta_s, 2),
                "current_kmh": round(speed, 1),
                "anticipatory": True,
                # apex-target provenance (corpus vs GGV) — unchanged contract
                "source": _target_source(ref),
                # issue #522: which zone of the corner this mark belongs to, and whether the
                # mark is the reference's or learned from the driver's own laps.
                "zone": zi,
                "mark_source": mark_source,
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
            if st.late_uncoached:
                # #522 review (cursor HIGH): the deferred late-brake feedback must not depend
                # on an apex deficit existing — a driver who braked late yet still carried
                # target apex speed needs the "brake earlier" verdict too, or the suppressed
                # live imperative's feedback is silently lost. Voice has no late_brake info
                # clip (deliberately unspoken); the HUD / coaching.cue surfaces deliver it.
                return Advisory(
                    kind="late_brake",
                    corner=ref.index,
                    spline=round(ref.apex_spline, 4),
                    urgency="info",
                    intensity=0.3,
                    register="calm",
                    message=(
                        f"T{ref.index + 1}: you ran deep past your brake point — "
                        "brake earlier next lap."
                    ),
                    detail={"braked_late_uncoached": True, "source": _target_source(ref)},
                )
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
                + (
                    " You also ran deep past your brake point — brake earlier next lap."
                    if st.late_uncoached
                    else ""
                )
            ),
            detail={
                "min_speed_kmh": round(st.min_speed_kmh, 1),
                "target_apex_kmh": round(target, 1),
                "deficit_kmh": deficit,
                "source": source,
                # Issue #522: the mid-corner imperative was suppressed (after-the-fact); the
                # miss is owned here, at exit, where feedback is actionable for NEXT lap.
                "braked_late_uncoached": st.late_uncoached,
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


def build_observer_from_reference(
    reference_archive: dict, *, brake_prepare_lead_s: float | None = None
) -> RealtimeObserver | None:
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
    track_id = track.get("id")
    track_layout = track.get("layout")
    return RealtimeObserver(
        refs,
        track_length_m=_positive_track_length_m(track.get("lengthM")),
        brake_prepare_lead_s=(
            brake_prepare_lead_s if brake_prepare_lead_s is not None else _BRAKE_PREPARE_LEAD_S
        ),
        track_id=track_id if isinstance(track_id, str) and track_id else None,
        track_layout=track_layout if isinstance(track_layout, str) and track_layout else None,
    )
