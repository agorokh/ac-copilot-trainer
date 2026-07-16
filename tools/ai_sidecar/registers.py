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


#: Audio-routing values carried on ``coaching.cue`` / ``coaching.voice`` payloads (#531 Part E).
#: ``authoritative_pc`` = the PC WASAPI in-ear path owns the audible cue; ``tablet_native`` = the
#: cue is glanceable/info-tier and a tablet endpoint may voice it natively. The field is a routing
#: HINT for remote endpoints — the in-process PC coach's own scheduling is unchanged by it.
AUDIO_ROUTING_AUTHORITATIVE_PC = "authoritative_pc"
AUDIO_ROUTING_TABLET_NATIVE = "tablet_native"
AUDIO_ROUTINGS: tuple[str, ...] = (AUDIO_ROUTING_AUTHORITATIVE_PC, AUDIO_ROUTING_TABLET_NATIVE)


def audio_routing_for_register(register: object) -> str:
    """Map an intensity register to its audio route (#531 Part E).

    ``urgent``/``critical`` cues stay on the authoritative PC WASAPI path (measured sub-150 ms);
    ``calm``/``alert`` cues may be voiced by the tablet. The boundary is policy, not physics:
    #531 Part G re-derives it from the measured tablet native-audio dispatch→audible latency —
    until that number is on record the PC keeps everything critical (the P7's WebAudio path
    measured ~605 ms acoustic, over the 450 ms budget).
    """
    if register_rank(register) >= REGISTER_RANK["urgent"]:
        return AUDIO_ROUTING_AUTHORITATIVE_PC
    return AUDIO_ROUTING_TABLET_NATIVE
