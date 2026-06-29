"""Tests for the pure voice cue layer (advisory -> phrase + arbitration). No audio, any OS."""

from __future__ import annotations

from tools.ai_sidecar.voice.cue import CueArbiter, SpokenCue, advisory_to_phrase


def _adv(
    kind: str, corner: int, urgency: str, register: str = "calm", **detail: object
) -> dict[str, object]:
    return {
        "kind": kind,
        "corner": corner,
        "urgency": urgency,
        "register": register,
        "detail": detail,
        "message": "m",
    }


def test_advisory_to_phrase_is_register_aware_and_terse():
    # the act tier (firm/critical) is terse + corner-less; the calm anticipatory tier keeps the
    # corner number.
    assert advisory_to_phrase(_adv("late_brake", 3, "act", register="firm")) == "Brake."
    assert advisory_to_phrase(_adv("late_brake", 3, "act", register="critical")) == "Brake!"
    assert (
        advisory_to_phrase(_adv("late_brake", 3, "prepare", register="calm"))
        == "Brake point, Turn 4."
    )
    assert advisory_to_phrase(_adv("brake_release", 0, "act", register="firm")) == "Release."
    assert advisory_to_phrase(_adv("apex_deficit", 6, "info")) == "More entry speed, Turn 7."


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
    cue = arb.select(
        [_adv("apex_deficit", 1, "info"), _adv("late_brake", 2, "act", register="firm")],
        now_s=0.0,
    )
    assert isinstance(cue, SpokenCue)
    assert cue.kind == "late_brake"  # 'act' beats 'info'
    assert cue.register == "firm"  # register carried through for the WS speaker
    assert cue.text == "Brake."  # terse act phrasing


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
    # A non-urgent (info) cue is anti-nag throttled by the per-corner cooldown.
    arb = CueArbiter(global_cooldown_s=0.0, corner_cooldown_s=6.0)
    assert arb.select([_adv("apex_deficit", 4, "info")], now_s=0.0) is not None
    # same corner+kind again within the per-corner cooldown -> suppressed
    assert arb.select([_adv("apex_deficit", 4, "info")], now_s=3.0) is None
    # after the per-corner cooldown it may fire again
    assert arb.select([_adv("apex_deficit", 4, "info")], now_s=7.0) is not None


def test_arbiter_act_escalation_bypasses_corner_cooldown():
    # codex review #371: a critical/firm "Brake!" escalation must be heard even within the corner
    # anti-nag window after an earlier calm lead-in for the SAME corner.
    arb = CueArbiter(global_cooldown_s=0.0, corner_cooldown_s=6.0)
    assert arb.select([_adv("late_brake", 4, "prepare", register="calm")], now_s=0.0) is not None
    esc = arb.select([_adv("late_brake", 4, "act", register="critical")], now_s=2.0)
    assert esc is not None and esc.register == "critical"  # not suppressed by the corner cooldown


def test_arbiter_empty_is_silent():
    assert CueArbiter().select([], now_s=0.0) is None


def test_arbiter_holds_info_cue_until_spline_lookahead_window():
    arb = CueArbiter(global_cooldown_s=0.0, corner_cooldown_s=0.0)
    far = {
        "kind": "apex_deficit",
        "corner": 1,
        "urgency": "info",
        "spline": 0.50,
        "car_spline": 0.40,
        "car_speed_kmh": 120.0,
        "message": "m",
    }
    assert arb.select([far], now_s=0.0) is None
    near = dict(far)
    near["car_spline"] = 0.495
    assert arb.select([near], now_s=0.0) is not None
