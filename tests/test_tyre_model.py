"""Tests for the tyre thermal model (tools.ai_sidecar.tyre_model)."""

from __future__ import annotations

from tools.ai_sidecar.tyre_model import (
    COMPOUND_WINDOWS,
    CRITICAL_C,
    OPTIMAL_BAND_ABOVE_C,
    OPTIMAL_BAND_BELOW_C,
    OPTIMAL_CRITICAL_MARGIN_C,
    analyze_tyres,
    tyres_from_lap_archive,
)


def _core(fl, fr, rl, rr):
    return {"fl": fl, "fr": fr, "rl": rl, "rr": rr}


# --- window status ----------------------------------------------------------
def test_in_window_balanced():
    r = analyze_tyres(_core(90, 90, 88, 88), compound="medium", laps_since_start=5)
    assert all(s == "in_window" for s in r.status.values())
    assert not r.warming
    assert "in window" in r.headline().lower()
    assert any(f.key == "balanced" for f in r.findings)


def test_cold_tyres_flagged_and_warming():
    r = analyze_tyres(_core(30, 32, 28, 29), compound="medium", laps_since_start=1)
    assert all(s == "cold" for s in r.status.values())
    assert r.warming
    assert any(f.key == "cold" for f in r.findings)


def test_overheat_flagged():
    r = analyze_tyres(_core(112, 110, 95, 96), compound="medium", laps_since_start=6)
    assert r.status["fl"] == "overheat"
    f = next(f for f in r.findings if f.key == "overheat")
    assert f.severity == "act"
    assert f.core_only is True


def test_critical_triggers_backoff():
    # CRITICAL_C is the soft limit (115); pin compound=soft so the threshold matches.
    r = analyze_tyres(_core(CRITICAL_C + 3, 100, 100, 100), compound="soft", laps_since_start=8)
    assert r.status["fl"] == "critical"
    assert "CRITICAL" in r.headline()
    assert any(f.key == "critical" and f.severity == "act" for f in r.findings)


def test_unknown_compound_falls_back_to_slick():
    r = analyze_tyres(_core(90, 90, 90, 90))
    assert r.compound == "slick"
    assert r.window == COMPOUND_WINDOWS["slick"]


def test_critical_is_compound_dependent():
    # 120°C is critical for SOFT (limit 115) but only overheat for HARD (limit 135) — codex #281.
    soft = analyze_tyres(_core(120, 100, 100, 100), compound="soft", laps_since_start=6)
    hard = analyze_tyres(_core(120, 100, 100, 100), compound="hard", laps_since_start=6)
    assert soft.status["fl"] == "critical"
    assert hard.status["fl"] == "overheat"
    assert not any(f.key == "critical" for f in hard.findings)


def test_degradation_onset_finding_in_window():
    # medium window 75-105; 104°C is in-window but in the top-3°C roll-off band (codex #281).
    r = analyze_tyres(_core(104, 104, 100, 100), compound="medium", laps_since_start=6)
    assert r.status["fl"] == "in_window"
    assert any(f.key == "degradation_onset" for f in r.findings)


def test_degradation_onset_is_compound_aware():
    # 104°C is degrading for MEDIUM (window top 105) but NOT for HARD (window top 110) — codex #281.
    med = analyze_tyres(_core(104, 104, 100, 100), compound="medium", laps_since_start=6)
    hard = analyze_tyres(_core(104, 104, 100, 100), compound="hard", laps_since_start=6)
    assert any(f.key == "degradation_onset" for f in med.findings)
    assert not any(f.key == "degradation_onset" for f in hard.findings)


def test_headline_precedence_overheat_over_warming():
    # one overheat wheel + others cold: headline says overheating (not warming), listing ONLY FL.
    r = analyze_tyres(_core(112, 60, 60, 60), compound="medium", laps_since_start=8)
    h = r.headline()
    assert "overheating" in h.lower()
    assert "FL" in h and "FR" not in h


def test_archive_rejects_nonfinite_temps_and_lap_n():
    # a NaN sample must be ignored (not poison the mean); NaN lap_n must not crash — codex #281.
    fields = ["spline", "tyreCoreTemp_fl", "tyreCoreTemp_fr", "tyreCoreTemp_rl", "tyreCoreTemp_rr"]
    samples = [
        [0.0, 90.0, 90.0, 88.0, 88.0],
        [0.5, float("nan"), 91.0, 89.0, 89.0],
        [1.0, 92.0, 92.0, 90.0, 90.0],
    ]
    archive = {"lap": {"lap_n": float("nan")}, "trace": {"fields": fields, "samples": samples}}
    r = tyres_from_lap_archive(archive)
    assert r is not None
    assert r.core["fl"] == 91.0  # mean of 90 and 92 (the NaN row skipped)


def test_warming_tyre_in_off_window_headline():
    # a late lap where tyres are below window (warming status) but not flagged "warming" rising —
    # the headline must still say off-window, not "in window" (codex #281).
    r = analyze_tyres(_core(60, 60, 58, 58), compound="medium", laps_since_start=8)
    assert "in window" not in r.headline().lower()


# --- imbalance --------------------------------------------------------------
def test_axle_imbalance_hypothesis():
    # fronts 12C hotter than rears -> front-axle finding (ranked hypothesis, not verdict)
    r = analyze_tyres(_core(100, 100, 86, 86), compound="medium", laps_since_start=5)
    f = next(f for f in r.findings if f.key == "axle_imbalance")
    assert "front" in f.summary
    assert f.confidence in ("medium", "low")
    assert "hypothes" in f.coaching.lower() or "check" in f.coaching.lower()


def test_side_imbalance_notes_track_confound():
    r = analyze_tyres(_core(100, 88, 99, 87), compound="medium", laps_since_start=5)
    f = next(f for f in r.findings if f.key == "side_imbalance")
    assert "confound" in f.coaching.lower()
    assert f.severity == "info"  # not actionable without a reference lap


def test_single_wheel_outlier():
    r = analyze_tyres(_core(110, 90, 90, 90), compound="hard", laps_since_start=5)
    assert any(f.key == "wheel_outlier" for f in r.findings)


# --- hot pressure estimate --------------------------------------------------
def test_hot_pressure_modelled_and_flagged_high():
    # cold 30 psi + hot core ~95C -> modelled hot well above the 26-29 window
    r = analyze_tyres(
        _core(95, 95, 95, 95),
        cold_pressure=_core(30.0, 30.0, 30.0, 30.0),
        compound="medium",
        laps_since_start=5,
    )
    assert r.hot_pressure_est["fl"] > 29.0
    f = next(f for f in r.findings if f.key == "hot_pressure_high")
    assert f.core_only is False  # hot pressure is modelled, not measured
    assert "modelled" in f.coaching.lower()


def test_no_pressure_means_no_hot_estimate():
    r = analyze_tyres(_core(90, 90, 90, 90), compound="medium", laps_since_start=5)
    assert r.hot_pressure_est == {}


# --- warm-up from previous lap ---------------------------------------------
def test_rising_fast_marks_warming_even_late():
    prev = _core(60, 60, 58, 58)
    r = analyze_tyres(_core(66, 66, 64, 64), compound="medium", prev_core=prev, laps_since_start=5)
    # mean core below window AND rising > 2C/lap -> warming
    assert r.warming


# --- archive integration ----------------------------------------------------
def _archive_with_temps(temps_per_wheel: dict[str, float]) -> dict:
    fields = [
        "spline",
        "speed",
        "eMs",
        "tyreCoreTemp_fl",
        "tyreCoreTemp_fr",
        "tyreCoreTemp_rl",
        "tyreCoreTemp_rr",
    ]
    samples = [
        [
            i / 4,
            100.0,
            i * 100.0,
            temps_per_wheel["fl"],
            temps_per_wheel["fr"],
            temps_per_wheel["rl"],
            temps_per_wheel["rr"],
        ]
        for i in range(5)
    ]
    return {
        # AC setup INI uses side-corner order: LF/RF/LR/RR (NOT FL/FR/...).
        "setup": {
            "snapshot": {
                "PRESSURE_LF.VALUE": "27.5",
                "PRESSURE_RF.VALUE": "27.5",
                "PRESSURE_LR.VALUE": "26.5",
                "PRESSURE_RR.VALUE": "26.5",
            }
        },
        "lap": {"lap_n": 5},
        "trace": {"fields": fields, "samples": samples},
    }


def test_tyres_from_lap_archive_averages_core_and_reads_pressure():
    r = tyres_from_lap_archive(_archive_with_temps(_core(92, 92, 88, 88)))
    assert r is not None
    assert r.core["fl"] == 92.0
    assert r.hot_pressure_est  # cold pressures were read from the setup snapshot


def test_tyres_from_lap_archive_none_without_temp_channels():
    archive = {"trace": {"fields": ["spline", "speed", "eMs"], "samples": [[0, 1, 2], [0.5, 1, 3]]}}
    assert tyres_from_lap_archive(archive) is None


def test_optimal_temp_recenters_window_on_car_true_peak():
    # #488 Part B: a captured car-true optimum re-centers the window on the real peak. peak=90 ->
    # window (70, 100), critical 115. AT the peak = in-window; well above peak+ABOVE = overheat.
    peak = 90.0
    r = analyze_tyres(_core(peak, peak, peak, peak), compound="soft", optimal_temp_c=peak)
    assert r.window == (peak - OPTIMAL_BAND_BELOW_C, peak + OPTIMAL_BAND_ABOVE_C)
    assert all(s == "in_window" for s in r.status.values())
    hot = analyze_tyres(
        _core(peak + OPTIMAL_BAND_ABOVE_C + 5, peak, peak, peak), optimal_temp_c=peak
    )
    assert hot.status["fl"] == "overheat"
    crit = analyze_tyres(
        _core(peak + OPTIMAL_CRITICAL_MARGIN_C + 1, peak, peak, peak), optimal_temp_c=peak
    )
    assert crit.status["fl"] == "critical"


def test_optimal_temp_overrides_generic_bucket():
    # Same core, different optimum: with optimal_temp_c the window is the CAR-true band, not the
    # generic per-compound bucket (which would be soft's (70, 100)).
    generic = analyze_tyres(_core(90, 90, 90, 90), compound="soft")
    car_true = analyze_tyres(_core(90, 90, 90, 90), compound="soft", optimal_temp_c=105.0)
    assert generic.window == COMPOUND_WINDOWS["soft"]
    assert car_true.window == (105.0 - OPTIMAL_BAND_BELOW_C, 105.0 + OPTIMAL_BAND_ABOVE_C)
    assert car_true.window != generic.window


def test_tyres_from_lap_archive_uses_car_true_optimum_and_longname():
    # #488 Part B: the tyres header's optimalTempC drives a car-true window; longName is the label.
    archive = _archive_with_temps(_core(85, 85, 83, 83))
    archive["tyres"] = {
        "compoundIndex": 4,
        "name": "R888R",
        "longName": "Toyo R888R",
        "optimalTempC": 88.0,
    }
    r = tyres_from_lap_archive(archive)
    assert r is not None
    assert r.window == (88.0 - OPTIMAL_BAND_BELOW_C, 88.0 + OPTIMAL_BAND_ABOVE_C)
    assert r.compound == "toyo r888r"  # long-name display label (lowercased)


def test_tyres_from_lap_archive_without_optimum_falls_back_to_generic():
    # Back-compat: a pre-#488 archive with no tyres.optimalTempC uses the generic slick window.
    r = tyres_from_lap_archive(_archive_with_temps(_core(92, 92, 88, 88)))
    assert r is not None
    assert r.window == COMPOUND_WINDOWS["slick"]


def test_tyres_from_lap_archive_acd_fallback_resolves_optimum(monkeypatch):
    # #488 Part B: a pre-#488 archive (compoundIndex only, no live optimum/name) resolves the
    # car-true optimum + compound name from the car's tyres.ini (ACD) when car_data_dir is given.
    from types import SimpleNamespace

    from tools.ai_sidecar import tyre_model

    archive = _archive_with_temps(_core(72, 72, 70, 70))
    archive["tyres"] = {"compoundIndex": 0}  # index only — the pre-#488 capture shape

    def _fake_specs(car_dir, compound_index):
        assert compound_index == 0
        return SimpleNamespace(optimal_temp_c=70.0, name="Slick Soft")

    monkeypatch.setattr(tyre_model, "read_tyre_specs", _fake_specs)
    r = tyres_from_lap_archive(archive, car_data_dir="/fake/car/dir")
    assert r is not None
    assert r.window == (70.0 - OPTIMAL_BAND_BELOW_C, 70.0 + OPTIMAL_BAND_ABOVE_C)
    assert r.compound == "slick soft"


def test_tyres_from_lap_archive_no_car_dir_skips_acd():
    # Without car_data_dir the ACD reader is never touched (no side effects, generic fallback).
    archive = _archive_with_temps(_core(92, 92, 88, 88))
    archive["tyres"] = {"compoundIndex": 0}
    r = tyres_from_lap_archive(archive)
    assert r is not None
    assert r.window == COMPOUND_WINDOWS["slick"]


def test_archive_zero_temps_are_unread_sentinel():
    # all-zero core (unread) -> no usable wheel data -> None (mirrors #266 all-zero guard)
    r = tyres_from_lap_archive(_archive_with_temps(_core(0.0, 0.0, 0.0, 0.0)))
    assert r is None
