"""Tests for the coaching debrief renderer + CLI (tools.ai_sidecar.coach_report)."""

from __future__ import annotations

import json
import math

from tools.ai_sidecar.coach_report import build_debrief, build_structured_debrief, main


def _corner_archive(*, degrade: float = 0.0) -> dict:
    radius, ds, n_pre, n_arc, n_post = 30.0, 2.0, 40, 30, 40
    n = n_pre + n_arc + n_post
    kappa = [0.0] * n_pre + [1.0 / radius] * n_arc + [0.0] * n_post
    theta, x, z = 0.0, 0.0, 0.0
    xs, zs = [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * ds
        x += ds * math.cos(theta)
        z += ds * math.sin(theta)
    apex_i = n_pre + n_arc // 2
    v = []
    for i in range(n):
        if i < 25:
            v.append(55.0)
        elif i < apex_i:
            v.append(55.0 + (25.0 - 55.0) * (i - 25) / max(1, apex_i - 25) - degrade)
        elif i < n_pre + n_arc + 5:
            v.append(25.0 + (55.0 - 25.0) * (i - apex_i) / max(1, n_pre + n_arc + 5 - apex_i))
        else:
            v.append(55.0)
    brake = [0.8 if 25 <= i < apex_i else 0.0 for i in range(n)]
    throttle = [1.0 if i >= apex_i + 1 else 0.0 for i in range(n)]
    steer = [0.4 if n_pre <= i < n_pre + n_arc else 0.0 for i in range(n)]
    t_ms = [0.0]
    for i in range(1, n):
        t_ms.append(t_ms[-1] + ds / max(0.5, 0.5 * (v[i] + v[i - 1])) * 1000.0)
    total = ds * (n - 1)
    spline = [(ds * i) / total for i in range(n)]
    samples = [
        [spline[i], v[i] * 3.6, t_ms[i], throttle[i], brake[i], steer[i], 4, xs[i], 0.0, zs[i]]
        for i in range(n)
    ]
    return {
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione", "lengthM": total},
        "lap": {"lap_ms": int(t_ms[-1]), "is_valid": True},
        "setup": {"snapshot": {"FRONT_BIAS.VALUE": "66", "TRACTION_CONTROL.VALUE": "4"}},
        "trace": {
            "fields": [
                "spline",
                "speed",
                "eMs",
                "throttle",
                "brake",
                "steer",
                "gear",
                "px",
                "py",
                "pz",
            ],
            "samples": samples,
        },
    }


def _scale_archive_time(archive: dict, factor: float) -> None:
    e_ms_idx = archive["trace"]["fields"].index("eMs")
    for sample in archive["trace"]["samples"]:
        sample[e_ms_idx] *= factor
    archive["lap"]["lap_ms"] = int(archive["lap"]["lap_ms"] * factor)


def test_build_debrief_renders_sections():
    text = build_debrief(_corner_archive(), grip_ceiling_g=2.5)
    assert "Coaching debrief" in text
    assert "Setup at a glance" in text
    assert "Brake bias (front): 66" in text
    assert "Balance (aero vs mechanical)" in text
    assert "Per-corner" in text


def test_build_debrief_with_reference_shows_time_loss():
    ref = _corner_archive(degrade=0.0)
    student = _corner_archive(degrade=8.0)  # student carries less apex speed
    text = build_debrief(student, reference_archive=ref, grip_ceiling_g=2.5)
    assert "vs reference" in text or "losing time" in text
    assert "Sector deltas vs reference" in text
    assert "SuperLap target" in text


def test_cli_main_runs(tmp_path, capsys):
    p = tmp_path / "lap.json"
    p.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    rc = main([str(p), "--grip-ceiling-g", "2.5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Coaching debrief" in out


def _rich_archive(
    *, degrade: float = 0.0, grip: float = 0.90, core: float = 35.0, weather: str = "clear"
) -> dict:
    """A corner archive with per-wheel tyre core-temp columns + a conditions block."""
    a = _corner_archive(degrade=degrade)
    a["trace"]["fields"] = a["trace"]["fields"] + [
        "tyreCoreTemp_fl",
        "tyreCoreTemp_fr",
        "tyreCoreTemp_rl",
        "tyreCoreTemp_rr",
    ]
    a["trace"]["samples"] = [row + [core, core, core, core] for row in a["trace"]["samples"]]
    a["conditions"] = {
        "trackGripLevel": grip,
        "ambientTempC": 22.0,
        "trackTempC": 28.0,
        "weatherType": weather,
    }
    return a


def test_structured_debrief_has_tyre_block_when_temps_present():
    d = build_structured_debrief(_rich_archive(core=35.0), grip_ceiling_g=2.5)
    assert d is not None
    tyres = d["tyres"]
    assert tyres is not None
    # 35°C is below GRIP_ONSET_C (40) → all four wheels read "cold"
    assert set(tyres["status"]) == {"fl", "fr", "rl", "rr"}
    assert all(s == "cold" for s in tyres["status"].values())
    # cold tyres must never be reported as "in window" (warming/cold/off-window are all acceptable)
    assert "in window" not in tyres["headline"].lower()


def test_structured_debrief_has_conditions_block():
    d = build_structured_debrief(_rich_archive(grip=0.90, weather="clear"), grip_ceiling_g=2.5)
    cond = d["conditions"]
    assert cond is not None
    assert cond["regime"] == "dry"
    assert cond["grip_band"] == "green"  # 0.90 < GREEN_BELOW (0.93)
    assert cond["grip_level"] == 0.90


def test_structured_debrief_omits_blocks_when_data_absent():
    d = build_structured_debrief(_corner_archive(), grip_ceiling_g=2.5)
    assert d["tyres"] is None  # no per-wheel temp columns
    assert d["conditions"] is None  # no conditions block
    assert d["corner_reference"] is None  # no reference lap


def test_corner_reference_present_with_reference_and_honest_source():
    ref = _corner_archive(degrade=0.0)
    student = _corner_archive(degrade=8.0)
    d = build_structured_debrief(student, reference_archive=ref, grip_ceiling_g=2.5)
    cr = d["corner_reference"]
    assert cr is not None and cr
    for entry in cr:
        assert entry["source"] == "reference_lap"  # corpus best, not a fabricated GGV ceiling
        assert "optimal_apex_kmh" not in entry  # must NOT over-claim a theoretical optimum
        assert isinstance(entry["deficit_to_target_kmh"], (int, float))
        assert isinstance(entry["target_apex_kmh"], (int, float))


def test_structured_debrief_includes_sector_deltas_and_superlap():
    ref = _corner_archive(degrade=0.0)
    student = _corner_archive(degrade=8.0)
    d = build_structured_debrief(student, reference_archive=ref, grip_ceiling_g=2.5)

    sector_deltas = d["sector_deltas"]
    assert sector_deltas is not None
    assert sector_deltas["track_id"] == "magione"
    assert len(sector_deltas["sectors"]) == 3
    assert len(sector_deltas["micro_sectors"]) == 9
    assert sector_deltas["micro_sectors"][0]["label"] == "S1.1"

    superlap = d["superlap"]
    assert superlap is not None
    assert superlap["segments"][0]["label"] == "S1.1"
    assert superlap["source_count"] >= 1


def test_sector_deltas_skip_invalid_reference_lap():
    ref = _corner_archive(degrade=0.0)
    ref["lap"]["is_valid"] = False
    student = _corner_archive(degrade=8.0)

    d = build_structured_debrief(student, reference_archive=ref, grip_ceiling_g=2.5)

    assert d["sector_deltas"] is None


def test_sector_deltas_skip_reference_from_different_combo():
    ref = _corner_archive(degrade=0.0)
    ref["track"]["id"] = "spa"
    student = _corner_archive(degrade=8.0)

    d = build_structured_debrief(student, reference_archive=ref, grip_ceiling_g=2.5)

    assert d["sector_deltas"] is None


def test_sector_deltas_skip_reference_from_different_track_layout():
    ref = _corner_archive(degrade=0.0)
    ref["track"]["layout"] = "junior"
    student = _corner_archive(degrade=8.0)
    student["track"]["layout"] = "gp"

    d = build_structured_debrief(student, reference_archive=ref, grip_ceiling_g=2.5)

    assert d["sector_deltas"] is None


def test_superlap_ignores_invalid_current_lap():
    ref = _corner_archive(degrade=8.0)
    student = _corner_archive(degrade=0.0)
    _scale_archive_time(student, 0.5)
    student["lap"]["is_valid"] = False

    d = build_structured_debrief(student, reference_archive=ref, grip_ceiling_g=2.5)

    superlap = d["superlap"]
    assert superlap is not None
    assert {seg["source_index"] for seg in superlap["segments"]} == {0}


def test_superlap_filters_corpus_to_same_car_and_track():
    ref = _corner_archive(degrade=8.0)
    student = _corner_archive(degrade=8.0)
    wrong_track = _corner_archive(degrade=0.0)
    _scale_archive_time(wrong_track, 0.5)
    wrong_track["track"]["id"] = "spa"

    d = build_structured_debrief(
        student,
        reference_archive=ref,
        corpus_archives=[wrong_track],
        grip_ceiling_g=2.5,
    )

    superlap = d["superlap"]
    assert superlap is not None
    assert {seg["track_id"] for seg in superlap["segments"]} == {"magione"}


def test_superlap_filters_corpus_to_same_track_layout():
    ref = _corner_archive(degrade=8.0)
    ref["track"]["layout"] = "gp"
    student = _corner_archive(degrade=8.0)
    student["track"]["layout"] = "gp"
    wrong_layout = _corner_archive(degrade=0.0)
    _scale_archive_time(wrong_layout, 0.5)
    wrong_layout["track"]["layout"] = "junior"

    d = build_structured_debrief(
        student,
        reference_archive=ref,
        corpus_archives=[wrong_layout],
        grip_ceiling_g=2.5,
    )

    superlap = d["superlap"]
    assert superlap is not None
    assert 2 not in {seg["source_index"] for seg in superlap["segments"]}


def test_debrief_text_includes_tyre_and_conditions_sections():
    text = build_debrief(_rich_archive(), grip_ceiling_g=2.5)
    assert "Tyres (thermal)" in text
    assert "Conditions (track/weather)" in text


def test_conditions_block_present_with_temps_only():
    # only track/ambient temps known (no grip, no weather) -> still meaningful (codex #292)
    a = _corner_archive()
    a["conditions"] = {
        "trackGripLevel": None,
        "weatherType": None,
        "trackTempC": 41.0,
        "ambientTempC": 30.0,
    }
    d = build_structured_debrief(a, grip_ceiling_g=2.5)
    assert d["conditions"] is not None
    assert d["conditions"]["track_temp_c"] == 41.0
    assert d["conditions"]["grip_level"] is None


def test_tyre_block_suppressed_in_wet_conditions():
    # slick thermal window is meaningless in the wet -> suppress the contradictory tyre block,
    # keep the wet conditions coaching (codex #291)
    a = _rich_archive(core=35.0, weather="rain", grip=0.90)
    d = build_structured_debrief(a, grip_ceiling_g=2.5)
    assert d["tyres"] is None  # not a "cold slick — build heat" cue in the rain
    assert d["conditions"] is not None
    assert d["conditions"]["regime"] == "wet"
    assert "Tyres (thermal)" not in d["text"]


def test_slower_reference_corners_are_not_published_as_targets():
    # a SLOWER reference must not be published as a pace target the driver has already beaten
    fast = _corner_archive(degrade=0.0)  # the driven (faster) lap
    slow_ref = _corner_archive(degrade=10.0)  # a stale/slower reference
    d = build_structured_debrief(fast, reference_archive=slow_ref, grip_ceiling_g=2.5)
    # every corner's "target" is below the driven speed -> all dropped -> block omitted
    assert d["corner_reference"] is None


def test_trail_braking_block_in_structured_debrief():
    # the trail-braking analyzer's per-corner read flows into the structured debrief + text (#296)
    d = build_structured_debrief(_corner_archive(), grip_ceiling_g=2.5)
    tb = d["trail_braking"]
    assert tb is not None and tb  # the corner brakes, so it produces a finding
    entry = tb[0]
    assert "classification" in entry and "trail_overlap" in entry and "coaching" in entry
    # the square-brake fixture is a non-"good" technique → surfaces in the text section
    assert "Trail braking" in d["text"]


def test_structured_debrief_includes_corner_diagnostics():
    d = build_structured_debrief(
        _corner_archive(degrade=2.0),
        reference_archive=_corner_archive(degrade=0.0),
        history_archives=[_corner_archive(degrade=4.0)],
        grip_ceiling_g=2.5,
    )
    diag = d["corners"][0]["diagnostics"]
    assert set(diag) >= {"steering", "brake_shape", "gear", "exit_road_usage", "consistency"}
    assert diag["exit_road_usage"]["available"] is True
    assert diag["consistency"]["available"] is True


def test_structured_debrief_ignores_history_from_other_track():
    other = _corner_archive(degrade=4.0)
    other["track"]["id"] = "different_track"
    d = build_structured_debrief(
        _corner_archive(degrade=2.0),
        history_archives=[other],
        grip_ceiling_g=2.5,
    )
    diag = d["corners"][0]["diagnostics"]["consistency"]
    assert diag["available"] is False
    assert diag["sample_count"] == 1


def test_structured_debrief_rejects_history_when_current_track_id_missing():
    current = _corner_archive(degrade=2.0)
    del current["track"]["id"]
    d = build_structured_debrief(
        current,
        history_archives=[_corner_archive(degrade=4.0)],
        grip_ceiling_g=2.5,
    )
    diag = d["corners"][0]["diagnostics"]["consistency"]
    assert diag["available"] is False
    assert diag["sample_count"] == 1


def test_structured_debrief_rejects_history_when_history_track_id_missing():
    other = _corner_archive(degrade=4.0)
    del other["track"]["id"]
    d = build_structured_debrief(
        _corner_archive(degrade=2.0),
        history_archives=[other],
        grip_ceiling_g=2.5,
    )
    diag = d["corners"][0]["diagnostics"]["consistency"]
    assert diag["available"] is False
    assert diag["sample_count"] == 1


def test_structured_debrief_rejects_one_sided_track_layout():
    other = _corner_archive(degrade=4.0)
    other["track"]["layout"] = "junior"
    d = build_structured_debrief(
        _corner_archive(degrade=2.0),
        history_archives=[other],
        grip_ceiling_g=2.5,
    )
    diag = d["corners"][0]["diagnostics"]["consistency"]
    assert diag["available"] is False
    assert diag["sample_count"] == 1


def test_structured_debrief_rejects_history_with_missing_car_id():
    other = _corner_archive(degrade=4.0)
    del other["car"]["id"]
    d = build_structured_debrief(
        _corner_archive(degrade=2.0),
        history_archives=[other],
        grip_ceiling_g=2.5,
    )
    diag = d["corners"][0]["diagnostics"]["consistency"]
    assert diag["available"] is False
    assert diag["sample_count"] == 1
