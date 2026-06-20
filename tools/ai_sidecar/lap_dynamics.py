"""Per-corner driving signatures from a lap-archive trace (stdlib-only).

Turns the raw ``trace`` of a lap archive (``spline, speed, throttle, brake, steer, gear, position``)
into derived dynamics channels and a list of :class:`CornerSignature` objects — the observable,
falsifiable per-corner facts the coaching/attribution layer reasons over ("min speed 92 km/h, brake
point at spline 0.31, trail-braked to apex, threw it back to power 12 m after apex").

Honest scope: the saved archive trace has **no per-wheel slip, tyre temps, or measured g-forces**.
We derive longitudinal g from dv/dt and lateral g from ``v^2 * curvature`` of the driven path — good
for technique + grip-ceiling signals, but precise setup attribution (brake-bias lockup balance, TC
wheelspin) needs the live physics channels (see ``corner_attribution`` Tier-A/Tier-B split).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

G = 9.81


# --- channel derivation -----------------------------------------------------
@dataclass
class LapTrace:
    """Derived per-sample channels for one lap (all lists aligned, length N)."""

    spline: list[float]
    t_s: list[float]
    v_ms: list[float]  # speed, m/s
    brake: list[float]
    throttle: list[float]
    steer: list[float]
    gear: list[float]
    x: list[float]
    z: list[float]
    lap_ms: float | None = None
    car_id: str | None = None
    track_id: str | None = None
    # optional Tier-B live channels (per sample, 4 wheels [FL, FR, RL, RR]); None when not persisted
    wheel_omega: list[list[float]] | None = None  # wheelAngularSpeed rad/s
    wheel_slip: list[list[float]] | None = None  # AC wheelSlip (Pacejka NDslip; secondary)
    # lazily derived
    _kappa: list[float] | None = field(default=None, repr=False)
    _lat_g: list[float] | None = field(default=None, repr=False)
    _long_g: list[float] | None = field(default=None, repr=False)

    def __len__(self) -> int:
        return len(self.spline)

    @property
    def v_kmh(self) -> list[float]:
        return [v * 3.6 for v in self.v_ms]

    @property
    def kappa(self) -> list[float]:
        if self._kappa is None:
            self._kappa = _curvature([(self.x[i], self.z[i]) for i in range(len(self))], span=2)
        return self._kappa

    @property
    def lat_g(self) -> list[float]:
        """Lateral g from v^2 * curvature (path-based; sign-less magnitude)."""
        if self._lat_g is None:
            self._lat_g = [self.v_ms[i] ** 2 * self.kappa[i] / G for i in range(len(self))]
        return self._lat_g

    @property
    def long_g(self) -> list[float]:
        """Longitudinal g from dv/dt (negative = braking, positive = accel)."""
        if self._long_g is None:
            self._long_g = _derivative(self.v_ms, self.t_s, scale=1.0 / G)
        return self._long_g

    @property
    def has_wheel_data(self) -> bool:
        """True when per-wheel angular speed (the Tier-B channel) is persisted in this lap."""
        return self.wheel_omega is not None


def _idx(fields: list[str], *names: str) -> int | None:
    for n in names:
        if n in fields:
            return fields.index(n)
    return None


_WHEELS = ("fl", "fr", "rl", "rr")


def _wheel_cols(fields: list[str], samples: list, base: str, n: int) -> list[list[float]] | None:
    """Read a 4-wheel channel (``<base>_fl/fr/rl/rr``) into N rows of [FL, FR, RL, RR], or None."""
    idxs = [_idx(fields, f"{base}_{w}") for w in _WHEELS]
    if any(i is None for i in idxs):
        return None
    out: list[list[float]] = []
    for row in samples:
        vals = []
        for i in idxs:
            try:
                vals.append(float(row[i]))
            except (TypeError, ValueError, IndexError):
                vals.append(0.0)
        out.append(vals)
    return out if len(out) == n else out


def lap_trace_from_archive(archive: dict[str, Any]) -> LapTrace:
    """Build a :class:`LapTrace` from a lap-archive dict.

    Tolerant of missing optional channels (filled with zeros). Requires position + speed to derive
    dynamics; raises ValueError if the trace is empty or lacks position.
    """
    trace = archive.get("trace") if isinstance(archive, dict) else None
    if not isinstance(trace, dict):
        raise ValueError("archive has no trace object")
    fields = trace.get("fields")
    samples = trace.get("samples")
    if not isinstance(fields, list) or not isinstance(samples, list) or not samples:
        raise ValueError("trace.fields/samples missing or empty")

    i_sp = _idx(fields, "spline")
    i_v = _idx(fields, "speed", "speed_kmh")
    i_br = _idx(fields, "brake")
    i_th = _idx(fields, "throttle", "gas")
    i_st = _idx(fields, "steer", "steering")
    i_g = _idx(fields, "gear")
    i_t = _idx(fields, "eMs", "elapsed_ms", "time_ms")
    i_x = _idx(fields, "px", "position_x_m", "x")
    i_z = _idx(fields, "pz", "position_z_m", "z")
    if i_x is None or i_z is None:
        raise ValueError("trace lacks position channels (px/pz)")
    if i_v is None:
        raise ValueError("trace lacks a speed channel")

    n = len(samples)

    def col(i: int | None, default: float = 0.0) -> list[float]:
        if i is None:
            return [default] * n
        out = []
        for row in samples:
            try:
                out.append(float(row[i]))
            except (TypeError, ValueError, IndexError):
                out.append(default)
        return out

    v_kmh = col(i_v)
    x_col = col(i_x)
    z_col = col(i_z)
    spline = col(i_sp)
    # spline drives corner windows + time-loss localization; if absent (or flat) derive it from
    # cumulative distance rather than silently zero-filling (which would collapse every window).
    if i_sp is None or (max(spline) - min(spline) <= 1e-9):
        spline = _spline_from_positions(x_col, z_col)
    t_ms = col(i_t)
    # time: prefer recorded eMs; else integrate from distance/speed; else uniform index
    if i_t is not None and any(t_ms):
        t_s = [t / 1000.0 for t in t_ms]
    else:
        t_s = _time_from_positions(x_col, z_col, [v / 3.6 for v in v_kmh])

    # optional Tier-B per-wheel channels (FL, FR, RL, RR); present only when persisted (#266)
    wheel_omega = _wheel_cols(fields, samples, "wheelAngularSpeed", n)
    wheel_slip = _wheel_cols(fields, samples, "wheelSlip", n)

    car = archive.get("car") if isinstance(archive.get("car"), dict) else {}
    track = archive.get("track") if isinstance(archive.get("track"), dict) else {}
    lap = archive.get("lap") if isinstance(archive.get("lap"), dict) else {}
    return LapTrace(
        spline=spline,
        t_s=t_s,
        v_ms=[v / 3.6 for v in v_kmh],
        brake=col(i_br),
        throttle=col(i_th),
        steer=col(i_st),
        gear=col(i_g),
        wheel_omega=wheel_omega,
        wheel_slip=wheel_slip,
        x=x_col,
        z=z_col,
        lap_ms=_finite(lap.get("lap_ms")),
        car_id=car.get("id") if isinstance(car, dict) else None,
        track_id=track.get("id") if isinstance(track, dict) else None,
    )


# --- corners ----------------------------------------------------------------
@dataclass(frozen=True)
class CornerSignature:
    """Observable facts about one corner of a lap (all derived, falsifiable)."""

    index: int
    entry_i: int
    apex_i: int
    exit_i: int
    apex_spline: float
    min_speed_kmh: float
    entry_speed_kmh: float
    exit_speed_kmh: float
    peak_lat_g: float
    peak_brake_g: float  # peak |long_g| while braking (magnitude)
    peak_accel_g: float
    brake_point_spline: float | None  # where braking began before the apex
    brake_to_apex_m: float | None  # braking distance to apex
    throttle_on_spline: float | None  # where throttle re-applied after apex
    apex_to_throttle_m: float | None
    trail_brake_frac: float  # fraction of entry samples with brake & steer both active
    max_abs_steer: float
    direction: str  # 'left' | 'right' | 'straightish'

    def describe(self) -> str:
        bp = "n/a" if self.brake_point_spline is None else f"{self.brake_point_spline:.3f}"
        return (
            f"C{self.index} apex@{self.apex_spline:.3f} vmin={self.min_speed_kmh:.0f}km/h "
            f"latG={self.peak_lat_g:.2f} brakeG={self.peak_brake_g:.2f} "
            f"brake@{bp} trail={self.trail_brake_frac:.0%}"
        )


def segment_corners(
    lap: LapTrace,
    *,
    min_lat_g: float = 0.35,
    min_separation_frac: float = 0.02,
    smooth_win: int = 5,
) -> list[tuple[int, int, int]]:
    """Find corners as (entry_i, apex_i, exit_i) index triples.

    A corner is a contiguous run where lateral demand (``lat_g``) exceeds ``min_lat_g``; the apex is
    the speed minimum within it. Runs closer than ``min_separation_frac`` of the lap are merged.
    """
    n = len(lap)
    if n < 5:
        return []
    lat = _smooth([abs(g) for g in lap.lat_g], smooth_win)
    active = [g >= min_lat_g for g in lat]
    runs: list[list[int]] = []
    i = 0
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]:
                j += 1
            runs.append([i, j - 1])
            i = j
        else:
            i += 1
    if not runs:
        return []
    # merge runs separated by a small gap
    gap = max(1, int(min_separation_frac * n))
    merged = [runs[0]]
    for r in runs[1:]:
        if r[0] - merged[-1][1] <= gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    out: list[tuple[int, int, int]] = []
    for entry_i, exit_i in merged:
        lo, hi = entry_i, exit_i
        apex_i = min(range(lo, hi + 1), key=lambda k: lap.v_ms[k])
        out.append((lo, apex_i, hi))
    return out


def corner_signatures(
    lap: LapTrace,
    corners: list[tuple[int, int, int]] | None = None,
    *,
    brake_thresh: float = 0.05,
    throttle_thresh: float = 0.2,
    steer_thresh: float = 0.05,
) -> list[CornerSignature]:
    """Compute a :class:`CornerSignature` for each corner (segmented if not provided)."""
    if corners is None:
        corners = segment_corners(lap)
    sigs: list[CornerSignature] = []
    for idx, (entry_i, apex_i, exit_i) in enumerate(corners):
        sigs.append(
            _signature(
                lap, idx, entry_i, apex_i, exit_i, brake_thresh, throttle_thresh, steer_thresh
            )
        )
    return sigs


def _signature(
    lap: LapTrace,
    idx: int,
    entry_i: int,
    apex_i: int,
    exit_i: int,
    brake_thresh: float,
    throttle_thresh: float,
    steer_thresh: float,
) -> CornerSignature:
    seg = range(entry_i, exit_i + 1)
    peak_lat = max(abs(lap.lat_g[k]) for k in seg)
    peak_brake = max((-lap.long_g[k] for k in seg if lap.long_g[k] < 0), default=0.0)
    peak_accel = max((lap.long_g[k] for k in seg if lap.long_g[k] > 0), default=0.0)
    # braking onset before apex: walk back from apex while brake is applied near-continuously
    brake_point = _first_before(lap.brake, apex_i, entry_i, brake_thresh)
    brake_to_apex = _dist(lap, brake_point, apex_i) if brake_point is not None else None
    # throttle re-application after apex
    throttle_on = _first_after(lap.throttle, apex_i, exit_i, throttle_thresh)
    apex_to_throttle = _dist(lap, apex_i, throttle_on) if throttle_on is not None else None
    # trail-brake: entry samples (turn-in..apex) with brake and steer both active
    entry_seg = range(entry_i, apex_i + 1)
    tb = [k for k in entry_seg if lap.brake[k] > brake_thresh and abs(lap.steer[k]) > steer_thresh]
    trail_frac = len(tb) / max(1, len(entry_seg))
    steers = [lap.steer[k] for k in seg]
    max_abs_steer = max((abs(s) for s in steers), default=0.0)
    mean_steer = sum(steers) / max(1, len(steers))
    direction = (
        "right"
        if mean_steer > steer_thresh
        else "left"
        if mean_steer < -steer_thresh
        else "straightish"
    )
    return CornerSignature(
        index=idx,
        entry_i=entry_i,
        apex_i=apex_i,
        exit_i=exit_i,
        apex_spline=lap.spline[apex_i],
        min_speed_kmh=lap.v_ms[apex_i] * 3.6,
        entry_speed_kmh=lap.v_ms[entry_i] * 3.6,
        exit_speed_kmh=lap.v_ms[exit_i] * 3.6,
        peak_lat_g=round(peak_lat, 3),
        peak_brake_g=round(peak_brake, 3),
        peak_accel_g=round(peak_accel, 3),
        brake_point_spline=None if brake_point is None else lap.spline[brake_point],
        brake_to_apex_m=None if brake_to_apex is None else round(brake_to_apex, 1),
        throttle_on_spline=None if throttle_on is None else lap.spline[throttle_on],
        apex_to_throttle_m=None if apex_to_throttle is None else round(apex_to_throttle, 1),
        trail_brake_frac=round(trail_frac, 3),
        max_abs_steer=round(max_abs_steer, 3),
        direction=direction,
    )


# --- geometry / signal helpers ---------------------------------------------
def _menger(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    abx, aby = b[0] - a[0], b[1] - a[1]
    cbx, cby = b[0] - c[0], b[1] - c[1]
    area2 = abs(abx * cby - aby * cbx)
    la = math.hypot(abx, aby)
    lc = math.hypot(cbx, cby)
    lac = math.hypot(a[0] - c[0], a[1] - c[1])
    denom = la * lc * lac
    return 0.0 if denom < 1e-9 else 2.0 * area2 / denom


def _curvature(plane: list[tuple[float, float]], *, span: int = 2) -> list[float]:
    n = len(plane)
    if n < 2 * span + 1:
        return [0.0] * n
    out = []
    for i in range(n):
        a = plane[max(0, i - span)]
        c = plane[min(n - 1, i + span)]
        out.append(_menger(a, plane[i], c))
    return out


def _derivative(y: list[float], t: list[float], *, scale: float = 1.0) -> list[float]:
    n = len(y)
    out = [0.0] * n
    for i in range(n):
        lo = max(0, i - 1)
        hi = min(n - 1, i + 1)
        dt = t[hi] - t[lo]
        out[i] = (y[hi] - y[lo]) / dt * scale if dt > 1e-6 else 0.0
    return out


def _smooth(y: list[float], win: int) -> list[float]:
    if win <= 1:
        return list(y)
    n = len(y)
    half = win // 2
    out = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out.append(sum(y[lo:hi]) / (hi - lo))
    return out


def _dist(lap: LapTrace, i: int, j: int) -> float:
    if i is None or j is None:
        return 0.0
    lo, hi = (i, j) if i <= j else (j, i)
    total = 0.0
    for k in range(lo, hi):
        total += math.hypot(lap.x[k + 1] - lap.x[k], lap.z[k + 1] - lap.z[k])
    return total


def _first_before(sig: list[float], apex_i: int, floor_i: int, thresh: float) -> int | None:
    """Earliest index in (floor_i..apex_i] from which ``sig`` stays > thresh to the apex."""
    point = None
    for k in range(apex_i, floor_i - 1, -1):
        if sig[k] > thresh:
            point = k
        elif point is not None:
            break
    return point


def _first_after(sig: list[float], apex_i: int, ceil_i: int, thresh: float) -> int | None:
    for k in range(apex_i, ceil_i + 1):
        if sig[k] > thresh:
            return k
    return None


def _spline_from_positions(x: list[float], z: list[float]) -> list[float]:
    """Normalized 0..1 lap position from cumulative arc length (used when no spline channel)."""
    n = len(x)
    if n == 0:
        return []
    dist = [0.0] * n
    for i in range(1, n):
        dist[i] = dist[i - 1] + math.hypot(x[i] - x[i - 1], z[i] - z[i - 1])
    total = dist[-1]
    if total <= 1e-9:
        return [i / max(1, n - 1) for i in range(n)]
    return [d / total for d in dist]


def _time_from_positions(x: list[float], z: list[float], v_ms: list[float]) -> list[float]:
    """Integrate time from inter-sample distance / speed when no eMs channel is present."""
    n = len(x)
    t = [0.0] * n
    for i in range(1, n):
        d = math.hypot(x[i] - x[i - 1], z[i] - z[i - 1])
        v = max(0.5, 0.5 * (v_ms[i] + v_ms[i - 1]))
        t[i] = t[i - 1] + d / v
    return t


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None
