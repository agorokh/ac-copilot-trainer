"""Tests for the bounded voice vocabulary (tools.ai_sidecar.voice.vocabulary)."""

from __future__ import annotations

from tools.ai_sidecar.voice import vocabulary as vocab


def test_vocabulary_is_bounded_and_complete() -> None:
    phrases = vocab.vocabulary()
    # Only (kind, urgency, register) triples present in _STEMS are baked; a per-corner stem (one
    # carrying {turn}) expands to generic + MAX_CORNER, a terse stem to a single generic clip.
    expected = 0
    for (_kind, _urg, _reg), stem in vocab._STEMS.items():
        expected += (1 + vocab.MAX_CORNER) if "{turn}" in stem else 1
    assert len(phrases) == expected
    # every clip id is unique and filesystem-safe
    ids = [p.clip_id for p in phrases]
    assert len(set(ids)) == len(ids)
    for cid in ids:
        assert " " not in cid and "/" not in cid


def test_vocabulary_within_max_clips_bound() -> None:
    # Structural guard against an accidental combinatorial blow-up (issue #368 adversary finding):
    # the bake must stay bounded, machine-enforced, not by convention.
    assert len(vocab.vocabulary()) <= vocab.MAX_CLIPS


def test_register_axis_is_present_and_bounded() -> None:
    # The register (intensity tier) is a real key axis, and every stem's register is a known tier.
    regs = {p.register for p in vocab.vocabulary()}
    assert regs <= set(vocab.REGISTERS)
    assert "critical" in regs and "calm" in regs  # the headline escalation exists
    # No (kind, urgency) lists ALL three registers (the anti-blowup cap) — a cue never needs every
    # tier; terse act cues escalate firm→critical, heads-ups stay calm.
    from collections import defaultdict

    by_ku: dict[tuple[str, str], set[str]] = defaultdict(set)
    for kind, urg, reg in vocab._STEMS:
        by_ku[(kind, urg)].add(reg)
    for ku, rset in by_ku.items():
        assert len(rset) < len(vocab.REGISTERS), f"{ku} bakes all registers — unbounded"


def test_clip_id_format_and_corner_words() -> None:
    assert vocab.clip_id_for("late_brake", "act", "firm", None) == "late_brake.act.firm.generic"
    assert vocab.clip_id_for("late_brake", "prepare", "calm", 3) == "late_brake.prepare.calm.t03"
    # 1-based spoken numbers map to words on the per-corner (anticipatory) clips
    t3 = next(p for p in vocab.vocabulary() if p.clip_id == "late_brake.prepare.calm.t03")
    assert "turn three" in t3.text
    assert t3.text.startswith("Brake")
    # the terse act tier carries NO corner number (≤450 ms / issue #368 AC c)
    crit = next(p for p in vocab.vocabulary() if p.clip_id == "late_brake.act.critical.generic")
    assert "turn" not in crit.text.lower()


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
    patched[("late_brake", "act", "firm")] = "Hit the brakes!"
    monkeypatch.setattr(vocab, "_STEMS", patched)
    assert vocab.vocabulary_hash() != before
