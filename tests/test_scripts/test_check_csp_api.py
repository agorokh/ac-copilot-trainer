"""Tests for ``scripts/check_csp_api.py`` CSP Lua static checks."""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path


def _load_check_csp_api() -> types.ModuleType:
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "check_csp_api.py"
    spec = importlib.util.spec_from_file_location("check_csp_api", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_scan_file_flags_blocklisted_api(tmp_path: Path) -> None:
    mod = _load_check_csp_api()
    f = tmp_path / "x.lua"
    f.write_text("function f() render.glBegin() end\n", encoding="utf-8")
    errs, warns = mod.scan_file(f, strict=False)
    assert errs
    assert any("glBegin" in e for e in errs)
    assert not warns


def test_scan_file_detects_blocklist_after_string_with_double_hyphen(tmp_path: Path) -> None:
    """`--` inside a string must not truncate the line before scanning."""
    mod = _load_check_csp_api()
    f = tmp_path / "x.lua"
    f.write_text('ac.log("see -- not a comment"); render.glBegin()\n', encoding="utf-8")
    errs, warns = mod.scan_file(f, strict=False)
    assert errs
    assert any("glBegin" in e for e in errs)
    assert not warns


def test_scan_file_ignores_blocklisted_name_inside_string_literal(tmp_path: Path) -> None:
    mod = _load_check_csp_api()
    f = tmp_path / "x.lua"
    f.write_text('ac.log("render.glBegin missing")\n', encoding="utf-8")
    errs, warns = mod.scan_file(f, strict=False)
    assert not errs
    assert not warns


def test_scan_file_allowlisted_render_call_clean(tmp_path: Path) -> None:
    mod = _load_check_csp_api()
    f = tmp_path / "x.lua"
    f.write_text("function f() render.debugSphere(vec3(), 1) end\n", encoding="utf-8")
    errs, warns = mod.scan_file(f, strict=False)
    assert not errs
    assert not warns


def test_scan_file_unknown_render_warning_or_strict_error(tmp_path: Path) -> None:
    mod = _load_check_csp_api()
    f = tmp_path / "x.lua"
    f.write_text("function f() render.totallyFakeThing() end\n", encoding="utf-8")
    e0, w0 = mod.scan_file(f, strict=False)
    assert not e0
    assert w0
    assert any("UNKNOWN render API" in w for w in w0)
    e1, _w1 = mod.scan_file(f, strict=True)
    assert e1
    assert any("UNKNOWN render API" in e for e in e1)


def test_scan_file_unit_confusion_warning(tmp_path: Path) -> None:
    mod = _load_check_csp_api()
    f = tmp_path / "x.lua"
    f.write_text("if sim.time > 50 then end\n", encoding="utf-8")
    errs, warns = mod.scan_file(f, strict=False)
    assert not errs
    assert warns
    assert any("UNIT WARNING" in w for w in warns)


def test_scan_file_missing_path_is_error(tmp_path: Path) -> None:
    mod = _load_check_csp_api()
    missing = tmp_path / "nope.lua"
    errs, warns = mod.scan_file(missing, strict=False)
    assert errs
    assert any("could not read" in e for e in errs)
    assert not warns
