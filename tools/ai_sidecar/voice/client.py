"""Voice client: subscribe to ``coaching.cue`` and speak cues via pyttsx3 (Windows SAPI).

The pure core — :func:`extract_advisory`, :class:`VoiceClient.handle_frame` (speaker + clock
injected), and the hello/subscribe frame builders — is CI-testable on any OS. The websockets loop
and the pyttsx3 engine are pragma-guarded (Windows / runtime / audio). Piper TTS is M2.

Run on the rig alongside the sidecar (``pip install -e ".[voice-client]"``):

    python -m tools.ai_sidecar.voice.client --url ws://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
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

#: Max pending TTS phrases; when full, drop the oldest so memory stays bounded under cue bursts.
_VOICE_QUEUE_MAX = 4
DEFAULT_TTS_RATE = 240
DEFAULT_TTS_VOLUME = 1.0

#: pyttsx3 rate (wpm) + volume per intensity register (issue #368) — the WS/pyttsx3 path can't bake
#: prosody, but it can speak faster + louder as the situation escalates, so the WS client conveys
#: the same intensity the in-process bank coach does (codex review #371).
_REGISTER_RATE: dict[str, int] = {"calm": 185, "firm": 200, "critical": 215}
_REGISTER_VOLUME: dict[str, float] = {"calm": 0.9, "firm": 1.0, "critical": 1.0}


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


def _pyttsx3_speaker(rate: int = DEFAULT_TTS_RATE, volume: float = DEFAULT_TTS_VOLUME):
    """Build a non-blocking speak(text, register) backed by pyttsx3 on a dedicated worker thread.

    pyttsx3/SAPI must init and run on one thread; the worker owns the engine so the asyncio loop
    stays responsive and incoming ``act`` cues can still be arbitrated while speech plays. The
    register (issue #368) sets the engine rate + volume per utterance so the WS path escalates tone.
    """
    import logging
    import queue
    import threading

    import pyttsx3

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
                engine.setProperty("rate", _REGISTER_RATE.get(register, rate))
                engine.setProperty("volume", _REGISTER_VOLUME.get(register, volume))
                engine.say(text)
                engine.runAndWait()
            except Exception:
                logger.exception("pyttsx3 playback failed for %r", text)

    t = threading.Thread(target=worker, daemon=True, name="pyttsx3-voice")
    t.start()

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


async def run(url: str, *, token: str | None = None) -> None:  # pragma: no cover - runtime/ws/audio
    """Connect, advertise the voice class, subscribe to coaching.cue, and speak arriving cues."""
    import json
    import time

    import websockets

    headers = {AUTH_HEADER: token} if token else {}
    client = VoiceClient(_pyttsx3_speaker())
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
