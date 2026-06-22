"""Tests for the tyre thermal model (tools.ai_sidecar.tyre_model)."""

from __future__ import annotations

from tools.ai_sidecar.tyre_model import (
    COMPOUND_WINDOWS,
    CRITICAL_C,
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
    # medium window 75-105; 104°C is in-window but past the 103°C degradation band (codex #281).
    r = analyze_tyres(_core(104, 104, 100, 100), compound="medium", laps_since_start=6)
    assert r.status["fl"] == "in_window"
    assert any(f.key == "degradation_onset" for f in r.findings)


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


def test_archive_zero_temps_are_unread_sentinel():
    # all-zero core (unread) -> no usable wheel data -> None (mirrors #266 all-zero guard)
    r = tyres_from_lap_archive(_archive_with_temps(_core(0.0, 0.0, 0.0, 0.0)))
    assert r is None
