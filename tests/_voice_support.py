"""Shared test helpers for the voice-coach suite (not collected — no ``test_`` prefix).

Builds a full in-memory manifest over the real vocabulary (no files needed for resolver/scheduler
logic) and a deterministic fake clock, so the engine logic is exercised with zero audio hardware.
"""

from __future__ import annotations

from tools.ai_sidecar.realtime_observer import Advisory
from tools.ai_sidecar.voice import vocabulary as vocab
from tools.ai_sidecar.voice.manifest import MANIFEST_VERSION, ClipEntry, Manifest


def build_manifest(*, samplerate: int = 22050, voice_signature: str = "tone-v1") -> Manifest:
    """A manifest covering the entire current vocabulary (dummy file/sha — no bytes on disk)."""
    clips: dict[str, ClipEntry] = {}
    for p in vocab.iter_vocabulary():
        clips[p.clip_id] = ClipEntry(
            clip_id=p.clip_id,
            file=f"{p.clip_id}.wav",
            kind=p.kind,
            urgency=p.urgency,
            corner=p.corner,
            text=p.text,
            sha256="0" * 64,
        )
    return Manifest(
        version=MANIFEST_VERSION,
        samplerate=samplerate,
        voice_signature=voice_signature,
        vocabulary_hash=vocab.vocabulary_hash(),
        clips=clips,
    )


def make_advisory(
    *,
    kind: str = "late_brake",
    corner: int = 2,
    urgency: str = "act",
    spline: float = 0.5,
    message: str = "",
    detail: dict | None = None,
) -> Advisory:
    return Advisory(
        kind=kind,
        corner=corner,
        spline=spline,
        urgency=urgency,
        message=message,
        detail=detail or {},
    )


class FakeClock:
    """A monotonic clock you advance by hand, for deterministic TTL/dedup/cooldown tests."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt
