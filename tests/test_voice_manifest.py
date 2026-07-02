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
    # lookup by the 4-axis advisory key (kind, urgency, register, corner)
    assert restored.lookup("late_brake", "prepare", "calm", 3) == "late_brake.prepare.calm.t03"
    assert restored.lookup("late_brake", "act", "urgent", None) == "late_brake.act.urgent.generic"
    assert restored.lookup("late_brake", "act", "firm", None) == "late_brake.act.urgent.generic"
    assert (
        restored.lookup("late_brake", "act", "critical", None) == "late_brake.act.critical.generic"
    )
    assert restored.lookup("late_brake", "prepare", "calm", 999) is None


def test_validate_clean_vocabulary_match() -> None:
    report = build_manifest().validate()  # no bank_dir → vocabulary/signature-only check
    assert report.vocabulary_matches
    assert report.signature_matches
    assert report.ok
    assert report.problems == []


def test_validate_detects_vocabulary_drift() -> None:
    m = build_manifest()
    m.vocabulary_hash = "deadbeef" * 8  # pretend the bank was baked against other wording
    report = m.validate()
    assert not report.vocabulary_matches
    assert any("vocabulary_hash mismatch" in p for p in report.problems)


def test_validate_detects_signature_drift() -> None:
    # Issue #438: a persona swap, prosody-chain edit, or intensity-chain bump with identical
    # wording keeps vocabulary_hash constant, so the signature suffix is the only stale-bank
    # detector for those changes.
    stale_signatures = [
        "tone-v3+race-engineer-original-v0+prosody2+intensity2",  # persona swap
        "tone-v3+race-engineer-original-v1+prosody1+intensity2",  # older prosody chain (codex #441)
        "tone-v3+race-engineer-original-v1+prosody2+intensity1",  # older intensity chain
        "tone-v3+race-engineer-original-v1+intensity2",  # pre-prosody suffix shape
    ]
    for sig in stale_signatures:
        report = build_manifest(voice_signature=sig).validate()
        assert report.vocabulary_matches, sig  # wording unchanged — vocabulary_hash cannot see it
        assert not report.signature_matches, sig
        assert not report.ok, sig
        assert any("voice_signature mismatch" in p for p in report.problems), sig


def test_signature_check_is_anchored_at_the_end() -> None:
    # endswith, not equality or substring: the host-varying prefix (backend, voice, ffmpeg major)
    # must not reject a portable bank, while "…+intensity2" must NOT accept an "…+intensity21"
    # bank.
    portable = build_manifest(
        voice_signature=f"kokoro:af_bella+ff8+{vocab.EXPECTED_SIGNATURE_SUFFIX}"
    )
    assert portable.validate().signature_matches
    near_miss = build_manifest(voice_signature=f"tone-v3+{vocab.EXPECTED_SIGNATURE_SUFFIX}1")
    assert not near_miss.validate().signature_matches


def test_validate_detects_missing_file_and_sha_mismatch(tmp_path) -> None:
    # Build a tiny real bank: one good file (sha matches) and one missing file.
    good = tmp_path / "late_brake.act.t01.wav"
    good.write_bytes(b"RIFFfake-wav-bytes")
    good_sha = sha256_bytes(good.read_bytes())
    data = {
        "version": 3,
        "samplerate": 22050,
        "voice_signature": f"tone-v3+{vocab.EXPECTED_SIGNATURE_SUFFIX}",
        "vocabulary_hash": vocab.vocabulary_hash(),
        "clips": {
            "late_brake.act.t01": {
                "clip_id": "late_brake.act.t01",
                "file": "late_brake.act.t01.wav",
                "kind": "late_brake",
                "urgency": "act",
                "register": "urgent",
                "corner": 1,
                "text": "Brake turn one.",
                "sha256": good_sha,
            },
            "late_brake.act.t02": {
                "clip_id": "late_brake.act.t02",
                "file": "late_brake.act.t02.wav",  # never written → missing
                "kind": "late_brake",
                "urgency": "act",
                "register": "urgent",
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


def test_v1_manifest_without_register_is_rejected() -> None:
    # Issue #368 migration: a v1 clip entry (no `register`) must fail at LOAD so engine.from_bank
    # returns a disabled coach (re-bake required) — never a clip whose tier is unknown.
    v1 = {
        "version": 1,
        "samplerate": 22050,
        "voice_signature": "tone-v1",
        "vocabulary_hash": "0" * 64,
        "clips": {
            "late_brake.act.t01": {
                "clip_id": "late_brake.act.t01",
                "file": "late_brake.act.t01.wav",
                "kind": "late_brake",
                "urgency": "act",
                "corner": 1,  # NOTE: no "register" — the v1 shape
                "text": "Brake turn one.",
                "sha256": "0" * 64,
            }
        },
    }
    with pytest.raises(ManifestError):
        Manifest.from_dict(v1)


def test_forward_incompatible_version_is_rejected() -> None:
    # A bank from a NEWER schema than this code understands must be refused, not mis-read.
    from tools.ai_sidecar.voice.manifest import MANIFEST_VERSION

    future = {
        "version": MANIFEST_VERSION + 1,
        "samplerate": 22050,
        "voice_signature": "x",
        "vocabulary_hash": "0" * 64,
        "clips": {},
    }
    with pytest.raises(ManifestError):
        Manifest.from_dict(future)


def test_manifest_version_must_match_schema_even_if_fields_look_current() -> None:
    # qodo review #371: the top-level version is a real schema gate, not informational metadata.
    data = {
        "version": 1,
        "samplerate": 22050,
        "voice_signature": f"tone-v3+{vocab.EXPECTED_SIGNATURE_SUFFIX}",
        "vocabulary_hash": "0" * 64,
        "clips": {
            "late_brake.act.urgent.generic": {
                "clip_id": "late_brake.act.urgent.generic",
                "file": "x.wav",
                "kind": "late_brake",
                "urgency": "act",
                "register": "urgent",
                "corner": None,
                "text": "Brake.",
                "sha256": "0" * 64,
            }
        },
    }
    with pytest.raises(ManifestError):
        Manifest.from_dict(data)


def test_unknown_register_is_rejected_at_load() -> None:
    # qodo/codex review #371: a hand-edited/corrupt manifest with a register outside the allowed
    # tiers (calm|alert|urgent|critical) must fail loudly at LOAD, not as a silent lookup miss
    # later.
    data = {
        "version": 3,
        "samplerate": 22050,
        "voice_signature": f"tone-v3+{vocab.EXPECTED_SIGNATURE_SUFFIX}",
        "vocabulary_hash": "0" * 64,
        "clips": {
            "late_brake.act.loud.generic": {
                "clip_id": "late_brake.act.loud.generic",
                "file": "x.wav",
                "kind": "late_brake",
                "urgency": "act",
                "register": "loud",  # not in calm|alert|urgent|critical
                "corner": None,
                "text": "Brake!",
                "sha256": "0" * 64,
            }
        },
    }
    with pytest.raises(ManifestError):
        Manifest.from_dict(data)
