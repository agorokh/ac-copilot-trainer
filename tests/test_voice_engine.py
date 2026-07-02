"""Tests for the top-level VoiceCoach seam (tools.ai_sidecar.voice.engine).

Covers the asserted advisory-emit -> dispatch latency (the issue #340 latency criterion, measured on
the real worker thread), and graceful degradation when the bank cannot be trusted.
"""

from __future__ import annotations

import json
import time

from _voice_support import make_advisory

from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank
from tools.ai_sidecar.voice.config import VoiceConfig
from tools.ai_sidecar.voice.engine import VoiceCoach
from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME
from tools.ai_sidecar.voice.playback import RecordingPlayback


def _baked(tmp_path):
    bake_bank(tmp_path, ToneBackend())
    return tmp_path


def test_coach_speaks_advisory_and_meets_latency_budget(tmp_path) -> None:
    pb = RecordingPlayback()
    coach = VoiceCoach.from_bank(_baked(tmp_path), VoiceConfig(), playback=pb)
    assert coach.enabled
    coach.start()
    try:
        t0 = time.perf_counter()
        coach.subscribe(make_advisory(kind="late_brake", urgency="act", corner=2))
        deadline = t0 + 2.0
        while not pb.played and time.perf_counter() < deadline:
            time.sleep(0.002)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        coach.stop()
    assert pb.played, "advisory was never dispatched to playback"
    # act cues are terse/corner-less; a late_brake act cue resolves to the generic urgent clip.
    assert pb.played[-1].clip_id == "late_brake.act.urgent.generic"
    # advisory-emit -> first-sample dispatch budget (target <= ~150 ms end-to-end). The
    # clip-playback
    # component is the pre-warmed audio stream, measured on-rig in the deferred live verification.
    assert elapsed_ms < 150.0, f"dispatch latency {elapsed_ms:.1f} ms exceeded 150 ms"


def test_disabled_when_manifest_missing(tmp_path) -> None:
    coach = VoiceCoach.from_bank(tmp_path, VoiceConfig(), playback=RecordingPlayback())
    assert not coach.enabled
    assert "manifest" in coach.disabled_reason.lower()
    # subscribe must be a safe no-op (never crash) when disabled
    coach.subscribe(make_advisory())
    coach.start()
    coach.stop()


def test_disabled_on_vocabulary_drift(tmp_path) -> None:
    _baked(tmp_path)
    mfp = tmp_path / MANIFEST_FILENAME
    data = json.loads(mfp.read_text())
    data["vocabulary_hash"] = "deadbeef" * 8  # wording changed but bank not re-baked
    mfp.write_text(json.dumps(data))
    pb = RecordingPlayback()
    coach = VoiceCoach.from_bank(tmp_path, VoiceConfig(), playback=pb)
    assert not coach.enabled
    coach.subscribe(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert pb.played == []  # never plays a possibly-wrong clip


def test_disabled_on_signature_drift(tmp_path) -> None:
    # Issue #438: persona/intensity-chain drift keeps vocabulary_hash constant (wording identical),
    # so the voice_signature suffix gate is what must disable the coach.
    _baked(tmp_path)
    mfp = tmp_path / MANIFEST_FILENAME
    data = json.loads(mfp.read_text())
    # Older prosody chain, same persona/intensity/wording — the sharpest form of the gap.
    data["voice_signature"] = "tone-v3+race-engineer-original-v1+prosody1+intensity3"
    mfp.write_text(json.dumps(data))
    pb = RecordingPlayback()
    coach = VoiceCoach.from_bank(tmp_path, VoiceConfig(), playback=pb)
    assert not coach.enabled
    assert "voice_signature" in coach.disabled_reason
    coach.subscribe(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert pb.played == []  # never plays clips whose baked persona/tone is stale


def test_disabled_coach_factory() -> None:
    coach = VoiceCoach.disabled("test reason")
    assert not coach.enabled
    assert coach.disabled_reason == "test reason"
    coach.subscribe(make_advisory())  # no-op, no crash


def test_build_playback_falls_back_to_sounddevice_when_rtmixer_missing(
    monkeypatch, tmp_path
) -> None:
    """rtmixer absent must NOT silence the coach — it degrades to the sounddevice backend.

    Reproduces the rig log `ModuleNotFoundError: No module named 'rtmixer'` → "coach disabled".
    Fakes the audio classes so the test needs no numpy / PortAudio / device.
    """
    import tools.ai_sidecar.voice.playback as pb_mod

    class _FakeBank:
        @staticmethod
        def from_manifest(_manifest, _bank_dir):
            return object()

    constructed: dict[str, object] = {}

    class _FakeRtMixer:
        def __init__(self, *_args, **_kwargs):
            raise ModuleNotFoundError("No module named 'rtmixer'")

    class _FakeSoundDevice:
        def __init__(self, _bank, *, device_name, host_api, **_kwargs):
            constructed["device_name"] = device_name
            constructed["host_api"] = host_api

    monkeypatch.setattr(pb_mod, "Bank", _FakeBank)
    monkeypatch.setattr(pb_mod, "RtMixerPlayback", _FakeRtMixer)
    monkeypatch.setattr(pb_mod, "SoundDevicePlayback", _FakeSoundDevice)

    playback = VoiceCoach._build_playback(
        object(), tmp_path, VoiceConfig(device_name="Headset", host_api="WASAPI"), "rtmixer"
    )

    assert isinstance(playback, _FakeSoundDevice)
    assert constructed == {"device_name": "Headset", "host_api": "WASAPI"}


def test_build_playback_disables_when_no_backend_importable(monkeypatch, tmp_path) -> None:
    """If neither rtmixer nor sounddevice imports, disable (None) rather than crash."""
    import tools.ai_sidecar.voice.playback as pb_mod

    class _FakeBank:
        @staticmethod
        def from_manifest(_manifest, _bank_dir):
            return object()

    class _FakeRtMixer:
        def __init__(self, *_args, **_kwargs):
            raise ModuleNotFoundError("No module named 'rtmixer'")

    class _FakeSoundDevice:
        def __init__(self, *_args, **_kwargs):
            raise ModuleNotFoundError("No module named 'sounddevice'")

    monkeypatch.setattr(pb_mod, "Bank", _FakeBank)
    monkeypatch.setattr(pb_mod, "RtMixerPlayback", _FakeRtMixer)
    monkeypatch.setattr(pb_mod, "SoundDevicePlayback", _FakeSoundDevice)

    assert VoiceCoach._build_playback(object(), tmp_path, VoiceConfig(), "rtmixer") is None


def test_build_playback_device_fault_still_disables_without_fallback(monkeypatch, tmp_path) -> None:
    """A real device/driver fault (not a missing module) disables — no silent sounddevice retry.

    The same fault would recur on sounddevice, and staying silent beats routing onto the wrong
    endpoint. Only a *missing module* triggers the fallback.
    """
    import tools.ai_sidecar.voice.playback as pb_mod

    class _FakeBank:
        @staticmethod
        def from_manifest(_manifest, _bank_dir):
            return object()

    sd_calls: list[object] = []

    class _FakeRtMixer:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("PortAudio device error -9996")

    class _FakeSoundDevice:
        def __init__(self, *_args, **_kwargs):
            sd_calls.append(object())

    monkeypatch.setattr(pb_mod, "Bank", _FakeBank)
    monkeypatch.setattr(pb_mod, "RtMixerPlayback", _FakeRtMixer)
    monkeypatch.setattr(pb_mod, "SoundDevicePlayback", _FakeSoundDevice)

    assert VoiceCoach._build_playback(object(), tmp_path, VoiceConfig(), "rtmixer") is None
    assert sd_calls == []  # device fault must not fall through to sounddevice
