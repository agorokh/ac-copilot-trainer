"""Tests for the #572 alien-line artifact: build, corridor validation, cache identity gates."""

from __future__ import annotations

import json
import math
import struct

import pytest

from tools.ac_harness.alien_line import (
    ALIEN_LINE_SCHEMA_VERSION,
    alien_line_path,
    build_alien_line_artifact,
    ensure_alien_line_artifact,
    fast_lane_sha12,
    load_alien_line_artifact,
    plant_provenance,
    save_alien_line_artifact,
    validate_corridor,
)
from tools.ac_harness.auto_drive import generic_gt3_ggv

_N = 240
_R = 120.0


def _circle_line(n: int = _N, r: float = _R) -> list[tuple[float, float, float]]:
    return [
        (r * math.cos(2 * math.pi * i / n), 0.0, r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _write_fast_lane(path, pts, side_left, side_right) -> None:
    """Minimal valid fast_lane.ai: v7 header + 20-byte points + 72-byte AiPointExtra block."""
    buf = bytearray(struct.pack("<4i", 7, len(pts), 0, len(pts)))
    for x, y, z in pts:
        buf += struct.pack("<3f", x, y, z)
        buf += struct.pack("<f", 0.0)  # length
        buf += struct.pack("<i", 0)  # id
    buf += struct.pack("<i", len(pts))  # lap extra
    for i in range(len(pts)):
        extra = bytearray(72)
        struct.pack_into("<2f", extra, 20, side_left[i], side_right[i])
        buf += extra
    path.write_bytes(bytes(buf))


def _plant_artifact(seed: str = "a") -> dict:
    return {"schema_version": 3, "created_utc": "2026-07-14T00:00:00Z", "constants": {"k": seed}}


@pytest.fixture
def lane(tmp_path):
    pts = _circle_line()
    path = tmp_path / "fast_lane.ai"
    _write_fast_lane(path, pts, [6.0] * _N, [6.0] * _N)
    return path, pts


def test_build_artifact_stays_in_corridor_and_respects_envelope(lane):
    path, pts = lane
    plant = generic_gt3_ggv()
    art = build_alien_line_artifact(
        pts,
        path,
        plant,
        _plant_artifact(),
        car_id="car_a",
        track_id="trk",
        margin_m=1.0,
        iters=400,
        v_top_kmh=220.0,
    )
    assert art["schema_version"] == ALIEN_LINE_SCHEMA_VERSION
    assert len(art["line"]) == _N and len(art["v_target_mps"]) == _N
    # Every optimized point stays within (side - margin) of its base point (corridor bound).
    for base, opt in zip(pts, art["line"], strict=True):
        off = math.hypot(opt[0] - base[0], opt[2] - base[2])
        assert off <= 6.0 - 1.0 + 1e-6
        assert opt[1] == base[1]  # y carried through
    assert art["qss"]["qss_laptime_s"] > 0
    assert art["corridor"]["max_ay_utilisation"] <= 1.0 + 1e-6
    assert all(v > 0 and math.isfinite(v) for v in art["v_target_mps"])
    # On a constant-curvature circle the corner speed must sit on the lateral envelope,
    # not above it: v^2 * kappa <= ay_max(v) [m/s^2] everywhere (checked by the builder).
    v0 = art["v_target_mps"][0]
    assert v0 * v0 * (1.0 / _R) <= plant.ay_max(v0) * 1.05


def test_build_rejects_short_line(lane):
    path, _ = lane
    with pytest.raises(ValueError, match="at least 3"):
        build_alien_line_artifact(
            [(0.0, 0.0, 0.0)], path, generic_gt3_ggv(), _plant_artifact(), car_id="c", track_id="t"
        )


@pytest.mark.parametrize(
    ("left", "right", "match"),
    [
        ([float("nan")] + [6.0] * (_N - 1), [6.0] * _N, "non-finite"),
        ([-1.0] + [6.0] * (_N - 1), [6.0] * _N, "absurd"),
        ([120.0] + [6.0] * (_N - 1), [6.0] * _N, "absurd"),
        ([1.0] + [6.0] * (_N - 1), [1.0] + [6.0] * (_N - 1), "narrower than a car"),
        ([6.0] * (_N - 1), [6.0] * _N, "length mismatch"),
    ],
)
def test_validate_corridor_fails_loud(left, right, match):
    with pytest.raises(ValueError, match=match):
        validate_corridor(left, right, _N)


def test_build_fails_loud_on_garbage_corridor(tmp_path):
    pts = _circle_line()
    path = tmp_path / "fast_lane.ai"
    # A drifted AiPointExtra layout parses "successfully" into absurd widths.
    _write_fast_lane(path, pts, [4242.0] * _N, [6.0] * _N)
    with pytest.raises(ValueError, match="absurd corridor width"):
        build_alien_line_artifact(
            pts, path, generic_gt3_ggv(), _plant_artifact(), car_id="c", track_id="t"
        )


def _build_and_save(tmp_path, lane, plant_art, **kw):
    path, pts = lane
    art = build_alien_line_artifact(
        pts,
        path,
        generic_gt3_ggv(),
        plant_art,
        car_id="car_a",
        track_id="trk",
        iters=200,
        **kw,
    )
    save_alien_line_artifact(tmp_path, art)
    return art


def test_cache_roundtrip_and_identity_gates(tmp_path, lane):
    path, _pts = lane
    plant_art = _plant_artifact()
    art = _build_and_save(tmp_path, lane, plant_art)
    prov = plant_provenance(plant_art)
    sha = fast_lane_sha12(path)
    params = art["params"]

    loaded = load_alien_line_artifact(
        tmp_path,
        "car_a",
        "trk",
        expected_plant_provenance=prov,
        expected_fast_lane_sha12=sha,
        params=params,
    )
    assert loaded is not None
    assert isinstance(loaded["line"][0], tuple)
    assert loaded["v_target_mps"] == pytest.approx(art["v_target_mps"])

    # A re-identified plant (different fit content) rejects the cache.
    stale_prov = plant_provenance(_plant_artifact(seed="b"))
    assert (
        load_alien_line_artifact(
            tmp_path,
            "car_a",
            "trk",
            expected_plant_provenance=stale_prov,
            expected_fast_lane_sha12=sha,
            params=params,
        )
        is None
    )
    # A re-baked AI line rejects the cache.
    assert (
        load_alien_line_artifact(
            tmp_path,
            "car_a",
            "trk",
            expected_plant_provenance=prov,
            expected_fast_lane_sha12="0" * 12,
            params=params,
        )
        is None
    )
    # Changed build params reject the cache.
    assert (
        load_alien_line_artifact(
            tmp_path,
            "car_a",
            "trk",
            expected_plant_provenance=prov,
            expected_fast_lane_sha12=sha,
            params={**params, "margin_m": 2.0},
        )
        is None
    )
    # Another combo / layout never sees this cache (separate identity-keyed file).
    assert (
        load_alien_line_artifact(
            tmp_path,
            "car_b",
            "trk",
            expected_plant_provenance=prov,
            expected_fast_lane_sha12=sha,
            params=params,
        )
        is None
    )
    assert (
        load_alien_line_artifact(
            tmp_path,
            "car_a",
            "trk",
            layout="gp",
            expected_plant_provenance=prov,
            expected_fast_lane_sha12=sha,
            params=params,
        )
        is None
    )


def test_cache_rejects_corruption_and_schema_drift(tmp_path, lane):
    path, _pts = lane
    plant_art = _plant_artifact()
    art = _build_and_save(tmp_path, lane, plant_art)
    prov = plant_provenance(plant_art)
    sha = fast_lane_sha12(path)
    cache_path = alien_line_path(tmp_path, "car_a", "trk")

    def load():
        return load_alien_line_artifact(
            tmp_path,
            "car_a",
            "trk",
            expected_plant_provenance=prov,
            expected_fast_lane_sha12=sha,
            params=art["params"],
        )

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["schema_version"] = ALIEN_LINE_SCHEMA_VERSION + 1
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    assert load() is None

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["schema_version"] = ALIEN_LINE_SCHEMA_VERSION
    payload["v_target_mps"][3] = float("nan")
    cache_path.write_text(json.dumps(payload), encoding="utf-8", errors="ignore")
    # json can't serialize nan by default -> write via allow_nan (json.dumps default allows it)
    assert load() is None

    cache_path.write_text("{not json", encoding="utf-8")
    assert load() is None


def test_ensure_builds_then_caches_then_invalidates(tmp_path, lane):
    path, _pts = lane
    plant = generic_gt3_ggv()
    plant_art = _plant_artifact()
    kw = dict(car_id="car_a", track_id="trk", iters=200)

    art1, src1 = ensure_alien_line_artifact(tmp_path, path, plant, plant_art, **kw)
    assert src1 == "built"
    assert alien_line_path(tmp_path, "car_a", "trk").exists()

    art2, src2 = ensure_alien_line_artifact(tmp_path, path, plant, plant_art, **kw)
    assert src2 == "cache"
    assert art2["v_target_mps"] == pytest.approx(art1["v_target_mps"])

    _art3, src3 = ensure_alien_line_artifact(tmp_path, path, plant, plant_art, rebuild=True, **kw)
    assert src3 == "built"

    # A re-identified plant invalidates the cache without an explicit rebuild.
    _art4, src4 = ensure_alien_line_artifact(tmp_path, path, plant, _plant_artifact(seed="b"), **kw)
    assert src4 == "built"


def test_pinch_points_counted_and_clearance_never_reduced(tmp_path):
    pts = _circle_line()
    path = tmp_path / "fast_lane.ai"
    # Left side inside the default margin on a stretch of points: a wall-hugging stock line.
    sl = [0.5 if i < 20 else 6.0 for i in range(_N)]
    _write_fast_lane(path, pts, sl, [6.0] * _N)
    art = build_alien_line_artifact(
        pts,
        path,
        generic_gt3_ggv(),
        _plant_artifact(),
        car_id="c",
        track_id="t",
        margin_m=1.2,
        iters=200,
    )
    assert art["corridor"]["pinch_points"] == 20
    # At pinched points the line may only hold or improve the stock clearance toward that edge:
    # the signed offset toward the pinched (left) side must be <= 0 within tolerance.
    base = [(p[0], p[2]) for p in pts]
    from tools.ac_harness.ggv_profile import _unit_normals

    normals = _unit_normals(base)
    for i in range(20):
        dx = art["line"][i][0] - base[i][0]
        dz = art["line"][i][2] - base[i][1]
        alpha = dx * normals[i][0] + dz * normals[i][1]
        assert alpha <= 1e-6  # never toward the pinched left edge


def test_cache_content_revalidated_on_hit(tmp_path, lane):
    path, _pts = lane
    plant = generic_gt3_ggv()
    plant_art = _plant_artifact()
    kw = dict(car_id="car_a", track_id="trk", iters=200)
    _art, src = ensure_alien_line_artifact(tmp_path, path, plant, plant_art, **kw)
    assert src == "built"

    # Tamper the cached profile: inflate every v_target 2x. Identity/provenance hashes still
    # match (they gate the INPUTS, not the artifact content) — revalidation must catch it.
    cache_path = alien_line_path(tmp_path, "car_a", "trk")
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["v_target_mps"] = [v * 2.0 for v in payload["v_target_mps"]]
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    _art2, src2 = ensure_alien_line_artifact(tmp_path, path, plant, plant_art, **kw)
    assert src2 == "built"  # rejected + rebuilt, never driven

    # Tamper the geometry: shove one point far off the corridor.
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["line"][10][0] += 25.0
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    _art3, src3 = ensure_alien_line_artifact(tmp_path, path, plant, plant_art, **kw)
    assert src3 == "built"

    # Untampered cache still hits.
    _art4, src4 = ensure_alien_line_artifact(tmp_path, path, plant, plant_art, **kw)
    assert src4 == "cache"


def test_verify_alien_line_artifact_reasons(lane):
    from tools.ac_harness.alien_line import verify_alien_line_artifact

    path, pts = lane
    plant = generic_gt3_ggv()
    art = build_alien_line_artifact(
        pts, path, plant, _plant_artifact(), car_id="c", track_id="t", iters=200
    )
    sl = [6.0] * _N
    sr = [6.0] * _N
    ok_payload = {"line": art["line"], "v_target_mps": art["v_target_mps"]}
    assert verify_alien_line_artifact(ok_payload, pts, sl, sr, plant, margin_m=1.2) is None

    short = {"line": art["line"][:-1], "v_target_mps": art["v_target_mps"][:-1]}
    assert "points" in verify_alien_line_artifact(short, pts, sl, sr, plant, margin_m=1.2)

    bad_geo = {"line": list(art["line"]), "v_target_mps": art["v_target_mps"]}
    bad_geo["line"][5] = (art["line"][5][0] + 25.0, art["line"][5][1], art["line"][5][2] + 25.0)
    assert "not a lateral offset" in verify_alien_line_artifact(
        bad_geo, pts, sl, sr, plant, margin_m=1.2
    )

    hot = {"line": art["line"], "v_target_mps": [v * 2.0 for v in art["v_target_mps"]]}
    assert "envelope" in verify_alien_line_artifact(hot, pts, sl, sr, plant, margin_m=1.2)


def test_build_rejects_degenerate_params(lane):
    path, pts = lane
    plant = generic_gt3_ggv()
    for bad_vtop in (0.0, -10.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="v_top_kmh"):
            build_alien_line_artifact(
                pts, path, plant, _plant_artifact(), car_id="c", track_id="t", v_top_kmh=bad_vtop
            )
    with pytest.raises(ValueError, match="margin_m"):
        build_alien_line_artifact(
            pts, path, plant, _plant_artifact(), car_id="c", track_id="t", margin_m=float("nan")
        )
    with pytest.raises(ValueError, match="iters"):
        build_alien_line_artifact(
            pts, path, plant, _plant_artifact(), car_id="c", track_id="t", iters=0
        )


def test_alien_prerequisites_error_paths(tmp_path, monkeypatch):
    # Qodo testability finding (#572): the --preflight-only alien readiness check is unit-tested
    # off-rig — no plant, corridor garbage, and the fully-ready path.
    from tools.ac_harness import auto_drive as ad
    from tools.ac_harness import plant_id as pid
    from tools.ac_harness.auto_drive import AutoDriveConfig, _alien_prerequisites_error

    cfg = AutoDriveConfig(track_id="trk", car_id="car_a", driver="alien")

    # Empty user dir: the real load path finds no artifact.
    msg = _alien_prerequisites_error(cfg, tmp_path)
    assert msg is not None and "no plant artifact" in msg

    # Plant ready (patched at the shared gate), corridor absurd -> loud corridor message.
    monkeypatch.setattr(pid, "load_plant_artifact", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr(
        pid, "plant_ready_for_full_consumption", lambda art, *, require_friction_fit: None
    )
    pts = _circle_line()
    bad_lane = tmp_path / "bad" / "fast_lane.ai"
    bad_lane.parent.mkdir()
    _write_fast_lane(bad_lane, pts, [4242.0] * _N, [6.0] * _N)
    monkeypatch.setattr(ad, "resolve_fast_lane", lambda *a, **kw: bad_lane)
    msg = _alien_prerequisites_error(cfg, tmp_path)
    assert msg is not None and "absurd corridor" in msg

    # Fully ready: valid plant + valid corridor -> None, and nothing was written.
    good_lane = tmp_path / "good" / "fast_lane.ai"
    good_lane.parent.mkdir()
    _write_fast_lane(good_lane, pts, [6.0] * _N, [6.0] * _N)
    monkeypatch.setattr(ad, "resolve_fast_lane", lambda *a, **kw: good_lane)
    assert _alien_prerequisites_error(cfg, tmp_path) is None
    assert not (tmp_path / "alien_line").exists()  # read-only: no cache write


def test_envelope_verification_rejects_overspeed(lane):
    from tools.ac_harness.alien_line import _verify_lateral_envelope

    _path, pts = lane
    plane = [(p[0], p[2]) for p in pts]
    plant = generic_gt3_ggv()
    # 100 m/s on a 120 m radius = 8.5 g lateral — far beyond any GT3 envelope.
    with pytest.raises(ValueError, match="exceeds the plant lateral envelope"):
        _verify_lateral_envelope(plane, [100.0] * len(plane), plant)
