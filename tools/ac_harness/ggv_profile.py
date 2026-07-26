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

import copy
import csv
import hashlib
import json
import math
import statistics
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

from tools.ac_harness.ai_line import StanleySteering, _horizontal

# fast_lane.ai binary layout (AiLine header + AiPoint blocks + AiPointExtra)
_FAST_LANE_HEADER_BYTES = 16  # 4 * int32: version, count, lap, samp
_FAST_LANE_MIN_BYTES = 20
_AI_POINT_STRIDE_BYTES = 20
_LAP_EXTRA_BYTES = 4
_AI_EXTRA_STRIDE_BYTES = 72
_AI_EXTRA_SIDELEFT_OFFSET_BYTES = 20

G = 9.81
MIN_LONGITUDINAL_SUPPORT_KMH = 40.0
MAX_LONGITUDINAL_SUPPORT_KMH = 300.0
MAX_DRIVE_SUPPORT_G = 2.0
MAX_PERSISTED_AY_CAP_G = 1.8
MAX_PERSISTED_BRAKE_CAP_G = 3.4
UNCERTAINTY_CHANNELS = ("lateral", "brake", "drive")
DEFAULT_UNCERTAINTY_BIN_KMH = 10.0
DEFAULT_UNCERTAINTY_MAX_KMH = 300.0
DEFAULT_UNCERTAINTY_LCB_Z = 1.96
DEFAULT_PRIOR_RELATIVE_STD = 0.15
DEFAULT_THERMAL_WINDOW_HALF_WIDTH_C = 10.0
DEFAULT_THERMAL_COVERAGE_FRACTION = 0.80
DEFAULT_THERMAL_STABILITY_FRACTION = 0.80
DEFAULT_THERMAL_STABILITY_HALF_WIDTH_C = 5.0
DEFAULT_THERMAL_MAX_WHEEL_SPREAD_C = 15.0
_WHEELS = ("fl", "fr", "rl", "rr")


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
    # Runtime-bearing measured overrides are deliberately separate from free-form provenance and
    # validated on every construction/load. Top-level coefficients remain the trusted prior.
    supported_longitudinal: Mapping = field(default_factory=dict)
    # Schema-v3 (#543): validated, runtime-bearing per-speed-bin posterior summaries. Each
    # channel carries mean, epistemic standard deviation, lower-confidence safe value, sample
    # count, and measured-vs-prior provenance. Empty means a legacy point-estimate model.
    uncertainty_bins: tuple[Mapping, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _validate_supported_longitudinal(
            self.supported_longitudinal,
            brake_b0_g=self.brake_b0_g,
            brake_b1=self.brake_b1,
            drive_b0_g=self.drive_b0_g,
            drive_b1=self.drive_b1,
            ax_brake_cap_g=self.ax_brake_cap_g,
        )
        _validate_uncertainty_bins(self.uncertainty_bins)
        # ``frozen=True`` does not freeze nested dicts. Detach observability provenance from its
        # caller and make the runtime-bearing support schema recursively read-only after validation.
        object.__setattr__(self, "provenance", copy.deepcopy(self.provenance))
        object.__setattr__(
            self,
            "supported_longitudinal",
            _freeze_supported_longitudinal(self.supported_longitudinal),
        )
        object.__setattr__(
            self, "uncertainty_bins", _freeze_uncertainty_bins(self.uncertainty_bins)
        )

    def ay_max(self, v_ms: float) -> float:
        point_g = min(self.ay_cap_g, self.mu_lat_g + self.k_aero_lat * v_ms * v_ms)
        return self._uncertainty_safe_g("lateral", v_ms, point_g) * G

    def ax_brake_max(self, v_ms: float) -> float:
        prior_g = max(0.5, self.brake_b0_g + self.brake_b1 * v_ms)
        supported_g = self._supported_longitudinal_g("brake", v_ms, prior_g, floor_g=0.5)
        point_g = min(self.ax_brake_cap_g, supported_g)
        return self._uncertainty_safe_g("brake", v_ms, point_g) * G

    def ax_drive_max(self, v_ms: float) -> float:
        prior_g = max(self.drive_min_g, self.drive_b0_g + self.drive_b1 * v_ms)
        supported_g = self._supported_longitudinal_g(
            "drive", v_ms, prior_g, floor_g=self.drive_min_g
        )
        return self._uncertainty_safe_g("drive", v_ms, supported_g) * G

    @property
    def uncertainty_aware(self) -> bool:
        """Whether this model carries the schema-v3 runtime uncertainty map."""
        return bool(self.uncertainty_bins)

    def _uncertainty_safe_g(self, kind: str, v_ms: float, point_g: float) -> float:
        """Return the lower-confidence grip for ``kind`` at speed, never above the point model.

        The point model remains the upper operating envelope. The uncertainty layer can only derate
        it. A missing or non-covering map is a legacy model and preserves the pre-v3 behavior.
        """
        speed_kmh = max(0.0, float(v_ms) * 3.6)
        for speed_bin in self.uncertainty_bins:
            if float(speed_bin["speed_min_kmh"]) <= speed_kmh < float(speed_bin["speed_max_kmh"]):
                channel = speed_bin[kind]
                return min(point_g, float(channel["safe_g"]))
        if self.uncertainty_bins and speed_kmh >= float(self.uncertainty_bins[-1]["speed_max_kmh"]):
            # Never fall back to the optimistic point model above the map. Carry the last safe
            # bound flat; that is conservative extrapolation, not an upward grip claim.
            return min(point_g, float(self.uncertainty_bins[-1][kind]["safe_g"]))
        return point_g

    def _supported_longitudinal_g(
        self, kind: str, v_ms: float, prior_g: float, *, floor_g: float
    ) -> float:
        """Apply a measured longitudinal envelope only inside its observed speed support.

        ``blend_ggv_safe`` deliberately keeps the trusted prior in the model's top-level
        coefficients.  A measured longitudinal curve is stored as an additive, provenance-backed
        override and tapers to the prior at both edges of the observed range. Braking evidence may
        safely raise or lower the envelope; drive evidence only raises it. Consequently an old
        consumer that ignores provenance remains conservative, while this consumer can learn where
        the handshake actually measured without extrapolating a low-speed fit to 240 km/h.

        Persisted provenance is untrusted input.  Any malformed/non-finite override is ignored and
        the prior is returned, matching the artifact loader's fail-safe contract.
        """
        override = self.supported_longitudinal.get(kind)
        if not isinstance(override, Mapping):
            return prior_g
        try:
            lo_kmh = float(override["speed_min_kmh"])
            hi_kmh = float(override["speed_max_kmh"])
            b0_g = float(override["b0_g"])
            b1 = float(override["b1"])
            measured_floor_g = float(override.get("floor_g", floor_g))
            taper_kmh = float(override.get("taper_kmh", 10.0))
        except (KeyError, TypeError, ValueError):
            return prior_g
        if not _finite_ggv(lo_kmh, hi_kmh, b0_g, b1, measured_floor_g, taper_kmh):
            return prior_g
        if lo_kmh < 0.0 or hi_kmh <= lo_kmh or measured_floor_g < 0.0 or taper_kmh <= 0.0:
            return prior_g
        speed_kmh = v_ms * 3.6
        if speed_kmh <= lo_kmh or speed_kmh >= hi_kmh:
            return prior_g
        measured_g = max(measured_floor_g, b0_g + b1 * v_ms)
        if kind != "brake" and measured_g <= prior_g:
            return prior_g
        taper_kmh = min(taper_kmh, (hi_kmh - lo_kmh) / 2.0)
        weight = min(
            1.0,
            (speed_kmh - lo_kmh) / taper_kmh,
            (hi_kmh - speed_kmh) / taper_kmh,
        )
        return prior_g + weight * (measured_g - prior_g)

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

    def to_dict(self) -> dict:
        """Serialize the model + provenance for a plant artifact (JSON-safe; #532 Part B)."""
        return {
            "mu_lat_g": self.mu_lat_g,
            "k_aero_lat": self.k_aero_lat,
            "brake_b0_g": self.brake_b0_g,
            "brake_b1": self.brake_b1,
            "drive_b0_g": self.drive_b0_g,
            "drive_b1": self.drive_b1,
            "drive_min_g": self.drive_min_g,
            "ellipse_n": self.ellipse_n,
            "ay_cap_g": self.ay_cap_g,
            "ax_brake_cap_g": self.ax_brake_cap_g,
            "provenance": copy.deepcopy(self.provenance),
            "supported_longitudinal": {
                kind: dict(override) for kind, override in self.supported_longitudinal.items()
            },
            "uncertainty_bins": [
                {
                    "speed_min_kmh": float(speed_bin["speed_min_kmh"]),
                    "speed_max_kmh": float(speed_bin["speed_max_kmh"]),
                    **{kind: dict(speed_bin[kind]) for kind in UNCERTAINTY_CHANNELS},
                }
                for speed_bin in self.uncertainty_bins
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> GGVModel:
        """Rebuild a model from :meth:`to_dict` output.

        Raises ``ValueError`` on a missing / non-finite CORE field so a corrupt plant artifact can
        never silently construct a ``nan`` grip curve that the driver would then act on (#532
        input-validation pitfall). Optional caps default to the dataclass defaults when absent.
        """
        if not isinstance(data, dict):
            raise ValueError(f"GGVModel.from_dict expects a dict, got {type(data).__name__}")
        core = (
            "mu_lat_g",
            "k_aero_lat",
            "brake_b0_g",
            "brake_b1",
            "drive_b0_g",
            "drive_b1",
            "drive_min_g",
            "ellipse_n",
        )
        vals: dict = {}
        for f in core:
            v = data.get(f)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise ValueError(f"GGVModel.from_dict: field {f!r} missing or non-finite: {v!r}")
            vals[f] = float(v)
        for f in ("ay_cap_g", "ax_brake_cap_g"):
            v = data.get(f)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
                vals[f] = float(v)
        # Positivity/range gates (Codex P2): the friction-ellipse math divides by ``ellipse_n``
        # (``**(1/n)``), so a non-positive exponent would CRASH the ggv path instead of falling back
        # to the generic plant; a non-positive lateral grip / cap would zero the envelope. Reject
        # both — never construct a model the driver cannot safely evaluate.
        if not (0.0 < vals["ellipse_n"] <= 8.0):
            raise ValueError(
                f"GGVModel.from_dict: ellipse_n out of range (0, 8]: {vals['ellipse_n']!r}"
            )
        if vals["mu_lat_g"] <= 0.0:
            raise ValueError(f"GGVModel.from_dict: mu_lat_g must be positive: {vals['mu_lat_g']!r}")
        if vals["k_aero_lat"] != 0.0:
            raise ValueError(
                "GGVModel.from_dict: persisted plant k_aero_lat must be zero: "
                f"{vals['k_aero_lat']!r}"
            )
        if vals["drive_min_g"] < 0.0:
            raise ValueError(
                f"GGVModel.from_dict: drive_min_g must be non-negative: {vals['drive_min_g']!r}"
            )
        cap_limits = {
            "ay_cap_g": MAX_PERSISTED_AY_CAP_G,
            "ax_brake_cap_g": MAX_PERSISTED_BRAKE_CAP_G,
        }
        for f, limit in cap_limits.items():
            if f in vals and not (0.0 < vals[f] <= limit):
                raise ValueError(f"GGVModel.from_dict: {f} must be in (0, {limit}]: {vals[f]!r}")
        prov = data.get("provenance")
        supported = data.get("supported_longitudinal", {})
        uncertainty_bins = data.get("uncertainty_bins", ())
        if uncertainty_bins is None:
            raise ValueError("GGVModel.from_dict: uncertainty_bins must be a list or tuple")
        return cls(
            **vals,
            provenance=copy.deepcopy(prov) if isinstance(prov, dict) else {},
            supported_longitudinal=copy.deepcopy(supported),
            uncertainty_bins=tuple(copy.deepcopy(uncertainty_bins)),
        )


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


def _probe_pct(xs: list[float], q: float) -> float:
    """Small-N probe quantile that always excludes one possible peak glitch."""
    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    return s[min(len(s) - 2, int(q * len(s)))]


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
    min_probe_samples: int = 8,
    allow_passive_longitudinal: bool = True,
) -> GGVModel:
    """Fit a :class:`GGVModel` from telemetry rows (dicts w/ speed_kmh, accg_lat, accg_lon).

    Per speed bin: 95th-pct |lat|, braking (-lon) and accel (+lon) g, with sample count and lateral
    spread. ``ay_max(v)=mu*g+k*v^2`` is fitted ONLY on bins with real cornering coverage (lat spread
    >= ``min_lat_spread_g`` and >= ``min_samples``); braking/accel fitted linearly.  Passive
    longitudinal bins keep that same threshold.  Rows explicitly tagged ``brake_probe`` or
    ``accel_sweep`` come from bounded, controlled maneuvers and may qualify their matching bin at
    ``min_probe_samples``. Ellipse exponent comes from the radial hull of ``(lat, lon)``.
    """
    lat_b: dict[int, list[float]] = {}
    brk_passive_b: dict[int, list[float]] = {}
    acc_passive_b: dict[int, list[float]] = {}
    brk_probe_b: dict[int, list[float]] = {}
    acc_probe_b: dict[int, list[float]] = {}
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
        source = r.get("source")
        if ao < 0 and source == "brake_probe":
            brk_probe_b.setdefault(b, []).append(abs(ao))
        elif ao < 0 and allow_passive_longitudinal:
            brk_passive_b.setdefault(b, []).append(abs(ao))
        elif ao >= 0 and source == "accel_sweep":
            acc_probe_b.setdefault(b, []).append(abs(ao))
        elif allow_passive_longitudinal:
            acc_passive_b.setdefault(b, []).append(abs(ao))
        # ``source`` comes from persisted/transported telemetry and can be malformed. Equality is
        # intentionally non-hashing so one list/dict value cannot abort the whole defensive fit.
        probe_source = source == "brake_probe" or source == "accel_sweep"
        if (allow_passive_longitudinal or probe_source) and (al > 0.2 or abs(ao) > 0.2):
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

    def trusted_longitudinal_value(
        vals: list[float], probe_vals: list[float]
    ) -> tuple[float, float] | None:
        """Return (p95, weight) from the evidence that qualified this speed bin.

        A controlled probe must not merely unlock a bin whose percentile is then diluted by a much
        larger passive sample set. Prefer its own percentile when it is the stronger demonstrated
        envelope; otherwise retain the independently qualified passive percentile.
        """
        passive_ok = len(vals) >= min_samples
        probe_ok = len(probe_vals) >= min_probe_samples
        if not passive_ok and not probe_ok:
            return None
        passive_p95 = _pct(vals, pct) if passive_ok else float("-inf")
        probe_p95 = _probe_pct(probe_vals, pct) if probe_ok else float("-inf")
        if probe_p95 > passive_p95:
            return (probe_p95, float(len(probe_vals)))
        return (passive_p95, float(len(vals)))

    # braking fit (linear in v) on bins with samples
    xs_b, ys_b, ws_b = [], [], []
    trusted_brake_bins: list[int] = []
    for b in sorted(set(brk_passive_b) | set(brk_probe_b)):
        trusted = trusted_longitudinal_value(brk_passive_b.get(b, []), brk_probe_b.get(b, []))
        if trusted is not None and b >= 30:
            xs_b.append((b + bin_kmh / 2) / 3.6)
            ys_b.append(trusted[0])
            ws_b.append(trusted[1])
            trusted_brake_bins.append(b)
    if len(xs_b) >= 2:
        fitted_brake_b0, fitted_brake_b1 = _linfit(xs_b, ys_b, ws_b)
        brake_fit_valid = fitted_brake_b1 >= 0.0
        brake_b0, brake_b1 = (fitted_brake_b0, fitted_brake_b1) if brake_fit_valid else (1.0, 0.0)
    else:
        brake_b0, brake_b1 = (1.0, 0.0)
        brake_fit_valid = False

    # accel fit (linear) - weakly identified (human under-drove), kept conservative
    xs_a, ys_a, ws_a = [], [], []
    trusted_accel_bins: list[int] = []
    for b in sorted(set(acc_passive_b) | set(acc_probe_b)):
        trusted = trusted_longitudinal_value(acc_passive_b.get(b, []), acc_probe_b.get(b, []))
        if trusted is not None and b >= 30:
            xs_a.append((b + bin_kmh / 2) / 3.6)
            ys_a.append(trusted[0])
            ws_a.append(trusted[1])
            trusted_accel_bins.append(b)
    drive_b0, drive_b1 = _linfit(xs_a, ys_a, ws_a) if len(xs_a) >= 2 else (0.8, 0.0)

    # ellipse exponent from radial hull edge: near the boundary (lat/aymax)^n + (lon/axmax)^n ~ 1.
    n_fit = _fit_ellipse_n(hull, mu_lat, k_aero, brake_b0, brake_b1)

    def covered_range(bins: list[int]) -> list[float] | None:
        if not bins:
            return None
        ordered = sorted(bins)
        if any(
            not math.isclose(b - a, bin_kmh) for a, b in zip(ordered, ordered[1:], strict=False)
        ):
            return None
        return [float(ordered[0]), float(ordered[-1]) + bin_kmh]

    prov = {
        "bins": cov,
        "lat_corner_bins": n_corner_bins,
        # Fitted-bin counts + hull size — the confidence signals the #532 Part B safe-envelope blend
        # reads to decide, per curve, whether to trust the measurement or fall back to the prior.
        "brake_bins": len(xs_b),
        "accel_bins": len(xs_a),
        "brake_fit_valid": brake_fit_valid,
        "brake_bins_contiguous": covered_range(trusted_brake_bins) is not None,
        "accel_bins_contiguous": covered_range(trusted_accel_bins) is not None,
        "brake_probe_bins": sum(
            1 for b in trusted_brake_bins if len(brk_probe_b.get(b, [])) >= min_probe_samples
        ),
        "accel_probe_bins": sum(
            1 for b in trusted_accel_bins if len(acc_probe_b.get(b, [])) >= min_probe_samples
        ),
        "brake_speed_range_kmh": covered_range(trusted_brake_bins),
        "accel_speed_range_kmh": covered_range(trusted_accel_bins),
        "passive_min_samples_per_bin": min_samples,
        "probe_min_samples_per_bin": min_probe_samples,
        "hull_points": len(hull),
        "lat_model": f"ay_max(v)={mu_lat:.3f}+{k_aero:.5f}*v_ms^2 g [mech peak; no aero-lat]",
        "brake_model": f"ax_brake(v)={brake_b0:.3f}+{brake_b1:.5f}*v_ms (g)",
        "accel_model": f"ax_drive(v)={drive_b0:.3f}+{drive_b1:.5f}*v_ms (g)",
        "ellipse_n": round(n_fit, 3),
    }
    return GGVModel(
        mu_lat_g=mu_lat,
        k_aero_lat=max(0.0, k_aero),
        brake_b0_g=brake_b0,
        brake_b1=brake_b1,
        drive_b0_g=drive_b0,
        drive_b1=drive_b1,
        drive_min_g=0.35,
        ellipse_n=n_fit,
        provenance=prov,
    )


def with_binned_uncertainty(
    point_model: GGVModel,
    rows: list[dict],
    prior: GGVModel,
    *,
    bin_kmh: float = DEFAULT_UNCERTAINTY_BIN_KMH,
    max_speed_kmh: float = DEFAULT_UNCERTAINTY_MAX_KMH,
    prior_relative_std: float = DEFAULT_PRIOR_RELATIVE_STD,
    lcb_z: float = DEFAULT_UNCERTAINTY_LCB_Z,
    min_samples: int = 40,
    min_probe_samples: int = 8,
) -> GGVModel:
    """Attach a deterministic binned-Bayesian lower-confidence map (#543).

    Each speed/channel bin starts from the generic plant as a normal prior. Directly observed
    95th-percentile envelope evidence updates that prior with a normal likelihood. The persisted
    posterior mean is useful for inspection, but the QSS consumes ``mean - z * epistemic_std``.
    Unmeasured bins therefore stay explicitly high-uncertainty and run below the optimistic prior;
    evidence never leaks into neighbouring speed bins.

    Samples at 100+ Hz are correlated, so the likelihood uses a capped effective sample size. This
    prevents a single two-second probe from claiming thousands of independent observations.
    """
    if not _finite_ggv(bin_kmh, max_speed_kmh, prior_relative_std, lcb_z):
        raise ValueError("uncertainty parameters must be finite")
    if (
        not math.isclose(bin_kmh, DEFAULT_UNCERTAINTY_BIN_KMH)
        or not math.isclose(max_speed_kmh, DEFAULT_UNCERTAINTY_MAX_KMH)
        or prior_relative_std <= 0.0
        or lcb_z <= 0.0
        or min_samples <= 0
        or min_probe_samples <= 0
    ):
        raise ValueError("uncertainty parameters require the complete 30x10 km/h runtime grid")
    if not math.isclose(bin_kmh, round(bin_kmh)):
        raise ValueError("bin_kmh must be a whole number of km/h")
    count = max_speed_kmh / bin_kmh
    if not math.isclose(count, round(count)):
        raise ValueError("max_speed_kmh must be an exact multiple of bin_kmh")

    raw: dict[int, dict[str, list[float]]] = {}
    for row in rows:
        try:
            speed = float(row["speed_kmh"])
            lateral = abs(float(row["accg_lat"]))
            longitudinal = float(row["accg_lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not _finite_ggv(speed, lateral, longitudinal) or not (0.0 <= speed < max_speed_kmh):
            continue
        low = int(speed // bin_kmh) * int(bin_kmh)
        bucket = raw.setdefault(
            low,
            {
                "lateral": [],
                "brake_probe": [],
                "drive_probe": [],
            },
        )
        bucket["lateral"].append(lateral)
        source = row.get("source")
        if longitudinal < 0.0:
            if source == "brake_probe":
                bucket["brake_probe"].append(abs(longitudinal))
        else:
            if source == "accel_sweep":
                bucket["drive_probe"].append(longitudinal)

    def posterior(
        values: list[float],
        prior_mean: float,
        *,
        floor_g: float,
        observed: bool,
        probe_qualified: bool = False,
    ) -> dict:
        prior_std = max(0.03, abs(prior_mean) * prior_relative_std)
        if not observed:
            mean = prior_mean
            std = prior_std
            source = "prior"
            n = 0
        else:
            n = len(values)
            # At the eight-sample controlled-probe gate, ordinary p95 is the maximum. Reuse the
            # telemetry fitter's small-N rule so one spike cannot lift a runtime-bearing posterior.
            envelope = _probe_pct(values, 0.95) if probe_qualified else _pct(values, 0.95)
            median = _pct(values, 0.50)
            robust_scale = max(0.03, (envelope - median) / 1.645)
            effective_n = min(50.0, max(1.0, float(n)))
            likelihood_std = max(0.03, robust_scale / math.sqrt(effective_n))
            prior_precision = 1.0 / (prior_std * prior_std)
            likelihood_precision = 1.0 / (likelihood_std * likelihood_std)
            variance = 1.0 / (prior_precision + likelihood_precision)
            mean = variance * (prior_mean * prior_precision + envelope * likelihood_precision)
            std = math.sqrt(variance)
            source = "measured"
        safe = max(floor_g, mean - lcb_z * std)
        return {
            "mean_g": round(mean, 6),
            "epistemic_std_g": round(std, 6),
            "safe_g": round(min(mean, safe), 6),
            "n": int(n),
            "source": source,
        }

    bins: list[dict] = []
    for index in range(int(round(count))):
        lo = index * bin_kmh
        hi = lo + bin_kmh
        mid_ms = (lo + hi) * 0.5 / 3.6
        bucket = raw.get(int(lo), {})
        lateral = list(bucket.get("lateral", []))
        brake_probe = list(bucket.get("brake_probe", []))
        drive_probe = list(bucket.get("drive_probe", []))

        lateral_observed = len(lateral) >= min_samples and _pct(lateral, 0.95) >= 0.9
        # Longitudinal caps require an explicit limit-reaching probe. Ordinary driving can provide
        # thousands of near-zero coast/maintenance-throttle samples without saying anything about
        # the available brake or drive envelope; treating their count as evidence can immobilize
        # the runtime plant. Lateral remains passively observable in actual cornering.
        brake_values = brake_probe
        brake_observed = len(brake_probe) >= min_probe_samples
        drive_values = drive_probe
        drive_observed = len(drive_probe) >= min_probe_samples
        bins.append(
            {
                "speed_min_kmh": float(lo),
                "speed_max_kmh": float(hi),
                "lateral": posterior(
                    lateral,
                    prior.ay_max(mid_ms) / G,
                    floor_g=0.5,
                    observed=lateral_observed,
                ),
                "brake": posterior(
                    brake_values,
                    prior.ax_brake_max(mid_ms) / G,
                    floor_g=0.5,
                    observed=brake_observed,
                    probe_qualified=True,
                ),
                "drive": posterior(
                    drive_values,
                    prior.ax_drive_max(mid_ms) / G,
                    floor_g=0.10,
                    observed=drive_observed,
                    probe_qualified=True,
                ),
            }
        )

    provenance = copy.deepcopy(point_model.provenance)
    provenance["uncertainty"] = {
        "method": "binned_normal_posterior_lcb",
        "bin_kmh": bin_kmh,
        "max_speed_kmh": max_speed_kmh,
        "prior_relative_std": prior_relative_std,
        "lcb_z": lcb_z,
        "runtime_uses": "min(point_estimate, lower_confidence_bound)",
        "unmeasured": "lower-confidence generic prior; no neighbouring-bin extrapolation",
        "measured_bins": {
            kind: sum(1 for speed_bin in bins if speed_bin[kind]["source"] == "measured")
            for kind in UNCERTAINTY_CHANNELS
        },
    }
    return replace(point_model, provenance=provenance, uncertainty_bins=tuple(bins))


def merge_selfplay_model(current: GGVModel, batch: GGVModel) -> tuple[GGVModel, dict]:
    """Merge one self-play batch refit into the current identified plant, monotonically (#577).

    The self-play loop drives the alien line, refits the friction envelope from ONLY that batch's
    lap archives, and must never *lose* previously proven grip to a smaller/softer batch: a lap
    driven at 0.9x the planned envelope produces measured lateral evidence BELOW what the
    handshake laps already proved, and adopting it verbatim would ratchet the plant (and every
    QSS profile built from it) downward. Merge rules, per speed bin:

    * **lateral** — a batch posterior is adopted ONLY when it raises ``safe_g`` (strict
      monotonicity). Measured provenance alone is not enough: a lap driven at 0.81x the planned
      envelope "measures" less grip than even the prior's lower-confidence bound already grants,
      and adopting it would ratchet the envelope (and every QSS profile built from it) downward.
      Grip once proven stays proven within the combo's cohort; the keep-last-valid falsification
      oracle in ``auto_alien`` is the safety valve when a raised envelope turns out wrong on
      track.
    * **brake / drive** — always the current model's bins: longitudinal bins only learn from
      controlled probes (``brake_probe`` / ``accel_sweep`` rows), which a non-handshake self-play
      drive never produces, so a batch refit can only regress them to the prior.

    Top-level lateral grip takes ``max(current, batch)`` (the point model is the operating
    ceiling the bins derate — proven-harder cornering may raise it, a soft batch never lowers
    it); every other coefficient, the caps, ``ellipse_n`` and the supported-longitudinal
    overrides stay the current model's. Both models must carry the identical uncertainty-bin
    grid (same schema-v3 fit pipeline) — anything else is a wiring bug and raises.
    """
    if not current.uncertainty_aware or not batch.uncertainty_aware:
        raise ValueError("selfplay merge requires two uncertainty-aware (schema-v3) models")
    if len(current.uncertainty_bins) != len(batch.uncertainty_bins):
        raise ValueError(
            "selfplay merge: uncertainty-bin grids differ "
            f"({len(current.uncertainty_bins)} vs {len(batch.uncertainty_bins)} bins)"
        )
    merged_bins: list[dict] = []
    lateral_adopted = 0
    lateral_raised = 0
    for cur_bin, new_bin in zip(current.uncertainty_bins, batch.uncertainty_bins, strict=True):
        if not math.isclose(
            float(cur_bin["speed_min_kmh"]), float(new_bin["speed_min_kmh"])
        ) or not math.isclose(float(cur_bin["speed_max_kmh"]), float(new_bin["speed_max_kmh"])):
            raise ValueError(
                "selfplay merge: bin speed ranges differ "
                f"({cur_bin['speed_min_kmh']}-{cur_bin['speed_max_kmh']} vs "
                f"{new_bin['speed_min_kmh']}-{new_bin['speed_max_kmh']} km/h)"
            )
        cur_lat = dict(cur_bin["lateral"])
        new_lat = dict(new_bin["lateral"])
        cur_measured = cur_lat.get("source") == "measured"
        new_measured = new_lat.get("source") == "measured"
        # Strictly monotone: only a measured batch posterior that RAISES safe_g wins. A measured-
        # but-lower posterior (a soft lap, or evidence below the prior's own LCB) never regresses
        # the envelope.
        if new_measured and float(new_lat["safe_g"]) > float(cur_lat["safe_g"]):
            lateral = new_lat
            if cur_measured:
                lateral_raised += 1
            else:
                lateral_adopted += 1
        else:
            lateral = cur_lat
        merged_bins.append(
            {
                "speed_min_kmh": float(cur_bin["speed_min_kmh"]),
                "speed_max_kmh": float(cur_bin["speed_max_kmh"]),
                "lateral": lateral,
                "brake": dict(cur_bin["brake"]),
                "drive": dict(cur_bin["drive"]),
            }
        )
    mu_before = current.mu_lat_g
    mu_after = max(current.mu_lat_g, batch.mu_lat_g)
    provenance = copy.deepcopy(current.provenance)
    history = provenance.setdefault("selfplay_merges", [])
    stats = {
        "lateral_bins_adopted": lateral_adopted,
        "lateral_bins_raised": lateral_raised,
        "mu_lat_g_before": round(mu_before, 6),
        "mu_lat_g_after": round(mu_after, 6),
        "batch_mu_lat_g": round(batch.mu_lat_g, 6),
    }
    history.append(stats)
    merged = replace(
        current,
        mu_lat_g=mu_after,
        provenance=provenance,
        uncertainty_bins=tuple(merged_bins),
    )
    return merged, dict(stats)


def observe_lap_tyre_state(
    archive: dict,
    *,
    thermal_window_half_width_c: float = DEFAULT_THERMAL_WINDOW_HALF_WIDTH_C,
    min_coverage_fraction: float = DEFAULT_THERMAL_COVERAGE_FRACTION,
    min_stability_fraction: float = DEFAULT_THERMAL_STABILITY_FRACTION,
    stability_half_width_c: float = DEFAULT_THERMAL_STABILITY_HALF_WIDTH_C,
    max_wheel_spread_c: float = DEFAULT_THERMAL_MAX_WHEEL_SPREAD_C,
) -> dict:
    """Tag one lap archive's tyre thermal/pressure/grip state (#543).

    The observer reads the canonical #488 archive channels. ``fit_eligible`` is deliberately strict:
    a valid lap, all four core-temperature and hot-pressure channels, a car-true optimum, and a
    stable within-lap per-wheel thermal state. ``tag`` still reports cold/optimal/hot relative to
    the car's optimum; a stable cold lap is usable as a conservative, explicitly tagged cohort.
    Surface temperatures and CSP ``dy`` peak-mu are reported when present; they do not fabricate
    eligibility when core/pressure evidence is missing.
    """
    trace = archive.get("trace") if isinstance(archive, dict) else None
    fields = trace.get("fields") if isinstance(trace, dict) else None
    samples = trace.get("samples") if isinstance(trace, dict) else None
    lap = archive.get("lap") if isinstance(archive, dict) else None
    tyres = archive.get("tyres") if isinstance(archive, dict) else None
    setup = archive.get("setup") if isinstance(archive, dict) else None
    lap_uuid = archive.get("lap_uuid") if isinstance(archive, dict) else None
    base = {
        "lap_uuid": lap_uuid if isinstance(lap_uuid, str) else None,
        "tag": "unknown",
        "fit_eligible": False,
        "reason": "missing trace",
        "optimal_temp_c": None,
        "core_temp_c": None,
        "surface_temp_c": None,
        "pressure_psi": None,
        "grip_multiplier": None,
        "compound_index": None,
        "compound_name": None,
        "setup_hash": None,
        "thermal_residence_fraction": 0.0,
        "thermal_stability_fraction": 0.0,
        "sample_coverage_fraction": 0.0,
        "wheel_core_temp_c": None,
        "wheel_spread_c": None,
    }
    if not isinstance(fields, list) or not isinstance(samples, list) or not samples:
        return base
    if not isinstance(tyres, dict):
        tyres = {}
    if not isinstance(setup, dict):
        setup = {}
    compound_index = tyres.get("compoundIndex")
    if isinstance(compound_index, bool) or not isinstance(compound_index, (int, float)):
        compound_index = None
    elif not math.isfinite(float(compound_index)):
        compound_index = None
    else:
        compound_index = int(compound_index)
    compound_name = tyres.get("name")
    if not isinstance(compound_name, str) or not compound_name.strip():
        compound_name = None
    setup_hash = setup.get("hash")
    if not isinstance(setup_hash, str) or not setup_hash.strip():
        setup_snapshot = setup.get("snapshot")
        if isinstance(setup_snapshot, (dict, list)):
            # CSP serializes the default/no-file setup as an empty snapshot and an empty hash. It is
            # still a concrete setup cohort: derive a stable identity from the persisted snapshot so
            # default laps group together without being conflated with genuinely missing metadata.
            canonical_snapshot = json.dumps(
                setup_snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            setup_hash = (
                "snapshot-sha256:" + hashlib.sha256(canonical_snapshot.encode("utf-8")).hexdigest()
            )
        else:
            setup_hash = None
    base.update(
        {
            "compound_index": compound_index,
            "compound_name": compound_name,
            "setup_hash": setup_hash,
        }
    )
    try:
        optimal = float(tyres.get("optimalTempC"))
    except (TypeError, ValueError):
        optimal = float("nan")
    if not math.isfinite(optimal):
        base["reason"] = "missing car-true optimalTempC"
        return base

    index = {name: i for i, name in enumerate(fields)}
    core_names = [f"tyreCoreTemp_{wheel}" for wheel in _WHEELS]
    pressure_names = [f"wheelsPressure_{wheel}" for wheel in _WHEELS]
    if any(name not in index for name in core_names + pressure_names):
        base["optimal_temp_c"] = optimal
        base["reason"] = "missing per-wheel core-temperature or pressure channels"
        return base

    def row_values(row, names: list[str]) -> list[float]:
        out = []
        for name in names:
            try:
                value = float(row[index[name]])
            except (IndexError, TypeError, ValueError):
                continue
            if math.isfinite(value) and value != 0.0:
                out.append(value)
        return out

    core_means: list[float] = []
    core_rows: list[list[float]] = []
    pressure_means: list[float] = []
    surface_means: list[float] = []
    grip_mu: list[float] = []
    in_window = 0
    surface_names = [
        f"tyreTemp{band}_{wheel}"
        for band in ("Inner", "Mid", "Outer")
        for wheel in _WHEELS
        if f"tyreTemp{band}_{wheel}" in index
    ]
    dy_names = [f"dy_{wheel}" for wheel in _WHEELS if f"dy_{wheel}" in index]
    for row in samples:
        if not isinstance(row, (list, tuple)):
            continue
        core = row_values(row, core_names)
        pressure = row_values(row, pressure_names)
        if len(core) == len(_WHEELS) and len(pressure) == len(_WHEELS):
            core_mean = statistics.fmean(core)
            core_means.append(core_mean)
            core_rows.append(core)
            pressure_means.append(statistics.fmean(pressure))
            if all(abs(value - optimal) <= thermal_window_half_width_c for value in core):
                in_window += 1
        surface = row_values(row, surface_names)
        if surface:
            surface_means.append(statistics.fmean(surface))
        dy = row_values(row, dy_names)
        if dy:
            grip_mu.append(statistics.fmean(dy))

    coverage = len(core_means) / len(samples)
    residence = in_window / len(core_means) if core_means else 0.0
    wheel_centers = (
        [statistics.median(row[i] for row in core_rows) for i in range(len(_WHEELS))]
        if core_rows
        else []
    )
    stable_rows = (
        sum(
            all(
                abs(row[i] - wheel_centers[i]) <= stability_half_width_c
                for i in range(len(_WHEELS))
            )
            for row in core_rows
        )
        if wheel_centers
        else 0
    )
    stability = stable_rows / len(core_rows) if core_rows else 0.0
    wheel_spread = max(wheel_centers) - min(wheel_centers) if wheel_centers else None
    mean_core = statistics.fmean(core_means) if core_means else None
    mean_pressure = statistics.fmean(pressure_means) if pressure_means else None
    tag = "unknown"
    if mean_core is not None:
        if mean_core < optimal - thermal_window_half_width_c:
            tag = "cold"
        elif mean_core > optimal + thermal_window_half_width_c:
            tag = "hot"
        else:
            tag = "optimal"
    is_valid = isinstance(lap, dict) and lap.get("is_valid") is True
    eligible = (
        is_valid
        and (compound_index is not None or compound_name is not None)
        and setup_hash is not None
        and coverage >= min_coverage_fraction
        and stability >= min_stability_fraction
        and wheel_spread is not None
        and wheel_spread <= max_wheel_spread_c
        and tag != "unknown"
    )
    grip_multiplier = None
    if grip_mu:
        peak = _pct(grip_mu, 0.95)
        if peak > 0.0:
            grip_multiplier = min(1.0, max(0.0, statistics.median(grip_mu) / peak))
    elif eligible:
        # No CSP dy channel: eligibility proves the thermal state, but not an absolute tyre-model
        # multiplier. One is neutral and explicitly provenance-labelled by the missing dy input.
        grip_multiplier = 1.0
    return {
        "lap_uuid": base["lap_uuid"],
        "tag": tag,
        "fit_eligible": eligible,
        "reason": (
            "thermally consistent"
            if eligible
            else (
                "missing tyre compound identity"
                if compound_index is None and compound_name is None
                else (
                    "missing setup identity"
                    if setup_hash is None
                    else "outside thermal stability/validity gate"
                )
            )
        ),
        "optimal_temp_c": round(optimal, 3),
        "core_temp_c": round(mean_core, 3) if mean_core is not None else None,
        "surface_temp_c": (round(statistics.fmean(surface_means), 3) if surface_means else None),
        "pressure_psi": round(mean_pressure, 3) if mean_pressure is not None else None,
        "grip_multiplier": (round(grip_multiplier, 5) if grip_multiplier is not None else None),
        "grip_multiplier_source": "dy_within_lap" if grip_mu else "thermal_neutral",
        "compound_index": compound_index,
        "compound_name": compound_name,
        "setup_hash": setup_hash,
        "thermal_residence_fraction": round(residence, 6),
        "thermal_stability_fraction": round(stability, 6),
        "sample_coverage_fraction": round(coverage, 6),
        "wheel_core_temp_c": (
            {wheel: round(value, 3) for wheel, value in zip(_WHEELS, wheel_centers, strict=True)}
            if wheel_centers
            else None
        ),
        "wheel_spread_c": round(wheel_spread, 3) if wheel_spread is not None else None,
    }


def ggv_from_lap_archives(
    archives: list[dict],
    prior: GGVModel,
    *,
    prior_name: str = "injected_prior",
    min_friction_rows: int = 200,
    probe_rows: list[dict] | None = None,
    probe_run_id: str | None = None,
) -> tuple[GGVModel, dict]:
    """Fit an uncertainty-aware GGV using only a thermally consistent lap cohort (#543)."""
    states = [observe_lap_tyre_state(archive) for archive in archives]
    eligible = [
        (archive, state)
        for archive, state in zip(archives, states, strict=True)
        if state.get("fit_eligible")
    ]
    if not eligible:
        raise ValueError("no thermally consistent valid lap archives")

    # A plant is per combo, which includes tyre compound and setup. A stale archive from the same
    # car/track session must not contaminate the posterior merely because its temperatures match.
    cohort_groups: dict[tuple[object, object, object], list[tuple[dict, dict]]] = {}
    cohort_first_index: dict[tuple[object, object, object], int] = {}
    for archive_index, (archive, state) in enumerate(eligible):
        compound = state.get("compound_index")
        if compound is None:
            compound = state.get("compound_name")
        key = (compound, state.get("setup_hash"), state.get("tag"))
        cohort_groups.setdefault(key, []).append((archive, state))
        cohort_first_index.setdefault(key, archive_index)
    cohort_key, eligible = sorted(
        cohort_groups.items(),
        key=lambda item: (
            -len(item[1]),
            0 if item[0][2] == "optimal" else 1,
            cohort_first_index[item[0]],
        ),
    )[0]
    core_center = statistics.median(float(state["core_temp_c"]) for _, state in eligible)
    pressure_center = statistics.median(float(state["pressure_psi"]) for _, state in eligible)
    for state in states:
        state["cohort_consistent"] = False
    selected: list[tuple[dict, dict]] = []
    for archive, state in eligible:
        cohort_ok = (
            abs(float(state["core_temp_c"]) - core_center) <= 5.0
            and abs(float(state["pressure_psi"]) - pressure_center) <= 2.0
        )
        state["cohort_consistent"] = cohort_ok
        if cohort_ok:
            selected.append((archive, state))
    if not selected:
        raise ValueError("thermally eligible laps do not form a consistent temp/pressure cohort")

    rows: list[dict] = []
    for archive, state in selected:
        trace = archive["trace"]
        fields = trace["fields"]
        index = {name: i for i, name in enumerate(fields)}
        required = ("speed", "accG_lat", "accG_long", "brake", "throttle")
        if any(name not in index for name in required):
            continue
        for sample in trace["samples"]:
            try:
                speed = float(sample[index["speed"]])
                lateral = float(sample[index["accG_lat"]])
                longitudinal = float(sample[index["accG_long"]])
                brake = float(sample[index["brake"]])
                throttle = float(sample[index["throttle"]])
            except (IndexError, TypeError, ValueError):
                continue
            if not _finite_ggv(speed, lateral, longitudinal, brake, throttle):
                continue
            rows.append(
                {
                    "speed_kmh": speed,
                    "accg_lat": lateral,
                    "accg_lon": longitudinal,
                    # The lap schema does not persist the controller's active-probe state. Do not
                    # infer it from brake/throttle alone (normal driving can look identical) and
                    # accidentally unlock the lower 8-sample probe gate; archive rows use the
                    # stricter passive threshold.
                    "source": "passive",
                    "thermal_lap_uuid": state.get("lap_uuid"),
                }
            )
    if len(rows) < min_friction_rows:
        raise ValueError(
            f"insufficient thermally consistent friction rows: {len(rows)} < {min_friction_rows}"
        )
    # The immutable archive proves the thermal state and supplies passive cornering. In the live
    # harness, archives are filtered to files written after this exact run began and the controller
    # gives every probe a nonce. That run scope is authoritative even after an invalid AC lap,
    # because graphics.completedLaps (valid laps) and the app archive counter (all boundaries) are
    # deliberately different clocks. Direct/offline callers without a nonce retain exact lap-number
    # matching and therefore cannot silently mix arbitrary probes into an archive cohort.
    selected_lap_numbers = {
        int(archive["lap"]["lap_n"])
        for archive, _ in selected
        if isinstance(archive.get("lap"), dict)
        and isinstance(archive["lap"].get("lap_n"), int)
        and not isinstance(archive["lap"].get("lap_n"), bool)
    }
    valid_probe_run_id = isinstance(probe_run_id, str) and bool(probe_run_id.strip())
    complete_run_cohort = len(selected) == len(archives)
    if valid_probe_run_id and complete_run_cohort:
        thermal_probe_rows = [
            dict(row)
            for row in (probe_rows or [])
            if isinstance(row, dict) and row.get("probe_run_id") == probe_run_id
        ]
        probe_attribution = "current-run nonce (complete thermal cohort)"
    elif valid_probe_run_id:
        # The nonce proves invocation identity, not tyre state. If any current-run archive is
        # invalid, thermally ineligible, or belongs to another cohort, conservatively keep every
        # longitudinal bin on the prior rather than assigning a probe to the wrong tyre regime.
        thermal_probe_rows = []
        probe_attribution = "current-run nonce rejected (incomplete thermal cohort)"
    else:
        thermal_probe_rows = [
            dict(row)
            for row in (probe_rows or [])
            if isinstance(row, dict)
            and isinstance(row.get("lap_number"), int)
            and not isinstance(row.get("lap_number"), bool)
            and int(row["lap_number"]) in selected_lap_numbers
        ]
        probe_attribution = "archive lap number"
    combined_rows = rows + thermal_probe_rows
    measured = ggv_from_telemetry(combined_rows, allow_passive_longitudinal=False)
    point_model = blend_ggv_safe(measured, prior, prior_name=prior_name)
    model = with_binned_uncertainty(point_model, combined_rows, prior)
    summary = {
        "friction_rows": len(rows),
        "probe_rows_seen": len(probe_rows or []),
        "probe_rows": len(thermal_probe_rows),
        "probe_attribution": probe_attribution,
        "tyre_states": states,
        "selected_lap_uuids": [state.get("lap_uuid") for _, state in selected],
        "thermal_cohort": {
            "core_temp_c": round(core_center, 3),
            "pressure_psi": round(pressure_center, 3),
            "core_tolerance_c": 5.0,
            "pressure_tolerance_psi": 2.0,
            "compound": cohort_key[0],
            "setup_hash": cohort_key[1],
            "thermal_tag": cohort_key[2],
        },
    }
    return model, summary


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


def blend_ggv_safe(
    measured: GGVModel,
    prior: GGVModel,
    *,
    prior_name: str = "injected_prior",
    min_brake_bins: int = 2,
    min_accel_bins: int = 2,
    min_longitudinal_span_kmh: float = MIN_LONGITUDINAL_SUPPORT_KMH,
    support_taper_kmh: float = 10.0,
) -> GGVModel:
    """Safe-envelope blend of a per-combo MEASURED GGVModel with a trusted PRIOR (#532 Part B).

    The measured model comes from :func:`ggv_from_telemetry` over probe-lap rows; the prior is the
    live-verified generic plant. The blend is the deterministic guard that keeps the operating plant
    from ever being MORE optimistic than warranted, while never regressing the reference combo:

    * **Lateral grip: the prior is BOTH ceiling and floor.** Ceiling — never extrapolate up (an
      aero-lateral term spins the GT3 out, live-disproven #259/#244; ``k_aero_lat`` stays 0, the cap
      stays the prior's). Floor — a conservative, AC-valid handshake never reaches the LATERAL grip
      limit (it drives clean at moderate pace by design), so a measured lateral BELOW the prior is a
      *lower bound*, not evidence of a weaker car; lowering the plant to it would regress the very
      car the prior nails, for no safety gain (the live slip limiter already guards over-drive).
      Genuine per-combo lateral lowering needs slip-saturation evidence / a limit-reaching lateral
      probe — deferred (unsafe to push a GT3 to its lateral limit unattended). So lateral == prior.
    * **Braking / drive accel** CAN be probed to their limits safely (straight-line braking, WOT
      accel). Apply the measured curve ONLY inside an observed span of at least
      ``min_longitudinal_span_kmh``. Braking accepts a curve that is consistently above OR below
      the prior: a weaker measured brake envelope must make the combo brake earlier. Drive accepts
      only a confident gain because conservative acceleration under-measurement is not hazardous.
      The measured curve tapers to the prior at both support edges and the prior is used everywhere
      outside, so a low-speed fit is never extrapolated to an unmeasured high-speed point.
      The prior remains in the top-level coefficients as a fail-safe for older consumers, and its
      hard caps are kept.
    * **The ellipse exponent is pinned to the prior.** The friction-ellipse boundary exponent
      requires limit-reaching (boundary) data; a conservative handshake's ``(lat, lon)`` hull is
      interior points, so a fit from it is unreliable — like the lateral limit, honest per-combo
      identification of it needs a limit-reaching probe (deferred). A wrong lat/long coupling is the
      biggest silent-spin risk (Council 2026-07-13), and the prior's exponent is live-verified.

    Net: the reference car (and any conservatively-driven combo) reproduces the prior — no
    regression, no spin — while a car that DEMONSTRABLY brakes / accelerates harder than the prior
    gets that measured improvement only over the speed range that proved it. The measured
    lower-bound envelope is recorded in provenance for a future slip-saturation pass. Provenance
    labels each curve ``measured(supported)`` vs ``prior``.
    """
    prov = dict(measured.provenance or {})
    corner_bins = int(prov.get("lat_corner_bins", 0) or 0)
    brake_bins = int(prov.get("brake_bins", 0) or 0)
    accel_bins = int(prov.get("accel_bins", 0) or 0)
    hull_points = int(prov.get("hull_points", 0) or 0)

    def observed_range(key: str) -> tuple[float, float] | None:
        value = prov.get(key)
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        lo, hi = value
        if not _finite_ggv(lo, hi) or float(lo) < 0.0 or float(hi) <= float(lo):
            return None
        return (float(lo), float(hi))

    def coverage_ok(value: tuple[float, float] | None) -> bool:
        return value is not None and value[1] - value[0] >= min_longitudinal_span_kmh

    brake_range = observed_range("brake_speed_range_kmh")
    accel_range = observed_range("accel_speed_range_kmh")
    supported_longitudinal: dict[str, dict] = {}

    # Lateral: the prior is ceiling AND floor (see docstring) — a non-limit measurement is only a
    # lower bound, so it never lowers the operating plant and never regresses the reference car.
    mu_lat, lat_src = prior.mu_lat_g, "prior"

    # Ellipse exponent: pinned to the prior — its boundary needs limit-reaching data the
    # conservative handshake does not produce (the hull is interior points). Recorded hull_points
    # feeds a future limit-reaching pass. See docstring.
    ellipse_n, ell_src = prior.ellipse_n, "prior"

    # Braking: the top-level curve remains the prior. A consistently stronger OR weaker measured
    # envelope is activated only over a sufficiently broad OBSERVED span and tapers back to the
    # prior at both edges. This prevents a narrow 50-90 km/h fit from changing a later 200 km/h
    # braking point.
    brake_b0, brake_b1, brake_src = prior.brake_b0_g, prior.brake_b1, "prior"
    if (
        brake_bins >= min_brake_bins
        and prov.get("brake_fit_valid") is True
        and coverage_ok(brake_range)
        and _finite_ggv(measured.brake_b0_g, measured.brake_b1)
        and _brake_curve_is_supported(
            measured.brake_b0_g,
            measured.brake_b1,
            prior.brake_b0_g,
            prior.brake_b1,
            v_lo=brake_range[0] / 3.6,
            v_hi=brake_range[1] / 3.6,
        )
    ):
        supported_longitudinal["brake"] = {
            "speed_min_kmh": brake_range[0],
            "speed_max_kmh": brake_range[1],
            "b0_g": measured.brake_b0_g,
            "b1": measured.brake_b1,
            "floor_g": 0.5,
            "taper_kmh": min(support_taper_kmh, (brake_range[1] - brake_range[0]) / 2.0),
        }
        brake_src = "measured(supported)"

    # Drive accel: same rule (the WOT sweep reaches full throttle; aggressive accel is TC-off-safe
    # live via the slip limiter). Measured only where it confidently exceeds the prior, else prior.
    drive_b0, drive_b1, drive_min, drive_src = (
        prior.drive_b0_g,
        prior.drive_b1,
        prior.drive_min_g,
        "prior",
    )
    if (
        accel_bins >= min_accel_bins
        and coverage_ok(accel_range)
        and _finite_ggv(measured.drive_b0_g, measured.drive_b1, measured.drive_min_g)
        and _curve_exceeds(
            measured.drive_b0_g,
            measured.drive_b1,
            prior.drive_b0_g,
            prior.drive_b1,
            v_lo=accel_range[0] / 3.6,
            v_hi=accel_range[1] / 3.6,
        )
    ):
        supported_longitudinal["drive"] = {
            "speed_min_kmh": accel_range[0],
            "speed_max_kmh": accel_range[1],
            "b0_g": measured.drive_b0_g,
            "b1": measured.drive_b1,
            "floor_g": measured.drive_min_g,
            "taper_kmh": min(support_taper_kmh, (accel_range[1] - accel_range[0]) / 2.0),
        }
        drive_src = "measured(supported)"

    blend_prov = {
        "blend_source": {
            "lateral": lat_src,
            "brake": brake_src,
            "drive": drive_src,
            "ellipse_n": ell_src,
        },
        "measured": {
            "mu_lat_g": round(measured.mu_lat_g, 4),
            "brake_b0_g": round(measured.brake_b0_g, 4),
            "brake_b1": round(measured.brake_b1, 5),
            "drive_b0_g": round(measured.drive_b0_g, 4),
            "drive_b1": round(measured.drive_b1, 5),
            "ellipse_n": round(measured.ellipse_n, 3),
            "lat_corner_bins": corner_bins,
            "brake_bins": brake_bins,
            "accel_bins": accel_bins,
            "brake_probe_bins": int(prov.get("brake_probe_bins", 0) or 0),
            "accel_probe_bins": int(prov.get("accel_probe_bins", 0) or 0),
            "brake_speed_range_kmh": list(brake_range) if brake_range else None,
            "accel_speed_range_kmh": list(accel_range) if accel_range else None,
            "passive_min_samples_per_bin": prov.get("passive_min_samples_per_bin"),
            "probe_min_samples_per_bin": prov.get("probe_min_samples_per_bin"),
            "hull_points": hull_points,
            "bins": prov.get("bins", {}),
        },
        "blend_gate": {
            "min_longitudinal_span_kmh": min_longitudinal_span_kmh,
            "brake_coverage_ok": coverage_ok(brake_range),
            "accel_coverage_ok": coverage_ok(accel_range),
            "outside_observed_range": "prior",
            "support_taper_kmh": support_taper_kmh,
        },
        "prior": prior_name,
        # A conservative handshake under-measures the lateral limit, so lateral values below the
        # prior remain lower bounds. Straight-line braking, however, is limit-reaching evidence.
        "note": (
            "lateral pinned to prior (conservative drive under-measures the lateral limit); "
            "braking evidence and drive gains applied only inside measured speed support; "
            "prior outside"
        ),
    }
    return GGVModel(
        mu_lat_g=mu_lat,
        k_aero_lat=0.0,  # ALWAYS 0 — an aero-lateral term spins the GT3 out (live-disproven #259)
        brake_b0_g=brake_b0,
        brake_b1=brake_b1,
        drive_b0_g=drive_b0,
        drive_b1=drive_b1,
        drive_min_g=drive_min,
        ellipse_n=ellipse_n,
        ay_cap_g=prior.ay_cap_g,  # never raise the lateral cap above the prior
        ax_brake_cap_g=prior.ax_brake_cap_g,
        provenance=blend_prov,
        supported_longitudinal=supported_longitudinal,
    )


def _curve_exceeds(
    m0: float,
    m1: float,
    p0: float,
    p1: float,
    *,
    v_lo: float = 11.0,
    v_hi: float = 50.0,
    margin: float = 0.03,
) -> bool:
    """True iff the linear curve ``m0+m1*v`` exceeds ``p0+p1*v`` (by ``margin`` g) at BOTH speeds.

    For two lines, exceeding at both endpoints of ``[v_lo, v_hi]`` (m/s; ~40..180 km/h) means the
    measured curve dominates the prior across the whole covered range — the only case where a
    measured braking/accel envelope is confidently BETTER than the prior and safe to adopt (a
    diluted under-measurement fails this, so it never lowers the plant).
    """
    return (m0 + m1 * v_lo) >= (p0 + p1 * v_lo) + margin and (m0 + m1 * v_hi) >= (
        p0 + p1 * v_hi
    ) + margin


def _brake_curve_is_supported(
    m0: float,
    m1: float,
    p0: float,
    p1: float,
    *,
    v_lo: float,
    v_hi: float,
    margin: float = 0.03,
) -> bool:
    """True when a brake curve is consistently stronger OR weaker over measured support."""
    exceeds = _curve_exceeds(m0, m1, p0, p1, v_lo=v_lo, v_hi=v_hi, margin=margin)
    below = (m0 + m1 * v_lo) <= (p0 + p1 * v_lo) - margin and (m0 + m1 * v_hi) <= (
        p0 + p1 * v_hi
    ) - margin
    return exceeds or below


def _finite_ggv(*values: float) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _freeze_supported_longitudinal(supported: Mapping) -> MappingProxyType:
    """Return a detached, recursively read-only copy of the two-level support mapping."""
    return MappingProxyType(
        {kind: MappingProxyType(dict(override)) for kind, override in supported.items()}
    )


def _freeze_uncertainty_bins(bins: tuple[Mapping, ...]) -> tuple[MappingProxyType, ...]:
    """Return a detached, recursively read-only uncertainty map."""
    return tuple(
        MappingProxyType(
            {
                "speed_min_kmh": float(speed_bin["speed_min_kmh"]),
                "speed_max_kmh": float(speed_bin["speed_max_kmh"]),
                **{kind: MappingProxyType(dict(speed_bin[kind])) for kind in UNCERTAINTY_CHANNELS},
            }
        )
        for speed_bin in bins
    )


def _validate_uncertainty_bins(bins: tuple[Mapping, ...]) -> None:
    """Validate schema-v3 runtime uncertainty data before the QSS can consume it."""
    if not isinstance(bins, (tuple, list)):
        raise ValueError("uncertainty_bins must be a list or tuple")
    previous_hi = None
    for index, speed_bin in enumerate(bins):
        if not isinstance(speed_bin, Mapping):
            raise ValueError(f"uncertainty_bins[{index}] must be a dict")
        expected = {"speed_min_kmh", "speed_max_kmh", *UNCERTAINTY_CHANNELS}
        if set(speed_bin) != expected:
            raise ValueError(
                f"uncertainty_bins[{index}] fields must be exactly {sorted(expected)!r}"
            )
        lo = speed_bin["speed_min_kmh"]
        hi = speed_bin["speed_max_kmh"]
        if (
            isinstance(lo, bool)
            or isinstance(hi, bool)
            or not _finite_ggv(lo, hi)
            or float(lo) < 0.0
            or float(hi) <= float(lo)
            or float(hi) > DEFAULT_UNCERTAINTY_MAX_KMH
        ):
            raise ValueError(f"uncertainty_bins[{index}] has an unsafe speed range")
        if previous_hi is not None and not math.isclose(float(lo), previous_hi):
            raise ValueError("uncertainty_bins must be contiguous and sorted")
        previous_hi = float(hi)
        for kind in UNCERTAINTY_CHANNELS:
            channel = speed_bin[kind]
            if not isinstance(channel, Mapping):
                raise ValueError(f"uncertainty_bins[{index}].{kind} must be a dict")
            required = {"mean_g", "epistemic_std_g", "safe_g", "n", "source"}
            if set(channel) != required:
                raise ValueError(
                    f"uncertainty_bins[{index}].{kind} fields must be exactly {sorted(required)!r}"
                )
            mean = channel["mean_g"]
            std = channel["epistemic_std_g"]
            safe = channel["safe_g"]
            n = channel["n"]
            source = channel["source"]
            if (
                any(isinstance(value, bool) for value in (mean, std, safe, n))
                or not _finite_ggv(mean, std)
                or not _finite_ggv(safe)
                or float(mean) <= 0.0
                or float(std) < 0.0
                or float(safe) <= 0.0
                or float(safe) > float(mean) + 1e-9
                or not isinstance(n, int)
                or n < 0
                or source not in {"measured", "prior"}
            ):
                raise ValueError(f"uncertainty_bins[{index}].{kind} is invalid")
    if bins and (
        not math.isclose(float(bins[0]["speed_min_kmh"]), 0.0)
        or not math.isclose(float(bins[-1]["speed_max_kmh"]), DEFAULT_UNCERTAINTY_MAX_KMH)
        or len(bins) != int(DEFAULT_UNCERTAINTY_MAX_KMH / DEFAULT_UNCERTAINTY_BIN_KMH)
        or any(
            not math.isclose(
                float(speed_bin["speed_max_kmh"]) - float(speed_bin["speed_min_kmh"]),
                DEFAULT_UNCERTAINTY_BIN_KMH,
            )
            for speed_bin in bins
        )
    ):
        raise ValueError("uncertainty_bins must cover the complete 30x10 km/h runtime grid")


def _validate_supported_longitudinal(
    supported: Mapping,
    *,
    brake_b0_g: float,
    brake_b1: float,
    drive_b0_g: float,
    drive_b1: float,
    ax_brake_cap_g: float,
) -> None:
    """Validate every runtime-bearing measured override against the trusted prior.

    The artifact's free-form ``provenance`` is observability only. Supported curves have their own
    schema and are accepted only when the same deterministic safety gates used by
    :func:`blend_ggv_safe` still hold after deserialization.
    """
    if not isinstance(supported, Mapping):
        raise ValueError("supported_longitudinal must be a dict")
    unknown = set(supported) - {"brake", "drive"}
    if unknown:
        raise ValueError(f"unsupported longitudinal override keys: {sorted(unknown)!r}")
    for kind, override in supported.items():
        if not isinstance(override, Mapping):
            raise ValueError(f"supported_longitudinal.{kind} must be a dict")
        required = {"speed_min_kmh", "speed_max_kmh", "b0_g", "b1", "floor_g", "taper_kmh"}
        if set(override) != required:
            raise ValueError(
                f"supported_longitudinal.{kind} fields must be exactly {sorted(required)!r}"
            )
        raw = [override[name] for name in sorted(required)]
        if any(isinstance(value, bool) for value in raw) or not _finite_ggv(*raw):
            raise ValueError(f"supported_longitudinal.{kind} contains non-finite fields")
        lo_kmh = float(override["speed_min_kmh"])
        hi_kmh = float(override["speed_max_kmh"])
        b0_g = float(override["b0_g"])
        b1 = float(override["b1"])
        floor_g = float(override["floor_g"])
        taper_kmh = float(override["taper_kmh"])
        span_kmh = hi_kmh - lo_kmh
        if (
            lo_kmh < 0.0
            or hi_kmh > MAX_LONGITUDINAL_SUPPORT_KMH
            or span_kmh < MIN_LONGITUDINAL_SUPPORT_KMH
            or taper_kmh <= 0.0
            or taper_kmh > span_kmh / 2.0
            or floor_g < 0.0
        ):
            raise ValueError(f"supported_longitudinal.{kind} has an unsafe range/taper/floor")
        v_lo, v_hi = lo_kmh / 3.6, hi_kmh / 3.6
        if kind == "brake":
            if floor_g != 0.5 or b1 < 0.0:
                raise ValueError("supported brake override requires floor_g=0.5 and b1>=0")
            if not _brake_curve_is_supported(b0_g, b1, brake_b0_g, brake_b1, v_lo=v_lo, v_hi=v_hi):
                raise ValueError(
                    "supported brake override is not consistently above/below its trusted prior"
                )
            if max(b0_g + b1 * v_lo, b0_g + b1 * v_hi) > ax_brake_cap_g:
                raise ValueError("supported brake override exceeds the trusted brake cap")
        else:
            if floor_g > MAX_DRIVE_SUPPORT_G:
                raise ValueError("supported drive floor exceeds the physical safety cap")
            if not _curve_exceeds(b0_g, b1, drive_b0_g, drive_b1, v_lo=v_lo, v_hi=v_hi):
                raise ValueError("supported drive override no longer exceeds its trusted prior")
            if max(floor_g, b0_g + b1 * v_lo, b0_g + b1 * v_hi) > MAX_DRIVE_SUPPORT_G:
                raise ValueError("supported drive override exceeds the physical safety cap")


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

    NOTE: this AiPointExtra layout drifts across CSP / track-tool versions (``ai_line.py`` declines
    to parse it for that reason). The stride/offsets here are validated against this rig's Magione
    ``fast_lane.ai``; the size guards below catch truncation but NOT a same-size layout change. If
    ``sideLeft``/``sideRight`` read as absurd widths on a re-baked AI line, re-derive the layout.
    """
    data = Path(path).read_bytes()
    if len(data) < _FAST_LANE_MIN_BYTES:
        raise ValueError(f"{path} is too small to be a fast_lane.ai file")
    _ver, count, _lap, _samp = struct.unpack_from("<4i", data, 0)
    if count <= 0:
        raise ValueError(f"{path} has invalid AI point count: {count}")
    es = _FAST_LANE_HEADER_BYTES + count * _AI_POINT_STRIDE_BYTES + _LAP_EXTRA_BYTES
    needed = es + count * _AI_EXTRA_STRIDE_BYTES
    if len(data) < needed:
        raise ValueError(
            f"{path} is truncated: expected at least {needed} bytes for {count} AI extras, "
            f"got {len(data)}"
        )
    left: list[float] = []
    right: list[float] = []
    for i in range(count):
        sl, sr = struct.unpack_from(
            "<2f", data, es + i * _AI_EXTRA_STRIDE_BYTES + _AI_EXTRA_SIDELEFT_OFFSET_BYTES
        )
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


# Apex solve budget. The fixed point converges in a handful of steps where ``ay_max`` is smooth;
# the descent guard then needs at most one step per uncertainty bin it walks down through.
_APEX_FIXED_POINT_STEPS = 8
_APEX_DESCENT_STEPS = 64


def apex_speed(
    kappa: float,
    ggv: GGVModel,
    *,
    v_top_ms: float,
    v_floor_ms: float = 0.0,
) -> float:
    """Largest speed at ``kappa`` whose lateral demand fits the envelope: ``v²·κ <= ay_max(v)``.

    ``GGVModel.ay_max`` is **not continuous in v** — :meth:`GGVModel._uncertainty_safe_g` selects
    ``safe_g`` from discrete speed bins (#543), so the envelope is a step function of speed. A bare
    fixed point ``v <- sqrt(ay_max(v)/κ)`` on a discontinuous map need not converge: it can settle
    on the *high* branch of a bin edge, where the speed it returns lands in a lower-grip bin than
    the one used to compute it. That yields an apex the plant cannot support, which
    :func:`~tools.ac_harness.alien_line._verify_lateral_envelope` then rejects with its float-noise
    tolerance — the solver handing its own verifier infeasible input (#695: 445/3960 curvature
    samples violating on a real Magione plant, worst 1.40x).

    So iterate, then **descend until the constraint actually holds**. A violation means
    ``ay_max(v) < v²·κ``, so the corrective iterate is strictly smaller; with finitely many bins the
    descent terminates. The returned speed satisfies the envelope by construction, not by assertion.

    ``v_floor_ms`` is a drivability floor and is applied only when it does not break the envelope —
    raising an infeasible corner back over the limit would reintroduce the same defect.
    """
    if kappa <= 0.0:
        return v_top_ms
    vi = v_top_ms
    for _ in range(_APEX_FIXED_POINT_STEPS):
        vi = min(v_top_ms, math.sqrt(ggv.ay_max(vi) / kappa))
    for _ in range(_APEX_DESCENT_STEPS):
        ay_limit = ggv.ay_max(vi)
        if vi * vi * kappa <= ay_limit:
            break
        # Strictly decreasing: ay_limit < vi²·κ here, so sqrt(ay_limit/κ) < vi.
        vi = math.sqrt(ay_limit / kappa)
    if v_floor_ms > vi and v_floor_ms * v_floor_ms * kappa <= ggv.ay_max(v_floor_ms):
        return v_floor_ms
    return vi


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

    1. apex speed from lateral grip (:func:`apex_speed` — envelope-feasible by construction even
       though the uncertainty-aware grip is a step function of v);
    2. backward pass: braking limited by the friction ellipse with speed-dependent grip;
    3. forward pass: accel limited by ellipse + traction/power cap.
    Returns (v_target_ms per point, ax_ff per point [m/s^2, +accel/-decel]).
    """
    n = len(kappa)
    # 1) apex (envelope-feasible by construction; ay_max is a step function of v — see apex_speed)
    v = [v_top_ms] * n
    for i in range(n):
        k = kappa[i]
        if k > 1e-6:
            v[i] = apex_speed(k, ggv, v_top_ms=v_top_ms, v_floor_ms=v_floor_ms)
    # The drivability floor is per-point: a corner whose feasible apex is below ``v_floor_ms`` must
    # keep its apex, otherwise the propagation passes would clamp it back over the lateral envelope
    # and hand the verifier the very infeasible profile the apex solve just avoided (#695).
    floor = [min(v_floor_ms, v[i]) for i in range(n)]
    # 2) backward (braking) - ellipse uses the lateral g implied by apex usage
    for _ in range(passes):
        for j in range(n):
            i = (n - 1 - j) % n
            nx = (i + 1) % n
            ds = seg[i]
            if ds <= 1e-6:  # coincident points must share speed, else propagation chain breaks
                if v[nx] < v[i]:
                    v[i] = max(floor[i], v[nx])
                continue
            ay_used = v[i] * v[i] * kappa[i]
            ax = ggv.ax_brake_avail(ay_used, v[i])
            cap = math.sqrt(v[nx] * v[nx] + 2.0 * ax * ds)
            if cap < v[i]:
                v[i] = max(floor[i], cap)
    # 3) forward (accel)
    for _ in range(passes):
        for i in range(n):
            pv = (i - 1) % n
            ds = seg[pv]
            if ds <= 1e-6:  # coincident points must share speed
                if v[pv] < v[i]:
                    v[i] = max(floor[i], v[pv])
                continue
            ay_used = v[pv] * v[pv] * kappa[pv]
            ax = ggv.ax_drive_avail(ay_used, v[pv])
            cap = math.sqrt(v[pv] * v[pv] + 2.0 * ax * ds)
            if cap < v[i]:
                v[i] = max(floor[i], cap)
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
    if len(fast_line) < 3:
        raise ValueError("ggv_speed_profile_from_model requires at least 3 points")
    plane = [(p[0], p[2]) for p in fast_line]
    seg = seg_lengths(plane)
    kappa = curvature_profile(plane, smooth_win=smooth_win, span=span)
    v, _ax = forward_backward_profile(kappa, seg, ggv, v_top_ms=v_top_kmh / 3.6)
    if len(seg) != len(v) or len(seg) != len(kappa):
        raise ValueError(
            f"profile arrays length mismatch: seg={len(seg)}, kappa={len(kappa)}, v={len(v)}"
        )
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
        # speed-dependent aero lateral grip: ay_max(v) = mu + k*v^2. Lifts the aero ceiling cap too.
        # CAUTION (live-disproven at Magione 2026-06-19): this is an OFFLINE model UPPER BOUND, not
        # an achievable target. The QSS it predicts (e.g. k=0.0005 -> ~70.9s) was NOT reproduced
        # live: the GT3 R lacks this much downforce-lateral grip at Magione speeds -- k>=0.0003 made
        # the car spin out (96s with teleports; k=0.0001 also spun). Use only as a what-if ceiling;
        # do NOT feed an aero-inflated v_target to a live controller. See issue #244.
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
