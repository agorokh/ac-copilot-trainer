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

#: Spline drop between consecutive frames that we treat as a new lap (start/finish wrap).
_LAP_WRAP_DROP = 0.5
#: km/h a corner exit must be under the target before it's worth an advisory.
_DEFICIT_MARGIN_KMH = 2.0
#: brake pedal fraction above which we consider the driver "on the brakes".
_BRAKE_ON = 0.05


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
        spline = _num(frame.get("spline"))
        speed = _num(frame.get("speed"))
        if spline is None or speed is None:
            return []
        brake = _num(frame.get("brake")) or 0.0

        # lap wrap: spline jumps backward across start/finish → new lap, reset passes
        if self._last_spline is not None and self._last_spline - spline > _LAP_WRAP_DROP:
            self.reset()
        self._last_spline = spline

        out: list[Advisory] = []
        for ref in self._refs:
            st = self._passes[ref.index]
            in_window = ref.spline_lo <= spline <= ref.spline_hi
            if in_window:
                st.inside = True
                st.min_speed_kmh = (
                    speed if st.min_speed_kmh is None else min(st.min_speed_kmh, speed)
                )
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
        """Fire once if the car is past the brake point, before apex, and still not braking."""
        bp = ref.best_brake_point_spline
        if bp is None or st.late_brake_emitted:
            return None
        if spline >= bp and spline < ref.apex_spline and brake < self._brake_on:
            st.late_brake_emitted = True
            return Advisory(
                kind="late_brake",
                corner=ref.index,
                spline=round(spline, 4),
                urgency="act",
                message=f"Past your brake point for T{ref.index} and still coasting — brake.",
                detail={
                    "brake_point_spline": round(bp, 4),
                    "current_kmh": round(speed, 1),
                    "source": "corpus_best",
                },
            )
        return None

    def _apex_deficit(self, ref: CornerReference, st: _CornerPass) -> Advisory | None:
        """On corner exit, compare the min speed carried to the corpus-best target apex."""
        st.exit_emitted = True
        if st.min_speed_kmh is None:
            return None
        target = ref.target_apex_kmh
        deficit = round(target - st.min_speed_kmh, 1)
        if deficit < self._deficit_margin:
            return None
        return Advisory(
            kind="apex_deficit",
            corner=ref.index,
            spline=round(ref.apex_spline, 4),
            urgency="info",
            message=(
                f"T{ref.index}: carried {deficit:.0f} km/h under target apex "
                f"({st.min_speed_kmh:.0f} vs {target:.0f}) — more entry speed if grip allows."
            ),
            detail={
                "min_speed_kmh": round(st.min_speed_kmh, 1),
                "target_apex_kmh": round(target, 1),
                "deficit_kmh": deficit,
                "source": "corpus_best",
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
