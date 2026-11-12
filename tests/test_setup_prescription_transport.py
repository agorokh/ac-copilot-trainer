"""Real WS transport/journal tests. Positive cards here isolate routing, not inference."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from contextlib import asynccontextmanager

import pytest

pytest.importorskip("websockets")
from websockets.asyncio.client import connect  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402

from tools.ai_sidecar import external_protocol as ep  # noqa: E402
from tools.ai_sidecar import server as srv  # noqa: E402
from tools.ai_sidecar import setup_prescription as engine  # noqa: E402

IDENTITY = {
    "car_id": "car",
    "track_id": "track",
    "layout_id": "",
    "session_id": "session",
    "compound_index": 0,
    "setup_path": "C:/setup.ini",
}


def card():
    return {
        "prescription_id": "frozen-routing-card",
        "status": "proposed",
        "summary": "LF pressure high",
        "evidence": "Routing fixture, not domain acceptance",
        "changes": [{"section": "PRESSURE_LF", "from": 24, "to": 23, "delta_psi": -1}],
        "identity": IDENTITY,
        "created_at": time.time(),
        "ttl_s": 120,
    }


async def send(ws, data):
    await ws.send(json.dumps(data))


async def recv(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 2))


@asynccontextmanager
async def running(tmp_path, monkeypatch):
    srv._reset_external_state()
    monkeypatch.setenv("AC_COPILOT_PRESSURE_EXPERIMENT", "1")
    monkeypatch.setattr(
        srv,
        "_setup_experiment_store_path",
        tmp_path / "journal/setup_experiments/experiments.jsonl",
    )
    monkeypatch.setattr(srv, "_prescription_inputs", lambda *_: ([], {}))
    monkeypatch.setattr(srv, "_prescription_lap_dir", lambda *_: tmp_path / "journal/laps")
    monkeypatch.setattr(engine, "build_prescription", lambda *_a, **_k: copy.deepcopy(card()))
    async with serve(
        lambda ws: srv._handler(ws, reply_coaching=False),
        "127.0.0.1",
        0,
        process_request=srv.make_process_request(None),
    ) as listener:
        url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
        try:
            yield url
        finally:
            srv._reset_external_state()


@asynccontextmanager
async def peer(url, *, lua=False):
    headers = {ep.CLIENT_HEADER: ep.LUA_CLIENT_ID} if lua else None
    async with connect(url, additional_headers=headers) as ws:
        await send(
            ws,
            {
                "v": 1,
                "type": "hello",
                "client": "fixture",
                "client_class": "lua" if lua else "screen",
            },
        )
        assert (await recv(ws))["type"] == "hello_ack"
        yield ws


async def context(lua, *, pit=True, identity=None):
    request = await recv(lua)
    assert request["operation"] == "context"
    await send(
        lua,
        {
            "v": 1,
            "type": ep.TYPE_SETUP_PRESCRIPTION_RPC_RESULT,
            "request_id": request["request_id"],
            "operation": "context",
            "ok": True,
            "context_id": request["request_id"],
            "identity": identity or IDENTITY,
            "is_in_pit": pit,
            "reset_allowed": True,
            "spinners": [],
            "lap_dir": "unused routing fixture",
        },
    )


async def result(lua, *, operation, readback=None, ok=True):
    request = await recv(lua)
    assert request["operation"] == operation
    await send(
        lua,
        {
            "v": 1,
            "type": ep.TYPE_SETUP_PRESCRIPTION_RPC_RESULT,
            "request_id": request["request_id"],
            "operation": operation,
            "ok": ok,
            "error": "Pit box exited" if not ok else None,
            "readback": readback or {},
        },
    )
    return request


def test_accept_deduplicates_across_connections_and_verifies_only_full_readback(
    tmp_path, monkeypatch
):
    async def run():
        async with running(tmp_path, monkeypatch) as url, peer(url, lua=True) as lua:
            async with peer(url) as screen:
                await send(
                    screen, {"v": 1, "type": ep.TYPE_SETUP_PRESCRIPTION_GET, "request_id": "epoch1"}
                )
                await context(lua)
                proposed = await recv(screen)
                assert proposed["status"] == "proposed" and proposed["request_id"] == "epoch1"
                assert "identity" not in proposed and "created_at" not in proposed
                decide = {
                    "v": 1,
                    "type": ep.TYPE_SETUP_PRESCRIPTION_DECIDE,
                    "prescription_id": proposed["prescription_id"],
                    "decision": "accept",
                    "request_id": "epoch1",
                }
                await send(screen, decide)
                await context(lua)
                applied = await result(lua, operation="apply", readback={})
                assert applied["changes"][0]["to"] == 23
                assert (await recv(screen))["status"] == "accepted_unverified"
            # A different socket retries the same decision. It receives only a
            # readback query, never a second apply, even after the first disconnect.
            async with peer(url) as reconnected:
                await send(reconnected, decide)
                await context(lua)
                await result(lua, operation="readback", readback={"PRESSURE_LF": 23})
                assert (await recv(reconnected))["status"] == "verified_applied"
                rows = engine.PrescriptionJournal(srv._setup_experiment_store_path).get(
                    proposed["prescription_id"]
                )
                assert rows["decision"] == "accept"

    asyncio.run(run())


def test_pit_exit_preserves_unverified_and_retries_do_not_apply(tmp_path, monkeypatch):
    async def run():
        async with (
            running(tmp_path, monkeypatch) as url,
            peer(url, lua=True) as lua,
            peer(url) as screen,
        ):
            await send(screen, {"v": 1, "type": ep.TYPE_SETUP_PRESCRIPTION_GET})
            await context(lua)
            proposed = await recv(screen)
            decision = {
                "v": 1,
                "type": ep.TYPE_SETUP_PRESCRIPTION_DECIDE,
                "prescription_id": proposed["prescription_id"],
                "decision": "accept",
            }
            await send(screen, decision)
            await context(lua, pit=False)
            await result(lua, operation="apply", ok=False)
            failed = await recv(screen)
            assert failed["status"] == "accepted_unverified"
            assert failed["reason"] == "Pit box exited"
            await send(screen, decision)
            await context(lua, pit=False)
            await result(lua, operation="readback", readback={"PRESSURE_LF": 24})
            assert (await recv(screen))["status"] == "accepted_unverified"

    asyncio.run(run())


def test_reject_without_trainer_is_durable_and_has_no_rpc(tmp_path, monkeypatch):
    async def run():
        async with running(tmp_path, monkeypatch) as url, peer(url) as screen:
            engine.PrescriptionJournal(srv._setup_experiment_store_path).remember(card())
            for _ in range(2):
                await send(
                    screen,
                    {
                        "v": 1,
                        "type": ep.TYPE_SETUP_PRESCRIPTION_DECIDE,
                        "prescription_id": card()["prescription_id"],
                        "decision": "reject",
                        "request_id": "epoch1",
                    },
                )
                response = await recv(screen)
                assert response["status"] == "rejected"
                assert response["request_id"] == "epoch1"
            assert not srv._prescription_broker.pending

    asyncio.run(run())


def test_rpc_result_from_untrusted_connection_cannot_satisfy_pending(tmp_path, monkeypatch):
    async def run():
        async with (
            running(tmp_path, monkeypatch) as url,
            peer(url, lua=True) as lua,
            peer(url) as screen,
        ):
            await send(screen, {"v": 1, "type": ep.TYPE_SETUP_PRESCRIPTION_GET})
            request = await recv(lua)
            forged = {
                "v": 1,
                "type": ep.TYPE_SETUP_PRESCRIPTION_RPC_RESULT,
                "request_id": request["request_id"],
                "operation": "context",
                "ok": True,
            }
            await send(screen, forged)
            assert (await recv(screen))["type"] == "error"
            assert request["request_id"] in srv._prescription_broker.pending
            await send(lua, {**forged, "ok": False, "error": "Fixture ends"})
            assert (await recv(screen))["status"] == "abstained"

    asyncio.run(run())


def test_protocol_rejects_client_evidence_and_arbitrary_apply_values():
    assert ep.validate_inbound({"v": 1, "type": ep.TYPE_SETUP_PRESCRIPTION_GET}) is None
    for extra in ({"archives": []}, {"changes": []}, {"identity": IDENTITY}, {"path": "C:/x"}):
        assert ep.validate_inbound({"v": 1, "type": ep.TYPE_SETUP_PRESCRIPTION_GET, **extra})
    for t in (ep.TYPE_SETUP_PRESCRIPTION_RPC, ep.TYPE_SETUP_PRESCRIPTION_CARD):
        assert ep.validate_inbound({"v": 1, "type": t})


def test_rpc_result_is_pinned_even_against_another_authenticated_lua(tmp_path, monkeypatch):
    async def run():
        async with (
            running(tmp_path, monkeypatch) as url,
            peer(url, lua=True) as lua,
            peer(url) as screen,
        ):
            await send(screen, {"v": 1, "type": ep.TYPE_SETUP_PRESCRIPTION_GET})
            request = await recv(lua)
            async with peer(url, lua=True) as other_lua:
                forged = {
                    "v": 1,
                    "type": ep.TYPE_SETUP_PRESCRIPTION_RPC_RESULT,
                    "request_id": request["request_id"],
                    "operation": "context",
                    "ok": True,
                }
                await send(other_lua, forged)
                assert (await recv(other_lua))["type"] == "error"
                assert request["request_id"] in srv._prescription_broker.pending
                await send(lua, {**forged, "ok": False, "error": "Fixture ends"})
                assert (await recv(screen))["status"] == "abstained"

    asyncio.run(run())


def test_expiry_records_timeout_without_actuation(tmp_path, monkeypatch):
    async def run():
        async with (
            running(tmp_path, monkeypatch) as url,
            peer(url, lua=True) as lua,
            peer(url) as screen,
        ):
            expired = card()
            expired["created_at"] -= 121
            engine.PrescriptionJournal(srv._setup_experiment_store_path).remember(expired)
            await send(
                screen,
                {
                    "v": 1,
                    "type": ep.TYPE_SETUP_PRESCRIPTION_DECIDE,
                    "prescription_id": expired["prescription_id"],
                    "decision": "accept",
                },
            )
            await context(lua)
            assert (await recv(screen))["status"] == "expired"
            assert not srv._prescription_broker.pending
            row = engine.PrescriptionJournal(srv._setup_experiment_store_path).get(
                expired["prescription_id"]
            )
            assert row["decision"] == "timeout"

    asyncio.run(run())


def test_experiment_is_default_off_and_cannot_apply_an_old_card(tmp_path, monkeypatch):
    async def run():
        async with running(tmp_path, monkeypatch) as url, peer(url) as screen:
            monkeypatch.delenv("AC_COPILOT_PRESSURE_EXPERIMENT", raising=False)
            engine.PrescriptionJournal(srv._setup_experiment_store_path).remember(card())
            await send(screen, {"v": 1, "type": ep.TYPE_SETUP_PRESCRIPTION_GET})
            inactive = await recv(screen)
            assert inactive["status"] == "abstained"
            assert inactive["reason"] == "Pressure experiment inactive"
            await send(
                screen,
                {
                    "v": 1,
                    "type": ep.TYPE_SETUP_PRESCRIPTION_DECIDE,
                    "prescription_id": card()["prescription_id"],
                    "decision": "accept",
                },
            )
            assert (await recv(screen))["status"] == "blocked"
            assert not srv._prescription_broker.pending
            row = engine.PrescriptionJournal(srv._setup_experiment_store_path).get(
                card()["prescription_id"]
            )
            assert "decision" not in row

    asyncio.run(run())


def test_disarming_preserves_safe_readback_and_reject(tmp_path, monkeypatch):
    async def run():
        async with (
            running(tmp_path, monkeypatch) as url,
            peer(url, lua=True) as lua,
            peer(url) as screen,
        ):
            journal = engine.PrescriptionJournal(srv._setup_experiment_store_path)
            journal.remember(card())
            journal.decide(card()["prescription_id"], "accept")
            monkeypatch.delenv("AC_COPILOT_PRESSURE_EXPERIMENT", raising=False)
            await send(
                screen,
                {
                    "v": 1,
                    "type": ep.TYPE_SETUP_PRESCRIPTION_DECIDE,
                    "prescription_id": card()["prescription_id"],
                    "decision": "accept",
                },
            )
            await context(lua)
            await result(lua, operation="readback", readback={"PRESSURE_LF": 23})
            assert (await recv(screen))["status"] == "verified_applied"

    asyncio.run(run())


def test_normal_input_path_selects_current_session_last_two_without_skipping_traps(
    tmp_path, monkeypatch
):
    from tools.ai_sidecar.setup_optimizer import save_records

    lap_dir = tmp_path / "journal/laps"
    lap_dir.mkdir(parents=True)
    store = tmp_path / "journal/setup_experiments/experiments.jsonl"
    rows = []
    for lap_n in (9, 3, 2):
        session = "older" if lap_n == 9 else "session"
        path = lap_dir / f"lap_{lap_n}.json"
        path.write_text(json.dumps({"lap": {"lap_n": lap_n}, "trap": lap_n == 3}))
        rows.append(
            {
                "experiment_id": str(lap_n),
                "session_uuid": session,
                "lap": {"lap_n": lap_n},
                "source_lap_path": str(path),
            }
        )
    save_records(rows, store)
    monkeypatch.setattr(srv, "read_tyre_specs", lambda *_a, **_k: None)
    archives, targets = srv._prescription_inputs(
        {"lap_dir": str(lap_dir), "identity": IDENTITY}, store
    )
    assert [row["lap"]["lap_n"] for row in archives] == [2, 3]
    assert archives[-1]["trap"] is True
    assert targets == {}


def test_registered_journal_cannot_be_redirected_by_context(tmp_path):
    ctx = {"lap_dir": str(tmp_path / "journal/laps"), "identity": IDENTITY}
    with pytest.raises(ValueError, match="does not match"):
        srv._prescription_inputs(
            ctx, tmp_path / "other/journal/setup_experiments/experiments.jsonl"
        )
