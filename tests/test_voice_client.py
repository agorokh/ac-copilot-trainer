"""Tests for the M0 voice client core (tools.ai_sidecar.voice.client) — frame parse + speak path."""

from __future__ import annotations

import sys
import threading
import time

import pytest

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
    _standalone_speaker,
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
    spoken: list[tuple[str, str]] = []  # (text, register) — the speaker is register-aware (#368)
    vc = VoiceClient(lambda text, register: spoken.append((text, register)))
    cue = vc.handle_frame(_cue_frame(), now_s=100.0)
    assert cue is not None
    assert cue.kind == "late_brake"
    assert spoken == [(cue.text, cue.register)]
    assert "Turn 4" in cue.text  # 0-based corner 3 -> Turn 4 (calm anticipatory keeps the corner)


def test_voice_client_ignores_non_cue_frame():
    spoken: list[tuple[str, str]] = []
    vc = VoiceClient(lambda text, register: spoken.append((text, register)))
    assert vc.handle_frame({"type": TYPE_HELLO}, now_s=1.0) is None
    assert spoken == []


def test_voice_client_respects_corner_cooldown():
    spoken: list[tuple[str, str]] = []
    vc = VoiceClient(lambda text, register: spoken.append((text, register)))
    # a non-urgent (info) cue is anti-nag throttled (an `act` escalation would bypass — #371).
    frame = _cue_frame(kind="apex_deficit", urgency="info")
    assert vc.handle_frame(frame, now_s=0.0) is not None
    # same corner + kind, within the 6 s per-corner cooldown -> suppressed
    assert vc.handle_frame(frame, now_s=1.0) is None
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
    speak = _pyttsx3_speaker(require_opt_in=False)
    time.sleep(0.05)
    speak("hello")  # worker failed; must not raise


def test_pyttsx3_speaker_can_fail_fast_when_startup_fails(monkeypatch):
    class _BrokenPyttsx3:
        @staticmethod
        def init():
            raise RuntimeError("no engine")

    monkeypatch.setitem(sys.modules, "pyttsx3", _BrokenPyttsx3())

    with pytest.raises(RuntimeError, match="failed to initialize"):
        _pyttsx3_speaker(require_opt_in=False, startup_timeout_s=0.2)


def test_pyttsx3_speaker_requires_tts_opt_in_and_no_bank(monkeypatch):
    called = False

    class _Pyttsx3:
        @staticmethod
        def init():
            nonlocal called
            called = True
            raise AssertionError("pyttsx3 should not initialize")

    monkeypatch.setitem(sys.modules, "pyttsx3", _Pyttsx3())
    _pyttsx3_speaker(environ={})("hello")
    _pyttsx3_speaker(environ={"AC_COPILOT_VOICE_TTS": "1", "AC_COPILOT_VOICE_BANK": "/bank"})(
        "hello"
    )

    assert called is False


def test_pyttsx3_speaker_enqueues_when_worker_ready(monkeypatch):
    ready = threading.Event()
    spoken: list[str] = []
    props: list[tuple[str, float | int]] = []

    class _Engine:
        def setProperty(self, name: str, value: float | int) -> None:
            props.append((name, value))

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
    speak = _pyttsx3_speaker(base_rate=260, base_volume=0.8, require_opt_in=False)
    assert ready.wait(timeout=1.0)
    speak("Turn 1", "unknown")
    deadline = time.monotonic() + 1.0
    while not spoken and time.monotonic() < deadline:
        time.sleep(0.01)
    assert spoken == ["Turn 1"]
    assert ("rate", 260) in props
    assert ("volume", 0.8) in props


def test_pyttsx3_register_tuning_is_centered_on_configured_values(monkeypatch):
    ready = threading.Event()
    spoken: list[str] = []
    props: list[tuple[str, float | int]] = []

    class _Engine:
        def setProperty(self, name: str, value: float | int) -> None:
            props.append((name, value))

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
    speak = _pyttsx3_speaker(base_rate=260, base_volume=0.8, require_opt_in=False)
    assert ready.wait(timeout=1.0)
    speak("Brake", "critical")
    deadline = time.monotonic() + 1.0
    while not spoken and time.monotonic() < deadline:
        time.sleep(0.01)
    assert spoken == ["Brake"]
    assert ("rate", 275) in props
    assert ("volume", 0.9) in props


def test_standalone_speaker_does_not_require_fallback_env_opt_in(monkeypatch):
    calls: list[bool] = []

    def fake_pyttsx3_speaker(*, require_opt_in: bool = True):
        calls.append(require_opt_in)
        return lambda text, register="calm": None

    monkeypatch.setattr("tools.ai_sidecar.voice.client._pyttsx3_speaker", fake_pyttsx3_speaker)

    _standalone_speaker()

    assert calls == [False]


def test_pyttsx3_speaker_drops_oldest_when_queue_full(monkeypatch):
    init_started = threading.Event()
    init_block = threading.Event()
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
            init_started.set()
            assert init_block.wait(timeout=1.0)
            return _Engine()

    monkeypatch.setitem(sys.modules, "pyttsx3", _Pyttsx3())
    monkeypatch.setattr("tools.ai_sidecar.voice.client._VOICE_QUEUE_MAX", 2)
    speak = _pyttsx3_speaker(require_opt_in=False)
    assert init_started.wait(timeout=1.0)
    speak("one")
    speak("two")
    speak("three")
    init_block.set()
    deadline = time.monotonic() + 1.0
    while len(spoken) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "one" not in spoken
    assert "two" in spoken
    assert "three" in spoken
