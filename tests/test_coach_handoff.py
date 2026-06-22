"""Tests for the structured coach-handoff protocol (tools.ai_sidecar.coach_handoff)."""

from __future__ import annotations

from tools.ai_sidecar.coach_handoff import COACH_HANDOFF_VERSION, build_coach_handoff
from tools.ai_sidecar.setup_model import from_snapshot


def _attr(key, cause_class, **kw):
    base = {
        "key": key,
        "symptom": kw.get("symptom", key),
        "phase": kw.get("phase", "entry"),
        "cause_class": cause_class,
        "confidence": kw.get("confidence", 0.8),
        "advisory": kw.get("advisory", False),
        "coaching": kw.get("coaching", "do the thing"),
        "setup_causes": kw.get("setup_causes", []),
        "technique_causes": kw.get("technique_causes", []),
    }
    return base


def _structured(corners, *, car="ks_porsche_911_gt3_r_2016", track="magione"):
    return {
        "text": "debrief",
        "car_id": car,
        "track_id": track,
        "balance": {"verdict": "mechanical_all_speed", "lever_class": "mechanical"},
        "corners": corners,
    }


SETUP = from_snapshot({"FRONT_BIAS.VALUE": "66", "DIFF_POWER.VALUE": "45", "TYRES.VALUE": "1"})


def test_envelope_is_versioned_and_well_formed_even_when_empty():
    h = build_coach_handoff(None, lap=3)
    assert h["v"] == COACH_HANDOFF_VERSION
    assert h["lap"] == 3
    assert h["corners"] == []
    assert h["total_time_lost_s"] is None
    assert h["top_focus_corner"] is None


def test_braking_loss_suggests_front_bias_rearward_for_911():
    # real brain output for braking is "setup+technique" (both causes present) — use the real value
    corners = [
        {
            "index": 0,
            "apex_spline": 0.3,
            "time_loss_s": 0.4,
            "headline": "C0",
            "attributions": [_attr("braking_phase_loss", "setup+technique", advisory=True)],
        }
    ]
    h = build_coach_handoff(_structured(corners), setup=SETUP)
    c = h["corners"][0]
    assert c["cause_class"] == "setup+technique"  # mixed class forwarded verbatim (v1 enum)
    d = c["suggested_setup_delta"]
    assert d["section"] == "FRONT_BIAS"
    assert d["direction"] == "decrease"  # suspected + 911 + 66% > 58% -> rearward
    assert "50-56" in d["rationale"]
    assert c["advisory"] is True


def test_braking_bias_decrease_is_gated_to_the_911():
    # a non-911 car with the same high bias must NOT get the 911-specific rearward advice
    corners = [
        {
            "index": 0,
            "apex_spline": 0.3,
            "time_loss_s": 0.4,
            "headline": "C0",
            "attributions": [_attr("braking_phase_loss", "setup+technique", advisory=True)],
        }
    ]
    h = build_coach_handoff(_structured(corners, car="ferrari_488_gt3"), setup=SETUP)
    d = h["corners"][0]["suggested_setup_delta"]
    assert d["section"] == "FRONT_BIAS"
    assert d["direction"] == "investigate"  # not "decrease" — car-specific target
    assert "50-56" not in d["rationale"]


def test_confirmed_braking_defers_to_the_brain_not_the_bias_number():
    # advisory=False -> per-wheel slip confirmed the axle; do NOT guess "decrease" from bias alone
    corners = [
        {
            "index": 0,
            "apex_spline": 0.3,
            "time_loss_s": 0.4,
            "headline": "C0",
            "attributions": [_attr("braking_phase_loss", "setup+technique", advisory=False)],
        }
    ]
    h = build_coach_handoff(_structured(corners), setup=SETUP)  # 911, bias 66 > 58
    d = h["corners"][0]["suggested_setup_delta"]
    assert d["direction"] == "investigate"  # respects the confirmed diagnosis
    assert "FORWARD" in d["rationale"] or "follow" in d["rationale"].lower()


def test_technique_corner_suggests_no_setup_change():
    corners = [
        {
            "index": 1,
            "apex_spline": 0.5,
            "time_loss_s": 0.2,
            "headline": "C1",
            "attributions": [_attr("entry_speed_left", "technique")],
        }
    ]
    h = build_coach_handoff(_structured(corners), setup=SETUP)
    assert h["corners"][0]["suggested_setup_delta"] is None


def test_grip_limited_suggests_grip_levers():
    corners = [
        {
            "index": 2,
            "apex_spline": 0.7,
            "time_loss_s": 0.1,
            "headline": "C2",
            "attributions": [_attr("grip_limited", "grip")],
        }
    ]
    d = build_coach_handoff(_structured(corners), setup=SETUP)["corners"][0][
        "suggested_setup_delta"
    ]
    assert d["direction"] == "increase_grip"
    assert "TYRES" in d["section"] or "WING" in d["section"]


def test_lap_summary_picks_biggest_time_loss():
    corners = [
        {
            "index": 0,
            "apex_spline": 0.1,
            "time_loss_s": 0.15,
            "headline": "C0",
            "attributions": [_attr("entry_speed_left", "technique")],
        },
        {
            "index": 1,
            "apex_spline": 0.4,
            "time_loss_s": 0.55,
            "headline": "C1",
            "attributions": [_attr("braking_phase_loss", "setup")],
        },
        {"index": 2, "apex_spline": 0.8, "time_loss_s": 0.0, "headline": "C2", "attributions": []},
    ]
    h = build_coach_handoff(_structured(corners), setup=SETUP, lap=5)
    assert h["top_focus_corner"] == 1  # biggest loser
    assert h["total_time_lost_s"] == 0.7  # 0.15 + 0.55 (the 0.0 corner excluded)
    assert h["corners"][2]["cause_class"] == "none"  # no attributions -> on pace


def test_braking_loss_without_setup_is_investigate():
    corners = [
        {
            "index": 0,
            "apex_spline": 0.3,
            "time_loss_s": 0.4,
            "headline": "C0",
            "attributions": [_attr("braking_phase_loss", "setup")],
        },
    ]
    # no CarSetup supplied -> can't read bias -> "investigate", not a specific direction
    corners[0]["attributions"][0]["advisory"] = True  # suspected, but no bias data
    d = build_coach_handoff(_structured(corners))["corners"][0]["suggested_setup_delta"]
    assert d["section"] == "FRONT_BIAS"
    assert d["direction"] == "investigate"


def test_end_to_end_from_build_structured_debrief():
    # integration: the real brain output flows into the handoff envelope
    import math

    from tools.ai_sidecar.coach_report import build_structured_debrief

    n = 110
    kappa = [0.0] * 40 + [1 / 30] * 30 + [0.0] * 40
    theta = x = z = 0.0
    xs, zs = [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * 2.0
        x += 2.0 * math.cos(theta)
        z += 2.0 * math.sin(theta)
    v = [55.0 if i < 25 or i > 75 else 25.0 for i in range(n)]
    t_ms, t = [0.0], 0.0
    for i in range(1, n):
        t += 2.0 / max(0.5, 0.5 * (v[i] + v[i - 1]))
        t_ms.append(t * 1000)
    fields = ["spline", "speed", "eMs", "throttle", "brake", "steer", "gear", "px", "py", "pz"]
    samples = [
        [
            i / (n - 1),
            v[i] * 3.6,
            t_ms[i],
            1.0 if i > 55 else 0.0,
            0.8 if 25 <= i < 55 else 0.0,
            0.4 if 40 <= i < 70 else 0.0,
            4,
            xs[i],
            0.0,
            zs[i],
        ]
        for i in range(n)
    ]
    archive = {
        "car": {"id": "x"},
        "track": {"id": "magione"},
        "setup": {"snapshot": {"FRONT_BIAS.VALUE": "66"}},
        "trace": {"fields": fields, "samples": samples},
    }
    structured = build_structured_debrief(archive, grip_ceiling_g=2.5)
    h = build_coach_handoff(structured, lap=1)
    assert h["v"] == COACH_HANDOFF_VERSION
    assert isinstance(h["corners"], list) and h["corners"]
