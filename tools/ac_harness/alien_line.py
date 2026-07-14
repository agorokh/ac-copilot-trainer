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

from tools.ac_harness.corner_refine import (
    L3Params,
    barrier_ggv,
    refine_profile,
    verify_refined_profile,
)
from tools.ac_harness.ggv_profile import (
    GGVModel,
    _unit_normals,
    curvature_profile,
    ggv_speed_profile_from_model,
    load_track_widths,
    min_curvature_line,
    seg_lengths,
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
    l3_params: L3Params | None = None,
) -> dict:
    """Build the combo's optimized line + QSS profile artifact from its identified plant.

    Pure and off-rig testable: ``fast_line`` is the stock AI line geometry, ``width_path`` the
    ``fast_lane.ai`` carrying the corridor extras, ``plant`` the identified (uncertainty-aware)
    friction model and ``plant_artifact`` the full loaded plant payload (for provenance). Raises
    on an invalid corridor or an envelope violation — never returns a degraded artifact.

    ``l3_params`` opts in to the #582 beyond-QSS per-corner refinement: the artifact then carries
    the refined profile in ``v_target_mps``, the untouched QSS profile in ``v_target_qss_mps``,
    the per-corner report under ``l3``, and the refinement parameters inside ``params`` (so the
    cache identity distinguishes refined from plain artifacts). ``None`` (the default) keeps the
    artifact byte-compatible with pre-#582 builds.
    """
    if len(fast_line) < 3:
        raise ValueError("alien line requires at least 3 fast-line points")
    # A zero / negative / non-finite speed cap would make the QSS profiler emit degenerate
    # v_target values that pass the lateral-envelope check trivially (#572 Codex review).
    if not (math.isfinite(v_top_kmh) and v_top_kmh > 0):
        raise ValueError(f"v_top_kmh must be finite and > 0 (got {v_top_kmh})")
    if not (math.isfinite(margin_m) and margin_m >= 0):
        raise ValueError(f"margin_m must be finite and >= 0 (got {margin_m})")
    if iters <= 0:
        raise ValueError(f"iters must be > 0 (got {iters})")
    plane = [(p[0], p[2]) for p in fast_line]
    side_left, side_right = load_track_widths(width_path)
    validate_corridor(side_left, side_right, len(plane))
    opt_plane, alpha = min_curvature_line(
        plane, side_left, side_right, margin_m=margin_m, iters=iters
    )
    # Defensive post-QP bound check: the optimizer must never have moved a point closer to an
    # edge than min(stock clearance, margin). At a pinch point (a side already inside the margin
    # on the STOCK line — e.g. a wall-hugging chicane) the bound toward that edge collapses to 0,
    # so the line can only hold or IMPROVE the stock clearance there — AC's own drivable
    # fast_lane is the ground-truth floor. Pinch points are counted in the corridor stats rather
    # than rejected (rejecting would brick every track whose stock line touches a wall once)
    # (#572 Codex review).
    pinch_points = 0
    for i, a in enumerate(alpha):
        lo = min(0.0, -(side_right[i] - margin_m))
        hi = max(0.0, side_left[i] - margin_m)
        if not lo - 1e-9 <= a <= hi + 1e-9:
            raise ValueError(
                f"optimizer offset out of corridor bounds at point {i}: "
                f"alpha={a:.3f} not in [{lo:.3f}, {hi:.3f}]"
            )
        if side_left[i] < margin_m or side_right[i] < margin_m:
            pinch_points += 1
    optimized = [(opt_plane[i][0], fast_line[i][1], opt_plane[i][1]) for i in range(len(fast_line))]
    v_target, summ = ggv_speed_profile_from_model(optimized, plant, v_top_kmh=v_top_kmh)
    worst_ay = _verify_lateral_envelope(opt_plane, v_target, plant)
    params: dict = {"margin_m": margin_m, "iters": iters, "v_top_kmh": v_top_kmh}
    l3_block: dict | None = None
    v_qss = list(v_target)
    if l3_params is not None:
        # #582 L3: refine the QSS interior per corner against the evidence-backed relaxed grip,
        # then re-verify the refined profile against the stability barrier the same way the
        # cache-revalidation path will — a build that cannot pass its own verifier must fail
        # here, never persist (fail loud, never degrade).
        kappa = curvature_profile(opt_plane)
        seg = seg_lengths(opt_plane)
        v_target, l3_block = refine_profile(
            seg, kappa, v_qss, plant, l3_params, v_top_ms=v_top_kmh / 3.6
        )
        reason = verify_refined_profile(opt_plane, kappa, v_target, plant, l3_params)
        if reason is not None:
            raise ValueError(f"L3-refined profile failed its own barrier verification: {reason}")
        # corridor.max_ay_utilisation stays the QSS-vs-safe-envelope metric (pinned at <= 1 by
        # construction). The DRIVEN profile is the refined one, so the l3 report carries its own
        # utilisation honestly: vs the stability barrier (the refined profile's actual contract,
        # <= 1) and vs the safe envelope (deliberately > 1 inside refined corners — the whole
        # point of L3, and the number the run evidence must not under-report; #583 Codex P2).
        barrier = barrier_ggv(plant, l3_params.max_rel_std)
        l3_block["max_ay_utilisation_vs_barrier"] = round(
            max((v * v * abs(kappa[i])) / barrier.ay_max(v) for i, v in enumerate(v_target)),
            4,
        )
        l3_block["max_ay_utilisation_vs_safe"] = round(
            max((v * v * abs(kappa[i])) / plant.ay_max(v) for i, v in enumerate(v_target)),
            4,
        )
        params["l3"] = l3_params.to_dict()
    artifact = {
        "schema_version": ALIEN_LINE_SCHEMA_VERSION,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "car_id": car_id,
        "track_id": track_id,
        "layout": layout,
        "setup": setup,
        "plant_provenance": plant_provenance(plant_artifact),
        "fast_lane_sha12": fast_lane_sha12(width_path),
        "params": params,
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
            # Points where the STOCK line itself sits inside the margin of an edge: the bound
            # toward that edge is 0, so the optimized line holds or improves stock clearance —
            # never worse than AC's own drivable line.
            "pinch_points": pinch_points,
        },
    }
    if l3_block is not None:
        artifact["v_target_qss_mps"] = v_qss
        artifact["l3"] = l3_block
    return artifact


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
    # A refined (#582) artifact must carry a sane QSS fallback profile alongside the refined one.
    # L3-typing is decided by the IDENTITY block (params.l3), not by the presence of the payload
    # "l3" report: an artifact whose params say L3 but whose l3 report / QSS fallback is missing
    # is malformed (it would silently drop the fallback + reporting for an L3-identified cache),
    # and an "l3" report without the params identity is equally inconsistent (#583 Qodo).
    params_block = payload.get("params")
    is_l3 = isinstance(params_block, dict) and params_block.get("l3") is not None
    if is_l3 != ("l3" in payload):
        return None
    if is_l3:
        if not isinstance(payload.get("l3"), dict):
            return None
        v_qss = payload.get("v_target_qss_mps")
        if not isinstance(v_qss, list) or len(v_qss) != len(vt):
            return None
        try:
            vq = [float(v) for v in v_qss]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(v) and v > 0 for v in vq):
            return None
        payload["v_target_qss_mps"] = vq
    payload["line"] = pts
    payload["v_target_mps"] = vt
    return payload


def verify_alien_line_artifact(
    payload: dict,
    fast_line: list[tuple[float, float, float]],
    side_left: list[float],
    side_right: list[float],
    plant: GGVModel,
    *,
    margin_m: float,
) -> str | None:
    """Re-verify a cached artifact against the CURRENT corridor and plant; reason or ``None``.

    Matching identity/provenance hashes prove the inputs did not change — not that the cached
    geometry/profile is sound (an edited or corrupted durable JSON, or one written by a buggy
    earlier build, keeps its hashes). Re-run the same safety checks the build path applies before
    the cache is ever driven (#572 Codex review): every cached point must be a purely-lateral,
    in-bounds offset of the current stock line, and the cached profile must respect the current
    plant's lateral envelope.
    """
    line = payload.get("line") or []
    v_target = payload.get("v_target_mps") or []
    if len(line) != len(fast_line):
        return f"cached line has {len(line)} points but fast_lane has {len(fast_line)}"
    base = [(p[0], p[2]) for p in fast_line]
    normals = _unit_normals(base)
    cached_plane = [(p[0], p[2]) for p in line]
    for i, (bx, bz) in enumerate(base):
        dx = cached_plane[i][0] - bx
        dz = cached_plane[i][1] - bz
        nx, nz = normals[i]
        alpha = dx * nx + dz * nz
        residual = math.hypot(dx - alpha * nx, dz - alpha * nz)
        if residual > 0.5:
            return f"cached point {i} is not a lateral offset of the stock line ({residual:.2f} m)"
        lo = min(0.0, -(side_right[i] - margin_m))
        hi = max(0.0, side_left[i] - margin_m)
        if not lo - 1e-6 <= alpha <= hi + 1e-6:
            return (
                f"cached point {i} outside the corridor bounds: alpha={alpha:.3f} "
                f"not in [{lo:.3f}, {hi:.3f}]"
            )
    # L3-typing keys on the identity block (params.l3), consistent with the loader (#583 Qodo).
    verify_params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    if (verify_params.get("l3") is not None) != ("l3" in payload):
        return "l3 identity/params mismatch: params.l3 and the l3 report must be present together"
    if "l3" in payload:
        # #582: a refined profile deliberately exceeds the safe LCB envelope inside refined
        # corners — its contract is the stability barrier instead, re-derived from the CURRENT
        # plant and the artifact's validated refinement params (tampered/laxer params fail
        # ``L3Params.from_dict`` and reject the cache). The persisted QSS fallback must still
        # honor the plain safe envelope.
        try:
            l3_params = L3Params.from_dict(verify_params.get("l3"))
        except ValueError as exc:
            return f"cached l3 params invalid: {exc}"
        v_qss = payload.get("v_target_qss_mps") or []
        if len(v_qss) != len(v_target):
            return (
                f"cached QSS fallback has {len(v_qss)} points but the refined profile "
                f"has {len(v_target)}"
            )
        try:
            _verify_lateral_envelope(cached_plane, v_qss, plant)
        except ValueError as exc:
            return f"cached QSS fallback fails the current plant envelope: {exc}"
        # The build contract is refined >= QSS pointwise (a reverted corner keeps QSS exactly).
        # An edited durable JSON that inflates the fallback above the refined profile (or slows
        # refined points below it) breaks that invariant even when both profiles individually
        # respect their envelopes — reject it like any other tamper (#583 Codex P2).
        for i, (v_ref, v_fallback) in enumerate(zip(v_target, v_qss, strict=True)):
            if v_ref < v_fallback - 1e-6:
                return (
                    f"cached refined profile falls below its QSS fallback at point {i}: "
                    f"{v_ref:.3f} < {v_fallback:.3f} m/s"
                )
        kappa = curvature_profile(cached_plane)
        reason = verify_refined_profile(cached_plane, kappa, v_target, plant, l3_params)
        if reason is not None:
            return f"cached refined profile fails the current stability barrier: {reason}"
        return None
    try:
        _verify_lateral_envelope(cached_plane, v_target, plant)
    except ValueError as exc:
        return f"cached profile fails the current plant envelope: {exc}"
    return None


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
    l3_params: L3Params | None = None,
    rebuild: bool = False,
) -> tuple[dict, str]:
    """Load the fresh cached alien line or build + persist it. Returns ``(artifact, source)``.

    ``source`` is ``"cache"`` or ``"built"`` so callers can log the provenance of what they drive.
    ``l3_params`` rides the cache identity: enabling (or re-tuning) the #582 refinement changes
    the expected ``params`` block, so a plain-QSS cache never serves an L3 request and vice versa.
    """
    from tools.ac_harness.ai_line import load_ai_line

    prov = plant_provenance(plant_artifact)
    lane_sha = fast_lane_sha12(fast_lane_path)
    params = {"margin_m": margin_m, "iters": iters, "v_top_kmh": v_top_kmh}
    if l3_params is not None:
        params["l3"] = l3_params.to_dict()
    fast_line = load_ai_line(fast_lane_path)
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
            # Hashes prove the inputs match; re-verify the cached CONTENT against the current
            # corridor + plant before it is ever driven (an edited/corrupted durable JSON keeps
            # its hashes). A failed verification falls through to an honest rebuild.
            side_left, side_right = load_track_widths(fast_lane_path)
            validate_corridor(side_left, side_right, len(fast_line))
            reason = verify_alien_line_artifact(
                cached, fast_line, side_left, side_right, plant, margin_m=margin_m
            )
            if reason is None:
                return cached, "cache"
            logger.warning("alien line cache failed revalidation (%s); rebuilding", reason)
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
        l3_params=l3_params,
    )
    save_alien_line_artifact(user_dir, artifact, setup_ini=setup_ini)
    artifact = dict(artifact)
    artifact["line"] = [tuple(p) for p in artifact["line"]]
    return artifact, "built"
