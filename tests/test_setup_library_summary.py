"""setup_library.summaryForSetup — per-row chip fields for Pocket Technician (#93)."""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"
FIXTURE_INI = REPO / "tests" / "fixtures" / "setups" / "pt_chip_summary.ini"


@pytest.fixture
def lua():
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    modules_path = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{modules_path}/?.lua"')
    return rt


def test_summary_for_setup_reads_front_bias(lua) -> None:
    """FRONT_BIAS VALUE maps to brake_bias for the rig screen chip row."""
    ini = str(FIXTURE_INI).replace("\\", "/")
    summary = lua.execute(
        f"""
        local setupLibrary = require("setup_library")
        return setupLibrary.summaryForSetup("{ini}")
        """
    )
    assert summary["brake_bias"] == 66
    assert summary["abs"] == 7
    assert summary["tc"] == 3
    assert summary["wing_f"] == 2
    assert summary["wing_r"] == 20


def test_chip_int_coercion_rounds_and_omits_invalid(lua) -> None:
    """chipInt helper used in setup.list matches issue #93 semantics."""
    out = lua.execute(
        """
        local function chipInt(v)
          if v == nil then return nil end
          local n = tonumber(v)
          if n == nil then return nil end
          return math.floor(n + 0.5)
        end
        return {
          bb = chipInt(66.4),
          missing = chipInt(nil),
          bad = chipInt("not-a-number"),
        }
        """
    )
    assert out["bb"] == 66
    assert out["missing"] is None
    assert out["bad"] is None
