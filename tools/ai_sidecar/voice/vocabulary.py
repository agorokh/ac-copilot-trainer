"""The bounded advisory vocabulary — the ONE source of truth for what gets baked and resolved.

The realtime coaching pipeline emits a *bounded* set of advisories:
``kind`` (``late_brake`` | ``apex_deficit``) x ``urgency`` (``info`` | ``prepare`` | ``act``) x a
**universal corner number** (``turn one`` .. ``turn twenty`` — track-agnostic, so safe to bake
once).
Because the set is finite and known ahead of time, we pre-render every utterance to a clip once and
look it up at runtime — no live TTS in the hot path.

This module enumerates that vocabulary deterministically. Both the offline bake step
(:mod:`tools.ai_sidecar.voice.bake`) and the runtime :mod:`~tools.ai_sidecar.voice.resolver` read
it,
so there is exactly **one** advisory->wording mapping (the issue #340 "no redundant code drift"
rule).
The :func:`vocabulary_hash` content-addresses the wording set: if a phrase changes, every manifest
built against the old wording is *detected* as stale at load (never silently played).

Corner *numbers* are universal; per-track corner *names* (e.g. "Eau Rouge") are explicitly deferred
(v1.1) to avoid per-track clip explosion. Runtime number-fragment splicing of dynamic values
("41 km/h") is likewise v1.1, behind the same resolver interface — v1 speaks whole macro-clips only.

Pure stdlib — importing this module pulls in **no** third-party dependency.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass

#: Advisory ``kind`` values this vocabulary covers (mirrors ``realtime_observer.Advisory.kind``).
KINDS: tuple[str, ...] = ("late_brake", "apex_deficit")

#: Advisory ``urgency`` tiers, low -> high (mirrors ``realtime_observer.Advisory.urgency``). The
#: bank
#: covers every (kind, urgency) pair so a future observer that promotes e.g. ``apex_deficit`` to
#: ``prepare`` already has a baked clip — the vocabulary is the bounded universe, not just today's
#: emitted subset.
URGENCIES: tuple[str, ...] = ("info", "prepare", "act")

#: Universal corner numbers we bake (1-based, as spoken). T21+ degrades to the generic clip.
MAX_CORNER: int = 20

#: Spoken cardinal for each 1-based corner number (index 0 unused). Words, not digits, so a neural
#: voice never mis-reads "11" as "eleven hundred" or similar.
NUMBER_WORDS: tuple[str, ...] = (
    "",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)

#: The spoken stem for each (kind, urgency). ``{turn}`` is filled with " turn three" or ""
#: (generic).
#: Keep these terse — a driver needs the verb first, mid-corner. Wording lives ONLY here.
_STEMS: dict[tuple[str, str], str] = {
    ("late_brake", "info"): "Brake point{turn}.",
    ("late_brake", "prepare"): "Brake soon{turn}.",
    ("late_brake", "act"): "Brake{turn}.",
    ("apex_deficit", "info"): "More entry speed{turn}.",
    ("apex_deficit", "prepare"): "Carry more speed{turn}.",
    ("apex_deficit", "act"): "More speed{turn}.",
}


@dataclass(frozen=True)
class Phrase:
    """One bakeable utterance: a stable clip id, its spoken text, and the advisory key it serves.

    ``corner`` is the 1-based, spoken corner number (``1``..:data:`MAX_CORNER`), or ``None`` for the
    corner-less *generic* fallback clip used when an advisory's corner falls outside the baked
    range.
    """

    clip_id: str
    text: str
    kind: str
    urgency: str
    corner: int | None


def clip_id_for(kind: str, urgency: str, corner: int | None) -> str:
    """Deterministic, filesystem-safe clip id for a ``(kind, urgency, corner)`` key.

    ``corner`` is the 1-based spoken number, or ``None`` for the generic (corner-less) clip.
    Examples:
    ``late_brake.act.t03``, ``apex_deficit.info.generic``.
    """
    suffix = "generic" if corner is None else f"t{corner:02d}"
    return f"{kind}.{urgency}.{suffix}"


def _phrase(kind: str, urgency: str, corner: int | None) -> Phrase:
    stem = _STEMS[(kind, urgency)]
    turn = "" if corner is None else f" turn {NUMBER_WORDS[corner]}"
    return Phrase(
        clip_id=clip_id_for(kind, urgency, corner),
        text=stem.format(turn=turn),
        kind=kind,
        urgency=urgency,
        corner=corner,
    )


def iter_vocabulary() -> Iterator[Phrase]:
    """Yield every bakeable :class:`Phrase` exactly once, in a stable, deterministic order.

    Order: by kind, then urgency (info, prepare, act), then corner (generic first, then 1..MAX).
    This
    ordering is part of the content-addressing contract — :func:`vocabulary_hash` depends on it
    being
    stable across runs.
    """
    for kind in KINDS:
        for urgency in URGENCIES:
            yield _phrase(kind, urgency, None)  # generic fallback first
            for corner in range(1, MAX_CORNER + 1):
                yield _phrase(kind, urgency, corner)


def vocabulary() -> list[Phrase]:
    """Materialize the full vocabulary as a list (convenience over :func:`iter_vocabulary`)."""
    return list(iter_vocabulary())


def vocabulary_hash() -> str:
    """Content hash (sha256 hex) of the wording set — the drift detector.

    Computed over the canonical JSON of every phrase's ``(clip_id, text, kind, urgency, corner)``.
    A manifest stamps this at bake time; the runtime compares it to the *current* vocabulary at load
    and refuses to map if they differ (the wording changed but the bank was not re-baked) — so a
    stale clip is **detected**, never silently spoken.
    """
    payload = [[p.clip_id, p.text, p.kind, p.urgency, p.corner] for p in iter_vocabulary()]
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
