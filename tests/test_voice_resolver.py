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


def test_second_zone_of_a_merged_corner_gets_its_own_dedup_key() -> None:
    """#522 coverage: a merged esses corner emits one heads-up PER BRAKE ZONE inside the 8 s
    dedup window — a later zone's cue must not be swallowed as a repeat of the first."""
    r = Resolver(build_manifest())
    z0 = r.resolve(
        make_advisory(
            kind="late_brake", urgency="prepare", register="calm", corner=2, detail={"zone": 0}
        )
    )
    z1 = r.resolve(
        make_advisory(
            kind="late_brake", urgency="prepare", register="calm", corner=2, detail={"zone": 1}
        )
    )
    assert z0 is not None and z1 is not None
    assert z0.dedup_key == "late_brake:2:calm"  # zone 0 keeps the pre-#522 key shape
    assert z1.dedup_key == "late_brake:2z1:calm"
    assert z0.dedup_key != z1.dedup_key


def test_act_cue_is_terse_corner_dropped() -> None:
    r = Resolver(build_manifest())
    # An act/urgent cue for a numbered corner resolves to the TERSE generic clip (no corner number).
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", register="urgent", corner=2))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.urgent.generic"
    assert utt.corner is None
    assert utt.register == "urgent"
    assert utt.dedup_key == "late_brake:2:urgent"  # dedup still tracks corner + register
    assert "turn" not in utt.text.lower()


def test_legacy_firm_register_alias_resolves_to_urgent() -> None:
    r = Resolver(build_manifest())
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", register="firm", corner=2))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.urgent.generic"
    assert utt.register == "urgent"
    assert utt.dedup_key == "late_brake:2:urgent"


def test_legacy_act_cue_without_register_resolves_to_playable_urgent() -> None:
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
    assert utt.clip_id == "late_brake.act.urgent.generic"
    assert utt.register == "urgent"
    assert utt.dedup_key == "late_brake:2:calm"


def test_register_fallback_critical_to_urgent() -> None:
    # If the bank has no clip for the requested tier, fall back toward calm. Drop the critical clip
    # and a critical advisory resolves to the urgent clip (audible, never silent), and
    # Utterance.register reports the tier that ACTUALLY played.
    m = build_manifest()
    del m.clips["late_brake.act.critical.generic"]
    m.__post_init__()
    r = Resolver(m)
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", register="critical", corner=2))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.urgent.generic"
    assert utt.register == "urgent"  # resolved tier, not the requested "critical"
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
    utt = r.resolve(make_advisory(kind="late_brake", urgency="act", register="urgent", corner=None))
    assert utt is not None
    assert utt.clip_id == "late_brake.act.urgent.generic"


def test_missing_clip_in_bank_returns_none() -> None:
    # A manifest with every fallback entry removed → resolver degrades to None (no wrong clip).
    m = build_manifest()
    for cid in (
        "late_brake.act.urgent.generic",
        "late_brake.act.alert.generic",
        "late_brake.act.calm.generic",
    ):
        m.clips.pop(cid, None)
    m.__post_init__()
    r = Resolver(m)
    assert (
        r.resolve(make_advisory(kind="late_brake", urgency="act", register="urgent", corner=2))
        is None
    )
