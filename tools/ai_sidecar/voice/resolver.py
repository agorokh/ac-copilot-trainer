"""``resolve(advisory) -> Utterance`` — turn a semantic advisory into a ready-to-play cue.

This is the **renderer** seam (issue #340: "scheduler != renderer"). It is a whole-clip lookup
against the :class:`~tools.ai_sidecar.voice.manifest.Manifest`; a future number-fragment splicer
will slot in behind this *same* signature without the scheduler or playback knowing.

Keying (issue #368): the manifest is keyed on ``(kind, urgency, register, corner)``. ``register`` is
the intensity tier the observer chose for the situation (calm|firm|critical). Two fallbacks keep a
cue audible rather than silent:

* **register fallback** — if the bank has no clip for the requested tier (the vocabulary may not
  bake every register for every cue), fall back toward ``calm`` (critical -> firm -> calm).
  ``calm`` is the always-present base tier.
* **corner fallback** — a corner beyond the baked range (T21+) or the terse act tier (which is
  corner-less by design) degrades to the generic, corner-less clip.

``Utterance.register`` is set to the register that was *actually resolved* (after fallback), so
logs and the timing report never claim a tier that did not play. The ``dedup_key`` is keyed on the
*requested* register, so a genuine escalation (calm -> firm -> critical for one corner) is treated
as distinct coaching events.

Corner-number convention: ``Advisory.corner`` is **0-based** (``realtime_observer`` uses 0-based
``CornerReference.index``); the spoken vocabulary is **1-based** ("turn one"). The resolver bridges
the two: ``spoken = corner + 1``.

Input validation is strict (issue #340 "missing input validation" pitfall): a malformed advisory
(unknown ``kind``/``urgency``/``register``, non-integer/NaN corner) resolves to ``None`` and is
logged — never crashes, never guesses.

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


def _register_fallback_chain(register: str, *, urgency: str) -> tuple[str, ...]:
    """Registers to try, from the requested tier down toward the always-present ``calm`` base.

    ``critical`` -> ``(critical, firm, calm)``; ``firm`` -> ``(firm, calm)``;
    ``calm`` -> ``(calm,)``.
    """
    if urgency == "act" and register == "calm":
        # Legacy Advisory construction predates the register field and therefore carries the
        # dataclass default "calm". The v2 vocabulary intentionally bakes act-now clips at firm /
        # critical, not calm, so try the playable firm act clip before dropping the cue.
        return ("firm", "calm")
    idx = vocab.REGISTERS.index(register)
    return tuple(reversed(vocab.REGISTERS[: idx + 1]))


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
        register = getattr(advisory, "register", "calm")
        if kind not in vocab.KINDS:
            _log.warning("voice: dropping advisory with unknown kind=%r", kind)
            return None
        if urgency not in vocab.URGENCIES:
            _log.warning("voice: dropping advisory kind=%s with unknown urgency=%r", kind, urgency)
            return None
        if register not in vocab.REGISTERS:
            _log.warning(
                "voice: dropping advisory kind=%s with unknown register=%r", kind, register
            )
            return None

        spoken = _spoken_corner(getattr(advisory, "corner", None))
        # Walk register fallback (requested → … → calm); within each register, prefer the
        # corner-specific clip and fall back to the generic (corner-less) clip. The terse act tier
        # is corner-less by design, so an act advisory for a numbered corner resolves to its generic
        # clip on the first register tried.
        clip_id: str | None = None
        resolved_register = register
        resolved_corner = spoken
        for reg in _register_fallback_chain(register, urgency=urgency):
            cid = self._manifest.lookup(kind, urgency, reg, spoken)
            if cid is not None:
                clip_id, resolved_register, resolved_corner = cid, reg, spoken
                break
            cid = self._manifest.lookup(kind, urgency, reg, None)
            if cid is not None:
                clip_id, resolved_register, resolved_corner = cid, reg, None
                break

        if clip_id is None:
            _log.warning(
                "voice: no bank clip for kind=%s urgency=%s register=%s corner=%r — skipping",
                kind,
                urgency,
                register,
                getattr(advisory, "corner", None),
            )
            return None

        entry = self._manifest.clips.get(clip_id)
        text = entry.text if entry is not None else ""
        # Dedup is keyed on the *advisory's* identity (kind + 0-based corner + REQUESTED register),
        # so a genuine escalation (calm→firm→critical for one corner) is distinct, while a repeat at
        # the same register within a pass collapses to one utterance regardless of corner/register
        # fallback.
        dedup_key = f"{kind}:{getattr(advisory, 'corner', None)}:{register}"
        return Utterance(
            clip_id=clip_id,
            kind=kind,
            urgency=urgency,
            register=resolved_register,
            corner=resolved_corner,
            text=text,
            dedup_key=dedup_key,
        )
