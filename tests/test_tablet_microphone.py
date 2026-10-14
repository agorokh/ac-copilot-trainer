"""PCM continuity/privacy and the executable tablet native/worklet path (#531)."""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from tools.ai_sidecar import external_protocol as ep
from tools.ai_sidecar import server
from tools.ai_sidecar.microphone import (
    MIC_CHUNK,
    MIC_END,
    MIC_SUBSCRIBE,
    MicContinuity,
    MicWavCapture,
    decode_chunk,
)
from tools.ai_sidecar.voice.audible_latency import capture_browser_microphone


def chunk(**changes):
    return {
        "v": 1,
        "type": MIC_CHUNK,
        "capture_id": "test-stream",
        "seq": 0,
        "sample_offset": 0,
        "sample_rate": 48000,
        "pcm16": base64.b64encode(b"\x01\x00\xff\x7f").decode(),
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"seq": True},
        {"sample_offset": -1},
        {"sample_rate": 1},
        {"capture_id": "../x"},
        {"pcm16": "!bad"},
        {"pcm16": "AA=="},
        {"pcm16": ""},
        {"pcm16": "A" * 20000},
        {"sample_offset": 48000 * 180},
    ],
)
def test_reject_malformed_pcm(changes):
    assert ep.validate_inbound(chunk(**changes))
    with pytest.raises(ValueError):
        decode_chunk(chunk(**changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"seq": 2, "sample_offset": 2},
        {"seq": 1, "sample_offset": 4},
        {"seq": 0, "sample_offset": 0},
        {"seq": 1, "sample_offset": 2, "capture_id": "new"},
        {"seq": 1, "sample_offset": 2, "sample_rate": 44100},
    ],
)
def test_stream_rejects_gap_duplicate_or_identity_change(changes):
    stream = MicContinuity()
    stream.accept(chunk())
    with pytest.raises(ValueError):
        stream.accept(chunk(**changes))


def test_local_writer_is_exact_midstream_and_never_clobbers(tmp_path):
    path = tmp_path / "capture.wav"
    capture = MicWavCapture(path, max_seconds=1)
    capture.accept(chunk(seq=20, sample_offset=40))
    capture.accept(chunk(seq=21, sample_offset=42))
    capture.close()
    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 48000)
        assert wav.readframes(4) == b"\x01\x00\xff\x7f" * 2
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        MicWavCapture(path, max_seconds=1)
    assert path.read_bytes() == original


def test_writer_duration_and_initial_server_sequence(tmp_path):
    with pytest.raises(ValueError, match="zero"):
        MicContinuity().accept(chunk(seq=1))
    capture = MicWavCapture(tmp_path / "capture.wav", max_seconds=0.00005)
    try:
        capture.accept(chunk())
        with pytest.raises(ValueError, match="duration"):
            capture.accept(chunk(seq=1, sample_offset=2))
    finally:
        capture.close()


class Peer:
    def __init__(self, address="127.0.0.1"):
        self.remote_address = (address, 1234)
        self.sent = []

    async def send(self, value):
        self.sent.append(json.loads(value))


def test_mic_relay_is_opt_in_local_voice_only_and_never_broadcasts():
    async def exercise():
        server._reset_external_state()
        producer, recorder, browser, remote = Peer(), Peer(), Peer(), Peer("192.0.2.1")
        try:
            for peer, cls in [
                (producer, "voice"),
                (recorder, "voice"),
                (browser, "browser"),
                (remote, "voice"),
            ]:
                await server._handle_external_frame(
                    peer, {"v": 1, "type": "hello", "client": "test", "client_class": cls}
                )
                peer.sent.clear()
            for peer in (browser, remote):
                await server._handle_external_frame(
                    peer, {"v": 1, "type": MIC_SUBSCRIBE, "enabled": True}
                )
                assert peer.sent[-1]["type"] == "error"
                peer.sent.clear()
            await server._handle_external_frame(producer, chunk())
            assert not recorder.sent  # no buffering for a future subscriber
            await server._handle_external_frame(
                recorder, {"v": 1, "type": MIC_SUBSCRIBE, "enabled": True}
            )
            recorder.sent.clear()
            await server._handle_external_frame(producer, chunk(seq=1, sample_offset=2))
            assert recorder.sent == [chunk(seq=1, sample_offset=2)]
            assert not browser.sent and not remote.sent
            assert not server._voice_dispatch_log and not server._voice_echo_log
            await server._handle_external_frame(producer, chunk(seq=3, sample_offset=4))
            assert producer.sent[-1]["type"] == "error"
            assert len(recorder.sent) == 1  # dropped chunks are never gap-filled
            await server._handle_external_frame(producer, chunk())
            await server._handle_external_frame(producer, {"v": 1, "type": MIC_END})
            assert recorder.sent[-1] == {"v": 1, "type": MIC_END, "capture_id": "test-stream"}
            server._drop_external_peer(recorder)
            assert not server._voice_mic_subscribers
        finally:
            server._reset_external_state()

    asyncio.run(exercise())


def test_microphone_requires_hello_and_voice_class():
    async def exercise():
        server._reset_external_state()
        peer = Peer()
        await server._handle_external_frame(peer, chunk())
        assert "hello" in peer.sent[-1]["message"]
        assert not server._voice_mic_streams

    asyncio.run(exercise())


def test_browser_capture_writes_real_ws_stream_and_rejects_early_end(tmp_path, monkeypatch):
    from websockets.asyncio.server import serve

    async def exercise():
        server._reset_external_state()
        ready, stop = asyncio.Event(), asyncio.Event()
        subscribed = asyncio.Event()
        original = server._handle_external_frame

        async def observed_handler(peer, data):
            await original(peer, data)
            if data.get("type") == MIC_SUBSCRIBE:
                subscribed.set()

        monkeypatch.setattr(server, "_handle_external_frame", observed_handler)
        async with serve(lambda ws: server._handler(ws, False), "127.0.0.1", 0) as running:
            port = running.sockets[0].getsockname()[1]
            reader = asyncio.create_task(
                capture_browser_microphone(
                    f"ws://127.0.0.1:{port}",
                    tmp_path / "actual.wav",
                    max_seconds=2,
                    ready=ready,
                    stop=stop,
                )
            )
            try:
                async with asyncio.timeout(5):
                    await subscribed.wait()
                    producer = Peer()
                    await server._handle_external_frame(
                        producer,
                        {"v": 1, "type": "hello", "client": "test", "client_class": "voice"},
                    )
                    await server._handle_external_frame(producer, chunk())
                    await ready.wait()
                    await server._handle_external_frame(producer, {"v": 1, "type": MIC_END})
                    with pytest.raises(ValueError, match="stopped"):
                        await reader
            finally:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
                server._reset_external_state()

    asyncio.run(exercise())
    with wave.open(str(tmp_path / "actual.wav"), "rb") as wav:
        assert wav.getnframes() == 2


def test_native_helper_and_worklet_execute_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the executable browser-helper check")
    script = Path(__file__).with_name("tablet_audio_check.cjs")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
