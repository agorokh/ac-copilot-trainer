"""Accelerated native transport fixtures; no AC, real driver, or audio backend."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time

import pytest
import websockets
from websockets.asyncio.server import serve

from tests.test_coaching_practice_bootstrap import _scoped_raw_reference
from tests.test_human_session import ASSISTANCE, native_identity, payload
from tests.test_server_practice_activation import _health, _peer, _send
from tools import human_session
from tools.ai_sidecar import server
from tools.ai_sidecar.coaching import practice
from tools.human_session import PRACTICE_COMBO, HumanSessionPermit
from tools.lap_archive_export import load_lap_archive
from tools.lap_qualification import qualify_archive


class _Clock:
    """Only replace these modules' clocks; the asyncio loop retains real time."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


class _SilentVoice:
    enabled = True
    practice_evidence_ready = True
    playback_details = {"device_name": "synthetic-no-audio"}

    def start(self):
        pass

    def stop(self):
        pass

    def set_instruction_guard(self, guard):
        self.guard = guard

    def subscribe(self, advisory):
        pass

    def refresh_instruction_guard(self):
        pass


@pytest.fixture
def study(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.upper().startswith("AC_COPILOT_"):
            monkeypatch.delenv(key, raising=False)
    ledger = tmp_path / "journal" / "lap-attributions.json"
    ledger.parent.mkdir()
    ledger.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")
    archive_root = ledger.parent / "laps"
    archive_root.mkdir()
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    permit_path = tmp_path / "campaign.json"
    HumanSessionPermit.prepare(
        permit_path, driver_id="synthetic-private-driver", assistance=ASSISTANCE
    )
    monkeypatch.setenv("AC_COPILOT_PRACTICE_PERMIT", str(permit_path))
    monkeypatch.setenv("AC_COPILOT_COACH_DRILLS", "1")
    clock = _Clock()
    monkeypatch.setattr(server, "time", clock)
    monkeypatch.setattr(human_session, "time", clock)
    monkeypatch.setattr(practice, "time", clock)
    from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank
    from tools.ai_sidecar.voice.engine import VoiceCoach

    monkeypatch.setattr(VoiceCoach, "from_bank", lambda *a, **kw: _SilentVoice())
    bank = tmp_path / "synthetic-bank"
    bake_bank(bank, ToneBackend())
    server._reset_external_state()
    server._wire_voice(server.VoiceRuntimeConfig("unused-historical-reference.json", str(bank)))
    yield permit_path, archive_root, ledger, clock
    server._reset_external_state()
    monkeypatch.delenv("AC_COPILOT_PRACTICE_PERMIT", raising=False)
    monkeypatch.delenv("AC_COPILOT_COACH_DRILLS", raising=False)
    server._wire_voice(server.VoiceRuntimeConfig(None, None))
    server.set_voice_coach(None)


def _session_frame(**changes):
    return {
        "v": 1,
        "type": "state.snapshot",
        "topic": "session",
        "payload": native_identity(**changes),
    }


def _tick(ordinal, elapsed=0, **changes):
    return {
        "v": 1,
        "type": "telemetry_tick",
        "payload": {
            **payload(ordinal, elapsed, min(0.999, elapsed / 60000)),
            "speed_kmh": 100.0,
            "rpm": 5000.0,
            "throttle": 0.5,
            "brake": 0.0,
            "steer": 0.0,
            "gear": 3,
            "lat_g": 0.0,
            "long_g": 0.0,
            "tyre_temps_c": dict.fromkeys(("fl", "fr", "rl", "rr"), 90.0),
            "brake_temps_c": dict.fromkeys(("fl", "fr", "rl", "rr"), 100.0),
            "tyre_optimal_temp_c": 90.0,
            "conditions": {"weatherType": 15, "trackGripLevel": 1.0},
            **changes,
        },
    }


async def _complete_warmup(ws, root, clock, ordinal, *, reported_ordinal=None, valid=True):
    origin = 1000 + (ordinal - 1) * 60.25
    if ordinal == 1:
        clock.now = origin
        await _send(ws, _tick(ordinal))
    for elapsed in range(250, 60001, 250):
        clock.now = origin + elapsed / 1000
        await _send(ws, _tick(ordinal, elapsed))
    clock.now = origin + 60.25
    await _send(ws, _tick(ordinal + 1))
    path = root / f"lap_synthetic_native_{ordinal}.json"
    record = _scoped_raw_reference(ordinal)
    record["conditions"]["weatherType"] = 15
    record["lap"]["is_valid"] = valid
    path.write_text(json.dumps(record), encoding="utf-8")
    before = path.read_bytes()
    await _send(
        ws,
        {
            "protocol": "ac_copilot_trainer.v1",
            "event": "lap_complete",
            "lap": ordinal if reported_ordinal is None else reported_ordinal,
            "lapTimeMs": 60000,
            "archivePath": str(path),
            "brainOnly": True,
        },
    )
    assert path.read_bytes() == before
    return path


def test_normal_native_ws_bootstraps_same_collector_with_only_two_warmups(study):
    permit_path, root, ledger, clock = study

    async def scenario():
        async with serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            0,
            process_request=server.make_process_request("synthetic-test-token"),
        ) as listener:
            port = listener.sockets[0].getsockname()[1]
            async with _peer(port) as ws:
                await _send(ws, _session_frame())
                collector = server._human_practice_session
                assert collector is not None and server._coach_runtime is None
                first = await _complete_warmup(ws, root, clock, 1)
                assert collector.status()["observed_laps"] == 1
                second = await _complete_warmup(ws, root, clock, 2)
                runtime = server._coach_runtime
                assert runtime is not None and runtime.practice is collector
                assert runtime.ledger is collector.ledger
                assert collector.status()["observed_laps"] == 2
                assert collector.status()["baseline_laps"] == 0
                assert collector.reference_identity == "scoped-warmup-1"
                assert collector.reference_qualification.authority == "attested_human"
                public = await _health(port)
                assert "synthetic-private-driver" not in json.dumps(public)
                assert str(permit_path) not in json.dumps(public)
                for path in (first, second):
                    archive = load_lap_archive(path)
                    assert "qualification" not in json.loads(path.read_bytes())
                    for use in ("human_progression", "live_reference", "map", "plant_fit"):
                        assert not qualify_archive(
                            archive, use=use, expected_combo=PRACTICE_COMBO
                        ).allowed
                entries = json.loads(ledger.read_bytes())["entries"]
                assert len(entries) == 2
                assert all(e["qualification"]["authority"] == "attested_human" for e in entries)
        assert HumanSessionPermit.read_status(permit_path)["phase"] == "aborted"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"is_live": False},
        {"is_replay": True},
        {"is_ai": True},
        {"is_ai": None},
        {"archive_lap_n": 2},
        {"track_id": "magione"},
    ],
)
def test_nonfresh_or_unproved_native_session_cannot_consume_permit(study, change):
    permit_path, _, ledger, _ = study

    async def scenario():
        async with serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            0,
            process_request=server.make_process_request("synthetic-test-token"),
        ) as listener:
            async with _peer(listener.sockets[0].getsockname()[1]) as ws:
                await _send(ws, _session_frame(**change))
                assert server._human_practice_session is None
                assert server._coach_runtime is None
                assert HumanSessionPermit.read_status(permit_path)["phase"] == "prepared"
                assert json.loads(ledger.read_bytes())["entries"] == []

    asyncio.run(scenario())


def test_control_change_aborts_permit_without_qualifying_archive(study):
    permit_path, _, ledger, _ = study

    async def scenario():
        async with serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            0,
            process_request=server.make_process_request("synthetic-test-token"),
        ) as listener:
            async with _peer(listener.sockets[0].getsockname()[1]) as ws:
                await _send(ws, _session_frame())
                await _send(ws, _tick(1, is_ai=True))
                assert HumanSessionPermit.read_status(permit_path)["phase"] == "aborted"
                assert server._coach_runtime is None
                assert json.loads(ledger.read_bytes())["entries"] == []

    asyncio.run(scenario())


def test_mismatched_completion_is_rejected_before_attribution_append(study):
    permit_path, root, ledger, clock = study

    async def scenario():
        async with serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            0,
            process_request=server.make_process_request("synthetic-test-token"),
        ) as listener:
            async with _peer(listener.sockets[0].getsockname()[1]) as ws:
                await _send(ws, _session_frame())
                await _complete_warmup(ws, root, clock, 1, reported_ordinal=2)
                assert HumanSessionPermit.read_status(permit_path)["phase"] == "aborted"
                assert json.loads(ledger.read_bytes())["entries"] == []

    asyncio.run(scenario())


def test_restart_and_identity_change_cannot_reset_consumed_study(study):
    permit_path, _, ledger, _ = study

    async def scenario():
        async with serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            0,
            process_request=server.make_process_request("synthetic-test-token"),
        ) as listener:
            async with _peer(listener.sockets[0].getsockname()[1]) as ws:
                await _send(ws, _session_frame())
                await _send(ws, _session_frame(session_uuid="different-session"))
                assert HumanSessionPermit.read_status(permit_path)["phase"] == "aborted"
                server._wire_voice(server.VoiceRuntimeConfig(None, None))
                assert server._human_session_permit is None
                assert server._coach_runtime is None
                assert (
                    server._pending_practice_status()["reason"]
                    == "human_session_permit_unavailable"
                )
                assert json.loads(ledger.read_bytes())["entries"] == []
                from tests.test_coaching_practice_runtime import COMBO, _reference

                legacy = permit_path.parent / "synthetic-verified-legacy.json"
                legacy.write_text(json.dumps(_reference()), encoding="utf-8")
                server._wire_voice(server.VoiceRuntimeConfig(str(legacy), None))
                await _send(ws, _session_frame(car_id=COMBO[0], track_id=COMBO[1]))
                assert server._coach_runtime is None
                assert server._human_practice_session is None

    asyncio.run(scenario())


def test_production_wire_then_run_order_preserves_unconsumed_configuration(study, monkeypatch):
    permit_path, _, _, _ = study
    real_serve = websockets.serve

    async def scenario():
        bound = asyncio.Event()
        port = None

        class ObservedServer:
            def __init__(self, *args, **kwargs):
                self.inner = real_serve(*args, **kwargs)

            async def __aenter__(self):
                nonlocal port
                listener = await self.inner.__aenter__()
                port = listener.sockets[0].getsockname()[1]
                bound.set()
                return listener

            async def __aexit__(self, *args):
                return await self.inner.__aexit__(*args)

        monkeypatch.setattr(websockets, "serve", ObservedServer)
        task = asyncio.create_task(server._run("127.0.0.1", 0, True, "synthetic-test-token"))
        try:
            await asyncio.wait_for(bound.wait(), 2)
            assert server._human_session_permit is not None
            assert HumanSessionPermit.read_status(permit_path)["phase"] == "prepared"
            async with _peer(port) as ws:
                await _send(ws, _session_frame())
                assert server._human_practice_session is not None
                assert server._human_practice_session.drill_id == "trail-brake-entry"
                assert HumanSessionPermit.read_status(permit_path)["phase"] == "active"
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        assert server._human_session_permit is None
        assert HumanSessionPermit.read_status(permit_path)["phase"] == "aborted"

    asyncio.run(scenario())


def test_ineligible_first_warmup_can_use_second_without_an_added_seed_lap(study):
    _, root, _, clock = study

    async def scenario():
        async with serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            0,
            process_request=server.make_process_request("synthetic-test-token"),
        ) as listener:
            async with _peer(listener.sockets[0].getsockname()[1]) as ws:
                await _send(ws, _session_frame())
                collector = server._human_practice_session
                await _complete_warmup(ws, root, clock, 1, valid=False)
                assert collector.status()["observed_laps"] == 1
                assert server._coach_runtime is None
                await _complete_warmup(ws, root, clock, 2)
                assert server._coach_runtime.practice is collector
                assert collector.reference_identity == "scoped-warmup-2"
                assert collector.status()["observed_laps"] == 2
                assert collector.status()["baseline_laps"] == 0

    asyncio.run(scenario())


def test_prospective_serve_without_private_inspection_token_does_not_consume_session(study):
    permit_path, _, _, _ = study
    with pytest.raises(SystemExit, match="configured sidecar token"):
        asyncio.run(server._run("127.0.0.1", 0, True, None))
    assert HumanSessionPermit.read_status(permit_path)["phase"] == "prepared"
