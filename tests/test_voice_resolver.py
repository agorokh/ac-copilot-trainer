"""Tests for the advisory->utterance resolver (tools.ai_sidecar.voice.resolver)."""

from __future__ import annotations

from _voice_support import build_manifest, make_advisory

from tools.ai_sidecar.voice.resolver import Resolver


def test_resolve_late_brake_act_maps_corner_0based_to_1based() -> None:
    r = Resolver(build_manifest())
    # Advisory.corner is 0-based; T-label and clip are 1-based → corner=2 -> "t03".
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", corner=2))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.t03"
    assert utt.urgency == "act"
    assert utt.dedup_key == "late_brake:2"
    assert "turn three" in utt.text


def test_resolve_apex_deficit_info() -> None:
    r = Resolver(build_manifest())
    utt = r.resolve(make_advisory(kind="apex_deficit", urgency="info", corner=0))
    assert utt is not None
    assert utt.clip_id == "apex_deficit.info.t01"
    assert utt.corner == 1


def test_corner_beyond_range_falls_back_to_generic() -> None:
    r = Resolver(build_manifest())
    # corner=49 (0-based) -> spoken 50 -> out of MAX_CORNER → generic clip, still speaks the verb.
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", corner=49))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.generic"
    assert utt.corner is None
    # dedup key still tracks the real corner so repeats in the same pass collapse
    assert utt.dedup_key == "late_brake:49"


def test_unknown_kind_or_urgency_returns_none() -> None:
    r = Resolver(build_manifest())
    assert r.resolve(make_advisory(kind="oversteer", urgency="act", corner=1)) is None
    assert r.resolve(make_advisory(kind="late_brake", urgency="scream", corner=1)) is None


def test_non_integer_corner_uses_generic() -> None:
    r = Resolver(build_manifest())
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", corner=None))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.generic"


def test_missing_clip_in_bank_returns_none() -> None:
    # A manifest with the wanted entry removed → resolver degrades to None (no wrong clip).
    m = build_manifest()
    del m.clips["late_brake.act.t03"]
    # rebuild the index after mutating clips
    m.__post_init__()
    del m.clips["late_brake.act.generic"]
    m.__post_init__()
    r = Resolver(m)
    assert r.resolve(make_advisory(kind="late_brake", urgency="act", corner=2)) is None
