"""Lua runtime smoke tests for HUD modules using lupa."""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"

STUB_UI_LUA = r"""
ui = {}
_calls = {}
_text_colored_calls = {}
_draw_rect_filled_calls = {}

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
function ui.drawRectFilled(p0, p1, color, rounding)
    _draw_rect_filled_calls[#_draw_rect_filled_calls + 1] = true
end
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
    violations, _total = lua.execute("return _get_text_colored_violations()")
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


def test_hud_draw_exercises_coaching_strip(lua):
    """RT-07: hud.draw() with active coaching lines exercises drawMainWindowStrip."""
    hud = lua.execute('local m = require("hud"); return m')
    vm = lua.eval("""
        {
            recording = true,
            speed = 80,
            brake = 0.3,
            lapCount = 3,
            bestLapMs = 60000,
            lastLapMs = 61500,
            deltaSmoothedSec = 0.05,
            appVersionUi = "v0.5.0",
            coachingLines = {
                { kind = "brake", text = "T5: brake earlier" },
                { kind = "line", text = "T8: smoother turn-in" },
            },
            coachingRemaining = 5.0,
            coachingHoldSeconds = 30,
            coachingMaxVisibleHints = 3,
            coachingShowPrimer = false,
        }
    """)
    hud["draw"](vm)
    violations, _total = lua.execute("return _get_text_colored_violations()")
    violation_list = list(violations.values()) if violations else []
    assert not violation_list, f"coaching strip path made {len(violation_list)} reversed call(s)"


def test_coaching_overlay_draw_approach_panel(lua):
    """RT-08: coaching_overlay.drawApproachPanel() exercises Part C panel."""
    overlay = lua.execute('local m = require("coaching_overlay"); return m')
    approach = lua.eval("""
        {
            turnLabel = "T5",
            targetSpeedKmh = 95,
            currentSpeedKmh = 110,
            distanceToBrakeM = 80,
            status = "approaching",
            progressPct = 0.6,
            brakeIndex = 1,
        }
    """)
    overlay["drawApproachPanel"](approach)
    violations, _total = lua.execute("return _get_text_colored_violations()")
    violation_list = list(violations.values()) if violations else []
    assert not violation_list, f"drawApproachPanel made {len(violation_list)} reversed call(s)"


def test_coaching_overlay_main_window_strip(lua):
    """RT-09: coaching_overlay.drawMainWindowStrip() exercises strip rendering."""
    overlay = lua.execute('local m = require("coaching_overlay"); return m')
    vm = lua.eval("""
        {
            coachingLines = {
                { kind = "brake", text = "T5: brake earlier" },
                { kind = "line", text = "T8: smoother turn-in" },
                { kind = "positive", text = "T9: matched reference" },
            },
            coachingRemaining = 10.0,
            coachingHoldSeconds = 30,
            coachingMaxVisibleHints = 3,
            coachingShowPrimer = false,
        }
    """)
    overlay["drawMainWindowStrip"](vm)
    violations, _total = lua.execute("return _get_text_colored_violations()")
    violation_list = list(violations.values()) if violations else []
    assert not violation_list, f"drawMainWindowStrip made {len(violation_list)} reversed call(s)"


def test_hud_settings_draw_full_path(lua):
    """RT-10: hud_settings.draw() with full viewmodel exercises all settings paths."""
    settings = lua.execute('local m = require("hud_settings"); return m')
    if settings["draw"] is None:
        pytest.skip("hud_settings.draw not exported")
    vm = lua.eval("""
        {
            config = {
                hudEnabled = true,
                approachMeters = 200,
                coachingHoldSeconds = 30,
                racingLineMode = "best",
                lineStyle = "tilt",
                racingLineEnabled = true,
                brakeMarkersEnabled = true,
                enableRenderDiagnostics = false,
                enableDraw3DDiagnostics = false,
            },
            stats = {
                telemetrySamples = 1234,
                brakeBest = 5,
                brakeLast = 4,
                brakeSession = 12,
                segmentCount = 17,
            },
            focusPracticeUi = {
                focusPracticeActive = false,
                focusPracticeHudSummary = "",
            },
        }
    """)
    settings["draw"](vm)
    violations, _total = lua.execute("return _get_text_colored_violations()")
    violation_list = list(violations.values()) if violations else []
    assert not violation_list, f"hud_settings.draw made {len(violation_list)} reversed call(s)"


def test_realtime_coaching_tick(lua):
    """RT-11: realtime_coaching.tick() executes without errors."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    segments = lua.eval("""
        {
            { kind = "straight", s0 = 0.0, s1 = 0.3, label = "S1" },
            { kind = "brake", s0 = 0.3, s1 = 0.35, label = "B1" },
            { kind = "corner", s0 = 0.35, s1 = 0.45, label = "T5", brakeSpline = 0.3 },
            { kind = "straight", s0 = 0.45, s1 = 1.0, label = "S2" },
        }
    """)
    rtc["rebuildSegmentIndex"](segments)
    opts = lua.eval("""
        {
            splinePos = 0.25,
            lapCount = 1,
            segments = nil,
            bestCornerFeatures = {},
            lastLapCornerFeats = {},
            trackLengthM = 5000,
            approachMeters = 200,
        }
    """)
    rtc["tick"](opts)
    rtc["reset"]()


# --------------------------------------------------------------------------
# Issue #69: visual rewrite smoke tests (RT12..RT17)
# --------------------------------------------------------------------------


def _count_text_calls(lua, literal: str) -> int:
    """Count how many textColored calls contain the given literal."""
    code = f"""
    local n = 0
    for i = 1, #_text_colored_calls do
        local c = _text_colored_calls[i]
        if type(c.text) == "string" and c.text:find({literal!r}, 1, true) then
            n = n + 1
        end
    end
    return n
    """
    return lua.execute(code)


def _count_draw_rects(lua) -> int:
    return lua.execute("return #_draw_rect_filled_calls")


def test_rt12_top_tile_renders_full_window_bg(lua):
    """RT-12: hud.draw with a hint renders drawRectFilled at (0,0) -> (w,h)."""
    hud = lua.execute('local m = require("hud"); return m')
    vm = lua.eval("""
        {
            recording = true,
            speed = 142,
            brake = 0.4,
            lapCount = 3,
            bestLapMs = 59918,
            lastLapMs = 61200,
            deltaSmoothedSec = 0.15,
            appVersionUi = "v0.4.2",
            realtimeHint = {
                text = "LESS COASTING ON THROTTLE",
                kind = "brake",
                cornerLabel = "T4 LEFT",
            },
        }
    """)
    hud["draw"](vm)
    violations, _ = lua.execute("return _get_text_colored_violations()")
    vl = list(violations.values()) if violations else []
    assert not vl, f"top tile hint path made reversed textColored calls: {vl}"
    # Must draw the panel background
    assert _count_draw_rects(lua) >= 1, "top tile must drawRectFilled for panel bg"
    # Must contain the title literal
    assert _count_text_calls(lua, "ACTIVE SUGGESTION") >= 1, (
        "top tile must render 'ACTIVE SUGGESTION' title"
    )
    # Must contain the uppercase hint text
    assert _count_text_calls(lua, "LESS COASTING") >= 1, "hint text must be rendered"


def test_rt13_top_tile_idle_state_visible(lua):
    """RT-13: hud.draw with NO hint still renders the idle panel (not blank)."""
    hud = lua.execute('local m = require("hud"); return m')
    vm = lua.eval("""
        {
            recording = false,
            speed = 0,
            brake = 0,
            lapCount = 0,
            bestLapMs = nil,
            lastLapMs = nil,
            deltaSmoothedSec = nil,
            appVersionUi = "v0.4.2",
            realtimeHint = nil,
        }
    """)
    hud["draw"](vm)
    # Idle state must still draw something (panel chrome + title)
    assert _count_draw_rects(lua) >= 1, "idle state must draw panel chrome"
    assert _count_text_calls(lua, "ACTIVE SUGGESTION") >= 1
    assert _count_text_calls(lua, "Complete a lap for coaching hints") >= 1, (
        "idle state must render placeholder guidance copy"
    )


def test_rt14_bottom_tile_renders_when_approaching(lua):
    """RT-14: drawApproachPanel renders all expected literals when status='approaching'."""
    overlay = lua.execute('local m = require("coaching_overlay"); return m')
    approach = lua.eval("""
        {
            turnLabel = "T4 LEFT",
            targetSpeedKmh = 125,
            currentSpeedKmh = 142,
            distanceToBrakeM = 150,
            status = "approaching",
            progressPct = 0.6,
            brakeIndex = 1,
        }
    """)
    result = overlay["drawApproachPanel"](approach)
    assert result, "drawApproachPanel should return true when status=approaching"
    violations, _ = lua.execute("return _get_text_colored_violations()")
    vl = list(violations.values()) if violations else []
    assert not vl, f"drawApproachPanel made reversed textColored calls: {vl}"
    # Must contain all the design-brief literals
    assert _count_text_calls(lua, "APPROACHING") >= 1
    assert _count_text_calls(lua, "T4 LEFT") >= 1
    assert _count_text_calls(lua, "TARGET ENTRY") >= 1
    assert _count_text_calls(lua, "CURRENT") >= 1
    assert _count_text_calls(lua, "DISTANCE TO BRAKING POINT") >= 1
    assert _count_text_calls(lua, "AG PORSCHE ACADEMY") >= 1
    # Must NOT contain the legacy footer
    assert _count_text_calls(lua, "AC COPILOT TRAINER") == 0
    # Must draw panel background + shared right box + dividers + progress bar
    assert _count_draw_rects(lua) >= 4


def test_rt15_bottom_tile_hidden_when_not_approaching(lua):
    """RT-15: drawApproachPanel returns false when status != 'approaching'."""
    overlay = lua.execute('local m = require("coaching_overlay"); return m')
    approach = lua.eval("""
        {
            turnLabel = "T4",
            targetSpeedKmh = 125,
            currentSpeedKmh = 90,
            distanceToBrakeM = 999,
            status = "match",
            progressPct = 0.0,
        }
    """)
    result = overlay["drawApproachPanel"](approach)
    assert not result, "drawApproachPanel must return false when status != approaching"
    # No textColored literals for the panel should have been rendered
    assert _count_text_calls(lua, "TARGET ENTRY") == 0
    assert _count_text_calls(lua, "AG PORSCHE ACADEMY") == 0


def test_rt16_bottom_tile_hidden_when_nil(lua):
    """RT-16: drawApproachPanel returns false when approachData is nil."""
    overlay = lua.execute('local m = require("coaching_overlay"); return m')
    result = overlay["drawApproachPanel"](None)
    assert not result, "drawApproachPanel must return false for nil data"


def test_rt17_bottom_tile_speed_color_delta(lua):
    """RT-17: CURRENT number is red when > target+8, green when <= target."""
    overlay = lua.execute('local m = require("coaching_overlay"); return m')
    # Case 1: too fast -> red
    approach_fast = lua.eval("""
        {
            turnLabel = "T4",
            targetSpeedKmh = 100,
            currentSpeedKmh = 120,
            distanceToBrakeM = 80,
            status = "approaching",
            progressPct = 0.5,
        }
    """)
    lua.execute("_text_colored_calls = {}")
    overlay["drawApproachPanel"](approach_fast)
    # Find the "120" call and check its color.r > 0.8 (red)
    red_ok = lua.execute("""
        for i = 1, #_text_colored_calls do
            local c = _text_colored_calls[i]
            if type(c.text) == "string" and c.text == "120" then
                if c.color and c.color.r and c.color.r > 0.8 and c.color.g < 0.4 then
                    return true
                end
                return false
            end
        end
        return false
    """)
    assert red_ok, "CURRENT=120 with target=100 must render red"

    # Case 2: under target -> green
    approach_slow = lua.eval("""
        {
            turnLabel = "T4",
            targetSpeedKmh = 100,
            currentSpeedKmh = 90,
            distanceToBrakeM = 80,
            status = "approaching",
            progressPct = 0.5,
        }
    """)
    lua.execute("_text_colored_calls = {}")
    overlay["drawApproachPanel"](approach_slow)
    green_ok = lua.execute("""
        for i = 1, #_text_colored_calls do
            local c = _text_colored_calls[i]
            if type(c.text) == "string" and c.text == "90" then
                if c.color and c.color.g and c.color.g > 0.7 and c.color.r < 0.4 then
                    return true
                end
                return false
            end
        end
        return false
    """)
    assert green_ok, "CURRENT=90 with target=100 must render green"

    # Case 3: exactly at target -> green (delta <= 0)
    approach_match = lua.eval("""
        {
            turnLabel = "T4",
            targetSpeedKmh = 100,
            currentSpeedKmh = 100,
            distanceToBrakeM = 80,
            status = "approaching",
            progressPct = 0.5,
        }
    """)
    lua.execute("_text_colored_calls = {}")
    overlay["drawApproachPanel"](approach_match)
    green100_ok = lua.execute("""
        for i = 1, #_text_colored_calls do
            local c = _text_colored_calls[i]
            if type(c.text) == "string" and c.text == "100" then
                if c.color and c.color.g and c.color.g > 0.7 and c.color.r < 0.4 then
                    return true
                end
            end
        end
        return false
    """)
    assert green100_ok, "CURRENT=100 with target=100 must render green at boundary"

    # Case 4: exactly target+8 -> white band (not red; delta > 8 is strict)
    approach_edge = lua.eval("""
        {
            turnLabel = "T4",
            targetSpeedKmh = 100,
            currentSpeedKmh = 108,
            distanceToBrakeM = 80,
            status = "approaching",
            progressPct = 0.5,
        }
    """)
    lua.execute("_text_colored_calls = {}")
    overlay["drawApproachPanel"](approach_edge)
    white108_ok = lua.execute("""
        for i = 1, #_text_colored_calls do
            local c = _text_colored_calls[i]
            if type(c.text) == "string" and c.text == "108" then
                local col = c.color
                if col and col.r > 0.85 and col.g > 0.85 then
                    return true
                end
                return false
            end
        end
        return false
    """)
    assert white108_ok, "CURRENT=108 with target=100 must render white (threshold, not red)"
