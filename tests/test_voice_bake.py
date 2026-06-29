"""Tests for the offline bake step (tools.ai_sidecar.voice.bake), stdlib ToneBackend only.

ToneBackend needs no third-party dependency, so CI bakes a real (audible) bank and asserts the
manifest content-addressing end to end without a TTS engine.
"""

from __future__ import annotations

import argparse
import wave

import pytest
from tools.ai_sidecar.voice import vocabulary as vocab
from tools.ai_sidecar.voice.bake import ToneBackend, _build_backend, bake_bank
from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME, Manifest, sha256_bytes


def test_bake_renders_full_vocabulary_with_valid_manifest(tmp_path) -> None:
    manifest = bake_bank(tmp_path, ToneBackend(), samplerate=22050)
    # one clip per vocabulary phrase
    assert len(manifest.clips) == len(vocab.vocabulary())
    # manifest stamps the current vocabulary hash + the backend voice signature
    assert manifest.vocabulary_hash == vocab.vocabulary_hash()
    assert manifest.voice_signature == "tone-v2"
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


def test_tone_backend_registers_are_distinct(tmp_path) -> None:
    # Issue #368: the register (intensity tier) must produce measurably distinct audio even from the
    # stdlib CI backend, so CI exercises the tone dimension end-to-end (firm/critical differ from
    # calm).
    manifest = bake_bank(tmp_path, ToneBackend())
    firm = manifest.clips["late_brake.act.firm.generic"].sha256
    crit = manifest.clips["late_brake.act.critical.generic"].sha256
    calm = manifest.clips["late_brake.prepare.calm.generic"].sha256
    assert len({firm, crit, calm}) == 3  # three distinct register clips


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
    ToneBackend().synthesize("Brake.", "firm", src, 22050)
    shaper = ProsodyShaper(apply_tempo=True)
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    shaper.shape(src, a, "critical", 22050)
    shaper.shape(src, b, "critical", 22050)
    assert a.read_bytes() == b.read_bytes()  # identical bytes → deterministic, content-addressable


def test_shaped_backend_preflights_missing_ffmpeg(monkeypatch) -> None:
    # qodo review #371: shaped backends should fail at backend selection with an actionable message,
    # not later inside ProsodyShaper.shape().
    monkeypatch.setattr("tools.ai_sidecar.voice.bake.shutil.which", lambda name: None)
    args = argparse.Namespace(
        backend="say-expressive",
        say_voice="Daniel",
        piper_model=None,
        kokoro_model=None,
        kokoro_voices=None,
        kokoro_voice="am_michael",
    )
    with pytest.raises(SystemExit, match="ffmpeg"):
        _build_backend(args)
