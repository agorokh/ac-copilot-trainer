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

from dataclasses import dataclass, field
from typing import Any

#: Higher rank preempts and may barge in through the global cooldown.
_URGENCY_RANK: dict[str, int] = {"info": 1, "prepare": 2, "act": 3}


@dataclass(frozen=True)
class SpokenCue:
    """One cue selected for the voice to speak."""

    text: str
    urgency: str
    corner: int
    kind: str


def _turn(corner: Any) -> str:
    """1-based turn label from a 0-based corner index (defensive on bad input)."""
    try:
        return f"Turn {int(corner) + 1}"
    except (TypeError, ValueError):
        return "this corner"


def advisory_to_phrase(advisory: dict[str, Any]) -> str:
    """Short, ear-first phrasing of one observer advisory dict."""
    kind = advisory.get("kind")
    corner = advisory.get("corner", 0)
    if kind == "late_brake":
        return f"Brake, {_turn(corner)}."
    if kind == "apex_deficit":
        return f"Carry more speed, {_turn(corner)}."
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
    _last_spoken_s: float | None = None
    _last_corner_kind_s: dict[tuple[int, str], float] = field(default_factory=dict)

    def select(self, advisories: list[dict[str, Any]], now_s: float) -> SpokenCue | None:
        """Choose the one cue to speak now, applying cooldowns + urgency preemption."""
        if not advisories:
            return None
        # Drop advisories still within their per-(corner, kind) cooldown.
        fresh: list[dict[str, Any]] = []
        for a in advisories:
            key = (_corner_key(a), str(a.get("kind", "")))
            last = self._last_corner_kind_s.get(key)
            if last is not None and now_s - last < self.corner_cooldown_s:
                continue
            fresh.append(a)
        if not fresh:
            return None
        # Highest urgency wins (ties: keep input order, i.e. the observer's per-frame order).
        best = max(fresh, key=lambda a: _URGENCY_RANK.get(str(a.get("urgency", "")), 0))
        is_act = _URGENCY_RANK.get(str(best.get("urgency", "")), 0) >= _URGENCY_RANK["act"]
        # Global cooldown: stay silent unless this is an urgent 'act' cue (which may barge in).
        if (
            self._last_spoken_s is not None
            and now_s - self._last_spoken_s < self.global_cooldown_s
            and not is_act
        ):
            return None
        self._last_spoken_s = now_s
        self._last_corner_kind_s[(_corner_key(best), str(best.get("kind", "")))] = now_s
        return SpokenCue(
            text=advisory_to_phrase(best),
            urgency=str(best.get("urgency", "info")),
            corner=_corner_key(best),
            kind=str(best.get("kind", "")),
        )


def _corner_key(advisory: dict[str, Any]) -> int:
    """0-based corner index from an advisory, defaulting to -1 when unreadable."""
    try:
        return int(advisory.get("corner"))
    except (TypeError, ValueError):
        return -1
