"""Tests for the M0 voice client core (tools.ai_sidecar.voice.client) — frame parse + speak path."""

from __future__ import annotations

import sys
import threading
import time

from tools.ai_sidecar.external_protocol import (
    CLIENT_CLASS_VOICE,
    TOPIC_COACHING_CUE,
    TYPE_HELLO,
    TYPE_STATE_SNAPSHOT,
    TYPE_STATE_SUBSCRIBE,
    make_coaching_cue,
)
from tools.ai_sidecar.voice.client import (
    VoiceClient,
    _pyttsx3_speaker,
    extract_advisory,
    make_hello_frame,
    make_subscribe_frame,
    should_enqueue_voice_cue,
)


def _cue_frame(kind="late_brake", corner=3, urgency="act"):
    advisory = {
        "kind": kind,
        "corner": corner,
        "spline": 0.5,
        "urgency": urgency,
        "message": "x",
        "detail": {},
    }
    return make_coaching_cue(advisory)


def test_extract_advisory_from_cue_frame():
    adv = extract_advisory(_cue_frame())
    assert adv is not None
    assert adv["kind"] == "late_brake"
    assert adv["corner"] == 3


def test_extract_advisory_ignores_other_topics_and_types():
    assert extract_advisory({"type": TYPE_STATE_SNAPSHOT, "topic": "delta", "state": {}}) is None
    assert extract_advisory({"type": TYPE_HELLO}) is None
    assert extract_advisory("nope") is None
    # right type+topic but non-dict state
    bad = {"type": TYPE_STATE_SNAPSHOT, "topic": TOPIC_COACHING_CUE, "state": 5}
    assert extract_advisory(bad) is None


def test_voice_client_speaks_selected_cue():
    spoken: list[str] = []
    vc = VoiceClient(spoken.append)
    cue = vc.handle_frame(_cue_frame(), now_s=100.0)
    assert cue is not None
    assert cue.kind == "late_brake"
    assert spoken == [cue.text]
    assert "Turn 4" in cue.text  # 0-based corner 3 -> Turn 4


def test_voice_client_ignores_non_cue_frame():
    spoken: list[str] = []
    vc = VoiceClient(spoken.append)
    assert vc.handle_frame({"type": TYPE_HELLO}, now_s=1.0) is None
    assert spoken == []


def test_voice_client_respects_corner_cooldown():
    spoken: list[str] = []
    vc = VoiceClient(spoken.append)
    assert vc.handle_frame(_cue_frame(), now_s=0.0) is not None
    # same corner + kind, within the 6 s per-corner cooldown -> suppressed
    assert vc.handle_frame(_cue_frame(), now_s=1.0) is None
    assert len(spoken) == 1


def test_hello_and_subscribe_frame_shapes():
    h = make_hello_frame()
    assert h["type"] == TYPE_HELLO
    assert h["client_class"] == CLIENT_CLASS_VOICE
    s = make_subscribe_frame()
    assert s["type"] == TYPE_STATE_SUBSCRIBE
    assert s["topics"] == [TOPIC_COACHING_CUE]


def test_should_enqueue_voice_cue_requires_live_worker():
    assert should_enqueue_voice_cue(failed=False, worker_alive=True) is True
    assert should_enqueue_voice_cue(failed=True, worker_alive=True) is False
    assert should_enqueue_voice_cue(failed=False, worker_alive=False) is False


def test_pyttsx3_speaker_drops_cues_when_init_fails(monkeypatch):
    class _BrokenPyttsx3:
        @staticmethod
        def init():
            raise RuntimeError("no engine")

    monkeypatch.setitem(sys.modules, "pyttsx3", _BrokenPyttsx3())
    speak = _pyttsx3_speaker()
    time.sleep(0.05)
    speak("hello")  # worker failed; must not raise


def test_pyttsx3_speaker_enqueues_when_worker_ready(monkeypatch):
    ready = threading.Event()
    spoken: list[str] = []

    class _Engine:
        def setProperty(self, *_args, **_kwargs) -> None:
            return None

        def say(self, text: str) -> None:
            spoken.append(text)

        def runAndWait(self) -> None:
            return None

    class _Pyttsx3:
        @staticmethod
        def init():
            ready.set()
            return _Engine()

    monkeypatch.setitem(sys.modules, "pyttsx3", _Pyttsx3())
    speak = _pyttsx3_speaker()
    assert ready.wait(timeout=1.0)
    speak("Turn 1")
    deadline = time.monotonic() + 1.0
    while not spoken and time.monotonic() < deadline:
        time.sleep(0.01)
    assert spoken == ["Turn 1"]
