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
    SoundDevicePlayback,
    _TimedCurrent,
    resolve_output_device,
    resolve_output_layout,
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


def test_output_layout_uses_fixed_multichannel_device_and_center_channel() -> None:
    """Regression for #602: the rig WASAPI endpoint rejects mono but accepts its 5.1 width."""
    devices = [{"name": "5.1 Speakers (USB Sound Device)", "max_output_channels": 6, "hostapi": 0}]
    attempted: list[int] = []

    def check_output_settings(*, device, channels, samplerate):  # noqa: ANN001
        assert device == 0
        assert samplerate == 48_000
        attempted.append(channels)
        if channels != 6:
            raise RuntimeError("Invalid number of channels [PaErrorCode -9998]")

    layout = resolve_output_layout(
        0,
        bank_channels=1,
        samplerate=48_000,
        devices=devices,
        host_apis=[{"name": "Windows WASAPI"}],
        check_output_settings=check_output_settings,
    )

    assert attempted == [1, 2, 3, 4, 5, 6]
    assert layout.stream_channels == 6
    assert layout.max_output_channels == 6
    assert layout.channel_map == (3,)


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
            assert kwargs["channels"] == 1

        def start(self) -> None:
            return None

        def play_buffer(self, pcm, channels):  # noqa: ANN001
            del pcm
            assert channels == [1]
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
        check_output_settings=lambda **_kwargs: None,
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


def test_sounddevice_expands_mono_for_fixed_multichannel_device(monkeypatch) -> None:
    """The interim backend must recover from the same fixed-width endpoint as rtmixer."""
    np = pytest.importorskip("numpy")
    resolver = Resolver(build_manifest())
    utterance = resolver.resolve(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert utterance is not None
    pcm = np.arange(5, dtype=np.float32)
    bank = Bank(samplerate=48_000, clips={utterance.clip_id: pcm})
    played: dict[str, object] = {}

    def check_output_settings(*, device, channels, samplerate):  # noqa: ANN001
        assert device == 0
        assert samplerate == 48_000
        if channels != 6:
            raise RuntimeError("Invalid number of channels [PaErrorCode -9998]")

    def play(output, *, samplerate, device):  # noqa: ANN001
        played.update(output=output, samplerate=samplerate, device=device)

    fake_sd = SimpleNamespace(
        query_devices=lambda: [
            {"name": "5.1 Speakers (USB Sound Device)", "max_output_channels": 6, "hostapi": 0}
        ],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        check_output_settings=check_output_settings,
        play=play,
        stop=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    playback = SoundDevicePlayback(
        bank,
        device_name="USB Sound Device",
        host_api="WASAPI",
    )
    playback.play(utterance)

    output = played["output"]
    assert output.shape == (5, 6)
    assert np.array_equal(output[:, 2], pcm)
    assert np.count_nonzero(output[:, [0, 1, 3, 4, 5]]) == 0
    assert playback.output_details["channel_map"] == [3]


def test_sounddevice_expands_multichannel_bank_through_negotiated_map(monkeypatch) -> None:
    """Every source channel must survive expansion when a device requires a wider stream."""
    np = pytest.importorskip("numpy")
    resolver = Resolver(build_manifest())
    utterance = resolver.resolve(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert utterance is not None
    pcm = np.column_stack(
        (
            np.arange(5, dtype=np.float32),
            np.arange(5, dtype=np.float32) + 10,
        )
    )
    bank = Bank(samplerate=48_000, clips={utterance.clip_id: pcm}, channels=2)
    played: dict[str, object] = {}

    def check_output_settings(*, device, channels, samplerate):  # noqa: ANN001
        assert device == 0
        assert samplerate == 48_000
        if channels != 6:
            raise RuntimeError("Invalid number of channels [PaErrorCode -9998]")

    fake_sd = SimpleNamespace(
        query_devices=lambda: [{"name": "Fixed 5.1", "max_output_channels": 6, "hostapi": 0}],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        check_output_settings=check_output_settings,
        play=lambda output, *, samplerate, device: played.update(
            output=output, samplerate=samplerate, device=device
        ),
        stop=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    playback = SoundDevicePlayback(bank, device_name="Fixed 5.1", host_api="WASAPI")
    playback.play(utterance)

    output = played["output"]
    assert output.shape == (5, 6)
    assert np.array_equal(output[:, :2], pcm)
    assert np.count_nonzero(output[:, 2:]) == 0
    assert playback.output_details["channel_map"] == [1, 2]


def test_bank_skips_clips_with_sha256_mismatch(tmp_path) -> None:
    # Qodo finding #1: a corrupted-but-decodable clip must be skipped at load, never played.
    pytest.importorskip("numpy")  # Bank decode needs numpy (the real-backend path)
    from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank
    from tools.ai_sidecar.voice.playback import Bank

    manifest = bake_bank(tmp_path, ToneBackend())
    victim = "late_brake.prepare.calm.t03"
    # Corrupt one clip's bytes without updating the manifest sha → load must skip it.
    (tmp_path / manifest.clips[victim].file).write_bytes(b"RIFFcorrupted-not-the-baked-bytes")
    bank = Bank.from_manifest(manifest, tmp_path)
    assert victim not in bank.clips  # mismatched clip skipped
    assert "late_brake.prepare.calm.t04" in bank.clips  # an untouched clip still loads
    assert len(bank.clips) == len(manifest.clips) - 1
