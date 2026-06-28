"""``resolve(advisory) -> Utterance`` — turn a semantic advisory into a ready-to-play cue.

This is the **renderer** seam (issue #340: "scheduler != renderer"). v1 is a whole-clip lookup
against the :class:`~tools.ai_sidecar.voice.manifest.Manifest`; the v1.1 number-fragment splicer
will slot in behind this *same* signature without the scheduler or playback knowing.

Corner-number convention: ``Advisory.corner`` is **0-based** (``realtime_observer`` uses 0-based
``CornerReference.index``); the spoken vocabulary is **1-based** ("turn one"). The resolver bridges
the two: ``spoken = corner + 1``. A corner beyond the baked range (T21+) degrades to the generic,
corner-less clip rather than going silent.

Input validation is strict (issue #340 "missing input validation" pitfall): a malformed advisory
(unknown ``kind``/``urgency``, non-integer/NaN corner) resolves to ``None`` and is logged — never
crashes, never guesses.

Pure stdlib.
"""

from __future__ import annotations

import logging

from tools.ai_sidecar.realtime_observer import Advisory
from tools.ai_sidecar.voice import vocabulary as vocab
from tools.ai_sidecar.voice.manifest import Manifest
from tools.ai_sidecar.voice.utterance import Utterance

_log = logging.getLogger("ai_sidecar.voice.resolver")


def _spoken_corner(corner: object) -> int | None:
    """Map a 0-based advisory corner to a 1-based spoken corner in ``1..MAX_CORNER``, else ``None``.

    ``None`` means "no in-range corner number" → the caller falls back to the generic clip. Rejects
    bools, non-integers, and NaN (bool is an int subclass — guard it explicitly).
    """
    if isinstance(corner, bool) or not isinstance(corner, int):
        return None
    spoken = corner + 1
    if 1 <= spoken <= vocab.MAX_CORNER:
        return spoken
    return None


class Resolver:
    """Resolve advisories to utterances against a single loaded manifest."""

    def __init__(self, manifest: Manifest) -> None:
        self._manifest = manifest

    def resolve(self, advisory: Advisory) -> Utterance | None:
        """Return the :class:`Utterance` for ``advisory``, or ``None`` if it cannot be mapped.

        Returns ``None`` (and logs) when the advisory is malformed or the bank has no clip for it —
        the scheduler then simply skips it (graceful degradation, never a wrong clip).
        """
        kind = getattr(advisory, "kind", None)
        urgency = getattr(advisory, "urgency", None)
        if kind not in vocab.KINDS:
            _log.warning("voice: dropping advisory with unknown kind=%r", kind)
            return None
        if urgency not in vocab.URGENCIES:
            _log.warning("voice: dropping advisory kind=%s with unknown urgency=%r", kind, urgency)
            return None

        spoken = _spoken_corner(getattr(advisory, "corner", None))
        # Prefer the corner-specific clip; fall back to the generic (corner-less) clip for T21+ or a
        # non-numeric corner so an out-of-range cue still speaks the verb ("Brake.") rather than
        # going silent.
        clip_id = self._manifest.lookup(kind, urgency, spoken)
        resolved_corner = spoken
        if clip_id is None and spoken is not None:
            clip_id = self._manifest.lookup(kind, urgency, None)
            resolved_corner = None
        if clip_id is None:
            _log.warning(
                "voice: no bank clip for kind=%s urgency=%s corner=%r — skipping",
                kind,
                urgency,
                getattr(advisory, "corner", None),
            )
            return None

        entry = self._manifest.clips.get(clip_id)
        text = entry.text if entry is not None else ""
        # Dedup is keyed on the *advisory's* identity (kind + its 0-based corner), so repeated
        # emissions for the same corner pass collapse to one utterance regardless of generic
        # fallback.
        dedup_key = f"{kind}:{getattr(advisory, 'corner', None)}"
        return Utterance(
            clip_id=clip_id,
            kind=kind,
            urgency=urgency,
            corner=resolved_corner,
            text=text,
            dedup_key=dedup_key,
        )
