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


def _target_source(ref: CornerReference) -> str:
    """Honest provenance of a corner's target apex (mirrors track_reference.score_lap).

    The realistic, demonstrated corpus best when one exists; otherwise the GGV theoretical optimum
    (a *ceiling*, not a guaranteed-achievable number). Never label a GGV optimum as corpus-observed.
    """
    return "corpus_best" if ref.best_observed_apex_kmh is not None else "ggv_optimum"


@dataclass
class Advisory:
    """One real-time coaching cue, machine-readable + human string."""

    kind: str  # "late_brake" | "apex_deficit"
    corner: int
    spline: float
    urgency: str  # "info" | "prepare" | "act"
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class _CornerPass:
    """Mutable per-corner state for the current lap pass (reset on wrap)."""

    inside: bool = False
    min_speed_kmh: float | None = None
    has_braked: bool = False  # any braking seen this pass — suppresses a false late-brake cue
    late_brake_emitted: bool = False
    exit_emitted: bool = False


def _num(value: Any) -> float | None:
    """Parse to a finite float, else None (rejects NaN/±inf and bools)."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _normalize_frame(frame: dict[str, Any]) -> tuple[float | None, float | None, float]:
    """Extract ``(spline, speed_kmh, brake)`` from either the offline replay shape or the live
    ``telemetry_tick`` shape.

    The replay/test shape carries ``spline``/``speed``/``brake`` at the top level; the live
    high-rate frame (``external_protocol._validate_telemetry_tick``) nests values under ``payload``
    with speed named ``speed_kmh``. We accept both so the #277 wiring can hand us the real frame
    without a translation shim. NB: the current high-rate contract does not yet carry ``spline`` —
    that wiring (#277) must add it to the payload, since corner location requires it.
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
    return spline, speed, brake


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
    ) -> None:
        # sorted by entry so the in/out-of-window scan is stable
        self._refs = sorted(references, key=lambda r: r.spline_lo)
        self._deficit_margin = deficit_margin_kmh
        self._brake_on = brake_on
        self._passes: dict[int, _CornerPass] = {r.index: _CornerPass() for r in self._refs}
        self._last_spline: float | None = None

    def reset(self) -> None:
        """Clear all per-corner pass state (start of a fresh lap)."""
        self._passes = {r.index: _CornerPass() for r in self._refs}
        self._last_spline = None

    def observe(self, frame: dict[str, Any]) -> list[Advisory]:
        """Process one live frame; return the advisories it triggers (possibly empty)."""
        spline, speed, brake = _normalize_frame(frame)
        if spline is None or speed is None:
            return []

        out: list[Advisory] = []
        # A backward spline jump is either a true start/finish wrap or a same-lap rewind
        # (teleport / pit / replay). Only a true wrap (prev high → current low) completes the lap
        # and earns end-of-lap grading of a corner that ends at the line (spline_hi ~0.99); a
        # rewind abandons the stint, so clear state WITHOUT a spurious apex-deficit (codex #294).
        if self._last_spline is not None and self._last_spline - spline > _LAP_WRAP_DROP:
            true_wrap = self._last_spline >= _WRAP_PREV_MIN and spline <= _WRAP_CUR_MAX
            if true_wrap:
                for ref in self._refs:
                    st = self._passes[ref.index]
                    if st.inside and not st.exit_emitted:
                        a = self._apex_deficit(ref, st)
                        if a is not None:
                            out.append(a)
            self.reset()
        self._last_spline = spline

        for ref in self._refs:
            st = self._passes[ref.index]
            in_window = ref.spline_lo <= spline <= ref.spline_hi
            if in_window:
                st.inside = True
                st.min_speed_kmh = (
                    speed if st.min_speed_kmh is None else min(st.min_speed_kmh, speed)
                )
                if brake >= self._brake_on:
                    st.has_braked = True  # record braking so a later release isn't "late to brake"
                a = self._late_brake(ref, st, spline, speed, brake)
                if a is not None:
                    out.append(a)
            elif st.inside and spline > ref.spline_hi and not st.exit_emitted:
                # just left the corner (downstream of exit) → grade the apex
                a = self._apex_deficit(ref, st)
                st.inside = False
                if a is not None:
                    out.append(a)
        return out

    def _late_brake(
        self, ref: CornerReference, st: _CornerPass, spline: float, speed: float, brake: float
    ) -> Advisory | None:
        """Fire once if the car is past the brake point, before apex, and has not braked at all.

        Suppressed once the driver has braked anywhere in this pass (``has_braked``): braking early
        and trailing off before the apex — normal trail-brake / rotation — is not "late to brake"
        and must not draw an urgent cue (codex #294).
        """
        bp = ref.best_brake_point_spline
        if bp is None or st.late_brake_emitted or st.has_braked:
            return None
        if spline >= bp and spline < ref.apex_spline and brake < self._brake_on:
            st.late_brake_emitted = True
            return Advisory(
                kind="late_brake",
                corner=ref.index,
                spline=round(spline, 4),
                urgency="act",
                # +1: CornerReference.index is 0-based; user-facing turn labels are 1-based (T1..)
                message=f"Past your brake point for T{ref.index + 1} and still coasting — brake.",
                detail={
                    "brake_point_spline": round(bp, 4),
                    "current_kmh": round(speed, 1),
                    "source": _target_source(ref),
                },
            )
        return None

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
        return Advisory(
            kind="apex_deficit",
            corner=ref.index,
            spline=round(ref.apex_spline, 4),
            urgency="info",
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
    try:
        ref_lap = lap_trace_from_archive(reference_archive)
    except ValueError:
        return None
    refs = build_references(ref_lap)
    if not refs:
        return None
    add_corpus_lap(refs, ref_lap)  # the reference lap IS the corpus best
    return RealtimeObserver(refs)
