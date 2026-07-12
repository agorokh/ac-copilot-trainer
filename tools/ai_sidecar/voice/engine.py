"""``VoiceCoach`` — the top-level seam the sidecar's telemetry loop feeds advisories into.

This is the single object the rest of the sidecar touches. It owns the resolver + scheduler +
playback and exposes one hot-path method, :meth:`subscribe`, which the telemetry/WS thread calls
with each :class:`~tools.ai_sidecar.realtime_observer.Advisory` the observer already emits::

    coach = VoiceCoach.from_bank("banks/piper-en", VoiceConfig(device_name="Headset"))
    coach.start()
    ...
    for advisory in observer.observe(frame):   # the SAME objects the text HUD renders
        coach.subscribe(advisory)              # non-blocking — just enqueues

Reuse, don't fork: the voice consumer subscribes in-process to the same advisory objects the coach
pipeline emits (issue #340). It never re-derives wording — the manifest is the only advisory->audio
mapping, so the text HUD and the voice path can never drift.

**Graceful degradation (issue #340 acceptance criterion).** If the manifest is unreadable, its
``vocabulary_hash`` no longer matches the current wording, or its ``voice_signature`` no longer
carries the current persona/prosody/intensity suffix (the bank is stale — issue #438),
:meth:`from_bank` returns a **disabled** coach: :meth:`subscribe` becomes a logged no-op. It
never crashes, and it never plays a clip that might be the wrong one. Per-clip gaps (a missing
single clip) are handled one
level down by the resolver returning ``None`` for just that advisory.

Pure stdlib at import time; the real audio backend (and its ``numpy``/``sounddevice``/``rtmixer``
deps) is built lazily inside :meth:`from_bank` only when no playback is injected.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from tools.ai_sidecar.voice.config import VoiceConfig
from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME, Manifest, ManifestError
from tools.ai_sidecar.voice.playback import Playback
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.scheduler import Scheduler

_log = logging.getLogger("ai_sidecar.voice.engine")


def _bank_duration_lookup(playback: Playback) -> Callable[[str], float | None] | None:
    """Best-effort clip-duration lookup from a real backend's pre-decoded bank.

    The real backends (:class:`RtMixerPlayback` / :class:`SoundDevicePlayback`) hold their
    ``Bank`` privately; the dispatch tap only needs read-only durations for the
    ``coaching.voice`` payload, so duck-read it rather than widening the Playback protocol.
    Returns ``None`` (durations omitted) for playbacks without a bank (injected test doubles).
    """
    bank = getattr(playback, "_bank", None)
    samplerate = getattr(bank, "samplerate", 0)
    if bank is None or not samplerate:
        return None

    def _duration_ms(clip_id: str) -> float | None:
        pcm = bank.get(clip_id)
        if pcm is None:
            return None
        return len(pcm) / samplerate * 1000.0

    return _duration_ms


class VoiceCoach:
    """Wires resolver + scheduler + playback. One coach per output channel."""

    def __init__(
        self,
        scheduler: Scheduler | None,
        playback: Playback | None,
        *,
        enabled: bool,
        disabled_reason: str = "",
    ) -> None:
        self._scheduler = scheduler
        self._playback = playback
        self._enabled = enabled
        self._disabled_reason = disabled_reason
        self._warned_disabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def disabled_reason(self) -> str:
        return self._disabled_reason

    def subscribe(self, advisory: object) -> None:
        """Enqueue one advisory to be spoken. Non-blocking; a no-op when the coach is disabled."""
        if not self._enabled or self._scheduler is None:
            if not self._warned_disabled:
                _log.warning(
                    "voice: coach disabled (%s) — ignoring advisories", self._disabled_reason
                )
                self._warned_disabled = True
            return
        self._scheduler.submit(advisory)

    def start(self) -> None:
        """Start the scheduler worker thread (no-op when disabled)."""
        if self._enabled and self._scheduler is not None:
            self._scheduler.start()

    def stop(self) -> None:
        """Stop the scheduler and release audio resources."""
        if self._scheduler is not None:
            self._scheduler.stop()
        if self._playback is not None:
            try:
                self._playback.close()
            except Exception:  # noqa: BLE001 - shutdown is best-effort
                _log.exception("voice: playback.close failed")

    @staticmethod
    def disabled(reason: str) -> VoiceCoach:
        """A coach that accepts (and drops) advisories — used when the bank can't be trusted."""
        _log.error("voice: running DISABLED — %s", reason)
        return VoiceCoach(None, None, enabled=False, disabled_reason=reason)

    @classmethod
    def from_bank(
        cls,
        bank_dir: str | Path,
        config: VoiceConfig | None = None,
        *,
        playback: Playback | None = None,
        clock: Callable[[], float] = time.monotonic,
        backend: str = "rtmixer",
        dispatch_listener: Callable[..., None] | None = None,
    ) -> VoiceCoach:
        """Build a coach from a baked bank directory.

        On any manifest problem that makes playback untrustworthy (unreadable manifest, a
        ``vocabulary_hash`` mismatch meaning the wording changed but the bank was not re-baked, or
        a ``voice_signature`` persona/prosody/intensity mismatch — issue #438), returns
        :meth:`disabled` rather than raising. ``playback`` may be injected (tests pass a
        :class:`~tools.ai_sidecar.voice.playback.RecordingPlayback`); otherwise the real backend is
        built lazily from the bank.

        ``dispatch_listener`` (issue #511 Part D) is called with one
        :class:`~tools.ai_sidecar.voice.dispatch.VoiceDispatch` per clip the scheduler actually
        dispatches — the seam the sidecar uses to broadcast ``coaching.voice`` frames to remote
        audio endpoints. ``None`` (the default) leaves the playback unwrapped.
        """
        config = config or VoiceConfig()
        base = Path(bank_dir)
        try:
            manifest = Manifest.load(base / MANIFEST_FILENAME)
        except ManifestError as exc:
            return cls.disabled(f"cannot load manifest: {exc}")

        report = manifest.validate(base if playback is None else None)
        if not report.vocabulary_matches:
            # Wording drifted from the baked bank — refuse to play anything (could be the wrong
            # clip).
            return cls.disabled("; ".join(report.problems) or "vocabulary_hash mismatch")
        if not report.signature_matches:
            # Persona/prosody/intensity chain drifted with identical wording — vocabulary_hash
            # cannot see this (issue #438); the baked tones are stale, so refuse rather than speak
            # with the wrong persona.
            return cls.disabled("; ".join(report.problems) or "voice_signature mismatch")
        for problem in report.problems:
            # File-level problems are non-fatal: the resolver/bank skip the affected clip. Log
            # loudly.
            _log.error("voice: bank problem (will skip affected clip): %s", problem)

        if playback is None:
            playback = cls._build_playback(manifest, base, config, backend)
            if playback is None:
                return cls.disabled(f"could not initialize audio backend {backend!r}")

        if dispatch_listener is not None:
            from tools.ai_sidecar.voice.dispatch import DispatchTapPlayback

            playback = DispatchTapPlayback(
                playback,
                dispatch_listener,
                duration_lookup=_bank_duration_lookup(playback),
            )

        resolver = Resolver(manifest)
        scheduler = Scheduler(resolver, playback, config, clock=clock)
        return cls(scheduler, playback, enabled=True)

    @staticmethod
    def _build_playback(
        manifest: Manifest, bank_dir: Path, config: VoiceConfig, backend: str
    ) -> Playback | None:
        """Lazily construct the real audio backend (deps imported here only).

        When ``backend="rtmixer"`` but the ``rtmixer`` extra is not importable, fall back to
        :class:`SoundDevicePlayback` rather than disabling the coach. This is the common Windows
        reality: ``rtmixer`` needs a C/PortAudio build (and is frequently absent from a PyInstaller
        bundle or a plain ``pip install``), while ``sounddevice`` ships a bundled-PortAudio wheel.
        ``sounddevice`` is the documented interim backend behind the same interface (issue #340), so
        the coach keeps speaking instead of going silent on a missing optional dep. A *device* or
        *driver* fault (not a missing module) still disables — that fault would recur on sounddevice
        too, and "stay silent" beats "play onto the wrong endpoint".
        """
        try:
            from tools.ai_sidecar.voice.playback import (
                Bank,
                RtMixerPlayback,
                SoundDevicePlayback,
            )

            bank = Bank.from_manifest(manifest, bank_dir)
            if backend == "sounddevice":
                return SoundDevicePlayback(
                    bank, device_name=config.device_name, host_api=config.host_api
                )
            if backend == "rtmixer":
                try:
                    return RtMixerPlayback(
                        bank, device_name=config.device_name, host_api=config.host_api
                    )
                except ImportError:
                    # rtmixer (or its native PortAudio dep) is not installed/bundled. Degrade to
                    # the sounddevice backend so the coach still speaks (issue #340 fallback).
                    _log.warning(
                        "voice: rtmixer backend unavailable (module not importable); "
                        "falling back to the sounddevice backend"
                    )
                    return SoundDevicePlayback(
                        bank, device_name=config.device_name, host_api=config.host_api
                    )
            _log.error("voice: unknown backend %r", backend)
            return None
        except Exception:  # noqa: BLE001 - missing extra / no device / driver fault → disable, not crash
            _log.exception("voice: failed to initialize audio backend %r", backend)
            return None
