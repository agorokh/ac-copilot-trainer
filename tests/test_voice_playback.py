"""Tests for playback device resolution + the recording double (no audio hardware).

The real audio backends lazy-import numpy/sounddevice/rtmixer and are not exercised on CI, but the
device resolver is a pure function over a device table, so the "pin by name + host-API, never route
onto the haptic USB-DAC" criterion is fully unit-tested here.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from _voice_support import FakeClock, build_manifest, make_advisory

from tools.ai_sidecar.voice.playback import (
    Bank,
    DeviceResolutionError,
    RecordingPlayback,
    RtMixerPlayback,
    _TimedCurrent,
    resolve_output_device,
)
from tools.ai_sidecar.voice.resolver import Resolver

_DEVICES = [
    {"name": "Speakers (Realtek)", "max_output_channels": 2, "hostapi": 0},
    {"name": "Haptic USB-DAC", "max_output_channels": 2, "hostapi": 0},
    {"name": "Gaming Headset", "max_output_channels": 2, "hostapi": 1},  # WASAPI
    {"name": "Gaming Headset", "max_output_channels": 2, "hostapi": 0},  # MME, same name
    {"name": "Studio Microphone", "max_output_channels": 0, "hostapi": 1},  # input only
]
_HOST_APIS = [{"name": "MME"}, {"name": "Windows WASAPI"}]


def test_resolve_pins_by_name_and_host_api() -> None:
    idx = resolve_output_device("Headset", "WASAPI", devices=_DEVICES, host_apis=_HOST_APIS)
    assert idx == 2  # the WASAPI headset, not the MME duplicate


def test_resolve_never_routes_onto_haptic_dac() -> None:
    idx = resolve_output_device("Headset", None, devices=_DEVICES, host_apis=_HOST_APIS)
    assert "haptic" not in _DEVICES[idx]["name"].lower()


def test_resolve_raises_when_no_match() -> None:
    with pytest.raises(DeviceResolutionError):
        resolve_output_device("Nonexistent", None, devices=_DEVICES, host_apis=_HOST_APIS)


def test_resolve_requires_a_name() -> None:
    with pytest.raises(DeviceResolutionError):
        resolve_output_device(None, None, devices=_DEVICES, host_apis=_HOST_APIS)
    with pytest.raises(DeviceResolutionError):
        resolve_output_device("   ", None, devices=_DEVICES, host_apis=_HOST_APIS)


def test_resolve_ignores_input_only_devices() -> None:
    # "Microphone" has no output channels → not a candidate, even by exact name.
    with pytest.raises(DeviceResolutionError):
        resolve_output_device("Microphone", None, devices=_DEVICES, host_apis=_HOST_APIS)


def test_resolve_rejects_wrong_host_api() -> None:
    # Headset exists, but not on a host-API whose name contains "ASIO".
    with pytest.raises(DeviceResolutionError):
        resolve_output_device("Headset", "ASIO", devices=_DEVICES, host_apis=_HOST_APIS)


def test_recording_playback_tracks_current() -> None:
    pb = RecordingPlayback()
    r = Resolver(build_manifest())
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert pb.current is None
    pb.play(utt)
    assert pb.current is utt
    assert pb.played == [utt]
    pb.finish()
    assert pb.current is None  # channel free, but not counted as a cancel
    assert pb.cancelled == []
    pb.play(utt)
    pb.cancel()
    assert pb.current is None
    assert pb.cancelled == [utt]


def test_timed_current_frees_channel_after_estimated_duration() -> None:
    # Qodo finding #2: the sounddevice fallback must free the channel when a clip naturally
    # finishes, or the scheduler treats it as perpetually busy and drops every later cue.
    clock = FakeClock()
    tc = _TimedCurrent(clock=clock)
    r = Resolver(build_manifest())
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert tc.current is None
    tc.set(utt, duration_s=0.5)
    assert tc.current is utt  # still sounding
    clock.advance(0.4)
    assert tc.current is utt  # mid-clip
    clock.advance(0.2)  # past the estimated end (0.6 > 0.5)
    assert tc.current is None  # channel freed automatically
    # cancel/clear frees immediately
    tc.set(utt, duration_s=10.0)
    tc.clear()
    assert tc.current is None


def test_rtmixer_playback_frees_channel_by_clip_duration(monkeypatch) -> None:
    np = pytest.importorskip("numpy")
    clock = FakeClock()
    resolver = Resolver(build_manifest())
    utt = resolver.resolve(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert utt is not None
    bank = Bank(samplerate=10, clips={utt.clip_id: np.zeros(5, dtype=np.float32)})
    actions: list[object] = []

    class _Mixer:
        def __init__(self, **kwargs) -> None:
            assert kwargs["device"] == 0
            assert kwargs["samplerate"] == 10

        def start(self) -> None:
            return None

        def play_buffer(self, pcm, channels):  # noqa: ANN001
            del pcm, channels
            action = object()  # no `.done` attribute on purpose
            actions.append(action)
            return action

        def cancel(self, action) -> None:  # noqa: ANN001
            assert action in actions

        def stop(self) -> None:
            return None

    fake_sd = SimpleNamespace(
        query_devices=lambda: [{"name": "Headset", "max_output_channels": 2, "hostapi": 0}],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
    )
    fake_rtmixer = SimpleNamespace(Mixer=_Mixer)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setitem(sys.modules, "rtmixer", fake_rtmixer)

    playback = RtMixerPlayback(bank, device_name="Headset", host_api="WASAPI", clock=clock)
    playback.play(utt)
    assert playback.current is utt
    clock.advance(0.49)
    assert playback.current is utt
    clock.advance(0.02)
    assert playback.current is None


def test_bank_skips_clips_with_sha256_mismatch(tmp_path) -> None:
    # Qodo finding #1: a corrupted-but-decodable clip must be skipped at load, never played.
    pytest.importorskip("numpy")  # Bank decode needs numpy (the real-backend path)
    from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank
    from tools.ai_sidecar.voice.playback import Bank

    manifest = bake_bank(tmp_path, ToneBackend())
    victim = "late_brake.act.t03"
    # Corrupt one clip's bytes without updating the manifest sha → load must skip it.
    (tmp_path / manifest.clips[victim].file).write_bytes(b"RIFFcorrupted-not-the-baked-bytes")
    bank = Bank.from_manifest(manifest, tmp_path)
    assert victim not in bank.clips  # mismatched clip skipped
    assert "late_brake.act.t04" in bank.clips  # an untouched clip still loads
    assert len(bank.clips) == len(manifest.clips) - 1
