"""Observability endpoints for the AI sidecar (issue #167).

``/health`` + ``/metrics`` are served over the websockets ``process_request``
hook on the SAME WS port (``make_process_request``); counters live in
``tools.ai_sidecar.observability``. Plain ``asyncio.run`` (the repo has no
pytest-asyncio), mirroring ``test_ai_sidecar_external.py``.
"""

from __future__ import annotations

import asyncio
import json
import socket
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

websockets = pytest.importorskip("websockets")
from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.asyncio.server import serve as ws_serve  # noqa: E402

from tools.ai_sidecar import external_protocol as ep  # noqa: E402
from tools.ai_sidecar import observability as obs  # noqa: E402
from tools.ai_sidecar.server import (  # noqa: E402
    _external_peer_classes,
    _external_peers,
    _handler,
    make_process_request,
    set_voice_runtime_status,
)


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@asynccontextmanager
async def _running_sidecar(token: str | None = None) -> AsyncIterator[int]:
    port = _free_port()
    _external_peers.clear()
    _external_peer_classes.clear()
    set_voice_runtime_status()
    try:
        async with ws_serve(
            lambda ws: _handler(ws, reply_coaching=True),
            "127.0.0.1",
            port,
            process_request=make_process_request(token),
        ):
            yield port
    finally:
        _external_peers.clear()
        _external_peer_classes.clear()
        set_voice_runtime_status()


def _http_get(port: int, path: str) -> tuple[int, list[str], str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return resp.status, resp.headers.get_all("Content-Type") or [], resp.read().decode()


def test_health_endpoint_on_ws_port() -> None:
    async def _run() -> tuple[int, list[str], str]:
        async with _running_sidecar() as port:
            return await asyncio.to_thread(_http_get, port, "/health")

    status, content_types, body = asyncio.run(_run())
    assert status == 200
    # Exactly ONE Content-Type — guards the websockets respond() append-bug.
    assert content_types == ["application/json"]
    payload = json.loads(body)
    assert payload["status"] == "ok"
    assert payload["connected_peers"] == 0
    assert payload["screen_peers"] == 0
    assert payload["voice"]["state"] == "skipped"
    assert payload["voice"]["enabled"] is False


def test_health_endpoint_sanitizes_voice_disabled_paths() -> None:
    async def _run() -> tuple[int, list[str], str]:
        async with _running_sidecar() as port:
            set_voice_runtime_status(
                configured=True,
                enabled=False,
                state="disabled",
                disabled_reason="failed to load reference /Users/driver/rig/ref.json: bad json",
            )
            return await asyncio.to_thread(_http_get, port, "/health")

    status, _content_types, body = asyncio.run(_run())
    payload = json.loads(body)

    assert status == 200
    assert payload["voice"]["disabled_reason"] == "failed to load reference <path> bad json"
    assert "/Users/driver" not in body


def test_metrics_endpoint_single_content_type_and_core_series() -> None:
    async def _run() -> tuple[int, list[str], str]:
        async with _running_sidecar() as port:
            return await asyncio.to_thread(_http_get, port, "/metrics")

    status, content_types, body = asyncio.run(_run())
    assert status == 200
    # Exactly ONE Content-Type, Prometheus exposition — the de-dup fix's guard.
    assert content_types == ["text/plain; version=0.0.4; charset=utf-8"]
    assert "ac_sidecar_up 1" in body
    assert "ac_sidecar_build_info{" in body
    assert "ac_sidecar_connected_peers 0" in body
    assert "ac_sidecar_screen_peers 0" in body


def test_ws_upgrade_still_works_and_counts_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate the process-global counters so the exact-count assertion below is
    # deterministic under the full suite (other tests also drive hello frames
    # through the shared METRICS singleton, which would push the count past 1).
    monkeypatch.setattr(obs, "METRICS", obs.SidecarMetrics())

    async def _run() -> str:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}") as client:
                await client.send(
                    json.dumps({ep.ENVELOPE_KEY: 1, ep.TYPE_KEY: ep.TYPE_HELLO, "client": "test"})
                )
                ack = json.loads(await asyncio.wait_for(client.recv(), timeout=5))
                assert ack[ep.TYPE_KEY] == ep.TYPE_HELLO_ACK
                # Peer held open → /metrics reflects it + the hello message counter.
                _, _, body = await asyncio.to_thread(_http_get, port, "/metrics")
                return body

    body = asyncio.run(_run())
    assert "ac_sidecar_connected_peers 1" in body
    assert 'ac_sidecar_messages_total{type="hello"} 1' in body


def test_metrics_builder_screen_recency(monkeypatch: pytest.MonkeyPatch) -> None:
    m = obs.SidecarMetrics()
    monkeypatch.setattr(obs, "METRICS", m)
    assert "ac_sidecar_screen_connected 0" in obs.build_metrics_text(0)
    m.note_screen_seen()
    assert "ac_sidecar_screen_connected 1" in obs.build_metrics_text(0)
    assert "ac_sidecar_screen_peers 2" in obs.build_metrics_text(2, screen_peers=2)
    assert "ac_sidecar_screen_connected 1" in obs.build_metrics_text(2, screen_peers=2)


def test_metrics_and_health_report_current_screen_peers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(obs, "METRICS", obs.SidecarMetrics())

    async def _run() -> tuple[dict[str, object], str]:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}") as client:
                await client.send(
                    json.dumps(
                        {
                            ep.ENVELOPE_KEY: 1,
                            ep.TYPE_KEY: ep.TYPE_HELLO,
                            "client": "ac-copilot-screen-01",
                            ep.CLIENT_CLASS_KEY: ep.CLIENT_CLASS_SCREEN,
                        }
                    )
                )
                ack = json.loads(await asyncio.wait_for(client.recv(), timeout=5))
                assert ack[ep.TYPE_KEY] == ep.TYPE_HELLO_ACK
                _, _, health_body = await asyncio.to_thread(_http_get, port, "/health")
                _, _, metrics_body = await asyncio.to_thread(_http_get, port, "/metrics")
                return json.loads(health_body), metrics_body

    health, metrics = asyncio.run(_run())
    assert health["connected_peers"] == 1
    assert health["screen_peers"] == 1
    assert "ac_sidecar_connected_peers 1" in metrics
    assert "ac_sidecar_screen_peers 1" in metrics
    assert "ac_sidecar_screen_connected 1" in metrics


def test_metrics_builder_message_label_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    m = obs.SidecarMetrics()
    monkeypatch.setattr(obs, "METRICS", m)
    m.record_message("event", "lap_complete")
    m.record_message("type", "hello")
    m.record_ollama_followup_error()
    text = obs.build_metrics_text(3)
    assert 'ac_sidecar_messages_total{event="lap_complete"} 1' in text
    assert 'ac_sidecar_messages_total{type="hello"} 1' in text
    assert "ac_sidecar_ollama_followup_errors_total 1" in text
    assert "ac_sidecar_connected_peers 3" in text
