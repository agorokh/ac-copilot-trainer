"""Normal WS/HTTP activation of parked human practice references (#529)."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from contextlib import asynccontextmanager

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from tests.test_coaching_practice_runtime import COMBO, _reference
from tools.ai_sidecar import external_protocol as ep
from tools.ai_sidecar import server
from tools.lap_qualification import build_qualification, qualify_archive


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.upper().startswith("AC_COPILOT_"):
            monkeypatch.delenv(key, raising=False)
    ledger = tmp_path / "synthetic-attributions.json"
    ledger.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")
    monkeypatch.setenv("AC_COPILOT_LAP_ATTRIBUTIONS", str(ledger))
    monkeypatch.setenv("AC_COPILOT_COACH_DRILLS", "1")
    server._reset_external_state()
    server.set_coach_runtime(None)
    server.set_realtime_observer(None)
    server.set_voice_coach(None)
    yield
    server._reset_external_state()
    monkeypatch.delenv("AC_COPILOT_COACH_DRILLS", raising=False)
    server._wire_voice(server.VoiceRuntimeConfig(None, None))
    server.set_realtime_observer(None)


@asynccontextmanager
async def _sidecar(tmp_path, reference=None):
    path = tmp_path / "qualified-human-reference.json"
    path.write_text(json.dumps(_reference() if reference is None else reference), encoding="utf-8")
    server._wire_voice(server.VoiceRuntimeConfig(str(path), None))
    async with serve(
        lambda ws: server._handler(ws, reply_coaching=True),
        "127.0.0.1",
        0,
        process_request=server.make_process_request("synthetic-test-token"),
    ) as listener:
        port = listener.sockets[0].getsockname()[1]
        yield port


async def _health(port):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 2)
        headers, body = response.split(b"\r\n\r\n", 1)
        assert headers.startswith(b"HTTP/1.1 200 ")
        return json.loads(body)
    finally:
        writer.close()
        await writer.wait_closed()


async def _wait_health(port, predicate):
    async with asyncio.timeout(2):
        while True:
            status = await _health(port)
            if predicate(status):
                return status
            await asyncio.sleep(0.01)


@asynccontextmanager
async def _peer(port, *, native=True, authorized=True):
    headers = {ep.CLIENT_HEADER: ep.LUA_CLIENT_ID} if authorized else {}
    async with connect(f"ws://127.0.0.1:{port}", additional_headers=headers) as ws:
        await ws.send(
            json.dumps(
                {
                    "v": 1,
                    "type": "hello",
                    "client": ep.LUA_CLIENT_ID if native else "test-dashboard",
                    "client_class": "lua" if native else "browser",
                }
            )
        )
        assert json.loads(await ws.recv())["type"] == "hello_ack"
        yield ws


async def _send(ws, frame):
    await ws.send(json.dumps(frame))
    # A validated-in-order application response proves the preceding snapshot was
    # consumed before any negative assertion, independently of HTTP scheduling.
    await ws.send('{"v":1,"type":"test.barrier"}')
    async with asyncio.timeout(2):
        while True:
            reply = json.loads(await ws.recv())
            if reply.get("type") == "error" and reply.get("ref_type") == "test.barrier":
                return


def _session(*, car=COMBO[0], track=COMBO[1], session="native-live-session", **extra):
    return {
        "v": 1,
        "type": "state.snapshot",
        "topic": "session",
        "payload": {
            "car_id": car,
            "track_id": track,
            "session_index": 0,
            "session_uuid": session,
        },
        **extra,
    }


def _phase(status):
    return status["voice"]["practice_drill"]["phase"]


def test_real_ws_activates_only_after_independent_native_combo_and_duplicate_is_noop(tmp_path):
    async def scenario():
        async with _sidecar(tmp_path) as port:
            initial = await _health(port)
            assert server._coach_runtime is None and server._observer is None
            assert initial["voice"]["practice_drill"] == {
                "configured": True,
                "active": False,
                "phase": "unavailable",
                "reason": "expected_combo_unavailable",
            }
            async with _peer(port) as ws:
                await _send(ws, _session())
                health = await _wait_health(port, lambda status: _phase(status) == "warmup")
                runtime = server._coach_runtime
                assert runtime is not None and runtime.practice is not None
                assert runtime.practice.reference_qualification.allowed
                assert runtime.practice.reference_qualification.authority == "human"
                assert server._observer is not None and server._map_reference_archive is not None
                assert set(health["voice"]["practice_drill"]) == {
                    "configured",
                    "active",
                    "phase",
                    "reason",
                }
                assert "native-live-session" not in json.dumps(health)
                generation = server._map_comparison_generation
                await _send(ws, _session())
                await _health(port)
                assert server._coach_runtime is runtime
                assert server._map_comparison_generation == generation
            await _wait_health(port, lambda status: _phase(status) == "unavailable")
            assert server._coach_runtime is None and server._observer is None
            assert runtime.practice.status()["phase"] == "aborted"
            assert runtime.practice.status()["reason"] == "native_session_disconnected"

    asyncio.run(scenario())


@pytest.mark.parametrize("native,authorized", [(True, False), (False, True), (False, False)])
def test_non_native_or_untrusted_hello_cannot_activate_reference(tmp_path, native, authorized):
    async def scenario():
        async with _sidecar(tmp_path) as port:
            async with _peer(port, native=native, authorized=authorized) as ws:
                await _send(ws, _session())
                status = await _health(port)
                assert _phase(status) == "unavailable"
                assert server._coach_runtime is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "bad",
    [
        _session(car="different-car"),
        _session(track="magione/wrong-layout"),
        _session(snapshot_age_ms=0),
        _session(session=""),
        {
            "v": 1,
            "type": "state.snapshot",
            "topic": "connection",
            "payload": {"car_id": COMBO[0], "track_id": COMBO[1], "session_index": 0},
        },
    ],
)
def test_wrong_combo_replayed_or_incomplete_native_identity_remains_parked(tmp_path, bad):
    async def scenario():
        async with _sidecar(tmp_path) as port:
            async with _peer(port) as ws:
                await _send(ws, bad)
                status = await _health(port)
                assert _phase(status) == "unavailable"
                assert server._coach_runtime is None and server._observer is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "reference",
    [
        _reference(authority=None),
        _reference(authority="ai"),
        {"malformed": True},
    ],
)
def test_native_context_cannot_promote_legacy_ai_or_invalid_reference(tmp_path, reference):
    async def scenario():
        async with _sidecar(tmp_path, reference) as port:
            async with _peer(port) as ws:
                await _send(ws, _session())
                status = await _health(port)
                assert _phase(status) == "unavailable"
                assert server._coach_runtime is None and server._observer is None
                assert not status["voice"]["enabled"]

    asyncio.run(scenario())


def test_human_import_cannot_activate_native_practice(tmp_path):
    reference = _reference()
    reference.update(source="imported", import_format="motec_csv")
    envelope = reference.pop("qualification")
    reference["qualification"] = build_qualification(
        reference,
        authority="human",
        origin="synthetic-import-test",
        supported_uses=envelope["supported_uses"],
        channels=envelope["channels"],
        evidence=envelope["evidence"],
    )
    assert qualify_archive(reference, use="live_reference", expected_combo=COMBO).allowed

    async def scenario():
        async with _sidecar(tmp_path, reference) as port:
            async with _peer(port) as ws:
                await _send(ws, _session())
                status = await _health(port)
                assert _phase(status) == "unavailable"
                assert server._coach_runtime is None

    asyncio.run(scenario())


def test_combo_change_aborts_and_stops_old_audio_before_clearing_guard(tmp_path):
    async def scenario():
        async with _sidecar(tmp_path) as port:
            async with _peer(port) as ws:
                await _send(ws, _session())
                await _wait_health(port, lambda status: _phase(status) == "warmup")
                runtime = server._coach_runtime
                events = []

                class ExistingVoice:
                    def set_instructional_guard(self, guard):
                        self.guard = guard
                        events.append("guard" if guard is not None else "unguard")

                    def refresh_instructional_guard(self):
                        assert not self.guard()
                        events.append("cancel")

                    def stop(self):
                        assert not self.guard()
                        events.append("stop")

                voice = ExistingVoice()
                server.set_voice_coach(voice)
                await _send(ws, _session())
                assert events == ["guard"]
                assert server._voice_coach is voice and server._coach_runtime is runtime
                await _send(ws, _session(track="different-track"))
                await _wait_health(port, lambda status: _phase(status) == "unavailable")
                assert events == ["guard", "cancel", "stop"]
                assert server._voice_coach is None
                assert server._coach_runtime is None and server._observer is None
                assert runtime.practice.status()["reason"] == "native_session_changed"
                # A new matching identity cannot silently acquire another lap budget.
                await _send(ws, _session(session="new-native-session"))
                status = await _health(port)
                assert status["voice"]["practice_drill"]["reason"] == "practice_restart_required"
                assert server._coach_runtime is None

    asyncio.run(scenario())


def test_stale_native_producer_is_silenced_and_heartbeat_keeps_same_generation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(server, "_PRACTICE_NATIVE_MAX_AGE_S", 0.08)

    async def scenario():
        async with _sidecar(tmp_path) as port:
            async with _peer(port) as ws:
                await _send(ws, _session())
                await _wait_health(port, lambda status: _phase(status) == "warmup")
                runtime = server._coach_runtime
                heartbeat = copy.deepcopy(_session())
                heartbeat["topic"] = "connection"
                heartbeat["payload"].pop("session_uuid")
                for _ in range(4):
                    await asyncio.sleep(0.03)
                    await _send(ws, heartbeat)
                    assert _phase(await _health(port)) == "warmup"
                    assert server._coach_runtime is runtime
                status = await _wait_health(port, lambda status: _phase(status) == "unavailable")
                assert status["voice"]["practice_drill"]["reason"] == "native_session_stale"
                assert server._coach_runtime is None and server._observer is None

    asyncio.run(scenario())


def test_default_off_native_identity_does_not_activate_managed_reference(tmp_path, monkeypatch):
    monkeypatch.delenv("AC_COPILOT_COACH_DRILLS")

    async def scenario():
        async with _sidecar(tmp_path) as port:
            async with _peer(port) as ws:
                await _send(ws, _session())
                status = await _health(port)
                assert status["voice"]["practice_drill"] == {
                    "configured": False,
                    "active": False,
                    "phase": "disabled",
                    "reason": "not_configured",
                }
                assert server._coach_runtime is None and server._observer is None
                assert "expected_combo_unavailable" in status["voice"]["disabled_reason"]

    asyncio.run(scenario())


def test_new_backend_without_reference_reports_private_free_disabled_practice(monkeypatch):
    monkeypatch.delenv("AC_COPILOT_COACH_DRILLS")
    server._wire_voice(server.VoiceRuntimeConfig(None, None))
    status = server.public_voice_runtime_status()["practice_drill"]
    assert status == {
        "configured": False,
        "active": False,
        "phase": "disabled",
        "reason": "not_configured",
    }


def test_wrong_initial_combo_does_not_consume_the_single_practice_admission(tmp_path):
    async def scenario():
        async with _sidecar(tmp_path) as port:
            async with _peer(port) as ws:
                await _send(ws, _session(track="other-track"))
                assert server._coach_runtime is None and not server._practice_admitted
                await _send(ws, _session())
                assert _phase(await _health(port)) == "warmup"
                assert server._practice_admitted

    asyncio.run(scenario())


@pytest.mark.parametrize("new_uuid", [False, True])
def test_reconnect_never_resets_an_admitted_practice_budget(tmp_path, new_uuid):
    async def scenario():
        async with _sidecar(tmp_path) as port:
            async with _peer(port) as ws:
                await _send(ws, _session())
                assert _phase(await _health(port)) == "warmup"
                original = server._coach_runtime
            await _wait_health(port, lambda status: _phase(status) == "unavailable")
            async with _peer(port) as ws:
                await _send(
                    ws,
                    _session(session="new-native-session" if new_uuid else "native-live-session"),
                )
                status = await _health(port)
                assert status["voice"]["practice_drill"]["reason"] == "practice_restart_required"
                assert server._coach_runtime is None and server._observer is None
                assert original.practice.status()["phase"] == "aborted"

    asyncio.run(scenario())


def test_native_full_track_layout_matches_reference_independently(tmp_path):
    reference = _reference()
    envelope = reference.pop("qualification")
    reference["track"].update(id="synthetic-track", layout="national")
    reference["qualification"] = build_qualification(
        reference,
        authority="human",
        origin="synthetic-layout-test",
        supported_uses=envelope["supported_uses"],
        channels=envelope["channels"],
        evidence=envelope["evidence"],
    )

    async def scenario():
        async with _sidecar(tmp_path, reference) as port:
            async with _peer(port) as ws:
                await _send(ws, _session(track="synthetic-track"))
                assert server._coach_runtime is None
                await _send(ws, _session(track="synthetic-track/national"))
                assert _phase(await _health(port)) == "warmup"
                assert server._practice_native_identity[:3] == (
                    COMBO[0],
                    "synthetic-track",
                    "national",
                )

    asyncio.run(scenario())
