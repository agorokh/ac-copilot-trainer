"""Tests for the offline bake step (tools.ai_sidecar.voice.bake), stdlib ToneBackend only.

ToneBackend needs no third-party dependency, so CI bakes a real (audible) bank and asserts the
manifest content-addressing end to end without a TTS engine.
"""

from __future__ import annotations

import wave

from tools.ai_sidecar.voice import vocabulary as vocab
from tools.ai_sidecar.voice.bake import ToneBackend, bake_bank
from tools.ai_sidecar.voice.manifest import MANIFEST_FILENAME, Manifest, sha256_bytes


def test_bake_renders_full_vocabulary_with_valid_manifest(tmp_path) -> None:
    manifest = bake_bank(tmp_path, ToneBackend(), samplerate=22050)
    # one clip per vocabulary phrase
    assert len(manifest.clips) == len(vocab.vocabulary())
    # manifest stamps the current vocabulary hash + the backend voice signature
    assert manifest.vocabulary_hash == vocab.vocabulary_hash()
    assert manifest.voice_signature == "tone-v1"
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
