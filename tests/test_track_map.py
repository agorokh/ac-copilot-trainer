"""#531 Part F: track.map geometry built from the reference archive."""

from __future__ import annotations

from tests.test_realtime_observer import _corner_archive as _raw_corner_archive
from tools.ai_sidecar.track_map import MAX_OUTLINE_POINTS, build_track_map


def test_circular_windows_preserve_measured_finish_and_start_samples() -> None:
    from tools.ai_sidecar.lap_dynamics import LapTrace
    from tools.ai_sidecar.track_map import _slice_circular

    lap = LapTrace(
        spline=[0, 0.01, 0.50, 0.98, 0.99, 1],
        t_s=[0, 1, 50, 98, 99, 100],
        brake=[0, 0, 0, 0.8, 0.8, 0.8],
        lap_ms=100_000,
        v_ms=[40] * 6,
        throttle=[0.5] * 6,
        steer=[0] * 6,
        gear=[4] * 6,
        x=list(range(6)),
        z=[0] * 6,
    )
    finish = _slice_circular(lap, 0.98, 1)
    assert finish.spline == [0.98, 0.99, 1]
    assert finish.t_s == [98, 99, 100]
    assert finish.brake == [0.8, 0.8, 0.8]
    whole = _slice_circular(lap, 0, 1)
    assert whole.spline == lap.spline
    assert whole.t_s == lap.t_s
    assert whole.brake == lap.brake
    wrapped = _slice_circular(lap, 0.98, 0.01)
    assert wrapped.spline == [0.98, 0.99, 1, 0.01]
    assert wrapped.t_s == [98, 99, 100, 101]
    assert wrapped.brake == [0.8, 0.8, 0.8, 0]


def test_unknown_combo_retains_geometry_without_corner_catalogue() -> None:
    archive = _corner_archive()
    archive["car"] = {}
    archive["track"] = {}
    live = {"available": True, "combo": [None, None, None], "corners": archive["corners"]}
    for catalog in (None, live):
        payload = build_track_map(archive, catalog)
        assert payload is not None and payload["outline"]
        assert payload["corners"] == []


def _corner_archive(*, degrade: float = 0.0) -> dict:
    archive = _raw_corner_archive(degrade=degrade)
    archive["source"] = "in_game"
    archive["corners"] = [{"label": "T1", "s0": 0.25, "s1": 0.8, "brakePointSpline": 0.22}]
    return archive


def test_measured_phases_and_missing_channels_stay_unknown() -> None:
    archive = _corner_archive()
    payload = build_track_map(archive)
    assert payload is not None
    phases = payload["corners"][0]["phases"]
    assert phases["braking"][0] < phases["braking"][1]
    assert phases["entry"][1] == phases["apex"][0]
    assert phases["apex"][0] == phases["apex"][1]
    assert phases["exit"][0] == phases["apex"][0]
    i = archive["trace"]["fields"].index("steer")
    for sample in archive["trace"]["samples"]:
        sample[i] = None
    payload = build_track_map(archive)
    assert payload is not None
    assert payload["corners"][0]["phases"]["braking"] is None
    assert payload["corners"][0]["phases"]["entry"] is None


def test_completed_lap_comparison_zero_and_signed_loss() -> None:
    from tools.ai_sidecar.track_map import build_corner_comparison, reference_identity

    ref = _corner_archive()
    result = build_corner_comparison(ref, ref)
    assert result["available"] is True
    assert result["reference_id"] == reference_identity(ref)
    row = result["corners"][0]
    assert row["time_loss_s"] == 0
    assert row["brake_onset_delta_m"] == 0
    assert result["largest_opportunity_id"] is None
    slower = _corner_archive(degrade=8)
    result = build_corner_comparison(slower, ref)
    assert result["available"] is True
    assert result["corners"][0]["time_loss_s"] > 0
    assert result["corners"][0]["min_speed_kmh"] < row["min_speed_kmh"]
    assert result["largest_opportunity_id"] == "T1"
    faster = build_corner_comparison(ref, slower)
    assert faster["corners"][0]["time_loss_s"] < 0
    assert faster["largest_opportunity_id"] is None


def test_completed_comparison_rejects_unverified_identity_or_trace() -> None:
    import copy

    from tools.ai_sidecar.track_map import build_corner_comparison

    reference = _corner_archive()
    for patch in ({"id": "other"}, {"id": "magione", "layout": "other"}, {"id": ""}):
        lap = copy.deepcopy(reference)
        lap["track"] = patch
        result = build_corner_comparison(lap, reference)
        assert result["available"] is False
        assert result["corners"] == []
    for valid in (False, None):
        lap = copy.deepcopy(reference)
        lap["lap"]["is_valid"] = valid
        assert build_corner_comparison(lap, reference)["available"] is False
    for channel in ("speed", "eMs", "spline"):
        lap = copy.deepcopy(reference)
        i = lap["trace"]["fields"].index(channel)
        lap["trace"]["samples"][10][i] = None
        assert build_corner_comparison(lap, reference)["available"] is False
    lap = copy.deepcopy(reference)
    for row in lap["trace"]["samples"]:
        row[lap["trace"]["fields"].index("brake")] = None
    result = build_corner_comparison(lap, reference)
    assert result["available"] is True
    assert result["corners"][0]["brake_onset_delta_m"] is None
    assert result["corners"][0]["time_loss_s"] == 0


def test_catalog_labels_survive_unmeasured_reference_phases() -> None:
    archive = _corner_archive()
    archive["corners"][0]["label"] = "T7"
    speed_i = archive["trace"]["fields"].index("speed")
    for sample in archive["trace"]["samples"]:
        sample[speed_i] = 180.0
    payload = build_track_map(archive)
    assert payload is not None
    assert payload["corners"][0]["id"] == "T7"
    assert payload["corners"][0]["anchor_phase"] == "catalog_brake_anchor"
    assert payload["corners"][0]["phases"]["apex"] is None
    assert "min_speed_kmh" not in payload["corners"][0]


def test_missing_catalogue_keeps_geometry_without_independent_numbering() -> None:
    archive = _raw_corner_archive()
    payload = build_track_map(archive)
    assert payload is not None
    assert payload["outline"]
    assert payload["corners"] == []
    assert "unavailable" in payload["corner_availability"]


def test_measured_native_finish_wrap_is_normalised_without_mutating_archive() -> None:
    import copy

    from tools.ai_sidecar.track_map import build_corner_comparison

    archive = _corner_archive()
    archive["trace"]["samples"][-1][0] = 0.0006
    before = copy.deepcopy(archive)
    payload = build_track_map(archive)
    assert payload is not None
    assert payload["spline"][-1] >= 0.99
    assert all(a <= b for a, b in zip(payload["spline"], payload["spline"][1:], strict=False))
    comparison = build_corner_comparison(archive, archive)
    assert comparison["available"] is True
    assert comparison["corners"][0]["time_loss_s"] == 0
    assert archive == before
    archive["trace"]["samples"][70][0] = 0.001
    assert build_track_map(archive) is None
    assert build_corner_comparison(archive, before)["available"] is False


def test_live_catalogue_is_same_combo_only_and_wraps_honestly() -> None:
    from tools.ai_sidecar.track_map import build_corner_comparison

    archive = _corner_archive()
    catalog = {
        "available": True,
        "combo": [archive["car"]["id"], "magione", ""],
        "corners": [{"corner_id": "T9", "s0": 0.95, "s1": 0.8, "brake_spline": 0.93}],
    }
    payload = build_track_map(archive, catalog)
    assert payload is not None
    assert payload["corners"][0]["label"] == "T9"
    assert payload["corner_catalog_source"] == "lua_active_reference"
    comparison = build_corner_comparison(archive, archive, catalog)
    assert comparison["available"] is True
    assert comparison["corners"][0]["time_loss_s"] == 0
    catalog["combo"][2] = "wrong_layout"
    payload = build_track_map(archive, catalog)
    assert payload is not None
    assert payload["corners"] == []
    assert build_corner_comparison(archive, archive, catalog)["available"] is False


def test_unknown_or_generated_reference_never_produces_measured_verdict() -> None:
    from tools.ai_sidecar.track_map import build_corner_comparison

    lap = _corner_archive()
    for source, import_format in (
        (None, None),
        ("imported", "generated_reference_v1"),
        ("imported", "unknown_format"),
    ):
        reference = _corner_archive()
        reference["source"] = source
        reference["import_format"] = import_format
        result = build_corner_comparison(lap, reference)
        assert result["available"] is False
        assert "provenance" in result["reason"]
        payload = build_track_map(reference)
        assert payload is not None and payload["outline"]
        assert payload["corners"][0]["label"] == "T1"
        assert payload["corners"][0]["phases"]["apex"] is None


def test_build_track_map_from_corner_archive() -> None:
    payload = build_track_map(_corner_archive())
    assert payload is not None
    assert payload["source"] == "reference_archive"
    assert payload["track_id"] == "magione"
    assert payload["car_id"] == "ks_porsche_911_gt3_r_2016"

    outline = payload["outline"]
    spline = payload["spline"]
    assert len(outline) == len(spline)
    assert 8 <= len(outline) <= MAX_OUTLINE_POINTS
    assert all(len(p) == 2 for p in outline)
    # spline-ordered: monotonically nondecreasing
    assert all(spline[i] <= spline[i + 1] for i in range(len(spline) - 1))

    corners = payload["corners"]
    assert len(corners) == 1  # the fixture is a single braking corner
    corner = corners[0]
    assert corner["label"] == "T1"
    assert 0.0 < corner["spline"] < 1.0
    assert corner["entry_spline"] <= corner["spline"]
    # apex minimum in the fixture is 25 m/s = 90 km/h
    assert 80 <= corner["min_speed_kmh"] <= 100
    assert corner.get("gear") == 4


def test_build_track_map_downsamples_long_traces() -> None:
    archive = _corner_archive()
    trace = archive["trace"]
    # inflate the trace ~20x by repeating samples with advancing spline
    base = trace["samples"]
    big = []
    n = len(base) * 20
    for i in range(n):
        row = list(base[i % len(base)])
        row[0] = i / n  # spline strictly increasing
        big.append(row)
    trace["samples"] = big
    trace["samples_count"] = len(big)

    payload = build_track_map(archive)
    assert payload is not None
    assert len(payload["outline"]) <= MAX_OUTLINE_POINTS


def test_build_track_map_honest_none_on_malformed() -> None:
    assert build_track_map({}) is None
    assert build_track_map({"trace": {"fields": ["spline"], "samples": []}}) is None
    # position channels missing -> None, never invented geometry
    archive = _corner_archive()
    fields = archive["trace"]["fields"]
    px_i = fields.index("px")
    pz_i = fields.index("pz")
    for row in archive["trace"]["samples"]:
        row[px_i] = None
        row[pz_i] = None
    archive["trace"]["fields"] = [f for f in fields if f not in ("px", "pz")]
    archive["trace"]["samples"] = [
        [v for i, v in enumerate(row) if i not in (px_i, pz_i)]
        for row in archive["trace"]["samples"]
    ]
    assert build_track_map(archive) is None


def test_build_track_map_rejects_degenerate_zero_positions() -> None:
    """Zero-filled px/pz columns (present-but-unreadable) must yield None — a collapsed
    single-point 'outline' would hide the honest no-reference state (Codex on PR #618)."""
    archive = _corner_archive()
    fields = archive["trace"]["fields"]
    px_i, pz_i = fields.index("px"), fields.index("pz")
    for row in archive["trace"]["samples"]:
        row[px_i] = 0.0
        row[pz_i] = 0.0
    assert build_track_map(archive) is None


def test_build_track_map_always_keeps_the_final_sample() -> None:
    """Downsampling must include the last sample — dropping the S/F tail makes the client's
    closing segment a false chord (daemon MEDIUM on PR #618)."""
    archive = _corner_archive()
    trace = archive["trace"]
    base = trace["samples"]
    n = len(base) * 20 + 7  # deliberately NOT divisible by the step
    big = []
    for i in range(n):
        row = list(base[i % len(base)])
        row[0] = i / n
        big.append(row)
    trace["samples"] = big
    trace["samples_count"] = len(big)

    payload = build_track_map(archive)
    assert payload is not None
    assert payload["spline"][-1] == round(big[-1][0], 4)
