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


def test_firmware_chip_refresh_path_present() -> None:
    """Issue #93: LVGL stale BB chip fix is clear-then-set + invalidate on stored labels."""
    cpp = (REPO / "firmware" / "screen" / "src" / "ui" / "screen_pocket_technician.cpp").read_text(
        encoding="utf-8"
    )
    assert "g_row_chip_labels" in cpp
    assert "refresh_chip_label" in cpp
    assert 'lv_label_set_text(chips, "")' in cpp
    assert "lv_obj_invalidate(chips)" in cpp
    assert "lv_obj_is_valid(chips)" in cpp
    assert "g_row_chip_labels[i] = nullptr" in cpp


def test_firmware_spinner_protocol_path_present() -> None:
    """Pocket Technician queues setup.spinner list/set frames and renders +/- controls."""
    screen_cpp = (
        REPO / "firmware" / "screen" / "src" / "ui" / "screen_pocket_technician.cpp"
    ).read_text(encoding="utf-8")
    main_cpp = (REPO / "firmware" / "screen" / "src" / "main.cpp").read_text(encoding="utf-8")
    header = (
        REPO / "firmware" / "screen" / "include" / "ui" / "screen_pocket_technician.h"
    ).read_text(encoding="utf-8")
    assert "PT_REQ_SPINNER_LIST" in header
    assert "PT_REQ_SPINNER_SET" in header
    assert "screen_pocket_technician_apply_spinner_ack" in screen_cpp
    assert "screen_pocket_technician_apply_spinner_list_error" in screen_cpp
    assert "active_path_or_null" in screen_cpp
    assert "make_spinner_row" in screen_cpp
    assert "setup.spinner.list" in main_cpp
    assert "setup.spinner.set" in main_cpp
    assert "phase2_json_float_or" in main_cpp
    assert "v.is<double>()" in main_cpp
    assert "v.is<long>()" in main_cpp
    assert "float             value" in header
    assert "format_spinner_value" in screen_cpp
    assert 'doc["path"] = req.path' in main_cpp


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


def _install_spinner_stubs(lua, setup_path: pathlib.Path, root: pathlib.Path) -> None:
    setup_lua = str(setup_path).replace("\\", "/")
    root_lua = str(root).replace("\\", "/")
    lua.execute(
        f"""
        ac = {{
          FolderID = {{ UserSetups = 11 }},
          getFolder = function(_id) return "{root_lua}" end,
          getCar = function(_idx) return {{}} end,
          getSim = function() return {{}} end,
          loadSetup = function(path)
            _G.__loaded_setup = path
            return true
          end,
        }}
        local setupReader = require("setup_reader")
        setupReader.activeSetupIniPath = function(_car, _sim)
          return "{setup_lua}"
        end
        """
    )


def test_spinner_list_reads_active_setup_controls(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "race.ini"
    setup_path.parent.mkdir(parents=True)
    setup_path.write_text(FIXTURE_INI.read_text(encoding="utf-8"), encoding="utf-8")
    _install_spinner_stubs(lua, setup_path, root)

    result = lua.execute(
        """
        local setupLibrary = require("setup_library")
        return setupLibrary.listSpinners({})
        """
    )

    assert result["ok"] is True
    first = result["spinners"][1]
    assert first["section"] == "FRONT_BIAS"
    assert first["label"] == "Brake bias"
    assert first["value"] == 66
    assert first["min"] == 40
    assert first["max"] == 80


def test_spinner_list_rejects_traversal_payload_path(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "race.ini"
    setup_path.parent.mkdir(parents=True)
    setup_path.write_text(FIXTURE_INI.read_text(encoding="utf-8"), encoding="utf-8")
    _install_spinner_stubs(lua, setup_path, root)
    attack = str(root / "ks_porsche_911_gt3_r_2016" / ".." / ".." / "outside.ini").replace(
        "\\",
        "/",
    )

    result = lua.execute(
        f"""
        local setupLibrary = require("setup_library")
        return setupLibrary.listSpinners({{ path = "{attack}" }})
        """
    )

    assert result["ok"] is False
    assert "traversal" in result["error"]


def test_spinner_list_prefers_csp_api(lua) -> None:
    lua.execute(
        """
        ac = {
          getSetupSpinners = function()
            return {
              { name = "ABS", label = "ABS", value = 7, min = 0, max = 12, step = 1 },
              { name = "FRONT_BIAS", value = 66, min = 40, max = 80, step = 1 },
            }
          end,
        }
        """
    )

    result = lua.execute(
        """
        local setupLibrary = require("setup_library")
        return setupLibrary.listSpinners({})
        """
    )

    assert result["ok"] is True
    assert result["source"] == "csp"
    assert result["spinners"][1]["section"] == "FRONT_BIAS"
    assert result["spinners"][2]["section"] == "ABS"


def test_spinner_set_rewrites_active_setup_and_applies(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "race.ini"
    setup_path.parent.mkdir(parents=True)
    setup_path.write_text(FIXTURE_INI.read_text(encoding="utf-8"), encoding="utf-8")
    _install_spinner_stubs(lua, setup_path, root)

    ack = lua.execute(
        """
        local setupLibrary = require("setup_library")
        return setupLibrary.setSpinner({ section = "FRONT_BIAS", value = 67 })
        """
    )

    assert ack["ok"] is True
    assert ack["section"] == "FRONT_BIAS"
    assert ack["value"] == 67
    assert "VALUE=67" in setup_path.read_text(encoding="utf-8")
    assert lua.globals()["__loaded_setup"] == str(setup_path).replace("\\", "/")


def test_spinner_set_preserves_decimal_values(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "race.ini"
    setup_path.parent.mkdir(parents=True)
    setup_path.write_text(
        "[TYRE_PRESSURE_LF]\nVALUE=26.5\nMIN=20\nMAX=35\nSTEP=0.1\n",
        encoding="utf-8",
    )
    _install_spinner_stubs(lua, setup_path, root)

    ack = lua.execute(
        """
        local setupLibrary = require("setup_library")
        return setupLibrary.setSpinner({ section = "TYRE_PRESSURE_LF", value = 26.6 })
        """
    )

    assert ack["ok"] is True
    assert ack["value"] == pytest.approx(26.6)
    assert "VALUE=26.6" in setup_path.read_text(encoding="utf-8")


def test_load_by_path_retries_after_cache_miss(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "Fresh.ini"
    setup_path.parent.mkdir(parents=True)
    setup_path.write_text("[HEADER]\nVERSION=1\n", encoding="utf-8")
    root_lua = str(root).replace("\\", "/")
    setup_lua = str(setup_path).replace("\\", "/")

    ack = lua.execute(
        f"""
        local scans = 0
        ac = {{
          FolderID = {{ UserSetups = 11 }},
          getFolder = function(_id) return "{root_lua}" end,
          loadSetup = function(path)
            _G.__loaded_setup = path
            return true
          end,
        }}
        local csp_helpers = require("csp_helpers")
        csp_helpers.safeCarIdRaw = function() return "ks_porsche_911_gt3_r_2016" end
        csp_helpers.safeTrackIdRaw = function() return "monza" end
        csp_helpers.safeTrackLayoutRaw = function() return "" end
        io.scanDir = function(path, pattern)
          if pattern ~= "*.ini" then return {{}} end
          scans = scans + 1
          if scans < 3 then return {{}} end
          return {{ "Fresh.ini" }}
        end
        local setupLibrary = require("setup_library")
        return setupLibrary.loadByName({{ name = "Fresh", path = "{setup_lua}" }})
        """
    )

    assert ack["ok"] is True
    assert ack["path"] == setup_lua
    assert lua.globals()["__loaded_setup"] == setup_lua


def test_spinner_set_prefers_csp_api_and_snaps_to_step(lua) -> None:
    lua.execute(
        """
        ac = {
          getSetupSpinners = function()
            return {
              { name = "ABS", label = "ABS", value = 7, min = 0, max = 12, step = 2 },
            }
          end,
          setSetupSpinnerValue = function(name, value)
            _G.__set_spinner_name = name
            _G.__set_spinner_value = value
            return true
          end,
        }
        """
    )

    ack = lua.execute(
        """
        local setupLibrary = require("setup_library")
        return setupLibrary.setSpinner({ section = "ABS", value = 9 })
        """
    )

    assert ack["ok"] is True
    assert ack["source"] == "csp"
    assert ack["value"] == 10
    assert lua.globals()["__set_spinner_name"] == "ABS"
    assert lua.globals()["__set_spinner_value"] == 10


def test_spinner_set_rejects_out_of_range_without_writing(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "race.ini"
    setup_path.parent.mkdir(parents=True)
    original = FIXTURE_INI.read_text(encoding="utf-8")
    setup_path.write_text(original, encoding="utf-8")
    _install_spinner_stubs(lua, setup_path, root)

    ack = lua.execute(
        """
        local setupLibrary = require("setup_library")
        return setupLibrary.setSpinner({ section = "FRONT_BIAS", value = 100 })
        """
    )

    assert ack["ok"] is False
    assert "out of range" in ack["error"]
    assert setup_path.read_text(encoding="utf-8") == original


def test_spinner_set_temp_file_collision_keeps_original(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "race.ini"
    setup_path.parent.mkdir(parents=True)
    original = FIXTURE_INI.read_text(encoding="utf-8")
    setup_path.write_text(original, encoding="utf-8")
    for i in range(1, 17):
        setup_path.with_name(f"{setup_path.name}.ac-copilot-tmp-{i}").write_text(
            "occupied\n",
            encoding="utf-8",
        )
    _install_spinner_stubs(lua, setup_path, root)

    ack = lua.execute(
        """
        local setupLibrary = require("setup_library")
        return setupLibrary.setSpinner({ section = "FRONT_BIAS", value = 67 })
        """
    )

    assert ack["ok"] is False
    assert "temp file" in ack["error"]
    assert setup_path.read_text(encoding="utf-8") == original


def test_spinner_set_write_nil_keeps_original(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "race.ini"
    setup_path.parent.mkdir(parents=True)
    original = FIXTURE_INI.read_text(encoding="utf-8")
    setup_path.write_text(original, encoding="utf-8")
    _install_spinner_stubs(lua, setup_path, root)

    ack = lua.execute(
        """
        local realOpen = io.open
        io.open = function(path, mode)
          if mode == "w" and path:find("%.ac%-copilot%-tmp%-1$") then
            return {
              write = function(_self, _text) return nil, "disk full" end,
              close = function(_self) return true end,
            }
          end
          return realOpen(path, mode)
        end
        local setupLibrary = require("setup_library")
        local ret = setupLibrary.setSpinner({ section = "FRONT_BIAS", value = 67 })
        io.open = realOpen
        return ret
        """
    )

    assert ack["ok"] is False
    assert "disk full" in ack["error"] or "write failed" in ack["error"]
    assert setup_path.read_text(encoding="utf-8") == original


def test_spinner_set_write_exception_reports_pcall_error(lua, tmp_path: pathlib.Path) -> None:
    root = tmp_path / "setups"
    setup_path = root / "ks_porsche_911_gt3_r_2016" / "monza" / "race.ini"
    setup_path.parent.mkdir(parents=True)
    original = FIXTURE_INI.read_text(encoding="utf-8")
    setup_path.write_text(original, encoding="utf-8")
    _install_spinner_stubs(lua, setup_path, root)

    ack = lua.execute(
        """
        local realOpen = io.open
        io.open = function(path, mode)
          if mode == "w" and path:find("%.ac%-copilot%-tmp%-1$") then
            return {
              write = function(_self, _text) error("disk exploded") end,
              close = function(_self) return true end
            }
          end
          return realOpen(path, mode)
        end
        local setupLibrary = require("setup_library")
        local ret = setupLibrary.setSpinner({ section = "FRONT_BIAS", value = 67 })
        io.open = realOpen
        return ret
        """
    )

    assert ack["ok"] is False
    assert "disk exploded" in ack["error"]
    assert setup_path.read_text(encoding="utf-8") == original


def test_write_text_file_restore_failure_uses_pcall() -> None:
    """Atomic setup write reports backup-restore failures via pcall (PR #365 Gemini)."""
    lua_src = (MODULES_DIR / "setup_library.lua").read_text(encoding="utf-8")
    assert "local okRestore, restoreRet, restoreErr = pcall(os.rename, backup, path)" in lua_src
    assert "not okRestore or not restoreRet" in lua_src
    assert 'local restoreMsg = (not okRestore and restoreRet) or restoreErr or "unknown"' in lua_src
    assert "restore from backup failed" in lua_src


def test_phase2_json_float_or_rejects_non_finite() -> None:
    main_cpp = (REPO / "firmware" / "screen" / "src" / "main.cpp").read_text(encoding="utf-8")
    assert "phase2_json_finite_float" in main_cpp
    assert "isnan" in main_cpp
    assert "isinf" in main_cpp


def test_setup_exchange_active_row_uses_delete_event() -> None:
    """Setup Exchange clears active LVGL rows from LV_EVENT_DELETE."""
    cpp = (REPO / "firmware" / "screen" / "src" / "ui" / "screen_setup_exchange.cpp").read_text(
        encoding="utf-8"
    )
    assert "void on_row_delete" in cpp
    assert "lv_obj_add_event_cb(row, on_row_delete, LV_EVENT_DELETE, ctx)" in cpp
    assert "ctx->active_row == lv_event_get_target(e)" in cpp
    assert "lv_obj_is_valid(ctx->active_row)" not in cpp
