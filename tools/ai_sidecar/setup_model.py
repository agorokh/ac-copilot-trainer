"""Typed, semantic comprehension of an Assetto Corsa car setup.

The harness already captures a ``setup.snapshot`` per lap archive and the rig can read/write
live setup values via ``ac.getSetupSpinners()`` / ``ac.setSetupSpinnerValue()``. This module turns
that raw ``{SECTION.KEY: value}`` blob into a :class:`CarSetup` whose parameters are *named, unit-
aware, and categorized* — so the corner-attribution / coaching layer can reason about **which knob a
symptom points to** ("entry understeer + front bias 66% → move FRONT_BIAS rearward") instead of an
opaque number vector.

Ground truth for the section layout is the verified glossary node
``docs/01_Vault/AcCopilotTrainer/00_System/glossary/ac-setup-ini-format.md`` (confirmed against
``ks_porsche_911_gt3_r_2016`` and ``bmw_m3_gt2``): each setting is a ``[SECTION]`` with a single
``VALUE=<int>`` key; per-corner settings carry an ``_LF/_RF/_LR/_RR`` suffix. Pure stdlib.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- categories -------------------------------------------------------------
BRAKES = "brakes"
TIRES = "tires"
AERO = "aero"
BALANCE = "balance"
DRIVETRAIN = "drivetrain"
SUSPENSION = "suspension"
GEARING = "gearing"
FUEL = "fuel"
META = "meta"
OTHER = "other"

# corner suffixes for per-wheel settings
_CORNERS = ("LF", "RF", "LR", "RR")
_CORNER_LABEL = {"LF": "front-left", "RF": "front-right", "LR": "rear-left", "RR": "rear-right"}


@dataclass(frozen=True)
class ParamSpec:
    """Semantic description of one AC setup section (what it is, not its value)."""

    section: str  # canonical AC [SECTION] (corner-resolved, e.g. PRESSURE_LF)
    human_name: str
    category: str
    units: str = ""
    summary: str = ""  # one-line "what it does"
    corner: str | None = None  # LF/RF/LR/RR when this is a per-corner setting
    car_specific: bool = False  # true when meaning depends on the car (e.g. WING_1)


# Base specs for non-per-corner sections (verified glossary). Per-corner specs are derived.
_BASE_SPECS: dict[str, ParamSpec] = {
    "FRONT_BIAS": ParamSpec(
        "FRONT_BIAS",
        "Brake bias (front)",
        BRAKES,
        "% front",
        "Front share of braking force. Higher = more front braking (stable but front-locks).",
    ),
    "BRAKE_POWER_MULT": ParamSpec(
        "BRAKE_POWER_MULT",
        "Brake power",
        BRAKES,
        "%",
        "Overall brake force scalar. Higher = shorter stops but easier to lock.",
    ),
    "ABS": ParamSpec(
        "ABS",
        "ABS level",
        BRAKES,
        "level",
        "Anti-lock aggressiveness (0=off). Higher intervenes earlier; can lengthen braking.",
    ),
    "TRACTION_CONTROL": ParamSpec(
        "TRACTION_CONTROL",
        "Traction control",
        DRIVETRAIN,
        "level",
        "On-throttle wheelspin limiter (0=off). Higher cuts power earlier on exit.",
    ),
    "WING_1": ParamSpec(
        "WING_1",
        "Front wing / splitter",
        AERO,
        "clicks",
        "Front downforce element (GT3). More = front grip at speed, costs drag.",
        car_specific=True,
    ),
    "WING_2": ParamSpec(
        "WING_2",
        "Rear wing",
        AERO,
        "clicks",
        "Rear downforce. More = high-speed stability/rear grip, costs top speed.",
        car_specific=True,
    ),
    "ARB_FRONT": ParamSpec(
        "ARB_FRONT",
        "Anti-roll bar (front)",
        BALANCE,
        "level",
        "Front roll stiffness. Stiffer = more understeer (less front mechanical grip).",
    ),
    "ARB_REAR": ParamSpec(
        "ARB_REAR",
        "Anti-roll bar (rear)",
        BALANCE,
        "level",
        "Rear roll stiffness. Stiffer = more oversteer (less rear mechanical grip).",
    ),
    "DIFF_POWER": ParamSpec(
        "DIFF_POWER",
        "Differential (power)",
        DRIVETRAIN,
        "%",
        "On-throttle LSD lock. Higher = more exit traction but more exit understeer.",
    ),
    "DIFF_COAST": ParamSpec(
        "DIFF_COAST",
        "Differential (coast)",
        DRIVETRAIN,
        "%",
        "Off-throttle LSD lock. Higher = more entry stability but less rotation.",
    ),
    "FINAL_RATIO": ParamSpec(
        "FINAL_RATIO",
        "Final drive",
        GEARING,
        "ratio",
        "Overall gearing. Higher = more acceleration, lower top speed.",
    ),
    "FUEL": ParamSpec("FUEL", "Fuel", FUEL, "L", "Fuel load (mass affects grip/pace)."),
    "TYRES": ParamSpec(
        "TYRES",
        "Tyre compound",
        TIRES,
        "index",
        "Compound index into the car's tyre list. Softer = more peak grip, faster wear.",
    ),
}

# Per-corner section prefixes -> (human stem, category, units, summary stem).
_PER_CORNER: dict[str, tuple[str, str, str, str]] = {
    "PRESSURE": (
        "Cold pressure",
        TIRES,
        "psi",
        "Cold tyre pressure. Too high/low moves hot pressure off the grip window.",
    ),
    "CAMBER": (
        "Camber",
        TIRES,
        "deg",
        "Static camber (negative). More = mid-corner grip, less braking/traction grip.",
    ),
    "TOE_OUT": (
        "Toe",
        SUSPENSION,
        "deg",
        "Toe angle. Toe-out aids turn-in; toe-in aids stability; both add drag/wear.",
    ),
    "SPRING_RATE": (
        "Spring rate",
        SUSPENSION,
        "N/mm",
        "Wheel-rate stiffness. Stiffer = sharper response, less mechanical grip.",
    ),
    "DAMP_BUMP": ("Bump damper", SUSPENSION, "clicks", "Compression damping."),
    "DAMP_FAST_BUMP": ("Fast bump damper", SUSPENSION, "clicks", "High-speed compression damping."),
    "DAMP_REBOUND": ("Rebound damper", SUSPENSION, "clicks", "Extension damping."),
    "DAMP_FAST_REBOUND": ("Fast rebound damper", SUSPENSION, "clicks", "High-speed rebound."),
    "ROD_LENGTH": ("Ride height", SUSPENSION, "mm", "Ride height / rod length per corner."),
    "PACKER_RANGE": ("Packer", SUSPENSION, "mm", "Bump-stop gap."),
    "BUMP_STOP_RATE": ("Bump-stop rate", SUSPENSION, "N/mm", "Bump-stop stiffness."),
    "INTERNAL_GEAR": ("Gear ratio", GEARING, "ratio", "Individual gear ratio."),
}

_META_SECTIONS = {"CAR", "ABOUT", "__EXT_PATCH", "HEADER", "BASIC"}


def _split_corner(section: str) -> tuple[str, str | None]:
    """('PRESSURE_LF') -> ('PRESSURE', 'LF'); ('FRONT_BIAS') -> ('FRONT_BIAS', None)."""
    for c in _CORNERS:
        if section.endswith("_" + c):
            return section[: -(len(c) + 1)], c
    return section, None


def spec_for(section: str) -> ParamSpec:
    """Resolve the :class:`ParamSpec` for an AC section name (corner-aware)."""
    sec = section.strip().upper()
    if sec in _BASE_SPECS:
        return _BASE_SPECS[sec]
    stem, corner = _split_corner(sec)
    if corner is not None and stem in _PER_CORNER:
        name, cat, units, summary = _PER_CORNER[stem]
        label = f"{name} ({_CORNER_LABEL[corner]})"
        return ParamSpec(sec, label, cat, units, summary, corner=corner)
    if sec in _META_SECTIONS or sec.startswith("__EXT"):
        return ParamSpec(sec, sec.title(), META)
    # unknown but maybe a known per-corner stem without a corner, or a novel section
    if stem in _PER_CORNER:
        name, cat, units, summary = _PER_CORNER[stem]
        return ParamSpec(sec, name, cat, units, summary)
    return ParamSpec(sec, sec.replace("_", " ").title(), OTHER)


@dataclass(frozen=True)
class SetupParam:
    """One resolved setup setting: its spec plus the actual value."""

    section: str
    value: float | None  # parsed numeric value (None if non-numeric, e.g. a name)
    raw: str  # original string value
    spec: ParamSpec

    @property
    def category(self) -> str:
        return self.spec.category

    @property
    def is_tunable(self) -> bool:
        return self.spec.category not in (META,) and self.value is not None

    def describe(self) -> str:
        v = self.raw if self.value is None else _fmt_num(self.value)
        unit = f" {self.spec.units}" if self.spec.units else ""
        return f"{self.spec.human_name}: {v}{unit}"


def _fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# --- the setup --------------------------------------------------------------
@dataclass
class CarSetup:
    """A parsed, semantic Assetto Corsa setup.

    ``params`` is keyed by canonical ``SECTION`` (corner-resolved). Convenience accessors expose the
    coaching-relevant knobs; :meth:`by_category` and :meth:`human_summary` give grouped/readable
    views; :meth:`diff` powers setup A/B attribution.
    """

    params: dict[str, SetupParam] = field(default_factory=dict)
    car_id: str | None = None
    track_id: str | None = None
    spinner_schema: dict[str, Any] | None = None  # full getSetupSpinners() descriptors

    # -- raw access --
    def value(self, section: str) -> float | None:
        p = self.params.get(section.strip().upper())
        return p.value if p else None

    def get(self, section: str) -> SetupParam | None:
        return self.params.get(section.strip().upper())

    # -- semantic accessors (None when the car/setup doesn't expose the knob) --
    @property
    def brake_bias_pct(self) -> float | None:
        return self.value("FRONT_BIAS")

    @property
    def abs_level(self) -> float | None:
        return self.value("ABS")

    @property
    def tc_level(self) -> float | None:
        return self.value("TRACTION_CONTROL")

    @property
    def brake_power_pct(self) -> float | None:
        return self.value("BRAKE_POWER_MULT")

    @property
    def wing_front(self) -> float | None:
        return self.value("WING_1")

    @property
    def wing_rear(self) -> float | None:
        return self.value("WING_2")

    @property
    def arb_front(self) -> float | None:
        return self.value("ARB_FRONT")

    @property
    def arb_rear(self) -> float | None:
        return self.value("ARB_REAR")

    @property
    def diff_power(self) -> float | None:
        return self.value("DIFF_POWER")

    @property
    def diff_coast(self) -> float | None:
        return self.value("DIFF_COAST")

    @property
    def compound_index(self) -> float | None:
        return self.value("TYRES")

    @property
    def fuel(self) -> float | None:
        return self.value("FUEL")

    def tire_pressures(self) -> dict[str, float]:
        """{'LF': 27.5, ...} for whatever corners are present."""
        out: dict[str, float] = {}
        for c in _CORNERS:
            v = self.value(f"PRESSURE_{c}")
            if v is not None:
                out[c] = v
        return out

    def cambers(self) -> dict[str, float]:
        return {c: v for c in _CORNERS if (v := self.value(f"CAMBER_{c}")) is not None}

    def mean_pressure(self) -> float | None:
        ps = list(self.tire_pressures().values())
        return sum(ps) / len(ps) if ps else None

    def pressure_split(self) -> dict[str, float] | None:
        """Axle/side pressure deltas (front-rear, left-right); imbalance hints at temp asymmetry."""
        p = self.tire_pressures()
        if not {"LF", "RF", "LR", "RR"} <= p.keys():
            return None
        front = (p["LF"] + p["RF"]) / 2
        rear = (p["LR"] + p["RR"]) / 2
        left = (p["LF"] + p["LR"]) / 2
        right = (p["RF"] + p["RR"]) / 2
        return {
            "front_minus_rear": round(front - rear, 2),
            "left_minus_right": round(left - right, 2),
        }

    def arb_balance(self) -> float | None:
        """ARB_FRONT - ARB_REAR. Positive = stiffer front (understeer-biased)."""
        f, r = self.arb_front, self.arb_rear
        return None if f is None or r is None else f - r

    # -- grouped / readable --
    def tunables(self) -> dict[str, SetupParam]:
        return {k: p for k, p in self.params.items() if p.is_tunable}

    def by_category(self) -> dict[str, list[SetupParam]]:
        out: dict[str, list[SetupParam]] = {}
        for p in self.tunables().values():
            out.setdefault(p.category, []).append(p)
        for ps in out.values():
            ps.sort(key=lambda p: p.section)
        return out

    def human_summary(self) -> list[str]:
        """Readable, category-grouped lines for a debrief / screen tile."""
        lines: list[str] = []
        order = [BRAKES, DRIVETRAIN, AERO, BALANCE, TIRES, SUSPENSION, GEARING, FUEL, OTHER]
        cats = self.by_category()
        for cat in order:
            ps = cats.get(cat)
            if not ps:
                continue
            lines.append(f"[{cat}]")
            lines.extend(f"  {p.describe()}" for p in ps)
        return lines

    def diff(self, other: CarSetup) -> dict[str, dict[str, float | None]]:
        """Sections whose value differs from ``other`` -> {'from': old, 'to': new}.

        ``other`` is the baseline. Used to attribute a lap-time delta to the changed knobs.
        """
        out: dict[str, dict[str, float | None]] = {}
        keys = set(self.tunables()) | set(other.tunables())
        for k in sorted(keys):
            a = other.value(k)
            b = self.value(k)
            if a is None and b is None:
                continue
            if a is None or b is None or abs(a - b) > 1e-9:
                out[k] = {"from": a, "to": b}
        return out


# --- parsers ----------------------------------------------------------------
def parse_setup_ini(text: str) -> dict[str, str]:
    """Parse AC setup ``.ini`` text into a flat ``{SECTION.KEY: value}`` snapshot.

    AC setups are ``[SECTION]`` blocks each with (usually) ``VALUE=<n>``. We flatten to the same
    ``SECTION.KEY`` convention used by lap-archive ``setup.snapshot`` and ``setup_optimizer``.
    """
    out: dict[str, str] = {}
    section = ""
    for raw_line in text.lstrip("\ufeff").splitlines():
        line = raw_line.split(";", 1)[0].split("//", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" in line and section:
            key, _, value = line.partition("=")
            out[f"{section}.{key.strip()}"] = value.strip()
    return out


def from_snapshot(
    snapshot: dict[str, Any], *, car_id: str | None = None, track_id: str | None = None
) -> CarSetup:
    """Build a :class:`CarSetup` from a flat ``{SECTION.KEY: value}`` snapshot.

    Multiple keys may share a section (rare in AC setups); the first ``.VALUE`` key wins, else the
    first key seen for that section. Section names are upper-cased and corner-resolved.
    """
    params: dict[str, SetupParam] = {}
    for raw_key, raw_value in snapshot.items():
        section, _, key = str(raw_key).partition(".")
        section = section.strip().upper()
        if not section:
            continue
        # prefer the VALUE key for a section; don't clobber a VALUE with a non-VALUE later
        if section in params and (key or "").strip().upper() != "VALUE":
            continue
        raw = "" if raw_value is None else str(raw_value)
        params[section] = SetupParam(section, _to_float(raw_value), raw, spec_for(section))
    return CarSetup(params=params, car_id=car_id, track_id=track_id)


def from_lap_archive(lap_archive: dict[str, Any]) -> CarSetup:
    """Extract the :class:`CarSetup` from a lap-archive dict (its ``setup.snapshot``)."""
    if not isinstance(lap_archive, dict):
        return CarSetup()
    setup = lap_archive.get("setup")
    snapshot = setup.get("snapshot") if isinstance(setup, dict) else None
    if not isinstance(snapshot, dict):
        snapshot = {}
    car = lap_archive.get("car") if isinstance(lap_archive.get("car"), dict) else {}
    track = lap_archive.get("track") if isinstance(lap_archive.get("track"), dict) else {}
    return from_snapshot(
        snapshot,
        car_id=car.get("id") if isinstance(car, dict) else None,
        track_id=track.get("id") if isinstance(track, dict) else None,
    )


def load_setup_file(path: str | Path) -> CarSetup:
    """Read and parse an AC setup ``.ini`` file into a :class:`CarSetup`."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    snap = parse_setup_ini(text)
    car_id = snap.get("CAR.MODEL") or snap.get("CAR.SCREEN_NAME")
    return from_snapshot(snap, car_id=car_id)


def from_spinners(
    spinners: list[dict[str, Any]], *, car_id: str | None = None, track_id: str | None = None
) -> CarSetup:
    """Build a :class:`CarSetup` from ``ac.getSetupSpinners()`` output.

    Each spinner is ``{name, value, min, max, step, ...}``; ``name`` is the AC section. This is the
    live read path the rig uses (the same surface Pocket Technician drives).
    """
    snapshot: dict[str, Any] = {}
    schema: dict[str, dict[str, Any]] = {}
    _desc = (
        "min",
        "max",
        "step",
        "value",
        "defaultValue",
        "displayMultiplier",
        "units",
        "unit",
        "label",
        "items",
        "itemValues",
        "readOnly",
    )
    for sp in spinners:
        if not isinstance(sp, dict):
            continue
        name = sp.get("name")
        if isinstance(name, str) and name.strip():
            key = name.strip()
            snapshot[f"{key}.VALUE"] = sp.get("value")
            schema[key] = {k: sp.get(k) for k in _desc if k in sp}
    out = from_snapshot(snapshot, car_id=car_id, track_id=track_id)
    if schema:
        out.spinner_schema = schema
    return out
