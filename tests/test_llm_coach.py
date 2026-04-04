"""Ollama debrief helper tests (issue #46) — mocked HTTP, no live inference."""

from __future__ import annotations

import json

import pytest

from tools.ai_sidecar.coaching import llm_coach


def test_debrief_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AC_COPILOT_OLLAMA_ENABLE", raising=False)
    assert llm_coach.debrief_feature_enabled() is False
    assert llm_coach.compose_debrief({"lap": 1, "lapTimeMs": 90000}, []) is None


def test_rules_fallback_has_two_paragraphs() -> None:
    text = llm_coach.rules_fallback_debrief(
        {
            "lap": 2,
            "lapTimeMs": 91500,
            "coachingHints": ["Brake earlier T3", "More throttle T5"],
        },
        [
            {"suggestion": "Corner 1 min speed +5 km/h vs reference"},
        ],
    )
    assert "\n\n" in text
    assert "91.500" in text
    assert "T3" in text or "throttle" in text.lower()
    assert "Corner 1" in text


def test_compose_debrief_rules_when_ollama_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AC_COPILOT_OLLAMA_ENABLE", "1")
    monkeypatch.setattr(
        llm_coach,
        "call_ollama_generate",
        lambda *_a, **_k: None,
    )
    text = llm_coach.compose_debrief(
        {"lap": 1, "lapTimeMs": 88000, "coachingHints": ["hint"]},
        [],
    )
    assert text
    assert "hint" in text


def test_compose_debrief_prefers_llm_when_ollama_returns_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AC_COPILOT_OLLAMA_ENABLE", "1")

    def _stub_llm(*_a: object, **_k: object) -> str:
        return "UNIQUE_LLM_DEBRIEF_BODY"

    monkeypatch.setattr(llm_coach, "call_ollama_generate", _stub_llm)
    text = llm_coach.compose_debrief({"lap": 1, "lapTimeMs": 88000}, [])
    assert text == "UNIQUE_LLM_DEBRIEF_BODY"
    assert "Post-lap debrief" not in text


def test_call_ollama_generate_non_object_json_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(["not", "an", "object"]).encode("utf-8")

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return payload

    monkeypatch.setattr(llm_coach.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert (
        llm_coach.call_ollama_generate(
            "p",
            base_url="http://127.0.0.1:11434",
            model="m",
            temperature=0.2,
            num_predict=100,
            timeout_sec=10.0,
        )
        is None
    )


def test_call_ollama_generate_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"response": "  First paragraph.\n\nSecond line.  "}).encode("utf-8")

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return payload

    monkeypatch.setattr(
        llm_coach.urllib.request,
        "urlopen",
        lambda *a, **k: _Resp(),
    )
    out = llm_coach.call_ollama_generate(
        "prompt",
        base_url="http://127.0.0.1:11434",
        model="m",
        temperature=0.2,
        num_predict=100,
        timeout_sec=10.0,
    )
    assert out
    assert "First paragraph" in out


def test_ollama_base_url_whitespace_host_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AC_COPILOT_OLLAMA_HOST", "  \t  ")
    assert llm_coach.ollama_base_url() == llm_coach._DEFAULT_HOST.rstrip("/")


def test_call_ollama_generate_rejects_schemeless_base_url() -> None:
    assert (
        llm_coach.call_ollama_generate(
            "p",
            base_url="127.0.0.1:11434",
            model="m",
            temperature=0.2,
            num_predict=100,
            timeout_sec=2.0,
        )
        is None
    )


def test_call_ollama_generate_incomplete_read_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import http.client

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(llm_coach.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert (
        llm_coach.call_ollama_generate(
            "p",
            base_url="http://127.0.0.1:11434",
            model="m",
            temperature=0.2,
            num_predict=100,
            timeout_sec=2.0,
        )
        is None
    )


def test_call_ollama_generate_network_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def _boom(*a: object, **k: object) -> None:
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(llm_coach.urllib.request, "urlopen", _boom)
    assert (
        llm_coach.call_ollama_generate(
            "p",
            base_url="http://127.0.0.1:9",
            model="m",
            temperature=0.2,
            num_predict=100,
            timeout_sec=2.0,
        )
        is None
    )


def test_prepare_outbound_attaches_debrief_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AC_COPILOT_OLLAMA_ENABLE", "1")
    monkeypatch.setattr(llm_coach, "call_ollama_generate", lambda *_a, **_k: None)
    from tools.ai_sidecar.protocol import (
        EVENT_COACHING_RESPONSE,
        PROTOCOL_VERSION,
        prepare_outbound_message,
    )

    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "lap_complete",
            "lap": 3,
            "lapTimeMs": 92000,
            "coachingHints": ["stay smooth"],
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_COACHING_RESPONSE
    assert "debrief" in out
    assert "stay smooth" in out["debrief"]
