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

Artifacts persist per-combo (car + track + optional layout + setup-content identity) under
``<AC user dir>/plant_id/`` — a **durable** Documents path, never ``.scratch`` (the original
``model_id.py`` was lost to exactly that; see issue #532's pitfall list).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import asdict, dataclass
from dataclasses import replace as dc_replace
from pathlib import Path

from tools.ac_harness.ai_line import _horizontal
from tools.ac_harness.ggv_profile import (
    GGVModel,
    blend_ggv_safe,
    fit_steer_feedforward,
    ggv_from_lap_archives,
    ggv_from_telemetry,
    seg_lengths,
    signed_curvature_profile,
)
from tools.ac_harness.lap_driver import PHASE_LAP, DriveFrame
from tools.ac_harness.racing_driver import RacingDriver

G = 9.81
# Schema v3 (#543) makes the optional ``ggv`` block uncertainty- and thermal-state-aware. Schema-v1
# and schema-v2 constants still load, but their absent/point-estimate GGV blocks fall back to the
# generic runtime plant until a new thermally tagged handshake produces a schema-v3 uncertainty map.
PLANT_SCHEMA_VERSION = 3
SUPPORTED_PLANT_SCHEMA_VERSIONS = (1, 2, 3)
# Constants a persisted plant artifact MUST carry (a fully-passed handshake produces all of them);
# a partial artifact is rejected on load so `--use-plant full` never silently degrades.
REQUIRED_PLANT_CONSTANTS = ("ff_sign", "ff_c1", "ff_c2", "rpm_up", "rpm_dn", "r_eff_m")

# AC gear encoding (live-verified, see custom_ai.py): 0=Reverse, 1=Neutral, 2=1st, 3=2nd, ...
_FIRST_FORWARD_GEAR = 2

logger = logging.getLogger(__name__)


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
    layout: str | None = None  # multi-layout track identity (None keeps the legacy artifact key)
    setup: str | None = None  # the setup the plant was measured under (None = default)
    setup_ini: str | None = None  # resolved setup .ini path (for the content-hash key)
    # #532 Part B: the per-combo friction plant (safe-envelope-blended GGVModel + fit provenance),
    # or None when no prior was injected / no friction rows were captured. Additive and ADVISORY —
    # a missing/failed ggv block never gates ``ok`` (consumption falls back to the generic plant),
    # unlike the 5 core constants which hard-abort.
    ggv: dict | None = None

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
            "layout": self.layout,
            "setup": self.setup,
            "setup_ini": self.setup_ini,
            "laps_used": self.laps_used,
            "duration_s": round(self.duration_s, 1),
            "constants": self.constants(),
            "measurements": [asdict(m) for m in self.measurements],
            "ggv": self.ggv,
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
    crossover_rpm_frac: float = 0.6,
    min_crossover_advantage: float = 0.02,
    min_sweep_top_rpm: float = 6000.0,
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

    # A valid crossover sits in the upper part of the observed pull: at least ``crossover_rpm_frac``
    # of the way from the lowest sampled rpm to the observed max. Below that, an equal/near-equal
    # accel overlap is pre-limiter noise, not the shift point (Codex review).
    rpm_min_seen = min((b * rpm_bin for gd in by_gear.values() for b in gd), default=0.0)
    min_crossover_rpm = rpm_min_seen + crossover_rpm_frac * max(0.0, rpm_max - rpm_min_seen)
    quality["min_crossover_rpm"] = round(min_crossover_rpm, 0)

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
            # Reject low-rpm false crossovers (Codex review): a flat/noisy pre-limiter pull can
            # produce an equal/near-equal overlap at low rpm and be mistaken for the shift point,
            # making later GGV runs upshift thousands of rpm early. Require (a) the crossover sits
            # in the upper part of the observed pull (past ~60% of the pull's rpm span from its
            # peak to the limiter), and (b) the next gear holds a REAL accel advantage, not noise.
            if rpm_here < min_crossover_rpm:
                continue
            nb = int((rpm_here * step) // rpm_bin)
            if nb in nxt and nxt[nb] >= cur[b] * (1.0 + min_crossover_advantage):
                crossovers.append(rpm_here)
                break
    if crossovers:
        rpm_up = _median(crossovers)
        method = "accel-crossover"
        quality["crossovers"] = [round(c, 0) for c in crossovers]
    else:
        # Limiter-margin fallback is only trustworthy if the sweep actually revved the engine out.
        # A tall-gear / early-aborted pull that only reached low rpm would otherwise persist a
        # spuriously low rpm_up and make later GGV runs short-shift (Codex review).
        if rpm_max < min_sweep_top_rpm:
            return ProbeMeasurement(
                "shift_points",
                False,
                {},
                quality,
                "limiter-margin",
                f"sweep never revved out (max rpm {rpm_max:.0f} < {min_sweep_top_rpm:.0f}); no "
                "accel-crossover found either — an incomplete pull cannot set a shift point",
            )
        rpm_up = rpm_max * fallback_limiter_frac
        method = "limiter-margin"
        quality["fallback"] = f"{fallback_limiter_frac} * observed max rpm {rpm_max:.0f}"
    # rpm_dn needs an ADJACENT-gear ratio step (b == a+1). A non-adjacent jump (e.g. gears 2 and 4
    # when 3 was missed) is a skipped-gear ratio, not a real shift step (Codex review).
    adj_steps = [
        ratios[b] / ratios[a]
        for a, b in zip(sorted(ratios), sorted(ratios)[1:], strict=False)
        if b == a + 1
    ]
    quality["adjacent_ratio_steps"] = [round(s, 3) for s in adj_steps]
    if not adj_steps or not _finite(rpm_up) or not 3000.0 <= rpm_up <= 12000.0:
        return ProbeMeasurement(
            "shift_points",
            False,
            {},
            quality,
            method,
            f"implausible rpm_up={rpm_up:.0f} (expect 3000..12000) or no ADJACENT gear ratio step "
            f"(observed gears {[g - 1 for g in gears]})",
        )
    steps = adj_steps
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
    completion the result lands in the public ``sink`` dict (keys ``ok``, ``result``,
    ``constants``, ``diagnostics``); ``rig_drive`` copies it into ``DriveStats.payload`` so the
    result flows out through the normal return value, not a config side-channel.
    """

    def __init__(
        self,
        fast_line: list[tuple[float, float, float]],
        speed_profile: list[float],
        *,
        car_id: str = "",
        track_id: str = "",
        layout: str | None = None,
        setup: str | None = None,
        setup_ini: str | None = None,
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
        # #532 Part B — friction ID. ``prior_ggv`` is the trusted generic plant the measured
        # friction envelope is safe-envelope-blended against (injected by the harness so the
        # controller stays import-clean of auto_drive). None => no ggv block is emitted.
        prior_ggv: GGVModel | None = None,
        prior_ggv_name: str = "injected_prior",
        # Active brake-at-speed probe: firm STRAIGHT-LINE braking (never a lateral push — the GT3
        # spins at the lateral limit, live-disproven #259) to trace the high-speed braking envelope.
        brake_level: float = 0.85,
        brake_probe_seconds: float = 2.5,
        brake_min_entry_kmh: float = 110.0,
        brake_min_exit_kmh: float = 45.0,
        brake_min_straight_m: float = 180.0,
        # Passive friction-row capture (speed/accg_lat/accg_lon from the physics accG channel) for
        # the GGV fit — throttled so ~1.5 laps yield a rich, bounded envelope sample.
        # The rig loop updates near 60 Hz. Capture each fresh frame during the bounded controlled
        # probes so a 2.5 s brake pull can populate multiple 10 km/h bins without extending the
        # braking maneuver. Passive rows still face ggv_from_telemetry's stricter 40-row/bin gate.
        friction_row_interval_s: float = 0.01,
        min_friction_rows: int = 200,
    ) -> None:
        self._base = RacingDriver(fast_line, speed_profile, pace=pace, max_speed_kmh=max_speed_kmh)
        self.car_id = car_id
        self.track_id = track_id
        self.layout = layout
        self.setup = setup
        self.setup_ini = setup_ini
        self.sink = sink if sink is not None else {}
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
        self._prior_ggv = prior_ggv
        self._prior_ggv_name = prior_ggv_name or "injected_prior"
        self.brake_level = brake_level
        self.brake_probe_seconds = brake_probe_seconds
        self.brake_min_entry_kmh = brake_min_entry_kmh
        self.brake_min_exit_kmh = brake_min_exit_kmh
        self.brake_min_straight_m = brake_min_straight_m
        self.friction_row_interval_s = friction_row_interval_s
        self.min_friction_rows = min_friction_rows

        plane = [(p[0], p[2]) for p in fast_line]
        self._seg = seg_lengths(plane)
        self._straights = find_straights(
            plane, kappa_max=kappa_straight, min_length_m=min_straight_m
        )
        self._sid, self._dist_to_end = _straight_membership(self._straights, self._seg, len(plane))
        # Probe queue. The sweep needs the longest straight; pulses/coast run wherever a straight
        # offers enough remaining room and re-queue if interrupted, so short-straight tracks
        # spread them across several passes. The active brake-at-speed probe (#532 Part B) is only
        # queued when a prior GGV is present to blend against — otherwise no ggv block is emitted
        # and the probe would burn a straight for nothing.
        self._pending: list[str] = ["accel_sweep", "steer_pulse", "coast"]
        if prior_ggv is not None:
            self._pending.append("brake_probe")
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
        # #532 Part B friction rows: (speed_kmh, accg_lat, accg_lon) sampled from the physics accG
        # channel across the whole drive (corner sequence => lateral, WOT sweep => accel, brake
        # probe => braking envelope). Fed to ggv_from_telemetry at finish.
        self._friction_rows: list[dict] = []
        self._friction_t: float | None = None
        self._friction_packet_id: int | None = None
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

        # #532 Part B: sample the friction envelope from the physics accG channel every driving
        # frame (throttled). Runs across all phases — the corner sequence supplies lateral rows, the
        # WOT sweep accel rows, and the brake probe the braking envelope.
        self._mine_friction(now)

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
        # A mid-WOT abort (recovery / position jump / driver-stuck) is a SECOND sweep-failure path
        # besides _end_sweep: discard this attempt's partial samples too, or a later retry could
        # fit shift points from non-contiguous pulls (Codex review).
        if kind == "accel_sweep":
            start = self._active.get("data", {}).get("samples_start")
            if start is not None:
                del self._sweep_samples[start:]
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

    def set_phys_read(self, fn) -> None:
        """Inject the physics-frame reader the harness owns (must expose ``wheel_omega``).

        The controller does NOT open OS shared memory itself — that would break controller purity
        and leak the mmap with no lifecycle to close it (daemon review). The rig loop, which
        already maps ``acpmf_physics`` and owns its close, provides this callable; off-rig tests
        pass a fake (or ``None`` to exercise the missing-channel path)."""
        self._phys_read = fn

    def _read_phys(self):
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

    def _mine_friction(self, now: float) -> None:
        """Sample one friction row (speed_kmh, accg_lat, accg_lon) from the physics accG channel.

        Throttled to ``friction_row_interval_s``. Reads the harness-owned physics frame (the same
        reader the r_eff coast probe uses) — the accG channel carries the REAL measured lateral and
        longitudinal accelerations that :func:`ggv_from_telemetry` de-contaminates and fits. A
        missing physics reader (off-rig with no fake) simply yields no rows -> no ggv block, which
        the consumer treats as "no per-combo plant" and falls back to the generic plant.
        """
        if self._prior_ggv is None:
            return  # no prior to blend against => no ggv block => nothing to capture
        if self._friction_t is not None and now - self._friction_t < self.friction_row_interval_s:
            return
        phys = self._read_phys()
        if phys is None:
            return
        speed = getattr(phys, "speed_kmh", None)
        ay = getattr(phys, "accg_lat", None)
        ao = getattr(phys, "accg_lon", None)
        if speed is None or ay is None or ao is None:
            return
        if not _finite(speed, ay, ao) or speed < 15.0:
            return
        # The controller can run faster than AC's physics mmap refresh. Do not count one mmap
        # packet several times merely because the harness clock advanced: duplicated frames would
        # fabricate the per-bin support that makes a fitted friction envelope runtime-bearing.
        packet_id = getattr(phys, "packet_id", None)
        if isinstance(packet_id, int) and not isinstance(packet_id, bool):
            if packet_id == self._friction_packet_id:
                return
            self._friction_packet_id = packet_id
        self._friction_t = now
        if len(self._friction_rows) < 60000:
            source = "passive"
            if self._active is not None:
                kind = self._active.get("kind")
                stage = self._active.get("stage")
                if kind == "brake_probe" and stage == "brake":
                    source = "brake_probe"
                elif kind == "accel_sweep" and stage == "wot":
                    source = "accel_sweep"
            self._friction_rows.append(
                {
                    "speed_kmh": float(speed),
                    "accg_lat": float(ay),
                    "accg_lon": float(ao),
                    "source": source,
                    # The archive writes state.lapsCompleted at the crossing, so samples gathered
                    # during this zero-based controller lap map to archive lap_n = lap_index + 1.
                    "lap_index": self._laps,
                }
            )

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
                "brake_probe": self.brake_min_straight_m,
            }[kind]
            if remaining < need:
                continue
            if kind in ("coast", "brake_probe") and self._read_phys() is None:
                # No physics channel => the coast r_eff fit / the brake-probe friction rows can
                # never land; drop the probe now (its fit / the ggv block simply reports the cause)
                # instead of burning straights retrying it.
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
        if kind == "brake_probe":
            return self._step_brake(base, speed_kmh, remaining, now)
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
            # Remember where THIS attempt's samples begin, so a failed pull (<2 gears) can discard
            # exactly its own samples and not let two disjoint single-gear pulls masquerade as one
            # continuous multi-gear sweep (Codex review).
            d.update(
                {
                    "rpm_hist": [],
                    "last_shift": now,
                    "start_gear": gear,
                    "samples_start": len(self._sweep_samples),
                }
            )
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
        # Judge THIS attempt only (from where its samples began), not the cumulative set: two
        # disjoint single-gear pulls must not combine into a fake multi-gear sweep (Codex review).
        start = (self._active or {}).get("data", {}).get("samples_start", 0)
        attempt = self._sweep_samples[start:]
        gears = {s["gear"] for s in attempt}
        self._active = None
        if len(gears) < 2:
            # Not a usable pull: DISCARD this attempt's samples so they can't pollute a later one,
            # then retry on the next long straight (bounded by the failure cap so a track that
            # never yields a multi-gear pull drops the sweep instead of looping forever).
            del self._sweep_samples[start:]
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

    def _step_brake(
        self, base: DriveFrame, speed_kmh: float, remaining: float, now: float
    ) -> DriveFrame:
        """Active brake-at-speed probe: firm STRAIGHT-LINE braking to trace the braking envelope.

        Straight-line only — steering follows the base line, never a lateral push (pushing to the
        lateral limit spins the GT3, live-disproven #259). The friction-row sampler captures the
        resulting high ``-accg_lon`` across the pull; this probe only COMMANDS the braking. Bounded
        by a time window, a speed floor, and the straight's remaining length so the car is always
        slowed and settled before the corner (never brakes into a turn).
        """
        st = self._active
        assert st is not None
        if st["stage"] == "prep":
            # Wait until fast enough to trace the HIGH-speed braking envelope; let the base driver
            # keep accelerating. Reserve enough distance to brake from the eventual entry speed to
            # the safety floor at a conservative 0.5 g, plus 30 m to settle before the corner.
            entry_kmh = max(speed_kmh, self.brake_min_entry_kmh)
            if now - st["t_stage"] > 8.0 or remaining < self._brake_probe_required_m(entry_kmh):
                self._abort_active(
                    "brake-probe prep: straight too short or entry speed not reached"
                )
                return base
            if speed_kmh < self.brake_min_entry_kmh:
                return base  # base accelerates toward the entry speed
            st["stage"] = "brake"
            st["t_stage"] = now
            st["data"]["entry_kmh"] = round(speed_kmh, 1)
        # Braking phase: stop when the window elapses, speed reaches the floor, or the straight is
        # running out (leave room to settle before the corner). Ending sets active=None; the base
        # driver resumes on the next step.
        if (
            now - st["t_stage"] >= self.brake_probe_seconds
            or speed_kmh <= self.brake_min_exit_kmh
            or remaining < 30.0
        ):
            st["data"]["exit_kmh"] = round(speed_kmh, 1)
            self._active = None
            return base
        return self._override(base, gas=0.0, brake=self.brake_level, gear_up=False, gear_dn=False)

    def _brake_probe_required_m(self, entry_kmh: float) -> float:
        """Conservative stopping distance from probe entry to the configured safety floor."""
        entry_mps = max(0.0, entry_kmh) / 3.6
        exit_mps = max(0.0, self.brake_min_exit_kmh) / 3.6
        braking_m = max(0.0, entry_mps * entry_mps - exit_mps * exit_mps) / (2.0 * 0.5 * G)
        return braking_m + 30.0

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
        ggv_block = self._build_ggv_block()
        self.result = HandshakeResult(
            ok=all(m.passed for m in measurements),
            car_id=self.car_id,
            track_id=self.track_id,
            layout=self.layout,
            setup=self.setup,
            setup_ini=str(self.setup_ini) if self.setup_ini else None,
            laps_used=self._laps,
            duration_s=now - (self._t_start if self._t_start is not None else now),
            measurements=measurements,
            ggv=ggv_block,
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
            "friction_rows": len(self._friction_rows),
            "ggv_ok": bool(ggv_block and ggv_block.get("ok")),
            "probe_attempts": dict(self._probe_attempts),
            "pending_at_finish": list(self._pending),
        }
        self.sink["ok"] = self.result.ok
        self.sink["result"] = self.result.to_dict()
        self.sink["constants"] = self.result.constants()
        self.sink["diagnostics"] = self.result_diagnostics
        self.finished = True

    def _build_ggv_block(self) -> dict | None:
        """Build a provisional point fit pending the thermally tagged lap archive (#543).

        Live physics rows do not contain the canonical #488 tyre channels, so even a successful
        point fit is diagnostics-only. The block remains ``ok=False`` until
        :func:`refine_ggv_from_lap_archives` observes the immutable archive and builds the thermal,
        per-speed-bin uncertainty map. This is advisory and never gates the core handshake
        constants.
        """
        if self._prior_ggv is None:
            return None
        n = len(self._friction_rows)
        block: dict = {
            "ok": False,
            "friction_rows": n,
            "model": None,
            "prior": self._prior_ggv_name,
            # Preserve explicit probe evidence before the overall point-fit gate. A fresh thermal
            # archive can supply the passive row volume while these rows retain the only trustworthy
            # brake/WOT limit tags.
            "provisional_probe_rows": [
                dict(row) for row in self._friction_rows if row.get("source") != "passive"
            ],
        }
        if n < self.min_friction_rows:
            block["reason"] = f"insufficient friction rows: {n} < {self.min_friction_rows}"
            return block
        try:
            measured = ggv_from_telemetry(self._friction_rows)
            blended = blend_ggv_safe(measured, self._prior_ggv, prior_name=self._prior_ggv_name)
        except (ValueError, ZeroDivisionError, KeyError, TypeError) as exc:
            # Narrow catch + log (never a broad catch-and-default). The failure is ADVISORY: the
            # consumer falls back to the generic plant, but the reason is recorded, not swallowed.
            logger.exception("friction-ID fit failed; ggv block degrades to the generic plant")
            block["reason"] = f"friction fit error: {type(exc).__name__}: {exc}"
            return block
        # The live rows have no tyre-state channels. Keep the point fit for diagnostics only;
        # refine_ggv_from_lap_archives replaces it after the immutable #488 archive is observed.
        block["provisional_model"] = blended.to_dict()
        # Ephemeral handoff only: refinement consumes these explicitly tagged live probe rows and
        # replaces the whole block before evidence/persistence. The lap archive proves the thermal
        # state; these tags prove which longitudinal samples were actually limit-reaching probes.
        block["reason"] = "awaiting thermally tagged lap archive"
        return block

    def finalize(self, now: float | None = None) -> None:
        """Force finalization when the drive ends before the schedule self-completes.

        Without this, a run whose drive budget expires mid-schedule leaves ``sink`` empty and the
        report reads a bare "no result" — hiding which constants WERE measured. Finalizing runs the
        fits over whatever was captured; incomplete probes fail their gates with interpretable
        details (#532 rig-found on Spa)."""
        if self.finished:
            return
        self._finish(now if now is not None else (self._prev_now or 0.0))


# ---------------------------------------------------------------------------
# Per-combo plant artifact (durable — NEVER .scratch; see module docstring)
# ---------------------------------------------------------------------------
def refine_ggv_from_lap_archives(
    result: dict,
    archives: list[str | Path | dict],
    prior: GGVModel,
    *,
    prior_name: str = "generic_gt3_ggv",
) -> dict:
    """Replace a handshake's provisional GGV with a thermally gated schema-v3 model.

    ``archives`` may contain paths from ``auto_drive.collect_lap_archives`` or already-loaded dicts
    for hermetic tests. The result is mutated and returned so evidence and persistence consume the
    same final block.
    """
    if "ggv" not in result or not isinstance(result.get("ggv"), dict):
        # No prior was injected into HandshakeController, so friction ID was explicitly disabled.
        # Thermal archives must not resurrect an unrequested GGV block.
        return {
            "ok": False,
            "skipped": True,
            "reason": "friction identification was not requested",
        }
    loaded: list[dict] = []
    load_errors: list[str] = []
    for item in archives:
        if isinstance(item, dict):
            loaded.append(item)
            continue
        try:
            payload = json.loads(Path(item).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            load_errors.append(f"{item}: {type(exc).__name__}")
            continue
        if isinstance(payload, dict):
            loaded.append(payload)
        else:
            load_errors.append(f"{item}: archive root is not an object")
    expected_car = str(result.get("car_id") or "")
    expected_track = str(result.get("track_id") or "")
    expected_layout = result.get("layout") or None
    matching: list[dict] = []
    identity_notes: list[str] = []
    for payload in loaded:
        car = payload.get("car") if isinstance(payload.get("car"), dict) else {}
        track = payload.get("track") if isinstance(payload.get("track"), dict) else {}
        actual_car = str(car.get("id") or "")
        actual_track = str(track.get("id") or "")
        actual_layout = track.get("layout") or None
        if (
            actual_car != expected_car
            or actual_track != expected_track
            or (actual_layout is not None and actual_layout != expected_layout)
        ):
            load_errors.append(
                "archive identity mismatch: "
                f"expected {expected_car}/{expected_track}/{expected_layout or '-'}, "
                f"got {actual_car}/{actual_track}/{actual_layout or '-'}"
            )
            continue
        if expected_layout is not None and actual_layout is None:
            # The current in-game archive schema does not serialize layout. These paths are
            # restricted to archives written after this run started, while car+track still match;
            # preserve the missing-layout fact rather than rejecting every multi-layout handshake.
            identity_notes.append(
                f"archive {payload.get('lap_uuid') or '?'} omitted layout; "
                f"accepted current-run {expected_layout!r} context"
            )
        matching.append(payload)
    previous_ggv = result.get("ggv") if isinstance(result.get("ggv"), dict) else {}
    probe_rows = previous_ggv.get("provisional_probe_rows", [])
    if not isinstance(probe_rows, list):
        probe_rows = []
    block: dict = {
        "ok": False,
        "model": None,
        "prior": prior_name,
        "lap_archives_seen": len(archives),
        "lap_archives_loaded": len(matching),
        "load_errors": load_errors,
        "identity_notes": identity_notes,
        "provisional_reason": previous_ggv.get("reason"),
    }
    try:
        model, summary = ggv_from_lap_archives(
            matching, prior, prior_name=prior_name, probe_rows=probe_rows
        )
    except (ValueError, ZeroDivisionError, KeyError, TypeError) as exc:
        logger.exception("thermal uncertainty fit failed; ggv block degrades to the generic plant")
        block["reason"] = f"thermal uncertainty fit error: {type(exc).__name__}: {exc}"
        result["ggv"] = block
        return block
    block.update(summary)
    block["ok"] = True
    block["model"] = model.to_dict()
    block["reason"] = "ok"
    result["ggv"] = block
    return block


def _setup_stem(setup: str | None) -> str | None:
    """The setup basename without ``.ini`` (or None), for a path-free identity sanity-check."""
    if not setup:
        return None
    return re.sub(r"\.ini$", "", str(setup).replace("\\", "/").rsplit("/", 1)[-1])


def _setup_content_hash(setup_ini: str | Path | None) -> str:
    """First 8 hex of the SHA-256 of the setup INI content, or "" when unreadable."""
    if not setup_ini:
        return ""
    try:
        return hashlib.sha256(Path(setup_ini).read_bytes()).hexdigest()[:8]
    except OSError:
        return ""


def _setup_key(setup: str | None, setup_ini: str | Path | None = None) -> str:
    """Filename-safe suffix identifying the setup a plant was measured under (empty = default).

    A car SETUP changes gear ratios / final drive / response, so a plant measured on the default
    setup must NOT be reused for a different-setup run (Codex review). Keyed by the setup basename
    PLUS a content hash of the resolved ``.ini`` when available, so two different files sharing a
    basename (``spa/Foo.ini`` vs ``generic/Foo.ini``, or an edited ``Foo.ini``) never collide:
    ``<car>__<track>`` (default) vs ``<car>__<track>__setup-<stem>[-<sha8>]``.
    """
    if not setup:
        return ""
    stem = re.sub(r"\.ini$", "", str(setup).replace("\\", "/").rsplit("/", 1)[-1])
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", stem)
    if not safe:
        return ""
    digest = _setup_content_hash(setup_ini)
    return f"__setup-{safe}-{digest}" if digest else f"__setup-{safe}"


def _layout_key(layout: str | None) -> str:
    """Filename-safe layout suffix (empty only for the legacy single-layout identity).

    Layout ids are AC folder basenames. Reject path-shaped values rather than normalizing them into
    a collision (for example ``gp/short`` and ``gp_short``); CLI callers already apply the same
    plain-id rule through ``validate_ac_id``.
    """
    if layout is None:
        return ""
    if (
        not isinstance(layout, str)
        or not layout
        or ".." in layout
        or re.fullmatch(r"[A-Za-z0-9._-]+", layout) is None
    ):
        raise ValueError(f"unsafe track layout id {layout!r} (allowed: letters/digits/._-)")
    return f"__layout-{layout}"


def plant_artifact_path(
    user_dir: Path,
    car_id: str,
    track_id: str,
    setup: str | None = None,
    setup_ini: str | Path | None = None,
    *,
    layout: str | None = None,
) -> Path:
    filename = f"{car_id}__{track_id}{_layout_key(layout)}{_setup_key(setup, setup_ini)}.json"
    return Path(user_dir) / "plant_id" / filename


def save_plant_artifact(user_dir: Path, result: dict) -> Path:
    """Persist a PASSED handshake result as the combo's plant artifact (atomic write).

    The artifact is keyed by car+track+layout+setup. ``layout=None`` keeps the exact legacy
    car+track+setup filename so existing single-layout artifacts remain loadable.
    """
    if not result.get("ok"):
        raise ValueError("refusing to persist a failed handshake as a plant artifact")
    ggv = result.get("ggv")
    if isinstance(ggv, dict) and ggv.get("ok"):
        model_data = ggv.get("model")
        model = GGVModel.from_dict(model_data) if isinstance(model_data, dict) else None
        if model is None or not model.uncertainty_aware:
            raise ValueError(
                "refusing to persist an ok schema-v3 ggv block without uncertainty bins"
            )
    car_id = str(result.get("car_id") or "")
    track_id = str(result.get("track_id") or "")
    if not car_id or not track_id:
        raise ValueError(f"plant artifact needs car_id and track_id (got {car_id!r}/{track_id!r})")
    setup = result.get("setup")
    setup_ini = result.get("setup_ini")
    layout = result.get("layout")
    from datetime import UTC, datetime

    payload = {
        "schema_version": PLANT_SCHEMA_VERSION,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **result,
    }
    path = plant_artifact_path(user_dir, car_id, track_id, setup, setup_ini, layout=layout)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_plant_artifact(
    user_dir: Path,
    car_id: str,
    track_id: str,
    setup: str | None = None,
    setup_ini: str | Path | None = None,
    *,
    layout: str | None = None,
) -> dict | None:
    """Load + validate the combo's plant artifact; ``None`` when absent or invalid.

    ``layout`` and ``setup`` (+ the resolved ``setup_ini`` content hash) are part of the combo
    identity. A request for one layout can never reuse a plant measured on another layout.
    """
    try:
        path = plant_artifact_path(user_dir, car_id, track_id, setup, setup_ini, layout=layout)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") not in SUPPORTED_PLANT_SCHEMA_VERSIONS
    ):
        return None
    if payload.get("car_id") != car_id or payload.get("track_id") != track_id:
        return None
    # The filename prevents normal cross-layout lookup; the payload check also rejects a copied or
    # renamed artifact whose stored physical-course identity does not match the requested layout.
    # Missing layout in v1/v2 artifacts is equivalent to None, preserving single-layout back-compat.
    if payload.get("layout") != layout:
        return None
    # Setup identity (name + content hash) is ALREADY enforced by the filename we opened
    # (`plant_artifact_path(..., setup, setup_ini)` built from the REQUEST's readable setup_ini).
    # Do NOT re-derive it from the stored payload's absolute setup_ini path — that path is the
    # creator's and is unreadable on another machine, which would reject a content-matched artifact
    # and break portability (daemon HIGH). A cheap stem sanity-check guards a corrupted/renamed
    # file without re-reading any path.
    if _setup_stem(payload.get("setup")) != _setup_stem(setup):
        return None
    constants = payload.get("constants")
    if not isinstance(constants, dict) or not constants:
        return None
    # A persisted artifact only exists when the handshake FULLY passed, so every consumed constant
    # MUST be present and finite. A partial artifact (missing e.g. ff_c1) would otherwise be
    # accepted and let `--use-plant full` silently drive on generic steering (Codex review) — the
    # exact hand-constant fallback the handshake exists to end. Reject it, don't degrade.
    for key in REQUIRED_PLANT_CONSTANTS:
        val = constants.get(key)
        if val is None or not _finite(val):
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
    if steer:
        # `--use-plant full` is a HARD requirement for measured steering: if the steering
        # constants are absent/non-finite, RAISE rather than silently return without them (which
        # would let the ggv driver fall back to generic steering — the exact degrade `full`
        # forbids). `load_plant_artifact` already guarantees these for a valid artifact.
        if not all(_finite(constants.get(k, float("nan"))) for k in ("ff_sign", "ff_c1", "ff_c2")):
            raise ValueError(
                "plant artifact missing measured steering constants (ff_sign/ff_c1/ff_c2); "
                "--use-plant full requires a complete artifact — re-run --driver handshake"
            )
        kwargs["steering_mode"] = "curvature_ff"
        kwargs["ff_sign"] = float(constants["ff_sign"])
        kwargs["ff_c1"] = float(constants["ff_c1"])
        kwargs["ff_c2"] = float(constants["ff_c2"])
    return kwargs


def plant_ggv_model(artifact: dict) -> GGVModel | None:
    """The per-combo friction plant (a :class:`GGVModel`) from an artifact's ggv block, or ``None``.

    Returns ``None`` when the artifact carries no usable ggv block — a v1 / Part-A artifact, or a
    run where the friction fit degraded (``ok=False``) — so the caller keeps the generic plant. A
    malformed / non-finite serialized model is rejected (``GGVModel.from_dict`` raises), so the
    ggv driver never builds a speed profile from a ``nan`` grip curve (#532 Part B input check).
    """
    ggv = artifact.get("ggv")
    if not isinstance(ggv, dict) or not ggv.get("ok"):
        return None
    model = ggv.get("model")
    if not isinstance(model, dict):
        return None
    try:
        restored = GGVModel.from_dict(model)
        # Schema-v1/v2 point estimates remain readable for provenance and their measured constants,
        # but #543 requires runtime friction to carry epistemic uncertainty. Until re-identified,
        # the caller keeps the generic plant rather than acting on false precision.
        return restored if restored.uncertainty_aware else None
    except (ValueError, TypeError):
        logger.warning(
            "plant artifact ggv block present but its model is invalid; using the generic plant"
        )
        return None


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
