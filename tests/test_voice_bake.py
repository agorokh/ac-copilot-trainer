"""Tests for the offline bake step (tools.ai_sidecar.voice.bake), stdlib ToneBackend only.

ToneBackend needs no third-party dependency, so CI bakes a real (audible) bank and asserts the
manifest content-addressing end to end without a TTS engine.
"""

from __future__ import annotations

import argparse
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from tools.ai_sidecar.voice import bake as bake_mod
from tools.ai_sidecar.voice import vocabulary as vocab
from tools.ai_sidecar.voice.bake import (
    KokoroBackend,
    PiperBackend,
    ToneBackend,
    _build_backend,
    bake_bank,
)
from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME, Manifest, sha256_bytes


def test_bake_renders_full_vocabulary_with_valid_manifest(tmp_path) -> None:
    manifest = bake_bank(tmp_path, ToneBackend(), samplerate=22050)
    # one clip per vocabulary phrase
    assert len(manifest.clips) == len(vocab.vocabulary())
    # manifest stamps the current vocabulary hash + the backend voice signature
    assert manifest.vocabulary_hash == vocab.vocabulary_hash()
    assert manifest.voice_signature == f"tone-v3+{vocab.EXPECTED_SIGNATURE_SUFFIX}"
    # every clip file exists, is non-empty audio, and its sha matches the manifest
    for entry in manifest.clips.values():
        fp = tmp_path / entry.file
        assert fp.is_file()
        assert sha256_bytes(fp.read_bytes()) == entry.sha256
        with wave.open(str(fp), "rb") as wf:
            assert wf.getnframes() > 0  # non-silent / non-empty clip
            assert wf.getframerate() == 22050
    # full validation (vocabulary + files + sha) is clean
    loaded = Manifest.load(tmp_path / MANIFEST_FILENAME)
    assert loaded.validate(tmp_path).ok


def test_bake_is_deterministic(tmp_path) -> None:
    # ToneBackend derives tone from a stable hash → byte-reproducible bank (content-addressing means
    # something). Bake twice into sibling dirs and compare per-clip sha.
    a = tmp_path / "a"
    b = tmp_path / "b"
    ma = bake_bank(a, ToneBackend())
    mb = bake_bank(b, ToneBackend())
    assert {c.clip_id: c.sha256 for c in ma.clips.values()} == {
        c.clip_id: c.sha256 for c in mb.clips.values()
    }
    assert ma.vocabulary_hash == mb.vocabulary_hash


def test_bake_distinct_phrases_have_distinct_audio(tmp_path) -> None:
    manifest = bake_bank(tmp_path, ToneBackend())
    shas = [c.sha256 for c in manifest.clips.values()]
    # Distinct texts should mostly yield distinct tones (no wholesale collision into one clip).
    assert len(set(shas)) > len(shas) // 2


def test_bake_resamples_external_backend_to_requested_samplerate(tmp_path) -> None:
    pytest.importorskip("numpy")

    class _Native22050Backend:
        voice_signature = f"native-22050-test+{vocab.EXPECTED_SIGNATURE_SUFFIX}"

        def synthesize(self, text, register, out_path, samplerate):  # noqa: ANN001
            del text, register, samplerate
            source_rate = 22050
            frames = bytearray()
            for i in range(int(source_rate * 0.05)):
                sample = 0.3 * math.sin(2 * math.pi * 440.0 * i / source_rate)
                frames += struct.pack("<h", int(sample * 32767))
            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(source_rate)
                wf.writeframes(bytes(frames))

    manifest = bake_bank(tmp_path, _Native22050Backend(), samplerate=48000)
    clip = tmp_path / next(iter(manifest.clips.values())).file
    with wave.open(str(clip), "rb") as wf:
        assert wf.getframerate() == 48000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
    assert manifest.samplerate == 48000


def test_bake_accepts_float32_external_backend(tmp_path) -> None:
    pytest.importorskip("numpy")

    class _Float32Backend:
        voice_signature = f"float32-test+{vocab.EXPECTED_SIGNATURE_SUFFIX}"

        def synthesize(self, text, register, out_path, samplerate):  # noqa: ANN001
            del text, register
            frames = bytearray()
            for i in range(int(samplerate * 0.02)):
                sample = 0.25 * math.sin(2 * math.pi * 330.0 * i / samplerate)
                frames += struct.pack("<f", sample)
            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(4)
                wf.setframerate(samplerate)
                wf.writeframes(bytes(frames))

    manifest = bake_bank(tmp_path, _Float32Backend(), samplerate=22050)
    clip = tmp_path / next(iter(manifest.clips.values())).file
    with wave.open(str(clip), "rb") as wf:
        assert wf.getframerate() == 22050
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        raw = wf.readframes(wf.getnframes())
    assert max(abs(v[0]) for v in struct.iter_unpack("<h", raw)) > 1000


def test_bank_policy_hook_runs_after_normalization_not_during_synthesis(tmp_path) -> None:
    class _ValidatingToneBackend(ToneBackend):
        def __init__(self) -> None:
            self.validated: list[str] = []

        def validate_baked_clip(self, text: str, register: str, out_path: Path) -> None:
            del text, register
            with wave.open(str(out_path), "rb") as wf:
                assert wf.getframerate() == 22050
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2
            self.validated.append(out_path.name)

    backend = _ValidatingToneBackend()
    backend.synthesize("Brake!", "critical", tmp_path / "benchmark.wav", 22050)
    assert backend.validated == []  # bench_voices uses the unchecked, measurable render path.

    manifest = bake_bank(tmp_path / "bank", backend, samplerate=22050)
    assert len(backend.validated) == len(manifest.clips)


def test_tone_backend_registers_are_distinct(tmp_path) -> None:
    # Issue #381: the register (intensity tier) must produce measurably distinct audio even from the
    # stdlib CI backend, so CI exercises calm/alert/urgent/critical end-to-end.
    manifest = bake_bank(tmp_path, ToneBackend())
    alert = manifest.clips["late_brake.act.alert.generic"].sha256
    urgent = manifest.clips["late_brake.act.urgent.generic"].sha256
    crit = manifest.clips["late_brake.act.critical.generic"].sha256
    calm = manifest.clips["late_brake.prepare.calm.generic"].sha256
    assert len({alert, urgent, crit, calm}) == 4  # four distinct register clips


def test_speech_backends_keep_act_registers_fast() -> None:
    # Issue #381: Kokoro quantizes terse utterance durations, so the shaped WAV contract below is
    # authoritative. These base-speed rails preserve the measured <=450 ms active ladder while
    # leaving critical enough articulation room for the final consonant.
    assert KokoroBackend._REGISTER_SPEED["calm"] < KokoroBackend._REGISTER_SPEED["alert"]
    assert KokoroBackend._REGISTER_SPEED["alert"] >= 1.26
    assert KokoroBackend._REGISTER_SPEED["urgent"] >= 1.28
    assert 1.20 <= KokoroBackend._REGISTER_SPEED["critical"] <= 1.25

    assert (
        PiperBackend._REGISTER_LENGTH_SCALE["calm"] > PiperBackend._REGISTER_LENGTH_SCALE["alert"]
    )
    assert (
        PiperBackend._REGISTER_LENGTH_SCALE["alert"] > PiperBackend._REGISTER_LENGTH_SCALE["urgent"]
    )
    assert (
        PiperBackend._REGISTER_LENGTH_SCALE["urgent"]
        > PiperBackend._REGISTER_LENGTH_SCALE["critical"]
    )
    assert PiperBackend._REGISTER_LENGTH_SCALE["critical"] <= 0.75


def test_prosody_shaper_is_run_to_run_deterministic(tmp_path) -> None:
    # Issue #368 (adversary): the ffmpeg-shaped path the product actually ships must be
    # byte-deterministic run-to-run on a fixed ffmpeg (`-bitexact`), so per-clip sha256 stays a real
    # drift detector. ToneBackend alone does not exercise the ffmpeg chain — this does.
    import shutil

    import pytest

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    from tools.ai_sidecar.voice.bake import ProsodyShaper

    # a plain tone WAV as the shaper input (no TTS engine needed)
    src = tmp_path / "src.wav"
    ToneBackend().synthesize("Brake.", "urgent", src, 22050)
    shaper = ProsodyShaper(apply_tempo=True)
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    shaper.shape(src, a, "critical", 22050)
    shaper.shape(src, b, "critical", 22050)
    assert a.read_bytes() == b.read_bytes()  # identical bytes → deterministic, content-addressable


def test_prosody_filter_resamples_before_critical_tempo_shift() -> None:
    filt = bake_mod._prosody_filter("critical", 48000, apply_tempo=True)

    assert filt.startswith("aresample=48000,asetrate=48000*1.05,aresample=48000,")


@pytest.mark.parametrize("backend", ["say-expressive", "piper", "kokoro"])
def test_shaped_backend_preflights_missing_ffmpeg(monkeypatch, backend: str) -> None:
    # qodo review #371: shaped backends should fail at backend selection with an actionable message,
    # not later inside ProsodyShaper.shape().
    monkeypatch.setattr("tools.ai_sidecar.voice.bake.shutil.which", lambda name: None)
    args = argparse.Namespace(
        backend=backend,
        say_voice="Daniel",
        piper_model="voice.onnx",
        kokoro_model="kokoro.onnx",
        kokoro_voices="voices.bin",
        kokoro_voice="am_michael",
    )
    with pytest.raises(SystemExit, match="ffmpeg"):
        _build_backend(args)


class _BatchToneBackend:
    # Must end with the persona/intensity suffix — validate() gates on it (issue #438).
    voice_signature = f"batch-tone-v1+{vocab.EXPECTED_SIGNATURE_SUFFIX}"

    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[str, str, Path]], int]] = []

    def synthesize(self, text: str, register: str, out_path: Path, samplerate: int) -> None:
        raise AssertionError("batch backend should not be called one clip at a time")

    def synthesize_many(self, items: list[tuple[str, str, Path]], samplerate: int) -> None:
        self.calls.append((list(items), samplerate))
        tone = ToneBackend()
        for text, register, target in items:
            tone.synthesize(text, register, target, samplerate)


def test_bake_rejects_backend_missing_signature_suffix(tmp_path) -> None:
    # qodo review #441: a backend whose voice_signature lacks the enforced suffix would bake a
    # bank Manifest.validate always refuses (from_bank disables the coach). Fail at bake time,
    # before any clip is rendered — never auto-append a provenance the backend did not declare.
    class _NoSuffixBackend:
        voice_signature = "custom-v1"

        def synthesize(self, text, register, out_path, samplerate):  # noqa: ANN001
            raise AssertionError("bake must fail before any clip is rendered")

    with pytest.raises(ValueError, match="EXPECTED_SIGNATURE_SUFFIX"):
        bake_bank(tmp_path, _NoSuffixBackend())
    assert not (tmp_path / MANIFEST_FILENAME).exists()


def test_bake_uses_batch_backend_when_available(tmp_path) -> None:
    backend = _BatchToneBackend()
    manifest = bake_bank(tmp_path, backend)

    assert len(backend.calls) == 1
    assert len(backend.calls[0][0]) == len(vocab.vocabulary())
    assert manifest.voice_signature == _BatchToneBackend.voice_signature
    assert manifest.validate(tmp_path).ok


def test_cli_status_output_is_windows_codepage_safe(tmp_path, monkeypatch, capsys) -> None:
    def fake_bake_bank(out_dir, backend, *, samplerate: int = 48000):
        return Manifest(
            version=3,
            samplerate=samplerate,
            voice_signature=backend.voice_signature,
            vocabulary_hash=vocab.vocabulary_hash(),
            clips={},
        )

    monkeypatch.setattr(bake_mod, "bake_bank", fake_bake_bank)

    assert bake_mod.main(["--backend", "tone", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "->" in out
    assert "→" not in out


def _write_pcm16_wav(path: Path, *, samplerate: int, value: int, frames: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(b"".join(struct.pack("<h", value) for _ in range(frames)))


def _first_sample(path: Path) -> int:
    with wave.open(str(path), "rb") as wf:
        return struct.unpack("<h", wf.readframes(1))[0]


@pytest.mark.parametrize(
    ("text", "register", "audible_ms", "duration_ms", "error"),
    [
        ("Brake.", "alert", 450, 450, None),
        ("Brake.", "alert", 451, 451, "brake act cue must be at most 450 ms"),
        ("Brake.", "urgent", 450, 450, None),
        ("Brake.", "urgent", 451, 451, "brake act cue must be at most 450 ms"),
        ("Brake!", "critical", 0, 380, "audible articulation must extend"),
        ("Brake!", "critical", 355, 380, "audible articulation must extend"),
        ("Brake!", "critical", 360, 380, None),
        ("Brake!", "critical", 375, 450, None),
        ("Brake!", "critical", 451, 451, "brake act cue must be at most 450 ms"),
    ],
)
def test_kokoro_brake_act_timing_window(
    tmp_path: Path,
    text: str,
    register: str,
    audible_ms: int,
    duration_ms: int,
    error: str | None,
) -> None:
    out = tmp_path / "brake.wav"
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(1000)
        wf.writeframes(
            struct.pack(
                f"<{duration_ms}h", *([1000] * audible_ms), *([0] * (duration_ms - audible_ms))
            )
        )
    backend = object.__new__(KokoroBackend)
    backend._voice = "am_fenrir"

    if error:
        with pytest.raises(RuntimeError, match=error):
            backend.validate_baked_clip(text, register, out)
    else:
        backend.validate_baked_clip(text, register, out)

    # The narrow duration contract is for the one-syllable alarm only, not every critical phrase.
    backend.validate_baked_clip("Save tyres!", "critical", out)


def test_kokoro_articulation_floor_is_scoped_to_operator_calibrated_voice(tmp_path) -> None:
    out = tmp_path / "short-but-audible.wav"
    _write_pcm16_wav(out, samplerate=1000, value=1000, frames=300)
    backend = object.__new__(KokoroBackend)
    backend._voice = "af_heart"

    # Different voices remain benchmarkable/bakeable below Fenrir's empirically calibrated floor;
    # the universal action-cue ceiling is still enforced for every Kokoro voice.
    backend.validate_baked_clip("Brake!", "critical", out)


class _CopyShaper:
    @property
    def signature(self) -> str:
        return "copy"

    def shape(self, in_wav: Path, out_wav: Path, register: str, samplerate: int) -> None:
        del register, samplerate
        out_wav.write_bytes(in_wav.read_bytes())


def _piper_backend(tmp_path: Path) -> PiperBackend:
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"stub-model")
    backend = PiperBackend(model)
    backend._shaper = _CopyShaper()
    return backend


def test_piper_batch_maps_clips_by_numeric_timestamp_order(tmp_path, monkeypatch) -> None:
    """Generation-order recovery must use NUMERIC, not lexical, timestamp sort.

    Piper names batch clips ``{monotonic_ns}.wav``; a lexical sort mis-orders across a digit-count
    rollover (…9.wav vs …10.wav), silently writing the wrong audio under each stable clip_id while
    the count guard still passes. Names 8/9/10 below sort numerically as 8<9<10 but lexically as
    10<8<9, so the old code would scramble the mapping; the new numeric sort keeps it correct.
    """
    backend = _piper_backend(tmp_path)
    out = tmp_path / "bank"
    items = [
        ("brake one", "urgent", out / "clip_a.wav"),
        ("turn two", "urgent", out / "clip_b.wav"),
        ("apex three", "urgent", out / "clip_c.wav"),
    ]
    names = ["8", "9", "10"]  # generation order; numeric != lexical

    def fake_run(cmd, *args, **kwargs):
        assert "--input-file" in cmd, "batch path must use --input-file"
        output_dir = Path(cmd[cmd.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        for gen_index, name in enumerate(names):
            # marker encodes generation order; clips are already at the target rate so the
            # post-move _normalize_wav is a no-op and the marker survives byte-for-byte.
            _write_pcm16_wav(
                output_dir / f"{name}.wav", samplerate=48000, value=(gen_index + 1) * 1000
            )
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bake_mod.subprocess, "run", fake_run)
    backend.synthesize_many(items, 48000)

    # input order == generation order, so target[i] must hold marker (i+1)*1000
    assert _first_sample(items[0][2]) == 1000
    assert _first_sample(items[1][2]) == 2000
    assert _first_sample(items[2][2]) == 3000


def test_piper_batch_preserves_register_length_scale(tmp_path, monkeypatch) -> None:
    backend = _piper_backend(tmp_path)
    out = tmp_path / "bank"
    items = [
        ("calm one", "calm", out / "clip_calm.wav"),
        ("critical two", "critical", out / "clip_critical.wav"),
    ]
    seen: list[tuple[str, list[str]]] = []

    def fake_run(cmd, *args, **kwargs):
        assert "--input-file" in cmd, "batch path must use --input-file"
        scale = cmd[cmd.index("--length_scale") + 1]
        input_path = Path(cmd[cmd.index("--input-file") + 1])
        texts = input_path.read_text(encoding="utf-8").splitlines()
        seen.append((scale, texts))
        output_dir = Path(cmd[cmd.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        for index, _text in enumerate(texts, start=1):
            _write_pcm16_wav(output_dir / f"{index}.wav", samplerate=48000, value=index * 1000)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bake_mod.subprocess, "run", fake_run)
    backend.synthesize_many(items, 48000)

    assert ("1.05", ["calm one"]) in seen
    assert ("0.69", ["critical two"]) in seen
    assert _first_sample(items[0][2]) == 1000
    assert _first_sample(items[1][2]) == 1000


def test_piper_batch_falls_back_to_per_clip_when_batch_fails(tmp_path, monkeypatch) -> None:
    """A Piper build without the batch flags (e.g. MIT rhasspy/piper) must not break the bake.

    The batch subprocess fails; synthesize_many must fall back to the per-clip ``--output_file``
    path that every Piper build supports, producing every requested clip at the target rate.
    """
    backend = _piper_backend(tmp_path)
    out = tmp_path / "bank"
    items = [
        ("brake one", "urgent", out / "clip_a.wav"),
        ("turn two", "calm", out / "clip_b.wav"),
    ]
    calls: list[str] = []

    def fake_run(cmd, *args, **kwargs):
        if "--input-file" in cmd:
            calls.append("batch")
            raise subprocess.CalledProcessError(2, cmd)  # batch flags unsupported
        # per-clip path: piper writes a WAV to --output_file. Bake the stub already at the target
        # rate so _normalize_wav early-returns and the stdlib-only voice-bake suite runs without
        # numpy (the `.[dev]` extra); the numpy resample path is covered by the tests above.
        calls.append("per-clip")
        out_path = Path(cmd[cmd.index("--output_file") + 1])
        _write_pcm16_wav(out_path, samplerate=48000, value=500)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bake_mod.subprocess, "run", fake_run)
    backend.synthesize_many(items, 48000)

    assert calls[0] == "batch"  # tried batch first
    assert calls.count("per-clip") == 2  # then one per clip
    for _text, _register, target in items:
        assert target.is_file()
        with wave.open(str(target), "rb") as wf:
            assert wf.getframerate() == 48000  # per-clip path produced clips at the target rate


def test_normalize_wav_gives_clear_error_when_numpy_missing(tmp_path, monkeypatch) -> None:
    """The 48 kHz bank default routes Piper output (commonly 22050 Hz) through _normalize_wav, which
    needs numpy (a `voice` extra, not a base dep). Without numpy the bake must fail with an
    actionable message, not a raw ModuleNotFoundError deep in the resample path.
    """
    fp = tmp_path / "native.wav"
    _write_pcm16_wav(fp, samplerate=22050, value=500)  # rate mismatch -> resample path
    monkeypatch.setitem(sys.modules, "numpy", None)  # simulate numpy not installed
    with pytest.raises(RuntimeError, match="numpy"):
        bake_mod._normalize_wav(fp, 48000)
