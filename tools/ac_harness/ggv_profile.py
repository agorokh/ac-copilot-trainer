"""GGV friction-circle minimum-time speed profiler (EPIC #154 Part G / #244 frontier controller).

Offline, pure-Python (stdlib ``math`` only), deterministic, CI-testable. Builds a speed-dependent
grip model (GGV) from human telemetry and computes a forward-backward quasi-steady-state
``v_target`` profile over a racing line - replacing the consumer-grade fixed-``brake_g`` backward
pass that merely replays *relaxed* human speeds. This is the engine of the frontier controller:
it exploits the friction circle + the aero rise of braking grip the old controller threw away.

Grounded in the 2026-06-19 15-agent deep-research synthesis + adversarial red-team and the empirical
plant-ID from ``human_laps.csv``. Red-team guardrails honored here:

* **GGV de-contamination** - ``ay_max(v)`` is fitted as ``mu*g + k_aero*v^2`` (downforce is
  quadratic) to ONLY low/mid-speed bins with real cornering data; the high-speed lateral bins are
  straight-line-braking artifacts (nobody corners at 220 km/h in relaxed laps) and are NOT trusted -
  the aero term is extrapolated upward instead. Each bin carries provenance (sample count + lateral
  spread) so a bin without cornering coverage never sets ``ay_max``.
* **95th-percentile, not peak** - robust to single-frame mmap glitches; self-play grows from here.
* **Curvature** - arc-length-aware Menger curvature on smoothed coordinates (no phantom apexes from
  the non-equispaced 1754-point line).
* **Friction-ellipse exponent fitted** from the ``(accg_lat, accg_lon)`` hull edge, not guessed.

The online controller never imports the fitter: it consumes the baked ``v_target`` list. Everything
here is plain arithmetic so CI verifies it with synthetic lines + synthetic telemetry, no game.
"""

from __future__ import annotations

import csv
import math
import struct
from dataclasses import dataclass, field, replace
from pathlib import Path

from tools.ac_harness.ai_line import StanleySteering, _horizontal

G = 9.81


# ---------------------------------------------------------------------------
# GGV grip model (speed-dependent friction circle), fitted from telemetry.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GGVModel:
    """Speed-dependent grip limits (in g) + the friction-ellipse exponent.

    ``ay_max(v)`` lateral and ``ax_brake_max(v)`` braking are the load-bearing curves;
    ``ax_drive_max`` is the (weakly identified) accel cap. ``ellipse_n`` couples them:
    available longitudinal g at lateral usage ``ay`` is ``ax_max * (1 - (ay/ay_max)^n)^(1/n)``.
    """

    mu_lat_g: float  # ay_max(v) = mu_lat_g + k_aero_lat * v_ms^2
    k_aero_lat: float
    brake_b0_g: float  # ax_brake_max(v) = brake_b0_g + brake_b1 * v_ms
    brake_b1: float
    drive_b0_g: float  # ax_drive_max(v) = max(drive_min_g, drive_b0_g + drive_b1 * v_ms)
    drive_b1: float
    drive_min_g: float
    ellipse_n: float
    ay_cap_g: float = 1.8  # hard sanity cap on extrapolated lateral grip
    ax_brake_cap_g: float = 3.4
    provenance: dict = field(default_factory=dict)

    def ay_max(self, v_ms: float) -> float:
        return min(self.ay_cap_g, self.mu_lat_g + self.k_aero_lat * v_ms * v_ms) * G

    def ax_brake_max(self, v_ms: float) -> float:
        return min(self.ax_brake_cap_g, max(0.5, self.brake_b0_g + self.brake_b1 * v_ms)) * G

    def ax_drive_max(self, v_ms: float) -> float:
        return max(self.drive_min_g, self.drive_b0_g + self.drive_b1 * v_ms) * G

    def ax_brake_avail(self, ay_used: float, v_ms: float) -> float:
        """Braking g still available given lateral g already used (friction ellipse)."""
        aymax = self.ay_max(v_ms)
        if aymax <= 1e-6:
            return self.ax_brake_max(v_ms)
        frac = min(1.0, abs(ay_used) / aymax)
        return self.ax_brake_max(v_ms) * (max(0.0, 1.0 - frac**self.ellipse_n)) ** (
            1.0 / self.ellipse_n
        )

    def ax_drive_avail(self, ay_used: float, v_ms: float) -> float:
        aymax = self.ay_max(v_ms)
        if aymax <= 1e-6:
            return self.ax_drive_max(v_ms)
        frac = min(1.0, abs(ay_used) / aymax)
        return self.ax_drive_max(v_ms) * (max(0.0, 1.0 - frac**self.ellipse_n)) ** (
            1.0 / self.ellipse_n
        )


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def _linfit(xs: list[float], ys: list[float], ws: list[float] | None = None) -> tuple[float, float]:
    """Weighted least squares y = a + b*x -> (a, b)."""
    if ws is None:
        ws = [1.0] * len(xs)
    sw = sum(ws)
    if sw <= 0 or len(xs) < 2:
        return (ys[0] if ys else 0.0, 0.0)
    mx = sum(w * x for w, x in zip(ws, xs, strict=False)) / sw
    my = sum(w * y for w, y in zip(ws, ys, strict=False)) / sw
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs, strict=False))
    sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys, strict=False))
    b = sxy / sxx if sxx > 1e-12 else 0.0
    return (my - b * mx, b)


def ggv_from_telemetry(
    rows: list[dict],
    *,
    bin_kmh: float = 10.0,
    pct: float = 0.95,
    min_corner_lat_g: float = 0.9,
    min_samples: int = 40,
) -> GGVModel:
    """Fit a :class:`GGVModel` from telemetry rows (dicts w/ speed_kmh, accg_lat, accg_lon).

    Per speed bin: 95th-pct |lat|, braking (-lon) and accel (+lon) g, with sample count and lateral
    spread. ``ay_max(v)=mu*g+k*v^2`` is fitted ONLY on bins with real cornering coverage (lat spread
    >= ``min_lat_spread_g`` and >= ``min_samples``); braking/accel fitted linearly. Ellipse exponent
    from the radial hull of ``(lat, lon)``.
    """
    lat_b: dict[int, list[float]] = {}
    brk_b: dict[int, list[float]] = {}
    acc_b: dict[int, list[float]] = {}
    hull: list[tuple[float, float]] = []  # (|lat|, |lon|) in g
    for r in rows:
        try:
            v = float(r["speed_kmh"])
            al = abs(float(r["accg_lat"]))
            ao = float(r["accg_lon"])
        except (KeyError, TypeError, ValueError):
            continue
        b = int(v // bin_kmh) * int(bin_kmh)
        lat_b.setdefault(b, []).append(al)
        (brk_b if ao < 0 else acc_b).setdefault(b, []).append(abs(ao))
        if al > 0.2 or abs(ao) > 0.2:
            hull.append((al, abs(ao)))

    # Lateral grip: ONLY bins where the car DEMONSTRABLY cornered hard count (p95 lateral high).
    # The high-speed bins are straight-line-braking artifacts (low lateral) and must NOT pull the
    # fit down (red-team contamination guard). There is no high-speed cornering data on this track,
    # so we do NOT claim an aero lateral term (k_aero_lat=0) - that would be extrapolating into an
    # empty corner of the envelope. mu_lat = demonstrated peak mechanical lateral grip.
    cov: dict[int, dict] = {}
    corner_p95: list[float] = []
    for b, vals in sorted(lat_b.items()):
        spread = (max(vals) - min(vals)) if vals else 0.0
        p95 = _pct(vals, pct)
        cov[b] = {
            "n": len(vals),
            "lat_spread_g": round(spread, 3),
            "lat_p95_g": round(p95, 3),
            "cornered": bool(len(vals) >= min_samples and p95 >= min_corner_lat_g and b >= 30),
        }
        if cov[b]["cornered"]:
            corner_p95.append(p95)
    mu_lat = max(corner_p95) if corner_p95 else 1.2
    k_aero = 0.0
    n_corner_bins = len(corner_p95)

    # braking fit (linear in v) on bins with samples
    xs_b, ys_b, ws_b = [], [], []
    for b, vals in sorted(brk_b.items()):
        if len(vals) >= min_samples and b >= 30:
            xs_b.append((b + bin_kmh / 2) / 3.6)
            ys_b.append(_pct(vals, pct))
            ws_b.append(float(len(vals)))
    brake_b0, brake_b1 = _linfit(xs_b, ys_b, ws_b) if len(xs_b) >= 2 else (1.0, 0.0)

    # accel fit (linear) - weakly identified (human under-drove), kept conservative
    xs_a, ys_a, ws_a = [], [], []
    for b, vals in sorted(acc_b.items()):
        if len(vals) >= min_samples and b >= 30:
            xs_a.append((b + bin_kmh / 2) / 3.6)
            ys_a.append(_pct(vals, pct))
            ws_a.append(float(len(vals)))
    drive_b0, drive_b1 = _linfit(xs_a, ys_a, ws_a) if len(xs_a) >= 2 else (0.8, 0.0)

    # ellipse exponent from radial hull edge: near the boundary (lat/aymax)^n + (lon/axmax)^n ~ 1.
    n_fit = _fit_ellipse_n(hull, mu_lat, k_aero, brake_b0, brake_b1)

    prov = {
        "bins": cov,
        "lat_corner_bins": n_corner_bins,
        "lat_model": f"ay_max(v)={mu_lat:.3f}+{k_aero:.5f}*v_ms^2 g [mech peak; no aero-lat]",
        "brake_model": f"ax_brake(v)={brake_b0:.3f}+{brake_b1:.5f}*v_ms (g)",
        "accel_model": f"ax_drive(v)={drive_b0:.3f}+{drive_b1:.5f}*v_ms (g)",
        "ellipse_n": round(n_fit, 3),
    }
    return GGVModel(
        mu_lat_g=mu_lat,
        k_aero_lat=max(0.0, k_aero),
        brake_b0_g=brake_b0,
        brake_b1=max(0.0, brake_b1),
        drive_b0_g=drive_b0,
        drive_b1=drive_b1,
        drive_min_g=0.35,
        ellipse_n=n_fit,
        provenance=prov,
    )


def _fit_ellipse_n(hull: list[tuple[float, float]], mu_lat, k_aero, brake_b0, brake_b1) -> float:
    """Pick n in [1,2] minimizing the hull-edge residual of (lat/aymax)^n + (lon/axmax)^n = 1."""
    if len(hull) < 20:
        return 1.5
    # use a coarse speed-independent envelope for the fit (peak mechanical), robust enough for n
    aymax = max(0.8, mu_lat + k_aero * (20.0**2))  # ~70 km/h
    axmax = max(0.8, brake_b0 + brake_b1 * 25.0)
    # keep only near-boundary points (top decile radial in normalized space)
    norm = [(lat / aymax, lon / axmax) for lat, lon in hull]
    rad = sorted(norm, key=lambda p: -(p[0] ** 2 + p[1] ** 2))[: max(20, len(norm) // 10)]
    best_n, best_err = 1.5, 1e18
    n = 1.0
    while n <= 2.01:
        err = sum((x**n + y**n - 1.0) ** 2 for x, y in rad)
        if err < best_err:
            best_err, best_n = err, n
        n += 0.05
    return best_n


# ---------------------------------------------------------------------------
# Curvature (arc-length-aware Menger, smoothed) + forward-backward profiler.
# ---------------------------------------------------------------------------
def _smooth_cyclic(pts: list[tuple[float, float]], win: int) -> list[tuple[float, float]]:
    n = len(pts)
    if win <= 0 or n < 3:
        return list(pts)
    out = []
    for i in range(n):
        sx = sz = 0.0
        for k in range(-win, win + 1):
            p = pts[(i + k) % n]
            sx += p[0]
            sz += p[1]
        m = 2 * win + 1
        out.append((sx / m, sz / m))
    return out


def menger_curvature(a, b, c) -> float:
    """Menger curvature 1/R of the circumcircle through 3 planar points (arc-length-aware)."""
    ab = math.hypot(b[0] - a[0], b[1] - a[1])
    bc = math.hypot(c[0] - b[0], c[1] - b[1])
    ca = math.hypot(a[0] - c[0], a[1] - c[1])
    if ab < 1e-9 or bc < 1e-9 or ca < 1e-9:
        return 0.0
    area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))  # 2*area
    return 2.0 * area2 / (ab * bc * ca)


def curvature_profile(
    plane: list[tuple[float, float]], *, smooth_win: int = 3, span: int = 3
) -> list[float]:
    """Per-point curvature (1/m) of a cyclic line: smooth coords, then Menger over +/-span."""
    p = _smooth_cyclic(plane, smooth_win)
    n = len(p)
    return [menger_curvature(p[(i - span) % n], p[i], p[(i + span) % n]) for i in range(n)]


def load_track_widths(path: str | Path) -> tuple[list[float], list[float]]:
    """Read per-point track-edge distances (sideLeft, sideRight, metres) from ``fast_lane.ai``.

    The AiPointExtra block (72-byte stride) carries the corridor: ``sideLeft@20``, ``sideRight@24``
    after ``speed@0/gas@4/brake@8/obsLatG@12/radius@16``. This is the on-file track width used to
    bound the min-curvature optimizer so the line stays on track (AC-valid) by construction.
    """
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ValueError(f"{path} is too small to be a fast_lane.ai file")
    _ver, count, _lap, _samp = struct.unpack_from("<4i", data, 0)
    if count <= 0:
        raise ValueError(f"{path} has invalid AI point count: {count}")
    es = 16 + count * 20 + 4
    needed = es + count * 72
    if len(data) < needed:
        raise ValueError(
            f"{path} is truncated: expected at least {needed} bytes for {count} AI extras, "
            f"got {len(data)}"
        )
    left: list[float] = []
    right: list[float] = []
    for i in range(count):
        sl, sr = struct.unpack_from("<2f", data, es + i * 72 + 20)
        left.append(sl)
        right.append(sr)
    return left, right


def _unit_normals(plane: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Left-hand unit normal at each point (perpendicular to the local tangent, cyclic)."""
    n = len(plane)
    out = []
    for i in range(n):
        a = plane[(i - 1) % n]
        b = plane[(i + 1) % n]
        tx, tz = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(tx, tz) or 1.0
        out.append((-tz / ln, tx / ln))
    return out


def min_curvature_line(
    plane: list[tuple[float, float]],
    side_left: list[float],
    side_right: list[float],
    *,
    margin_m: float = 1.2,
    iters: int = 2000,
    damp: float = 0.5,
) -> tuple[list[tuple[float, float]], list[float]]:
    """Minimum-curvature racing line within the track corridor (TUMFTM-style, pure-Python).

    Moves each point along its lateral normal by ``alpha_i`` bounded to ``[-(sideRight-margin),
    +(sideLeft-margin)]`` (margin keeps the car half-width off the edge -> AC-valid). Minimizes the
    PATH curvature ``sum (kappa_ref_i + alpha''_i)^2`` where ``kappa_ref`` is the base-line signed
    curvature and ``alpha'' ~= (a_{i-1} - 2 a_i + a_{i+1}) / ds^2`` is the curvature the offset adds
    (small-offset linearization). The base curvature drives the offset to flatten corners (bow
    out → larger radius → higher apex speed) up to the corridor. Damped in-place Gauss-Seidel keeps
    the stiff 4th-order operator stable. Returns (optimized plane points, alpha offsets).
    """
    n = len(plane)
    if n < 3:
        raise ValueError("min_curvature_line requires at least 3 cyclic points")
    if len(side_left) != n or len(side_right) != n:
        raise ValueError(
            "corridor width arrays must match plane length: "
            f"plane={n}, side_left={len(side_left)}, side_right={len(side_right)}"
        )
    if margin_m < 0:
        raise ValueError("margin_m must be non-negative")
    nrm = _unit_normals(plane)
    kref = signed_curvature_profile(plane, smooth_win=1, span=2)
    ds = (sum(seg_lengths(plane)) / n) or 1.0
    ds2 = ds * ds
    lo = [min(0.0, -(side_right[i] - margin_m)) for i in range(n)]
    hi = [max(0.0, side_left[i] - margin_m) for i in range(n)]
    alpha = [0.0] * n

    def resid(k: int) -> float:
        return kref[k] + (alpha[(k - 1) % n] - 2 * alpha[k] + alpha[(k + 1) % n]) / ds2

    for _ in range(iters):
        for i in range(n):
            res2 = resid((i - 1) % n) - 2 * resid(i) + resid((i + 1) % n)
            a = alpha[i] - damp * ds2 * res2 / 6.0
            alpha[i] = lo[i] if a < lo[i] else hi[i] if a > hi[i] else a
    return [
        (plane[i][0] + alpha[i] * nrm[i][0], plane[i][1] + alpha[i] * nrm[i][1]) for i in range(n)
    ], alpha


def optimize_fast_line(
    fast_line: list[tuple[float, float, float]],
    width_path: str | Path,
    *,
    margin_m: float = 1.2,
    iters: int = 1200,
) -> list[tuple[float, float, float]]:
    """Min-curvature-optimized (x, y, z) line within the track corridor (y carried through)."""
    plane = [(p[0], p[2]) for p in fast_line]
    sl, sr = load_track_widths(width_path)
    opt, _alpha = min_curvature_line(plane, sl, sr, margin_m=margin_m, iters=iters)
    return [(opt[i][0], fast_line[i][1], opt[i][1]) for i in range(len(fast_line))]


def signed_curvature_profile(
    plane: list[tuple[float, float]], *, smooth_win: int = 3, span: int = 3
) -> list[float]:
    """Per-point SIGNED curvature (1/m) of a cyclic line: magnitude = Menger, sign = turn direction.

    Sign is the planar cross product of consecutive chords (``> 0`` one way, ``< 0`` the other). The
    absolute mapping to "left/right" depends on the (x, z) handedness and is reconciled live by the
    controller's ``ff_sign`` flag; what matters here is that the sign is consistent along the line.
    """
    p = _smooth_cyclic(plane, smooth_win)
    n = len(p)
    out = []
    for i in range(n):
        a = p[(i - span) % n]
        b = p[i]
        c = p[(i + span) % n]
        mag = menger_curvature(a, b, c)
        v1x, v1z = b[0] - a[0], b[1] - a[1]
        v2x, v2z = c[0] - b[0], c[1] - b[1]
        cross = v1x * v2z - v1z * v2x
        out.append(mag if cross >= 0 else -mag)
    return out


def fit_steer_feedforward(
    rows: list[dict], *, min_lat_g: float = 0.3, min_kmh: float = 15.0
) -> tuple[float, float, float, int]:
    """Calibrate a bicycle-model steer feedforward from human telemetry.

    Fits the normalized steer command ``steer ≈ c1*kappa + c2*(v^2*kappa)`` where the human's own
    instantaneous curvature ``kappa = a_y / v^2`` and ``a_y = accg_lat*g`` (signed). ``c1`` is the
    geometric (Ackermann) term ``L/steer_scale``; ``c2`` the understeer term ``K_ug/steer_scale``
    (both absorb the unknown rad-per-unit-steer of the actuator). Returns ``(c1, c2, rms_frac, n)``;
    ``rms_frac`` is the residual RMS as a fraction of the steer RMS (lower = better calibrated).
    """
    x11 = x12 = x22 = y1 = y2 = 0.0
    samples: list[tuple[float, float, float]] = []
    for r in rows:
        try:
            v = float(r["speed_kmh"]) / 3.6
            ay = float(r["accg_lat"]) * G
            st = float(r["steer"])
        except (KeyError, TypeError, ValueError):
            continue
        if v < min_kmh / 3.6 or abs(float(r["accg_lat"])) < min_lat_g:
            continue
        kappa = ay / (v * v)
        x1, x2 = kappa, ay  # x2 == v^2 * kappa
        x11 += x1 * x1
        x12 += x1 * x2
        x22 += x2 * x2
        y1 += x1 * st
        y2 += x2 * st
        samples.append((x1, x2, st))
    n = len(samples)
    if n < 50:
        return (0.0, 0.0, 1.0, n)
    det = x11 * x22 - x12 * x12
    if abs(det) < 1e-12:
        return (0.0, 0.0, 1.0, n)
    c1 = (y1 * x22 - y2 * x12) / det
    c2 = (x11 * y2 - x12 * y1) / det
    sse = sum((c1 * a + c2 * b - s) ** 2 for a, b, s in samples)
    sst = sum(s * s for _, _, s in samples)
    rms_frac = (sse / sst) ** 0.5 if sst > 0 else 1.0
    return (c1, c2, rms_frac, n)


def seg_lengths(plane: list[tuple[float, float]]) -> list[float]:
    n = len(plane)
    return [
        math.hypot(plane[(i + 1) % n][0] - plane[i][0], plane[(i + 1) % n][1] - plane[i][1])
        for i in range(n)
    ]


def forward_backward_profile(
    kappa: list[float],
    seg: list[float],
    ggv: GGVModel,
    *,
    v_top_ms: float = 64.0,
    v_floor_ms: float = 8.0,
    passes: int = 4,
) -> tuple[list[float], list[float]]:
    """Quasi-steady-state minimum-time speed profile over a cyclic line.

    1. apex speed from lateral grip (fixed-point, grip depends on v);
    2. backward pass: braking limited by the friction ellipse with speed-dependent grip;
    3. forward pass: accel limited by ellipse + traction/power cap.
    Returns (v_target_ms per point, ax_ff per point [m/s^2, +accel/-decel]).
    """
    n = len(kappa)
    # 1) apex (fixed-point on v because ay_max depends on v)
    v = [v_top_ms] * n
    for i in range(n):
        k = kappa[i]
        if k > 1e-6:
            vi = v_top_ms
            for _ in range(8):
                vi = min(v_top_ms, math.sqrt(ggv.ay_max(vi) / k))
            v[i] = max(v_floor_ms, vi)
    # 2) backward (braking) - ellipse uses the lateral g implied by apex usage
    for _ in range(passes):
        for j in range(n):
            i = (n - 1 - j) % n
            nx = (i + 1) % n
            ds = seg[i]
            if ds <= 1e-6:  # coincident points must share speed, else propagation chain breaks
                if v[nx] < v[i]:
                    v[i] = max(v_floor_ms, v[nx])
                continue
            ay_used = v[i] * v[i] * kappa[i]
            ax = ggv.ax_brake_avail(ay_used, v[i])
            cap = math.sqrt(v[nx] * v[nx] + 2.0 * ax * ds)
            if cap < v[i]:
                v[i] = max(v_floor_ms, cap)
    # 3) forward (accel)
    for _ in range(passes):
        for i in range(n):
            pv = (i - 1) % n
            ds = seg[pv]
            if ds <= 1e-6:  # coincident points must share speed
                if v[pv] < v[i]:
                    v[i] = max(v_floor_ms, v[pv])
                continue
            ay_used = v[pv] * v[pv] * kappa[pv]
            ax = ggv.ax_drive_avail(ay_used, v[pv])
            cap = math.sqrt(v[pv] * v[pv] + 2.0 * ax * ds)
            if cap < v[i]:
                v[i] = max(v_floor_ms, cap)
    v = [min(v_top_ms, x) for x in v]
    # ax feedforward from the profile (central, cyclic): a = v*dv/ds
    ax_ff = []
    for i in range(n):
        nx = (i + 1) % n
        ds = seg[i]
        ax_ff.append(((v[nx] * v[nx] - v[i] * v[i]) / (2.0 * ds)) if ds > 1e-6 else 0.0)
    return v, ax_ff


def _read_csv(path: str | Path) -> list[dict]:
    with Path(path).open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def ggv_speed_profile_from_model(
    fast_line: list[tuple[float, float, float]],
    ggv: GGVModel,
    *,
    v_top_kmh: float = 232.0,
    smooth_win: int = 3,
    span: int = 3,
) -> tuple[list[float], dict]:
    """Compute the forward-backward QSS profile from a GGVModel directly (no telemetry CSV).

    Use this when the GGV is known (e.g. a hand-built / scaled model) rather than fitting from raw
    telemetry. Returns (v_target_mps per fast_line point, summary dict).
    """
    plane = [(p[0], p[2]) for p in fast_line]
    seg = seg_lengths(plane)
    kappa = curvature_profile(plane, smooth_win=smooth_win, span=span)
    v, _ax = forward_backward_profile(kappa, seg, ggv, v_top_ms=v_top_kmh / 3.6)
    total = sum(seg)
    laptime = sum(seg[i] / max(0.5, 0.5 * (v[i] + v[(i + 1) % len(v)])) for i in range(len(v)))
    summ = {
        "points": len(v),
        "length_m": round(total, 1),
        "qss_laptime_s": round(laptime, 2),
        "qss_avg_kmh": round(total / laptime * 3.6, 1),
        "vmax_kmh": round(max(v) * 3.6, 1),
        "vmin_kmh": round(min(v) * 3.6, 1),
        "max_kappa": round(max(kappa), 4),
    }
    return v, summ


def build_ggv_speed_profile(
    fast_line: list[tuple[float, float, float]],
    human_csv: str | Path,
    *,
    v_top_kmh: float = 232.0,
    smooth_win: int = 3,
    span: int = 3,
    accel_peak_g: float | None = None,
    lat_grip_g: float | None = None,
    lat_aero_k: float | None = None,
) -> tuple[list[float], GGVModel, dict]:
    """End-to-end offline build: fit GGV from telemetry, compute the QSS profile on ``fast_line``.

    Returns (v_target_mps aligned to fast_line points, GGVModel, summary dict). The v_target list is
    drop-in for :class:`RacingDriver` (one m/s target per line point).

    ``accel_peak_g`` overrides the (under-driven, human-fit) drive accel with a traction-shaped
    curve peaking at ``accel_peak_g`` low-speed and fading with speed. The human barely used the gas
    (0.24-0.97 g), so the fitted accel is far below the car's capability; an aggressive accel target
    is made TC-off-safe live by ``slip_limited_controls``. Braking/lateral are left as fitted.
    """
    ggv = ggv_from_telemetry(_read_csv(human_csv))
    if accel_peak_g is not None:
        # traction-shaped accel: peak low-speed, ~0.4 g by 60 m/s (power/drag fade)
        ggv = replace(ggv, drive_b0_g=accel_peak_g, drive_b1=-(accel_peak_g - 0.4) / 60.0)
    if lat_grip_g is not None:
        # grip self-play: the relaxed human under-corners (~1.2 g), a real GT3 R does ~1.5 g. Push
        # the lateral envelope up to raise apex speeds; kept honest live by validity.
        ggv = replace(ggv, mu_lat_g=lat_grip_g, ay_cap_g=max(ggv.ay_cap_g, lat_grip_g + 0.1))
    if lat_aero_k is not None:
        # speed-dependent aero lateral grip: a real GT3 R gains downforce grip with speed, so fast
        # corners hold > mechanical 1.5 g. ay_max(v) = mu + k*v^2. Lifts the aero ceiling cap too.
        ggv = replace(ggv, k_aero_lat=lat_aero_k, ay_cap_g=max(ggv.ay_cap_g, 3.0))
    v, summ = ggv_speed_profile_from_model(
        fast_line, ggv, v_top_kmh=v_top_kmh, smooth_win=smooth_win, span=span
    )
    summ["ggv"] = ggv.provenance
    return v, ggv, summ


class CurvatureFeedforwardSteering:
    """Curvature-feedforward + Stanley-feedback lateral controller (Stage 3).

    ``delta = ff_sign*(c1*kappa + c2*v^2*kappa)``  (feedforward from the LINE's signed curvature,
    with ``v^2*kappa`` a_y-capped) ``+ fb_weight * Stanley(cross-track + heading)`` (feedback).

    Bare Stanley only corrects error; at racing corner speeds it saturates and the car runs wide.
    The feedforward supplies the steady-state wheel angle the curve needs (calibrated from human
    telemetry via :func:`fit_steer_feedforward`), so Stanley only trims the residual — the car can
    carry the GGV profile's corner speeds. ``ff_sign`` reconciles the line curvature sign convention
    with the actuator's ``steer>0=right`` live (flip if the car veers off on the first corner).
    """

    def __init__(
        self,
        line: list[tuple[float, float, float]],
        *,
        c1: float,
        c2: float,
        ff_sign: float = 1.0,
        ay_cap_mps2: float = 14.0,
        preview_m: float = 6.0,
        fb_weight: float = 0.6,
        smooth_win: int = 3,
        span: int = 3,
        **stanley_kwargs,
    ) -> None:
        self._plane = [(p[0], p[2]) for p in line]
        self._kappa = signed_curvature_profile(self._plane, smooth_win=smooth_win, span=span)
        self._seg = seg_lengths(self._plane)
        self.n = len(self._plane)
        self.c1 = c1
        self.c2 = c2
        self.ff_sign = ff_sign
        self.ay_cap = ay_cap_mps2
        self.preview_m = preview_m
        self.fb_weight = fb_weight
        self._stanley = StanleySteering(line, **stanley_kwargs)

    def _nearest(self, car: tuple[float, float]) -> int:
        best_i, best = 0, float("inf")
        for i, p in enumerate(self._plane):
            d = (p[0] - car[0]) ** 2 + (p[1] - car[1]) ** 2
            if d < best:
                best, best_i = d, i
        return best_i

    def _advance(self, idx: int, dist_m: float) -> int:
        rem, i = dist_m, idx
        for _ in range(self.n):
            s = self._seg[i]
            if s >= rem:
                return (i + 1) % self.n
            rem -= s
            i = (i + 1) % self.n
        return idx

    def steer(self, position_xyz, look_dir_xyz, speed_kmh: float) -> float:
        """Return steering in ``[-1, 1]`` (``>0`` = right) from pose + speed."""
        car = _horizontal(position_xyz)
        look = self._advance(self._nearest(car), self.preview_m)
        k = self._kappa[look]
        v = max(speed_kmh, 0.0) / 3.6
        ay = min(v * v * abs(k), self.ay_cap)  # cap a_y (grip-bounded understeer term)
        ff = self.ff_sign * (self.c1 * k + self.c2 * (ay if k >= 0 else -ay))
        fb = self._stanley.steer(position_xyz, look_dir_xyz, speed_kmh)
        out = ff + self.fb_weight * fb
        return -1.0 if out < -1.0 else 1.0 if out > 1.0 else out
