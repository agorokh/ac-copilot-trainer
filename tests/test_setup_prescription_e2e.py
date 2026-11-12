"""Synthetic vertical integration, not the twelve-case real-driver experiment.

Real WebSocket dispatch, journal registration/import, archive loader, inference,
strict axle data reader, Lua prescription/setup library, and disk readback run
together. Only the absent CSP SDK and its unsafe physical setters are adapters.
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

pytest.importorskip("websockets")
lupa = pytest.importorskip("lupa")
from test_setup_prescription import inputs  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402

from tools.ai_sidecar import external_protocol as ep  # noqa: E402
from tools.ai_sidecar import server as srv  # noqa: E402
from tools.ai_sidecar.setup_optimizer import load_records  # noqa: E402

MODULES = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"


def _to_lua(rt, value):
    if isinstance(value, dict):
        return rt.table_from({key: _to_lua(rt, item) for key, item in value.items()})
    if isinstance(value, list):
        return rt.table_from([_to_lua(rt, item) for item in value])
    return value


def _from_lua(value):
    if not hasattr(value, "keys"):
        return value
    keys = list(value.keys())
    if keys and set(keys) == set(range(1, len(keys) + 1)):
        return [_from_lua(value[index]) for index in range(1, len(keys) + 1)]
    return {key: _from_lua(value[key]) for key in keys}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("AC_COPILOT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AC_COPILOT_PRESSURE_EXPERIMENT", "1")
    ledger = tmp_path / "attributions.json"
    ledger.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    ac_root, config = tmp_path / "assetto", tmp_path / "cfg"
    car_data = ac_root / "content/cars/test_car/data"
    car_data.mkdir(parents=True)
    (car_data / "tyres.ini").write_text(
        "[FRONT_1]\nNAME=Front\nPRESSURE_IDEAL=26\n"
        "[REAR_1]\nNAME=Rear\nPRESSURE_IDEAL=30\n"
        "[THERMAL_FRONT_1]\nPERFORMANCE_CURVE=front.lut\n"
        "[THERMAL_REAR_1]\nPERFORMANCE_CURVE=rear.lut\n",
        encoding="utf-8",
    )
    (car_data / "front.lut").write_text("70|0.9\n80|1\n90|0.9\n", encoding="utf-8")
    (car_data / "rear.lut").write_text("80|0.9\n90|1\n100|0.9\n", encoding="utf-8")
    monkeypatch.setattr(srv, "resolve_ac_root", lambda: ac_root)
    monkeypatch.setattr(srv, "_setup_experiment_store_path", None)
    monkeypatch.setattr(srv, "_setup_experiment_store_seeded", False)

    setup_path = tmp_path / "setups/test_car/test_track/test.ini"
    setup_path.parent.mkdir(parents=True)
    sections = ("PRESSURE_LF", "PRESSURE_RF", "PRESSURE_LR", "PRESSURE_RR")
    setup_path.write_text("".join(f"[{section}]\nVALUE=20\n" for section in sections))
    lap_dir = config / "ac_copilot_trainer/journal/laps"
    lap_dir.mkdir(parents=True)
    paths = []
    archives, _, _, _ = inputs(28)
    for archive in archives:
        # This input is synthetic, so no human evidence is manufactured. Use
        # the canonical qualifier's ordinary unannotated legacy-driver path.
        archive.pop("qualification", None)
        archive["setup"]["path"] = setup_path.as_posix()
        path = lap_dir / f"lap_{archive['lap']['lap_n']}.json"
        path.write_text(json.dumps(archive), encoding="utf-8")
        paths.append(path)

    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path="{MODULES.as_posix()}/?.lua;"..package.path')
    rt.globals()._setup = setup_path.as_posix()
    rt.globals()._config = config.as_posix()
    rt.globals()._root = ac_root.as_posix()
    rt.execute(
        """
        pit, writes = true, 0
        pressures = {PRESSURE_LF=20,PRESSURE_RF=20,PRESSURE_LR=20,PRESSURE_RR=20}
        ac = {
          FolderID={ScriptConfig=1,Root=2,UserSetups=3,Documents=4},
          getFolder=function(id)
            if id==1 then return _config elseif id==2 then return _root end
            return _config
          end,
          getCarID=function() return 'test_car' end,
          getTrackID=function() return 'test_track' end,
          getTrackLayout=function() return '' end,
          getCar=function() return {isInPit=pit,compoundIndex=1,setupFilename=_setup} end,
          getSim=function() return {} end,
          isCarResetAllowed=function() return true end,
          getSetupSpinners=function()
            local rows={}
            for _,section in ipairs({'PRESSURE_LF','PRESSURE_RF','PRESSURE_LR','PRESSURE_RR'}) do
              rows[#rows+1]={name=section,value=pressures[section],min=10,max=40,
                step=1,units='psi',displayMultiplier=1}
            end
            return rows
          end,
          setSetupSpinnerValue=function(section,value)
            writes=writes+1; pressures[section]=value; return true
          end
        }
        rpc=require('setup_prescription')
        """
    )
    return rt, paths, lap_dir.parent / "setup_experiments/experiments.jsonl"


async def _send(ws, frame):
    await ws.send(json.dumps(frame))


async def _recv(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 3))


@asynccontextmanager
async def _peer(url, *, lua=False):
    headers = {ep.AUTH_HEADER: "synthetic-test-token"}
    if lua:
        headers[ep.CLIENT_HEADER] = ep.LUA_CLIENT_ID
    async with connect(url, additional_headers=headers) as ws:
        await _send(
            ws,
            {
                "v": 1,
                "type": "hello",
                "client": "synthetic-e2e",
                "client_class": "lua" if lua else "screen",
            },
        )
        assert (await _recv(ws))["type"] == "hello_ack"
        yield ws


@asynccontextmanager
async def _running(fixture):
    rt, paths, store = fixture
    srv._reset_external_state()
    async with serve(
        lambda ws: srv._handler(ws, reply_coaching=False),
        "127.0.0.1",
        0,
        process_request=srv.make_process_request("synthetic-test-token"),
    ) as listener:
        url = f"ws://127.0.0.1:{listener.sockets[0].getsockname()[1]}"
        try:
            async with _peer(url, lua=True) as lua:
                await _send(
                    lua, {"v": 1, "type": "setup.experiment.store", "store_path": str(store)}
                )
                assert (await _recv(lua))["ok"] is True
                for path in paths:
                    await _send(
                        lua, {"v": 1, "type": "setup.experiment.record", "archive_path": str(path)}
                    )
                    assert (await _recv(lua))["ok"] is True
                yield url, lua, rt, store
        finally:
            srv._reset_external_state()


async def _relay(lua, rt):
    request = await _recv(lua)
    assert request["type"] == ep.TYPE_SETUP_PRESCRIPTION_RPC
    response = _from_lua(rt.globals().rpc.handle(_to_lua(rt, request), "test_session"))
    response.update(v=1, type=ep.TYPE_SETUP_PRESCRIPTION_RPC_RESULT)
    await _send(lua, response)
    return request, response


async def _get_card(screen, lua, rt):
    await _send(screen, {"v": 1, "type": ep.TYPE_SETUP_PRESCRIPTION_GET, "request_id": "epoch1"})
    request, context = await _relay(lua, rt)
    assert request["operation"] == "context" and context["is_in_pit"] is True
    card = await _recv(screen)
    assert card["status"] == "proposed", card
    assert card["request_id"] == "epoch1"
    assert {change["section"]: change["to"] for change in card["changes"]} == {
        "PRESSURE_LF": 19,
        "PRESSURE_RF": 19,
        "PRESSURE_LR": 21,
        "PRESSURE_RR": 21,
    }
    assert "measured" in card["evidence"] and "psi" in card["evidence"]
    return card


def _accept(card):
    return {
        "v": 1,
        "type": ep.TYPE_SETUP_PRESCRIPTION_DECIDE,
        "prescription_id": card["prescription_id"],
        "decision": "accept",
        "request_id": "epoch1",
    }


def test_full_synthetic_get_apply_readback_and_reconnect_dedup(fixture):
    async def run():
        async with _running(fixture) as (url, lua, rt, store):
            async with _peer(url) as screen:
                card = await _get_card(screen, lua, rt)
                await _send(screen, _accept(card))
                await _relay(lua, rt)  # fresh authoritative context
                request, applied = await _relay(lua, rt)  # actual Lua -> SDK adapter -> readback
                assert request["operation"] == "apply" and applied["ok"] is True
                assert rt.globals().writes == 4
                assert (await _recv(screen))["status"] == "verified_applied"
                for _ in range(2):
                    await _send(screen, _accept(card))
                    await _relay(lua, rt)  # no second apply after this context
                    assert (await _recv(screen))["status"] == "verified_applied"
            async with _peer(url) as reconnected:
                await _send(reconnected, _accept(card))
                await _relay(lua, rt)
                assert (await _recv(reconnected))["status"] == "verified_applied"
            assert rt.globals().writes == 4
            rows = [
                row for row in load_records(store) if row.get("record_type") == "setup_prescription"
            ]
            assert len(rows) == 1 and rows[0]["decision"] == "accept"
            assert rows[0]["status"] == "verified_applied"
            assert rows[0]["readback"] == {
                "PRESSURE_LF": 19,
                "PRESSURE_RF": 19,
                "PRESSURE_LR": 21,
                "PRESSURE_RR": 21,
            }
            # The same store retains both original lap rows after the decision.
            assert len(load_records(store)) == 3

    asyncio.run(run())


def test_full_synthetic_pit_exit_and_reconnect_perform_zero_setters(fixture):
    async def run():
        async with _running(fixture) as (url, lua, rt, store):
            async with _peer(url) as screen:
                card = await _get_card(screen, lua, rt)
                rt.globals().pit = False
                await _send(screen, _accept(card))
                await _relay(lua, rt)
                request, refused = await _relay(lua, rt)
                assert request["operation"] == "apply" and refused["ok"] is False
                assert "pit box" in refused["error"]
                assert (await _recv(screen))["status"] == "accepted_unverified"
            async with _peer(url) as reconnected:
                await _send(reconnected, _accept(card))
                await _relay(lua, rt)
                request, readback = await _relay(lua, rt)
                assert request["operation"] == "readback" and readback["ok"] is True
                assert (await _recv(reconnected))["status"] == "accepted_unverified"
            assert rt.globals().writes == 0
            rows = [
                row for row in load_records(store) if row.get("record_type") == "setup_prescription"
            ]
            assert len(rows) == 1 and rows[0]["decision"] == "accept"
            assert rows[0]["status"] == "accepted_unverified"

    asyncio.run(run())
