"""Car-true tyre compound specs, resolved from Assetto Corsa car data (``tyres.ini``).

This is the *identity* side of the tyre story. ``tyre_model.py`` consumes **live** core
temperature and can only *infer* a compound window because "compound identity is NOT in the
telemetry feed" (see that module's docstring). This reader closes that gap: it reads the car's
own ``tyres.ini`` — the ground-truth `NAME`, physical size, cold/hot ideal pressures, peak-mu
references, and the car-specific optimal core temperature baked into the thermal
`PERFORMANCE_CURVE` — so downstream coaching can key off the *actual* compound the driver
selected (``ac.getCar().compoundIndex`` / setup ``[TYRES] VALUE``) instead of a generic guess.

On this rig every stock/Kunos car ships **only** ``data.acd`` (no unpacked ``data/`` folder), so
this module must decrypt the packed+obfuscated ACD container itself. Pure stdlib, Windows-safe.

ACD format (confirmed by decrypting the real ``ks_porsche_911_gt3_r_2016/data.acd`` — see the
Part-B investigation note). Canonical reference: the ``bovis/acd_extractor`` Ruby implementation
and aluigi's ZenHAX writeup (``zenhax.com/viewtopic.php?t=90``).

* **Key** — derived from the CAR FOLDER NAME string via 8 small integer algorithms, then rendered
  as the dash-joined decimal string ``"p1-p2-...-p8"``. The *string* is the key material, so its
  length is variable (25 chars for the 911), and de-obfuscation indexes byte-by-byte into it.
* **Container** — leading ``int32``: if it equals ``-1111`` a version ``int32`` follows, otherwise
  it is already the first filename length. Then repeating records:
  ``[name_len:uint32][name bytes][content_len:uint32][content]`` where content is stored as
  ``content_len`` little-endian ``int32``s — only each int's low byte carries the obfuscated char.
* **De-obfuscation** — ``char = (stored_low_byte - key_ord[i % len(key)]) mod 256`` (subtraction,
  NOT XOR; empirically verified — XOR yields garbage).

Everything is wrapped so a malformed / renamed / missing car degrades to ``None`` (or None-fields)
and never raises — the sidecar must not crash on one bad car.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

_ACD_DUMMY_LEADING = -1111
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
# ACD decryption (folder-name key + container unpack)
# --------------------------------------------------------------------------------------------------


def _acd_key(folder_name: str) -> str:
    """Derive the ACD obfuscation key string from the car folder name.

    Verbatim port of the 8-part integer algorithm from the canonical ``bovis/acd_extractor``
    ``Cipher.get_key``. Returns the dash-joined decimal string used as key material.
    """
    o = [ord(c) for c in folder_name]
    n = len(o)

    # PART 1: sum of all ordinals
    p1 = 0
    for i in range(n):
        p1 += o[i]
    p1 &= 0xFF

    # PART 2: alternating multiply / subtract over pairs
    p2 = 0
    i = 0
    while i < n - 1:
        p2 = p2 * o[i]
        i += 1
        p2 = p2 - o[i]
        i += 1
    p2 &= 0xFF

    # PART 3: multiply / integer-divide / subtract with +0x1b offset (truncate-toward-zero divide)
    p3 = 0
    i = 1
    while i < n - 3:
        p3 = p3 * o[i]
        i += 1
        if p3 < 0:
            p3 = -(abs(p3) // (o[i] + 0x1B))
        else:
            p3 = p3 // (o[i] + 0x1B)
        i -= 2
        p3 = p3 + (-(0x1B) - o[i])
        i += 4
    p3 &= 0xFF

    # PART 4: 0x1683 minus ordinals from index 1
    p4 = 0x1683
    i = 1
    while i < n:
        p4 = p4 - o[i]
        i += 1
    p4 &= 0xFF

    # PART 5: 0x42 seeded multiply/add chain with 0xf / 0x16 offsets, stride 4
    p5 = 0x42
    i = 1
    while i < n - 4:
        a = p5 * (o[i] + 0xF)
        i -= 1
        b = o[i]
        i += 1
        b = b + 0xF
        b = b * a
        b = b + 0x16
        p5 = b
        i += 4
    p5 &= 0xFF

    # PART 6: 0x65 minus every other ordinal
    p6 = 0x65
    i = 0
    while i < n - 2:
        p6 = p6 - o[i]
        i += 2
    p6 &= 0xFF

    # PART 7: 0xab modulo every other ordinal
    p7 = 0xAB
    i = 0
    while i < n - 2:
        p7 = p7 % o[i]
        i += 2
    p7 &= 0xFF

    # PART 8: 0xab alternating integer-divide / add
    p8 = 0xAB
    i = 0
    while i < n - 1:
        p8 = p8 // o[i]
        i += 1
        p8 = p8 + o[i]
    p8 &= 0xFF

    return f"{p1}-{p2}-{p3}-{p4}-{p5}-{p6}-{p7}-{p8}"


def _acd_unpack(data: bytes, folder_name: str) -> dict[str, bytes]:
    """De-obfuscate a raw ``data.acd`` blob into ``{filename: content_bytes}``.

    Raises on truncation/format errors; callers wrap this and degrade to ``None``.
    """
    key = _acd_key(folder_name)
    key_ord = [ord(c) for c in key]
    klen = len(key_ord)
    if klen == 0:  # empty folder name -> unusable key
        raise ValueError("empty ACD key")

    files: dict[str, bytes] = {}
    pos = 0
    total = len(data)

    # Leading int: -1111 => a version int follows; otherwise it IS the first filename length.
    (lead,) = struct.unpack_from("<l", data, pos)
    if lead == _ACD_DUMMY_LEADING:
        pos += 4  # consume the -1111 marker
        pos += 4  # consume the version int (not needed for extraction)

    while pos < total:
        (name_len,) = struct.unpack_from("<I", data, pos)
        pos += 4
        # A bogus length (obfuscation drift / trailing padding) would overrun — bail cleanly.
        if name_len == 0 or pos + name_len > total:
            break
        name = data[pos : pos + name_len].decode("utf-8", "replace")
        pos += name_len

        (content_len,) = struct.unpack_from("<I", data, pos)
        pos += 4
        content_span = content_len * 4
        if pos + content_span > total:
            break

        out = bytearray(content_len)
        base = pos
        for j in range(content_len):
            low = data[base + j * 4]  # low byte of each int32 carries the obfuscated char
            out[j] = (low - key_ord[j % klen]) & 0xFF
        pos += content_span

        files[name] = bytes(out)

    return files


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

    Prefers an unpacked ``data/`` folder (any car that has been extracted); otherwise decrypts
    ``data.acd`` using the car FOLDER NAME as the key. Result cached per ``car_dir``.
    """
    cache_key = str(car_dir)
    if cache_key in _ARCHIVE_CACHE:
        return _ARCHIVE_CACHE[cache_key]

    archive: dict[str, str] | None = None
    try:
        # Prefer an unpacked data/ folder. Read the small data files (tyres.ini + any .lut) up
        # front, lowercasing member names so every downstream lookup is case-insensitive — AC mods
        # ship TYRES.INI / Tyres.ini too, and a case-exact check misses them on a case-sensitive FS.
        data_dir = car_dir / "data"
        members: dict[str, str] = {}
        if data_dir.is_dir():
            for child in data_dir.iterdir():
                if child.is_file() and child.suffix.lower() in (".ini", ".lut"):
                    try:
                        members[child.name.lower()] = _decode_text(child.read_bytes())
                    except OSError:
                        continue
        if "tyres.ini" in members:
            archive = members
        else:
            acd_path = car_dir / "data.acd"
            if acd_path.is_file():
                raw = acd_path.read_bytes()
                unpacked = _acd_unpack(raw, car_dir.name)  # key derived from THIS folder's name
                # Lowercase member names for the same case-insensitive lookups downstream.
                lowered = {name.lower(): blob for name, blob in unpacked.items()}
                if "tyres.ini" in lowered:
                    archive = {name: _decode_text(blob) for name, blob in lowered.items()}
    except (OSError, ValueError, struct.error, IndexError):
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
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        m = _SECTION_RE.match(line)
        if m:
            name = m.group(1).strip().upper()
            current = sections.setdefault(name, {})
            continue
        if current is None or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        # strip inline comment (';' or '#') and surrounding whitespace/quotes
        value = re.split(r"[;#]", value, maxsplit=1)[0].strip().strip('"').strip("'")
        current[key.strip().upper()] = value
    return sections


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip())
    except (ValueError, AttributeError):
        return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except (ValueError, AttributeError):
        return None


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
        # Filename reference into the same archive. Archive keys are lowercased by _load_archive, so
        # a single lowercased lookup is case-insensitive and O(1) (no linear scan needed).
        curve_text = archive.get(candidate.lower())
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

    Source preference: unpacked ``data/tyres.ini`` if present, else decrypt ``data.acd`` (folder
    name is the key). Parses ``[FRONT_<N>]`` (bare ``[FRONT]`` for N==0), falling back to
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
