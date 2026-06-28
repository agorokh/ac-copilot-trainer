"""The :class:`Utterance` type — *rendered speech*, kept distinct from the semantic ``Advisory``.

Issue #340 architecture requirement: ``Advisory`` (a semantic coaching event produced by the brain)
and ``Utterance`` (a concrete sound the engine is about to play) are **separate types**. The
:mod:`~tools.ai_sidecar.voice.manifest` is the only bridge between them. A future RL/agentic coach
emits *advisories* onto the same bus; it never injects raw audio or text into the clip path. Keeping
the types apart is what lets the v1.1 number-splicing renderer slot in behind the same
``resolve(advisory) -> Utterance`` interface without touching the scheduler or playback.

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Urgency ordering used everywhere a "which cue wins" decision is made (higher = more urgent).
URGENCY_RANK: dict[str, int] = {"info": 0, "prepare": 1, "act": 2}


@dataclass(frozen=True)
class Utterance:
    """A resolved, ready-to-play speech cue.

    Attributes:
        clip_id: The bank clip to play (key into the manifest / pre-decoded PCM bank).
        kind: Originating advisory ``kind`` (carried for logging + cooldown bucketing).
        urgency: Originating advisory ``urgency`` — drives scheduling (act > prepare > info) and
            barge-in.
        corner: 1-based spoken corner number, or ``None`` for a generic (corner-less) clip.
        text: The spoken text (for logs / debugging; never re-synthesized at runtime in v1).
        dedup_key: Stable key identifying "the same cue this corner pass" — ``"{kind}:{corner}"``.
            The scheduler suppresses a repeat of this key within one pass, and a genuinely new pass
            (or a different kind/corner) is never suppressed.
    """

    clip_id: str
    kind: str
    urgency: str
    corner: int | None
    text: str
    dedup_key: str

    @property
    def rank(self) -> int:
        """Numeric urgency rank (``act`` highest); unknown urgencies sort lowest."""
        return URGENCY_RANK.get(self.urgency, -1)
