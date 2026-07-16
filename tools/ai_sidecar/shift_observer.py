"""Live upshift/downshift cues from telemetry (#531 Part E).

Mirrors the in-game shift model (``src/ac_copilot_trainer/modules/shift_profile.lua``): the Lua
side resolves a per-gear upshift target from the learned reference-trace profile (falling back to
a fixed fraction of the rev limiter) and — since #531 Part E — rides that resolved target on the
``telemetry_tick`` as ``shift_rpm`` (+ ``shift_rpm_source``). This observer consumes it and emits
``coaching.cue`` advisories for the tablet coach lane:

- ``upshift`` — rpm reached the shift target under real throttle. Emitted once per gear
  engagement (re-armed by a gear change), never while braking.
- ``downshift`` — sustained bogging: real throttle but rpm far below the gear's shift target
  (the lower gear would put the engine in its band). Heuristic by construction and labelled so
  in ``detail``; conservatively gated (sustain window + cooldown + minimum speed) because a
  wrong "shift down" is worse than silence.

Both cues are ``register="calm"`` — glanceable tablet-tier per the #531 Part E audio-routing
policy (``audio_routing="tablet_native"``); the PC in-ear coach never speaks them (they are not
in the voice vocabulary, deliberately: the shift ribbon and HUD already own that surface).

Pure stdlib; fed the same ``telemetry_tick`` frames as the other observers. Sentinel discipline:
missing/non-finite channels disable the cue for that frame — ``0`` is a legitimate value
(neutral gear, closed throttle), absence is unknown.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from tools.ai_sidecar.realtime_observer import Advisory

#: Heuristic shift zone as a fraction of the rev limiter — mirrors
#: ``shift_profile.lua``'s ``DEFAULT_SHIFT_ZONE_FRAC`` (the fallback when no learned
#: ``shift_rpm`` rides the frame).
DEFAULT_SHIFT_ZONE_FRAC = 0.92
#: Only coach shifts under real throttle — mirrors ``realtime_coaching.lua``'s
#: ``SHIFT_MIN_GAS``.
MIN_SHIFT_GAS = 0.55
#: Re-emit guard: even across gear changes, consecutive upshift cues are at least this far
#: apart (a gearbox bounce must not machine-gun the lane).
UPSHIFT_COOLDOWN_S = 2.0
#: Bog detection: rpm at/below this fraction of the gear's shift target counts as lugging.
DOWNSHIFT_BOG_FRAC = 0.40
#: Bog must be sustained this long before a downshift cue fires (transient dips are normal).
DOWNSHIFT_SUSTAIN_S = 0.6
#: Downshift cues are rare by design.
DOWNSHIFT_COOLDOWN_S = 8.0
#: No bog coaching below this speed — pulling away from a stop legitimately lugs.
DOWNSHIFT_MIN_SPEED_KMH = 30.0


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _payload(frame: dict[str, Any]) -> dict[str, Any]:
    return frame.get("payload") if isinstance(frame.get("payload"), dict) else {}


def _pick(frame: dict[str, Any], *keys: str) -> Any:
    payload = _payload(frame)
    for src in (frame, payload):
        for key in keys:
            if key in src:
                return src[key]
    return None


@dataclass
class ShiftObserver:
    """Stateful shift-cue observer; feed it live ``telemetry_tick`` frames."""

    clock: Callable[[], float] = time.monotonic
    _last_gear: int | None = None
    _upshift_cued_gear: int | None = None
    _last_upshift_at: float = field(default=float("-inf"))
    _bog_since: float | None = None
    _last_downshift_at: float = field(default=float("-inf"))

    def reset(self) -> None:
        self._last_gear = None
        self._upshift_cued_gear = None
        self._last_upshift_at = float("-inf")
        self._bog_since = None
        self._last_downshift_at = float("-inf")

    def observe(self, frame: dict[str, Any]) -> list[Advisory]:
        now = self.clock()
        rpm = _num(_pick(frame, "rpm"))
        gear_raw = _num(_pick(frame, "gear"))
        throttle = _num(_pick(frame, "throttle", "gas"))
        brake = _num(_pick(frame, "brake"))
        gear = int(gear_raw) if gear_raw is not None and gear_raw >= 0 else None

        if gear is None or rpm is None:
            # Unknown gear/rpm: nothing to coach this frame; keep armed state (a dropped
            # channel must not fabricate a fresh gear engagement).
            return []

        if gear != self._last_gear:
            # New gear engagement re-arms both cues; a bog streak never spans gears.
            self._last_gear = gear
            self._upshift_cued_gear = None
            self._bog_since = None

        if gear < 1:
            return []

        target, source = self._shift_target(frame)
        if target is None:
            return []

        out: list[Advisory] = []
        throttled = throttle is not None and throttle >= MIN_SHIFT_GAS
        braking = brake is not None and brake > 0.2

        if (
            throttled
            and not braking
            and rpm >= target
            and self._upshift_cued_gear != gear
            and (now - self._last_upshift_at) >= UPSHIFT_COOLDOWN_S
        ):
            self._upshift_cued_gear = gear
            self._last_upshift_at = now
            out.append(
                Advisory(
                    kind="upshift",
                    corner=-1,
                    spline=float(_num(_pick(frame, "spline")) or 0.0),
                    urgency="act",
                    message="Shift up.",
                    detail={
                        "gear": gear,
                        "rpm": round(rpm),
                        "shift_rpm": round(target),
                        "shift_rpm_source": source,
                    },
                    intensity=0.2,
                    register="calm",
                )
            )

        speed = _num(_pick(frame, "speed_kmh", "speedKmh"))
        bogging = (
            throttled
            and not braking
            and gear >= 2
            and speed is not None
            and speed >= DOWNSHIFT_MIN_SPEED_KMH
            and rpm > 0
            and rpm <= target * DOWNSHIFT_BOG_FRAC
        )
        if not bogging:
            self._bog_since = None
        else:
            if self._bog_since is None:
                self._bog_since = now
            if (
                (now - self._bog_since) >= DOWNSHIFT_SUSTAIN_S
                and (now - self._last_downshift_at) >= DOWNSHIFT_COOLDOWN_S
            ):
                self._last_downshift_at = now
                self._bog_since = None
                out.append(
                    Advisory(
                        kind="downshift",
                        corner=-1,
                        spline=float(_num(_pick(frame, "spline")) or 0.0),
                        urgency="act",
                        message="Shift down.",
                        detail={
                            "gear": gear,
                            "rpm": round(rpm),
                            "shift_rpm": round(target),
                            "shift_rpm_source": source,
                            "classification": "bog_heuristic",
                        },
                        intensity=0.2,
                        register="calm",
                    )
                )
        return out

    def _shift_target(self, frame: dict[str, Any]) -> tuple[float | None, str]:
        """The upshift rpm for the current frame: learned (from the Lua shift profile riding
        the tick as ``shift_rpm``) when present, else the heuristic limiter fraction."""
        direct = _num(_pick(frame, "shift_rpm"))
        if direct is not None and direct > 0:
            source = _pick(frame, "shift_rpm_source")
            return direct, source if isinstance(source, str) and source else "learned"
        rpm_max = _num(_pick(frame, "rpm_max", "rpmMax"))
        if rpm_max is not None and rpm_max > 0:
            return rpm_max * DEFAULT_SHIFT_ZONE_FRAC, "heuristic"
        return None, "unavailable"
