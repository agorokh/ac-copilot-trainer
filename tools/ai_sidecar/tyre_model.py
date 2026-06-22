"""Tyre thermal model: optimal window, warm-up, degradation, imbalance, hot-pressure estimate.

Consumes per-wheel CORE temperature (CSP ``tyreCoreTemperature``, persisted by #266) + cold pressure
(setup) and produces a pro-engineer tyre read. Pure stdlib.

Grounded in adversarially-verified research (see
``docs/01_Vault/AcCopilotTrainer/03_Investigations/tyre-thermal-knowledge-2026-06-21.md``). The
red-team corrections are encoded here and must NOT be "simplified" away:

* **Core is a BULK average** — no edge/surface temp, so window/onset/blistering calls are
  inferences, never definitive. We report a degradation-onset *band*, not a blistering diagnosis.
* **Pressure↔core coupling is gas-law** ~+1 psi / 10 °C (≈0.013 psi/°C·psi). Hot pressure here is
  **modelled** from cold + coupling, never measured (CSP is read-only for live pressure).
* **Thermal overheat and mechanical wear both raise core temp** — core alone cannot separate them.
* **Left-right (and weakly front-rear) asymmetry is confounded by track corner-direction bias** — a
  balance finding is a ranked HYPOTHESIS pending a reference-lap comparison, not a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_WHEELS = ("fl", "fr", "rl", "rr")

# --- verified parameters (°C core, bulk-average) ---------------------------
#: Optimal core-temp window per compound key. "slick" is the generic fallback when compound is
#: unknown (compound identity is NOT in the telemetry feed — see module docstring).
COMPOUND_WINDOWS: dict[str, tuple[float, float]] = {
    "soft": (70.0, 100.0),
    "medium": (75.0, 105.0),
    "hard": (80.0, 110.0),
    "wet": (55.0, 80.0),
    "slick": (75.0, 105.0),  # generic slick fallback (medium-ish)
}
GRIP_ONSET_C = 40.0  # below ~35-45: too cold to make meaningful grip
DEG_WARN_C = 103.0  # 100-105 degradation-onset band (grip roll-off region)
CRITICAL_C = 115.0  # >115 soft / ~130-140 hard: thermal-risk back-off trigger

# pressure↔core coupling (ideal gas, constant V): ~+1 psi per 10 °C at GT3 pressures
PRESSURE_PSI_PER_DEGC = 0.12
HOT_PRESSURE_WINDOW = (26.0, 29.0)  # GT3 target HOT psi
_COLD_CORE_REF_C = 25.0  # nominal cold-tyre core for the hot-pressure delta estimate

# imbalance thresholds (°C)
AXLE_IMBALANCE_C = 10.0  # |front_avg - rear_avg| beyond natural ~4-8
SIDE_IMBALANCE_C = 7.0  # |left_avg - right_avg| (heavily track-direction confounded)
WHEEL_OUTLIER_C = 15.0  # a single corner this far from its pair-mate
BALANCED_SPREAD_C = 5.0  # all four within this = thermally balanced

# warm-up
WARMUP_RISE_C_PER_LAP = 2.0  # core rising faster than this early = still warming


@dataclass(frozen=True)
class TyreFinding:
    """One tyre observation: what it is, how confident, and what to do (honest about data)."""

    key: str
    summary: str
    severity: str  # "info" | "caution" | "act"
    core_only: bool  # True = computable from core temp alone; False = needs richer channels
    coaching: str
    confidence: str  # "high" | "medium" | "low"


@dataclass
class TyreReport:
    """Per-wheel + whole-car tyre-thermal read for one lap."""

    compound: str
    window: tuple[float, float]
    core: dict[str, float]  # fl/fr/rl/rr core temp (°C)
    status: dict[str, str]  # per-wheel: cold|warming|in_window|overheat|critical
    mean_core: float
    front_minus_rear: float | None
    left_minus_right: float | None
    spread: float
    hot_pressure_est: dict[str, float]  # modelled psi per wheel (estimate)
    warming: bool
    findings: list[TyreFinding] = field(default_factory=list)

    def headline(self) -> str:
        bad = [w for w, s in self.status.items() if s in ("overheat", "critical", "cold")]
        if any(self.status[w] == "critical" for w in self.status):
            return (
                f"TYRES CRITICAL: {', '.join(w.upper() for w in bad)} over-temp — back off / box."
            )
        if self.warming:
            return f"Tyres warming (mean core {self.mean_core:.0f}°C) — build heat before pushing."
        if bad:
            return f"Tyres off-window: {', '.join(w.upper() for w in bad)} ({self.compound})."
        return f"Tyres in window ({self.compound}, mean core {self.mean_core:.0f}°C)."


def _status_for(core: float, window: tuple[float, float]) -> str:
    lo, hi = window
    if core >= CRITICAL_C:
        return "critical"
    if core > hi:
        return "overheat"
    if core < GRIP_ONSET_C:
        return "cold"
    if core < lo:
        return "warming"
    return "in_window"


def _hot_pressure_est(cold_psi: float, core: float) -> float:
    """Modelled hot pressure: cold + gas-law coupling over the core rise from a nominal cold ref."""
    return round(cold_psi + PRESSURE_PSI_PER_DEGC * (core - _COLD_CORE_REF_C), 2)


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def analyze_tyres(
    core: dict[str, float],
    cold_pressure: dict[str, float] | None = None,
    *,
    compound: str | None = None,
    prev_core: dict[str, float] | None = None,
    laps_since_start: int | None = None,
) -> TyreReport:
    """Analyze a lap's per-wheel core temps (+ optional cold pressures, compound, previous lap).

    ``core``/``cold_pressure`` are ``{fl,fr,rl,rr: value}`` (missing wheels tolerated). ``compound``
    is one of COMPOUND_WINDOWS keys; unknown → generic ``slick``. ``prev_core`` +
    ``laps_since_start`` drive warm-up vs steady classification. Returns a :class:`TyreReport`.
    """
    comp = (compound or "slick").lower()
    window = COMPOUND_WINDOWS.get(comp, COMPOUND_WINDOWS["slick"])
    core = {w: float(core[w]) for w in _WHEELS if w in core and core[w] is not None}
    status = {w: _status_for(core[w], window) for w in core}
    present = list(core.values())
    mean_core = round(_mean(present), 1)
    spread = round(max(present) - min(present), 1) if present else 0.0

    front = [core[w] for w in ("fl", "fr") if w in core]
    rear = [core[w] for w in ("rl", "rr") if w in core]
    left = [core[w] for w in ("fl", "rl") if w in core]
    right = [core[w] for w in ("fr", "rr") if w in core]
    fmr = round(_mean(front) - _mean(rear), 1) if front and rear else None
    lmr = round(_mean(left) - _mean(right), 1) if left and right else None

    hot_est: dict[str, float] = {}
    if cold_pressure:
        for w in core:
            cp = cold_pressure.get(w)
            if cp is not None:
                hot_est[w] = _hot_pressure_est(float(cp), core[w])

    # warm-up: cold/below-window mean AND (rising fast OR within first 2 laps)
    rising_fast = False
    if prev_core:
        rises = [core[w] - prev_core[w] for w in core if w in prev_core]
        rising_fast = bool(rises) and _mean(rises) > WARMUP_RISE_C_PER_LAP
    early = laps_since_start is not None and laps_since_start <= 2
    warming = (
        bool(present)
        and mean_core < window[0]
        and (rising_fast or early or laps_since_start is None)
    )

    findings = _build_findings(core, status, window, comp, mean_core, fmr, lmr, spread, hot_est)
    return TyreReport(
        compound=comp,
        window=window,
        core=core,
        status=status,
        mean_core=mean_core,
        front_minus_rear=fmr,
        left_minus_right=lmr,
        spread=spread,
        hot_pressure_est=hot_est,
        warming=warming,
        findings=findings,
    )


def _build_findings(
    core: dict[str, float],
    status: dict[str, str],
    window: tuple[float, float],
    comp: str,
    mean_core: float,
    fmr: float | None,
    lmr: float | None,
    spread: float,
    hot_est: dict[str, float],
) -> list[TyreFinding]:
    out: list[TyreFinding] = []
    crit = [w for w, s in status.items() if s == "critical"]
    over = [w for w, s in status.items() if s == "overheat"]
    cold = [w for w, s in status.items() if s in ("cold", "warming")]
    if crit:
        out.append(
            TyreFinding(
                "critical",
                f"{', '.join(w.upper() for w in crit)} core ≥ {CRITICAL_C:.0f}°C",
                "act",
                True,
                "Thermal-risk band — back off significantly or box. (A risk trigger, not a "
                "blistering diagnosis: core is a bulk average.)",
                "low",
            )
        )
    if over:
        out.append(
            TyreFinding(
                "overheat",
                f"{', '.join(w.upper() for w in over)} above the {comp} window "
                f"(> {window[1]:.0f}°C)",
                "act",
                True,
                "Reduce thermal load: ease exit throttle, smoother brake/steer; if it persists, "
                "raise cold pressure or pick a harder compound.",
                "medium",
            )
        )
    if cold:
        out.append(
            TyreFinding(
                "cold",
                f"{', '.join(w.upper() for w in cold)} below the {comp} window "
                f"(< {window[0]:.0f}°C)",
                "caution",
                True,
                "Still building heat — one or two more laps, or load the tyre harder; surface temp "
                "(the true grip layer) is not measurable, so this is approximate.",
                "low",
            )
        )
    if fmr is not None and abs(fmr) > AXLE_IMBALANCE_C:
        hotter = "front" if fmr > 0 else "rear"
        out.append(
            TyreFinding(
                "axle_imbalance",
                f"{hotter} axle hotter by {abs(fmr):.0f}°C",
                "caution",
                True,
                f"Check the cold-pressure split first; then a {hotter}-bias hypothesis (brake "
                "bias / ARB / camber). Ranked hypotheses, not a verdict.",
                "medium",
            )
        )
    if lmr is not None and abs(lmr) > SIDE_IMBALANCE_C:
        out.append(
            TyreFinding(
                "side_imbalance",
                f"left-right core differs by {abs(lmr):.0f}°C",
                "info",
                True,
                "HIGH confound: a track with directional corners produces this naturally. Only "
                "actionable vs a reference lap / known-symmetric circuit.",
                "low",
            )
        )
    # single-wheel outlier vs its axle pair-mate
    for a, b in (("fl", "fr"), ("fr", "fl"), ("rl", "rr"), ("rr", "rl")):
        if a in core and b in core and core[a] - core[b] > WHEEL_OUTLIER_C:
            out.append(
                TyreFinding(
                    "wheel_outlier",
                    f"{a.upper()} ≫ {b.upper()} by {core[a] - core[b]:.0f}°C",
                    "caution",
                    True,
                    f"Check {a.upper()} cold pressure + camber vs its pair-mate; one corner is "
                    "loading/heating asymmetrically.",
                    "low",
                )
            )
    if hot_est:
        high = [w for w, p in hot_est.items() if p > HOT_PRESSURE_WINDOW[1]]
        low = [w for w, p in hot_est.items() if p < HOT_PRESSURE_WINDOW[0]]
        if high:
            out.append(
                TyreFinding(
                    "hot_pressure_high",
                    f"modelled hot pressure high on {', '.join(w.upper() for w in high)} "
                    f"(> {HOT_PRESSURE_WINDOW[1]:.0f} psi)",
                    "caution",
                    False,
                    "Drop cold pressure ~0.5 psi to bring hot pressure into the 26-29 window. "
                    "NOTE: hot pressure is MODELLED from cold + gas-law, not measured.",
                    "low",
                )
            )
        if low:
            out.append(
                TyreFinding(
                    "hot_pressure_low",
                    f"modelled hot pressure low on {', '.join(w.upper() for w in low)} "
                    f"(< {HOT_PRESSURE_WINDOW[0]:.0f} psi)",
                    "caution",
                    False,
                    "Raise cold pressure ~0.5 psi. Modelled estimate, not measured.",
                    "low",
                )
            )
    if not out and spread <= BALANCED_SPREAD_C and mean_core >= window[0]:
        out.append(
            TyreFinding(
                "balanced",
                f"all four within {BALANCED_SPREAD_C:.0f}°C, in window",
                "info",
                True,
                "Thermally balanced — no tyre tuning needed; focus on pace/consistency.",
                "medium",
            )
        )
    return out


def tyres_from_lap_archive(archive: dict) -> TyreReport | None:
    """Build a :class:`TyreReport` from a lap archive's per-wheel ``tyreCoreTemp_*`` trace columns.

    Averages each wheel's core temp over the lap (the trace carries per-sample core temps, #266).
    Returns None if the archive has no per-wheel temp channels. Compound/cold-pressure are read from
    the setup snapshot when present (compound index → unknown name, so falls back to generic slick).
    """
    trace = archive.get("trace") if isinstance(archive, dict) else None
    if not isinstance(trace, dict):
        return None
    fields = trace.get("fields")
    samples = trace.get("samples")
    if not isinstance(fields, list) or not isinstance(samples, list) or not samples:
        return None
    idx = {w: fields.index(f"tyreCoreTemp_{w}") for w in _WHEELS if f"tyreCoreTemp_{w}" in fields}
    if not idx:
        return None
    sums = {w: 0.0 for w in idx}
    counts = {w: 0 for w in idx}
    for row in samples:
        for w, i in idx.items():
            try:
                v = float(row[i])
            except (TypeError, ValueError, IndexError):
                continue
            if v != 0.0:  # 0 = unread sentinel (see #266 all-zero guard)
                sums[w] += v
                counts[w] += 1
    core = {w: round(sums[w] / counts[w], 1) for w in idx if counts[w] > 0}
    if not core:
        return None
    setup = archive.get("setup") if isinstance(archive.get("setup"), dict) else {}
    snap = setup.get("snapshot") if isinstance(setup.get("snapshot"), dict) else {}
    cold = {}
    for w in _WHEELS:
        key = f"PRESSURE_{w.upper()}.VALUE"
        if key in snap:
            try:
                cold[w] = float(snap[key])
            except (TypeError, ValueError):
                pass
    return analyze_tyres(core, cold or None)
