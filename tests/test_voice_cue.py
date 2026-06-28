"""Tests for the pure voice cue layer (advisory -> phrase + arbitration). No audio, any OS."""

from __future__ import annotations

from tools.ai_sidecar.voice.cue import CueArbiter, SpokenCue, advisory_to_phrase


def _adv(kind: str, corner: int, urgency: str, **detail: object) -> dict[str, object]:
    return {"kind": kind, "corner": corner, "urgency": urgency, "detail": detail, "message": "m"}


def test_advisory_to_phrase_is_short_and_turn_anchored():
    assert advisory_to_phrase(_adv("late_brake", 3, "act")) == "Brake, Turn 4."
    assert advisory_to_phrase(_adv("apex_deficit", 6, "info")) == "Carry more speed, Turn 7."


def test_advisory_to_phrase_unknown_kind_falls_back_to_message():
    assert (
        advisory_to_phrase({"kind": "weird", "corner": 0, "message": "Do the thing"})
        == "Do the thing"
    )


def test_advisory_to_phrase_handles_bad_corner():
    assert "this corner" in advisory_to_phrase(
        {"kind": "late_brake", "corner": None, "message": ""}
    )


def test_arbiter_speaks_one_cue_highest_urgency():
    arb = CueArbiter()
    cue = arb.select([_adv("apex_deficit", 1, "info"), _adv("late_brake", 2, "act")], now_s=0.0)
    assert isinstance(cue, SpokenCue)
    assert cue.kind == "late_brake"  # 'act' beats 'info'
    assert cue.text == "Brake, Turn 3."


def test_arbiter_global_cooldown_suppresses_non_urgent():
    arb = CueArbiter(global_cooldown_s=2.5)
    first = arb.select([_adv("apex_deficit", 1, "info")], now_s=0.0)
    assert first is not None
    # within the global cooldown, a non-urgent cue stays silent
    assert arb.select([_adv("apex_deficit", 2, "info")], now_s=1.0) is None


def test_arbiter_act_barges_in_through_global_cooldown():
    arb = CueArbiter(global_cooldown_s=2.5)
    assert arb.select([_adv("apex_deficit", 1, "info")], now_s=0.0) is not None
    barge = arb.select([_adv("late_brake", 2, "act")], now_s=0.8)  # within cooldown but urgent
    assert barge is not None and barge.kind == "late_brake"


def test_arbiter_per_corner_cooldown_avoids_nagging():
    arb = CueArbiter(global_cooldown_s=0.0, corner_cooldown_s=6.0)
    assert arb.select([_adv("late_brake", 4, "act")], now_s=0.0) is not None
    # same corner+kind again within the per-corner cooldown -> suppressed
    assert arb.select([_adv("late_brake", 4, "act")], now_s=3.0) is None
    # after the per-corner cooldown it may fire again
    assert arb.select([_adv("late_brake", 4, "act")], now_s=7.0) is not None


def test_arbiter_empty_is_silent():
    assert CueArbiter().select([], now_s=0.0) is None
