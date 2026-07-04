"""Hermetic tests for ``tools.ai_sidecar.tyre_specs``.

No dependency on the Steam install: a tiny synthetic ``data.acd`` is built in-test with the SAME
obfuscation the reader reverses (encode = ``(char + key_ord[i % len]) & 0xFF``, the inverse of the
reader's subtraction), so the round-trip proves both the container layout and the de-obfuscation.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from tools.ai_sidecar.tyre_specs import (
    TyreSpec,
    _acd_key,
    read_tyre_specs,
)

# --------------------------------------------------------------------------------------------------
# Synthetic ACD encoder (mirror-image of the reader's decrypt path)
# --------------------------------------------------------------------------------------------------


def _acd_encode_content(text: str, key: str) -> bytes:
    """Obfuscate one member's bytes: each char -> a little-endian int32 whose low byte is
    ``(char + key_ord[i % len]) & 0xFF`` (upper 3 bytes zero). Inverse of the reader's subtract."""
    key_ord = [ord(c) for c in key]
    klen = len(key_ord)
    raw = text.encode("utf-8")
    out = bytearray()
    for i, ch in enumerate(raw):
        low = (ch + key_ord[i % klen]) & 0xFF
        out += struct.pack("<I", low)
    return bytes(out)


def _build_acd(folder_name: str, members: dict[str, str], with_version: bool = True) -> bytes:
    """Assemble a synthetic ``data.acd`` for ``folder_name`` containing ``members``.

    Layout: optional ``[-1111][version]`` prefix, then per member
    ``[name_len:uint32][name][content_len:uint32][content int32s]``.
    """
    key = _acd_key(folder_name)
    blob = bytearray()
    if with_version:
        blob += struct.pack("<l", -1111)
        blob += struct.pack("<l", 42)  # arbitrary version int
    for name, text in members.items():
        name_bytes = name.encode("utf-8")
        blob += struct.pack("<I", len(name_bytes))
        blob += name_bytes
        blob += struct.pack("<I", len(text.encode("utf-8")))
        blob += _acd_encode_content(text, key)
    return bytes(blob)


# A compact but realistic tyres.ini: bare [FRONT]/[REAR] == compound 0, plus a [FRONT_1].
_SYNTH_TYRES_INI = """\
[HEADER]
VERSION=7

[COMPOUND_DEFAULT]
INDEX=0

; ---- compound 0 ----
[FRONT]
NAME=Toyo R888R          ; road-legal semi-slick
SHORT_NAME=R
WIDTH=0.255
RADIUS=0.318
RIM_RADIUS=0.2286
PRESSURE_STATIC=24 ; cold
PRESSURE_IDEAL=30  ; hot
DX_REF=1.44
DY_REF=1.42

[REAR]
NAME=Toyo R888R
WIDTH=0.275
RADIUS=0.320
RIM_RADIUS=0.2286
PRESSURE_STATIC=24
PRESSURE_IDEAL=30
DX_REF=1.44
DY_REF=1.42

[THERMAL_FRONT]
PERFORMANCE_CURVE=tcurve_r888.lut
COOL_FACTOR=1.9

[THERMAL_REAR]
PERFORMANCE_CURVE=tcurve_r888.lut

; ---- compound 1 (duplicate NAME key exercises last-write-wins) ----
[FRONT_1]
NAME=PLACEHOLDER
NAME=Slick Medium
WIDTH=0.300
RADIUS=0.330
RIM_RADIUS=0.2413
DX_REF=1.60
DY_REF=1.58

[THERMAL_FRONT_1]
PERFORMANCE_CURVE=tcurve_slick.lut
"""

# 3-point curve: peak grip 1.0 at 85 C (a clear single max, not on the endpoints).
_SYNTH_R888_LUT = "60|0.85\n85|1.00\n110|0.92\n"
# Compound-1 curve peaks at 95 C.
_SYNTH_SLICK_LUT = "70|0.80\n95|1.00\n130|0.88\n"


@pytest.fixture
def synth_car(tmp_path: Path) -> Path:
    """A car dir whose only tyre source is a synthetic encrypted ``data.acd``."""
    folder = "synth_test_car"
    car_dir = tmp_path / folder
    car_dir.mkdir()
    acd = _build_acd(
        folder,
        {
            "tyres.ini": _SYNTH_TYRES_INI,
            "tcurve_r888.lut": _SYNTH_R888_LUT,
            "tcurve_slick.lut": _SYNTH_SLICK_LUT,
        },
    )
    (car_dir / "data.acd").write_bytes(acd)
    return car_dir


# --------------------------------------------------------------------------------------------------
# ACD decrypt + parse round-trip
# --------------------------------------------------------------------------------------------------


def test_acd_roundtrip_compound0(synth_car: Path) -> None:
    """Decrypt a synthetic data.acd and parse compound 0 end-to-end."""
    spec = read_tyre_specs(synth_car, 0)
    assert spec is not None
    assert spec == TyreSpec(
        compound_index=0,
        name="Toyo R888R",
        width_m=0.255,
        radius_m=0.318,
        rim_radius_m=0.2286,
        size_label="255/R31.8 (rim R22.9)",
        pressure_static_psi=24.0,
        pressure_ideal_psi=30.0,
        dx_ref=1.44,
        dy_ref=1.42,
        optimal_temp_c=85.0,  # peak of the 3-point PERFORMANCE_CURVE
        version=7,
    )


def test_acd_roundtrip_compound1(synth_car: Path) -> None:
    """Compound 1 resolves the ``_1`` sections and its own thermal curve (peak 95 C)."""
    spec = read_tyre_specs(synth_car, 1)
    assert spec is not None
    assert spec.name == "Slick Medium"  # last-write-wins over the PLACEHOLDER duplicate key
    assert spec.width_m == 0.300
    assert spec.dx_ref == 1.60
    assert spec.optimal_temp_c == 95.0
    # PRESSURE_* absent in the compound-1 section -> None, not fabricated.
    assert spec.pressure_static_psi is None
    assert spec.pressure_ideal_psi is None


def test_acd_no_version_prefix(tmp_path: Path) -> None:
    """A container whose leading int is already the first filename length (no -1111) parses too."""
    folder = "no_version_car"
    car_dir = tmp_path / folder
    car_dir.mkdir()
    acd = _build_acd(
        folder,
        {"tyres.ini": _SYNTH_TYRES_INI, "tcurve_r888.lut": _SYNTH_R888_LUT},
        with_version=False,
    )
    (car_dir / "data.acd").write_bytes(acd)
    spec = read_tyre_specs(car_dir, 0)
    assert spec is not None
    assert spec.name == "Toyo R888R"
    assert spec.optimal_temp_c == 85.0


def test_key_is_folder_name_dependent(synth_car: Path) -> None:
    """The key is derived from the folder name: a data.acd built for a DIFFERENT folder name must
    NOT decrypt to a readable tyres.ini (guards against a folder-name-independent regression)."""
    wrong = _build_acd("some_other_folder", {"tyres.ini": _SYNTH_TYRES_INI})
    (synth_car / "data.acd").write_bytes(wrong)
    # Wrong key -> either no readable "tyres.ini" member (None) or a garbled one whose fields
    # do not match. Either way it must not yield the correct spec.
    spec = read_tyre_specs(synth_car, 0)
    assert spec is None or spec.name != "Toyo R888R"


# --------------------------------------------------------------------------------------------------
# Unpacked data/ source preference
# --------------------------------------------------------------------------------------------------


def test_prefers_unpacked_data_dir(tmp_path: Path) -> None:
    """When an unpacked ``data/tyres.ini`` exists it is used directly (no decryption needed), and
    its ``.lut`` is resolved from the same folder."""
    car_dir = tmp_path / "unpacked_car"
    data_dir = car_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "tyres.ini").write_text(_SYNTH_TYRES_INI, encoding="utf-8")
    (data_dir / "tcurve_r888.lut").write_text(_SYNTH_R888_LUT, encoding="utf-8")
    spec = read_tyre_specs(car_dir, 0)
    assert spec is not None
    assert spec.name == "Toyo R888R"
    assert spec.radius_m == 0.318
    assert spec.optimal_temp_c == 85.0


def test_unpacked_data_dir_is_case_insensitive(tmp_path: Path) -> None:
    """AC mods ship TYRES.INI / Tyres.ini and .LUT in mixed case; the reader must still resolve them
    (a case-exact lookup would miss them on a case-sensitive FS) — gemini HIGH on PR #500."""
    car_dir = tmp_path / "mixed_case_car"
    data_dir = car_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "TYRES.INI").write_text(_SYNTH_TYRES_INI, encoding="utf-8")
    (data_dir / "TCurve_R888.LUT").write_text(_SYNTH_R888_LUT, encoding="utf-8")
    spec = read_tyre_specs(car_dir, 0)
    assert spec is not None
    assert spec.name == "Toyo R888R"
    assert spec.optimal_temp_c == 85.0  # the mixed-case .lut still resolves


def test_acd_member_names_are_case_insensitive(tmp_path: Path) -> None:
    """A data.acd whose member is packed as TYRES.INI (mod author's case) still resolves."""
    folder = "mixed_case_acd_car"
    car_dir = tmp_path / folder
    car_dir.mkdir(parents=True)
    acd = _build_acd(folder, {"TYRES.INI": _SYNTH_TYRES_INI, "TCURVE_R888.LUT": _SYNTH_R888_LUT})
    (car_dir / "data.acd").write_bytes(acd)
    spec = read_tyre_specs(car_dir, 0)
    assert spec is not None
    assert spec.name == "Toyo R888R"
    assert spec.optimal_temp_c == 85.0


# --------------------------------------------------------------------------------------------------
# Tolerant parsing + graceful degradation
# --------------------------------------------------------------------------------------------------


def test_missing_car_returns_none(tmp_path: Path) -> None:
    """No data.acd and no data/ -> None (never raises)."""
    assert read_tyre_specs(tmp_path / "does_not_exist", 0) is None


def test_out_of_range_compound_returns_none(synth_car: Path) -> None:
    """A compound index with no matching section -> None."""
    assert read_tyre_specs(synth_car, 9) is None


def test_missing_fields_degrade_to_none(tmp_path: Path) -> None:
    """A section present but missing individual keys yields None for those fields, not a crash.
    Also: comments and a missing THERMAL section leave optimal_temp_c None (never fabricated)."""
    ini = (
        "[HEADER]\n"
        "; no VERSION key here\n"
        "[FRONT]\n"
        "NAME=Sparse Compound  ; only a name\n"
        "WIDTH=0.2\n"
        "; RADIUS intentionally omitted -> radius_m None, so size_label None\n"
    )
    car_dir = tmp_path / "sparse_car"
    data_dir = car_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "tyres.ini").write_text(ini, encoding="utf-8")
    spec = read_tyre_specs(car_dir, 0)
    assert spec is not None
    assert spec.name == "Sparse Compound"
    assert spec.width_m == 0.2
    assert spec.radius_m is None
    assert spec.rim_radius_m is None
    assert spec.size_label is None  # needs width AND radius
    assert spec.pressure_static_psi is None
    assert spec.dx_ref is None
    assert spec.optimal_temp_c is None  # no THERMAL section / curve
    assert spec.version is None


def test_inline_comment_and_whitespace_stripping(tmp_path: Path) -> None:
    """`KEY=VALUE ; comment` and stray whitespace are handled; numeric parse ignores the comment."""
    ini = (
        "[FRONT]\n"
        "NAME = Spaced Name \t ; trailing comment\n"
        "WIDTH= 0.245\t; width with tab+comment\n"
        "RADIUS =0.315 # hash comment style\n"
        "RIM_RADIUS=0.22\n"
    )
    car_dir = tmp_path / "commenty_car"
    data_dir = car_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "tyres.ini").write_text(ini, encoding="utf-8")
    spec = read_tyre_specs(car_dir, 0)
    assert spec is not None
    assert spec.name == "Spaced Name"
    assert spec.width_m == 0.245
    assert spec.radius_m == 0.315
    assert spec.size_label == "245/R31.5 (rim R22.0)"


def test_rear_fallback_for_missing_front_key(tmp_path: Path) -> None:
    """A key present only in [REAR_N] is used when [FRONT_N] omits it."""
    ini = (
        "[FRONT]\n"
        "NAME=Front Only Name\n"
        "WIDTH=0.28\n"
        "RADIUS=0.33\n"
        "[REAR]\n"
        "NAME=Front Only Name\n"
        "WIDTH=0.30\n"
        "RADIUS=0.34\n"
        "PRESSURE_STATIC=21 ; only defined on REAR\n"
    )
    car_dir = tmp_path / "rear_fallback_car"
    data_dir = car_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "tyres.ini").write_text(ini, encoding="utf-8")
    spec = read_tyre_specs(car_dir, 0)
    assert spec is not None
    # FRONT value wins where present...
    assert spec.width_m == 0.28
    # ...REAR fills the key FRONT omits.
    assert spec.pressure_static_psi == 21.0


def test_corrupt_acd_returns_none(tmp_path: Path) -> None:
    """Random bytes named data.acd must degrade to None, never raise."""
    car_dir = tmp_path / "corrupt_car"
    car_dir.mkdir()
    (car_dir / "data.acd").write_bytes(b"\x00\x01\x02\x03not a real acd" * 8)
    assert read_tyre_specs(car_dir, 0) is None


def test_caches_archive_per_car_dir(synth_car: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The decrypted archive is cached per car_dir: a second read for another compound does not
    re-read data.acd from disk."""
    import tools.ai_sidecar.tyre_specs as mod

    # Prime the cache.
    assert read_tyre_specs(synth_car, 0) is not None

    # Now make any further disk read explode; a cached second call must still succeed.
    def _boom(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("data.acd should not be re-read when cached")

    monkeypatch.setattr(mod.Path, "read_bytes", _boom)
    spec = read_tyre_specs(synth_car, 1)
    assert spec is not None
    assert spec.name == "Slick Medium"


def test_archive_cache_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-car archive cache evicts oldest entries at capacity (Qodo reliability finding): a
    long-lived process reading many cars never grows the cache without limit."""
    import tools.ai_sidecar.tyre_specs as mod

    monkeypatch.setattr(mod, "_ARCHIVE_CACHE", {})
    monkeypatch.setattr(mod, "_ARCHIVE_CACHE_MAX", 2)
    for i in range(4):
        folder = f"car_{i}"
        cd = tmp_path / folder
        cd.mkdir()
        acd = _build_acd(
            folder, {"tyres.ini": _SYNTH_TYRES_INI, "tcurve_r888.lut": _SYNTH_R888_LUT}
        )
        (cd / "data.acd").write_bytes(acd)
        assert read_tyre_specs(cd, 0) is not None
    assert len(mod._ARCHIVE_CACHE) <= 2
