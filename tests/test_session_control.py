"""Guarded harness pit return: real WS authority and actual Lua execution boundary."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from tools.ac_harness.rig_lock import RigSessionLock, RigSessionOwner
from tools.ai_sidecar import external_protocol as ep
from tools.ai_sidecar import server as srv

SESSION = "native_session_956"
STAMP = "2026-11-13T17:00:00Z"


def command(**changes):
    return {
        "v": 1,
        "type": ep.TYPE_SESSION_RETURN_TO_PITS,
        "request_id": "pilot_return_1",
        "session_id": SESSION,
        "rig_owner_pid": os.getpid(),
        "rig_owner_started_at": STAMP,
        **changes,
    }


def ack(request, **changes):
    return {
        "v": 1,
        "type": ep.TYPE_SESSION_RETURN_TO_PITS_ACK,
        "request_id": request["request_id"],
        "session_id": SESSION,
        "operation": "return_to_pits",
        "ok": True,
        "native_result": "accepted",
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"rig_owner_pid": True},
        {"rig_owner_pid": 0},
        {"session_id": ""},
        {"request_id": "x" * 65},
        {"rig_owner_started_at": ""},
        {"preserveDamage": False},
    ],
)
def test_protocol_rejects_invalid_control(changes):
    assert ep.validate_inbound(command(**changes)) is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"ok": 1},
        {"native_result": "arrived"},
        {"ok": False},
        {"operation": "start"},
        {"session_id": ""},
        {"error": "x" * 161},
    ],
)
def test_protocol_rejects_invalid_ack(changes):
    assert ep.validate_inbound(ack(command(), **changes)) is not None


@pytest.fixture
def native():
    lupa = pytest.importorskip("lupa")
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    modules = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"
    rt.execute(f'package.path = "{modules.as_posix()}/?.lua;" .. package.path')
    rt.execute("""
      now, calls, online, result, raises = 1000, 0, false, true, false
      os.time = function() return now end
      ac = {
        getSim = function() return {isOnlineRace=online} end,
        tryToTeleportToPits = function(preserveDamage)
          assert(preserveDamage == true)
          calls = calls + 1
          if raises then error('native exception') end
          return result
        end
      }
      rpc = require('session_control').new()
    """)

    def run(**changes):
        frame = command(**{"command_id": "original_command", "deadline_epoch": 1005, **changes})
        return dict(rt.globals().rpc.handle(rt.table_from(frame), SESSION).items())

    return rt, run


@pytest.mark.parametrize(
    "setup,changes,expected",
    [
        ("", {"session_id": "wrong_session"}, "refused"),
        ("online=true", {}, "refused"),
        ("online=nil", {}, "refused"),
        ("ac.getSim=function() error('unknown') end", {}, "refused"),
        ("ac.tryToTeleportToPits=nil", {}, "unavailable"),
        ("", {"deadline_epoch": 999}, "refused"),
        ("", {"deadline_epoch": 1007}, "refused"),
        ("os.time=nil", {}, "refused"),
    ],
)
def test_native_refuses_without_invocation(native, setup, changes, expected):
    rt, run = native
    rt.execute(setup)
    assert run(**changes)["native_result"] == expected
    assert rt.globals().calls == 0


@pytest.mark.parametrize(
    "setup,expected",
    [
        ("", "accepted"),
        ("result=false", "refused"),
        ("raises=true", "exception"),
    ],
)
def test_native_dedup_includes_refusal_and_uncertain_outcome(native, setup, expected):
    rt, run = native
    rt.execute(setup)
    first = run()
    duplicate = run(request_id="new_broker_envelope")
    assert first["native_result"] == duplicate["native_result"] == expected
    assert duplicate["duplicate"] and duplicate["request_id"] == "new_broker_envelope"
    assert rt.globals().calls == 1
    assert run(rig_owner_started_at="different_owner")["ok"] is False
    assert rt.globals().calls == 1


def test_native_cache_does_not_evict_old_reservations(native):
    rt, run = native
    for i in range(128):
        assert run(command_id=f"command_{i}")["ok"]
    assert run(command_id="overflow")["ok"] is False
    assert run(command_id="command_0")["duplicate"]
    assert rt.globals().calls == 128


@pytest.fixture
def lease(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.upper().startswith("AC_COPILOT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    srv._reset_external_state()
    from tools.ac_harness.rig_lock import default_rig_session_lock_path

    lock = RigSessionLock(
        default_rig_session_lock_path(),
        owner=RigSessionOwner(pid=os.getpid(), cwd=str(tmp_path), started_at=STAMP),
    )
    lock.acquire()
    yield lock
    lock.release()
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
async def peer(url, identity="screen"):
    async with connect(
        url, additional_headers={ep.AUTH_HEADER: "test-token", ep.CLIENT_HEADER: identity}
    ) as ws:
        await ws.send(
            json.dumps(
                {
                    "v": 1,
                    "type": "hello",
                    "client": identity,
                    "client_class": "lua" if identity == ep.LUA_CLIENT_ID else "screen",
                }
            )
        )
        assert (await recv(ws))["type"] == "hello_ack"
        yield ws


async def recv(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 2))


async def no_frame(ws):
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(ws.recv(), 0.04)


def test_authenticated_pinned_private_return(lease):
    async def run():
        async with (
            running() as url,
            peer(url, ep.LUA_CLIENT_ID) as lua,
            peer(url, ep.SESSION_START_CLIENT_ID) as harness,
            peer(url) as screen,
        ):
            await harness.send(json.dumps(command()))
            forwarded = await recv(lua)
            assert forwarded["command_id"] == command()["request_id"]
            assert forwarded["request_id"] != command()["request_id"]
            assert forwarded["deadline_epoch"] > 0
            await screen.send(json.dumps(ack(forwarded)))
            assert (await recv(screen))["type"] == "error"
            await lua.send(json.dumps(ack(forwarded)))
            assert await recv(harness) == ack(command())
            await no_frame(screen)
            assert not srv._pit_return_broker.pending

    asyncio.run(run())


@pytest.mark.parametrize(
    "reason", ["untrusted", "missing_lease", "owner_changed", "bench_active", "two_lua"]
)
def test_control_denied_before_forward(lease, monkeypatch, reason):
    async def run():
        async with (
            running() as url,
            peer(url, ep.LUA_CLIENT_ID) as lua,
            peer(url, ep.SESSION_START_CLIENT_ID if reason != "untrusted" else "screen") as harness,
        ):
            if reason == "missing_lease":
                lease.release()
            if reason == "bench_active":
                monkeypatch.setattr(srv, "_bench_status", lambda: {"active": True})
            frame = (
                command(rig_owner_started_at="new_stamp")
                if reason == "owner_changed"
                else command()
            )
            if reason == "two_lua":
                async with peer(url, ep.LUA_CLIENT_ID):
                    await harness.send(json.dumps(frame))
                    assert (await recv(harness))["type"] == "error"
            else:
                await harness.send(json.dumps(frame))
                assert (await recv(harness))["type"] == "error"
            await no_frame(lua)
            assert not srv._pit_return_broker.pending

    asyncio.run(run())


def test_queued_control_rechecks_actual_lease_after_transaction_lock(lease):
    async def run():
        async with (
            running() as url,
            peer(url, ep.LUA_CLIENT_ID) as lua,
            peer(url, ep.SESSION_START_CLIENT_ID) as harness,
        ):
            lock = srv._prescription_lock()
            await lock.acquire()
            try:
                await harness.send(json.dumps(command()))
                await no_frame(lua)
                lease.release()
            finally:
                lock.release()
            assert (await recv(harness))["type"] == "error"
            await no_frame(lua)

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "disconnect", "session_changed", "lease_released"])
def test_unknown_outcome_never_replays_or_publishes_acceptance(lease, monkeypatch, failure):
    monkeypatch.setattr(srv._pit_return_broker, "timeout_s", 0.06)

    async def run():
        async with (
            running() as url,
            peer(url, ep.LUA_CLIENT_ID) as lua,
            peer(url, ep.SESSION_START_CLIENT_ID) as harness,
        ):
            await harness.send(json.dumps(command()))
            forwarded = await recv(lua)
            if failure == "disconnect":
                await lua.close()
            elif failure == "session_changed":
                await lua.send(json.dumps(ack(forwarded, session_id="replacement_session")))
            elif failure == "lease_released":
                lease.release()
                await lua.send(json.dumps(ack(forwarded)))
            response = await recv(harness)
            assert response["type"] == "error" and "no retry" in response["message"]
            assert not srv._pit_return_broker.pending
            if failure != "disconnect":
                await no_frame(lua)

    asyncio.run(run())
