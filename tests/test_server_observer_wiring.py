"""M0 (#341) server wiring: live telemetry_tick -> RealtimeObserver -> coaching.cue fan-out."""

from __future__ import annotations

import asyncio
import json

import tools.ai_sidecar.server as server
from tests.test_realtime_observer import _corner_archive
from tools.ai_sidecar.external_protocol import TOPIC_COACHING_CUE, TYPE_STATE_SNAPSHOT
from tools.ai_sidecar.realtime_observer import Advisory


class _FakeObserver:
    def __init__(self, advisories):
        self._advisories = advisories
        self.calls = 0
        self.seen: list[dict] = []

    def observe(self, frame):
        self.calls += 1
        self.seen.append(frame)
        return self._advisories

    def reset(self):  # observer protocol used by _release_observer_feed
        pass


def _adv(kind="late_brake", corner=3, urgency="act"):
    return Advisory(kind=kind, corner=corner, spline=0.5, urgency=urgency, message="m", detail={})


def _capture_broadcast(monkeypatch):
    sent: list[tuple[dict, object]] = []

    async def _fake_broadcast(frame, *, exclude):
        sent.append((frame, exclude))

    monkeypatch.setattr(server, "_broadcast_external", _fake_broadcast)
    return sent


def _reset_feed(monkeypatch):
    """Isolate the single-producer feed globals per test."""
    monkeypatch.setattr(server, "_observer_feed_peer", None)
    monkeypatch.setattr(server, "_observer_feed_warned", False)
    server._peripheral_rate_limiter.reset()
    server._background_tasks.clear()


async def _run_publish_cues(frame, *, exclude):
    await server._publish_coaching_cues(frame, exclude=exclude)
    pending = list(server._background_tasks)
    if pending:
        await asyncio.gather(*pending)


def test_publish_coaching_cues_broadcasts_coaching_cue(monkeypatch):
    _reset_feed(monkeypatch)
    observer = _FakeObserver([_adv()])
    monkeypatch.setattr(server, "_observer", observer)
    sent = _capture_broadcast(monkeypatch)

    frame = {"type": "telemetry_tick", "payload": {"spline": 0.5, "speed_kmh": 100}}
    asyncio.run(_run_publish_cues(frame, exclude="ws-1"))

    assert observer.seen == [frame]
    assert len(sent) == 1
    cue_frame, exclude = sent[0]
    assert exclude == "ws-1"
    assert cue_frame["type"] == TYPE_STATE_SNAPSHOT
    assert cue_frame["topic"] == TOPIC_COACHING_CUE
    assert cue_frame["payload"]["kind"] == "late_brake"
    assert cue_frame["payload"]["corner"] == 3


def test_publish_coaching_cues_fans_out_each_advisory(monkeypatch):
    # one frame -> two advisories -> two coaching.cue frames, each carrying the same exclude.
    _reset_feed(monkeypatch)
    a = _adv(kind="late_brake", corner=3)
    b = _adv(kind="apex_deficit", corner=7, urgency="info")
    monkeypatch.setattr(server, "_observer", _FakeObserver([a, b]))
    sent = _capture_broadcast(monkeypatch)

    asyncio.run(_run_publish_cues({"type": "telemetry_tick", "payload": {}}, exclude="wsX"))

    assert len(sent) == 2
    assert sent[0][0]["payload"]["kind"] == "late_brake" and sent[0][0]["payload"]["corner"] == 3
    assert sent[1][0]["payload"]["kind"] == "apex_deficit" and sent[1][0]["payload"]["corner"] == 7
    assert sent[0][1] == "wsX" and sent[1][1] == "wsX"


def test_publish_coaching_cues_noop_without_observer(monkeypatch):
    _reset_feed(monkeypatch)
    monkeypatch.setattr(server, "_observer", None)
    sent = _capture_broadcast(monkeypatch)
    asyncio.run(_run_publish_cues({"type": "telemetry_tick", "payload": {}}, exclude=None))
    assert sent == []


def test_publish_coaching_cues_swallows_observer_error(monkeypatch):
    _reset_feed(monkeypatch)

    class _Boom:
        def observe(self, frame):
            raise RuntimeError("boom")

        def reset(self):
            pass

    monkeypatch.setattr(server, "_observer", _Boom())
    sent = _capture_broadcast(monkeypatch)
    # must not raise — the peripheral path is never broken by an observer fault
    asyncio.run(_run_publish_cues({"type": "telemetry_tick", "payload": {}}, exclude=None))
    assert sent == []


def test_publish_coaching_cues_ignores_second_producer(monkeypatch):
    # single-producer guard: a second concurrent producer is NOT fed to the single-stream observer.
    _reset_feed(monkeypatch)
    observer = _FakeObserver([_adv()])
    monkeypatch.setattr(server, "_observer", observer)
    sent = _capture_broadcast(monkeypatch)

    asyncio.run(_run_publish_cues({"type": "telemetry_tick", "payload": {}}, exclude="owner"))
    asyncio.run(_run_publish_cues({"type": "telemetry_tick", "payload": {}}, exclude="intruder"))

    assert observer.calls == 1  # only the owner's frame reached the observer
    assert len(sent) == 1
    assert server._observer_feed_peer == "owner"


def test_release_observer_feed_frees_owner_only(monkeypatch):
    _reset_feed(monkeypatch)
    monkeypatch.setattr(server, "_observer", _FakeObserver([]))
    monkeypatch.setattr(server, "_observer_feed_peer", "owner")
    server._release_observer_feed("owner")
    assert server._observer_feed_peer is None
    # releasing for a non-owner peer is a no-op
    monkeypatch.setattr(server, "_observer_feed_peer", "owner2")
    server._release_observer_feed("someone-else")
    assert server._observer_feed_peer == "owner2"


def test_wire_voice_builds_and_installs_observer_from_reference(tmp_path, monkeypatch):
    # Happy path of the real loader (#354 — replaces the removed _load_observer happy-path test):
    # a corner-bearing reference archive is read, built, and installed via set_realtime_observer.
    # This drives the file-read -> build -> install seam that the dead _load_observer test used to.
    monkeypatch.setattr(server, "_observer", None)
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    server._wire_voice(server.VoiceRuntimeConfig(reference_path=str(ref), bank_dir=None))
    assert server._observer is not None


def test_wire_voice_no_corners_reference_disables_observer(tmp_path, monkeypatch):
    # build_observer_from_reference returns None for a reference with no usable corners; _wire_voice
    # logs and leaves the observer UNINSTALLED (best-effort), never raising. The sentinel makes the
    # negative-install non-vacuous: a pre-existing observer is left untouched, not cleared/replaced.
    sentinel = object()
    monkeypatch.setattr(server, "_observer", sentinel)
    ref = tmp_path / "no_corners.json"
    ref.write_text(json.dumps({}), encoding="utf-8")
    server._wire_voice(server.VoiceRuntimeConfig(reference_path=str(ref), bank_dir=None))
    assert server._observer is sentinel


def test_wire_voice_missing_reference_is_best_effort(monkeypatch):
    # A missing/unreadable reference must NOT abort the sidecar — telemetry + haptics keep flowing
    # (#341 best-effort; the earlier fail-fast _load_observer/SystemExit contract was abandoned).
    # The sentinel proves _wire_voice neither raises nor disturbs the existing observer.
    sentinel = object()
    monkeypatch.setattr(server, "_observer", sentinel)
    server._wire_voice(
        server.VoiceRuntimeConfig(reference_path="does-not-exist-9f3a.json", bank_dir=None)
    )
    assert server._observer is sentinel


def test_wire_voice_tts_installs_pyttsx3_adapter(monkeypatch):
    import tools.ai_sidecar.voice.client as voice_client

    spoken: list[tuple[str, str]] = []
    seen: dict[str, float | int] = {}
    server.set_voice_coach(None)

    def fake_speaker(*, base_rate: int, base_volume: float):
        seen["rate"] = base_rate
        seen["volume"] = base_volume

        def speak(text: str, register: str = "calm") -> None:
            spoken.append((text, register))

        return speak

    monkeypatch.setenv("AC_COPILOT_VOICE_RATE", "260")
    monkeypatch.setenv("AC_COPILOT_VOICE_VOLUME", "0.8")
    monkeypatch.setattr(voice_client, "_pyttsx3_speaker", fake_speaker)

    try:
        server._wire_voice(
            server.VoiceRuntimeConfig(reference_path=None, bank_dir=None, tts_enabled=True)
        )
        assert server._voice_coach is not None
        server._voice_coach.subscribe(_adv(kind="apex_deficit", corner=1, urgency="info"))
    finally:
        server.set_voice_coach(None)

    assert spoken == [("More entry speed, Turn 2.", "calm")]
    assert seen == {"rate": 260, "volume": 0.8}


def test_wire_voice_bank_uses_env_audio_routing(monkeypatch):
    from tools.ai_sidecar.voice import engine

    seen: dict[str, object] = {}

    class _Coach:
        enabled = True
        disabled_reason = ""

        def start(self) -> None:
            seen["started"] = True

    def fake_from_bank(bank_dir, config, *, backend):  # noqa: ANN001
        seen["bank_dir"] = bank_dir
        seen["backend"] = backend
        seen["device_name"] = config.device_name
        seen["host_api"] = config.host_api
        seen["verbosity"] = config.verbosity.name.lower()
        return _Coach()

    server.set_voice_coach(None)
    monkeypatch.setenv("AC_COPILOT_VOICE_BACKEND", "sounddevice")
    monkeypatch.setenv("AC_COPILOT_VOICE_DEVICE", "USB Sound Device")
    monkeypatch.setenv("AC_COPILOT_VOICE_HOST_API", "Windows DirectSound")
    monkeypatch.setenv("AC_COPILOT_VOICE_VERBOSITY", "high")
    monkeypatch.setattr(engine.VoiceCoach, "from_bank", fake_from_bank)

    try:
        server._wire_voice(server.VoiceRuntimeConfig(reference_path=None, bank_dir="bank-dir"))
        assert server._voice_coach is not None
    finally:
        server.set_voice_coach(None)

    assert seen == {
        "bank_dir": "bank-dir",
        "backend": "sounddevice",
        "device_name": "USB Sound Device",
        "host_api": "Windows DirectSound",
        "verbosity": "high",
        "started": True,
    }


class _FakeWS:
    """Minimal loopback websocket stand-in for handler-level tests."""

    def __init__(self, host="127.0.0.1", port=5000):
        self.remote_address = (host, port)
        self.sent: list[str] = []

    async def send(self, payload):
        self.sent.append(payload)


def _full_tick_payload():
    return {
        "speed_kmh": 100.0,
        "rpm": 6000,
        "throttle": 0.5,
        "brake": 0.0,
        "steer": 0.0,
        "gear": 3,
        "lat_g": 0.1,
        "long_g": -0.1,
        "spline": 0.5,
    }


def test_publish_coaching_cues_rate_limited_at_20hz(monkeypatch):
    _reset_feed(monkeypatch)
    observer = _FakeObserver([_adv()])
    monkeypatch.setattr(server, "_observer", observer)
    sent = _capture_broadcast(monkeypatch)
    frame = {"type": "telemetry_tick", "payload": {"spline": 0.5, "speed_kmh": 100}}
    now = [0.0]
    monkeypatch.setattr(
        server, "_peripheral_rate_limiter", server._RateLimiter(clock=lambda: now[0])
    )

    asyncio.run(_run_publish_cues(frame, exclude="ws-1"))
    now[0] += 0.01
    asyncio.run(_run_publish_cues(frame, exclude="ws-1"))

    assert observer.calls == 1
    assert len(sent) == 1


def test_handler_routes_telemetry_tick_into_observer(monkeypatch):
    # Locks the seam: a real telemetry_tick through _handle_external_frame reaches the observer
    # and broadcasts a coaching.cue excluding the producer.
    _reset_feed(monkeypatch)
    observer = _FakeObserver([_adv()])
    monkeypatch.setattr(server, "_observer", observer)
    sent = _capture_broadcast(monkeypatch)
    ws = _FakeWS()
    monkeypatch.setattr(server, "_external_peers", {ws})
    monkeypatch.setattr(server, "_external_peer_classes", {ws: "physical"})

    frame = {"v": 1, "type": "telemetry_tick", "payload": _full_tick_payload()}

    async def _run() -> None:
        await server._handle_external_frame(ws, frame)
        pending = list(server._background_tasks)
        if pending:
            await asyncio.gather(*pending)

    asyncio.run(_run())

    assert observer.calls == 1
    assert observer.seen[0] is frame
    assert len(sent) == 1
    assert sent[0][0]["topic"] == TOPIC_COACHING_CUE
    assert sent[0][1] is ws  # producer excluded from its own cue fan-out
