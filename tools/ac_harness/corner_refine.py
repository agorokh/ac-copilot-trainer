"""Beyond-QSS per-corner interior refinement (L3, EPIC #529 / #582 — the #577 item-3 follow-up).

The forward-backward QSS profile (:func:`tools.ac_harness.ggv_profile.forward_backward_profile`)
consumes the **uncertainty-safe** grip curves: with a schema-v3 plant every query returns
``min(point_model, mean - 1.96*std)`` per 10 km/h bin (#543). That lower-confidence bound is the
right floor to *drive blind* — and the #577 self-play runs proved it is exactly what binds the lap
time (both Magione plants collapsed to the same 91.94 s floor: the bins, not the cars, bind).

L3 recovers the evidence-supported headroom **per corner, never globally**:

* **Segmentation** — corners are maximal cyclic windows of the optimized line where the QSS
  curvature magnitude exceeds a threshold, padded and merged, so every window is bracketed by
  low-curvature boundary points.
* **Corridor constraints from QSS** — the QSS speeds at each window's entry/exit points are fixed
  boundary conditions (pins). Refinement only reshapes the interior between them; straights and
  un-refined corners keep the QSS profile bit-for-bit.
* **Evidence gate** — a corner may relax a grip channel only through speed bins whose posterior is
  ``measured`` with bounded relative epistemic spread. Prior-dominated or high-variance bins stay
  at the safe LCB. A corner with no relaxable lateral bin in its speed range is NOT refined — the
  report names the revert reason (never a silent fallback).
* **Interior re-solve** — a boundary-pinned mini forward-backward pass over the window against the
  relaxed grip: higher evidence-backed apex speeds and a deeper friction-ellipse trail-brake into
  them (the backward pass with lateral coupling *is* the trail-brake shape). The z-ladder search
  is a deterministic grid; a candidate is accepted only when it is pointwise >= the QSS interior
  and strictly faster over the window.
* **Stability barrier** — no refined point may exceed ``mean - Z_STABILITY_FLOOR*std`` lateral
  (the slip-margin proxy available to a point-mass plant), enforced at build AND at every cache
  re-verification. The chosen ladder z is always >= the floor, so the barrier holds by
  construction; it is still checked explicitly (defense in depth against future grip-curve
  changes).

Everything here is offline, deterministic (fixed grids, no RNG) and stdlib-``math`` only, so CI
verifies it with synthetic lines + synthetic plants, no game. NOT end-to-end RL (council-hardened
design in the epic body). Falsification of the *driven* outcome stays with the #577
keep-last-valid oracle in :mod:`tools.ac_harness.auto_alien`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from tools.ac_harness.ggv_profile import (
    DEFAULT_UNCERTAINTY_LCB_Z,
    UNCERTAINTY_CHANNELS,
    GGVModel,
)

L3_SCHEMA_VERSION = 1

# The stability floor: refined speeds may never rely on grip above ``mean - 1.0*std``. This is a
# module constant, not a parameter — a persisted artifact must not be able to talk the verifier
# into a laxer barrier than the build honored.
Z_STABILITY_FLOOR = 1.0
# A measured bin whose epistemic spread exceeds this fraction of its mean is not relaxable: the
# mean itself is too poorly known to lean on, whatever z says.
MAX_REL_STD_CEILING = 0.5

DEFAULT_Z_LADDER = (1.5, Z_STABILITY_FLOOR)
DEFAULT_KAPPA_THRESHOLD = 0.005  # 1/m — corner when the local radius is under ~200 m
DEFAULT_PAD_POINTS = 3
DEFAULT_MIN_CORNER_POINTS = 5
DEFAULT_MAX_REL_STD = 0.25
_FB_PASSES = 4
_APEX_FIXED_POINT_ITERS = 8
_IMPROVE_TOL_MS = 1e-9  # m/s pointwise tolerance for "not slower than QSS"
_BARRIER_TOL = 1e-6  # float-noise tolerance on the lateral-utilisation barrier


@dataclass(frozen=True)
class L3Params:
    """Validated refinement parameters; persisted verbatim in the artifact ``params`` block."""

    z_ladder: tuple[float, ...] = DEFAULT_Z_LADDER
    kappa_threshold: float = DEFAULT_KAPPA_THRESHOLD
    pad_points: int = DEFAULT_PAD_POINTS
    min_corner_points: int = DEFAULT_MIN_CORNER_POINTS
    max_rel_std: float = DEFAULT_MAX_REL_STD

    def __post_init__(self) -> None:
        ladder = tuple(float(z) for z in self.z_ladder)
        if not ladder:
            raise ValueError("l3 z_ladder must not be empty")
        for z in ladder:
            if not math.isfinite(z):
                raise ValueError(f"l3 z_ladder values must be finite (got {z})")
            if z < Z_STABILITY_FLOOR:
                raise ValueError(
                    f"l3 z_ladder value {z} is below the stability floor {Z_STABILITY_FLOOR}"
                )
            if z > DEFAULT_UNCERTAINTY_LCB_Z:
                raise ValueError(
                    f"l3 z_ladder value {z} exceeds the safe LCB z "
                    f"{DEFAULT_UNCERTAINTY_LCB_Z} (that would be a derate, not a refinement)"
                )
        object.__setattr__(self, "z_ladder", ladder)
        if not (math.isfinite(self.kappa_threshold) and self.kappa_threshold > 0.0):
            raise ValueError(
                f"l3 kappa_threshold must be finite and > 0 (got {self.kappa_threshold})"
            )
        if not isinstance(self.pad_points, int) or self.pad_points < 0:
            raise ValueError(f"l3 pad_points must be an int >= 0 (got {self.pad_points})")
        if not isinstance(self.min_corner_points, int) or self.min_corner_points < 3:
            raise ValueError(
                f"l3 min_corner_points must be an int >= 3 (got {self.min_corner_points})"
            )
        if not (math.isfinite(self.max_rel_std) and 0.0 < self.max_rel_std <= MAX_REL_STD_CEILING):
            raise ValueError(
                f"l3 max_rel_std must be in (0, {MAX_REL_STD_CEILING}] (got {self.max_rel_std})"
            )

    def to_dict(self) -> dict:
        return {
            "schema_version": L3_SCHEMA_VERSION,
            "z_ladder": list(self.z_ladder),
            "kappa_threshold": self.kappa_threshold,
            "pad_points": self.pad_points,
            "min_corner_points": self.min_corner_points,
            "max_rel_std": self.max_rel_std,
        }

    @classmethod
    def from_dict(cls, data: object) -> L3Params:
        """Rebuild persisted params; raises ``ValueError`` on any tampered/unsafe value.

        Persisted artifacts are untrusted input (the durable JSON is hand-editable): the same
        validation that guards the build guards the re-verification, so a laxer-than-floor ladder
        or an absurd ``max_rel_std`` can never talk the verifier into accepting hotter speeds.
        """
        if not isinstance(data, dict):
            raise ValueError("l3 params must be a dict")
        if data.get("schema_version") != L3_SCHEMA_VERSION:
            raise ValueError(f"unsupported l3 params schema: {data.get('schema_version')!r}")
        ladder = data.get("z_ladder")
        if not isinstance(ladder, (list, tuple)):
            raise ValueError("l3 params z_ladder must be a list")
        try:
            return cls(
                z_ladder=tuple(float(z) for z in ladder),
                kappa_threshold=float(data["kappa_threshold"]),
                pad_points=int(data["pad_points"]),
                min_corner_points=int(data["min_corner_points"]),
                max_rel_std=float(data["max_rel_std"]),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"malformed l3 params: {exc}") from exc


def _relaxable_channel(channel: dict, max_rel_std: float) -> bool:
    """Whether one bin/channel posterior carries enough measured evidence to relax."""
    if channel.get("source") != "measured":
        return False
    mean = float(channel["mean_g"])
    std = float(channel["epistemic_std_g"])
    return mean > 0.0 and std / mean <= max_rel_std


def relaxed_ggv(ggv: GGVModel, z: float, max_rel_std: float) -> GGVModel:
    """The plant with measured, low-variance bins relaxed from the 1.96-z LCB to ``mean - z*std``.

    Prior-dominated and high-variance bins keep their original ``safe_g`` — evidence never leaks
    across bins, exactly the #543 contract. The relaxed value never drops below the original safe
    bound and never exceeds the posterior mean, so the frozen-model validation invariants hold.
    The point model stays the upper envelope (``_uncertainty_safe_g`` keeps the ``min``).
    """
    if not (math.isfinite(z) and Z_STABILITY_FLOOR <= z <= DEFAULT_UNCERTAINTY_LCB_Z):
        raise ValueError(
            f"relaxation z must be in [{Z_STABILITY_FLOOR}, {DEFAULT_UNCERTAINTY_LCB_Z}] (got {z})"
        )
    if not ggv.uncertainty_bins:
        return ggv
    relaxed_bins = []
    for speed_bin in ggv.uncertainty_bins:
        out = {
            "speed_min_kmh": speed_bin["speed_min_kmh"],
            "speed_max_kmh": speed_bin["speed_max_kmh"],
        }
        for kind in UNCERTAINTY_CHANNELS:
            channel = dict(speed_bin[kind])
            if _relaxable_channel(channel, max_rel_std):
                mean = float(channel["mean_g"])
                std = float(channel["epistemic_std_g"])
                relaxed = mean - z * std
                channel["safe_g"] = round(min(mean, max(float(channel["safe_g"]), relaxed)), 6)
            out[kind] = channel
        relaxed_bins.append(out)
    return replace(ggv, uncertainty_bins=tuple(relaxed_bins))


def barrier_ggv(ggv: GGVModel, max_rel_std: float) -> GGVModel:
    """The stability-barrier envelope: the most grip any refined point is allowed to rely on."""
    return relaxed_ggv(ggv, Z_STABILITY_FLOOR, max_rel_std)


def segment_corners(
    kappa: list[float],
    *,
    kappa_threshold: float,
    pad_points: int,
    min_corner_points: int,
) -> list[list[int]]:
    """Corner windows of a cyclic line: padded maximal runs of ``|kappa| >= threshold``.

    Returns windows as lists of consecutive absolute point indices (cyclic — a window may wrap
    index 0). Overlapping/adjacent padded runs merge into one window (an S-chicane is one
    refinement problem, not two overlapping ones). Windows shorter than ``min_corner_points``
    after padding are dropped. When the merged coverage leaves no low-curvature boundary at all
    (a kart-track lap that is one long corner), no window is returned — the caller reverts.
    """
    n = len(kappa)
    if n < 3:
        return []
    in_corner = [abs(k) >= kappa_threshold for k in kappa]
    if all(in_corner):
        return []
    if not any(in_corner):
        return []
    # Maximal cyclic runs: walk from a known out-of-corner anchor so runs never split at index 0.
    anchor = next(i for i in range(n) if not in_corner[i])
    runs: list[tuple[int, int]] = []  # (start, length) in absolute indices
    i = 0
    while i < n:
        idx = (anchor + i) % n
        if in_corner[idx]:
            start = idx
            length = 0
            while i < n and in_corner[(anchor + i) % n]:
                length += 1
                i += 1
            runs.append((start, length))
        else:
            i += 1
    # Pad each run, then merge padded runs that overlap or touch on the cycle.
    padded = []
    for start, length in runs:
        p_start = (start - pad_points) % n
        p_length = min(n, length + 2 * pad_points)
        padded.append((p_start, p_length))
    merged: list[tuple[int, int]] = []
    for start, length in padded:
        placed = False
        while not placed:
            placed = True
            for j, (mstart, mlength) in enumerate(merged):
                if _cyclic_overlap(start, length, mstart, mlength, n):
                    start, length = _cyclic_union(start, length, mstart, mlength, n)
                    del merged[j]
                    placed = False
                    break
        merged.append((start, length))
    windows = []
    for start, length in sorted(merged):
        if length < min_corner_points:
            continue
        if length >= n - 1:
            # No usable boundary pins remain; refuse rather than pin inside a corner.
            return []
        windows.append([(start + k) % n for k in range(length)])
    return windows


def _cyclic_overlap(s1: int, l1: int, s2: int, l2: int, n: int) -> bool:
    """Whether two cyclic arcs share an index OR touch (end-to-start adjacency).

    Adjacency counts as overlap on purpose: two padded windows that touch form one contiguous
    covered arc, and leaving them as separate windows would pin a "boundary" speed at a point
    that is itself inside the other corner's padded approach (#583 Qodo). Arc 1 is expanded by
    one index on each side, so a shared-index test also catches exact touching.
    """
    covered = [False] * n
    for k in range(min(n, l1 + 2)):
        covered[(s1 - 1 + k) % n] = True
    return any(covered[(s2 + k) % n] for k in range(l2))


def _cyclic_union(s1: int, l1: int, s2: int, l2: int, n: int) -> tuple[int, int]:
    covered = [False] * n
    for k in range(l1):
        covered[(s1 + k) % n] = True
    for k in range(l2):
        covered[(s2 + k) % n] = True
    if all(covered):
        return (0, n)
    # The union of two overlapping cyclic arcs is one arc: find its start (a covered point whose
    # predecessor is uncovered) and walk its length.
    start = next(i for i in range(n) if covered[i] and not covered[(i - 1) % n])
    length = 0
    while covered[(start + length) % n] and length < n:
        length += 1
    return (start, length)


def _window_time_s(idxs: list[int], seg: list[float], v: list[float]) -> float:
    """Travel time over a window (same trapezoidal-speed formula as the QSS laptime)."""
    total = 0.0
    for j in range(len(idxs) - 1):
        ds = seg[idxs[j]]
        total += ds / max(0.5, 0.5 * (v[j] + v[j + 1]))
    return total


def _spanned_bins(ggv: GGVModel, speeds_ms: list[float]) -> list[dict]:
    """The uncertainty bins the window's speed range passes through (by bin boundaries)."""
    if not ggv.uncertainty_bins or not speeds_ms:
        return []
    lo_kmh = min(speeds_ms) * 3.6
    hi_kmh = max(speeds_ms) * 3.6
    spanned = []
    for speed_bin in ggv.uncertainty_bins:
        if float(speed_bin["speed_max_kmh"]) <= lo_kmh:
            continue
        if float(speed_bin["speed_min_kmh"]) > hi_kmh:
            continue
        spanned.append(speed_bin)
    return spanned


def _solve_window(
    idxs: list[int],
    seg: list[float],
    kappa: list[float],
    v_qss: list[float],
    model: GGVModel,
    v_top_ms: float,
) -> list[float]:
    """Boundary-pinned forward-backward interior re-solve of one window against ``model``.

    The entry/exit speeds stay the QSS values (the corridor constraints); the interior follows
    the same apex/backward/forward structure as the global QSS pass, including the
    friction-ellipse lateral coupling — the backward branch with lateral usage IS the
    trail-brake shape.
    """
    m = len(idxs)
    v = [0.0] * m
    v[0] = v_qss[idxs[0]]
    v[-1] = v_qss[idxs[-1]]
    for j in range(1, m - 1):
        k = abs(kappa[idxs[j]])
        if k > 1e-6:
            vi = v_top_ms
            for _ in range(_APEX_FIXED_POINT_ITERS):
                vi = min(v_top_ms, math.sqrt(model.ay_max(vi) / k))
            v[j] = max(0.5, vi)
        else:
            v[j] = v_top_ms
    for _ in range(_FB_PASSES):
        for j in range(m - 2, 0, -1):
            ds = seg[idxs[j]]
            if ds <= 1e-6:
                if v[j + 1] < v[j]:
                    v[j] = v[j + 1]
                continue
            ay_used = v[j] * v[j] * abs(kappa[idxs[j]])
            ax = model.ax_brake_avail(ay_used, v[j])
            cap = math.sqrt(v[j + 1] * v[j + 1] + 2.0 * ax * ds)
            if cap < v[j]:
                v[j] = cap
        for j in range(1, m - 1):
            ds = seg[idxs[j - 1]]
            if ds <= 1e-6:
                if v[j - 1] < v[j]:
                    v[j] = v[j - 1]
                continue
            ay_used = v[j - 1] * v[j - 1] * abs(kappa[idxs[j - 1]])
            ax = model.ax_drive_avail(ay_used, v[j - 1])
            cap = math.sqrt(v[j - 1] * v[j - 1] + 2.0 * ax * ds)
            if cap < v[j]:
                v[j] = cap
    return v


def _barrier_violation(
    idxs: list[int],
    kappa: list[float],
    v: list[float],
    barrier: GGVModel,
) -> str | None:
    """The first stability-barrier violation in a refined window, or ``None``."""
    for j, i in enumerate(idxs):
        limit = barrier.ay_max(v[j])
        if limit <= 0.0:
            return f"barrier envelope non-positive at point {i} (v={v[j]:.1f} m/s)"
        ratio = (v[j] * v[j] * abs(kappa[i])) / limit
        if ratio > 1.0 + _BARRIER_TOL:
            return (
                f"lateral utilisation {ratio:.4f}x the stability barrier at point {i} "
                f"(v={v[j] * 3.6:.1f} km/h)"
            )
    return None


def refine_profile(
    seg: list[float],
    kappa: list[float],
    v_qss: list[float],
    ggv: GGVModel,
    params: L3Params,
    *,
    v_top_ms: float,
) -> tuple[list[float], dict]:
    """Refine the QSS ``v_target`` per corner; returns ``(v_refined, report)``.

    The report is complete and honest: every segmented corner appears exactly once, either
    ``refined`` (with the chosen z, the relaxed channels, the predicted gain and the barrier
    headroom) or ``reverted`` (with the named reason). Points outside refined corners — and every
    reverted corner's interior — carry the QSS speeds unchanged.
    """
    n = len(v_qss)
    if not (len(seg) == len(kappa) == n):
        raise ValueError(
            f"refine_profile arrays length mismatch: seg={len(seg)}, kappa={len(kappa)}, v={n}"
        )
    if n < 3:
        raise ValueError("refine_profile requires at least 3 points")
    if not (math.isfinite(v_top_ms) and v_top_ms > 0):
        raise ValueError(f"v_top_ms must be finite and > 0 (got {v_top_ms})")
    for i in range(n):
        if not (math.isfinite(seg[i]) and seg[i] >= 0.0):
            raise ValueError(f"non-finite/negative segment length at point {i}: {seg[i]}")
        if not math.isfinite(kappa[i]):
            raise ValueError(f"non-finite curvature at point {i}: {kappa[i]}")
        if not (math.isfinite(v_qss[i]) and v_qss[i] > 0.0):
            raise ValueError(f"non-finite/non-positive QSS speed at point {i}: {v_qss[i]}")

    report: dict = {
        "schema_version": L3_SCHEMA_VERSION,
        "params": params.to_dict(),
        "corners": [],
        "refined_corners": 0,
        "reverted_corners": 0,
        "predicted_gain_ms": 0,
    }
    v_out = list(v_qss)
    if not ggv.uncertainty_aware:
        report["reverted_all"] = "plant is not uncertainty-aware (legacy point model) — QSS kept"
        return v_out, report

    windows = segment_corners(
        kappa,
        kappa_threshold=params.kappa_threshold,
        pad_points=params.pad_points,
        min_corner_points=params.min_corner_points,
    )
    if not windows:
        report["reverted_all"] = (
            "no refinable corner window (line has no bracketed corner at "
            f"|kappa| >= {params.kappa_threshold})"
        )
        return v_out, report

    barrier = barrier_ggv(ggv, params.max_rel_std)
    relaxed_by_z = {z: relaxed_ggv(ggv, z, params.max_rel_std) for z in params.z_ladder}
    total_gain_s = 0.0
    for corner_id, idxs in enumerate(windows):
        v_window_qss = [v_qss[i] for i in idxs]
        entry: dict = {
            "corner": corner_id,
            "start": idxs[0],
            "end": idxs[-1],
            "points": len(idxs),
            "v_entry_kmh": round(v_window_qss[0] * 3.6, 1),
            "v_exit_kmh": round(v_window_qss[-1] * 3.6, 1),
        }
        report["corners"].append(entry)
        spanned = _spanned_bins(ggv, v_window_qss)
        relaxable_lateral = [
            f"{int(b['speed_min_kmh'])}-{int(b['speed_max_kmh'])}"
            for b in spanned
            if _relaxable_channel(dict(b["lateral"]), params.max_rel_std)
        ]
        relaxable_brake = [
            f"{int(b['speed_min_kmh'])}-{int(b['speed_max_kmh'])}"
            for b in spanned
            if _relaxable_channel(dict(b["brake"]), params.max_rel_std)
        ]
        relaxable_drive = [
            f"{int(b['speed_min_kmh'])}-{int(b['speed_max_kmh'])}"
            for b in spanned
            if _relaxable_channel(dict(b["drive"]), params.max_rel_std)
        ]
        if not relaxable_lateral:
            lo = min(v_window_qss) * 3.6
            hi = max(v_window_qss) * 3.6
            entry["status"] = "reverted"
            entry["reason"] = (
                f"no measured low-variance lateral bin in the corner's {lo:.0f}-{hi:.0f} km/h "
                "range — safe-QSS kept"
            )
            report["reverted_corners"] += 1
            continue

        qss_time = _window_time_s(idxs, seg, v_window_qss)
        best_candidate: tuple[float, float, list[float]] | None = None  # (time, z, speeds)
        rejected: list[str] = []
        for z in params.z_ladder:
            candidate = _solve_window(idxs, seg, kappa, v_qss, relaxed_by_z[z], v_top_ms)
            if any(candidate[j] < v_window_qss[j] - _IMPROVE_TOL_MS for j in range(len(idxs))):
                # The friction-ellipse coupling makes pointwise dominance an empirical check,
                # not an algebraic guarantee: a candidate that dips below QSS anywhere is not
                # an improvement contract we can keep — reject it honestly.
                rejected.append(f"z={z}: interior dipped below the QSS profile")
                continue
            violation = _barrier_violation(idxs, kappa, candidate, barrier)
            if violation is not None:
                rejected.append(f"z={z}: {violation}")
                continue
            cand_time = _window_time_s(idxs, seg, candidate)
            if best_candidate is None or cand_time < best_candidate[0]:
                best_candidate = (cand_time, z, candidate)
        if best_candidate is None or best_candidate[0] >= qss_time - 1e-9:
            entry["status"] = "reverted"
            entry["reason"] = "no ladder candidate beat the QSS interior" + (
                f" ({'; '.join(rejected)})" if rejected else " (relaxation had no effect)"
            )
            report["reverted_corners"] += 1
            continue
        cand_time, z, speeds = best_candidate
        for j, i in enumerate(idxs):
            v_out[i] = speeds[j]
        gain_s = qss_time - cand_time
        total_gain_s += gain_s
        entry["status"] = "refined"
        entry["z"] = z
        entry["relaxed_lateral_bins_kmh"] = relaxable_lateral
        entry["relaxed_brake_bins_kmh"] = relaxable_brake
        # The forward pass consumes relaxed drive bins too (ax_drive_avail) — report them so the
        # per-corner provenance names every channel the refinement leaned on (#583 Codex P2).
        entry["relaxed_drive_bins_kmh"] = relaxable_drive
        entry["gain_ms"] = int(round(gain_s * 1000.0))
        entry["v_apex_qss_kmh"] = round(min(v_window_qss) * 3.6, 1)
        entry["v_apex_l3_kmh"] = round(min(speeds) * 3.6, 1)
        report["refined_corners"] += 1

    report["predicted_gain_ms"] = int(round(total_gain_s * 1000.0))
    return v_out, report


def profile_utilisation(kappa: list[float], v_target: list[float], model: GGVModel) -> float:
    """Max lateral utilisation of a speed profile vs ``model.ay_max`` (1.0 = on the envelope).

    Pure and reusable: the build reports the refined profile vs the barrier and vs the safe
    envelope, and the run evidence reports the DRIVEN target (``v_target * ggv_scale``) vs the
    barrier — a scaled overspeed probe must never be recorded as within-barrier (#583 Codex P2).
    Raises on a length mismatch or a non-positive envelope (reporting must fail loud, not
    under-report).
    """
    if len(kappa) != len(v_target):
        raise ValueError(
            f"profile_utilisation arrays length mismatch: kappa={len(kappa)}, v={len(v_target)}"
        )
    worst = 0.0
    for i, v in enumerate(v_target):
        limit = model.ay_max(v)
        if limit <= 0.0:
            raise ValueError(f"lateral envelope non-positive at point {i} (v={v:.1f} m/s)")
        worst = max(worst, (v * v * abs(kappa[i])) / limit)
    return worst


def verify_refined_profile(
    plane: list[tuple[float, float]],
    kappa: list[float],
    v_target: list[float],
    ggv: GGVModel,
    params: L3Params,
) -> str | None:
    """Re-verify a refined profile against the CURRENT plant's stability barrier; reason or None.

    The cache-revalidation counterpart of the build-time barrier: every point (refined or not)
    must respect ``barrier_ggv`` — the barrier dominates the safe envelope, so un-refined points
    pass trivially, while a tampered durable JSON (or one built from a since-deflated fit) fails
    loudly and falls through to an honest rebuild.
    """
    if len(v_target) != len(plane) or len(kappa) != len(plane):
        return (
            f"refined profile arrays length mismatch: plane={len(plane)}, "
            f"kappa={len(kappa)}, v={len(v_target)}"
        )
    barrier = barrier_ggv(ggv, params.max_rel_std)
    for i, v in enumerate(v_target):
        limit = barrier.ay_max(v)
        if limit <= 0.0:
            return f"barrier envelope non-positive at point {i} (v={v:.1f} m/s)"
        ratio = (v * v * abs(kappa[i])) / limit
        if ratio > 1.0 + _BARRIER_TOL:
            return (
                f"refined profile exceeds the stability barrier at point {i}: "
                f"v={v:.2f} m/s -> {ratio:.4f}x (mean - {Z_STABILITY_FLOOR}*std)"
            )
    return None
