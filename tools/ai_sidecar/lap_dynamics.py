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

#: km/h drop below the pre-corner speed peak that marks the deceleration ONSET — the start of a
#: corner's window for segmentation (see :func:`segment_corners`). Small, so the brake-point
#: detector has room to walk back, without swallowing the straight that precedes the corner.
_DECEL_ONSET_KMH = 2.0


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
    # optional Tier-B chassis + hot-pressure channels (issue #478); None when not persisted OR
    # present-but-all-zero (the "unreadable" sentinel — see _scalar_col / _wheel_cols).
    accg_long: list[float] | None = None  # measured longitudinal g (accG_long, in G; -ve = braking)
    accg_lat: list[float] | None = None  # measured lateral g (accG_lat, in G)
    yaw_rate: list[float] | None = None  # measured yaw rate (rad/s), CSP localAngularVelocity.y
    wheel_pressure: list[list[float]] | None = None  # dynamic HOT pressure psi [FL, FR, RL, RR]
    # optional Tier-1 base-AC dynamic channels (issue #490); per sample, 4 wheels [FL, FR, RL, RR];
    # None when not persisted OR present-but-all-zero (the "unreadable" sentinel — see _wheel_cols).
    tyre_temp_inner: list[list[float]] | None = None  # tread inner temp, °C
    tyre_temp_mid: list[list[float]] | None = None  # tread middle temp, °C
    tyre_temp_outer: list[list[float]] | None = None  # tread outer temp, °C
    camber: list[list[float]] | None = None  # dynamic (running) camber, DEGREES (CSP `camber`)
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

    @property
    def has_chassis_data(self) -> bool:
        """True when measured chassis dynamics (accG / yaw_rate) are persisted in this lap."""
        return self.yaw_rate is not None or self.accg_lat is not None or self.accg_long is not None

    @property
    def has_pressure_data(self) -> bool:
        """True when dynamic HOT tyre pressure is persisted in this lap (issue #478)."""
        return self.wheel_pressure is not None

    @property
    def has_tyre_band_data(self) -> bool:
        """True when cross-tread tyre temps (inner + outer) are persisted (issue #490).

        Requires BOTH bands — the cross-tread gradient (inner-vs-outer) is the camber/pressure
        diagnosis signal, so a lap with only one band cannot confirm the rule.
        """
        return self.tyre_temp_inner is not None and self.tyre_temp_outer is not None

    @property
    def has_tier_b_data(self) -> bool:
        """True when ANY live channel (per-wheel, chassis, pressure, or tyre bands) is persisted."""
        return (
            self.has_wheel_data
            or self.has_chassis_data
            or self.has_pressure_data
            or self.has_tyre_band_data
        )


def _idx(fields: list[str], *names: str) -> int | None:
    for n in names:
        if n in fields:
            return fields.index(n)
    return None


_WHEELS = ("fl", "fr", "rl", "rr")


def _wheel_cols(fields: list[str], samples: list, base: str, n: int) -> list[list[float]] | None:
    """Read a 4-wheel channel (``<base>_fl/fr/rl/rr``) into N rows of [FL, FR, RL, RR], or None.

    Returns None when the columns are absent OR present-but-all-zero. The all-zero guard matters
    since #266 made these fields ALWAYS present in the trace: a real lap whose wheels were
    unreadable persists zeros, and a zero ``wheelAngularSpeed`` would otherwise compute slip = -1
    (full lock) at every sample and falsely "confirm" a lockup. All-zero => treat as no live data.
    """
    idxs = [_idx(fields, f"{base}_{w}") for w in _WHEELS]
    if any(i is None for i in idxs):
        return None
    out: list[list[float]] = []
    any_nonzero = False
    for row in samples:
        vals = []
        for i in idxs:
            try:
                v = float(row[i])
            except (TypeError, ValueError, IndexError):
                v = 0.0
            if v != 0.0:
                any_nonzero = True
            vals.append(v)
        out.append(vals)
    return out if any_nonzero else None


def _scalar_col(fields: list[str], samples: list, name: str) -> list[float] | None:
    """Read a single channel column by ``name`` into N floats, or None.

    Same all-zero guard as :func:`_wheel_cols`: #478 makes these chassis fields ALWAYS present in a
    new trace, so a real lap whose chassis was unreadable persists zeros. A zero must read as "no
    live data" (not a real 0 g / 0 yaw), so the confirming channel marker is never emitted off an
    absent signal. Returns None when the column is absent OR present-but-all-zero.
    """
    i = _idx(fields, name)
    if i is None:
        return None
    out: list[float] = []
    any_nonzero = False
    for row in samples:
        try:
            v = float(row[i])
        except (TypeError, ValueError, IndexError):
            v = 0.0
        if v != 0.0:
            any_nonzero = True
        out.append(v)
    return out if any_nonzero else None


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
    # optional Tier-B chassis + hot-pressure channels; present only when persisted (#478)
    accg_long = _scalar_col(fields, samples, "accG_long")
    accg_lat = _scalar_col(fields, samples, "accG_lat")
    yaw_rate = _scalar_col(fields, samples, "yaw_rate")
    wheel_pressure = _wheel_cols(fields, samples, "wheelsPressure", n)
    # optional Tier-1 base-AC dynamic bands (issue #490); present only when persisted
    tyre_temp_inner = _wheel_cols(fields, samples, "tyreTempInner", n)
    tyre_temp_mid = _wheel_cols(fields, samples, "tyreTempMid", n)
    tyre_temp_outer = _wheel_cols(fields, samples, "tyreTempOuter", n)
    camber = _wheel_cols(fields, samples, "camber", n)

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
        accg_long=accg_long,
        accg_lat=accg_lat,
        yaw_rate=yaw_rate,
        wheel_pressure=wheel_pressure,
        tyre_temp_inner=tyre_temp_inner,
        tyre_temp_mid=tyre_temp_mid,
        tyre_temp_outer=tyre_temp_outer,
        camber=camber,
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
    steering_correction_count: int = 0
    steering_rate_p95: float = 0.0
    steering_smoothness_score: float = 100.0
    steering_scrub_index: float = 0.0
    gear_at_apex: int | None = None
    entry_gear: int | None = None
    exit_gear: int | None = None
    gear_change_count: int = 0
    brake_shape: str = "unknown"
    brake_late_rise_count: int = 0
    brake_release_smoothness: float = 1.0

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
    smooth_win: int = 5,
    min_apex_drop_kmh: float = 15.0,
    split_rise_kmh: float = 18.0,
) -> list[tuple[int, int, int]]:
    """Find corners as (entry_i, apex_i, exit_i) triples — one per real, driver-perceived corner.

    A corner is a **prominent speed minimum** (you brake and slow down for it), gated by a little
    lateral g at the apex. This keeps the corner list — and therefore the coach's spoken turn
    numbers — aligned with the track (issue: cue/track misalignment, where phantom corners shifted
    every turn number and merged corners fired cues seconds early):

    * **Phantom rejection** (``min_apex_drop_kmh``): ``lat_g = v² · κ / G`` blows up at high speed,
      so a gentle kink on a 200 km/h straight (and the start/finish line) clears ``min_lat_g`` with
      no real slow-down. A genuine corner's apex must sit at least ``min_apex_drop_kmh`` below the
      higher of its entry/exit boundary speeds, else it is dropped.
    * **Blob splitting** (``split_rise_kmh``): neighbouring minima are kept separate only when the
      speed *peak* between them rises ``split_rise_kmh`` above the deeper minimum, so an esses
      splits into several corners (each its own apex) instead of one giant window.

    ``entry_i`` reaches back to the deceleration onset (room for the brake-point detector) while
    ``exit_i`` stays tight (40 % speed recovery past the apex) so cues land right at the corner.
    """
    n = len(lap)
    if n < 5:
        return []
    v = _smooth(lap.v_ms, smooth_win)
    lat = _smooth([abs(g) for g in lap.lat_g], smooth_win)

    # 1. Candidate apexes = local speed minima (a driver-perceived corner IS a speed dip). Collapse
    #    flat minima to their midpoint.
    mins: list[int] = []
    k = 1
    while k < n - 1:
        if v[k] <= v[k - 1] and v[k] <= v[k + 1]:
            j = k
            while j < n - 1 and v[j + 1] == v[k]:
                j += 1
            mins.append((k + j) // 2)
            k = j + 1
        else:
            k += 1
    if not mins:
        return []

    # 2. Merge neighbouring minima separated only by a shallow speed peak (one corner, double apex).
    merged_mins: list[int] = []
    for m in mins:
        if merged_mins:
            peak = max(range(merged_mins[-1], m + 1), key=lambda t: v[t])
            if (v[peak] - max(v[merged_mins[-1]], v[m])) * 3.6 < split_rise_kmh:
                if v[m] < v[merged_mins[-1]]:
                    merged_mins[-1] = m
                continue
        merged_mins.append(m)

    # 3. Build each corner. Entry reaches back to the deceleration onset so the braking zone is in
    #    the window (the brake-point detector needs room before the apex); exit stays TIGHT — the
    #    first point where speed has recovered 40% of the dip — so the apex-deficit grade and the
    #    spoken cue land right at the corner, not deep onto the next straight.
    # smoothing offsets the minimum a sample or two; snap each apex to the true raw-speed minimum
    raw = lap.v_ms
    out: list[tuple[int, int, int]] = []
    for mi, apex in enumerate(merged_mins):
        lb = 0 if mi == 0 else merged_mins[mi - 1]
        rb = n - 1 if mi == len(merged_mins) - 1 else merged_mins[mi + 1]
        a_lo, a_hi = max(lb, apex - smooth_win), min(rb, apex + smooth_win)
        apex = min(range(a_lo, a_hi + 1), key=lambda t: raw[t])  # exact apex speed
        # Entry = the deceleration ONSET (where speed first falls a hair below the preceding peak),
        # not the peak itself: wide enough that the brake-point detector has room to walk back, but
        # tight enough that a straight on the approach is NOT counted as part of the corner window.
        peak_i = max(range(lb, apex + 1), key=lambda t: v[t])
        entry = peak_i
        while entry < apex and raw[entry] > raw[peak_i] - _DECEL_ONSET_KMH / 3.6:
            entry += 1
        exit_peak = max(range(apex, rb + 1), key=lambda t: v[t])
        drop_kmh = (max(raw[entry], raw[exit_peak]) - raw[apex]) * 3.6
        if drop_kmh < min_apex_drop_kmh:  # phantom: lat_g spike with no real slow-down
            continue
        if lat[apex] < min_lat_g:  # braking on a straight is not a corner
            continue
        recover = raw[apex] + 0.4 * (raw[exit_peak] - raw[apex])
        ex = apex
        while ex < exit_peak and raw[ex] < recover:
            ex += 1
        if entry < apex < ex:
            out.append((entry, apex, ex))
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
    steering = _steering_metrics(lap, entry_i, apex_i, exit_i, steer_thresh=steer_thresh)
    gear = _gear_metrics(lap, entry_i, apex_i, exit_i)
    brake_shape = _brake_shape_metrics(lap, entry_i, apex_i, brake_thresh=brake_thresh)
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
        steering_correction_count=steering["corrections"],
        steering_rate_p95=steering["rate_p95"],
        steering_smoothness_score=steering["smoothness_score"],
        steering_scrub_index=steering["scrub_index"],
        gear_at_apex=gear["apex"],
        entry_gear=gear["entry"],
        exit_gear=gear["exit"],
        gear_change_count=gear["changes"],
        brake_shape=brake_shape["classification"],
        brake_late_rise_count=brake_shape["late_rises"],
        brake_release_smoothness=brake_shape["release_smoothness"],
    )


# --- geometry / signal helpers ---------------------------------------------
def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * q))))
    return ordered[pos]


def _steering_metrics(
    lap: LapTrace,
    entry_i: int,
    apex_i: int,
    exit_i: int,
    *,
    steer_thresh: float,
) -> dict[str, float | int]:
    """Single-lap steering smoothness facts.

    The archive has steering input but no tyre scrub telemetry. We therefore expose an honest
    *scrub proxy*: high steering rate and repeated corrections while the car is fast and loaded.
    """
    seg = list(range(entry_i, exit_i + 1))
    if len(seg) < 2:
        return {
            "corrections": 0,
            "rate_p95": 0.0,
            "smoothness_score": 100.0,
            "scrub_index": 0.0,
        }
    rates: list[float] = []
    signed: list[int] = []
    scrub_terms: list[float] = []
    for a, b in zip(seg, seg[1:], strict=False):
        dt = max(1e-3, lap.t_s[b] - lap.t_s[a])
        delta = lap.steer[b] - lap.steer[a]
        rate = abs(delta) / dt
        rates.append(rate)
        # Proxy for scrub risk: steering saw while loaded/speedy. It is NOT tyre slip.
        scrub_terms.append(rate * max(0.0, abs(lap.lat_g[b])) * max(0.0, lap.v_ms[b]) / 50.0)
    for k in seg:
        steer = lap.steer[k]
        if abs(steer) > steer_thresh:
            signed.append(1 if steer > 0 else -1)
    corrections = 0
    last = signed[0] if signed else 0
    for sign in signed[1:]:
        if sign != last:
            corrections += 1
            last = sign
    rate_p95 = _quantile(rates, 0.95)
    scrub = sum(scrub_terms) / max(1, len(scrub_terms))
    smoothness = 100.0 - min(70.0, rate_p95 * 16.0) - min(30.0, corrections * 8.0)
    return {
        "corrections": corrections,
        "rate_p95": round(rate_p95, 3),
        "smoothness_score": round(max(0.0, smoothness), 1),
        "scrub_index": round(scrub, 3),
    }


def _gear_value(value: float) -> int | None:
    if not math.isfinite(value):
        return None
    gear = int(round(value))
    return gear if gear > 0 else None


def _gear_metrics(lap: LapTrace, entry_i: int, apex_i: int, exit_i: int) -> dict[str, int | None]:
    gears = [_gear_value(lap.gear[k]) for k in range(entry_i, exit_i + 1)]
    compact = [g for g in gears if g is not None]
    changes = 0
    last = compact[0] if compact else None
    for gear in compact[1:]:
        if gear != last:
            changes += 1
            last = gear
    return {
        "entry": _gear_value(lap.gear[entry_i]),
        "apex": _gear_value(lap.gear[apex_i]),
        "exit": _gear_value(lap.gear[exit_i]),
        "changes": changes,
    }


def _brake_shape_metrics(
    lap: LapTrace,
    entry_i: int,
    apex_i: int,
    *,
    brake_thresh: float,
) -> dict[str, float | int | str]:
    active = [k for k in range(entry_i, apex_i + 1) if lap.brake[k] > brake_thresh]
    if not active:
        return {"classification": "no_brake", "late_rises": 0, "release_smoothness": 1.0}
    peak_i = max(active, key=lambda k: lap.brake[k])
    peak = lap.brake[peak_i]
    late_rises = 0
    max_drop = 0.0
    late_start = entry_i + max(0, apex_i - entry_i) // 2
    for a, b in zip(range(late_start, apex_i), range(late_start + 1, apex_i + 1), strict=False):
        if lap.brake[b] - lap.brake[a] > 0.05:
            late_rises += 1
    for a, b in zip(range(peak_i, apex_i), range(peak_i + 1, apex_i + 1), strict=False):
        delta = lap.brake[b] - lap.brake[a]
        max_drop = max(max_drop, -delta)
    release_total = max(0.0, peak - lap.brake[apex_i])
    release_smoothness = 1.0 if release_total <= 1e-6 else 1.0 - min(1.0, max_drop / release_total)
    if late_rises >= 2:
        classification = "increasing_pressure"
    elif max_drop >= 0.35:
        classification = "abrupt_release"
    elif lap.brake[apex_i] >= 0.25:
        classification = "braking_at_apex"
    else:
        classification = "ideal_trace"
    return {
        "classification": classification,
        "late_rises": late_rises,
        "release_smoothness": round(max(0.0, release_smoothness), 3),
    }


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
