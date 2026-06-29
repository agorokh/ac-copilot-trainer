"""Tests for the advisory->utterance resolver (tools.ai_sidecar.voice.resolver)."""

from __future__ import annotations

from _voice_support import build_manifest, make_advisory

from tools.ai_sidecar.realtime_observer import Advisory
from tools.ai_sidecar.voice.resolver import Resolver


def test_resolve_anticipatory_brake_maps_corner_0based_to_1based() -> None:
    r = Resolver(build_manifest())
    # The anticipatory (prepare/calm) cue carries the corner: corner=2 (0-based) -> "t03".
    utt = r.resolve(make_advisory(kind="late_brake", urgency="prepare", register="calm", corner=2))
    assert utt is not None
    assert utt.clip_id == "late_brake.prepare.calm.t03"
    assert utt.urgency == "prepare"
    assert utt.register == "calm"
    assert utt.dedup_key == "late_brake:2:calm"
    assert "turn three" in utt.text


def test_act_cue_is_terse_corner_dropped() -> None:
    r = Resolver(build_manifest())
    # An act/firm cue for a numbered corner resolves to the TERSE generic clip (no corner number).
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", register="firm", corner=2))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.firm.generic"
    assert utt.corner is None
    assert utt.register == "firm"
    assert utt.dedup_key == "late_brake:2:firm"  # dedup still tracks the real corner + register
    assert "turn" not in utt.text.lower()


def test_legacy_act_cue_without_register_resolves_to_playable_firm() -> None:
    r = Resolver(build_manifest())
    advisory = Advisory(
        kind="late_brake",
        corner=2,
        spline=0.5,
        urgency="act",
        message="Brake now",
    )

    utt = r.resolve(advisory)

    assert utt is not None
    assert utt.clip_id == "late_brake.act.firm.generic"
    assert utt.register == "firm"
    assert utt.dedup_key == "late_brake:2:calm"


def test_register_fallback_critical_to_firm() -> None:
    # If the bank has no clip for the requested tier, fall back toward calm. Drop the critical clip
    # and a critical advisory resolves to the firm clip (audible, never silent), and
    # Utterance.register reports the tier that ACTUALLY played.
    m = build_manifest()
    del m.clips["late_brake.act.critical.generic"]
    m.__post_init__()
    r = Resolver(m)
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", register="critical", corner=2))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.firm.generic"
    assert utt.register == "firm"  # resolved tier, not the requested "critical"
    assert utt.dedup_key == "late_brake:2:critical"  # dedup keyed on REQUESTED tier (escalation)


def test_resolve_apex_deficit_info() -> None:
    r = Resolver(build_manifest())
    utt = r.resolve(make_advisory(kind="apex_deficit", urgency="info", register="calm", corner=0))
    assert utt is not None
    assert utt.clip_id == "apex_deficit.info.calm.t01"
    assert utt.corner == 1


def test_corner_beyond_range_falls_back_to_generic() -> None:
    r = Resolver(build_manifest())
    # corner=49 (0-based) -> spoken 50 -> out of MAX_CORNER → generic clip, still speaks the verb.
    utt = r.resolve(make_advisory(kind="late_brake", urgency="prepare", register="calm", corner=49))
    assert utt is not None
    assert utt.clip_id == "late_brake.prepare.calm.generic"
    assert utt.corner is None
    # dedup key still tracks the real corner so repeats in the same pass collapse
    assert utt.dedup_key == "late_brake:49:calm"


def test_unknown_kind_urgency_or_register_returns_none() -> None:
    r = Resolver(build_manifest())
    assert r.resolve(make_advisory(kind="oversteer", urgency="act", corner=1)) is None
    assert r.resolve(make_advisory(kind="late_brake", urgency="scream", corner=1)) is None
    assert r.resolve(make_advisory(kind="late_brake", urgency="act", register="panic")) is None


def test_non_integer_corner_uses_generic() -> None:
    r = Resolver(build_manifest())
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", register="firm", corner=None))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.firm.generic"


def test_missing_clip_in_bank_returns_none() -> None:
    # A manifest with every fallback entry removed → resolver degrades to None (no wrong clip).
    m = build_manifest()
    for cid in ("late_brake.act.firm.generic", "late_brake.act.calm.generic"):
        m.clips.pop(cid, None)
    m.__post_init__()
    r = Resolver(m)
    assert (
        r.resolve(make_advisory(kind="late_brake", urgency="act", register="firm", corner=2))
        is None
    )
