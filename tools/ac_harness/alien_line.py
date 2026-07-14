"""Per-combo optimized racing line + QSS profile artifact (#572, EPIC #529 P2).

Composes the line-QP + QSS stages that already exist in :mod:`tools.ac_harness.ggv_profile` into a
durable, identity-gated artifact next to the plant artifact:

* **Build** — min-curvature line within the track corridor (``min_curvature_line`` bounded by the
  ``fast_lane.ai`` ``sideLeft``/``sideRight`` extras), then the forward-backward QSS min-time speed
  profile against the combo's identified uncertainty-aware
  :class:`~tools.ac_harness.ggv_profile.GGVModel`.
* **Cache** — persisted under ``Documents/Assetto Corsa/alien_line/`` (durable AC state, NEVER
  ``.scratch/`` — a gitignored scratch dir is disposable by contract and this repo has already lost
  runtime state to a cleanup once). Keyed by the same combo identity stem as the plant artifact
  (:func:`tools.ac_harness.plant_id.combo_artifact_stem`) PLUS the exact plant fit provenance and
  the ``fast_lane.ai`` content hash, so a re-identified plant or a re-baked AI line can never
  silently serve a stale optimized line.
* **Validate** — corridor widths are checked before the QP (the AiPointExtra layout drifts across
  CSP/track-tool versions; absurd widths must fail loudly, not produce an off-track line), and the
  built profile is checked against the plant's lateral envelope (fail loud, never degrade).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path

from tools.ac_harness.ggv_profile import (
    GGVModel,
    curvature_profile,
    ggv_speed_profile_from_model,
    load_track_widths,
    min_curvature_line,
)
from tools.ac_harness.plant_id import combo_artifact_stem

logger = logging.getLogger(__name__)

ALIEN_LINE_SCHEMA_VERSION = 1

# Corridor sanity bounds (metres). ``sideLeft``/``sideRight`` are per-point distances from the AI
# line to each track edge. A parse of a drifted AiPointExtra layout produces garbage well outside
# these: negative widths, kilometre-scale floats, NaN. Real circuits run ~4 m (kart track) to
# ~40 m (runway/oval apron) total width.
_SIDE_MAX_M = 60.0
_TOTAL_WIDTH_MIN_M = 3.0
# The QSS profile must respect the plant's lateral envelope by construction; tolerate only float
# noise when re-verifying it (fail loud on anything larger — that is a solver/plant bug).
_ENVELOPE_TOL = 1e-6


def alien_line_path(
    user_dir: Path,
    car_id: str,
    track_id: str,
    setup: str | None = None,
    setup_ini: str | Path | None = None,
    *,
    layout: str | None = None,
) -> Path:
    """The combo's alien-line artifact path (same identity stem as the plant artifact)."""
    stem = combo_artifact_stem(car_id, track_id, setup, setup_ini, layout=layout)
    return Path(user_dir) / "alien_line" / f"{stem}.json"


def plant_provenance(plant_artifact: dict) -> dict:
    """Stable provenance of the exact plant fit an alien line was computed from.

    A content hash over the canonical-JSON plant artifact (plus its ``created_utc`` for a human-
    readable anchor). Any re-identification — new probes, new thermal cohorts, schema bump —
    changes the hash, which invalidates every cached line derived from the previous fit.
    """
    canonical = json.dumps(plant_artifact, sort_keys=True, separators=(",", ":"))
    return {
        "created_utc": plant_artifact.get("created_utc"),
        "sha12": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12],
    }


def fast_lane_sha12(path: str | Path) -> str:
    """First 12 hex of the SHA-256 of the ``fast_lane.ai`` bytes (the corridor+geometry source)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def validate_corridor(
    side_left: list[float], side_right: list[float], n_points: int, *, source: str = "fast_lane.ai"
) -> None:
    """Reject a corridor that cannot be a real track before the QP consumes it.

    The AiPointExtra stride/offsets drift across CSP / track-tool versions (see
    :func:`~tools.ac_harness.ggv_profile.load_track_widths`); a same-size layout change parses
    "successfully" into garbage. Garbage in the corridor means the "optimized" line leaves the
    track — so fail loudly here, never downstream as a mysterious off-track drive.
    """
    if len(side_left) != n_points or len(side_right) != n_points:
        raise ValueError(
            f"corridor length mismatch vs line points in {source}: "
            f"left={len(side_left)}, right={len(side_right)}, line={n_points}"
        )
    for i, (sl, sr) in enumerate(zip(side_left, side_right, strict=True)):
        if not (math.isfinite(sl) and math.isfinite(sr)):
            raise ValueError(f"non-finite corridor width at point {i} in {source}: {sl}/{sr}")
        if sl < 0.0 or sr < 0.0 or sl > _SIDE_MAX_M or sr > _SIDE_MAX_M:
            raise ValueError(
                f"absurd corridor width at point {i} in {source}: sideLeft={sl:.2f} "
                f"sideRight={sr:.2f} (expected 0..{_SIDE_MAX_M:.0f} m per side — "
                "AiPointExtra layout drift? re-derive the offsets)"
            )
        if (sl + sr) < _TOTAL_WIDTH_MIN_M:
            raise ValueError(
                f"corridor narrower than a car at point {i} in {source}: "
                f"total={sl + sr:.2f} m < {_TOTAL_WIDTH_MIN_M} m"
            )


def _verify_lateral_envelope(
    plane: list[tuple[float, float]], v_target: list[float], plant: GGVModel
) -> float:
    """Max lateral utilisation of the profile vs the plant envelope; raises when exceeded.

    ``forward_backward_profile`` caps corner speed at ``v = sqrt(ay_max/|kappa|)`` by construction,
    so anything beyond float noise here is a solver or plant regression — the exact class of bug
    that spins the live car. Returns the max ``ay_used/ay_max`` ratio for the report.
    """
    kappa = curvature_profile(plane)
    worst = 0.0
    for i, v in enumerate(v_target):
        ay_limit = plant.ay_max(v)  # m/s^2 (GGVModel.ay_max applies G internally)
        if ay_limit <= 0:
            raise ValueError(f"plant lateral envelope non-positive at point {i} (v={v:.1f} m/s)")
        ratio = (v * v * abs(kappa[i])) / ay_limit
        worst = max(worst, ratio)
        if ratio > 1.0 + _ENVELOPE_TOL:
            raise ValueError(
                f"QSS profile exceeds the plant lateral envelope at point {i}: "
                f"v={v:.2f} m/s, kappa={kappa[i]:.5f} -> {ratio:.4f}x ay_max"
            )
    return worst


def build_alien_line_artifact(
    fast_line: list[tuple[float, float, float]],
    width_path: str | Path,
    plant: GGVModel,
    plant_artifact: dict,
    *,
    car_id: str,
    track_id: str,
    layout: str | None = None,
    setup: str | None = None,
    margin_m: float = 1.2,
    iters: int = 1200,
    v_top_kmh: float = 240.0,
) -> dict:
    """Build the combo's optimized line + QSS profile artifact from its identified plant.

    Pure and off-rig testable: ``fast_line`` is the stock AI line geometry, ``width_path`` the
    ``fast_lane.ai`` carrying the corridor extras, ``plant`` the identified (uncertainty-aware)
    friction model and ``plant_artifact`` the full loaded plant payload (for provenance). Raises
    on an invalid corridor or an envelope violation — never returns a degraded artifact.
    """
    if len(fast_line) < 3:
        raise ValueError("alien line requires at least 3 fast-line points")
    plane = [(p[0], p[2]) for p in fast_line]
    side_left, side_right = load_track_widths(width_path)
    validate_corridor(side_left, side_right, len(plane))
    opt_plane, alpha = min_curvature_line(
        plane, side_left, side_right, margin_m=margin_m, iters=iters
    )
    optimized = [(opt_plane[i][0], fast_line[i][1], opt_plane[i][1]) for i in range(len(fast_line))]
    v_target, summ = ggv_speed_profile_from_model(optimized, plant, v_top_kmh=v_top_kmh)
    worst_ay = _verify_lateral_envelope(opt_plane, v_target, plant)
    return {
        "schema_version": ALIEN_LINE_SCHEMA_VERSION,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "car_id": car_id,
        "track_id": track_id,
        "layout": layout,
        "setup": setup,
        "plant_provenance": plant_provenance(plant_artifact),
        "fast_lane_sha12": fast_lane_sha12(width_path),
        "params": {"margin_m": margin_m, "iters": iters, "v_top_kmh": v_top_kmh},
        "line": [[p[0], p[1], p[2]] for p in optimized],
        "v_target_mps": list(v_target),
        "qss": summ,
        "corridor": {
            "points": len(plane),
            "max_offset_m": round(max(abs(a) for a in alpha), 2),
            "min_total_width_m": round(
                min(sl + sr for sl, sr in zip(side_left, side_right, strict=True)), 2
            ),
            "max_ay_utilisation": round(worst_ay, 4),
        },
    }


def save_alien_line_artifact(
    user_dir: Path, artifact: dict, *, setup_ini: str | Path | None = None
) -> Path:
    """Persist the alien-line artifact atomically next to the plant artifact tree.

    ``setup_ini`` must be the same resolved INI the caller keys plant lookups with — the filename
    embeds its content hash, so save and load resolve the identical identity stem.
    """
    for key in ("car_id", "track_id"):
        if not artifact.get(key):
            raise ValueError(f"alien line artifact needs {key}")
    path = alien_line_path(
        Path(user_dir),
        str(artifact["car_id"]),
        str(artifact["track_id"]),
        artifact.get("setup"),
        setup_ini,
        layout=artifact.get("layout"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_alien_line_artifact(
    user_dir: Path,
    car_id: str,
    track_id: str,
    setup: str | None = None,
    setup_ini: str | Path | None = None,
    *,
    layout: str | None = None,
    expected_plant_provenance: dict,
    expected_fast_lane_sha12: str,
    params: dict | None = None,
) -> dict | None:
    """Load + validate the combo's cached alien line; ``None`` when absent or identity-stale.

    Staleness gates (each one alone rejects the cache — a stale line is never silently driven):
    schema version, combo identity, the exact plant fit provenance, the ``fast_lane.ai`` content
    hash, the build params, and finite line/profile geometry.
    """
    try:
        path = alien_line_path(user_dir, car_id, track_id, setup, setup_ini, layout=layout)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != ALIEN_LINE_SCHEMA_VERSION:
        return None
    if payload.get("car_id") != car_id or payload.get("track_id") != track_id:
        return None
    if payload.get("layout") != layout:
        return None
    prov = payload.get("plant_provenance")
    if not isinstance(prov, dict) or prov.get("sha12") != expected_plant_provenance.get("sha12"):
        logger.info("alien line cache rejected: plant fit changed since the line was built")
        return None
    if payload.get("fast_lane_sha12") != expected_fast_lane_sha12:
        logger.info("alien line cache rejected: fast_lane.ai content changed")
        return None
    if params is not None and payload.get("params") != params:
        logger.info("alien line cache rejected: build params changed")
        return None
    line = payload.get("line")
    v_target = payload.get("v_target_mps")
    if (
        not isinstance(line, list)
        or not isinstance(v_target, list)
        or len(line) < 3
        or len(line) != len(v_target)
    ):
        return None
    try:
        pts = [(float(p[0]), float(p[1]), float(p[2])) for p in line]
        vt = [float(v) for v in v_target]
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(c) for p in pts for c in p) or not all(
        math.isfinite(v) and v > 0 for v in vt
    ):
        return None
    payload["line"] = pts
    payload["v_target_mps"] = vt
    return payload


def ensure_alien_line_artifact(
    user_dir: Path,
    fast_lane_path: str | Path,
    plant: GGVModel,
    plant_artifact: dict,
    *,
    car_id: str,
    track_id: str,
    layout: str | None = None,
    setup: str | None = None,
    setup_ini: str | Path | None = None,
    margin_m: float = 1.2,
    iters: int = 1200,
    v_top_kmh: float = 240.0,
    rebuild: bool = False,
) -> tuple[dict, str]:
    """Load the fresh cached alien line or build + persist it. Returns ``(artifact, source)``.

    ``source`` is ``"cache"`` or ``"built"`` so callers can log the provenance of what they drive.
    """
    prov = plant_provenance(plant_artifact)
    lane_sha = fast_lane_sha12(fast_lane_path)
    params = {"margin_m": margin_m, "iters": iters, "v_top_kmh": v_top_kmh}
    if not rebuild:
        cached = load_alien_line_artifact(
            user_dir,
            car_id,
            track_id,
            setup,
            setup_ini,
            layout=layout,
            expected_plant_provenance=prov,
            expected_fast_lane_sha12=lane_sha,
            params=params,
        )
        if cached is not None:
            return cached, "cache"
    from tools.ac_harness.ai_line import load_ai_line

    fast_line = load_ai_line(fast_lane_path)
    artifact = build_alien_line_artifact(
        fast_line,
        fast_lane_path,
        plant,
        plant_artifact,
        car_id=car_id,
        track_id=track_id,
        layout=layout,
        setup=setup,
        margin_m=margin_m,
        iters=iters,
        v_top_kmh=v_top_kmh,
    )
    save_alien_line_artifact(user_dir, artifact, setup_ini=setup_ini)
    artifact = dict(artifact)
    artifact["line"] = [tuple(p) for p in artifact["line"]]
    return artifact, "built"
