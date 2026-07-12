"""Auto-handshake plant identification — machine-measure the controller constants (#529 P1 / #532).

The Magione frontier feat (#244: 90.7s human -> 82.7s autonomous) ran on **hand constants**:
``ff_sign`` set per-track from a human-lap correlation, ``ff_c1``/``ff_c2`` fit offline by a
(since lost) ``.scratch`` script, shift points as :class:`RacingDriver` defaults, one hardcoded
``generic_gt3_ggv()`` plant for every car. This module is the Phase-0 **kinematic handshake**
(epic #529 gate G0): designed probe maneuvers executed in-sim through the carcsw hijack measure
every one of those constants from the car's actual response, each with a quality metric and an
interpretable failure mode — zero hand-tuned values on the pipeline.

Probes (all within <= ``max_laps`` laps of track time, default 2):

* **steer pulses** (short straight-line steer excursions, both directions) -> ``ff_sign`` — the
  sign mapping between the actuator (``steer > 0``) and the line-curvature convention of
  :func:`tools.ac_harness.ggv_profile.signed_curvature_profile` (both use the same (x, z)
  cross-product form, so the pulse measurement and the controller consume one convention).
* **corner mining** (normal guided driving between probes) -> ``ff_c1``/``ff_c2`` — windowed
  kinematic rows (speed, yaw-rate-implied lateral g, commanded steer) fed to the *existing*
  :func:`tools.ac_harness.ggv_profile.fit_steer_feedforward` (no duplicated fit logic).
* **WOT accel sweep** (full throttle through the gears on the longest straight) -> per-gear
  ratios (rpm/speed) + shift points ``rpm_up``/``rpm_dn`` from the accel-crossover between
  adjacent gears (falls back to an observed-limiter margin, and says so in provenance).
* **coast** (throttle+brake free segment) -> effective wheel radius ``r_eff_m`` from
  ``wheelAngularSpeed[4]`` vs body speed (feeds :func:`racing_driver.slip_ratio`).

Design split (house rule): everything here is **pure and CI-testable** — the controller conforms
to the same ``step()``/``on_recovery()`` contract as :class:`RacingDriver`, so the *unchanged*
``auto_drive.rig_drive`` loop executes it (one rig loop, no drift), driving a synthetic plant in
tests. The only rig-only piece is the lazy ``acpmf_physics`` reader (``phys_read="auto"``).

Artifacts persist per-combo under ``<AC user dir>/plant_id/`` — a **durable** Documents path,
never ``.scratch`` (the original ``model_id.py`` was lost to exactly that; see issue #532's
pitfall list).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from dataclasses import replace as dc_replace
from pathlib import Path

from tools.ac_harness.ai_line import _horizontal
from tools.ac_harness.ggv_profile import (
    fit_steer_feedforward,
    seg_lengths,
    signed_curvature_profile,
)
from tools.ac_harness.lap_driver import PHASE_LAP, DriveFrame
from tools.ac_harness.racing_driver import RacingDriver

G = 9.81
PLANT_SCHEMA_VERSION = 1

# AC gear encoding (live-verified, see custom_ai.py): 0=Reverse, 1=Neutral, 2=1st, 3=2nd, ...
_FIRST_FORWARD_GEAR = 2


def _finite(*values: float) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


# ---------------------------------------------------------------------------
# Measurements + result envelope
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProbeMeasurement:
    """One machine-measured constant (or constant group) with quality + provenance.

    ``detail`` must stay interpretable on failure: it names the probe and the observed values so
    the hard-abort in the run report tells the operator *what the car actually did* (#532 AC).
    """

    name: str
    passed: bool
    value: dict
    quality: dict
    method: str
    detail: str


@dataclass(frozen=True)
class HandshakeResult:
    """The full handshake outcome: every measurement, pass/fail, and the merged constants."""

    ok: bool
    car_id: str
    track_id: str
    laps_used: int
    duration_s: float
    measurements: tuple[ProbeMeasurement, ...]

    def failed(self) -> list[ProbeMeasurement]:
        return [m for m in self.measurements if not m.passed]

    def constants(self) -> dict:
        """Merged constants from PASSED measurements only (a failed probe contributes nothing)."""
        out: dict = {}
        for m in self.measurements:
            if m.passed:
                out.update(m.value)
        return out

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "car_id": self.car_id,
            "track_id": self.track_id,
            "laps_used": self.laps_used,
            "duration_s": round(self.duration_s, 1),
            "constants": self.constants(),
            "measurements": [asdict(m) for m in self.measurements],
        }


# ---------------------------------------------------------------------------
# Pure fits (unit-testable on synthetic data)
# ---------------------------------------------------------------------------
def fit_ff_sign(
    pulses: list[dict], *, min_abs_dpsi_rad: float = 0.035, min_pulses: int = 2
) -> ProbeMeasurement:
    """``ff_sign`` from steer-pulse records ``{"steer", "dpsi_rad", "duration_s", "speed_kmh"}``.

    Each pulse's heading change ``dpsi_rad`` uses the same (x, z) cross convention as the line's
    signed curvature, so ``sign(dpsi) * sign(steer)`` IS the feedforward sign. All pulses must
    agree and each must produce a clearly-resolved heading change.
    """
    quality = {"pulses": len(pulses), "min_abs_dpsi_rad": min_abs_dpsi_rad}
    observed = [
        {
            "steer": round(p.get("steer", 0.0), 3),
            "dpsi_rad": round(p.get("dpsi_rad", 0.0), 4),
            "speed_kmh": round(p.get("speed_kmh", 0.0), 1),
        }
        for p in pulses
    ]
    quality["observed"] = observed
    if len(pulses) < min_pulses:
        return ProbeMeasurement(
            "ff_sign",
            False,
            {},
            quality,
            "steer-pulse",
            f"only {len(pulses)}/{min_pulses} steer pulses captured (probe did not complete "
            "within the lap budget)",
        )
    signs: list[int] = []
    for p in pulses:
        steer = float(p.get("steer", 0.0))
        dpsi = float(p.get("dpsi_rad", 0.0))
        if not _finite(steer, dpsi) or abs(steer) < 1e-6:
            return ProbeMeasurement(
                "ff_sign", False, {}, quality, "steer-pulse", f"non-finite pulse record: {p}"
            )
        if abs(dpsi) < min_abs_dpsi_rad:
            return ProbeMeasurement(
                "ff_sign",
                False,
                {},
                quality,
                "steer-pulse",
                f"ambiguous yaw response: |dpsi|={abs(dpsi):.4f} rad < {min_abs_dpsi_rad} for "
                f"steer={steer:+.2f} at {p.get('speed_kmh', 0):.0f} km/h",
            )
        signs.append(1 if dpsi * steer > 0 else -1)
    if len(set(signs)) != 1:
        return ProbeMeasurement(
            "ff_sign",
            False,
            {},
            quality,
            "steer-pulse",
            f"pulses disagree on the steer->yaw sign: {signs} (observed: {observed})",
        )
    both_dirs = len({1 if p["steer"] > 0 else -1 for p in pulses}) == 2
    quality["both_directions"] = both_dirs
    return ProbeMeasurement(
        "ff_sign",
        True,
        {"ff_sign": float(signs[0])},
        quality,
        "steer-pulse",
        f"{len(pulses)} pulses agree: steer>0 turns "
        f"{'with' if signs[0] > 0 else 'against'} the +curvature convention",
    )


def fit_steer_ff(
    rows: list[dict],
    *,
    ff_sign: float | None = None,
    min_rows_used: int = 80,
    max_rms_frac: float = 0.5,
) -> ProbeMeasurement:
    """``ff_c1``/``ff_c2`` from mined corner rows, via the existing GGV steer-feedforward fitter.

    The fit's own sign (``sign(c1)``) must reconcile with the pulse-measured ``ff_sign`` when one
    is supplied — the two probes observe the same physical relation through different maneuvers,
    so a mismatch means at least one measurement is bad and the handshake must not pass it on.
    """
    c1, c2, rms_frac, n = fit_steer_feedforward(rows)
    quality = {"rows": len(rows), "rows_used": n, "rms_frac": round(rms_frac, 4)}
    if n < min_rows_used:
        return ProbeMeasurement(
            "steer_ff",
            False,
            {},
            quality,
            "corner-mining + fit_steer_feedforward",
            f"only {n} usable corner rows (< {min_rows_used}); not enough cornering captured "
            "within the lap budget",
        )
    if not _finite(c1, c2, rms_frac) or abs(c1) < 1e-9:
        return ProbeMeasurement(
            "steer_ff",
            False,
            {},
            quality,
            "corner-mining + fit_steer_feedforward",
            f"degenerate fit: c1={c1!r} c2={c2!r} rms_frac={rms_frac!r}",
        )
    if rms_frac > max_rms_frac:
        return ProbeMeasurement(
            "steer_ff",
            False,
            {},
            quality,
            "corner-mining + fit_steer_feedforward",
            f"fit residual too high: rms_frac={rms_frac:.3f} > {max_rms_frac} over {n} rows",
        )
    fit_sign = 1.0 if c1 > 0 else -1.0
    quality["fit_sign"] = fit_sign
    if ff_sign is not None and fit_sign != ff_sign:
        return ProbeMeasurement(
            "steer_ff",
            False,
            {},
            quality,
            "corner-mining + fit_steer_feedforward",
            f"corner-fit sign ({fit_sign:+.0f}) contradicts the pulse-measured ff_sign "
            f"({ff_sign:+.0f}) — c1={c1:.4f}, c2={c2:.6f}; refusing both",
        )
    # Normalize magnitudes: c1 > 0, direction carried by ff_sign (the controller applies
    # ``steer = ff_sign * (c1*kappa + c2*v^2*kappa)``).
    return ProbeMeasurement(
        "steer_ff",
        True,
        {"ff_c1": c1 * fit_sign, "ff_c2": c2 * fit_sign},
        quality,
        "corner-mining + fit_steer_feedforward",
        f"c1={c1 * fit_sign:.4f} c2={c2 * fit_sign:.6f} rms_frac={rms_frac:.3f} n={n}",
    )


def fit_gear_ratios(
    ratio_samples: dict[int, list[float]], *, min_samples: int = 25, max_mad_frac: float = 0.05
) -> ProbeMeasurement:
    """Per-gear ``rpm / speed_kmh`` ratios (median), gears in AC encoding (2 = 1st).

    Gates: >= 2 observed gears, per-gear scatter (MAD/median) below ``max_mad_frac``, ratios
    strictly decreasing with gear (a taller gear always turns fewer rpm per km/h).
    """
    ratios: dict[int, float] = {}
    quality: dict = {"per_gear_n": {}, "per_gear_mad_frac": {}}
    for gear, samples in sorted(ratio_samples.items()):
        finite = [s for s in samples if _finite(s) and s > 0]
        quality["per_gear_n"][gear] = len(finite)
        if len(finite) < min_samples:
            continue
        med = _median(finite)
        mad = _median([abs(s - med) for s in finite])
        mad_frac = mad / med if med > 0 else 1.0
        quality["per_gear_mad_frac"][gear] = round(mad_frac, 4)
        if mad_frac > max_mad_frac:
            return ProbeMeasurement(
                "gear_ratios",
                False,
                {},
                quality,
                "rpm/speed per stable gear",
                f"gear {gear - 1} ratio scatter too high (MAD/median={mad_frac:.3f} > "
                f"{max_mad_frac}) — clutch-slip or shift transients contaminated the samples",
            )
        ratios[gear] = med
    if len(ratios) < 2:
        return ProbeMeasurement(
            "gear_ratios",
            False,
            {},
            quality,
            "rpm/speed per stable gear",
            f"only {len(ratios)} gear(s) with >= {min_samples} stable samples "
            f"(observed n per gear: {quality['per_gear_n']})",
        )
    ordered = [ratios[g] for g in sorted(ratios)]
    if any(b >= a for a, b in zip(ordered, ordered[1:], strict=False)):
        return ProbeMeasurement(
            "gear_ratios",
            False,
            {},
            quality,
            "rpm/speed per stable gear",
            f"ratios not strictly decreasing with gear: "
            f"{ {g - 1: round(r, 1) for g, r in sorted(ratios.items())} }",
        )
    return ProbeMeasurement(
        "gear_ratios",
        True,
        {"gear_ratios": {str(g): round(r, 3) for g, r in sorted(ratios.items())}},
        quality,
        "rpm/speed per stable gear",
        f"{len(ratios)} gears: "
        + ", ".join(f"g{g - 1}={r:.1f}" for g, r in sorted(ratios.items())),
    )


def fit_shift_points(
    sweep_samples: list[dict],
    ratios: dict[int, float],
    *,
    rpm_bin: float = 200.0,
    fallback_limiter_frac: float = 0.97,
    downshift_margin: float = 0.9,
) -> ProbeMeasurement:
    """``rpm_up``/``rpm_dn`` from the WOT sweep's per-gear accel curves.

    Preferred method: for adjacent observed gears, the accel-crossover rpm where the next gear
    out-accelerates the current one. Fallback (and the provenance says so): a margin below the
    observed limiter. ``rpm_dn`` is placed so a downshift lands the engine below ``rpm_up``.
    """
    by_gear: dict[int, dict[int, list[float]]] = {}
    rpm_max = 0.0
    for s in sweep_samples:
        gear, rpm, accel = s.get("gear"), s.get("rpm"), s.get("accel_mps2")
        if gear is None or not _finite(rpm, accel) or gear < _FIRST_FORWARD_GEAR or rpm <= 0:
            continue
        rpm_max = max(rpm_max, rpm)
        by_gear.setdefault(int(gear), {}).setdefault(int(rpm // rpm_bin), []).append(float(accel))
    gears = sorted(by_gear)
    quality: dict = {
        "sweep_samples": len(sweep_samples),
        "gears_observed": [g - 1 for g in gears],
        "rpm_max_observed": round(rpm_max, 0),
    }
    if len(gears) < 2:
        return ProbeMeasurement(
            "shift_points",
            False,
            {},
            quality,
            "WOT sweep accel-crossover",
            f"sweep covered {len(gears)} gear(s) (need >= 2); "
            f"{len(sweep_samples)} samples captured — probe did not complete a multi-gear pull",
        )

    def curve(gear: int) -> dict[int, float]:
        return {b: _median(v) for b, v in by_gear[gear].items() if v}

    crossovers: list[float] = []
    for g, g_next in zip(gears, gears[1:], strict=False):
        if g_next != g + 1 or g not in ratios or g_next not in ratios:
            continue
        step = ratios[g_next] / ratios[g]  # < 1 for a taller gear
        cur, nxt = curve(g), curve(g_next)
        if not cur or not nxt:
            continue
        peak_bin = max(cur, key=cur.get)
        for b in sorted(cur):
            if b <= peak_bin:
                continue
            rpm_here = (b + 0.5) * rpm_bin
            nb = int((rpm_here * step) // rpm_bin)
            if nb in nxt and cur[b] <= nxt[nb]:
                crossovers.append(rpm_here)
                break
    if crossovers:
        rpm_up = _median(crossovers)
        method = "accel-crossover"
        quality["crossovers"] = [round(c, 0) for c in crossovers]
    else:
        rpm_up = rpm_max * fallback_limiter_frac
        method = "limiter-margin"
        quality["fallback"] = f"{fallback_limiter_frac} * observed max rpm {rpm_max:.0f}"
    steps = [
        ratios[b] / ratios[a]
        for a, b in zip(sorted(ratios), sorted(ratios)[1:], strict=False)
        if a in ratios and b in ratios
    ]
    if not steps or not _finite(rpm_up) or not 3000.0 <= rpm_up <= 12000.0:
        return ProbeMeasurement(
            "shift_points",
            False,
            {},
            quality,
            method,
            f"implausible rpm_up={rpm_up:.0f} (expect 3000..12000) or no ratio steps "
            f"(steps={steps})",
        )
    rpm_dn = rpm_up * _median(steps) * downshift_margin
    if not _finite(rpm_dn) or rpm_dn >= rpm_up * 0.85 or rpm_dn < 1500.0:
        return ProbeMeasurement(
            "shift_points",
            False,
            {},
            quality,
            method,
            f"implausible rpm_dn={rpm_dn:.0f} from rpm_up={rpm_up:.0f} and ratio steps {steps}",
        )
    return ProbeMeasurement(
        "shift_points",
        True,
        {"rpm_up": round(rpm_up, 0), "rpm_dn": round(rpm_dn, 0)},
        quality,
        method,
        f"rpm_up={rpm_up:.0f} rpm_dn={rpm_dn:.0f} ({method}, {len(gears)} gears observed)",
    )


def fit_r_eff(
    coast_samples: list[dict],
    *,
    min_samples: int = 25,
    min_omega: float = 8.0,
    max_spread_frac: float = 0.08,
) -> ProbeMeasurement:
    """Effective wheel radius from coast samples ``{"v_mps", "omega": (fl, fr, rl, rr)}``.

    On a coast (no drive, no brake torque) every wheel rolls true, so ``v / omega`` is the
    rolling radius. Per-wheel medians must agree within ``max_spread_frac``.
    """
    per_wheel: list[list[float]] = [[], [], [], []]
    for s in coast_samples:
        v = s.get("v_mps")
        omega = s.get("omega")
        if not _finite(v) or v < 3.0 or not omega or len(omega) != 4:
            continue
        for i, w in enumerate(omega):
            if _finite(w) and w > min_omega:
                per_wheel[i].append(v / w)
    counts = [len(w) for w in per_wheel]
    quality: dict = {"coast_samples": len(coast_samples), "per_wheel_n": counts}
    if min(counts, default=0) < min_samples:
        return ProbeMeasurement(
            "r_eff",
            False,
            {},
            quality,
            "coast v/omega",
            f"insufficient coast wheel-speed samples (per wheel: {counts}, need >= "
            f"{min_samples} each) — physics reader unavailable or coast probe never ran",
        )
    medians = [_median(w) for w in per_wheel]
    r_eff = _median(medians)
    spread = (max(medians) - min(medians)) / r_eff if r_eff > 0 else 1.0
    quality["per_wheel_r_m"] = [round(m, 4) for m in medians]
    quality["spread_frac"] = round(spread, 4)
    if not _finite(r_eff) or not 0.2 <= r_eff <= 0.5:
        return ProbeMeasurement(
            "r_eff",
            False,
            {},
            quality,
            "coast v/omega",
            f"implausible r_eff={r_eff!r} m (expect 0.2..0.5; per-wheel {medians})",
        )
    if spread > max_spread_frac:
        return ProbeMeasurement(
            "r_eff",
            False,
            {},
            quality,
            "coast v/omega",
            f"per-wheel radii disagree (spread {spread:.3f} > {max_spread_frac}): {medians}",
        )
    return ProbeMeasurement(
        "r_eff",
        True,
        {"r_eff_m": round(r_eff, 4)},
        quality,
        "coast v/omega",
        f"r_eff={r_eff:.3f} m (per-wheel {[f'{m:.3f}' for m in medians]})",
    )


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return float("nan")
    mid = n // 2
    return s[mid] if n % 2 else 0.5 * (s[mid - 1] + s[mid])


# ---------------------------------------------------------------------------
# Straight detection on the racing line
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Straight:
    start_idx: int
    end_idx: int  # inclusive, cyclic
    length_m: float


def find_straights(
    plane: list[tuple[float, float]],
    *,
    kappa_max: float = 0.004,
    min_length_m: float = 60.0,
) -> list[Straight]:
    """Contiguous cyclic runs of near-zero curvature, longest first."""
    kappa = signed_curvature_profile(plane)
    seg = seg_lengths(plane)
    n = len(plane)
    mask = [abs(k) < kappa_max for k in kappa]
    if all(mask):
        return [Straight(0, n - 1, sum(seg))]
    # rotate so index 0 is NOT straight -> runs never wrap
    start = mask.index(False)
    runs: list[Straight] = []
    i = 0
    while i < n:
        j = (start + i) % n
        if not mask[j]:
            i += 1
            continue
        k = i
        length = 0.0
        while k < n and mask[(start + k) % n]:
            length += seg[(start + k) % n]
            k += 1
        if length >= min_length_m:
            runs.append(Straight((start + i) % n, (start + k - 1) % n, length))
        i = k
    return sorted(runs, key=lambda s: -s.length_m)


def _straight_membership(
    straights: list[Straight], seg: list[float], n: int
) -> tuple[list[int], list[float]]:
    """Per-point ``(straight_id, arc distance to that straight's end)`` (-1 / 0.0 when none)."""
    sid = [-1] * n
    dist_to_end = [0.0] * n
    for s_id, s in enumerate(straights):
        idx = s.end_idx
        acc = 0.0
        while True:
            sid[idx] = s_id
            dist_to_end[idx] = acc
            if idx == s.start_idx:
                break
            acc += seg[(idx - 1) % n]
            idx = (idx - 1) % n
    return sid, dist_to_end


# ---------------------------------------------------------------------------
# The handshake controller (drop-in for the rig drive loop's driver contract)
# ---------------------------------------------------------------------------
def _unit_xz(p: tuple[float, float, float]) -> tuple[float, float] | None:
    x, z = _horizontal(p)
    norm = math.hypot(x, z)
    if norm < 1e-6 or not _finite(x, z):
        return None
    return (x / norm, z / norm)


def _heading_delta(h0: tuple[float, float], h1: tuple[float, float]) -> float:
    """Signed heading change (rad) in the SAME (x, z) cross convention as the line curvature."""
    cross = h0[0] * h1[1] - h0[1] * h1[0]
    dot = h0[0] * h1[0] + h0[1] * h1[1]
    return math.atan2(cross, dot)


class HandshakeController:
    """Guided-drive probe executor: navigates the AI line conservatively, runs designed probes
    on straights, mines corners, then fits + gates every constant (:class:`HandshakeResult`).

    Conforms to the ``step()``/``on_recovery()`` driver contract of :class:`RacingDriver`, plus
    a ``finished`` flag the rig loop honors, so **the existing** ``rig_drive`` executes it. On
    completion the result lands in ``sink`` (a mutable dict shared with the CLI): keys ``ok``,
    ``result`` (full dict), ``constants``.
    """

    def __init__(
        self,
        fast_line: list[tuple[float, float, float]],
        speed_profile: list[float],
        *,
        car_id: str = "",
        track_id: str = "",
        sink: dict | None = None,
        phys_read=None,  # Callable[[], PhysFrame | None] | "auto" | None
        pace: float = 0.65,
        max_speed_kmh: float = 150.0,
        max_laps: int = 2,
        kappa_straight: float = 0.004,
        min_straight_m: float = 60.0,
        # Pulse sizing (live-safety): 0.08 normalized steer at <=75 km/h keeps a GT3 well inside
        # its lateral grip while the ~0.15 rad heading response stays ~4x the resolve gate.
        pulse_steer: float = 0.08,
        pulse_seconds: float = 0.9,
        pulse_gap_seconds: float = 1.2,
        pulse_count: int = 4,
        pulse_speed_range_kmh: tuple[float, float] = (25.0, 75.0),
        sweep_min_straight_m: float = 220.0,
        coast_seconds: float = 2.2,
        coast_min_kmh: float = 45.0,
        row_interval_s: float = 0.25,
        min_corner_rows: int = 120,
    ) -> None:
        self._base = RacingDriver(fast_line, speed_profile, pace=pace, max_speed_kmh=max_speed_kmh)
        self.car_id = car_id
        self.track_id = track_id
        self._sink = sink if sink is not None else {}
        self._phys_read = phys_read
        self.max_laps = max_laps
        self.pulse_steer = pulse_steer
        self.pulse_seconds = pulse_seconds
        self.pulse_gap_seconds = pulse_gap_seconds
        self.pulse_count = pulse_count
        self.pulse_speed_range_kmh = pulse_speed_range_kmh
        self.coast_seconds = coast_seconds
        self.coast_min_kmh = coast_min_kmh
        self.row_interval_s = row_interval_s
        self.min_corner_rows = min_corner_rows

        plane = [(p[0], p[2]) for p in fast_line]
        self._seg = seg_lengths(plane)
        self._straights = find_straights(
            plane, kappa_max=kappa_straight, min_length_m=min_straight_m
        )
        self._sid, self._dist_to_end = _straight_membership(self._straights, self._seg, len(plane))
        # Probe queue. The sweep needs the longest straight; pulses/coast run wherever a straight
        # offers enough remaining room and re-queue if interrupted, so short-straight tracks
        # spread them across several passes.
        self._pending: list[str] = ["accel_sweep", "steer_pulse", "coast"]
        # Per-probe attempt cap: a probe that keeps aborting (straight too short, prep timeout,
        # unusable pull) must not loop forever and starve the completion gate. After the cap it is
        # DROPPED from the schedule; its fit then fails with an interpretable "probe did not
        # complete" detail (#532 rig-found on Spa: the sweep re-queued forever, held the car in
        # 2nd, and the handshake never finished).
        self._probe_attempts: dict[str, int] = {}
        self._max_probe_attempts = 5
        self._active: dict | None = None
        self._pulse_records: list[dict] = []
        self._next_pulse_sign = 1.0
        self._sweep_samples: list[dict] = []
        self._coast_samples: list[dict] = []
        self._rows: list[dict] = []
        self._ratio_samples: dict[int, list[float]] = {}
        self._laps = 0
        self._t_start: float | None = None
        self._prev_heading: tuple[float, float] | None = None
        self._prev_now: float | None = None
        self._prev_car: tuple[float, float] | None = None
        self._gear_prev: int | None = None
        self._gear_since = 0.0
        self._row_acc = {"dpsi": 0.0, "dt": 0.0, "v": 0.0, "steer": 0.0, "n": 0, "t0": None}
        self._speed_hist: list[tuple[float, float]] = []  # (t, v_mps) for smoothed accel
        self.finished = False
        self.result: HandshakeResult | None = None
        self.result_diagnostics: dict = {}

    # -- driver contract ----------------------------------------------------
    def on_recovery(self) -> None:
        self._abort_active("recovery/teleport")
        self._reset_kinematic_state()
        self._base.on_recovery()

    def step(
        self,
        position_xyz: tuple[float, float, float],
        look_dir_xyz: tuple[float, float, float],
        speed_kmh: float,
        rpm: float,
        gear: int,
        now: float,
    ) -> DriveFrame:
        base = self._base.step(position_xyz, look_dir_xyz, speed_kmh, rpm, gear, now)
        if self.finished:
            return base
        if self._t_start is None:
            self._t_start = now
        car = _horizontal(position_xyz)
        if self._prev_car is not None:
            jump = math.hypot(car[0] - self._prev_car[0], car[1] - self._prev_car[1])
            if jump > 30.0:
                self._abort_active("position jump")
                self._reset_kinematic_state()
        self._prev_car = car

        heading = _unit_xz(look_dir_xyz)
        dpsi = 0.0
        dt = 0.0
        if heading is not None and self._prev_heading is not None and self._prev_now is not None:
            dt = now - self._prev_now
            if 0.0 < dt <= 0.2:
                dpsi = _heading_delta(self._prev_heading, heading)
            else:
                dt = 0.0
        if heading is not None:
            self._prev_heading = heading
        self._prev_now = now

        v_mps = max(speed_kmh, 0.0) / 3.6
        self._speed_hist.append((now, v_mps))
        while self._speed_hist and now - self._speed_hist[0][0] > 0.35:
            self._speed_hist.pop(0)

        self._mine_gear_ratio(now, rpm, gear, speed_kmh)
        if base.lap_completed:
            self._laps += 1

        if base.needs_recovery:
            # rig loop answers with a teleport + on_recovery(); abort the active probe here so a
            # half-captured maneuver never contaminates a fit.
            self._abort_active("driver stuck")
            return base

        frame = base
        if self._active is not None:
            frame = self._step_active(base, car, speed_kmh, rpm, gear, v_mps, dpsi, dt, now)
        else:
            if base.phase == PHASE_LAP:
                self._mine_row(now, v_mps, dpsi, dt, base.steer)
                self._maybe_start_probe(car, speed_kmh, now)
                if self._active is not None:
                    frame = self._step_active(base, car, speed_kmh, rpm, gear, v_mps, dpsi, dt, now)

        if not self.finished:
            done_probing = not self._pending and self._active is None
            if (done_probing and len(self._rows) >= self.min_corner_rows) or (
                self._laps >= self.max_laps
            ):
                self._finish(now)
        return frame

    # -- internals ----------------------------------------------------------
    def _reset_kinematic_state(self) -> None:
        self._prev_heading = None
        self._prev_now = None
        self._prev_car = None
        self._speed_hist.clear()
        self._row_acc = {"dpsi": 0.0, "dt": 0.0, "v": 0.0, "steer": 0.0, "n": 0, "t0": None}

    def _abort_active(self, why: str) -> None:
        if self._active is None:
            return
        kind = self._active["kind"]
        self._active = None
        if kind == "steer_pulse" and len(self._pulse_records) >= self.pulse_count:
            return  # already have enough pulses; nothing to re-queue
        # sweep needs the longest straight -> back of the queue; others retry ASAP -> front.
        self._requeue(kind, front=kind != "accel_sweep", failed=True)

    def _requeue(self, kind: str, *, front: bool, failed: bool) -> None:
        """Re-queue a probe unless it is already pending or has exhausted its FAILURE cap.

        ``failed`` counts against the cap; a normal continuation (a pulse that got its record and
        needs another) passes ``failed=False`` so it is not penalized. The cap is the anti-hang:
        a probe a track can't satisfy (no long-enough straight, physics channel absent) is dropped
        after ``_max_probe_attempts`` failures so the schedule completes and the fit reports an
        interpretable "probe did not complete" detail, instead of looping forever (#532)."""
        if failed:
            self._probe_attempts[kind] = self._probe_attempts.get(kind, 0) + 1
        if kind in self._pending:
            return
        if self._probe_attempts.get(kind, 0) >= self._max_probe_attempts:
            return  # dropped: its fit reports "probe did not complete"
        if front:
            self._pending.insert(0, kind)
        else:
            self._pending.append(kind)

    def _read_phys(self):
        if self._phys_read == "auto":  # pragma: no cover - rig-only lazy binding
            self._phys_read = _auto_phys_reader()
        if self._phys_read is None:
            return None
        try:
            return self._phys_read()
        except ValueError:
            return None

    def _mine_gear_ratio(self, now: float, rpm: float, gear: int, speed_kmh: float) -> None:
        if gear != self._gear_prev:
            self._gear_prev = gear
            self._gear_since = now
            return
        if (
            gear >= _FIRST_FORWARD_GEAR
            and now - self._gear_since > 0.5
            and speed_kmh > 15.0
            and rpm > 500.0
            and _finite(rpm, speed_kmh)
        ):
            samples = self._ratio_samples.setdefault(gear, [])
            if len(samples) < 4000:
                samples.append(rpm / speed_kmh)

    def _mine_row(self, now: float, v_mps: float, dpsi: float, dt: float, steer: float) -> None:
        if dt <= 0.0 or v_mps * 3.6 < 15.0:
            return
        acc = self._row_acc
        if acc["t0"] is None:
            acc["t0"] = now
        acc["dpsi"] += dpsi
        acc["dt"] += dt
        acc["v"] += v_mps
        acc["steer"] += steer
        acc["n"] += 1
        if now - acc["t0"] < self.row_interval_s or acc["n"] < 2:
            return
        psi_dot = acc["dpsi"] / acc["dt"] if acc["dt"] > 0 else 0.0
        v = acc["v"] / acc["n"]
        ay_g = v * psi_dot / G
        row = {
            "speed_kmh": v * 3.6,
            "accg_lat": ay_g,
            "steer": acc["steer"] / acc["n"],
        }
        # Only CORNERING rows count toward the steer-FF fit budget, at the SAME lateral-g floor
        # the fitter applies (fit_steer_feedforward min_lat_g=0.3) — otherwise the "enough rows"
        # completion gate can pass on rows the fit then discards.
        if (
            all(_finite(val) for val in row.values())
            and abs(ay_g) >= 0.3
            and len(self._rows) < 20000
        ):
            self._rows.append(row)
        self._row_acc = {"dpsi": 0.0, "dt": 0.0, "v": 0.0, "steer": 0.0, "n": 0, "t0": None}

    def _remaining_on_straight(self, car: tuple[float, float]) -> float:
        idx = self._base.pursuit.nearest_index(car)
        if self._sid[idx] < 0:
            return -1.0
        return self._dist_to_end[idx]

    def _maybe_start_probe(self, car: tuple[float, float], speed_kmh: float, now: float) -> None:
        if not self._pending:
            return
        remaining = self._remaining_on_straight(car)
        if remaining < 0:
            return
        for kind in list(self._pending):
            need = {
                "accel_sweep": max(self._min_sweep_m(), 1.0),
                "steer_pulse": 70.0,
                "coast": max(self.coast_seconds * max(speed_kmh, 40.0) / 3.6 + 25.0, 60.0),
            }[kind]
            if remaining < need:
                continue
            if kind == "coast" and self._read_phys() is None:
                # No physics channel => r_eff can never fit; fail it now with an interpretable
                # message instead of burning straights retrying (the fit reports the cause).
                self._pending.remove(kind)
                continue
            self._pending.remove(kind)
            self._active = {"kind": kind, "stage": "prep", "t_stage": now, "data": {}}
            return

    def _min_sweep_m(self) -> float:
        longest = self._straights[0].length_m if self._straights else 0.0
        # Demand the longest straight (within 10%) so the sweep gets maximum gear coverage,
        # but never more than the track offers.
        return min(220.0, max(0.6 * longest, 120.0))

    def _step_active(
        self,
        base: DriveFrame,
        car: tuple[float, float],
        speed_kmh: float,
        rpm: float,
        gear: int,
        v_mps: float,
        dpsi: float,
        dt: float,
        now: float,
    ) -> DriveFrame:
        assert self._active is not None
        kind = self._active["kind"]
        remaining = self._remaining_on_straight(car)
        if kind == "steer_pulse":
            return self._step_pulse(base, speed_kmh, dpsi, dt, remaining, now)
        if kind == "accel_sweep":
            return self._step_sweep(base, speed_kmh, rpm, gear, v_mps, remaining, now)
        return self._step_coast(base, speed_kmh, v_mps, remaining, now)

    @staticmethod
    def _override(base: DriveFrame, **kw) -> DriveFrame:
        return dc_replace(base, **kw)

    def _step_pulse(
        self,
        base: DriveFrame,
        speed_kmh: float,
        dpsi: float,
        dt: float,
        remaining: float,
        now: float,
    ) -> DriveFrame:
        st = self._active
        lo, hi = self.pulse_speed_range_kmh
        if remaining < 25.0 and st["stage"] != "recover":
            self._abort_active("straight ended mid-pulse")
            return base
        if st["stage"] == "prep":
            if now - st["t_stage"] > 8.0:
                self._abort_active("pulse prep timeout")
                return base
            if speed_kmh > hi:
                return self._override(base, gas=0.0, brake=0.15)
            if speed_kmh < lo:
                return base  # let the base driver bring the speed up
            st["stage"] = "steer"
            st["t_stage"] = now
            st["data"] = {"dpsi": 0.0, "v_sum": 0.0, "n": 0, "sign": self._next_pulse_sign}
        if st["stage"] == "steer":
            d = st["data"]
            if dt > 0.0:
                d["dpsi"] += dpsi
            d["v_sum"] += speed_kmh
            d["n"] += 1
            if now - st["t_stage"] >= self.pulse_seconds:
                self._pulse_records.append(
                    {
                        "steer": d["sign"] * self.pulse_steer,
                        "dpsi_rad": d["dpsi"],
                        "duration_s": now - st["t_stage"],
                        "speed_kmh": d["v_sum"] / max(d["n"], 1),
                    }
                )
                self._next_pulse_sign = -st["data"]["sign"]
                st["stage"] = "recover"
                st["t_stage"] = now
                return base
            return self._override(
                base, steer=d["sign"] * self.pulse_steer, brake=0.0, gas=min(base.gas, 0.5)
            )
        # recover: give Stanley the wheel to settle back onto the line
        if now - st["t_stage"] >= self.pulse_gap_seconds:
            self._active = None
            if len(self._pulse_records) < self.pulse_count:
                self._requeue("steer_pulse", front=True, failed=False)
        return base

    def _step_sweep(
        self,
        base: DriveFrame,
        speed_kmh: float,
        rpm: float,
        gear: int,
        v_mps: float,
        remaining: float,
        now: float,
    ) -> DriveFrame:
        st = self._active
        d = st["data"]
        # Leave braking room: end the pull while the base profile can still slow for the corner at
        # a comfortable ~0.65 g plus margin.
        brake_margin_m = v_mps * v_mps / (2.0 * 6.5) + 25.0
        if st["stage"] == "prep":
            # NO forced downshift / brake-to-entry (that trapped the car in 2nd on Spa, #532): a
            # WOT pull from the CURRENT gear through its natural upshifts gives adjacent-gear
            # coverage for the crossover fit. Start flooring it immediately on a long-enough
            # straight; the gear-ratio miner separately covers low gears.
            if remaining < brake_margin_m + 40.0:
                self._abort_active("sweep straight too short for a WOT pull")
                return base
            st["stage"] = "wot"
            st["t_stage"] = now
            d.update({"rpm_hist": [], "last_shift": now, "start_gear": gear})
        # WOT pull
        if remaining < brake_margin_m:
            self._end_sweep(now)
            return base
        d.setdefault("rpm_hist", []).append((now, rpm, gear))
        d["rpm_hist"] = [(t, r, g) for (t, r, g) in d["rpm_hist"] if now - t <= 0.6]
        accel = self._smoothed_accel()
        if _finite(rpm, speed_kmh, accel) and gear >= _FIRST_FORWARD_GEAR:
            self._sweep_samples.append(
                {"t": now, "gear": gear, "rpm": rpm, "speed_kmh": speed_kmh, "accel_mps2": accel}
            )
        gear_up = False
        same_gear = [(t, r) for (t, r, g) in d["rpm_hist"] if g == gear]
        plateau = (
            len(same_gear) >= 8
            and (same_gear[-1][1] - same_gear[0][1]) < 40.0
            and same_gear[-1][0] - same_gear[0][0] >= 0.45
            and rpm > 3000.0
        )
        if plateau and now - d.get("last_shift", 0.0) > 0.5:
            if gear < self._base.max_gear:
                gear_up = True
                d["last_shift"] = now
                d["upshift_gear"] = gear
                d["upshift_t"] = now
            else:
                self._end_sweep(now)  # already in top gear -> pull is done
                return base
        if (
            d.get("upshift_t") is not None
            and now - d["upshift_t"] > 1.5
            and gear == d.get("upshift_gear")
        ):
            # commanded an upshift but the gear never changed -> out of gears; end the pull
            self._end_sweep(now)
            return base
        return self._override(base, gas=1.0, brake=0.0, gear_up=gear_up, gear_dn=False)

    def _smoothed_accel(self) -> float:
        if len(self._speed_hist) < 2:
            return float("nan")
        (t0, v0), (t1, v1) = self._speed_hist[0], self._speed_hist[-1]
        if t1 - t0 <= 1e-3:
            return float("nan")
        return (v1 - v0) / (t1 - t0)

    def _end_sweep(self, now: float) -> None:
        gears = {s["gear"] for s in self._sweep_samples}
        self._active = None
        if len(gears) < 2:
            # not a usable pull; retry on the next long straight (bounded by the failure cap so a
            # track that never yields a multi-gear pull drops the sweep instead of looping forever)
            self._requeue("accel_sweep", front=False, failed=True)

    def _step_coast(
        self, base: DriveFrame, speed_kmh: float, v_mps: float, remaining: float, now: float
    ) -> DriveFrame:
        st = self._active
        if st["stage"] == "prep":
            if now - st["t_stage"] > 8.0:
                self._abort_active("coast prep timeout")
                return base
            if speed_kmh < self.coast_min_kmh:
                return base  # base accelerates
            st["stage"] = "coast"
            st["t_stage"] = now
        if remaining < 25.0:
            self._abort_active("straight ended mid-coast")
            return base
        phys = self._read_phys()
        if phys is not None and getattr(phys, "wheel_omega", None):
            self._coast_samples.append({"v_mps": v_mps, "omega": tuple(phys.wheel_omega)})
        if now - st["t_stage"] >= self.coast_seconds:
            self._active = None
        return self._override(base, gas=0.0, brake=0.0, gear_up=False, gear_dn=False)

    def _finish(self, now: float) -> None:
        m_sign = fit_ff_sign(self._pulse_records)
        ff_sign = m_sign.value.get("ff_sign") if m_sign.passed else None
        m_ff = fit_steer_ff(self._rows, ff_sign=ff_sign)
        m_ratios = fit_gear_ratios(self._ratio_samples)
        ratios = (
            {int(g): float(r) for g, r in m_ratios.value.get("gear_ratios", {}).items()}
            if m_ratios.passed
            else {}
        )
        m_shift = fit_shift_points(self._sweep_samples, ratios)
        m_reff = fit_r_eff(self._coast_samples)
        measurements = (m_sign, m_ff, m_ratios, m_shift, m_reff)
        self.result = HandshakeResult(
            ok=all(m.passed for m in measurements),
            car_id=self.car_id,
            track_id=self.track_id,
            laps_used=self._laps,
            duration_s=now - (self._t_start if self._t_start is not None else now),
            measurements=measurements,
        )
        # Record which probes never completed within the budget, so a partial finalize (drive
        # ended) is diagnosable — how many pulses/sweep-gears/coast-samples/corner-rows landed.
        self.result_diagnostics = {
            "pulses": len(self._pulse_records),
            "corner_rows": len(self._rows),
            "sweep_samples": len(self._sweep_samples),
            "sweep_gears": sorted({s["gear"] - 1 for s in self._sweep_samples}),
            "coast_samples": len(self._coast_samples),
            "gear_ratio_gears": sorted(self._ratio_samples),
            "probe_attempts": dict(self._probe_attempts),
            "pending_at_finish": list(self._pending),
        }
        self._sink["ok"] = self.result.ok
        self._sink["result"] = self.result.to_dict()
        self._sink["constants"] = self.result.constants()
        self._sink["diagnostics"] = self.result_diagnostics
        self.finished = True

    def finalize(self, now: float | None = None) -> None:
        """Force finalization when the drive ends before the schedule self-completes.

        Without this, a run whose drive budget expires mid-schedule leaves ``sink`` empty and the
        report reads a bare "no result" — hiding which constants WERE measured. Finalizing runs the
        fits over whatever was captured; incomplete probes fail their gates with interpretable
        details (#532 rig-found on Spa)."""
        if self.finished:
            return
        self._finish(now if now is not None else (self._prev_now or 0.0))


def _auto_phys_reader():  # pragma: no cover - rig-only
    """Lazy ``acpmf_physics`` reader for the live handshake (returns ``None``-safe callable)."""
    from tools.ac_harness.racing_telemetry import PHYS_BYTES, parse_physics
    from tools.ac_harness.shared_memory import (
        SHM_PHYSICS,
        SharedMemoryUnavailable,
        open_shared_memory,
    )

    try:
        shm = open_shared_memory(SHM_PHYSICS, PHYS_BYTES)
    except SharedMemoryUnavailable:
        return None

    def read():
        try:
            return parse_physics(shm.read(PHYS_BYTES))
        except (ValueError, SharedMemoryUnavailable):
            return None

    return read


# ---------------------------------------------------------------------------
# Per-combo plant artifact (durable — NEVER .scratch; see module docstring)
# ---------------------------------------------------------------------------
def plant_artifact_path(user_dir: Path, car_id: str, track_id: str) -> Path:
    return Path(user_dir) / "plant_id" / f"{car_id}__{track_id}.json"


def save_plant_artifact(user_dir: Path, result: dict) -> Path:
    """Persist a PASSED handshake result as the combo's plant artifact (atomic write)."""
    if not result.get("ok"):
        raise ValueError("refusing to persist a failed handshake as a plant artifact")
    car_id = str(result.get("car_id") or "")
    track_id = str(result.get("track_id") or "")
    if not car_id or not track_id:
        raise ValueError(f"plant artifact needs car_id and track_id (got {car_id!r}/{track_id!r})")
    from datetime import UTC, datetime

    payload = {
        "schema_version": PLANT_SCHEMA_VERSION,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }
    path = plant_artifact_path(user_dir, car_id, track_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_plant_artifact(user_dir: Path, car_id: str, track_id: str) -> dict | None:
    """Load + validate the combo's plant artifact; ``None`` when absent or invalid."""
    path = plant_artifact_path(user_dir, car_id, track_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != PLANT_SCHEMA_VERSION:
        return None
    if payload.get("car_id") != car_id or payload.get("track_id") != track_id:
        return None
    constants = payload.get("constants")
    if not isinstance(constants, dict) or not constants:
        return None
    for key in ("ff_sign", "ff_c1", "ff_c2", "rpm_up", "rpm_dn", "r_eff_m"):
        val = constants.get(key)
        if val is not None and not _finite(val):
            return None
    return payload


def plant_driver_kwargs(artifact: dict, *, steer: bool) -> dict:
    """RacingDriver kwargs from an artifact's measured constants.

    ``steer=False`` (``--use-plant auto``): shift points only — the lateral controller stays the
    verified-stable Stanley config. ``steer=True`` (``--use-plant full``): also switch to the
    measured curvature-feedforward steering (``ff_sign``/``ff_c1``/``ff_c2``).
    """
    constants = artifact.get("constants", {})
    kwargs: dict = {}
    if _finite(constants.get("rpm_up", float("nan")), constants.get("rpm_dn", float("nan"))):
        kwargs["rpm_up"] = float(constants["rpm_up"])
        kwargs["rpm_dn"] = float(constants["rpm_dn"])
    if steer and all(
        _finite(constants.get(k, float("nan"))) for k in ("ff_sign", "ff_c1", "ff_c2")
    ):
        kwargs["steering_mode"] = "curvature_ff"
        kwargs["ff_sign"] = float(constants["ff_sign"])
        kwargs["ff_c1"] = float(constants["ff_c1"])
        kwargs["ff_c2"] = float(constants["ff_c2"])
    return kwargs


def apply_handshake_outcome(report, sink: dict) -> None:
    """Fold the handshake outcome into an ``AutoDriveReport``-shaped object (duck-typed).

    A run whose handshake produced no result — or a result with failed probes — FAILs at
    ``stage="handshake"`` with the failed probes' interpretable details (#532 hard-abort AC).
    """
    result = sink.get("result")
    if not result:
        report.ok = False
        report.stage = "handshake"
        report.error = (
            "handshake produced no result (drive ended before the probe schedule completed)"
        )
        return
    if not sink.get("ok"):
        failed = [m for m in result.get("measurements", []) if not m.get("passed")]
        passed = [m.get("name") for m in result.get("measurements", []) if m.get("passed")]
        names = ", ".join(m.get("name", "?") for m in failed) or "unknown"
        details = "; ".join(f"{m.get('name')}: {m.get('detail')}" for m in failed)
        diag = sink.get("diagnostics", {})
        report.ok = False
        report.stage = "handshake"
        report.error = (
            f"handshake probe(s) failed: {names} — {details}"
            + (f" | measured: {', '.join(passed)}" if passed else "")
            + (f" | diagnostics: {diag}" if diag else "")
        )
        return
    constants = sink.get("constants", {})
    report.notes.append(
        "handshake ok: "
        + ", ".join(f"{k}={v}" for k, v in sorted(constants.items()) if not isinstance(v, dict))
    )
