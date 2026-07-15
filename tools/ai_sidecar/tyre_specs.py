"""Car-true tyre compound specs, resolved from Assetto Corsa car data (``tyres.ini``).

This is the *identity* side of the tyre story. ``tyre_model.py`` consumes **live** core
temperature and can only *infer* a compound window because "compound identity is NOT in the
telemetry feed" (see that module's docstring). This reader closes that gap: it reads the car's
own ``tyres.ini`` — the ground-truth `NAME`, physical size, cold/hot ideal pressures, peak-mu
references, and the car-specific optimal core temperature baked into the thermal
`PERFORMANCE_CURVE` — so downstream coaching can key off the *actual* compound the driver
selected (``ac.getCar().compoundIndex`` / setup ``[TYRES] VALUE``) instead of a generic guess.

Stock/Kunos cars commonly ship only ``data.acd`` rather than an unpacked ``data/`` folder.
The domain-neutral :mod:`tools.ac_content` module owns that packed-container format; this module
only resolves tyre-specific members from the decoded archive.

Everything is wrapped so a malformed / renamed / missing car degrades to ``None`` (or None-fields)
and never raises — the sidecar must not crash on one bad car.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.ac_content import CarDataSource

#: Compound index N maps to sections ``[FRONT_N]`` / ``[REAR_N]``; N==0 also matches bare
#: ``[FRONT]`` / ``[REAR]`` (AC treats the unsuffixed section as compound 0). Thermal curve lives in
#: the sibling ``[THERMAL_FRONT*]`` section.


@dataclass(frozen=True)
class TyreSpec:
    """Resolved specs for one tyre compound of one car. Every field may be ``None`` if the source
    car is missing that key (we never fabricate)."""

    compound_index: int
    name: str | None  # [FRONT_N] NAME, e.g. "Slick Soft" / "Toyo R888R"
    width_m: float | None  # WIDTH (metres)
    radius_m: float | None  # RADIUS (metres)
    rim_radius_m: float | None  # RIM_RADIUS (metres)
    size_label: (
        str | None
    )  # human size string derived from width/radius/rim; None if inputs missing
    pressure_static_psi: float | None  # PRESSURE_STATIC (ideal cold)
    pressure_ideal_psi: float | None  # PRESSURE_IDEAL (ideal hot)
    dx_ref: float | None  # DX_REF (peak longitudinal mu)
    dy_ref: float | None  # DY_REF (peak lateral mu)
    optimal_temp_c: float | None  # x at max y of the [THERMAL_*] PERFORMANCE_CURVE LUT
    version: int | None  # [HEADER] VERSION


# --------------------------------------------------------------------------------------------------
# tyres.ini resolution + tolerant INI parsing
# --------------------------------------------------------------------------------------------------

#: Per-car_dir cache of ``{archive_member_name: text}`` so repeated compound reads decrypt once.
_ARCHIVE_CACHE: dict[str, dict[str, str] | None] = {}
#: Bound the per-car archive cache. Distinct car dirs are few in practice, but a long-lived process
#: (a batch lake rebuild over many cars) must never grow it without limit (Qodo reliability nit).
_ARCHIVE_CACHE_MAX = 64

_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def _decode_text(raw: bytes) -> str:
    """Best-effort text decode of an INI/LUT member (AC data is ASCII/latin-1 in practice)."""
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _load_archive(car_dir: Path) -> dict[str, str] | None:
    """Return ``{member_name: text}`` for the car, or ``None`` if no source is readable.

    Uses the same effective-source precedence as Assetto Corsa: packed ``data.acd`` when present,
    otherwise a flat unpacked ``data/`` folder. Result cached per ``car_dir``.
    """
    cache_key = str(car_dir)
    if cache_key in _ARCHIVE_CACHE:
        return _ARCHIVE_CACHE[cache_key]

    archive: dict[str, str] | None = None
    try:
        source = CarDataSource(car_dir)
        tyres_raw = source.read_member("tyres.ini")
        if tyres_raw is not None:
            tyres_text = _decode_text(tyres_raw)
            archive = {"tyres.ini": tyres_text}
            # Load only LUTs explicitly referenced by tyres.ini. The accessor caches one packed
            # decode but reads no unrelated unpacked files, keeping sidecar startup bounded.
            for section in _parse_ini_sections(tyres_text).values():
                curve = section.get("PERFORMANCE_CURVE", "").strip()
                if not curve.lower().endswith(".lut"):
                    continue
                member = curve.replace("\\", "/").rsplit("/", 1)[-1]
                if member.lower() in archive:
                    continue
                lut_raw = source.read_member(member)
                if lut_raw is not None:
                    archive[member.lower()] = _decode_text(lut_raw)
    except (OSError, ValueError, IndexError):
        archive = None

    # Bounded insert: evict the oldest entry (dict preserves insertion order) when at capacity.
    if cache_key not in _ARCHIVE_CACHE and len(_ARCHIVE_CACHE) >= _ARCHIVE_CACHE_MAX:
        _ARCHIVE_CACHE.pop(next(iter(_ARCHIVE_CACHE)))
    _ARCHIVE_CACHE[cache_key] = archive
    return archive


def _parse_ini_sections(text: str) -> dict[str, dict[str, str]]:
    """Tolerant AC-INI parser: last-write-wins on duplicate keys, strips ``;`` inline comments,
    ignores blank/comment lines and stray junk. Section names are upper-cased for lookup."""
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        # Strip an inline comment (';'/'#') from the WHOLE line first, so a section header or key
        # with a trailing comment (e.g. "[FRONT] ; road tyre") still parses — the anchored
        # _SECTION_RE would otherwise fail to match the raw line.
        stripped = re.split(r"[;#]", line, maxsplit=1)[0].strip()
        if not stripped:
            continue
        m = _SECTION_RE.match(stripped)
        if m:
            name = m.group(1).strip().upper()
            current = sections.setdefault(name, {})
            continue
        if current is None or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip().strip('"').strip("'")
        current[key.strip().upper()] = value
    return sections


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        f = float(value.strip())
    except (ValueError, AttributeError):
        return None
    # Reject NaN/±inf so a corrupt INI can't propagate a non-finite into size-label formatting,
    # window math, or int() (which raises OverflowError on inf) downstream.
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _to_int(value: str | None) -> int | None:
    f = _to_float(value)  # inherits the non-finite guard; int() on a finite float is safe
    return int(f) if f is not None else None


def _section_for(
    sections: dict[str, dict[str, str]], prefix: str, compound_index: int
) -> dict[str, str] | None:
    """Resolve ``[<PREFIX>_<N>]`` with N==0 falling back to the bare ``[<PREFIX>]`` alias."""
    exact = sections.get(f"{prefix}_{compound_index}")
    if exact is not None:
        return exact
    if compound_index == 0:
        return sections.get(prefix)
    return None


def _get(section: dict[str, str] | None, key: str) -> str | None:
    if section is None:
        return None
    return section.get(key.upper())


def _size_label(
    width_m: float | None, radius_m: float | None, rim_radius_m: float | None
) -> str | None:
    """Human tyre-size string derived from physical dims, e.g. ``"300/R34.0 (rim R24.1)"``.

    Width is rendered in millimetres (AC width is metres); radius/rim in centimetre-precision ``R``
    notation. Returns ``None`` unless at least width and radius are known.
    """
    if width_m is None or radius_m is None:
        return None
    width_mm = round(width_m * 1000)
    radius_label = f"R{radius_m * 100:.1f}"
    if rim_radius_m is not None:
        return f"{width_mm}/{radius_label} (rim R{rim_radius_m * 100:.1f})"
    return f"{width_mm}/{radius_label}"


_LUT_PAIR_RE = re.compile(r"^\s*([-+0-9.eE]+)\s*\|\s*([-+0-9.eE]+)\s*$")


def _parse_lut_pairs(text: str) -> list[tuple[float, float]]:
    """Parse a ``.lut`` (or inline) ``x|y`` table, tolerant of comments/blank lines."""
    pairs: list[tuple[float, float]] = []
    for line in text.splitlines():
        stripped = re.split(r"[;#]", line, maxsplit=1)[0].strip()
        if not stripped:
            continue
        m = _LUT_PAIR_RE.match(stripped)
        if not m:
            continue
        try:
            pairs.append((float(m.group(1)), float(m.group(2))))
        except ValueError:
            continue
    return pairs


def _optimal_temp_from_curve(
    performance_curve: str | None, archive: dict[str, str]
) -> float | None:
    """Resolve the PERFORMANCE_CURVE (a ``.lut`` filename in the same archive, or an inline table)
    and return the temperature (x) at peak grip (max y). Ties resolve to the first (lowest) x that
    reaches the max — the temperature at which peak grip is first achieved. ``None`` if it cannot be
    resolved.
    """
    if not performance_curve:
        return None
    curve_text: str | None = None
    candidate = performance_curve.strip()
    if candidate.lower().endswith(".lut"):
        # Filename reference into the same archive. Use the lowercased BASENAME (some mods write a
        # path prefix like `data/tcurve.lut` or `data\tcurve.lut`) — archive keys are lowercased
        # basenames, so this stays a case-insensitive O(1) lookup.
        base = candidate.replace("\\", "/").rsplit("/", 1)[-1].lower()
        curve_text = archive.get(base)
    else:
        # Inline curve: AC allows the LUT written directly, sometimes wrapped in parentheses.
        curve_text = candidate.replace("(", "\n").replace(")", "\n").replace(",", "\n")

    if not curve_text:
        return None
    pairs = _parse_lut_pairs(curve_text)
    if not pairs:
        return None
    max_y = max(y for _, y in pairs)
    for x, y in pairs:
        if y == max_y:
            return x
    return None


# --------------------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------------------


def read_tyre_specs(car_dir: str | Path, compound_index: int) -> TyreSpec | None:
    """Resolve ``tyres.ini`` for ``car_dir``; return the :class:`TyreSpec` for ``compound_index``.

    Source preference matches AC: packed ``data.acd`` when present, otherwise unpacked
    ``data/tyres.ini``. Parses ``[FRONT_<N>]`` (bare ``[FRONT]`` for N==0), falling back to
    ``[REAR_<N>]`` for any key the front section omits. Optimal core temp is the peak of the
    matching ``[THERMAL_FRONT_<N>]`` (or ``[THERMAL_REAR_<N>]``) ``PERFORMANCE_CURVE``.

    Returns ``None`` if neither source is readable / has no ``tyres.ini``. Never raises on a
    malformed car — unreadable individual fields degrade to ``None``.
    """
    try:
        car_path = Path(car_dir)
    except (TypeError, ValueError):
        return None

    archive = _load_archive(car_path)
    if archive is None:
        return None

    tyres_text = archive.get("tyres.ini")
    if not tyres_text:
        return None

    try:
        sections = _parse_ini_sections(tyres_text)

        front = _section_for(sections, "FRONT", compound_index)
        rear = _section_for(sections, "REAR", compound_index)
        if front is None and rear is None:
            # Compound index out of range for this car.
            return None

        def field(key: str) -> str | None:
            # Prefer FRONT; fall back to REAR for keys the front section omits.
            return _get(front, key) if _get(front, key) is not None else _get(rear, key)

        width_m = _to_float(field("WIDTH"))
        radius_m = _to_float(field("RADIUS"))
        rim_radius_m = _to_float(field("RIM_RADIUS"))

        thermal_front = _section_for(sections, "THERMAL_FRONT", compound_index)
        thermal_rear = _section_for(sections, "THERMAL_REAR", compound_index)
        perf_curve = _get(thermal_front, "PERFORMANCE_CURVE")
        if perf_curve is None:
            perf_curve = _get(thermal_rear, "PERFORMANCE_CURVE")

        header = sections.get("HEADER")

        return TyreSpec(
            compound_index=compound_index,
            name=field("NAME"),
            width_m=width_m,
            radius_m=radius_m,
            rim_radius_m=rim_radius_m,
            size_label=_size_label(width_m, radius_m, rim_radius_m),
            pressure_static_psi=_to_float(field("PRESSURE_STATIC")),
            pressure_ideal_psi=_to_float(field("PRESSURE_IDEAL")),
            dx_ref=_to_float(field("DX_REF")),
            dy_ref=_to_float(field("DY_REF")),
            optimal_temp_c=_optimal_temp_from_curve(perf_curve, archive),
            version=_to_int(_get(header, "VERSION")),
        )
    except Exception:
        # Absolute backstop: a malformed car must never crash the sidecar.
        return None
