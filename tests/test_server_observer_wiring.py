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
    server.set_race_manager(server.RaceManagementObserver())
    server._peripheral_rate_limiter.reset()
    server._background_tasks.clear()


def test_public_voice_status_exposes_frontier_and_redacts_paths(monkeypatch):
    class _Coach:
        frontier = {
            "configured": True,
            "active": False,
            "source": "reference",
            "reason": r"alien_load_failed: C:\Users\Jane Doe\Documents\alien.json",
            "corners": [],
        }

    monkeypatch.setattr(server, "_coach_runtime", _Coach())
    status = server.public_voice_runtime_status()

    assert status["coach_frontier"]["source"] == "reference"
    assert status["coach_frontier"]["reason"] == "alien_frontier_error"


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


def test_publish_coaching_cues_fans_out_race_management_without_corner_observer(monkeypatch):
    _reset_feed(monkeypatch)
    race = _FakeObserver([_adv(kind="fuel_save", corner=-1, urgency="act")])
    monkeypatch.setattr(server, "_observer", None)
    server.set_race_manager(race)
    sent = _capture_broadcast(monkeypatch)
    try:
        asyncio.run(
            _run_publish_cues(
                {"type": "telemetry_tick", "payload": {"fuel_l": 8.0, "lap": 2}},
                exclude="ws-1",
            )
        )
    finally:
        server.set_race_manager(server.RaceManagementObserver())

    assert race.calls == 1
    assert len(sent) == 1
    assert sent[0][0]["payload"]["kind"] == "fuel_save"


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
    status = server.voice_runtime_status()
    assert status["state"] == "disabled"
    assert status["disabled_reason"] == "reference archive has no usable corners"
    assert str(ref) not in str(status["disabled_reason"])


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
    status = server.voice_runtime_status()
    assert status["state"] == "disabled"
    assert "failed to load reference" in str(status["disabled_reason"])
    assert "does-not-exist-9f3a.json" not in str(status["disabled_reason"])


def test_wire_voice_bank_without_reference_reports_disabled(monkeypatch):
    server.set_voice_coach(None)
    monkeypatch.setattr(server, "_observer", None)

    server._wire_voice(server.VoiceRuntimeConfig(reference_path=None, bank_dir="bank-dir"))

    status = server.voice_runtime_status()
    assert status["configured"] is True
    assert status["enabled"] is False
    assert status["state"] == "disabled"
    assert "REFERENCE_ARCHIVE" in str(status["disabled_reason"])


def test_wire_voice_tts_without_reference_reports_disabled(monkeypatch):
    server.set_voice_coach(None)
    monkeypatch.setattr(server, "_observer", None)

    server._wire_voice(
        server.VoiceRuntimeConfig(reference_path=None, bank_dir=None, tts_enabled=True)
    )

    status = server.voice_runtime_status()
    assert status["configured"] is True
    assert status["enabled"] is False
    assert status["state"] == "disabled"
    assert status["backend"] == "pyttsx3"
    assert "REFERENCE_ARCHIVE" in str(status["disabled_reason"])


def test_voice_runtime_status_replaces_snapshot_atomically():
    server.set_voice_runtime_status(configured=True, state="initializing")
    prior = server.voice_runtime_status()

    server.set_voice_runtime_status()

    assert prior["configured"] is True
    assert prior["state"] == "initializing"
    assert server.voice_runtime_status()["state"] == "skipped"


def test_wire_voice_tts_installs_pyttsx3_adapter(tmp_path, monkeypatch):
    import tools.ai_sidecar.voice.client as voice_client

    spoken: list[tuple[str, str]] = []
    seen: dict[str, float | int] = {}
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    monkeypatch.setattr(server, "_observer", None)
    server.set_voice_coach(None)

    def fake_speaker(
        *,
        base_rate: int,
        base_volume: float,
        require_opt_in: bool,
        startup_timeout_s: float | None,
    ):
        seen["rate"] = base_rate
        seen["volume"] = base_volume
        seen["require_opt_in"] = int(require_opt_in)
        seen["startup_timeout_s"] = startup_timeout_s

        def speak(text: str, register: str = "calm") -> None:
            spoken.append((text, register))

        return speak

    monkeypatch.setenv("AC_COPILOT_VOICE_RATE", "260")
    monkeypatch.setenv("AC_COPILOT_VOICE_VOLUME", "0.8")
    monkeypatch.setattr(voice_client, "_pyttsx3_speaker", fake_speaker)

    try:
        server._wire_voice(
            server.VoiceRuntimeConfig(reference_path=str(ref), bank_dir=None, tts_enabled=True)
        )
        assert server._voice_coach is not None
        server._voice_coach.subscribe(_adv(kind="apex_deficit", corner=1, urgency="info"))
        assert server.voice_runtime_status()["state"] == "tts"
    finally:
        server.set_voice_coach(None)

    assert spoken == [("More entry speed, Turn 2.", "calm")]
    assert seen == {"rate": 260, "volume": 0.8, "require_opt_in": 0, "startup_timeout_s": 2.0}


def test_wire_voice_bank_uses_env_audio_routing(tmp_path, monkeypatch):
    from tools.ai_sidecar.voice import engine

    seen: dict[str, object] = {}
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps(_corner_archive()), encoding="utf-8")

    class _Coach:
        enabled = True
        disabled_reason = ""
        playback_details = {
            "device_index": 16,
            "device_name": "5.1 Speakers (USB Sound Device)",
            "host_api": "Windows WASAPI",
            "max_output_channels": 6,
            "bank_channels": 1,
            "stream_channels": 6,
            "channel_map": [3],
        }

        def start(self) -> None:
            seen["started"] = True

    def fake_from_bank(bank_dir, config, *, backend, dispatch_listener=None):  # noqa: ANN001
        seen["bank_dir"] = bank_dir
        seen["backend"] = backend
        seen["device_name"] = config.device_name
        seen["host_api"] = config.host_api
        seen["verbosity"] = config.verbosity.name.lower()
        # Issue #511 Part D: the server wires its dispatch listener so remote voice
        # endpoints receive coaching.voice broadcasts.
        seen["dispatch_listener"] = dispatch_listener is server._on_voice_dispatch
        return _Coach()

    server.set_voice_coach(None)
    monkeypatch.setenv("AC_COPILOT_VOICE_BACKEND", "sounddevice")
    monkeypatch.setenv("AC_COPILOT_VOICE_DEVICE", "USB Sound Device")
    monkeypatch.setenv("AC_COPILOT_VOICE_HOST_API", "Windows DirectSound")
    monkeypatch.setenv("AC_COPILOT_VOICE_VERBOSITY", "high")
    monkeypatch.setattr(engine.VoiceCoach, "from_bank", fake_from_bank)
    monkeypatch.setattr(server, "_observer", None)

    try:
        server._wire_voice(server.VoiceRuntimeConfig(reference_path=str(ref), bank_dir="bank-dir"))
        assert server._voice_coach is not None
        status = server.voice_runtime_status()
        assert status["state"] == "enabled"
        assert status["device_name"] == "5.1 Speakers (USB Sound Device)"
        assert status["host_api"] == "Windows WASAPI"
        assert status["bank_channels"] == 1
        assert status["max_output_channels"] == 6
        assert status["stream_channels"] == 6
        assert status["channel_map"] == [3]
    finally:
        server.set_voice_coach(None)

    assert seen == {
        "bank_dir": "bank-dir",
        "backend": "sounddevice",
        "device_name": "USB Sound Device",
        "host_api": "Windows DirectSound",
        "verbosity": "high",
        "dispatch_listener": True,
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


# ---- issue #522 part 2: lap_complete -> per-driver brake-mark calibration --------------------


def _write_lap_archive(tmp_path, archive: dict, name: str = "lap_0001.json") -> str:
    laps = tmp_path / "journal" / "laps"
    laps.mkdir(parents=True, exist_ok=True)
    p = laps / name
    p.write_text(json.dumps(archive), encoding="utf-8")
    return str(p)


def _real_observer():
    from tools.ai_sidecar.realtime_observer import build_observer_from_reference

    obs = build_observer_from_reference(_corner_archive())
    assert obs is not None
    return obs


def test_calibrate_brake_marks_from_lap_updates_observer(tmp_path, monkeypatch):
    obs = _real_observer()
    monkeypatch.setattr(server, "_observer", obs)
    monkeypatch.setattr(
        server, "_recent_brake_cal_keys", server._recent_brake_cal_keys.__class__(maxlen=8)
    )
    # calibration is core telemetry learning, deliberately INDEPENDENT of the optional LLM
    # debrief pipeline: it must fold with the debrief feature disabled (PR #525 review).
    monkeypatch.delenv("AC_COPILOT_OLLAMA_ENABLE", raising=False)
    path = _write_lap_archive(tmp_path, _corner_archive())
    asyncio.run(server._calibrate_brake_marks_from_lap({"archivePath": path, "lap": 3}))
    assert obs._driver_marks, "the driver's own lap must calibrate at least one zone"
    laps_folded = next(iter(obs._driver_marks.values()))[1]
    # the brainOnly re-send of the SAME lap must not double-weight the EMA
    asyncio.run(server._calibrate_brake_marks_from_lap({"archivePath": path, "lap": 3}))
    assert next(iter(obs._driver_marks.values()))[1] == laps_folded


def test_calibration_skips_explicitly_invalid_lap(tmp_path, monkeypatch):
    obs = _real_observer()
    monkeypatch.setattr(server, "_observer", obs)
    monkeypatch.setattr(
        server, "_recent_brake_cal_keys", server._recent_brake_cal_keys.__class__(maxlen=8)
    )
    archive = _corner_archive()
    archive["lap"]["is_valid"] = False  # a cut lap's brake points are not calibration data
    path = _write_lap_archive(tmp_path, archive)
    asyncio.run(server._calibrate_brake_marks_from_lap({"archivePath": path, "lap": 4}))
    assert obs._driver_marks == {}


def test_calibration_env_kill_switch(monkeypatch):
    monkeypatch.setenv("AC_COPILOT_BRAKE_CAL", "0")
    assert server._brake_calibration_enabled() is False
    monkeypatch.delenv("AC_COPILOT_BRAKE_CAL")
    assert server._brake_calibration_enabled() is True


def test_unresolvable_frame_does_not_reserve_the_calibration_key(tmp_path, monkeypatch):
    """PR #525 review: a lap_complete with neither an inline trace nor an archivePath must not
    reserve the dedup key — the archive-backed re-send of the SAME lap must still calibrate."""
    obs = _real_observer()
    monkeypatch.setattr(server, "_observer", obs)
    monkeypatch.setattr(
        server, "_recent_brake_cal_keys", server._recent_brake_cal_keys.__class__(maxlen=8)
    )
    # plain frame: same lap identity, nothing loadable -> returns without reserving
    asyncio.run(server._calibrate_brake_marks_from_lap({"lap": 3, "lapTimeMs": 133498}))
    assert len(server._recent_brake_cal_keys) == 0
    assert obs._driver_marks == {}
    # archive-backed re-send of the same physical lap -> calibrates
    path = _write_lap_archive(tmp_path, _corner_archive())
    asyncio.run(
        server._calibrate_brake_marks_from_lap({"lap": 3, "lapTimeMs": 133498, "archivePath": path})
    )
    assert obs._driver_marks, "the archive-backed re-send must not be starved by the empty frame"


def test_late_resend_after_a_newer_lap_is_still_deduped(tmp_path, monkeypatch):
    """PR #525 review: the dedup memory is a bounded set of recent lap identities, not a single
    slot — a brainOnly re-send of lap N arriving AFTER lap N+1 folded must not refold lap N."""
    obs = _real_observer()
    monkeypatch.setattr(server, "_observer", obs)
    monkeypatch.setattr(
        server, "_recent_brake_cal_keys", server._recent_brake_cal_keys.__class__(maxlen=8)
    )
    path_n = _write_lap_archive(tmp_path, _corner_archive(), name="lap_0003.json")
    path_n1 = _write_lap_archive(tmp_path, _corner_archive(), name="lap_0004.json")
    asyncio.run(
        server._calibrate_brake_marks_from_lap(
            {"lap": 3, "lapTimeMs": 133498, "archivePath": path_n}
        )
    )
    laps_folded = next(iter(obs._driver_marks.values()))[1]
    asyncio.run(
        server._calibrate_brake_marks_from_lap(
            {"lap": 4, "lapTimeMs": 132513, "archivePath": path_n1}
        )
    )
    after_lap4 = next(iter(obs._driver_marks.values()))[1]
    # the LATE re-send of lap 3 (same identity) must be a no-op
    asyncio.run(
        server._calibrate_brake_marks_from_lap(
            {"lap": 3, "lapTimeMs": 133498, "archivePath": path_n}
        )
    )
    assert next(iter(obs._driver_marks.values()))[1] == after_lap4
    assert after_lap4 == laps_folded + 1


def test_calibration_inactive_when_coach_v2_owns_the_cue_path(monkeypatch):
    """PR #525 review: with coach v2 routing live telemetry, folding laps into the LEGACY
    observer would log 'calibrated' with zero effect on the spoken cues — the task must not
    be scheduled at all."""
    monkeypatch.setattr(server, "_observer", _real_observer())
    monkeypatch.setattr(server, "_coach_runtime", object())
    monkeypatch.delenv("AC_COPILOT_BRAKE_CAL", raising=False)
    assert server._brake_calibration_active() is False
    monkeypatch.setattr(server, "_coach_runtime", None)
    assert server._brake_calibration_active() is True


# ---------------------------------------------------------------- #531 Part D/E server wiring
def test_cue_payload_carries_audio_routing_by_register(monkeypatch):
    """#531 Part E: urgent/critical cues route authoritative_pc; calm/alert tablet_native."""
    _reset_feed(monkeypatch)
    server._race_status.reset()
    advisories = [
        Advisory(
            kind="late_brake",
            corner=1,
            spline=0.1,
            urgency="act",
            message="m",
            detail={},
            register="urgent",
        ),
        Advisory(
            kind="fuel_status",
            corner=-1,
            spline=0.1,
            urgency="info",
            message="m",
            detail={},
            register="calm",
        ),
    ]
    observer = _FakeObserver(advisories)
    monkeypatch.setattr(server, "_observer", observer)
    monkeypatch.setattr(server, "_shift_observer", None)
    sent = _capture_broadcast(monkeypatch)

    frame = {"type": "telemetry_tick", "payload": {"spline": 0.1, "speed_kmh": 100}}
    asyncio.run(_run_publish_cues(frame, exclude="ws-1"))

    routings = {f["payload"]["kind"]: f["payload"]["audio_routing"] for f, _ in sent}
    assert routings == {"late_brake": "authoritative_pc", "fuel_status": "tablet_native"}


def test_shift_observer_cues_broadcast_but_never_reach_voice(monkeypatch):
    """#531 Part E: upshift/downshift fan out on coaching.cue, but are NOT submitted to the
    in-process voice coach (no baked clips — the resolver would warn-and-drop per straight)."""
    _reset_feed(monkeypatch)
    server._race_status.reset()
    monkeypatch.setattr(server, "_observer", None)
    server.set_race_manager(None)
    shift = _FakeObserver(
        [
            Advisory(
                kind="upshift",
                corner=-1,
                spline=0.2,
                urgency="act",
                message="Shift up.",
                detail={},
                register="calm",
            )
        ]
    )
    monkeypatch.setattr(server, "_shift_observer", shift)

    class _RecordingCoach:
        def __init__(self):
            self.seen = []

        def subscribe(self, advisory):
            self.seen.append(advisory)

    coach = _RecordingCoach()
    monkeypatch.setattr(server, "_voice_coach", coach)
    sent = _capture_broadcast(monkeypatch)

    frame = {"type": "telemetry_tick", "payload": {"rpm": 8800, "gear": 3, "throttle": 0.9}}
    asyncio.run(_run_publish_cues(frame, exclude="ws-1"))

    kinds = [f["payload"]["kind"] for f, _ in sent if f.get("topic") == "coaching.cue"]
    assert kinds == ["upshift"]
    assert sent[0][0]["payload"]["audio_routing"] == "tablet_native"
    assert coach.seen == []  # not in the voice vocabulary -> never submitted


def test_vocabulary_kinds_still_reach_voice(monkeypatch):
    _reset_feed(monkeypatch)
    server._race_status.reset()
    monkeypatch.setattr(server, "_observer", _FakeObserver([_adv(kind="late_brake")]))
    monkeypatch.setattr(server, "_shift_observer", None)

    class _RecordingCoach:
        def __init__(self):
            self.seen = []

        def subscribe(self, advisory):
            self.seen.append(advisory)

    coach = _RecordingCoach()
    monkeypatch.setattr(server, "_voice_coach", coach)
    _capture_broadcast(monkeypatch)

    frame = {"type": "telemetry_tick", "payload": {"spline": 0.5, "speed_kmh": 100}}
    asyncio.run(_run_publish_cues(frame, exclude="ws-1"))
    assert [a.kind for a in coach.seen] == ["late_brake"]


def test_race_status_published_from_tick_fuel_change_gated(monkeypatch):
    """#531 Part D remainder: the tick path publishes race.status once per change, quiet on
    identical payloads."""
    _reset_feed(monkeypatch)
    server._race_status.reset()
    monkeypatch.setattr(server, "_observer", None)
    monkeypatch.setattr(server, "_shift_observer", None)
    sent = _capture_broadcast(monkeypatch)

    def _tick_frame(lap, fuel):
        return {"type": "telemetry_tick", "payload": {"lap": lap, "fuel_l": fuel}}

    asyncio.run(_run_publish_cues(_tick_frame(0, 10.0), exclude="ws-1"))
    server._peripheral_rate_limiter.reset()  # bypass the 1 Hz cap for the test
    asyncio.run(_run_publish_cues(_tick_frame(1, 8.0), exclude="ws-1"))
    server._peripheral_rate_limiter.reset()
    asyncio.run(_run_publish_cues(_tick_frame(1, 8.0), exclude="ws-1"))

    status_frames = [f for f, _ in sent if f.get("topic") == "race.status"]
    assert len(status_frames) == 1
    payload = status_frames[0]["payload"]
    assert payload["fuel_per_lap_l"] == 2.0
    assert payload["laps_remaining"] == 4.0
    assert status_frames[0]["source"] == "sidecar.race_status"


def test_relay_taps_feed_race_status_predicted_lap(monkeypatch):
    """The Lua delta/lap topics flowing through the relay feed the predicted-lap fusion —
    anchored on the delta's own reference baseline, not the stint best."""
    server._race_status.reset()
    server._race_status.note_lap({"lap": 3, "best_lap_ms": 112000.0})
    server._race_status.note_delta({"delta_s": 0.5, "reference_lap_ms": 110000.0})
    snap = server._race_status.snapshot()
    assert snap["predicted_lap_ms"] == 110500


def test_release_observer_feed_resets_shift_and_race_status(monkeypatch):
    """A producer swap must not inherit the previous stream's armed gears or fuel/delta
    fusion (Codex on PR #615)."""
    monkeypatch.setattr(server, "_observer_feed_peer", "ws-owner")
    monkeypatch.setattr(server, "_observer", None)
    monkeypatch.setattr(server, "_coach_runtime", None)
    server.set_race_manager(None)

    class _Resettable:
        def __init__(self):
            self.resets = 0

        def reset(self):
            self.resets += 1

    shift = _Resettable()
    monkeypatch.setattr(server, "_shift_observer", shift)
    server._race_status.reset()
    server._race_status.note_fuel({"fuel_l": 10.0, "fuel_per_lap_l": 2.0, "laps_remaining": 5.0})

    server._release_observer_feed("ws-owner")
    assert shift.resets == 1
    assert server._race_status.snapshot() is None


def test_wire_voice_builds_track_map_frame(tmp_path, monkeypatch):
    """#531 Part F: wiring a corner-bearing reference also builds the track.map frame the
    subscribe replay path serves to late subscribers."""
    monkeypatch.setattr(server, "_observer", None)
    monkeypatch.setattr(server, "_track_map_frame", None)
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    server._wire_voice(server.VoiceRuntimeConfig(reference_path=str(ref), bank_dir=None))
    frame = server._track_map_frame
    assert frame is not None
    assert frame["topic"] == "track.map"
    assert len(frame["payload"]["outline"]) >= 8
    assert frame["payload"]["corners"][0]["label"] == "T1"


def test_runtime_rewire_broadcasts_fresh_track_map(tmp_path, monkeypatch):
    """#622 advisory: if voice/reference wiring moves in-process at runtime, connected
    subscribers receive the rebuilt map instead of waiting for another subscribe."""
    sent = _capture_broadcast(monkeypatch)
    monkeypatch.setattr(server, "_observer", None)
    monkeypatch.setattr(server, "_track_map_frame", None)
    server._background_tasks.clear()
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps(_corner_archive()), encoding="utf-8")

    async def _rewire():
        monkeypatch.setattr(server, "_event_loop", asyncio.get_running_loop())
        server._wire_voice(server.VoiceRuntimeConfig(reference_path=str(ref), bank_dir=None))
        await asyncio.sleep(0)
        pending = list(server._background_tasks)
        if pending:
            await asyncio.gather(*pending)

    asyncio.run(_rewire())
    assert len(sent) == 1
    frame, exclude = sent[0]
    assert exclude is None
    assert frame["topic"] == "track.map"
    assert frame == server._track_map_frame


def test_rewire_without_geometry_clears_stale_track_map(tmp_path, monkeypatch):
    """A re-wire whose reference cannot supply geometry must not leave the previous
    track's map for late subscribers (Codex on PR #618)."""
    monkeypatch.setattr(server, "_observer", None)
    monkeypatch.setattr(server, "_track_map_frame", {"topic": "track.map", "payload": {}})
    ref = tmp_path / "no_geometry.json"
    ref.write_text(json.dumps({}), encoding="utf-8")
    server._wire_voice(server.VoiceRuntimeConfig(reference_path=str(ref), bank_dir=None))
    assert server._track_map_frame is None
