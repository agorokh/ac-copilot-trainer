"""In-the-ear voice coach — speak the live advisory stream (issue #340).

A pre-rendered **phrase-bank** voice output layer for the real-time coaching pipeline. It consumes
the *same* :class:`~tools.ai_sidecar.realtime_observer.Advisory` objects the text HUD already
renders
(``kind`` x ``urgency`` x universal corner number) and **speaks** them — local-first, jitter-free,
zero-GPU — turning the existing "brain" into an in-the-ear co-driver.

Why a baked clip bank, not live TTS in the hot path: a GT3 at 250 km/h covers ~21 m in 300 ms, so
live-TTS jitter would land cues *after* the braking zone. Our advisory vocabulary is **bounded**
(:mod:`vocabulary`), so a baked bank gives deterministic sub-50 ms playback while Assetto Corsa
saturates the GPU — exactly CrewChiefV4's proven architecture.

Layering (each module single-focus, so a future free-form/TTS path can never stall critical cues):

* :mod:`vocabulary`  — the bounded ``(kind, urgency, corner)`` phrase set; the ONE source of truth
  that both the offline bake step and the runtime resolver read.
* :mod:`utterance`   — :class:`Utterance`, the *rendered speech* type (distinct from ``Advisory``).
* :mod:`manifest`    — content-addressed ``(kind, urgency, corner) -> clip`` mapping; the only
  advisory->audio mapping. Hashes the vocabulary + voice signature so wording drift is *detected*.
* :mod:`config`      — verbosity levels + per-kind cooldown (the "how chatty is the coach" lever).
* :mod:`resolver`    — ``resolve(advisory) -> Utterance`` (v1: whole-clip lookup; v1.1 splicing
  hides behind this same interface).
* :mod:`scheduler`   — urgency scheduler (act > prepare > info) with dedup, TTL/staleness drop, and
  barge-in; runs on a dedicated thread, decoupled from the renderer.
* :mod:`playback`    — the ``Playback`` interface + a real ``rtmixer``/``sounddevice`` backend
  (lazy-imported) pinned to a named headset endpoint, plus injectable fakes for tests.
* :mod:`bake`        — offline build step that renders the bounded vocabulary to WAV + manifest.
* :mod:`engine`      — :class:`VoiceCoach`, the top-level seam the sidecar's telemetry loop feeds.

**Dependency discipline (issue #340 architecture requirement):** the stdlib sidecar core stays
dep-free. ``numpy`` / ``sounddevice`` / ``rtmixer`` are **lazy-imported inside** :mod:`playback`
(and optionally :mod:`bake`) only, behind the ``voice`` optional extra in ``pyproject.toml``.
Importing this package — or :mod:`vocabulary`, :mod:`manifest`, :mod:`resolver`, :mod:`scheduler`,
:mod:`config`, :mod:`utterance` — pulls in **no** third-party dependency, so the resolver/scheduler/
manifest logic is fully unit-testable on CI with no audio hardware.
"""

from __future__ import annotations

__all__ = [
    "Advisory",
    "Utterance",
]

# Re-export the upstream semantic event so callers have one import site for the seam types. This is
# a pure-stdlib re-export (realtime_observer is itself dep-free) — it does NOT pull in audio deps.
from tools.ai_sidecar.realtime_observer import Advisory

from .utterance import Utterance
