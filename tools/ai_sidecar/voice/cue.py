"""Pure cue layer: realtime_observer ``Advisory`` -> short spoken phrase + arbitration.

No audio, no I/O — CI-testable on any OS (the Windows pyttsx3 speaking lives in :mod:`client`).
The driver cannot read a screen, so cues are short, ear-first, and place-anchored ("Brake, Turn 4")
— not the on-screen strings ("TARGET 142 KM/H"). Exactly one cue is spoken at a time: an
:class:`CueArbiter` enforces a per-corner cooldown (don't nag the same corner) and a global cooldown
(don't talk over yourself), with urgency preemption so an ``act`` cue (brake NOW) can barge in.

Input is the wire form of :class:`tools.ai_sidecar.realtime_observer.Advisory` — a plain dict
``{kind, corner, spline, urgency, message, detail}`` (sidecar-serialized onto ``coaching.cue``).
``corner`` is 0-based (turn labels are 1-based).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from tools.ai_sidecar.voice.vocabulary import normalize_register

#: Higher rank preempts and may barge in through the global cooldown.
_URGENCY_RANK: dict[str, int] = {"info": 1, "prepare": 2, "act": 3}
#: Default lap length (m) for spline lookahead when track length is unknown.
DEFAULT_LAP_LENGTH_M = 2500.0
#: Target lead time (s) before turn-in for non-urgent cues.
DEFAULT_LOOKAHEAD_S = 1.5


def _forward_spline_delta(car_s: float, target_s: float) -> float:
    """Forward distance along the lap from ``car_s`` to ``target_s`` in [0, 1)."""
    return (target_s - car_s) % 1.0


def _lookahead_spline_fraction(
    speed_kmh: float, *, lookahead_s: float = DEFAULT_LOOKAHEAD_S
) -> float:
    if not math.isfinite(speed_kmh) or speed_kmh <= 0:
        return 0.02
    dist_m = (speed_kmh / 3.6) * lookahead_s
    return min(0.08, max(0.005, dist_m / DEFAULT_LAP_LENGTH_M))


def _within_spline_lookahead(advisory: dict[str, Any]) -> bool:
    """True when the car is within the M0 ~1–2 s spline lookahead window of the advisory."""
    urgency = str(advisory.get("urgency", ""))
    if _URGENCY_RANK.get(urgency, 0) >= _URGENCY_RANK["act"]:
        return True
    car_s = advisory.get("car_spline")
    target_s = advisory.get("spline")
    if not isinstance(car_s, int | float) or not isinstance(target_s, int | float):
        return True
    speed = advisory.get("car_speed_kmh")
    speed_kmh = float(speed) if isinstance(speed, int | float) else 120.0
    delta = _forward_spline_delta(float(car_s), float(target_s))
    return delta <= _lookahead_spline_fraction(speed_kmh)


@dataclass(frozen=True)
class SpokenCue:
    """One cue selected for the voice to speak."""

    text: str
    urgency: str
    corner: int
    kind: str
    register: str = "calm"  # intensity tier (issue #368) — drives the WS speaker's rate/volume


def _turn(corner: Any) -> str:
    """1-based turn label from a 0-based corner index (defensive on bad input)."""
    try:
        return f"Turn {int(corner) + 1}"
    except (TypeError, ValueError):
        return "this corner"


def _effective_register(advisory: dict[str, Any]) -> str:
    """Register for the fallback path, mirroring :func:`resolver._register_fallback_chain`.

    An ``act`` advisory carrying the default ``calm`` register is a legacy / register-less producer:
    act-now cues are never baked at ``calm`` (they live at ``alert``/``urgent``/``critical``), so
    treat that case as ``urgent`` — otherwise the WS/pyttsx3 fallback under-reacts (non-terse
    phrasing + low rate/volume) on a time-critical cue, diverging from the in-process resolver.
    """
    register = normalize_register(advisory.get("register", "calm"))
    if advisory.get("urgency") == "act" and register == "calm":
        return "urgent"
    return register


def advisory_to_phrase(advisory: dict[str, Any]) -> str:
    """Short, ear-first phrasing of one observer advisory dict, register-aware (issue #368).

    The terse act tier (``alert``/``urgent``/``critical``) drops the corner number — the driver
    knows the corner and needs the verb now; the calm anticipatory tier keeps it. Mirrors the baked
    phrase-bank wording (``vocabulary._STEMS``) so the WS/pyttsx3 path speaks the same words as the
    in-process bank coach, and the speaker varies rate/volume by ``register`` to convey the
    intensity.
    """
    kind = advisory.get("kind")
    register = _effective_register(advisory)
    corner = advisory.get("corner", 0)
    if kind == "late_brake":
        if register == "critical":
            return "Brake!"
        if register in {"alert", "urgent"}:
            return "Brake."
        return f"Brake point, {_turn(corner)}."
    if kind == "brake_release":
        return "Release." if register in {"alert", "urgent", "critical"} else "Ease off."
    if kind == "apex_deficit":
        return f"More entry speed, {_turn(corner)}."
    if kind == "fuel_status":
        return "Fuel check."
    if kind == "fuel_save":
        return "Lift and coast." if register == "critical" else "Save fuel."
    if kind == "tyre_manage":
        if register == "critical":
            return "Save tyres!"
        return "Save tyres." if advisory.get("urgency") == "act" else "Manage tyres."
    if kind == "brake_manage":
        return "Cool brakes!" if register == "critical" else "Cool brakes."
    if kind == "conditions_strategy":
        return "Smooth inputs." if advisory.get("urgency") == "act" else "Adjust to track."
    # Unknown kind: fall back to the observer's own message (already human-readable), trimmed.
    message = advisory.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return f"Check {_turn(corner)}."


@dataclass
class CueArbiter:
    """Pick at most one cue to speak per tick; suppress nagging + talking-over.

    Feed it the advisories from one frame plus a monotonic ``now_s`` clock (injected, so tests are
    deterministic). Returns the :class:`SpokenCue` to speak, or ``None`` to stay silent. State:
    last-spoken time (global cooldown) + last time each (corner, kind) was spoken (per-corner
    cooldown). An ``act`` cue preempts the global cooldown so an urgent "brake" is never swallowed.
    """

    global_cooldown_s: float = 2.5
    corner_cooldown_s: float = 6.0
    #: floor between two DIFFERENT brake-zone heads-ups chaining through the global cooldown —
    #: enough for the previous short clip to finish, well under the 2.5 s anti-chatter window.
    zone_chain_min_gap_s: float = 1.2
    _last_spoken_s: float | None = None
    _last_spoken_key: tuple[int, int, str] | None = None
    _last_corner_kind_s: dict[tuple[int, int, str], float] = field(default_factory=dict)

    def select(self, advisories: list[dict[str, Any]], now_s: float) -> SpokenCue | None:
        """Choose the one cue to speak now, applying cooldowns + urgency preemption."""
        if not advisories:
            return None
        # Drop advisories still within their per-(corner, kind) cooldown — EXCEPT an `act` cue,
        # which bypasses the anti-nag window so a hotter escalation ("Brake!") is still heard after
        # an earlier calm lead-in for the same corner (codex review #371). Mirrors the
        # in-process scheduler's act exemption.
        fresh: list[dict[str, Any]] = []
        for a in advisories:
            if a.get("kind") == "late_brake" and a.get("urgency") == "info":
                # #522 exit debrief ("you ran deep past your brake point"): HUD/text-bound
                # by design. Speaking the anticipatory "Brake point, Turn N." phrase AFTER
                # the corner would be exactly the after-the-fact noise #522 removed — never
                # arbitrate it (and never let it consume a cooldown slot).
                continue
            is_act = _URGENCY_RANK.get(str(a.get("urgency", "")), 0) >= _URGENCY_RANK["act"]
            key = (_corner_key(a), _zone_key(a), str(a.get("kind", "")))
            last = self._last_corner_kind_s.get(key)
            if not is_act and last is not None and now_s - last < self.corner_cooldown_s:
                continue
            fresh.append(a)
        fresh = [a for a in fresh if _within_spline_lookahead(a)]
        if not fresh:
            return None
        # Highest urgency wins (ties: keep input order, i.e. the observer's per-frame order).
        best = max(fresh, key=lambda a: _URGENCY_RANK.get(str(a.get("urgency", "")), 0))
        is_act = _URGENCY_RANK.get(str(best.get("urgency", "")), 0) >= _URGENCY_RANK["act"]
        best_key = (_corner_key(best), _zone_key(best), str(best.get("kind", "")))
        # A DIFFERENT brake zone's heads-up may chain through the global cooldown after a short
        # floor: two zones of a merged esses corner can sit < 2.5 s apart, the #522 observer
        # emits only calm `prepare` brake cues (no act tier to barge in), and the second mark's
        # coaching is lost if it waits out the full window (PR #525 review). Same-key repeats
        # still respect the full cooldown (anti-chatter unchanged).
        zone_chain = (
            str(best.get("kind", "")) == "late_brake"
            and self._last_spoken_key is not None
            and best_key != self._last_spoken_key
            and self._last_spoken_s is not None
            and now_s - self._last_spoken_s >= self.zone_chain_min_gap_s
        )
        # Global cooldown: stay silent unless this is an urgent 'act' cue (which may barge in)
        # or a distinct brake-zone heads-up past the chain floor.
        if (
            self._last_spoken_s is not None
            and now_s - self._last_spoken_s < self.global_cooldown_s
            and not is_act
            and not zone_chain
        ):
            return None
        self._last_spoken_s = now_s
        self._last_spoken_key = best_key
        self._last_corner_kind_s[best_key] = now_s
        return SpokenCue(
            text=advisory_to_phrase(best),
            urgency=str(best.get("urgency", "info")),
            corner=_corner_key(best),
            kind=str(best.get("kind", "")),
            register=_effective_register(best),
        )


def _corner_key(advisory: dict[str, Any]) -> int:
    """0-based corner index from an advisory, defaulting to -1 when unreadable."""
    try:
        return int(advisory.get("corner"))
    except (TypeError, ValueError):
        return -1


def _zone_key(advisory: dict[str, Any]) -> int:
    """Brake-zone ordinal within a merged corner (issue #522), 0 when absent/unreadable.

    Joins the per-corner cooldown key so the SECOND zone's heads-up in a merged esses corner
    is not suppressed as a repeat of the first — mirroring the phrase-bank resolver's
    zone-aware dedup key (PR #525 review).
    """
    detail = advisory.get("detail")
    zone = detail.get("zone") if isinstance(detail, dict) else None
    return zone if isinstance(zone, int) else 0
