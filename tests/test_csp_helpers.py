"""Lupa L0 regression for `csp_helpers.safeCarField` — guarded reads of risky `ac.StateCar` fields.

CSP `ac.StateCar` is a C-struct that THROWS on unknown fields (csp-api-field-safety decision /
issue #24). `safeCarField` is the pcall-guarded reader required for fields not on the confirmed
list (e.g. `resetCounter`, used for teleport detection in #185): it must return the value when the
field exists and a default (nil) — without propagating the error — when the read throws, so the
caller degrades gracefully on builds lacking the field instead of aborting `script.update`.
"""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"


def _runtime():
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    p = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{p}/?.lua"')
    return rt


def test_safe_car_field_returns_value_when_present():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local ch = require("csp_helpers")
          local car = { resetCounter = 7 }
          return ch.safeCarField(car, "resetCounter")
        end)()
        """
    )
    assert out == 7


def test_safe_car_field_nil_car_returns_default():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local ch = require("csp_helpers")
          return { d = ch.safeCarField(nil, "resetCounter", -1),
                   n = ch.safeCarField(nil, "resetCounter") }
        end)()
        """
    )
    assert out["d"] == -1
    assert out["n"] is None  # no default -> nil


def test_safe_car_field_absent_field_returns_default():
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local ch = require("csp_helpers")
          local car = { lapCount = 3 }
          return ch.safeCarField(car, "resetCounter") == nil
        end)()
        """
    )
    assert out is True


def test_safe_car_field_throwing_field_does_not_propagate():
    # Mimic CSP StateCar: a metatable __index that errors on unknown fields. safeCarField must
    # swallow the throw and return the default (the exact P1 scenario from #185).
    rt = _runtime()
    out = rt.eval(
        r"""
        (function()
          local ch = require("csp_helpers")
          local car = setmetatable({}, { __index = function() error("unknown field") end })
          local ok, res = pcall(function() return ch.safeCarField(car, "resetCounter", 99) end)
          return { ok = ok, res = res }
        end)()
        """
    )
    assert out["ok"] is True  # safeCarField did NOT propagate the error
    assert out["res"] == 99  # fell back to the default
