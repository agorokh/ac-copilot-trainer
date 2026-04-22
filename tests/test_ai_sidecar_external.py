"""External-client extension tests for the AI sidecar (issue #81).

Covers:
- ``make_token_check`` returns ``None`` when no token is configured.
- Argparse refuses ``--external-bind`` without ``--token``.
- ``external_protocol.validate_inbound`` enforces the v1 envelope contract.
- WS upgrade rejects on missing token, accepts with matching token.
- Hub fan-out: ``config.set`` from peer A reaches peer B and the simulated
  ack from B reaches A.
- Action with unknown name surfaces as an ``error`` frame from the sidecar.

Tests use plain ``asyncio.run`` — repo has no pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

websockets = pytest.importorskip("websockets")
from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.asyncio.server import serve as ws_serve  # noqa: E402

from tools.ai_sidecar import external_protocol as ep  # noqa: E402
from tools.ai_sidecar.server import (  # noqa: E402
    _handler,
    _is_loopback,
    make_token_check,
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
    process_request = make_token_check(token)
    async with ws_serve(
        lambda ws: _handler(ws, reply_coaching=True),
        "127.0.0.1",
        port,
        process_request=process_request,
    ):
        yield port


def test_make_token_check_returns_none_without_token() -> None:
    assert make_token_check(None) is None
    assert make_token_check("") is None


def test_is_loopback_classification() -> None:
    assert _is_loopback("127.0.0.1")
    assert _is_loopback("localhost")
    assert _is_loopback("::1")
    assert not _is_loopback("0.0.0.0")
    assert not _is_loopback("192.168.1.10")


def test_validate_inbound_accepts_known_types() -> None:
    assert ep.validate_inbound({"v": 1, "type": "hello", "client": "screen-01"}) is None
    assert ep.validate_inbound({"v": 1, "type": "config.get", "key": "hudEnabled"}) is None
    assert (
        ep.validate_inbound({"v": 1, "type": "config.set", "key": "hudEnabled", "value": True})
        is None
    )
    assert ep.validate_inbound({"v": 1, "type": "action", "name": "toggleFocusPractice"}) is None
    assert (
        ep.validate_inbound({"v": 1, "type": "state.subscribe", "topics": ["lap"]}) is None
    )


def test_validate_inbound_rejects_invalid() -> None:
    assert "unsupported envelope version" in (ep.validate_inbound({"type": "hello"}) or "")
    assert "non-empty 'client'" in (ep.validate_inbound({"v": 1, "type": "hello"}) or "")
    assert "non-empty 'key'" in (ep.validate_inbound({"v": 1, "type": "config.get"}) or "")
    assert "value" in (ep.validate_inbound({"v": 1, "type": "config.set", "key": "k"}) or "")
    assert "unknown action" in (
        ep.validate_inbound({"v": 1, "type": "action", "name": "rmRfRoot"}) or ""
    )
    assert "unknown topic" in (
        ep.validate_inbound({"v": 1, "type": "state.subscribe", "topics": ["pit_window"]}) or ""
    )
    assert "unknown type" in (ep.validate_inbound({"v": 1, "type": "explode"}) or "")


def test_external_bind_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argparse refuses --external-bind without --token (SystemExit)."""
    from tools.ai_sidecar import server as srv

    monkeypatch.setattr(
        "sys.argv",
        ["ai_sidecar", "--external-bind", "0.0.0.0", "--port", "0"],
    )
    with pytest.raises(SystemExit):
        srv.main()


def test_non_loopback_host_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.ai_sidecar import server as srv

    monkeypatch.setattr(
        "sys.argv",
        ["ai_sidecar", "--host", "0.0.0.0", "--port", "0"],
    )
    with pytest.raises(SystemExit):
        srv.main()


def test_upgrade_rejected_without_token() -> None:
    token_check = make_token_check("s3cret")
    assert token_check is not None

    class _Conn:
        remote_address = ("192.168.1.50", 12345)

    class _Req:
        headers = {}

    response = token_check(_Conn(), _Req())
    assert response is not None
    assert response.status_code == 401


def test_upgrade_accepted_with_token() -> None:
    async def _run() -> dict:
        async with _running_sidecar(token="s3cret") as port:
            async with ws_connect(
                f"ws://127.0.0.1:{port}/",
                additional_headers={
                    ep.AUTH_HEADER: "s3cret",
                    ep.CLIENT_HEADER: "test-client",
                },
            ) as ws:
                await ws.send(
                    json.dumps({"v": 1, "type": "hello", "client": "test"})
                )
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(raw)

    ack = asyncio.run(_run())
    assert ack["type"] == ep.TYPE_HELLO_ACK
    assert "config.set" in ack["capabilities"]


def test_upgrade_accepted_without_token_on_loopback() -> None:
    async def _run() -> dict:
        async with _running_sidecar(token="s3cret") as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "test"}))
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(raw)

    ack = asyncio.run(_run())
    assert ack["type"] == ep.TYPE_HELLO_ACK


def test_action_with_unknown_name_rejected() -> None:
    async def _run() -> dict:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}/") as ws:
                await ws.send(json.dumps({"v": 1, "type": "hello", "client": "x"}))
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # hello_ack
                await ws.send(
                    json.dumps({"v": 1, "type": "action", "name": "nukeFleet"})
                )
                err_raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                return json.loads(err_raw)

    err = asyncio.run(_run())
    assert err["type"] == ep.TYPE_ERROR
    assert "unknown action" in err["message"]


def test_config_set_round_trip_via_hub() -> None:
    """Two peers: A sends config.set, B receives it; B's ack reaches A."""

    async def _run() -> tuple[dict, dict]:
        async with _running_sidecar() as port:
            async with (
                ws_connect(f"ws://127.0.0.1:{port}/") as a,
                ws_connect(f"ws://127.0.0.1:{port}/") as b,
            ):
                for s, name in [(a, "client-a"), (b, "client-b")]:
                    await s.send(
                        json.dumps({"v": 1, "type": "hello", "client": name})
                    )
                    await asyncio.wait_for(s.recv(), timeout=2.0)  # hello_ack

                await a.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "config.set",
                            "key": "hudEnabled",
                            "value": False,
                        }
                    )
                )
                forwarded = json.loads(await asyncio.wait_for(b.recv(), timeout=2.0))

                await b.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "config.ack",
                            "key": "hudEnabled",
                            "applied": True,
                        }
                    )
                )
                ack_back = json.loads(await asyncio.wait_for(a.recv(), timeout=2.0))
                return forwarded, ack_back

    forwarded, ack_back = asyncio.run(_run())
    assert forwarded["type"] == "config.set"
    assert forwarded["key"] == "hudEnabled"
    assert forwarded["value"] is False
    assert ack_back["type"] == "config.ack"
    assert ack_back["applied"] is True
