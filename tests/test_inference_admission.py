"""Provider/placement failures and real blocking-worker admission (#854)."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from tools.ai_sidecar.coaching import llm_coach as llm
from tools.ai_sidecar.coaching.generation import (
    RIG_GPU_UUID,
    LatestGenerationQueue,
    apply_rig_inference_defaults,
)


class Response:
    def __init__(self, value):
        self.raw = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self, *_args):
        return self.raw


def generate(**overrides):
    options = dict(
        base_url="http://127.0.0.1:11435/v1",
        model="llama3.2:3b",
        temperature=0.0,
        num_predict=20,
        timeout_sec=1.0,
    )
    options.update(overrides)
    return llm.call_ollama_generate("grounded prompt", **options)


def test_chat_provider_payload_and_health_attestation(monkeypatch):
    monkeypatch.setenv("AC_COPILOT_INFERENCE_PROVIDER", "openai")
    monkeypatch.setenv("AC_COPILOT_INFERENCE_GPU_UUID", RIG_GPU_UUID)
    monkeypatch.setenv("AC_COPILOT_INFERENCE_HEALTH_URL", "http://127.0.0.1:11435/health")
    calls = []

    def request(req, **kwargs):
        calls.append((req, kwargs))
        if isinstance(req, str):
            return Response(
                dict(
                    ready=True,
                    model="llama3.2:3b",
                    gpu_uuid=RIG_GPU_UUID,
                    utc_epoch=time.time(),
                    placement=[{"gpu_uuid": RIG_GPU_UUID}],
                    provider="ollama",
                )
            )
        return Response({"choices": [{"message": {"content": "HOLD STEADY"}}]})

    monkeypatch.setattr(llm.urllib.request, "urlopen", request)
    assert generate() == "HOLD STEADY"
    body = json.loads(calls[1][0].data)
    assert calls[1][0].full_url == "http://127.0.0.1:11435/v1/chat/completions"
    assert body["model"] == "llama3.2:3b" and body["max_tokens"] == 20
    assert body["seed"] == 42 and body["stream"] is False
    assert llm.inference_status()["backend_provider"] == "ollama"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ready", False),
        ("gpu_uuid", "GPU-main-3060"),
        ("model", "other-model"),
        ("utc_epoch", 0),
        ("utc_epoch", float("nan")),
        ("utc_epoch", True),
        ("placement", []),
        ("placement", [{"gpu_uuid": "GPU-main-3060"}]),
    ],
)
def test_bad_placement_never_generates(monkeypatch, field, value):
    monkeypatch.setenv("AC_COPILOT_INFERENCE_GPU_UUID", RIG_GPU_UUID)
    monkeypatch.setenv("AC_COPILOT_INFERENCE_HEALTH_URL", "http://127.0.0.1:11435/health")
    calls = []

    def request(req, **_kwargs):
        calls.append(req)
        health = dict(ready=True, model="llama3.2:3b", gpu_uuid=RIG_GPU_UUID, utc_epoch=time.time())
        health[field] = value
        return Response(health)

    monkeypatch.setattr(llm.urllib.request, "urlopen", request)
    assert generate() is None
    assert calls == ["http://127.0.0.1:11435/health"]
    assert llm.inference_status()["fallback_reason"] == "placement_unavailable"


@pytest.mark.parametrize(
    "overrides",
    [
        {"temperature": float("nan")},
        {"timeout_sec": float("inf")},
        {"num_predict": 129},
        {"deadline": float("nan")},
        {"base_url": "http://example.com:11434"},
    ],
)
def test_invalid_config_does_no_network_io(monkeypatch, overrides):
    calls = []
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda *args, **kw: calls.append(args))
    assert generate(**overrides) is None
    assert calls == []


def test_rig_defaults_disable_model_and_drop_retired_3050_endpoint():
    """#854: RTX3050 removed — default is rules-only and no retired endpoint is seeded."""
    env: dict[str, str] = {}
    apply_rig_inference_defaults(env)
    assert env["AC_COPILOT_INFERENCE_ENABLE"] == "0"
    for retired in (
        "AC_COPILOT_INFERENCE_BASE_URL",
        "AC_COPILOT_INFERENCE_HEALTH_URL",
        "AC_COPILOT_INFERENCE_GPU_UUID",
    ):
        assert retired not in env
    # Bounded generation profile stays seeded (finite caps).
    assert env["AC_COPILOT_OLLAMA_TIMEOUT_SEC"] == "8"
    assert env["AC_COPILOT_OLLAMA_NUM_PREDICT"] == "64"


def test_operator_reenable_alias_and_explicit_endpoint_preserved():
    """Explicit operator opt-in and an approved endpoint survive the defaults pass."""
    env = {
        "AC_COPILOT_OLLAMA_ENABLE": "1",
        "AC_COPILOT_INFERENCE_BASE_URL": "http://127.0.0.1:11500/v1",
    }
    apply_rig_inference_defaults(env)
    assert env["AC_COPILOT_INFERENCE_ENABLE"] == "1"
    assert env["AC_COPILOT_INFERENCE_BASE_URL"] == "http://127.0.0.1:11500/v1"


def test_default_off_makes_no_model_http_call_but_keeps_rules(monkeypatch):
    """Default-off startup performs zero model HTTP I/O; deterministic rules remain."""
    env: dict[str, str] = {}
    apply_rig_inference_defaults(env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    def _boom(*_args, **_kwargs):
        raise AssertionError("no model HTTP call allowed when inference is default-off")

    monkeypatch.setattr(llm.urllib.request, "urlopen", _boom)
    inbound = {"lap": 3, "lapTimeMs": 95000, "coachingHints": ["brake later into T1"]}
    assert llm.compose_debrief(inbound, []) is None
    assert llm.compose_llm_debrief_only(inbound, []) is None
    assert llm.compose_corner_hint("T3", 180, 130, 80) is None
    assert llm.inference_status()["enabled"] is False
    # Deterministic CPU-brain rules advice is independent of the model path.
    assert llm.rules_fallback_debrief(inbound, []).startswith("Post-lap debrief")


def test_invalid_env_falls_back_without_hiding_programming_error(monkeypatch):
    monkeypatch.setenv("AC_COPILOT_OLLAMA_ENABLE", "1")
    monkeypatch.setenv("AC_COPILOT_OLLAMA_TEMPERATURE", "nan")
    assert llm.compose_debrief({"lap": 1}, []).startswith("Post-lap debrief")
    assert llm.compose_llm_debrief_only({"lap": 1}, []) is None


@pytest.mark.parametrize(
    "current,target,text,accepted",
    [
        (180, 130, "BRAKE HARD NOW", True),
        (95, 120, "BRAKE HARD NOW", False),
        (152, 149, "HOLD STEADY", True),
        (152, 149, "BRAKE EARLIER", False),
        (180, 130, "BRAKE HARD AT 70 METRES", False),
        (180, 130, "REDUCE THROTTLE TO PREVENT TIRE LOCKUP", False),
    ],
)
def test_corner_output_cannot_contradict_facts(monkeypatch, current, target, text, accepted):
    monkeypatch.setenv("AC_COPILOT_OLLAMA_ENABLE", "1")
    monkeypatch.setattr(llm, "call_ollama_generate", lambda *args, **kw: text)
    result = llm.compose_corner_hint("T3", current, target, 80)
    assert result == (text if accepted else None)


def test_cancelled_submitter_keeps_exclusive_worker_and_only_latest_pending():
    async def run():
        queue = LatestGenerationQueue()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def slow():
            calls.append("active")
            entered.set()
            assert release.wait(3)
            return "active-result"

        first = asyncio.create_task(queue.submit(slow, deadline=time.monotonic() + 5))
        assert await asyncio.to_thread(entered.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(
            queue.submit(lambda: calls.append("obsolete"), deadline=time.monotonic() + 5)
        )
        await asyncio.sleep(0)
        third = asyncio.create_task(
            queue.submit(
                lambda: calls.append("latest") or "latest-result", deadline=time.monotonic() + 5
            )
        )
        await asyncio.sleep(0)
        assert await second is None
        assert queue.status() == {"active": True, "pending": 1, "discarded": 1}
        assert calls == ["active"]
        release.set()
        assert await third == "latest-result"
        assert calls == ["active", "latest"]

    asyncio.run(run())


def test_expired_pending_does_not_execute_and_running_reply_is_discarded():
    async def run():
        queue = LatestGenerationQueue()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def slow():
            entered.set()
            release.wait(2)
            return "late"

        now = time.monotonic()
        first = asyncio.create_task(queue.submit(slow, deadline=now + 0.05))
        assert await asyncio.to_thread(entered.wait, 1)
        pending = asyncio.create_task(
            queue.submit(lambda: calls.append("must not run"), deadline=now + 0.05)
        )
        await asyncio.sleep(0.07)
        release.set()
        assert await first is None and await pending is None
        assert calls == [] and queue.discarded == 2

    asyncio.run(run())
