"""Native CSP Setup Exchange broker through real authenticated websocket dispatch."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

pytest.importorskip("websockets")
from websockets.asyncio.client import connect  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402

from tools.ai_sidecar import external_protocol as ep  # noqa: E402
from tools.ai_sidecar import server as srv  # noqa: E402
from tools.ai_sidecar.csp_setup_exchange import (  # noqa: E402
    SetupExchangeBroker,
    fit_screen_response,
    install_response,
    search_response,
)
from tools.ai_sidecar.se_proxy import SetupExchangeError  # noqa: E402

CAR = "ks_porsche_911_gt3_r_2016"
TRACK = "magione"
SEARCH = {"v": 1, "type": "se.search", "car_id": CAR, "track_id": TRACK}
DOWNLOAD = {"v": 1, "type": "se.download", "setup_id": 42, "car_id": CAR, "track_id": TRACK}


def test_screen_requests_round_trip_through_production_lua_and_safe_installer():
    # Run the two production languages together. Only CSP's asynchronous signing/HTTP
    # APIs are adapters; request routing, Lua dispatch/provider and installation are real.
    from test_setup_exchange_lua import respond, runtime

    rt, to_lua, _ = runtime()
    rt.globals()._car, rt.globals()._track = CAR, TRACK
    rt.execute("""
      wb = require('ws_bridge'); wb.configure('ws://127.0.0.1:8765'); wb.tick(0)
      wb.registerAsyncRequestHandler('se.csp.request', 'se.csp.result',
        require('setup_exchange').handle)
    """)

    async def relay(lua):
        request = await recv(lua)
        rt.globals()._recv(json.dumps(request))
        rt.execute("wb.pollInbound(8)")
        return request

    async def run():
        async with running() as url, peer(url, lua=True) as lua, peer(url) as screen:
            await send(screen, SEARCH)
            await relay(lua)
            rt.globals()._keyCallback(None, "private-machine-key")
            respond(rt, to_lua, 1, {"key": "private-challenge"})
            rt.globals()._signCallback("private-signature", "private-header")
            assert json.loads(rt.globals()._http[2].body)["carID"] == CAR
            respond(rt, to_lua, 2, {"sessionID": "private-session"})
            respond(
                rt,
                to_lua,
                3,
                [
                    {
                        "setupID": 42,
                        "name": "Community race",
                        "userName": "Fixture driver",
                        "carID": CAR,
                        "trackID": TRACK,
                        "statDownloads": 125,
                    }
                ],
                headers={"x-total-count": "9"},
            )
            await lua.send(rt.globals()._sent[1])
            search = await recv(screen)
            assert search["ok"] is True and search["total"] == 9
            row = search["setups"][0]
            assert row["author"] == "Fixture driver" and row["downloads"] == 125

            await send(screen, {**DOWNLOAD, "name": row["name"]})
            await relay(lua)
            assert len(rt.globals()._http) == 4  # signed session reused for download
            respond(
                rt,
                to_lua,
                4,
                {
                    "setupID": 42,
                    "carID": CAR,
                    "trackID": TRACK,
                    "data": "[CAR]\nMODEL=" + CAR + "\n[ABS]\nVALUE=2\n",
                },
            )
            await lua.send(rt.globals()._sent[2])
            ack = await recv(screen)
            assert ack["ok"] is True and ack["type"] == "se.download.ack"
            installed = Path(ack["path"])
            assert installed.is_relative_to(srv._setup_exchange_user_setups_root)
            assert installed.parent == srv._setup_exchange_user_setups_root / CAR / TRACK
            assert installed.name == ack["name"]
            assert "VALUE=2" in await asyncio.to_thread(installed.read_text)
            assert "private" not in json.dumps([search, ack])

    asyncio.run(run())


@pytest.fixture(autouse=True)
def isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for key in list(os.environ):
        if key.upper().startswith("AC_COPILOT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(srv, "_setup_exchange_endpoint", None)
    monkeypatch.setattr(
        srv, "_setup_exchange_user_setups_root", tmp_path / "Assetto Corsa" / "setups"
    )
    srv._reset_external_state()
    yield
    srv._reset_external_state()


@asynccontextmanager
async def running():
    async with serve(
        lambda ws: srv._handler(ws, reply_coaching=True),
        "127.0.0.1",
        0,
        process_request=srv.make_process_request("test-token"),
    ) as server:
        yield f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/"


@asynccontextmanager
async def peer(url, *, lua=False, claim_lua=False):
    headers = {ep.AUTH_HEADER: "test-token"}
    if lua:
        headers[ep.CLIENT_HEADER] = ep.LUA_CLIENT_ID
    async with connect(url, additional_headers=headers) as ws:
        await send(
            ws,
            {
                "v": 1,
                "type": "hello",
                "client": "test",
                "client_class": "lua" if lua or claim_lua else "screen",
            },
        )
        assert (await recv(ws))["type"] == "hello_ack"
        yield ws


async def send(ws, frame):
    await ws.send(json.dumps(frame))


async def recv(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 2))


def result(request, response, **extra):
    return {
        "v": 1,
        "type": ep.TYPE_SETUP_EXCHANGE_CSP_RESULT,
        "request_id": request["request_id"],
        "operation": request["operation"],
        "ok": True,
        "response": response,
        **extra,
    }


def test_native_search_keeps_author_and_private_result():
    async def run():
        async with (
            running() as url,
            peer(url, lua=True) as lua,
            peer(url) as screen,
            peer(url) as other,
        ):
            await send(screen, SEARCH)
            request = await recv(lua)
            assert request["type"] == ep.TYPE_SETUP_EXCHANGE_CSP_REQUEST
            assert request["operation"] == "search" and request["car_id"] == CAR
            await send(
                lua,
                result(
                    request,
                    [
                        {
                            "setupID": 42,
                            "name": "Race",
                            "userName": "Alice",
                            "carID": CAR,
                            "trackID": TRACK,
                            "statDownloads": 99,
                        }
                    ],
                    total_count=10,
                ),
            )
            response = await recv(screen)
            assert response["ok"] is True and response["total"] == 10
            assert response["setups"][0]["author"] == "Alice"
            assert response["setups"][0]["downloads"] == 99
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(other.recv(), 0.05)

    asyncio.run(run())


def test_download_uses_safe_installer_and_preserves_existing_file():
    async def run():
        async with running() as url, peer(url, lua=True) as lua, peer(url) as screen:
            paths = []
            for _ in range(2):
                await send(screen, DOWNLOAD)
                request = await recv(lua)
                await send(
                    lua,
                    result(
                        request,
                        {
                            "name": "Race",
                            "data": "[HEADER]\nVERSION=1",
                            "carID": CAR,
                            "trackID": TRACK,
                        },
                    ),
                )
                ack = await recv(screen)
                assert ack["type"] == "se.download.ack" and ack["ok"] is True
                assert ack["name"] == Path(ack["path"]).name
                paths.append(Path(ack["path"]))
            assert paths[0] != paths[1]
            assert [p.read_text() for p in paths] == ["[HEADER]\nVERSION=1\n"] * 2

    asyncio.run(run())


def test_no_authenticated_lua_does_not_ask_for_proxy():
    async def run():
        async with running() as url, peer(url, claim_lua=True) as fake, peer(url) as screen:
            await send(screen, SEARCH)
            response = await recv(screen)
            assert response["ok"] is False
            assert "practice" in response["error"] and "proxy" not in response["error"]
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(fake.recv(), 0.05)

    asyncio.run(run())


def test_pending_request_does_not_block_hello_or_allow_spoofed_results():
    async def run():
        async with (
            running() as url,
            peer(url, lua=True) as lua,
            peer(url) as screen,
            peer(url) as fake,
        ):
            await send(screen, SEARCH)
            request = await recv(lua)
            await send(
                screen, {"v": 1, "type": "hello", "client": "heartbeat", "client_class": "screen"}
            )
            assert (await recv(screen))["type"] == "hello_ack"
            await send(fake, result(request, []))
            assert (await recv(fake))["type"] == "error"
            await send(lua, result(request, {}, operation="download"))
            assert (await recv(lua))["type"] == "error"
            await send(lua, result({**request, "request_id": "0" * 32}, []))
            assert (await recv(lua))["type"] == "error"
            await send(lua, result(request, []))
            assert (await recv(screen))["ok"] is True

    asyncio.run(run())


def test_timeout_and_late_result(monkeypatch):
    monkeypatch.setattr(srv._setup_exchange_broker, "timeout_s", 0.05)

    async def run():
        async with running() as url, peer(url, lua=True) as lua, peer(url) as screen:
            await send(screen, SEARCH)
            request = await recv(lua)
            response = await recv(screen)
            assert response["ok"] is False and "timed out" in response["error"]
            await send(lua, result(request, []))
            assert (await recv(lua))["type"] == "error"
            assert not srv._setup_exchange_broker.pending

    asyncio.run(run())


def test_requester_disconnect_cancels_download_without_installing():
    root = srv._setup_exchange_user_setups_root

    async def run():
        async with running() as url, peer(url, lua=True) as lua:
            async with peer(url) as screen:
                await send(screen, DOWNLOAD)
                request = await recv(lua)
            # Wait for server teardown by a fresh request/ack on the same loop.
            for _ in range(30):
                if not srv._setup_exchange_broker.pending:
                    break
                await asyncio.sleep(0.01)
            await send(lua, result(request, {"name": "Race", "data": "[HEADER]\nVERSION=1"}))
            assert (await recv(lua))["type"] == "error"
            assert not root.exists()

    asyncio.run(run())


def test_producer_disconnect_returns_error():
    async def run():
        async with running() as url, peer(url) as screen:
            async with peer(url, lua=True) as lua:
                await send(screen, SEARCH)
                await recv(lua)
            response = await recv(screen)
            assert response["ok"] is False and "disconnected" in response["error"]

    asyncio.run(run())


def test_ambiguous_trainer_and_duplicate_pending_fail_closed():
    async def run():
        async with running() as url, peer(url, lua=True) as lua, peer(url) as screen:
            async with peer(url, lua=True):
                await send(screen, SEARCH)
                assert "Multiple" in (await recv(screen))["error"]
            await send(screen, SEARCH)
            request = await recv(lua)
            await send(screen, SEARCH)
            assert "pending" in (await recv(screen))["error"]
            await send(lua, result(request, []))
            assert (await recv(screen))["ok"] is True

    asyncio.run(run())


@pytest.mark.parametrize(
    "frame",
    [
        {"v": 1, "type": "se.download.ack", "ok": True, "path": "forged.ini", "name": "forged.ini"},
        {"v": 1, "type": "se.search.result", "ok": True, "setups": []},
    ],
)
def test_external_cannot_forge_sidecar_outputs(frame):
    async def run():
        async with running() as url, peer(url) as fake, peer(url) as screen:
            await send(fake, frame)
            assert (await recv(fake))["type"] == "error"
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(screen.recv(), 0.05)

    asyncio.run(run())


@pytest.mark.parametrize(
    "raw",
    [
        {"data": "x", "carID": "another_car"},
        {"data": "x", "trackID": "another_track"},
        {"data": "x", "setupID": 99},
        {"data": "x" * (512 * 1024 + 1)},
        {"data": 12},
    ],
)
def test_download_rejects_wrong_identity_and_invalid_data(raw):
    with pytest.raises(SetupExchangeError):
        install_response(DOWNLOAD, {"response": raw}, srv._setup_exchange_user_setups_root)
    assert not srv._setup_exchange_user_setups_root.exists()


def test_official_rows_are_bounded_to_serial_screen_envelope():
    rows = [
        {
            "setupID": i + 1,
            "name": "名" * 400,
            "userName": "A\n" * 400,
            "carID": CAR,
            "trackID": TRACK,
        }
        for i in range(100)
    ]
    frame = fit_screen_response(
        {
            "v": 1,
            "type": "se.search.result",
            **search_response({"limit": 40}, {"response": rows, "total_count": 100}),
        }
    )
    assert 0 < frame["count"] < 40
    assert frame["total"] == 100
    assert len(json.dumps(frame, separators=(",", ":")).encode()) <= 7600
    assert "\n" not in frame["setups"][0]["author"]


@pytest.mark.parametrize(
    "endpoint", [None, "", "  ", "http://se.acstuff.club/ ", "https://se.acstuff.club/"]
)
def test_native_default_selection(endpoint, monkeypatch):
    monkeypatch.setattr(srv, "_setup_exchange_endpoint", endpoint)
    assert srv._uses_native_setup_exchange()


def test_broker_capacity_reset_and_producer_identity():
    async def run():
        broker = SetupExchangeBroker(max_pending=1)
        requester, producer = object(), object()
        key = broker.begin(requester, producer, "search")
        with pytest.raises(SetupExchangeError):
            broker.begin(object(), producer, "search")
        assert not broker.accept(object(), {"request_id": key, "operation": "search"})
        pending = broker.pending[key].future
        broker.reset()
        assert not broker.pending and pending.cancelled()

    asyncio.run(run())


def test_csp_failure_does_not_forward_service_error_or_secrets():
    async def run():
        async with running() as url, peer(url, lua=True) as lua, peer(url) as screen:
            await send(screen, SEARCH)
            request = await recv(lua)
            await send(
                lua,
                {
                    "v": 1,
                    "type": ep.TYPE_SETUP_EXCHANGE_CSP_RESULT,
                    "request_id": request["request_id"],
                    "operation": "search",
                    "ok": False,
                    "error": "service body contains a session-secret",
                },
            )
            ack = await recv(screen)
            assert ack["ok"] is False and "secret" not in ack["error"]

    asyncio.run(run())
