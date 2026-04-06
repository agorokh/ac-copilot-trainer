"""Lua runtime smoke tests for HUD modules using lupa."""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"

STUB_UI_LUA = r"""
ui = {}
local _calls = {}
local _text_colored_calls = {}

function ui.text(s)
    _calls[#_calls + 1] = { name = "text", arg = s }
end

function ui.textColored(text, color)
    _text_colored_calls[#_text_colored_calls + 1] = {
        text = text, color = color,
        text_type = type(text), color_type = type(color),
    }
end

function ui.textWrapped(s) _calls[#_calls + 1] = { name = "textWrapped" } end
function ui.separator() end
function ui.sameLine(a, b) end
function ui.windowSize() return _vec2(360, 220) end
function ui.getCursor() return _vec2(0, 0) end
function ui.setCursor(v) end
function ui.drawRectFilled() end
function ui.drawRect() end
function ui.deltaTime() return 0.016 end
function ui.checkbox(label, current) return false end
function ui.slider(label, val, min, max, fmt) return val, false end
function ui.combo(label, preview, flags, fn) end
function ui.selectable(label, sel) return false end
function ui.pushDWriteFont() end
function ui.popDWriteFont() end
function ui.pushFont() end
function ui.popFont() end
ui.Font = { Title = "title" }

-- rgbm: callable table so rgbm(r,g,b,m) works AND rgbm.colors.red works
local _rgbm_meta = {}
function _rgbm_meta.__call(_, r, g, b, m)
    return { r = r or 0, g = g or 0, b = b or 0, mult = m or 1, _isRgbm = true }
end
rgbm = setmetatable({}, _rgbm_meta)
rgbm.colors = {
    red = rgbm(1, 0, 0, 1),
    white = rgbm(1, 1, 1, 1),
}

function _vec2(x, y) return { x = x or 0, y = y or 0 } end
vec2 = _vec2
function vec3(x, y, z) return { x = x or 0, y = y or 0, z = z or 0 } end

ac = {
    log = function() end,
    getFolder = function() return "" end,
    FolderID = { Root = 0 },
}

-- Block bmw.txt loading
local _real_open = io.open
io.open = function(path, mode)
    if path and (string.find(path, "bmw") or string.find(path, "BMW")) then return nil end
    return _real_open(path, mode)
end

function _get_text_colored_violations()
    local out = {}
    for i = 1, #_text_colored_calls do
        local c = _text_colored_calls[i]
        -- Violation: text param is a table with .r/.g/.b (an rgbm)
        if type(c.text) == "table" and c.text._isRgbm then
            out[#out + 1] = { kind = "color_as_text", index = i }
        end
        -- Violation: color param is a string
        if type(c.color) == "string" then
            out[#out + 1] = { kind = "string_as_color", index = i }
        end
    end
    return out, #_text_colored_calls
end
"""


@pytest.fixture
def lua():
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    rt.execute(STUB_UI_LUA)
    modules_path = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{modules_path}/?.lua"')
    return rt


def test_hud_module_loads(lua):
    """RT-01: hud.lua loads without error."""
    hud = lua.execute('local m = require("hud"); return m')
    assert hud is not None
    assert hud["draw"] is not None


def test_hud_draw_no_textcolored_violations(lua):
    """RT-02: hud.draw() executes without crashes and uses correct textColored signature."""
    hud = lua.execute('local m = require("hud"); return m')
    vm = lua.eval("""
        {
            recording = false,
            speed = 100,
            brake = 0.5,
            lapCount = 1,
            bestLapMs = 60000,
            lastLapMs = 61000,
            deltaSmoothedSec = 0.1,
            appVersionUi = "v0.5.0",
            realtimeHint = nil,
            debriefText = nil,
            sectorMessage = "S1",
            coastWarn = false,
            postLapLines = nil,
            setupChangeMsg = nil,
            autoSetupLine = nil,
            tireLockupFlash = false,
        }
    """)
    hud["draw"](vm)
    violations, total = lua.execute("return _get_text_colored_violations()")
    violation_list = list(violations.values()) if violations else []
    assert not violation_list, (
        f"hud.draw() made {len(violation_list)} reversed textColored call(s) "
        f"out of {total} total. CSP signature is text-first, color-second."
    )
    assert total > 0, "hud.draw() did not call ui.textColored at all"


def test_hud_draw_with_realtime_hint(lua):
    """RT-03: hud.draw() handles realtimeHint without crashes."""
    hud = lua.execute('local m = require("hud"); return m')
    vm = lua.eval("""
        {
            recording = true,
            speed = 120,
            brake = 0,
            lapCount = 2,
            bestLapMs = 60000,
            lastLapMs = 61000,
            deltaSmoothedSec = -0.05,
            appVersionUi = "v0.5.0",
            realtimeHint = {
                text = "T5: brake earlier",
                kind = "brake",
                cornerLabel = "T5",
            },
            focusPracticeActive = true,
            focusPracticeLabel = "T5 + T6",
        }
    """)
    hud["draw"](vm)
    violations, total = lua.execute("return _get_text_colored_violations()")
    violation_list = list(violations.values()) if violations else []
    assert not violation_list, f"realtime hint draw made violations: {violation_list}"


def test_hud_settings_module_loads(lua):
    """RT-04: hud_settings.lua loads without error."""
    settings = lua.execute('local m = require("hud_settings"); return m')
    assert settings is not None


def test_coaching_overlay_module_loads(lua):
    """RT-05: coaching_overlay.lua loads without error."""
    overlay = lua.execute('local m = require("coaching_overlay"); return m')
    assert overlay is not None
    assert overlay["drawApproachPanel"] is not None


def test_realtime_coaching_module_loads(lua):
    """RT-06: realtime_coaching.lua loads without error."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    assert rtc is not None
    assert rtc["tick"] is not None
