"""Tests for the content-addressed phrase-bank manifest (tools.ai_sidecar.voice.manifest)."""

from __future__ import annotations

import json

import pytest
from _voice_support import build_manifest

from tools.ai_sidecar.voice import vocabulary as vocab
from tools.ai_sidecar.voice.manifest import (
    Manifest,
    ManifestError,
    sha256_bytes,
)


def test_manifest_roundtrip_and_lookup() -> None:
    m = build_manifest()
    restored = Manifest.from_dict(json.loads(m.to_json()))
    assert restored.vocabulary_hash == m.vocabulary_hash
    assert restored.samplerate == m.samplerate
    # lookup by advisory key works for a numbered and a generic clip
    assert restored.lookup("late_brake", "act", 3) == "late_brake.act.t03"
    assert restored.lookup("apex_deficit", "info", None) == "apex_deficit.info.generic"
    assert restored.lookup("late_brake", "act", 999) is None


def test_validate_clean_vocabulary_match() -> None:
    report = build_manifest().validate()  # no bank_dir → vocabulary-only check
    assert report.vocabulary_matches
    assert report.ok
    assert report.problems == []


def test_validate_detects_vocabulary_drift() -> None:
    m = build_manifest()
    m.vocabulary_hash = "deadbeef" * 8  # pretend the bank was baked against other wording
    report = m.validate()
    assert not report.vocabulary_matches
    assert any("vocabulary_hash mismatch" in p for p in report.problems)


def test_validate_detects_missing_file_and_sha_mismatch(tmp_path) -> None:
    # Build a tiny real bank: one good file (sha matches) and one missing file.
    good = tmp_path / "late_brake.act.t01.wav"
    good.write_bytes(b"RIFFfake-wav-bytes")
    good_sha = sha256_bytes(good.read_bytes())
    data = {
        "version": 1,
        "samplerate": 22050,
        "voice_signature": "tone-v1",
        "vocabulary_hash": vocab.vocabulary_hash(),
        "clips": {
            "late_brake.act.t01": {
                "clip_id": "late_brake.act.t01",
                "file": "late_brake.act.t01.wav",
                "kind": "late_brake",
                "urgency": "act",
                "corner": 1,
                "text": "Brake turn one.",
                "sha256": good_sha,
            },
            "late_brake.act.t02": {
                "clip_id": "late_brake.act.t02",
                "file": "late_brake.act.t02.wav",  # never written → missing
                "kind": "late_brake",
                "urgency": "act",
                "corner": 2,
                "text": "Brake turn two.",
                "sha256": "0" * 64,
            },
        },
    }
    m = Manifest.from_dict(data)
    report = m.validate(tmp_path)
    assert report.vocabulary_matches  # wording is current
    assert any("missing clip file" in p for p in report.problems)

    # now corrupt the good file → sha mismatch
    good.write_bytes(b"corrupted")
    report2 = m.validate(tmp_path)
    assert any("sha256 mismatch" in p for p in report2.problems)


def test_load_malformed_manifest_raises(tmp_path) -> None:
    bad = tmp_path / "manifest.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ManifestError):
        Manifest.load(bad)

    bad.write_text(json.dumps({"version": 1}), encoding="utf-8")  # missing required keys
    with pytest.raises(ManifestError):
        Manifest.load(bad)
