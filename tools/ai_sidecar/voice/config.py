"""Voice coach configuration — verbosity levels + per-kind cooldown (the "how chatty" lever).

The operator's control surface over the coach. Two knobs the issue calls out:

* **verbosity** — suppress lower-urgency chatter. ``low`` speaks only ``prepare``/``act`` (the
  driver does not want "more entry speed, turn 7" repeated every lap); ``off`` mutes the coach;
  ``normal``/``high`` speak everything.
* **per-kind cooldown** — a minimum gap between two cues of the *same kind*, so a corner the driver
  keeps fluffing does not produce a wall of speech. Cooldown never delays a *fresh* ``act`` cue
  (the scheduler exempts ``act`` — see :mod:`tools.ai_sidecar.voice.scheduler`).

Validation is strict (issue #340 "missing input validation" pitfall): unknown verbosity, negative or
non-finite cooldown/TTL/dedup windows, and an empty device-name string are rejected at construction.

Pure stdlib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum

from tools.ai_sidecar.voice.utterance import URGENCY_RANK


class Verbosity(IntEnum):
    """How chatty the coach is. Ordered so ``>=`` comparisons read naturally."""

    OFF = 0  # mute — speak nothing
    LOW = 1  # only prepare + act (suppress info)
    NORMAL = 2  # info + prepare + act
    HIGH = 3  # info + prepare + act, shorter cooldowns

    @staticmethod
    def parse(value: str | Verbosity) -> Verbosity:
        """Coerce a config string (``"low"``) or enum to :class:`Verbosity`; raises on unknown."""
        if isinstance(value, Verbosity):
            return value
        try:
            return Verbosity[str(value).strip().upper()]
        except KeyError as exc:
            valid = ", ".join(v.name.lower() for v in Verbosity)
            raise ValueError(f"unknown verbosity {value!r}; expected one of: {valid}") from exc


#: Lowest urgency RANK that each verbosity level will speak. ``OFF`` speaks nothing (sentinel above
#: the max rank). Derived from :data:`URGENCY_RANK` so it stays in lockstep with the urgency ladder.
_MIN_RANK_FOR: dict[Verbosity, int] = {
    Verbosity.OFF: max(URGENCY_RANK.values()) + 1,  # nothing qualifies
    Verbosity.LOW: URGENCY_RANK["prepare"],
    Verbosity.NORMAL: URGENCY_RANK["info"],
    Verbosity.HIGH: URGENCY_RANK["info"],
}

#: Default per-kind cooldown (seconds) between two cues of the same kind. ``apex_deficit`` is
#: informational and repeats every lap, so it gets a longer gap; ``late_brake`` is urgent and rare,
#: so a short gap. These are overridable per :class:`VoiceConfig`.
_DEFAULT_COOLDOWN_S: dict[str, float] = {
    "late_brake": 1.0,
    "brake_release": 1.5,
    "apex_deficit": 6.0,
}


def _check_finite_nonneg(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got {value!r}")
    f = float(value)
    if not math.isfinite(f) or f < 0:
        raise ValueError(f"{name} must be finite and >= 0, got {value!r}")
    return f


@dataclass
class VoiceConfig:
    """Operator-facing voice settings, validated at construction.

    Attributes:
        verbosity: :class:`Verbosity` (or a string coerced via :meth:`Verbosity.parse`).
        cooldown_s: per-``kind`` minimum gap between same-kind cues (merged over the defaults).
        device_name: substring of the output device to pin (matched with ``host_api``). ``None``
            uses the system default — but production should pin the headset by name so voice never
            lands on the haptic USB-DAC.
        host_api: PortAudio host-API name to disambiguate the device (e.g. ``"Windows WASAPI"``).
        ttl_s: an advisory older than this (now - emit time) is dropped as stale before it speaks.
        dedup_window_s: a repeat of the same ``(kind, corner)`` within this window is suppressed;
            the window is shorter than a lap, so the next corner pass is never suppressed.
        high_cooldown_factor: multiplier applied to cooldowns when ``verbosity == HIGH`` (chattier).
    """

    verbosity: Verbosity = Verbosity.NORMAL
    cooldown_s: dict[str, float] = field(default_factory=dict)
    device_name: str | None = None
    host_api: str | None = None
    ttl_s: float = 1.5
    dedup_window_s: float = 8.0
    high_cooldown_factor: float = 0.5

    def __post_init__(self) -> None:
        self.verbosity = Verbosity.parse(self.verbosity)
        # Merge caller overrides on top of the defaults; validate every value.
        merged = dict(_DEFAULT_COOLDOWN_S)
        for k, v in (self.cooldown_s or {}).items():
            merged[str(k)] = _check_finite_nonneg(f"cooldown_s[{k!r}]", v)
        self.cooldown_s = merged
        self.ttl_s = _check_finite_nonneg("ttl_s", self.ttl_s)
        self.dedup_window_s = _check_finite_nonneg("dedup_window_s", self.dedup_window_s)
        self.high_cooldown_factor = _check_finite_nonneg(
            "high_cooldown_factor", self.high_cooldown_factor
        )
        if self.device_name is not None:
            if not isinstance(self.device_name, str) or not self.device_name.strip():
                raise ValueError("device_name must be a non-empty string or None")
        if self.host_api is not None:
            if not isinstance(self.host_api, str) or not self.host_api.strip():
                raise ValueError("host_api must be a non-empty string or None")

    def urgency_allowed(self, urgency: str) -> bool:
        """Whether the current verbosity speaks a cue of this ``urgency``."""
        rank = URGENCY_RANK.get(urgency, -1)
        if rank < 0:
            return False
        return rank >= _MIN_RANK_FOR[self.verbosity]

    def cooldown_for(self, kind: str) -> float:
        """Effective same-kind cooldown for ``kind`` under the current verbosity."""
        base = self.cooldown_s.get(kind, 0.0)
        if self.verbosity == Verbosity.HIGH:
            return base * self.high_cooldown_factor
        return base
