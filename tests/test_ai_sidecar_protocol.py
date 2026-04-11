"""Protocol helpers and WebSocket round-trip for AI sidecar (issue #45)."""

from __future__ import annotations

import asyncio
import json

import pytest

from tools.ai_sidecar.protocol import (
    EVENT_ANALYSIS_ERROR,
    EVENT_COACHING_RESPONSE,
    EVENT_CORNER_ADVICE,
    PROTOCOL_VERSION,
    prepare_outbound_message,
)


def test_prepare_rejects_bad_protocol() -> None:
    out = prepare_outbound_message(
        {"protocol": 99, "event": "lap_complete", "lap": 1},
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR
    assert out["protocol"] == PROTOCOL_VERSION


def test_prepare_coaching_response_fixture() -> None:
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "lap_complete",
            "lap": 4,
            "lapTimeMs": 91000,
            "coachingHints": ["a"],
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_COACHING_RESPONSE
    assert out["lap"] == 4
    assert isinstance(out["hints"], list)
    assert out["hints"][0]["text"]


def test_prepare_no_reply_mode() -> None:
    assert (
        prepare_outbound_message(
            {"protocol": PROTOCOL_VERSION, "event": "lap_complete", "lap": 1},
            reply_coaching=False,
        )
        is None
    )


def test_corner_query_respects_no_reply_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.ai_sidecar.protocol as proto

    monkeypatch.setattr(proto, "compose_corner_hint", lambda **_k: "SHOULD NOT RUN")
    assert (
        prepare_outbound_message(
            {
                "protocol": PROTOCOL_VERSION,
                "event": "corner_query",
                "corner": "T1",
                "cur": 80,
                "ref": 70,
                "dist": 12,
            },
            reply_coaching=False,
        )
        is None
    )


def test_corner_query_requires_cur_ref_dist_keys() -> None:
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "corner_query",
            "corner": "T1",
            "cur": 80,
            "ref": 70,
            # missing dist
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR


def test_corner_query_rejects_bool_speed() -> None:
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "corner_query",
            "corner": "T1",
            "cur": True,
            "ref": 100,
            "dist": 10,
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_ANALYSIS_ERROR


def test_corner_query_silent_when_no_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.ai_sidecar.protocol as proto

    monkeypatch.setattr(proto, "compose_corner_hint", lambda **_: None)
    assert (
        prepare_outbound_message(
            {
                "protocol": PROTOCOL_VERSION,
                "event": "corner_query",
                "corner": "T1",
                "cur": 80,
                "ref": 70,
                "dist": 12,
            },
            reply_coaching=True,
        )
        is None
    )


def test_corner_query_returns_advice_when_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.ai_sidecar.protocol as proto

    monkeypatch.setattr(proto, "compose_corner_hint", lambda **_: "BRAKE EARLIER")
    out = prepare_outbound_message(
        {
            "protocol": PROTOCOL_VERSION,
            "event": "corner_query",
            "corner": "T1",
            "cur": 80,
            "ref": 70,
            "dist": 12,
        },
        reply_coaching=True,
    )
    assert out is not None
    assert out["event"] == EVENT_CORNER_ADVICE
    assert out["text"] == "BRAKE EARLIER"


def test_sidecar_websocket_lap_complete_roundtrip() -> None:
    websockets = pytest.importorskip("websockets", minversion="12")
    from tools.ai_sidecar.server import _handler

    async def _go() -> None:
        async with websockets.serve(
            lambda w: _handler(w, reply_coaching=True),
            "127.0.0.1",
            0,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "protocol": PROTOCOL_VERSION,
                            "event": "lap_complete",
                            "lap": 7,
                            "lapTimeMs": 95000,
                            "coachingHints": [],
                        },
                        separators=(",", ":"),
                    )
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                out = json.loads(raw)
                assert out["protocol"] == PROTOCOL_VERSION
                assert out["event"] == EVENT_COACHING_RESPONSE
                assert out["lap"] == 7
                assert len(out["hints"]) >= 1

    asyncio.run(_go())


def test_sidecar_non_object_json_gets_analysis_error() -> None:
    websockets = pytest.importorskip("websockets", minversion="12")
    from tools.ai_sidecar.server import _handler

    async def _go() -> None:
        async with websockets.serve(
            lambda w: _handler(w, reply_coaching=True),
            "127.0.0.1",
            0,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri) as ws:
                await ws.send("[]")
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                out = json.loads(raw)
                assert out["event"] == EVENT_ANALYSIS_ERROR
                assert out["message"] == "root must be a JSON object"

    asyncio.run(_go())


def test_sidecar_invalid_json_gets_analysis_error() -> None:
    websockets = pytest.importorskip("websockets", minversion="12")
    from tools.ai_sidecar.server import _handler

    async def _go() -> None:
        async with websockets.serve(
            lambda w: _handler(w, reply_coaching=True),
            "127.0.0.1",
            0,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            uri = f"ws://127.0.0.1:{port}"
            async with websockets.connect(uri) as ws:
                await ws.send("{not json")
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                out = json.loads(raw)
                assert out["event"] == EVENT_ANALYSIS_ERROR

    asyncio.run(_go())
