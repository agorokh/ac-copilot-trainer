"""Pure unit tests for the FFB calibration helpers (issue #533).

Covers the platform-independent halves of ``tools/ac_harness/ffb_calibrate``: the finalFF
sample summary, the gain recommendation math, the offset sanity gate, and the format-preserving
``user_ff.ini`` reader/writer. The launch + shared-memory sample loop is rig-only and excluded
from coverage there.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pytest

from tools.ac_harness.ffb_calibrate import (
    FfbStats,
    _auto_drive_passthrough,
    _evidence_key,
    _nonneg_float,
    _pos_float,
    offset_looks_valid,
    read_user_ff_value,
    recommend_gain,
    should_write,
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


def test_summarize_drops_non_finite():
    # A wrong offset can read +/-inf; dropping it keeps report JSON valid and stats un-poisoned.
    stats = summarize([0.5, float("inf"), -0.5, float("-inf"), float("nan")])
    assert stats.n == 2
    assert stats.peak == pytest.approx(0.5)


def test_summarize_empty_is_zeroed():
    stats = summarize([])
    assert stats == FfbStats(n=0, peak=0.0, rms=0.0, clip_fraction=0.0, clip_threshold=0.99)


def test_summarize_percentiles_sit_below_kerb_peak():
    # A signal dominated by ~0.5 with a few kerb spikes to ~1.8: p99 sits well below the max, so
    # calibration keys off p99 rather than the rare spike (the live-observed 911 behaviour).
    stats = summarize([0.5] * 990 + [1.8] * 10)
    assert stats.peak == pytest.approx(1.8)
    assert stats.p99 < stats.peak
    assert stats.p95 == pytest.approx(0.5, abs=0.1)


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


@pytest.mark.parametrize(
    ("valid", "write", "dry_run", "expected"),
    [
        (True, True, False, True),  # explicit --write, valid offset, not dry-run -> write
        (True, False, False, False),  # no --write -> report-only (the default)
        (True, True, True, False),  # --dry-run vetoes --write
        (False, True, False, False),  # invalid offset -> never write
    ],
)
def test_should_write(valid, write, dry_run, expected):
    assert should_write(valid, write, dry_run) is expected


# --------------------------------------------------------------------------- offset gate
def test_offset_looks_valid_accepts_normal_signal():
    ok, _ = offset_looks_valid(
        FfbStats(n=1000, peak=0.85, rms=0.4, clip_fraction=0.01, clip_threshold=0.99)
    )
    assert ok is True


def test_offset_looks_valid_accepts_kerb_spike_peak():
    # finalFF is not clamped to 1.0 — a live 911 Spa lap peaked at 1.85 on kerbs. That must be
    # accepted (regression: the original 1.10 ceiling wrongly rejected a real signal).
    ok, _ = offset_looks_valid(
        FfbStats(n=2692, peak=1.853, rms=0.527, clip_fraction=0.031, clip_threshold=0.99)
    )
    assert ok is True


def test_offset_looks_valid_rejects_too_few_samples():
    ok, reason = offset_looks_valid(
        FfbStats(n=10, peak=0.8, rms=0.4, clip_fraction=0.0, clip_threshold=0.99)
    )
    assert ok is False
    assert "samples" in reason


def test_offset_looks_valid_duration_aware_min_rejects_stalled_window():
    # 300 samples clears the fixed 200 floor, but a duration-aware floor (what _run passes for a
    # long window) rejects a mid-sample stall that only produced a short live slice.
    ok, reason = offset_looks_valid(
        FfbStats(n=300, peak=0.8, rms=0.4, clip_fraction=0.0, clip_threshold=0.99),
        min_samples=1000,
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


def test_read_user_ff_value_strips_inline_comment():
    text = "[abarth500]\nVALUE=1.010 ; hand-tuned 2026-07-12\n"
    assert read_user_ff_value(text, "abarth500") == pytest.approx(1.010)


def test_read_user_ff_value_strips_hash_comment():
    assert read_user_ff_value("[abarth500]\nVALUE=0.750 # tuned\n", "abarth500") == pytest.approx(
        0.750
    )


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_read_user_ff_value_rejects_non_finite(bad):
    # A corrupt VALUE=nan/inf is unusable; treated as absent so the caller falls back to 1.0.
    assert read_user_ff_value(f"[x]\nVALUE={bad}\n", "x") is None


def test_auto_drive_passthrough_forwards_only_set_overrides():
    ns = argparse.Namespace(
        track_layout="tourist",
        ac_user_dir=Path("D:/AC"),
        ac_root=None,
        cm_exe=None,
        sidecar_url=None,
    )
    assert _auto_drive_passthrough(ns) == [
        "--track-layout",
        "tourist",
        "--ac-user-dir",
        str(Path("D:/AC")),
    ]


def test_auto_drive_passthrough_empty_when_all_default():
    ns = argparse.Namespace(
        track_layout=None, ac_user_dir=None, ac_root=None, cm_exe=None, sidecar_url=None
    )
    assert _auto_drive_passthrough(ns) == []


def test_evidence_key_includes_layout():
    # Two layouts of the same base track must not collide in the evidence bundle.
    assert _evidence_key("ks_x", "spa", None) == "ks_x_spa"
    assert _evidence_key("ks_x", "nords", "tourist") == "ks_x_nords_tourist"


@pytest.mark.parametrize("bad", ["0", "-1", "inf", "nan", "-inf"])
def test_pos_float_rejects_nonpositive_and_nonfinite(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        _pos_float(bad)


def test_pos_float_accepts_positive():
    assert _pos_float("0.5") == pytest.approx(0.5)


@pytest.mark.parametrize("bad", ["-1", "inf", "nan"])
def test_nonneg_float_rejects_negative_and_nonfinite(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        _nonneg_float(bad)


def test_nonneg_float_accepts_zero():
    assert _nonneg_float("0") == pytest.approx(0.0)


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


def test_update_inserts_value_into_existing_section_missing_value():
    # A section exists but has no VALUE line: insert VALUE in place, do NOT append a duplicate
    # [car] section at EOF (daemon MEDIUM finding).
    text = "[abarth500]\nVALUE=1.000\n[bmw_m3_gt2]\n[ks_bmw_m4]\nVALUE=1.000\n"
    out = update_user_ff_value(text, "bmw_m3_gt2", 0.9)
    assert read_user_ff_value(out, "bmw_m3_gt2") == pytest.approx(0.9)
    assert out.count("[bmw_m3_gt2]") == 1  # no duplicate section
    assert read_user_ff_value(out, "abarth500") == pytest.approx(1.0)
    assert read_user_ff_value(out, "ks_bmw_m4") == pytest.approx(1.0)


def test_update_inserts_value_into_last_section_missing_value():
    # Target is the file's final section and has no VALUE line — insert at EOF, no duplicate.
    out = update_user_ff_value("[abarth500]\nVALUE=1.000\n[bmw_m3_gt2]\n", "bmw_m3_gt2", 0.8)
    assert read_user_ff_value(out, "bmw_m3_gt2") == pytest.approx(0.8)
    assert out.count("[bmw_m3_gt2]") == 1
