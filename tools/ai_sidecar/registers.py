"""Canonical intensity-``register`` domain — the single source of truth shared by the observer
(which *produces* a register by quantizing a severity scalar) and the voice vocabulary (which
*consumes* it to key the tone manifest).

This module is deliberately dependency-free (stdlib only) and lives OUTSIDE
:mod:`tools.ai_sidecar.voice`. The voice package's ``__init__`` imports
:class:`tools.ai_sidecar.realtime_observer.Advisory`, so the observer cannot import from
``voice.vocabulary`` without a circular import. Hoisting the register ladder here lets both the
observer and ``voice.vocabulary`` import the *same* constants and helpers instead of each
re-declaring ``REGISTER_RANK`` and the legacy ``firm`` alias (which risked drift when the ladder
scaled from three to four tiers — issue #381).
"""

from __future__ import annotations

#: Intensity tiers, low -> high (issue #381). Drives the baked *tone* of a clip, never scheduling.
#: ``calm`` = measured heads-up; ``alert`` = clear attention cue; ``urgent`` = act-now correction;
#: ``critical`` = alarm. The observer quantizes a continuous severity scalar to one of these with
#: hysteresis (:func:`tools.ai_sidecar.realtime_observer`), and the resolver keys the manifest on
#: it.
REGISTERS: tuple[str, ...] = ("calm", "alert", "urgent", "critical")

#: Backward-compatible input aliases for advisory producers and older tests/log replays. New banks
#: bake ``urgent``; legacy ``firm`` advisories resolve to that tier instead of going silent.
REGISTER_ALIASES: dict[str, str] = {"firm": "urgent"}


def normalize_register(register: object) -> str:
    """Return the canonical intensity tier for ``register``.

    ``firm`` is accepted as a legacy alias for ``urgent`` so old advisory logs and producers keep
    speaking after the #381 vocabulary change. Unknown values are returned unchanged; callers still
    validate against :data:`REGISTERS`.
    """
    raw = str(register)
    return REGISTER_ALIASES.get(raw, raw)


#: Register ordering (low -> high) for the cap/hysteresis comparisons in the observer and the
#: scheduler's louder-same-urgency arbitration. Derived from :data:`REGISTERS` so they never drift.
REGISTER_RANK: dict[str, int] = {register: rank for rank, register in enumerate(REGISTERS)}


def register_rank(register: object, default: int = 0) -> int:
    """Ordering helper for intensity comparisons, accepting legacy aliases."""
    return REGISTER_RANK.get(normalize_register(register), default)
