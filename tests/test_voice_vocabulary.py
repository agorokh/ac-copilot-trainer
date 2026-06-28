"""Tests for the bounded voice vocabulary (tools.ai_sidecar.voice.vocabulary)."""

from __future__ import annotations

from tools.ai_sidecar.voice import vocabulary as vocab


def test_vocabulary_is_bounded_and_complete() -> None:
    phrases = vocab.vocabulary()
    # kinds x urgencies x (generic + MAX_CORNER numbered)
    expected = len(vocab.KINDS) * len(vocab.URGENCIES) * (1 + vocab.MAX_CORNER)
    assert len(phrases) == expected
    # every clip id is unique and filesystem-safe
    ids = [p.clip_id for p in phrases]
    assert len(set(ids)) == len(ids)
    for cid in ids:
        assert " " not in cid and "/" not in cid


def test_clip_id_format_and_corner_words() -> None:
    assert vocab.clip_id_for("late_brake", "act", 3) == "late_brake.act.t03"
    assert vocab.clip_id_for("apex_deficit", "info", None) == "apex_deficit.info.generic"
    # 1-based spoken numbers map to words
    t3 = next(p for p in vocab.vocabulary() if p.clip_id == "late_brake.act.t03")
    assert "turn three" in t3.text
    assert t3.text.startswith("Brake")


def test_generic_phrases_have_no_corner_number() -> None:
    generic = [p for p in vocab.vocabulary() if p.corner is None]
    assert generic, "expected corner-less generic fallbacks"
    for p in generic:
        assert "turn" not in p.text.lower()


def test_vocabulary_hash_is_stable_and_deterministic() -> None:
    # Same content -> same hash across calls (the drift detector must be reproducible).
    assert vocab.vocabulary_hash() == vocab.vocabulary_hash()
    assert len(vocab.vocabulary_hash()) == 64  # sha256 hex


def test_vocabulary_hash_changes_when_wording_changes(monkeypatch) -> None:
    before = vocab.vocabulary_hash()
    # Simulate a wording edit and confirm the content hash moves (so a stale bank is detectable).
    patched = dict(vocab._STEMS)
    patched[("late_brake", "act")] = "Hit the brakes{turn}!"
    monkeypatch.setattr(vocab, "_STEMS", patched)
    assert vocab.vocabulary_hash() != before
