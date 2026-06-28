"""Live voice-wiring tests (issue #341): protocol + observer→coaching.cue + in-process coach.

The sidecar turns the live ``telemetry_tick`` stream into spoken cues by feeding a
``RealtimeObserver`` and publishing its advisories on the ``coaching.cue`` topic (and feeding the
#340 in-process ``VoiceCoach``). These tests exercise that wiring with a fake observer + fake coach
(no audio hardware) and a real end-to-end WS round-trip. ``asyncio.run`` per repo convention.
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
from tools.ai_sidecar import server  # noqa: E402
from tools.ai_sidecar.realtime_observer import Advisory  # noqa: E402
from tools.ai_sidecar.server import _reset_external_state, make_token_check  # noqa: E402

# --------------------------------------------------------------------------------------------------
# Isolation — global sidecar module state must not leak between tests (Qodo focus area).
# --------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_sidecar_state() -> None:
    server.set_realtime_observer(None)
    server.set_voice_coach(None)
    _reset_external_state()
    yield
    server.set_realtime_observer(None)
    server.set_voice_coach(None)
    _reset_external_state()


# --------------------------------------------------------------------------------------------------
# Fakes + helpers
# --------------------------------------------------------------------------------------------------


class _FakeObserver:
    """Returns a fixed advisory list on every ``observe`` call."""

    def __init__(self, advisories: list[Advisory]) -> None:
        self._advisories = advisories
        self.frames_seen: list[dict] = []

    def observe(self, frame: dict) -> list[Advisory]:
        self.frames_seen.append(frame)
        return list(self._advisories)


class _FakeCoach:
    """Records advisories handed to it (stands in for the #340 VoiceCoach)."""

    def __init__(self) -> None:
        self.spoken: list[Advisory] = []

    def subscribe(self, advisory: Advisory) -> None:
        self.spoken.append(advisory)


def _advisory(**over: object) -> Advisory:
    base: dict = dict(
        kind="late_brake", corner=2, spline=0.4, urgency="act", message="Brake T3", detail={"x": 1}
    )
    base.update(over)
    return Advisory(**base)  # type: ignore[arg-type]


def _free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@asynccontextmanager
async def _running_sidecar() -> AsyncIterator[int]:
    port = _free_port()
    _reset_external_state()
    try:
        async with ws_serve(
            lambda ws: server._handler(ws, reply_coaching=True),
            "127.0.0.1",
            port,
            process_request=make_token_check(None),
        ):
            yield port
    finally:
        _reset_external_state()


def _telemetry_tick(**payload_overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "speed_kmh": 112.0,
        "rpm": 5400.0,
        "gear": 3,
        "throttle": 0.72,
        "brake": 0.84,
        "steer": -0.13,
        "lat_g": 0.42,
        "long_g": -0.78,
    }
    payload.update(payload_overrides)
    return {"v": 1, "type": ep.TYPE_TELEMETRY_TICK, "seq": 7, "ts_sim": 123.45, "payload": payload}


# --------------------------------------------------------------------------------------------------
# Protocol surface
# --------------------------------------------------------------------------------------------------


def test_voice_client_class_is_known_and_hello_validates() -> None:
    assert ep.CLIENT_CLASS_VOICE in ep.KNOWN_CLIENT_CLASSES
    hello = {"v": 1, "type": "hello", "client": "voice-1", "client_class": ep.CLIENT_CLASS_VOICE}
    assert ep.validate_inbound(hello) is None


def test_coaching_cue_topic_is_subscribable() -> None:
    assert ep.TOPIC_COACHING_CUE in ep.KNOWN_TOPICS
    sub = {"v": 1, "type": "state.subscribe", "topics": [ep.TOPIC_COACHING_CUE]}
    assert ep.validate_inbound(sub) is None


def test_telemetry_tick_accepts_optional_spline_and_lap() -> None:
    assert ep.validate_inbound(_telemetry_tick(spline=0.5)) is None
    assert ep.validate_inbound(_telemetry_tick(spline=0.0, lap=3)) is None
    assert ep.validate_inbound(_telemetry_tick(completedLaps=5)) is None
    assert ep.validate_inbound(_telemetry_tick(lapCount=5)) is None
    # still valid with neither (existing producers unaffected)
    assert ep.validate_inbound(_telemetry_tick()) is None


def test_telemetry_tick_rejects_bad_spline_and_lap() -> None:
    assert "spline must be <= 1" in (ep.validate_inbound(_telemetry_tick(spline=1.5)) or "")
    assert "spline must be >= 0" in (ep.validate_inbound(_telemetry_tick(spline=-0.1)) or "")
    assert "spline requires a finite number" in (
        ep.validate_inbound(_telemetry_tick(spline="x")) or ""
    )
    assert "lap must be >= 0" in (ep.validate_inbound(_telemetry_tick(lap=-1)) or "")


def test_make_coaching_cue_frame_shape() -> None:
    payload = {"kind": "late_brake", "corner": 2, "urgency": "act", "message": "Brake T3"}
    cue = ep.make_coaching_cue(payload, ts_sim=12.5)
    assert cue["v"] == ep.ENVELOPE_VERSION
    assert cue["type"] == ep.TYPE_STATE_SNAPSHOT
    assert cue["topic"] == ep.TOPIC_COACHING_CUE
    assert cue["payload"] is payload
    assert cue["source"] == "sidecar.observer"
    assert cue["ts_sim"] == 12.5
    assert "ts_sim" not in ep.make_coaching_cue(payload)  # omitted when None


# --------------------------------------------------------------------------------------------------
# _publish_coaching_cues unit logic
# --------------------------------------------------------------------------------------------------


def test_publish_coaching_cues_broadcasts_and_speaks(monkeypatch) -> None:
    captured: list[dict] = []

    async def _fake_broadcast(frame, *, exclude):  # noqa: ANN001
        captured.append(frame)

    monkeypatch.setattr(server, "_broadcast_external", _fake_broadcast)
    coach = _FakeCoach()
    adv = _advisory()
    server.set_realtime_observer(_FakeObserver([adv]))
    server.set_voice_coach(coach)
    try:
        asyncio.run(server._publish_coaching_cues({"ts_sim": 9.0, "payload": {}}, exclude="lua"))
    finally:
        server.set_realtime_observer(None)
        server.set_voice_coach(None)

    assert len(captured) == 1
    cue = captured[0]
    assert cue["topic"] == ep.TOPIC_COACHING_CUE
    assert cue["type"] == ep.TYPE_STATE_SNAPSHOT
    assert cue["payload"]["kind"] == "late_brake"
    assert cue["payload"]["corner"] == 2  # 0-based, faithful to the Advisory
    assert cue["payload"]["message"] == "Brake T3"
    assert cue["payload"]["spline"] == 0.4
    assert cue["payload"]["detail"] == {"x": 1}
    assert cue["ts_sim"] == 9.0
    assert coach.spoken == [adv]  # in-process coach got the same advisory


def test_publish_coaching_cues_is_noop_without_observer(monkeypatch) -> None:
    captured: list[dict] = []

    async def _fake_broadcast(frame, *, exclude):  # noqa: ANN001
        captured.append(frame)

    monkeypatch.setattr(server, "_broadcast_external", _fake_broadcast)
    server.set_realtime_observer(None)
    asyncio.run(server._publish_coaching_cues({"payload": {}}, exclude=None))
    assert captured == []


def test_publish_coaching_cues_survives_observer_fault(monkeypatch) -> None:
    class _BoomObserver:
        def observe(self, frame):  # noqa: ANN001
            raise RuntimeError("boom")

    captured: list[dict] = []

    async def _fake_broadcast(frame, *, exclude):  # noqa: ANN001
        captured.append(frame)

    monkeypatch.setattr(server, "_broadcast_external", _fake_broadcast)
    server.set_realtime_observer(_BoomObserver())
    try:
        # must not raise into the live loop
        asyncio.run(server._publish_coaching_cues({"payload": {}}, exclude=None))
    finally:
        server.set_realtime_observer(None)
    assert captured == []


# --------------------------------------------------------------------------------------------------
# End-to-end: telemetry_tick → coaching.cue to a voice-class WS client
# --------------------------------------------------------------------------------------------------


def test_telemetry_tick_publishes_coaching_cue_to_voice_client() -> None:
    adv = _advisory(kind="apex_deficit", corner=5, spline=0.6, urgency="info", message="T6 carry")

    async def _hello(ws, client: str, client_class: str | None = None) -> dict:
        frame: dict[str, object] = {"v": 1, "type": "hello", "client": client}
        if client_class is not None:
            frame["client_class"] = client_class
        await ws.send(json.dumps(frame))
        return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))

    async def _run() -> dict:
        server.set_realtime_observer(_FakeObserver([adv]))
        try:
            async with _running_sidecar() as port:
                async with (
                    ws_connect(f"ws://127.0.0.1:{port}/") as lua,
                    ws_connect(f"ws://127.0.0.1:{port}/") as voice,
                ):
                    await _hello(lua, "trainer-lua", ep.CLIENT_CLASS_LUA)
                    await _hello(voice, "voice-1", ep.CLIENT_CLASS_VOICE)
                    await lua.send(json.dumps(_telemetry_tick(spline=0.6), separators=(",", ":")))
                    return json.loads(await asyncio.wait_for(voice.recv(), timeout=2.0))
        finally:
            server.set_realtime_observer(None)

    cue = asyncio.run(_run())
    assert cue["type"] == ep.TYPE_STATE_SNAPSHOT
    assert cue["topic"] == ep.TOPIC_COACHING_CUE
    assert cue["payload"]["kind"] == "apex_deficit"
    assert cue["payload"]["corner"] == 5
    assert cue["payload"]["message"] == "T6 carry"
    assert cue["ts_sim"] == 123.45
