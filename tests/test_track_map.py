"""#531 Part F: track.map geometry built from the reference archive."""

from __future__ import annotations

from tests.test_realtime_observer import _corner_archive
from tools.ai_sidecar.track_map import MAX_OUTLINE_POINTS, build_track_map


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
