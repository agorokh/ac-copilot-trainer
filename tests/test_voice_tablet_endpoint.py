"""Tablet coaching-audio endpoint tests (issue #511 Part D).

Covers the additive protocol surface (``coaching.voice`` topic, ``voice.echo`` /
``voice.demo`` inbound types), the dispatch tap (post-scheduler broadcast seam), the engine
wiring, and the sidecar's static/JSON HTTP routes — all without audio hardware, per the
repo's injectable-playback test discipline.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path

import pytest

from tools.ai_sidecar import external_protocol as ep
from tools.ai_sidecar import server
from tools.ai_sidecar.server import _reset_external_state, make_process_request
from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank
from tools.ai_sidecar.voice.config import VoiceConfig
from tools.ai_sidecar.voice.dispatch import DispatchTapPlayback, VoiceDispatch
from tools.ai_sidecar.voice.engine import VoiceCoach
from tools.ai_sidecar.voice.playback import RecordingPlayback
from tools.ai_sidecar.voice.utterance import Utterance


@pytest.fixture(autouse=True)
def _isolated_sidecar_state():
    server.set_realtime_observer(None)
    server.set_voice_coach(None)
    _reset_external_state()
    server._voice_bank_dir = None
    server._voice_clip_files = frozenset()
    yield
    server.set_realtime_observer(None)
    server.set_voice_coach(None)
    _reset_external_state()
    server._voice_bank_dir = None
    server._voice_clip_files = frozenset()


def _utterance(clip_id: str = "late_brake.act.urgent.generic") -> Utterance:
    return Utterance(
        clip_id=clip_id,
        kind="late_brake",
        urgency="act",
        register="urgent",
        corner=None,
        text="Brake!",
        dedup_key="late_brake:None:urgent",
    )


# --------------------------------------------------------------------------------------------
# Protocol
# --------------------------------------------------------------------------------------------


def test_coaching_voice_topic_is_sidecar_produced_and_subscribable() -> None:
    assert ep.TOPIC_COACHING_VOICE in ep.SIDECAR_PRODUCED_TOPICS
    assert ep.TOPIC_COACHING_VOICE in ep.KNOWN_TOPICS
    assert ep.topics_are_sidecar_only([ep.TOPIC_COACHING_VOICE])
    err = ep.validate_inbound(
        {"v": 1, "type": ep.TYPE_STATE_SUBSCRIBE, "topics": [ep.TOPIC_COACHING_VOICE]}
    )
    assert err is None


def test_make_coaching_voice_shape() -> None:
    payload = {"seq": 1, "clip_id": "late_brake.act.critical.generic", "t_wall_ms": 123.0}
    frame = ep.make_coaching_voice(payload)
    assert frame["v"] == 1
    assert frame["type"] == ep.TYPE_STATE_SNAPSHOT
    assert frame["topic"] == ep.TOPIC_COACHING_VOICE
    assert frame["payload"] is payload
    assert frame["source"] == "sidecar.voice"


def test_validate_voice_echo_accepts_valid_and_rejects_bad() -> None:
    good = {
        "v": 1,
        "type": ep.TYPE_VOICE_ECHO,
        "seq": 3,
        "clip_id": "late_brake.act.urgent.generic",
        "t_dispatch_ms": 1000.0,
        "t_receive_ms": 1010.0,
        "t_play_ms": 1015.0,
        "buffer_state": "preloaded",
        "audio_armed": True,
    }
    assert ep.validate_inbound(good) is None
    for mutation, expect in [
        ({"seq": -1}, "seq"),
        ({"seq": True}, "seq"),
        ({"clip_id": ""}, "clip_id"),
        ({"t_dispatch_ms": "x"}, "t_dispatch_ms"),
        ({"buffer_state": "weird"}, "buffer_state"),
        ({"audio_armed": "yes"}, "audio_armed"),
    ]:
        frame = dict(good)
        frame.update(mutation)
        err = ep.validate_inbound(frame)
        assert err is not None and expect in err, (mutation, err)


def test_validate_voice_demo() -> None:
    good = {"v": 1, "type": ep.TYPE_VOICE_DEMO, "kind": "late_brake", "urgency": "act"}
    assert ep.validate_inbound(good) is None
    assert ep.validate_inbound({**good, "urgency": "loud"}) is not None
    assert ep.validate_inbound({**good, "kind": ""}) is not None
    assert ep.validate_inbound({**good, "corner": 99}) is not None
    assert ep.validate_inbound({**good, "corner": 5, "register": "critical"}) is None


# --------------------------------------------------------------------------------------------
# Dispatch tap
# --------------------------------------------------------------------------------------------


def test_dispatch_tap_emits_and_forwards() -> None:
    inner = RecordingPlayback()
    events: list[VoiceDispatch] = []
    wall = iter([100.0, 101.0]).__next__
    mono = iter([5.0, 6.0]).__next__
    tap = DispatchTapPlayback(
        inner,
        events.append,
        duration_lookup=lambda cid: 361.4,
        wall_clock=wall,
        mono_clock=mono,
    )
    utt = _utterance()
    tap.play(utt)
    assert inner.played == [utt]
    assert tap.current is utt
    assert len(events) == 1
    ev = events[0]
    assert ev.seq == 1
    assert ev.clip_id == utt.clip_id
    assert ev.duration_ms == 361.4
    assert ev.t_wall_ms == 100.0 * 1000.0
    assert ev.t_mono_ms == 5.0 * 1000.0
    tap.cancel()
    assert inner.cancelled == [utt]
    tap.play(_utterance("apex_deficit.info.calm.t01"))
    assert events[-1].seq == 2


def test_dispatch_tap_listener_fault_never_breaks_audio() -> None:
    inner = RecordingPlayback()

    def _boom(_ev: VoiceDispatch) -> None:
        raise RuntimeError("listener bug")

    tap = DispatchTapPlayback(inner, _boom)
    tap.play(_utterance())
    assert len(inner.played) == 1  # audio path wins


def test_dispatch_tap_no_event_when_backend_raises() -> None:
    class _Boom:
        current = None

        def play(self, _utt: Utterance) -> None:
            raise RuntimeError("device gone")

        def cancel(self) -> None:  # pragma: no cover - interface completeness
            pass

        def close(self) -> None:  # pragma: no cover
            pass

    events: list[VoiceDispatch] = []
    tap = DispatchTapPlayback(_Boom(), events.append)
    with pytest.raises(RuntimeError):
        tap.play(_utterance())
    assert events == []


def test_engine_wires_dispatch_listener_through_real_scheduler(tmp_path: Path) -> None:
    bake_bank(tmp_path, ToneBackend())
    events: list[VoiceDispatch] = []
    coach = VoiceCoach.from_bank(
        tmp_path,
        VoiceConfig(),
        playback=RecordingPlayback(),
        dispatch_listener=events.append,
    )
    assert coach.enabled
    coach.start()
    try:
        import time as _time

        from _voice_support import make_advisory

        coach.subscribe(make_advisory(kind="late_brake", urgency="act", corner=2))
        t0 = _time.perf_counter()
        while not events and _time.perf_counter() - t0 < 2.0:
            _time.sleep(0.002)
    finally:
        coach.stop()
    assert events, "dispatch listener never fired through the real scheduler"
    assert events[0].clip_id == "late_brake.act.urgent.generic"
    assert events[0].t_wall_ms > 0
    assert events[0].seq == 1


# --------------------------------------------------------------------------------------------
# Server: dispatch listener + HTTP routes
# --------------------------------------------------------------------------------------------


def test_on_voice_dispatch_records_without_event_loop() -> None:
    ev = VoiceDispatch(
        seq=1,
        clip_id="late_brake.act.critical.generic",
        kind="late_brake",
        urgency="act",
        register="critical",
        corner=None,
        text="Brake!",
        duration_ms=361.4,
        t_wall_ms=1.0,
        t_mono_ms=2.0,
    )
    server._on_voice_dispatch(ev)
    assert list(server._voice_dispatch_log)[-1]["clip_id"] == ev.clip_id


class _FakeHeaders:
    def __init__(self) -> None:
        self._data: dict[str, str] = {"Content-Type": "text/plain; charset=utf-8"}

    def __setitem__(self, key: str, value: str) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._data.get(key, default)


class _FakeResponse:
    def __init__(self, status: HTTPStatus, text: str) -> None:
        self.status = status
        self.headers = _FakeHeaders()
        self.body = text.encode("utf-8")


class _FakeConnection:
    def respond(self, status: HTTPStatus, text: str) -> _FakeResponse:
        return _FakeResponse(status, text)


class _FakeRequest:
    def __init__(self, path: str) -> None:
        self.path = path
        self.headers: dict[str, str] = {}


def _get(path: str):
    handler = make_process_request(None)
    return handler(_FakeConnection(), _FakeRequest(path))


def test_http_tablet_page_served() -> None:
    resp = _get("/tablet/voice")
    assert resp.status == HTTPStatus.OK
    assert "text/html" in resp.headers.get("Content-Type", "")
    assert b"coaching.voice" in resp.body


def test_http_voice_routes_404_without_bank() -> None:
    assert _get("/voice/manifest.json").status == HTTPStatus.NOT_FOUND
    assert _get("/voice/clips/anything.wav").status == HTTPStatus.NOT_FOUND


def test_http_clip_serving_is_allowlisted(tmp_path: Path) -> None:
    bake_bank(tmp_path, ToneBackend())
    server._set_voice_web_bank(tmp_path)
    manifest_resp = _get("/voice/manifest.json")
    assert manifest_resp.status == HTTPStatus.OK
    manifest = json.loads(manifest_resp.body.decode("utf-8"))
    entry = next(iter(manifest["clips"].values()))
    ok = _get(f"/voice/clips/{entry['file']}")
    assert ok.status == HTTPStatus.OK
    assert ok.headers.get("Content-Type") == "audio/wav"
    assert ok.headers.get("Content-Length") == str(len(ok.body))
    assert ok.body[:4] == b"RIFF"
    # Traversal / non-manifest names never resolve, even when the file exists on disk.
    assert _get("/voice/clips/../manifest.json").status == HTTPStatus.NOT_FOUND
    assert _get("/voice/clips/manifest.json").status == HTTPStatus.NOT_FOUND
    assert _get("/voice/clips/..%2Fmanifest.json").status == HTTPStatus.NOT_FOUND


def test_http_dispatch_and_echo_logs() -> None:
    server._voice_dispatch_log.append({"seq": 9, "clip_id": "x"})
    server._voice_echo_log.append({"seq": 9, "clip_id": "x", "t_server_ms": 1.0})
    d = json.loads(_get("/voice/dispatches").body.decode("utf-8"))
    e = json.loads(_get("/voice/echoes").body.decode("utf-8"))
    assert d["dispatches"][-1]["seq"] == 9
    assert e["echoes"][-1]["seq"] == 9


# --------------------------------------------------------------------------------------------
# Server: WS voice.echo / voice.demo flows (real sockets, loopback)
# --------------------------------------------------------------------------------------------

websockets = pytest.importorskip("websockets")
from websockets.asyncio.client import connect as ws_connect  # noqa: E402
from websockets.asyncio.server import serve as ws_serve  # noqa: E402


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
        ):
            yield port
    finally:
        _reset_external_state()


async def _hello(ws, client: str = "test-client", client_class: str = "voice") -> None:
    await ws.send(json.dumps({"v": 1, "type": "hello", "client": client,
                              "client_class": client_class}))
    ack = json.loads(await ws.recv())
    assert ack["type"] == "hello_ack"


def test_ws_voice_echo_recorded() -> None:
    async def _t() -> list[dict]:
        async with _running_sidecar() as port:
            async with ws_connect(f"ws://127.0.0.1:{port}") as ws:
                await _hello(ws)
                await ws.send(
                    json.dumps(
                        {
                            "v": 1,
                            "type": "voice.echo",
                            "seq": 7,
                            "clip_id": "late_brake.act.critical.generic",
                            "t_dispatch_ms": 100.0,
                            "t_receive_ms": 110.0,
                            "t_play_ms": 118.0,
                            "buffer_state": "preloaded",
                            "audio_armed": True,
                        }
                    )
                )
                # voice.echo is fire-and-forget; poll the log briefly. Capture INSIDE the
                # context — sidecar teardown clears the ring buffers by design.
                for _ in range(100):
                    if server._voice_echo_log:
                        break
                    await asyncio.sleep(0.01)
                return list(server._voice_echo_log)

    echoes = asyncio.run(_t())
    assert echoes, "echo was not recorded"
    rec = echoes[-1]
    assert rec["seq"] == 7
    assert rec["t_server_ms"] > 0


def test_ws_voice_demo_feeds_coach_and_broadcasts_cue() -> None:
    class _FakeCoach:
        def __init__(self) -> None:
            self.spoken: list = []

        def subscribe(self, advisory) -> None:
            self.spoken.append(advisory)

    coach = _FakeCoach()

    async def _t() -> list:
        async with _running_sidecar() as port:
            server.set_voice_coach(coach)
            async with ws_connect(f"ws://127.0.0.1:{port}") as listener:
                await _hello(listener, client="listener")
                await listener.send(
                    json.dumps({"v": 1, "type": "state.subscribe", "topics": ["coaching.cue"]})
                )
                async with ws_connect(f"ws://127.0.0.1:{port}") as producer:
                    await _hello(producer, client="bench")
                    await producer.send(
                        json.dumps(
                            {
                                "v": 1,
                                "type": "voice.demo",
                                "kind": "late_brake",
                                "urgency": "act",
                                "register": "critical",
                            }
                        )
                    )
                    frame = json.loads(await asyncio.wait_for(listener.recv(), timeout=5.0))
                    return [frame]

    frames = asyncio.run(_t())
    assert coach.spoken, "voice.demo never reached the coach"
    assert coach.spoken[0].register == "critical"
    assert frames[0]["topic"] == "coaching.cue"
    assert frames[0]["payload"]["kind"] == "late_brake"
