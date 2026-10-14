"""Explicit output routing: synthetic device tables and PCM only, never audio hardware."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
from _voice_support import build_manifest, make_advisory

from tools.ai_sidecar.voice import audible_latency as al
from tools.ai_sidecar.voice.config import VoiceConfig, parse_channel_map
from tools.ai_sidecar.voice.playback import (
    Bank,
    OutputLayoutError,
    RtMixerPlayback,
    SoundDevicePlayback,
    resolve_output_layout,
)
from tools.ai_sidecar.voice.resolver import Resolver
from tools.rig_launcher.settings import default_settings_payload
from tools.rig_launcher.supervisor import GamePointConfig, GamePointSupervisor, LauncherPaths


@pytest.mark.parametrize("value", ["5, 6", (5, 6), [5, 6]])
def test_map_normalizes_one_based_values(value):
    assert VoiceConfig(channel_map=value).channel_map == (5, 6)
    assert parse_channel_map(None) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "1,",
        ",1",
        "1,,2",
        "1.0",
        "x",
        "-1",
        "0",
        "1,1",
        "+1",
        "１",
        (),
        [],
        [True],
        [1.0],
        [0],
        [-1],
        [1, 1],
        1,
        True,
    ],
)
def test_invalid_explicit_map_never_becomes_default(value):
    with pytest.raises(ValueError, match="channel map"):
        VoiceConfig(channel_map=value)


def _layout(channel_map, *, bank_channels=1, check=lambda **kwargs: None):
    return resolve_output_layout(
        0,
        bank_channels=bank_channels,
        samplerate=48_000,
        devices=[{"name": "Output", "max_output_channels": 6, "hostapi": 0}],
        host_apis=[{"name": "Windows WASAPI"}],
        check_output_settings=check,
        channel_map=channel_map,
    )


@pytest.mark.parametrize("channel_map", ["5", "5,6", "2,1"])
def test_explicit_wasapi_map_keeps_endpoint_width(channel_map):
    probes = []
    layout = _layout(channel_map, check=lambda **kwargs: probes.append(kwargs["channels"]))
    assert probes == [6]
    assert layout.stream_channels == 6
    assert layout.status()["channel_map"] == list(parse_channel_map(channel_map))


@pytest.mark.parametrize("value,bank_channels", [("7", 1), ("1", 2), ("1,2,3", 2), ("", 1)])
def test_incompatible_map_rejected_without_device_probe(value, bank_channels):
    with pytest.raises(OutputLayoutError):
        _layout(value, bank_channels=bank_channels, check=lambda **kwargs: pytest.fail("probed"))


@pytest.mark.parametrize("channel_map", ["5", "5,6", "1"])
def test_requested_output_width_failure_does_not_fallback_to_lower_width(channel_map):
    probes = []

    def check(**kwargs):
        probes.append(kwargs["channels"])
        raise RuntimeError("unsupported")

    with pytest.raises(OutputLayoutError, match="6..6"):
        _layout(channel_map, check=check)
    assert probes == [6]


@pytest.mark.parametrize("backend", [SoundDevicePlayback, RtMixerPlayback])
@pytest.mark.parametrize("bank_channels,channel_map", [(1, (5, 6)), (1, (5,)), (2, (2, 1))])
def test_both_backends_apply_actual_pcm_route(monkeypatch, backend, bank_channels, channel_map):
    np = pytest.importorskip("numpy")
    utterance = Resolver(build_manifest()).resolve(make_advisory(kind="late_brake", urgency="act"))
    assert utterance is not None
    pcm = np.arange(5, dtype=np.float32)
    if bank_channels == 2:
        pcm = np.column_stack((pcm, pcm + 10))
    bank = Bank(48_000, {utterance.clip_id: pcm}, channels=bank_channels)
    seen = {}

    def check(**kwargs):
        seen["width"] = kwargs["channels"]

    sd = SimpleNamespace(
        query_devices=lambda: [{"name": "Output", "max_output_channels": 6, "hostapi": 0}],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        check_output_settings=check,
        play=lambda output, **kwargs: seen.update(pcm=output),
        stop=lambda: None,
    )

    class Mixer:
        def __init__(self, **kwargs):
            assert kwargs["channels"] == 6

        def start(self):
            pass

        def play_buffer(self, output, *, channels):
            seen.update(pcm=output, map=channels)
            return object()

    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setitem(sys.modules, "rtmixer", SimpleNamespace(Mixer=Mixer))
    playback = backend(bank, device_name="Output", host_api="WASAPI", channel_map=channel_map)
    playback.play(utterance)
    assert playback.output_details["channel_map"] == list(channel_map)
    if backend is SoundDevicePlayback:
        output = seen["pcm"]
        for source_index, destination in enumerate(channel_map):
            np.testing.assert_array_equal(
                output[:, destination - 1], pcm if bank_channels == 1 else pcm[:, source_index]
            )
        unused = [i for i in range(output.shape[1]) if i + 1 not in channel_map]
        assert not np.any(output[:, unused])
    else:
        assert seen["map"] == list(channel_map)
        expected = (
            np.column_stack((pcm, pcm)) if bank_channels == 1 and len(channel_map) == 2 else pcm
        )
        np.testing.assert_array_equal(seen["pcm"], expected)


def test_chirp_uses_same_rear_channels_as_voice(monkeypatch):
    np = pytest.importorskip("numpy")
    captured = {}

    class CallbackStop(Exception):
        pass

    class Stream:
        time = 10.0
        latency = 0.01

        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            assert kwargs["channels"] == 6
            assert kwargs["device"] == 0

        def __enter__(self):
            pcm = np.ones((20_000, 6), dtype=np.float32)
            with pytest.raises(CallbackStop):
                self.callback(pcm, len(pcm), SimpleNamespace(outputBufferDacTime=10.01), None)
            captured["pcm"] = pcm
            return self

        def __exit__(self, *args):
            pass

    sd = SimpleNamespace(
        query_devices=lambda: [{"name": "Output", "max_output_channels": 6, "hostapi": 0}],
        query_hostapis=lambda: [{"name": "Windows WASAPI"}],
        check_output_settings=lambda **kwargs: None,
        OutputStream=Stream,
        CallbackStop=CallbackStop,
    )
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    al.play_chirp("rear", device="Output", host_api="WASAPI", channel_map="5,6")
    assert not np.any(captured["pcm"][:, :4])
    assert np.any(captured["pcm"][:, 4])
    np.testing.assert_array_equal(captured["pcm"][:, 4], captured["pcm"][:, 5])
    with pytest.raises(OutputLayoutError):
        al.play_chirp("bad", device="Output", host_api="WASAPI", channel_map="")


def test_game_point_settings_env_precedence_and_sidecar_export(tmp_path):
    paths = LauncherPaths(tmp_path)
    paths.settings_path.write_text(json.dumps({"voice_channel_map": " 5, 6 "}), encoding="utf-8")
    cfg = GamePointConfig.from_env({}, paths=paths)
    assert cfg.voice_channel_map == "5,6"
    supervisor = GamePointSupervisor(cfg, environ={"AC_COPILOT_VOICE_CHANNEL_MAP": "1,2"})
    assert supervisor.sidecar_environment()["AC_COPILOT_VOICE_CHANNEL_MAP"] == "5,6"
    assert (
        GamePointConfig.from_env(
            {"AC_COPILOT_VOICE_CHANNEL_MAP": "2,1"}, paths=paths
        ).voice_channel_map
        == "2,1"
    )
    with pytest.raises(ValueError):
        GamePointConfig.from_env({"AC_COPILOT_VOICE_CHANNEL_MAP": ""}, paths=paths)
    assert default_settings_payload()["voice_channel_map"] is None


@pytest.mark.parametrize("value", ["", "1,1", 5, [5, 6], False])
def test_malformed_map_setting_is_not_discarded(tmp_path, value):
    paths = LauncherPaths(tmp_path)
    paths.settings_path.write_text(json.dumps({"voice_channel_map": value}), encoding="utf-8")
    with pytest.raises(ValueError):
        GamePointConfig.from_env({}, paths=paths)
    assert (
        GamePointConfig.from_env(
            {"AC_COPILOT_VOICE_CHANNEL_MAP": "5"}, paths=paths
        ).voice_channel_map
        == "5"
    )


@pytest.mark.parametrize("value", ["", "5,6"])
def test_pyttsx3_rejects_map_before_import_or_worker(monkeypatch, value):
    from tools.ai_sidecar.voice.client import _pyttsx3_speaker

    monkeypatch.setitem(sys.modules, "pyttsx3", None)
    with pytest.raises(ValueError, match="unsupported by pyttsx3"):
        _pyttsx3_speaker(environ={"AC_COPILOT_VOICE_CHANNEL_MAP": value}, require_opt_in=False)


@pytest.mark.parametrize(
    "backend,missing_rtmixer", [("rtmixer", False), ("sounddevice", False), ("rtmixer", True)]
)
def test_engine_forwards_map_including_import_fallback(monkeypatch, backend, missing_rtmixer):
    from tools.ai_sidecar.voice import playback
    from tools.ai_sidecar.voice.engine import VoiceCoach

    seen = []
    monkeypatch.setattr(Bank, "from_manifest", lambda *args: object())

    def construct(bank, **kwargs):
        seen.append(kwargs["channel_map"])
        return object()

    def missing(*args, **kwargs):
        raise ImportError("test absence")

    monkeypatch.setattr(playback, "RtMixerPlayback", missing if missing_rtmixer else construct)
    monkeypatch.setattr(playback, "SoundDevicePlayback", construct)
    VoiceCoach._build_playback(build_manifest(), None, VoiceConfig(channel_map="5,6"), backend)
    assert seen == [(5, 6)]


def test_launcher_cli_keeps_channel_map(tmp_path, monkeypatch):
    from tools.rig_launcher.app import build_arg_parser, config_from_args

    monkeypatch.setenv("AC_COPILOT_VOICE_CHANNEL_MAP", "5,6")
    args = build_arg_parser().parse_args(["--log-dir", str(tmp_path)])
    assert config_from_args(args).voice_channel_map == "5,6"


@pytest.mark.parametrize(
    "cli_map,env_map,expected",
    [(None, "5,6", (5, 6)), ("2,1", "5,6", (2, 1)), ("", "5,6", None), (None, "", None)],
)
def test_server_effective_map_and_fail_closed(tmp_path, monkeypatch, cli_map, env_map, expected):
    from tests.test_realtime_observer import _corner_archive
    from tools.ai_sidecar import server
    from tools.ai_sidecar.voice.engine import VoiceCoach

    ref = tmp_path / "reference.json"
    ref.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    seen = []

    def from_bank(bank_dir, config, **kwargs):
        seen.append(config.channel_map)
        return SimpleNamespace(
            enabled=True,
            start=lambda: None,
            playback_details={"channel_map": list(config.channel_map)},
        )

    monkeypatch.setenv("AC_COPILOT_VOICE_CHANNEL_MAP", env_map)
    monkeypatch.delenv("AC_COPILOT_COACH_V2", raising=False)
    monkeypatch.setattr(VoiceCoach, "from_bank", from_bank)
    monkeypatch.setattr(server, "_voice_coach", None)
    monkeypatch.setattr(server, "_observer", None)
    monkeypatch.setattr(server, "_set_voice_web_bank", lambda *args: None)
    server._wire_voice(server.VoiceRuntimeConfig(str(ref), "test-bank", channel_map=cli_map))
    status = server.voice_runtime_status()
    if expected is None:
        assert not seen
        assert not status["enabled"]
        assert "channel map" in status["disabled_reason"]
        assert server._voice_coach is None
    else:
        assert seen == [expected]
        assert status["enabled"]
        assert status["channel_map"] == list(expected)


def test_server_tts_cannot_ignore_cli_channel_map(tmp_path, monkeypatch):
    from tests.test_realtime_observer import _corner_archive
    from tools.ai_sidecar import server
    from tools.ai_sidecar.voice import client

    ref = tmp_path / "reference.json"
    ref.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    monkeypatch.delenv("AC_COPILOT_VOICE_CHANNEL_MAP", raising=False)
    monkeypatch.setattr(client, "_pyttsx3_speaker", lambda **kwargs: pytest.fail("initialized TTS"))
    monkeypatch.setattr(server, "_voice_coach", None)
    server._wire_voice(server.VoiceRuntimeConfig(str(ref), None, tts_enabled=True, channel_map="5"))
    status = server.voice_runtime_status()
    assert not status["enabled"]
    assert "unsupported by pyttsx3" in status["disabled_reason"]


def test_sidecar_cli_forwards_explicit_map(monkeypatch):
    from tools.ai_sidecar import server

    seen = []

    async def run(*args, **kwargs):
        pass

    monkeypatch.setattr(server, "_run", run)
    monkeypatch.setattr(server, "_wire_voice", lambda config: seen.append(config.channel_map))
    monkeypatch.setattr(sys, "argv", ["ai_sidecar", "--voice-channel-map", "5,6"])
    server.main()
    assert seen == ["5,6"]
