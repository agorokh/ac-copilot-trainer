"""Tests for the Track Titan CoachingOracle parser (pure; runs on any OS, no Windows/OCR)."""

from __future__ import annotations

from tools.ai_sidecar.coach_handoff import CAUSE_CLASSES
from tools.ai_sidecar.coaching_oracle import (
    FALLBACK_LAYOUT,
    CoachingSnapshot,
    _coerce_lines,
    debrief_to_advisories,
    parse_overlay_text,
    select_layout,
)

# Real OCR captured live this session (AG_PC, magione, Cayman GT4) — the regression fixture.
# Upscaled debrief crop (clean):
CAPTURED_DEBRIEF = [
    "ACTIVE SUGGESTION",
    "DRIVE A LAP",
    "REFERENCE WILL APPEAR",
    "Post-lap debrief (lap 1, 188354 s). Focus areas from on-track coaching: Full throttle only 0% of",  # noqa: E501
    "lap — focus on earlier power applicate.",
]
# Full-screen OCR (noisier — includes tyre psi that must NOT be mistaken for the lap delta):
CAPTURED_FULL = [
    "Current:",
    "Last:",
    "5:49.254",
    "3:08.354",
    "Best:",
    "Record:",
    "3:08.354",
    "3:08.354",
    "ACTIVE SUGGESTION",
    "DRIVE A LAP",
    "REFERENCE WILL APPEAR",
    'St-lap debrief (lap 1883" s). Focus areas from on-trad coaching: Full throttle only Of',
    "lap — on earlier power",
    "Comp: H",
    "Laps: 2",
    "-9.5 psi",
    "gooc",
    "100%",
    "-9.6 psi",
    "100%",
    "+ 0.657",
    "OSS",
    "KMH",
    "FUEL",
    "30.00",
    "WAITING",
    "DISTANCE TO BRAKING POINT",
    "TARGET ENTRY",
    "EST. LAP -",
]


def test_parse_extracts_debrief_delta_and_meta():
    snap = parse_overlay_text(CAPTURED_FULL, CAPTURED_DEBRIEF, captured_utc="2026-06-27T00:00:00Z")
    assert isinstance(snap, CoachingSnapshot)
    assert snap.source == "track_titan"
    assert snap.suggestion_state == "post_lap_debrief"
    assert snap.debrief_text is not None and "debrief" in snap.debrief_text.lower()
    assert "earlier power" in snap.debrief_text
    # The lap delta is +0.657 — NOT the -9.5 tyre psi (3-decimal + magnitude filter).
    assert snap.delta_gainloss_s == 0.657
    assert snap.tyre_compound == "H"
    assert "3:08.354" in snap.lap_times_s
    assert "throttle" in snap.focus_areas


def test_delta_ignores_tyre_psi_only():
    # psi present, no lap delta -> delta is None (never grabs the 1-decimal psi).
    snap = parse_overlay_text(["-9.5 psi", "100%", "Comp: H"])
    assert snap.delta_gainloss_s is None


def test_awaiting_valid_lap_state():
    snap = parse_overlay_text(["ACTIVE SUGGESTION", "DRIVE A LAP", "REFERENCE WILL APPEAR"])
    assert snap.suggestion_state == "awaiting_valid_lap"
    assert snap.debrief_text is None
    assert snap.advisories == []


def test_advisories_are_technique_only_no_setup_delta():
    snap = parse_overlay_text(CAPTURED_FULL, CAPTURED_DEBRIEF)
    assert snap.advisories, "expected advisories from the debrief focus areas"
    for adv in snap.advisories:
        assert adv["cause_class"] == "technique"
        assert adv["cause_class"] in CAUSE_CLASSES
        assert adv["suggested_setup_delta"] is None  # never fabricate a setup change from TT text
        assert adv["source"] == "track_titan"
        assert isinstance(adv["coaching"], str) and adv["coaching"]


def test_debrief_to_advisories_falls_back_to_debrief_text():
    # A debrief with no recognized focus keyword still yields one advisory carrying the text.
    snap = CoachingSnapshot(
        source="track_titan",
        suggestion_state="post_lap_debrief",
        debrief_text="Post-lap debrief: tidy up your mid-corner balance.",
        focus_areas=[],
    )
    advs = debrief_to_advisories(snap)
    assert len(advs) == 1
    assert advs[0]["coaching"] == snap.debrief_text
    assert advs[0]["suggested_setup_delta"] is None


def test_multidigit_minute_lap_time_kept_intact():
    # Regression: the minute field may be 2 digits (10:03.123) — must not drop the first digit.
    snap = parse_overlay_text(["Best:", "10:03.123", "Last:", "9:58.700"])
    assert "10:03.123" in snap.lap_times_s
    assert "9:58.700" in snap.lap_times_s


def test_advisories_gated_on_debrief_not_live_hud_labels():
    # Live HUD labels (THROTTLE/BRAKE) with no post-lap debrief must NOT mint advice.
    snap = parse_overlay_text(["THROTTLE", "BRAKE", "REFERENCE WILL APPEAR"])
    assert snap.suggestion_state == "awaiting_valid_lap"
    assert snap.focus_areas == []
    assert snap.advisories == []


def test_debrief_match_is_bounded_not_greedy_over_full_screen():
    # Full-screen fallback must bound the debrief to its ~2 lines, not swallow trailing HUD text.
    full = [
        "Post-lap debrief (lap 2, 95.1 s). Focus areas: brake earlier into T1",
        "and carry more apex speed.",
        "Comp: H",
        "OIL TMP 99",
        "EST. LAP -",
    ]
    snap = parse_overlay_text(full)
    assert snap.debrief_text is not None
    assert "apex speed" in snap.debrief_text
    assert "OIL TMP" not in snap.debrief_text  # trailing HUD not swallowed


def test_extract_debrief_split_marker_fallback():
    # Marker split across two OCR lines -> the fallback 2-line window still finds it.
    snap = parse_overlay_text(["post-lap", "debrief: brake earlier"])
    assert snap.debrief_text is not None
    assert "debrief" in snap.debrief_text.lower()


def test_bare_debrief_word_is_not_a_real_debrief():
    # Only a genuine "post-lap/st-lap debrief" marker counts — a stray "debrief" token does not.
    snap = parse_overlay_text(["some debrief blurb", "THROTTLE", "BRAKE"])
    assert snap.debrief_text is None
    assert snap.focus_areas == []
    assert snap.advisories == []


def test_state_derived_from_crop_when_full_screen_empty():
    # If the full-screen OCR failed (empty) but the crop saw the suggestion, still derive the state.
    snap = parse_overlay_text([], ["REFERENCE WILL APPEAR"])
    assert snap.suggestion_state == "awaiting_valid_lap"


def test_select_layout_exact_and_fallback():
    assert select_layout(3440, 1440).name == "ag_pc_3440x1440"
    # Uncalibrated resolution -> generic fractional layout, not a wrong calibration.
    assert select_layout(1920, 1080) is FALLBACK_LAYOUT
    assert select_layout(1920, 1080).name == "generic"


def test_coerce_lines_flattens_and_stringifies():
    # Defensive against the OCR helper emitting nested/scalar/None arrays.
    assert _coerce_lines(None) == []
    assert _coerce_lines("x") == ["x"]
    assert _coerce_lines(["a", "b"]) == ["a", "b"]
    assert _coerce_lines([["a", "b"], "c"]) == ["a", "b", "c"]  # one-level nesting flattened
    assert _coerce_lines([1, None, 2]) == ["1", "2"]
    assert _coerce_lines([["a", None, "b"]]) == ["a", "b"]  # nested None dropped, not "None"


def test_spaced_post_lap_debrief_marker_recognized():
    snap = parse_overlay_text(["Post lap debrief: focus on earlier throttle application"])
    assert snap.suggestion_state == "post_lap_debrief"
    assert snap.debrief_text is not None
    assert "throttle" in snap.focus_areas


def test_empty_input_is_safe():
    snap = parse_overlay_text([])
    assert snap.suggestion_state == "unknown"
    assert snap.debrief_text is None
    assert snap.delta_gainloss_s is None
    assert snap.advisories == []


def test_get_coaching_returns_none_on_non_dict_json(monkeypatch):
    """Qodo: helper JSON must be a dict; list/scalar shapes return None."""
    import tools.ai_sidecar.coaching_oracle as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_primary_screen_size", lambda: (0, 0))

    class _Proc:
        returncode = 0
        stdout = '["not","a","dict"]'
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc())
    assert mod.TrackTitanScreenOracle().get_coaching() is None


def test_get_coaching_returns_none_when_parse_raises(monkeypatch):
    """Qodo: parse failures must not escape get_coaching's None-on-failure contract."""
    import tools.ai_sidecar.coaching_oracle as mod

    monkeypatch.setattr(mod.sys, "platform", "win32")
    monkeypatch.setattr(mod, "_primary_screen_size", lambda: (0, 0))

    class _Proc:
        returncode = 0
        stdout = '{"full_lines":["x"],"debrief_lines":[]}'
        stderr = ""

    def _boom(*a, **k):
        raise TypeError("simulated parse failure")

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(mod, "parse_overlay_text", _boom)
    assert mod.TrackTitanScreenOracle().get_coaching() is None
