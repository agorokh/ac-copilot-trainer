"""The bounded advisory vocabulary — the ONE source of truth for what gets baked and resolved.

The realtime coaching pipeline emits a *bounded* set of advisories across three orthogonal axes:

* ``kind`` — the control point
  (``late_brake`` | ``brake_release`` | ``turn_in`` | ``apex_deficit``).
* ``urgency`` (``info`` | ``prepare`` | ``act``) — drives the SCHEDULER (priority, barge-in,
  verbosity gating). Never a tone knob.
* ``register`` (``calm`` | ``alert`` | ``urgent`` | ``critical``) — the **intensity tier**:
  which tonal variant of the command is spoken. This is issue #368's headline — the SAME control
  point spoken with a tone that reflects how severe the situation is ("not just 'turn left'"). The
  register is baked into the clip's prosody (rate/pitch/loudness/brightness — see
  :mod:`tools.ai_sidecar.voice.bake`), so tone is delivered with zero hot-path TTS.

plus a **universal corner number** (``turn one`` .. ``turn twenty`` — track-agnostic, safe to bake
once). Because the set is finite and known ahead of time, we pre-render every utterance once and
look it up at runtime — no live TTS in the hot path.

**Terseness (issue #368 AC c).** A driver at 250 km/h covers ~21 m in 300 ms, so a critical "brake
NOW" cue must be ≤450 ms. The corner number ("…turn seventeen") is ~700 ms of speech the driver does
not need mid-corner — they know which corner they are in. So the **anticipatory/low-intensity** cues
(``prepare``/``info``, where the driver has lead time) carry the corner number, while the
**act-now** cues (``act`` urgency / ``alert``+``urgent``+``critical`` registers) are corner-less and
terse ("Brake.", "Brake, brake!"). A stem carries a corner number iff its text contains ``{turn}``;
this single rule bounds the bank and guarantees the act tier stays terse.

This module enumerates that vocabulary deterministically. Both the offline bake step
(:mod:`tools.ai_sidecar.voice.bake`) and the runtime :mod:`~tools.ai_sidecar.voice.resolver`
read it, so there is exactly **one** advisory->wording mapping (the issue #340 "no redundant code
drift" rule).
:func:`vocabulary_hash` content-addresses the wording set (now including ``register``): if a phrase
changes, every manifest built against the old wording is *detected* as stale at load (never silently
played).

Pure stdlib — importing this module pulls in **no** third-party dependency.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass

# The intensity-``register`` ladder is the SHARED domain of the observer (producer) and this
# vocabulary (consumer); it lives in the dependency-free :mod:`tools.ai_sidecar.registers` so both
# sides import the same constants instead of re-declaring them (issue #381). Re-exported here so
# existing importers (scheduler, client, cue, resolver, manifest, tests) keep using ``vocabulary``.
from tools.ai_sidecar.registers import (
    REGISTER_ALIASES,
    REGISTER_RANK,
    REGISTERS,
    normalize_register,
    register_rank,
)

__all__ = [
    "REGISTER_ALIASES",
    "REGISTER_RANK",
    "REGISTERS",
    "normalize_register",
    "register_rank",
]

#: Advisory ``kind`` values this vocabulary covers (mirrors ``realtime_observer.Advisory.kind``).
#: The braking cluster (issue #368 "braking first" slice): the anticipatory late-brake cue, the
#: over-braking release cue, and the (text-HUD) apex-deficit verdict. Every kind here is actually
#: EMITTED by the observer — we do not bake clips a cue never produces. ``turn_in`` /
#: ``hold`` / ``unwind`` / ``throttle`` / ``track_out`` / ``gear`` are the documented next slice
#: (they need steering / line-error grounding the live payload does not yet support honestly).
KINDS: tuple[str, ...] = (
    "late_brake",
    "brake_release",
    "apex_deficit",
    # Coach v2 (diagnosed, anticipatory, paced — emitted by tools.ai_sidecar.coaching_runtime):
    # one verb-first imperative per diagnosed root error, plus the live SAVE and the fix CONFIRM.
    "early_brake",
    "brake_late",
    "slow_apex",
    "no_trail",
    "late_throttle",
    "save",
    "confirm",
    "fuel_status",
    "fuel_save",
    "tyre_manage",
    "brake_manage",
    "conditions_strategy",
)

#: Advisory ``urgency`` tiers, low -> high (mirrors ``realtime_observer.Advisory.urgency``). Drives
#: SCHEDULING only (priority / barge-in / verbosity), never tone.
URGENCIES: tuple[str, ...] = ("info", "prepare", "act")

# Intensity tiers (``REGISTERS``) and the legacy ``firm`` alias now live in
# :mod:`tools.ai_sidecar.registers` and are re-exported at the top of this module.

#: Original/licensed persona metadata folded into every backend ``voice_signature``. This explicitly
#: documents that the distributed voice is a project-authored race-engineer style, not a real driver
#: clone.
VOICE_PERSONA_ID = "race-engineer-original-v1"
VOICE_PERSONA_LICENSE = "project-authored; no unconsented real-person clone"
# v4 restores the final consonant articulation of critical Kokoro cues while retaining the
# <=450 ms alarm budget (operator A/B finding, issue #381).
INTENSITY_CHAIN_VERSION = 4

#: Bump when the per-register prosody delivery changes: the ffmpeg filter chains in
#: ``bake._prosody_filter`` (shaped speech backends) or ``bake.ToneBackend``'s register tone table
#: (the CI voice). Lives here — not in ``bake`` — so the stdlib-only ``manifest`` gate can enforce
#: it without importing the bake stack (moved from ``bake.PROSODY_VERSION``, codex review #441).
PROSODY_VERSION = 2

#: The persona/prosody/intensity-chain suffix every backend appends as the FINAL segment of its
#: ``voice_signature`` at bake time (``bake._signature_suffix``). ``Manifest.validate`` anchors on
#: this suffix (issue #438): a persona swap, prosody-chain edit, or intensity-chain bump with
#: identical wording keeps ``vocabulary_hash`` constant, so this suffix is the only stale-bank
#: detector for those changes. Host-varying signature parts (backend id, voice name, ffmpeg major)
#: stay OUT of the suffix so baked banks remain portable across hosts.
EXPECTED_SIGNATURE_SUFFIX = (
    f"{VOICE_PERSONA_ID}+prosody{PROSODY_VERSION}+intensity{INTENSITY_CHAIN_VERSION}"
)


#: Universal corner numbers we bake (1-based, as spoken). T21+ degrades to the generic clip.
MAX_CORNER: int = 20

#: Hard upper bound on the materialized vocabulary size — a structural guard against an accidental
#: combinatorial blow-up (every (kind, urgency, register) listing all corners). Enforced by a test;
#: see ``tests/test_voice_vocabulary.py``. The real count is far below this (terse tiers are
#: corner-less); the bound exists so a future contributor cannot silently explode the bake.
MAX_CLIPS: int = 256

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

#: The spoken stem for each (kind, urgency, register). ``{turn}`` is filled with " turn three" or ""
#: (generic); a stem WITHOUT ``{turn}`` is corner-less and terse (the act tier). Wording lives ONLY
#: here. The keys of this table ARE the register matrix — only the (kind, urgency, register) triples
#: present here are baked, so registers that never vary tonally for a cue are simply absent (the
#: anti-blow-up lever). Wording escalates *with* the register (Hellier/Edworthy: warning urgency
#: needs semantics + acoustics to move together) — "Brake point" -> "Brake." ->
#: "Brake, brake!".
_STEMS: dict[tuple[str, str, str], str] = {
    # late_brake: anticipatory heads-up (carries the corner) -> terse act -> terse alarm. The three
    # registers ARE the headline — the same control point spoken with a tone that escalates with how
    # late/hot the driver is ("not just 'turn left'").
    ("late_brake", "prepare", "calm"): "Brake point{turn}.",
    ("late_brake", "act", "alert"): "Brake.",
    ("late_brake", "act", "urgent"): "Brake.",
    # Critical is the SAME word as urgent — the escalation is carried by TONE (louder, brighter,
    # faster: the issue #368 headline "even the tone reflects the situation"), kept to one syllable
    # so the alarm lands inside the braking window (≤450 ms). The "!" gives the synthesizer a
    # sharper intonation than urgent's ".".
    ("late_brake", "act", "critical"): "Brake!",
    # brake_release: over-braking past the apex while off-throttle — terse, in-corner (no number).
    ("brake_release", "prepare", "calm"): "Ease off.",
    ("brake_release", "act", "alert"): "Release.",
    ("brake_release", "act", "urgent"): "Release.",
    # apex_deficit: the text-HUD min-speed verdict. Voice keeps it as a calm heads-up that LOW
    # verbosity suppresses (issue #368 AC e: no post-fact narration in low verbosity).
    ("apex_deficit", "info", "calm"): "More entry speed{turn}.",
    # --- Coach v2: verb-first imperatives, corner-LESS (the cue lands AT the corner, so timing
    # carries the location — no spoken number). The same word is baked at alert/urgent/critical so
    # severity changes tone without changing the coaching command. ---
    ("early_brake", "prepare", "alert"): "Brake later.",
    ("brake_late", "prepare", "alert"): "Brake earlier.",
    ("no_trail", "prepare", "alert"): "Trail it.",
    ("slow_apex", "prepare", "alert"): "Carry more.",
    ("late_throttle", "act", "alert"): "Power.",
    ("early_brake", "prepare", "urgent"): "Brake later.",
    ("brake_late", "prepare", "urgent"): "Brake earlier.",
    ("no_trail", "prepare", "urgent"): "Trail it.",
    ("slow_apex", "prepare", "urgent"): "Carry more.",
    ("late_throttle", "act", "urgent"): "Power.",
    # magnitude grading (P2/#381): the SAME word, hotter tone, for a gross miss.
    ("early_brake", "prepare", "critical"): "Brake later.",
    ("brake_late", "prepare", "critical"): "Brake earlier.",
    ("no_trail", "prepare", "critical"): "Trail it.",
    ("slow_apex", "prepare", "critical"): "Carry more.",
    ("late_throttle", "act", "critical"): "Power.",
    ("save", "act", "critical"): "Brake!",
    ("confirm", "info", "calm"): "Good.",
    # Stint-level race-management cues. These are generic by design: the detailed fuel/tyre/brake
    # numbers ride in the advisory payload for screens/logs, while the voice keeps the hot path
    # short enough to act on.
    ("fuel_status", "info", "calm"): "Fuel check.",
    ("fuel_save", "act", "urgent"): "Save fuel.",
    ("fuel_save", "act", "critical"): "Lift and coast.",
    ("tyre_manage", "prepare", "alert"): "Manage tyres.",
    ("tyre_manage", "act", "urgent"): "Save tyres.",
    ("tyre_manage", "act", "critical"): "Save tyres!",
    ("brake_manage", "prepare", "alert"): "Cool brakes.",
    ("brake_manage", "act", "critical"): "Cool brakes!",
    ("conditions_strategy", "prepare", "calm"): "Track is green.",
    ("conditions_strategy", "prepare", "alert"): "Adjust to track.",
    ("conditions_strategy", "act", "urgent"): "Smooth inputs.",
}


@dataclass(frozen=True)
class Phrase:
    """One bakeable utterance: a stable clip id, its spoken text, and the advisory key it serves.

    ``corner`` is the 1-based, spoken corner number (``1``..:data:`MAX_CORNER`), or ``None`` for the
    corner-less clip (the *generic* fallback, and the only form the terse act tier takes).
    """

    clip_id: str
    text: str
    kind: str
    urgency: str
    register: str
    corner: int | None


def clip_id_for(kind: str, urgency: str, register: str, corner: int | None) -> str:
    """Deterministic, filesystem-safe clip id for a ``(kind, urgency, register, corner)`` key.

    ``corner`` is the 1-based spoken number, or ``None`` for the corner-less clip. The register
    segment sits before the corner suffix so ordering stays stable for content-addressing.
    Examples: ``late_brake.act.critical.generic``, ``turn_in.prepare.calm.t03``.
    """
    suffix = "generic" if corner is None else f"t{corner:02d}"
    return f"{kind}.{urgency}.{register}.{suffix}"


def _uses_corner(stem: str) -> bool:
    """True when a stem speaks a corner number — i.e. it should be baked per corner (1..MAX).

    A stem without ``{turn}`` is corner-less and terse (the act tier): one generic clip only.
    """
    return "{turn}" in stem


def _phrase(kind: str, urgency: str, register: str, corner: int | None) -> Phrase:
    stem = _STEMS[(kind, urgency, register)]
    turn = "" if corner is None else f" turn {NUMBER_WORDS[corner]}"
    return Phrase(
        clip_id=clip_id_for(kind, urgency, register, corner),
        text=stem.format(turn=turn),
        kind=kind,
        urgency=urgency,
        register=register,
        corner=corner,
    )


def iter_vocabulary() -> Iterator[Phrase]:
    """Yield every bakeable :class:`Phrase` exactly once, in a stable, deterministic order.

    Order: kind (KINDS order) -> urgency (info, prepare, act) -> register
    (calm, alert, urgent, critical) -> corner (generic first, then 1..MAX *only* for stems that
    carry ``{turn}``). Only
    ``(kind, urgency, register)`` triples present in :data:`_STEMS` are emitted. This ordering *is*
    part of the content-addressing contract — :func:`vocabulary_hash` depends on it being stable.
    """
    for kind in KINDS:
        for urgency in URGENCIES:
            for register in REGISTERS:
                stem = _STEMS.get((kind, urgency, register))
                if stem is None:
                    continue
                yield _phrase(kind, urgency, register, None)  # generic / terse clip first
                if _uses_corner(stem):
                    for corner in range(1, MAX_CORNER + 1):
                        yield _phrase(kind, urgency, register, corner)


def vocabulary() -> list[Phrase]:
    """Materialize the full vocabulary as a list (convenience over :func:`iter_vocabulary`)."""
    return list(iter_vocabulary())


def vocabulary_hash() -> str:
    """Content hash (sha256 hex) of the wording set — the drift detector.

    Computed over the canonical JSON of every phrase's
    ``(clip_id, text, kind, urgency, register, corner)``. A manifest stamps this at bake time; the
    runtime compares it to the *current* vocabulary at load and refuses to map if they differ (the
    wording or register set changed but the bank was not re-baked) — so a stale clip is
    **detected**, never silently spoken.
    """
    payload = [
        [p.clip_id, p.text, p.kind, p.urgency, p.register, p.corner] for p in iter_vocabulary()
    ]
    blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, sort_keys=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
