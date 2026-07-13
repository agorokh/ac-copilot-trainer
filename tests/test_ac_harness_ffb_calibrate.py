"""Pure unit tests for per-car FFB gain auto-calibration (issue #533).

Exercise the platform-independent core of ``tools/ac_harness/ffb_calibrate.py`` — the sample
statistics, the gain recommendation maths, the ``user_ff.ini`` surgical read/write (backup +
install-tree guard + newline preservation), and the sampling loop (with a fake reader + injected
clock). No Assetto Corsa, no Windows, no shared memory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.ac_harness.ffb_calibrate import (
    DEFAULT_GAIN,
    GAIN_CEIL,
    GAIN_FLOOR,
    TARGET_PEAK,
    CalibrationResult,
    calibrate_from_samples,
    collect_final_ff,
    format_result,
    parse_user_ff_gain,
    read_user_ff_text,
    recommend_gain,
    resolve_user_ff_ini,
    set_user_ff_gain,
    summarize_final_ff,
    validate_user_ff_write_target,
    write_user_ff,
)


# --------------------------------------------------------------------------- summarize
def test_summarize_empty_is_all_zero():
    obs = summarize_final_ff([])
    assert obs.sample_count == 0
    assert obs.peak == 0.0
    assert obs.clip_fraction == 0.0
    assert obs.mean_abs == 0.0


def test_summarize_peak_and_mean_use_absolute_value():
    obs = summarize_final_ff([0.2, -0.8, 0.4, -0.6])
    assert obs.peak == pytest.approx(0.8)
    assert obs.mean_abs == pytest.approx((0.2 + 0.8 + 0.4 + 0.6) / 4)
    assert obs.sample_count == 4


def test_summarize_clip_fraction_counts_saturated_frames():
    # 2 of 5 samples at/above the 0.99 threshold.
    obs = summarize_final_ff([0.5, 0.999, -1.0, 0.3, 0.1], clip_threshold=0.99)
    assert obs.clip_fraction == pytest.approx(2 / 5)


# --------------------------------------------------------------------------- recommend_gain
def test_recommend_raises_gain_when_peak_below_target():
    obs = summarize_final_ff([0.45, -0.45, 0.30])  # peak 0.45, no clip
    rec = recommend_gain(1.0, obs)
    # 1.0 * 0.90 / 0.45 == 2.0 -> hits the ceiling but is still a raise
    assert rec.recommended == pytest.approx(min(2.0, TARGET_PEAK / 0.45))
    assert rec.enough_signal is True
    assert "raise gain" in rec.reason or "clamped" in rec.reason


def test_recommend_reduces_gain_when_clipping():
    obs = summarize_final_ff([1.0, 1.0, 1.0, 0.99])  # heavy clip, peak 1.0
    rec = recommend_gain(1.0, obs)
    assert rec.recommended == pytest.approx(0.9)  # 1.0 * 0.90 / 1.0
    assert rec.recommended < 1.0
    assert "reduce gain" in rec.reason


def test_recommend_small_trim_when_near_target_no_clip():
    obs = summarize_final_ff([0.92, -0.90, 0.88])  # peak 0.92, above target, not clipping
    rec = recommend_gain(1.0, obs)
    assert rec.recommended == pytest.approx(round(0.90 / 0.92, 3))
    assert rec.recommended < 1.0
    assert "trim" in rec.reason


def test_recommend_clamps_to_floor_and_flags():
    obs = summarize_final_ff([1.0] * 10)  # would push gain far down from a huge current
    rec = recommend_gain(0.1, obs, gain_floor=GAIN_FLOOR, gain_ceil=GAIN_CEIL)
    assert rec.recommended == GAIN_FLOOR
    assert rec.clamped is True
    assert "clamped" in rec.reason


def test_recommend_clamps_to_ceiling():
    obs = summarize_final_ff([0.1, -0.1])  # tiny peak -> huge raise
    rec = recommend_gain(1.0, obs)
    assert rec.recommended == GAIN_CEIL
    assert rec.clamped is True


def test_recommend_keeps_gain_when_no_signal():
    obs = summarize_final_ff([])
    rec = recommend_gain(1.05, obs)
    assert rec.recommended == pytest.approx(1.05)
    assert rec.enough_signal is False
    assert "insufficient signal" in rec.reason


def test_recommend_keeps_gain_when_all_zero_samples():
    obs = summarize_final_ff([0.0, 0.0, 0.0])
    rec = recommend_gain(1.0, obs)
    assert rec.enough_signal is False


def test_recommend_rounds_to_three_dp():
    obs = summarize_final_ff([0.7])  # 0.90/0.70 = 1.2857... -> 1.286
    rec = recommend_gain(1.0, obs)
    assert rec.recommended == pytest.approx(1.286)


# --------------------------------------------------------------------------- user_ff.ini parse
_SAMPLE_INI = (
    "[ks_porsche_911_rsr_2017]\nVALUE=1.053\n\n"
    "[bmw_m3_gt2]\nVALUE=1.010\n\n"
    "[ks_mazda_mx5_nd]\nVALUE=1.011\n"
)


def test_parse_gain_reads_named_car():
    assert parse_user_ff_gain(_SAMPLE_INI, "bmw_m3_gt2") == pytest.approx(1.010)
    assert parse_user_ff_gain(_SAMPLE_INI, "ks_porsche_911_rsr_2017") == pytest.approx(1.053)


def test_parse_gain_missing_car_is_none():
    assert parse_user_ff_gain(_SAMPLE_INI, "ks_porsche_911_gt3_r_2016") is None


def test_parse_gain_section_without_value_is_none():
    assert parse_user_ff_gain("[car_x]\n; no value here\n", "car_x") is None


# ----------------------------------------------------------------- user_ff.ini surgical set
def test_set_gain_updates_existing_and_preserves_other_cars():
    updated = set_user_ff_gain(_SAMPLE_INI, "bmw_m3_gt2", 0.925)
    assert parse_user_ff_gain(updated, "bmw_m3_gt2") == pytest.approx(0.925)
    # the other two cars are untouched
    assert parse_user_ff_gain(updated, "ks_porsche_911_rsr_2017") == pytest.approx(1.053)
    assert parse_user_ff_gain(updated, "ks_mazda_mx5_nd") == pytest.approx(1.011)
    assert "VALUE=0.925" in updated


def test_set_gain_appends_new_section_when_absent():
    updated = set_user_ff_gain(_SAMPLE_INI, "ks_porsche_911_gt3_r_2016", 0.880)
    assert "[ks_porsche_911_gt3_r_2016]" in updated
    assert parse_user_ff_gain(updated, "ks_porsche_911_gt3_r_2016") == pytest.approx(0.880)
    # pre-existing content preserved
    assert parse_user_ff_gain(updated, "bmw_m3_gt2") == pytest.approx(1.010)


def test_set_gain_appends_to_empty_file():
    updated = set_user_ff_gain("", "bmw_m3_gt2", 1.0)
    assert updated == "[bmw_m3_gt2]\nVALUE=1.000\n"


def test_set_gain_inserts_value_when_section_has_none():
    updated = set_user_ff_gain("[car_x]\n", "car_x", 0.5)
    assert parse_user_ff_gain(updated, "car_x") == pytest.approx(0.5)


def test_set_gain_preserves_crlf_newlines():
    crlf = "[bmw_m3_gt2]\r\nVALUE=1.010\r\n"
    updated = set_user_ff_gain(crlf, "bmw_m3_gt2", 0.9)
    assert updated == "[bmw_m3_gt2]\r\nVALUE=0.900\r\n"
    assert "\n" not in updated.replace("\r\n", "")  # no lone LF introduced


def test_set_gain_only_changes_target_line_bytewise():
    before = _SAMPLE_INI
    after = set_user_ff_gain(before, "bmw_m3_gt2", 0.925)
    # exactly one line differs
    diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=False) if a != b]
    assert diff == [("VALUE=1.010", "VALUE=0.925")]


# --------------------------------------------------------------------------- write-target guard
def _valid_target(tmp_path: Path) -> Path:
    cfg = tmp_path / "Assetto Corsa" / "cfg"
    cfg.mkdir(parents=True)
    return cfg / "user_ff.ini"


def test_validate_accepts_ac_cfg_user_ff(tmp_path: Path):
    target = _valid_target(tmp_path)
    assert validate_user_ff_write_target(target).name == "user_ff.ini"


def test_validate_rejects_install_tree(tmp_path: Path):
    bad = tmp_path / "steamapps" / "common" / "assettocorsa" / "user_ff.ini"
    bad.parent.mkdir(parents=True)
    with pytest.raises(ValueError, match="must be <AC Documents>"):
        validate_user_ff_write_target(bad)


def test_validate_rejects_wrong_filename(tmp_path: Path):
    cfg = tmp_path / "Assetto Corsa" / "cfg"
    cfg.mkdir(parents=True)
    with pytest.raises(ValueError, match="must be <AC Documents>"):
        validate_user_ff_write_target(cfg / "race.ini")


def test_resolve_user_ff_ini_joins_cfg():
    assert resolve_user_ff_ini(Path("/x/Assetto Corsa")) == Path("/x/Assetto Corsa/cfg/user_ff.ini")


# --------------------------------------------------------------------------- write + backup
def test_write_creates_file_without_backup_when_absent(tmp_path: Path):
    target = _valid_target(tmp_path)
    backup = write_user_ff(target, "[bmw_m3_gt2]\nVALUE=0.900\n")
    assert backup is None
    assert target.is_file()
    assert parse_user_ff_gain(read_user_ff_text(target), "bmw_m3_gt2") == pytest.approx(0.9)


def test_write_backs_up_existing(tmp_path: Path):
    target = _valid_target(tmp_path)
    target.write_bytes(b"[bmw_m3_gt2]\nVALUE=1.010\n")
    backup = write_user_ff(target, "[bmw_m3_gt2]\nVALUE=0.900\n")
    assert backup is not None and backup.name == "user_ff.ini.backup"
    assert backup.read_bytes() == b"[bmw_m3_gt2]\nVALUE=1.010\n"  # original preserved
    assert parse_user_ff_gain(read_user_ff_text(target), "bmw_m3_gt2") == pytest.approx(0.9)


def test_write_preserves_crlf_bytes(tmp_path: Path):
    target = _valid_target(tmp_path)
    write_user_ff(target, "[bmw_m3_gt2]\r\nVALUE=0.900\r\n")
    assert b"\r\n" in target.read_bytes()


def test_write_refuses_bad_target(tmp_path: Path):
    bad = tmp_path / "assettocorsa" / "user_ff.ini"
    bad.parent.mkdir(parents=True)
    with pytest.raises(ValueError):
        write_user_ff(bad, "x")


# --------------------------------------------------------------------------- collect_final_ff loop
class _FakeClock:
    """Monotonic clock advancing ``step`` per call; first call returns 0.0."""

    def __init__(self, step: float) -> None:
        self._t = -step
        self._step = step

    def __call__(self) -> float:
        self._t += self._step
        return self._t


class _FakeReader:
    """Returns scripted finalFF values; ``"torn"`` raises ValueError, exhaustion returns 0.0."""

    def __init__(self, values: list) -> None:
        self._it = iter(values)

    def read_final_ff(self):
        try:
            v = next(self._it)
        except StopIteration:
            return 0.0
        if v == "torn":
            raise ValueError("torn read")
        return v


def test_collect_samples_for_duration():
    reader = _FakeReader([0.1, 0.2, -0.3, 0.95, 0.4])
    samples, meta = collect_final_ff(
        reader, sample_hz=100, duration_s=0.055, clock=_FakeClock(0.01), sleep=lambda _: None
    )
    assert samples == [0.1, 0.2, -0.3, 0.95, 0.4]
    assert meta.read_ok == 5
    assert meta.torn_reads == 0
    assert meta.offset_ok is True


def test_collect_skips_torn_and_none_frames():
    reader = _FakeReader([0.5, "torn", None, 0.9])
    samples, meta = collect_final_ff(
        reader, sample_hz=100, duration_s=0.045, clock=_FakeClock(0.01), sleep=lambda _: None
    )
    assert samples == [0.5, 0.9]
    assert meta.torn_reads == 1
    assert meta.no_physics == 1


def test_collect_flags_out_of_range_offset():
    reader = _FakeReader([0.5, 1.5])
    samples, meta = collect_final_ff(
        reader, sample_hz=100, duration_s=0.025, clock=_FakeClock(0.01), sleep=lambda _: None
    )
    assert meta.offset_ok is False
    assert 1.5 in samples


def test_collect_honors_stop_event():
    class _Stop:
        def is_set(self) -> bool:
            return True

    reader = _FakeReader([0.5, 0.6])
    samples, meta = collect_final_ff(
        reader,
        sample_hz=100,
        duration_s=10.0,
        stop=_Stop(),
        clock=_FakeClock(0.01),
        sleep=lambda _: None,
    )
    assert samples == []
    assert meta.read_ok == 0


# --------------------------------------------------------------------------- calibrate_from_samples
def test_calibrate_dry_run_does_not_write(tmp_path: Path):
    target = _valid_target(tmp_path)
    result = calibrate_from_samples(
        [1.0, 1.0, 0.99], car_id="bmw_m3_gt2", user_ff_path=target, write=False
    )
    assert isinstance(result, CalibrationResult)
    assert result.written is False
    assert not target.exists()


def test_calibrate_writes_reduced_gain_on_clipping(tmp_path: Path):
    target = _valid_target(tmp_path)
    target.write_bytes(b"[bmw_m3_gt2]\nVALUE=1.000\n")
    result = calibrate_from_samples(
        [1.0, 1.0, 1.0, 0.995], car_id="bmw_m3_gt2", user_ff_path=target, write=True
    )
    assert result.written is True
    assert result.backup_path is not None
    assert result.recommendation.recommended == pytest.approx(0.9)
    assert parse_user_ff_gain(read_user_ff_text(target), "bmw_m3_gt2") == pytest.approx(0.9)


def test_calibrate_uses_default_gain_when_car_absent(tmp_path: Path):
    target = _valid_target(tmp_path)
    result = calibrate_from_samples(
        [0.45, -0.45], car_id="new_car", user_ff_path=target, write=True
    )
    assert result.recommendation.current_gain == pytest.approx(DEFAULT_GAIN)
    assert result.written is True


def test_calibrate_does_not_write_without_signal(tmp_path: Path):
    target = _valid_target(tmp_path)
    target.write_bytes(b"[bmw_m3_gt2]\nVALUE=1.010\n")
    result = calibrate_from_samples([], car_id="bmw_m3_gt2", user_ff_path=target, write=True)
    assert result.written is False
    # untouched hand-tuned value
    assert parse_user_ff_gain(read_user_ff_text(target), "bmw_m3_gt2") == pytest.approx(1.010)


def test_format_result_contains_key_fields(tmp_path: Path):
    target = _valid_target(tmp_path)
    result = calibrate_from_samples(
        [0.95, 0.99, 1.0], car_id="bmw_m3_gt2", user_ff_path=target, write=False
    )
    text = format_result(result)
    assert "bmw_m3_gt2" in text
    assert "observed peak" in text
    assert "recommended VALUE" in text
    assert "clipping" in text
