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
