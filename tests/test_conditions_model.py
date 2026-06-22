"""Tests for the conditions→grip model (tools.ai_sidecar.conditions_model)."""

from __future__ import annotations

from tools.ai_sidecar.conditions_model import (
    analyze_conditions,
    conditions_from_lap_archive,
)


def _cond(grip=0.98, track=30.0, ambient=22.0, weather="dry"):
    return {
        "trackGripLevel": grip,
        "trackTempC": track,
        "ambientTempC": ambient,
        "weatherType": weather,
    }


# --- regime gating ----------------------------------------------------------
def test_wet_regime_disables_slick_model():
    r = analyze_conditions(_cond(weather="light_rain", track=18.0))
    assert r.regime == "wet"
    assert r.slick_model_valid is False
    f = next(f for f in r.findings if f.key == "wet_regime")
    assert "do not" in f.coaching.lower() and "build heat" in f.coaching.lower()
    # cold-track slick advice must NOT fire in the wet
    assert not any(f.key == "cold_track" for f in r.findings)


def test_dry_regime_detected_defensively():
    assert analyze_conditions(_cond(weather="Clear")).regime == "dry"
    assert analyze_conditions(_cond(weather="overcast")).regime == "dry"
    assert analyze_conditions(_cond(weather="Heavy Rain")).regime == "wet"


def test_null_weather_is_unknown_not_dry():
    r = analyze_conditions(_cond(weather=None))
    assert r.regime == "unknown"
    assert r.slick_model_valid is True  # unknown is treated as not-wet for slick logic


# --- trackGripLevel bands ---------------------------------------------------
def test_green_track_flagged():
    r = analyze_conditions(_cond(grip=0.90))
    assert r.grip_band == "green"
    assert any(f.key == "green_track" for f in r.findings)


def test_rubbered_track_is_reference_quality():
    r = analyze_conditions(_cond(grip=0.99))
    assert r.grip_band == "rubbered"
    assert any(f.key == "rubbered_track" for f in r.findings)


def test_grip_out_of_sane_range_flags_investigate():
    r = analyze_conditions(_cond(grip=0.5))
    assert any(f.key == "grip_out_of_range" and f.approximate for f in r.findings)


# --- normalization (approximate) -------------------------------------------
def test_normalizer_is_track_grip_clamped():
    assert analyze_conditions(_cond(grip=0.97)).normalizer() == 0.97
    assert analyze_conditions(_cond(grip=None)).normalizer() == 1.0  # unknown -> neutral
    assert analyze_conditions(_cond(grip=2.0)).normalizer() == 1.05  # clamped to sane ceiling


def test_grip_delta_skipped_across_mismatched_regimes():
    # codex #283: dry current vs WET reference — a trackGripLevel delta is meaningless, so skip it.
    r = analyze_conditions(
        _cond(grip=0.97, weather="dry"),
        reference_conditions=_cond(grip=0.90, weather="rain"),
    )
    assert r.grip_level_delta is None
    assert not any(f.key == "grip_vs_reference" for f in r.findings)


def test_wet_to_wet_grip_delta_suppressed():
    # codex #283: trackGripLevel comparison doesn't transfer in the wet, even wet-vs-wet.
    r = analyze_conditions(
        _cond(grip=0.95, weather="rain"), reference_conditions=_cond(grip=0.92, weather="rain")
    )
    assert r.grip_level_delta is None


def test_out_of_range_grip_skips_delta():
    # codex #283: if either grip scalar is outside the sane band, the delta is unreliable -> skip.
    r = analyze_conditions(_cond(grip=0.5), reference_conditions=_cond(grip=0.99))
    assert r.grip_level_delta is None


def test_reference_temp_note_gated_by_regime():
    # codex #283: a dry-current vs WET-reference track-temp comparison must not fire.
    r = analyze_conditions(
        _cond(track=20.0, weather="dry"),
        reference_conditions=_cond(track=34.0, weather="rain"),
    )
    assert not any(f.key == "track_temp_vs_reference" for f in r.findings)


def test_grip_vs_reference_is_labeled_approximate():
    r = analyze_conditions(_cond(grip=0.94), reference_conditions=_cond(grip=0.99))
    assert r.grip_level_delta is not None and r.grip_level_delta < 0
    f = next(f for f in r.findings if f.key == "grip_vs_reference")
    assert f.approximate is True
    assert "approximate" in f.coaching.lower()


# --- temperature is QUALITATIVE only ----------------------------------------
def test_cold_track_is_qualitative_no_grip_number():
    r = analyze_conditions(_cond(track=15.0))
    f = next(f for f in r.findings if f.key == "cold_track")
    assert f.approximate is True
    # no fabricated grip percentage anywhere in the coaching
    assert "%" not in f.coaching


def test_null_track_temp_guarded():
    r = analyze_conditions(_cond(track=None))
    assert r.track_temp_c is None
    assert any(f.key == "no_track_temp" for f in r.findings)
    assert not any(f.key in ("cold_track", "hot_track") for f in r.findings)


def test_track_temp_vs_reference_direction_only():
    r = analyze_conditions(_cond(track=20.0), reference_conditions=_cond(track=32.0))
    f = next(f for f in r.findings if f.key == "track_temp_vs_reference")
    assert "colder" in f.summary
    assert "%" not in f.coaching  # direction only, no quantified grip change


# --- archive integration ----------------------------------------------------
def test_conditions_from_lap_archive():
    archive = {"conditions": _cond(grip=0.96, track=28.0)}
    ref = {"conditions": _cond(grip=0.99, track=34.0)}
    r = conditions_from_lap_archive(archive, reference_archive=ref)
    assert r.regime == "dry"
    assert r.grip_level == 0.96
    assert r.grip_level_delta is not None


def test_conditions_from_archive_missing_block():
    r = conditions_from_lap_archive({"lap": {}})
    assert r.regime == "unknown"
    assert r.grip_level is None
