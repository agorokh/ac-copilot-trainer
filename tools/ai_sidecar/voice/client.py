"""Voice client: subscribe to ``coaching.cue`` and speak cues via pyttsx3 (Windows SAPI).

The pure core — :func:`extract_advisory`, :class:`VoiceClient.handle_frame` (speaker + clock
injected), and the hello/subscribe frame builders — is CI-testable on any OS. The websockets loop
and the pyttsx3 engine are pragma-guarded (Windows / runtime / audio). Piper TTS is M2.

Run on the rig alongside the sidecar (``pip install -e ".[voice-client]"``):

    python -m tools.ai_sidecar.voice.client --url ws://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Mapping
from typing import Any

from tools.ai_sidecar.external_protocol import (
    AUTH_HEADER,
    CLIENT_CLASS_KEY,
    CLIENT_CLASS_VOICE,
    ENVELOPE_KEY,
    ENVELOPE_VERSION,
    TOPIC_COACHING_CUE,
    TYPE_HELLO,
    TYPE_KEY,
    TYPE_STATE_SNAPSHOT,
    TYPE_STATE_SUBSCRIBE,
)
from tools.ai_sidecar.voice.cue import CueArbiter, SpokenCue
from tools.ai_sidecar.voice.vocabulary import normalize_register

#: Max pending TTS phrases; when full, drop the oldest so memory stays bounded under cue bursts.
_VOICE_QUEUE_MAX = 4
DEFAULT_TTS_RATE = 240
DEFAULT_TTS_VOLUME = 1.0

#: pyttsx3 rate/volume offsets per intensity register. The configured base rate/volume remains the
#: center point so rig tuning knobs still work; the WS/pyttsx3 path just nudges calm down and
#: critical up to convey intensity when there is no baked prosody.
_REGISTER_RATE_DELTA: dict[str, int] = {
    "calm": -18,
    "alert": -6,
    "urgent": 8,
    "critical": 20,
}
_REGISTER_VOLUME_DELTA: dict[str, float] = {
    "calm": -0.12,
    "alert": -0.03,
    "urgent": 0.05,
    "critical": 0.12,
}


def extract_advisory(frame: dict[str, Any]) -> dict[str, Any] | None:
    """Return the advisory dict from a ``coaching.cue`` snapshot frame, else ``None``. Pure."""
    if not isinstance(frame, dict):
        return None
    if frame.get(TYPE_KEY) != TYPE_STATE_SNAPSHOT or frame.get("topic") != TOPIC_COACHING_CUE:
        return None
    payload = frame.get("payload")
    return payload if isinstance(payload, dict) else None


def make_hello_frame(client: str = "voice-client") -> dict[str, Any]:
    """Hello advertising the ``voice`` client class."""
    return {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: TYPE_HELLO,
        "client": client,
        CLIENT_CLASS_KEY: CLIENT_CLASS_VOICE,
    }


def make_subscribe_frame() -> dict[str, Any]:
    """Subscribe to the ``coaching.cue`` topic."""
    return {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: TYPE_STATE_SUBSCRIBE,
        "topics": [TOPIC_COACHING_CUE],
    }


class VoiceClient:
    """Stateful cue consumer: frame -> arbiter -> speak. Speaker + clock injected for tests."""

    def __init__(
        self, speaker: Callable[[str, str], None], *, arbiter: CueArbiter | None = None
    ) -> None:
        self._speak = speaker
        self._arbiter = arbiter or CueArbiter()

    def handle_frame(self, frame: dict[str, Any], now_s: float) -> SpokenCue | None:
        """Process one inbound frame; speak + return the cue when one is selected, else ``None``."""
        advisory = extract_advisory(frame)
        if advisory is None:
            return None
        cue = self._arbiter.select([advisory], now_s)
        if cue is not None:
            self._speak(cue.text, cue.register)  # register drives the speaker's rate/volume (#368)
        return cue


def should_enqueue_voice_cue(*, failed: bool, worker_alive: bool) -> bool:
    """Return True when the pyttsx3 worker may accept another queued cue."""
    return not failed and worker_alive


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _register_rate(base_rate: int, register: str) -> int:
    return max(1, base_rate + _REGISTER_RATE_DELTA.get(normalize_register(register), 0))


def _register_volume(base_volume: float, register: str) -> float:
    return min(
        1.0,
        max(0.0, base_volume + _REGISTER_VOLUME_DELTA.get(normalize_register(register), 0.0)),
    )


def _disabled_speaker(reason: str) -> Callable[[str, str], None]:
    import logging

    logger = logging.getLogger(__name__)
    warned = False

    def speak(text: str, register: str = "calm") -> None:
        nonlocal warned
        del register
        if not warned:
            logger.warning("pyttsx3 disabled: %s; dropping cue %r", reason, text)
            warned = True

    return speak


def _pyttsx3_speaker(
    base_rate: int = DEFAULT_TTS_RATE,
    base_volume: float = DEFAULT_TTS_VOLUME,
    *,
    require_opt_in: bool = True,
    environ: Mapping[str, str] | None = None,
    rate: int | None = None,
    volume: float | None = None,
    startup_timeout_s: float | None = None,
) -> Callable[[str, str], None]:
    """Build a non-blocking speak(text, register) backed by pyttsx3 on a dedicated worker thread.

    pyttsx3/SAPI must init and run on one thread; the worker owns the engine so the asyncio loop
    stays responsive and incoming ``act`` cues can still be arbitrated while speech plays. The
    register (issue #368) sets the engine rate + volume per utterance so the WS path escalates tone.
    """
    import logging
    import os
    import queue
    import threading

    import pyttsx3

    if rate is not None:
        base_rate = rate
    if volume is not None:
        base_volume = volume

    env = os.environ if environ is None else environ
    if require_opt_in:
        if not _env_truthy(env.get("AC_COPILOT_VOICE_TTS")):
            return _disabled_speaker("AC_COPILOT_VOICE_TTS=1 is required")
        if env.get("AC_COPILOT_VOICE_BANK"):
            return _disabled_speaker("AC_COPILOT_VOICE_BANK is configured")

    logger = logging.getLogger(__name__)
    q: queue.Queue[tuple[str, str] | None] = queue.Queue(maxsize=_VOICE_QUEUE_MAX)
    ready = threading.Event()
    failed = threading.Event()

    def worker() -> None:
        try:
            engine = pyttsx3.init()
        except Exception:
            failed.set()
            logger.exception("pyttsx3 voice worker failed to initialize")
            return
        ready.set()
        while True:
            item = q.get()
            if item is None:
                break
            text, register = item
            try:
                engine.setProperty("rate", _register_rate(base_rate, register))
                engine.setProperty("volume", _register_volume(base_volume, register))
                engine.say(text)
                engine.runAndWait()
            except Exception:
                logger.exception("pyttsx3 playback failed for %r", text)

    t = threading.Thread(target=worker, daemon=True, name="pyttsx3-voice")
    t.start()
    if startup_timeout_s is not None:
        deadline = time.monotonic() + max(0.0, startup_timeout_s)
        while not ready.is_set():
            if failed.is_set():
                raise RuntimeError("pyttsx3 voice worker failed to initialize")
            if not t.is_alive():
                raise RuntimeError("pyttsx3 voice worker exited before initialization")
            if time.monotonic() >= deadline:
                raise RuntimeError("pyttsx3 voice worker did not become ready")
            time.sleep(0.01)

    def speak(text: str, register: str = "calm") -> None:
        if not should_enqueue_voice_cue(failed=failed.is_set(), worker_alive=t.is_alive()):
            logger.warning("pyttsx3 unavailable; dropping cue %r", text)
            return
        try:
            q.put_nowait((text, register))
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait((text, register))
            except queue.Full:
                logger.warning("pyttsx3 queue saturated; dropping cue %r", text)

    return speak


def _standalone_speaker() -> Callable[[str, str], None]:
    """Standalone WS client owns its pyttsx3 output, so it does not require fallback env opt-in."""
    return _pyttsx3_speaker(require_opt_in=False)


async def run(url: str, *, token: str | None = None) -> None:  # pragma: no cover - runtime/ws/audio
    """Connect, advertise the voice class, subscribe to coaching.cue, and speak arriving cues."""
    import json
    import time

    import websockets

    headers = {AUTH_HEADER: token} if token else {}
    client = VoiceClient(_standalone_speaker())
    async with websockets.connect(url, additional_headers=headers) as ws:
        await ws.send(json.dumps(make_hello_frame()))
        await ws.send(json.dumps(make_subscribe_frame()))
        async for raw in ws:
            try:
                frame = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(frame, dict):
                client.handle_frame(frame, time.monotonic())


def main() -> None:  # pragma: no cover - CLI wiring
    import asyncio

    p = argparse.ArgumentParser(description="AC Copilot voice client (coaching.cue -> TTS)")
    p.add_argument("--url", default="ws://127.0.0.1:8765")
    p.add_argument("--token", default=None)
    args = p.parse_args()
    try:
        asyncio.run(run(args.url, token=args.token))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":  # pragma: no cover
    main()
