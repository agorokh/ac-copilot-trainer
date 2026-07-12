"""Pure unit tests for the FFB calibration helpers (issue #533).

Covers the platform-independent halves of ``tools/ac_harness/ffb_calibrate``: the finalFF
sample summary, the gain recommendation math, the offset sanity gate, and the format-preserving
``user_ff.ini`` reader/writer. The launch + shared-memory sample loop is rig-only and excluded
from coverage there.
"""

from __future__ import annotations

import math

import pytest

from tools.ac_harness.ffb_calibrate import (
    FfbStats,
    offset_looks_valid,
    read_user_ff_value,
    recommend_gain,
    summarize,
    update_user_ff_value,
)


# --------------------------------------------------------------------------- summarize
def test_summarize_peak_rms_and_clip_fraction():
    stats = summarize([0.0, 0.5, -1.0, 1.0], clip_threshold=0.99)
    assert stats.n == 4
    assert stats.peak == pytest.approx(1.0)
    assert stats.rms == pytest.approx(math.sqrt((0 + 0.25 + 1 + 1) / 4))
    assert stats.clip_fraction == pytest.approx(0.5)  # -1.0 and 1.0 reach the clip threshold


def test_summarize_ignores_nan():
    stats = summarize([0.4, float("nan"), -0.4])
    assert stats.n == 2
    assert stats.peak == pytest.approx(0.4)


def test_summarize_empty_is_zeroed():
    stats = summarize([])
    assert stats == FfbStats(n=0, peak=0.0, rms=0.0, clip_fraction=0.0, clip_threshold=0.99)


# --------------------------------------------------------------------------- recommend_gain
def test_recommend_gain_scales_down_when_clipping():
    # Peak 1.0 at gain 1.0, target 0.9 -> reduce to 0.9.
    assert recommend_gain(1.0, 1.0, target_peak=0.90) == pytest.approx(0.90)


def test_recommend_gain_scales_up_when_weak():
    # Peak only 0.45 at gain 1.0, target 0.9 -> double to 2.0 (then hits ceiling 2.0 exactly).
    assert recommend_gain(1.0, 0.45, target_peak=0.90, ceiling=2.0) == pytest.approx(2.0)


def test_recommend_gain_clamps_to_floor():
    # A massively over-driven peak would push gain below the floor; it is clamped.
    assert recommend_gain(1.0, 10.0, target_peak=0.90, floor=0.30) == pytest.approx(0.30)


def test_recommend_gain_nonpositive_peak_returns_clamped_current():
    assert recommend_gain(1.5, 0.0) == pytest.approx(1.5)
    assert recommend_gain(5.0, 0.0, ceiling=2.0) == pytest.approx(2.0)  # current clamped to ceiling


def test_recommend_gain_rounds_to_three_decimals():
    val = recommend_gain(1.0, 0.7, target_peak=0.90)
    assert val == round(val, 3)


def test_recommend_gain_rejects_floor_above_ceiling():
    with pytest.raises(ValueError, match="floor .* must be <= ceiling"):
        recommend_gain(1.0, 0.5, floor=2.0, ceiling=1.0)


# --------------------------------------------------------------------------- offset gate
def test_offset_looks_valid_accepts_normal_signal():
    ok, _ = offset_looks_valid(
        FfbStats(n=1000, peak=0.85, rms=0.4, clip_fraction=0.01, clip_threshold=0.99)
    )
    assert ok is True


def test_offset_looks_valid_rejects_too_few_samples():
    ok, reason = offset_looks_valid(
        FfbStats(n=10, peak=0.8, rms=0.4, clip_fraction=0.0, clip_threshold=0.99)
    )
    assert ok is False
    assert "samples" in reason


def test_offset_looks_valid_rejects_out_of_range_peak():
    # A wrong byte offset reads garbage floats far outside [-1, 1].
    ok, reason = offset_looks_valid(
        FfbStats(n=1000, peak=42.0, rms=9.0, clip_fraction=0.0, clip_threshold=0.99)
    )
    assert ok is False
    assert "offset" in reason


def test_offset_looks_valid_rejects_silent_signal():
    ok, reason = offset_looks_valid(
        FfbStats(n=1000, peak=0.001, rms=0.0, clip_fraction=0.0, clip_threshold=0.99)
    )
    assert ok is False
    assert "silent" in reason


# --------------------------------------------------------------------------- user_ff.ini I/O
_SAMPLE = "[abarth500]\nVALUE=1.000\n[ks_porsche_911_rsr_2017]\nVALUE=1.053\n"


def test_read_user_ff_value_present():
    assert read_user_ff_value(_SAMPLE, "ks_porsche_911_rsr_2017") == pytest.approx(1.053)


def test_read_user_ff_value_absent_is_none():
    assert read_user_ff_value(_SAMPLE, "ks_bmw_m4") is None


def test_update_existing_value_preserves_other_cars():
    out = update_user_ff_value(_SAMPLE, "ks_porsche_911_rsr_2017", 0.912)
    assert "[abarth500]\nVALUE=1.000" in out  # untouched
    assert read_user_ff_value(out, "ks_porsche_911_rsr_2017") == pytest.approx(0.912)
    assert read_user_ff_value(out, "abarth500") == pytest.approx(1.000)


def test_update_appends_new_car_when_absent():
    out = update_user_ff_value(_SAMPLE, "bmw_m3_gt2", 1.234)
    assert read_user_ff_value(out, "bmw_m3_gt2") == pytest.approx(1.234)
    # existing entries preserved
    assert read_user_ff_value(out, "abarth500") == pytest.approx(1.000)


def test_update_preserves_trailing_newline():
    assert update_user_ff_value(_SAMPLE, "abarth500", 0.5).endswith("\n")
    assert not update_user_ff_value(_SAMPLE.rstrip("\n"), "abarth500", 0.5).endswith("\n")


def test_update_only_replaces_first_value_in_section():
    # A section has one VALUE; make sure we don't spill into the next section's VALUE.
    out = update_user_ff_value(_SAMPLE, "abarth500", 0.7)
    assert read_user_ff_value(out, "abarth500") == pytest.approx(0.7)
    assert read_user_ff_value(out, "ks_porsche_911_rsr_2017") == pytest.approx(1.053)
