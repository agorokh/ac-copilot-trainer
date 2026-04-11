"""End-to-end product-gate tests for the Phase 5 HUD rebuild (issue #72).

These tests are the contract for the live-frame engine + always-visible tiles
+ bundled fonts + locked window size. They MUST fail on `main` before the
rebuild lands and turn green only when the rebuild is complete. Bots cannot
greenlight a partial fix because pytest stays red until ETE-01..ETE-08 all pass.

Each test mirrors a real session state from the user's CSP log evidence.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES = REPO / "src" / "ac_copilot_trainer" / "modules"
ENTRY = REPO / "src" / "ac_copilot_trainer" / "ac_copilot_trainer.lua"
MANIFEST = REPO / "src" / "ac_copilot_trainer" / "manifest.ini"
FONTS_DIR = REPO / "src" / "ac_copilot_trainer" / "content" / "fonts"
ASSETS_DIR = REPO / "src" / "ac_copilot_trainer" / "content" / "assets"

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

STUB_UI_LUA = r"""
ui = {}
_calls = {}
_text_colored_calls = {}
_dwrite_text_calls = {}
_draw_image_calls = {}
_draw_rect_filled_calls = {}
_path_arc_calls = {}
_pushed_dwrite_fonts = {}
_resize_calls = {}
_move_calls = {}
_storage_state = {}

function ui.text(s)
    _calls[#_calls + 1] = { name = "text", arg = s }
end
function ui.textColored(text, color)
    _text_colored_calls[#_text_colored_calls + 1] = {
        text = text, color = color,
        text_type = type(text), color_type = type(color),
    }
end
function ui.textWrapped(s) end
function ui.separator() end
function ui.sameLine(a, b) end
function ui.windowSize() return _vec2(640, 240) end
function ui.windowPos() return _vec2(100, 100) end
function ui.getCursor() return _vec2(0, 0) end
function ui.getCursorY() return 0 end
function ui.setCursor(v) end
function ui.drawRectFilled(p0, p1, color, rounding, flags)
    _draw_rect_filled_calls[#_draw_rect_filled_calls + 1] = {
        p0 = p0, p1 = p1, color = color, rounding = rounding,
    }
end
function ui.drawRect() end
function ui.drawLine() end
function ui.drawCircleFilled() end
function ui.drawImage(asset, p0, p1, color)
    _draw_image_calls[#_draw_image_calls + 1] = { asset = asset, color = color }
end
function ui.drawImageQuad() end
function ui.pathClear() end
function ui.pathArcTo(center, radius, a1, a2, segments)
    _path_arc_calls[#_path_arc_calls + 1] = { center = center, radius = radius }
end
function ui.pathLineTo() end
function ui.pathStroke() end
function ui.pathFillConvex() end
function ui.deltaTime() return 0.016 end
function ui.checkbox(label, current) return false end
function ui.slider(label, val, min, max, fmt) return val, false end
function ui.combo(label, preview, flags, fn) end
function ui.selectable(label, sel) return false end
function ui.pushFont() end
function ui.popFont() end
function ui.pushDWriteFont(name)
    _pushed_dwrite_fonts[#_pushed_dwrite_fonts + 1] = name
end
function ui.popDWriteFont() end
function ui.dwriteDrawText(text, fontPx, position, color)
    _dwrite_text_calls[#_dwrite_text_calls + 1] = {
        text = text, fontPx = fontPx, color = color, position = position,
    }
end
function ui.dwriteText(text, fontPx, color)
    _dwrite_text_calls[#_dwrite_text_calls + 1] = {
        text = text, fontPx = fontPx, color = color,
    }
end
function ui.measureDWriteText(text, fontPx)
    return _vec2(string.len(text or "") * fontPx * 0.55, fontPx)
end
function ui.measureText(text, wrap) return _vec2(string.len(text or "") * 7, 14) end
function ui.beginGroup() end
function ui.endGroup() end
function ui.pushClipRect() end
function ui.popClipRect() end
function ui.pushStyleColor() end
function ui.popStyleColor() end
function ui.pushStyleVar() end
function ui.popStyleVar() end
function ui.itemHovered() return false end
function ui.invisibleButton() return false end
function ui.calcTextSize(text) return _vec2(string.len(text or "") * 7, 14) end
function ui.button() return false end
function ui.mouseLocalPos() return _vec2(0, 0) end
function ui.mouseClicked() return false end
function ui.MouseButton() return 0 end
ui.Font = { Title = "title", Main = "main", Small = "small" }
ui.WindowFlags = { None = 0 }
ui.StyleColor = { Text = 1 }
ui.StyleVar = { Alpha = 1 }
ui.MouseButton = { Left = 0, Right = 1 }

-- ui.DWriteFont returns a wrapper table that records its constructor args.
-- We track it so tests can verify "Michroma:/content/fonts;..." style usage.
function ui.DWriteFont(spec)
    return { _isDWriteFont = true, _spec = spec }
end

local _rgbm_meta = {}
function _rgbm_meta.__call(_, r, g, b, m)
    return { r = r or 0, g = g or 0, b = b or 0, mult = m or 1, _isRgbm = true }
end
rgbm = setmetatable({}, _rgbm_meta)
rgbm.colors = {
    red = rgbm(1, 0, 0, 1),
    white = rgbm(1, 1, 1, 1),
    transparent = rgbm(0, 0, 0, 0),
}

function _vec2(x, y) return { x = x or 0, y = y or 0, _isVec2 = true } end
vec2 = _vec2
function vec3(x, y, z) return { x = x or 0, y = y or 0, z = z or 0 } end

ac = {
    log = function() end,
    getFolder = function() return "" end,
    FolderID = { Root = 0, ScriptConfig = 1, AppLuaRoot = 2 },
    getAppWindows = function()
        return {
            { name = "AC_Copilot_Trainer/AC Copilot Trainer", title = "AC Copilot Trainer" },
            { name = "AC_Copilot_Trainer/Coaching", title = "Coaching" },
            { name = "AC_Copilot_Trainer/Settings", title = "Settings" },
        }
    end,
    accessAppWindow = function(name)
        return {
            valid = function() return true end,
            position = function() return _vec2(0, 0) end,
            size = function() return _vec2(640, 240) end,
            move = function(self, v)
                _move_calls[#_move_calls + 1] = { name = name, pos = v }
                return self
            end,
            resize = function(self, v)
                _resize_calls[#_resize_calls + 1] = { name = name, size = v }
                return self
            end,
            setVisible = function(self) return self end,
            setPinned = function(self) return self end,
            visible = function() return true end,
            pinned = function() return false end,
        }
    end,
    storage = function(key_or_layout, default)
        if type(key_or_layout) == "string" then
            local key = key_or_layout
            return {
                get = function() return _storage_state[key] or default end,
                set = function(_, v) _storage_state[key] = v end,
            }
        end
        return key_or_layout
    end,
    getSim = function()
        return {
            isInMainMenu = false,
            windowWidth = 1920,
            windowHeight = 1080,
            trackLengthM = 4500,
        }
    end,
    getCar = function() return nil end,
    getUI = function() return { uiScale = 1.0 } end,
}

-- Suppress legacy BMW.txt font lookup so coaching_font cache initialisation
-- never tries to open a non-existent file in this stub environment.
local _real_open = io.open
io.open = function(path, mode)
    if path and (string.find(path, "bmw") or string.find(path, "BMW")) then return nil end
    return _real_open(path, mode)
end

function _reset_recorders()
    _calls = {}
    _text_colored_calls = {}
    _dwrite_text_calls = {}
    _draw_image_calls = {}
    _draw_rect_filled_calls = {}
    _path_arc_calls = {}
    _pushed_dwrite_fonts = {}
end

function _count_dwrite_text(literal)
    local n = 0
    for i = 1, #_dwrite_text_calls do
        local c = _dwrite_text_calls[i]
        if type(c.text) == "string" and string.find(c.text, literal, 1, true) then
            n = n + 1
        end
    end
    return n
end

function _last_pushed_font_spec()
    if #_pushed_dwrite_fonts == 0 then return nil end
    local f = _pushed_dwrite_fonts[#_pushed_dwrite_fonts]
    if type(f) == "table" and f._isDWriteFont then return f._spec end
    return tostring(f)
end

function _all_pushed_font_specs()
    local out = {}
    for i = 1, #_pushed_dwrite_fonts do
        local f = _pushed_dwrite_fonts[i]
        if type(f) == "table" and f._isDWriteFont then
            out[#out + 1] = f._spec
        else
            out[#out + 1] = tostring(f)
        end
    end
    return out
end
"""


@pytest.fixture
def lua():
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    rt.execute(STUB_UI_LUA)
    modules_path = str(MODULES).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{modules_path}/?.lua"')
    return rt


def _build_trace(lua, n: int = 2000):  # noqa: ANN001,ANN202  -- lua is lupa runtime
    """Build a 2000-sample best lap trace matching the persistence file shape:
    each sample is { spline, eMs, speed }, sorted by spline 0..1.
    """
    return lua.execute(f"""
        local t = {{}}
        for i = 1, {n} do
            local sp = (i - 1) / ({n} - 1)
            t[i] = {{ spline = sp, eMs = sp * 60000, speed = 100 + 60 * math.sin(sp * 6.28) }}
        end
        return t
    """)


def _build_brake_points(lua):  # noqa: ANN001,ANN202
    """7 brake points matching the user's persistence file."""
    return lua.execute("""
        return {
            { spline = 0.10, px = 0, py = 0, pz = 0, entrySpeed = 95,  label = "T1" },
            { spline = 0.22, px = 0, py = 0, pz = 0, entrySpeed = 110, label = "T2" },
            { spline = 0.36, px = 0, py = 0, pz = 0, entrySpeed = 85,  label = "T3" },
            { spline = 0.45, px = 0, py = 0, pz = 0, entrySpeed = 95,  label = "T4" },
            { spline = 0.58, px = 0, py = 0, pz = 0, entrySpeed = 120, label = "T5" },
            { spline = 0.71, px = 0, py = 0, pz = 0, entrySpeed = 80,  label = "T6" },
            { spline = 0.88, px = 0, py = 0, pz = 0, entrySpeed = 100, label = "T7" },
        }
    """)


def _build_segments(lua):  # noqa: ANN001,ANN202
    """13 segments (straight + brake + corner alternating)."""
    return lua.execute("""
        return {
            { kind = "straight", s0 = 0.00, s1 = 0.08, label = "S1" },
            { kind = "brake",    s0 = 0.08, s1 = 0.10, label = "B1" },
            { kind = "corner",   s0 = 0.10, s1 = 0.16, label = "T1", brakeSpline = 0.08 },
            { kind = "straight", s0 = 0.16, s1 = 0.20, label = "S2" },
            { kind = "brake",    s0 = 0.20, s1 = 0.22, label = "B2" },
            { kind = "corner",   s0 = 0.22, s1 = 0.28, label = "T2", brakeSpline = 0.20 },
            { kind = "straight", s0 = 0.28, s1 = 0.43, label = "S3" },
            { kind = "brake",    s0 = 0.43, s1 = 0.45, label = "B4" },
            { kind = "corner",   s0 = 0.45, s1 = 0.52, label = "T4", brakeSpline = 0.43 },
            { kind = "straight", s0 = 0.52, s1 = 0.56, label = "S4" },
            { kind = "brake",    s0 = 0.56, s1 = 0.58, label = "B5" },
            { kind = "corner",   s0 = 0.58, s1 = 0.66, label = "T5", brakeSpline = 0.56 },
            { kind = "straight", s0 = 0.66, s1 = 1.00, label = "S5" },
        }
    """)


# ---------------------------------------------------------------------------
# ETE-01: Empty session (no persistence, no laps)
# ---------------------------------------------------------------------------


def test_ete01_empty_session_returns_placeholder(lua):
    """ETE-01: With no persistence at all, realtime_coaching.tick MUST return a
    placeholder viewmodel (not nil), and hud.draw MUST render panel chrome."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    rtc["reset"]()
    opts = lua.eval("""
        {
            splinePos = 0.50,
            currentSpeedKmh = 90,
            bestSortedTrace = nil,
            brakingPoints = {},
            segments = {},
            trackLengthM = 4500,
        }
    """)
    view = rtc["tick"](opts)
    assert view is not None, "tick must return a viewmodel even with no data"
    assert view["primaryLine"] is not None, "must have a primaryLine in empty state"
    assert view["subState"] == "no_reference", (
        f"empty state subState must be 'no_reference', got {view['subState']}"
    )

    # hud.draw still renders chrome + ACTIVE SUGGESTION title
    lua.execute("_reset_recorders()")
    hud = lua.execute('local m = require("hud"); return m')
    vm = lua.eval("""
        {
            recording = false, speed = 0, brake = 0, lapCount = 0,
            bestLapMs = nil, lastLapMs = nil, deltaSmoothedSec = nil,
            appVersionUi = "v0.5.0",
            realtimeHint = nil,
            realtimeView = {
                primaryLine = "DRIVE A LAP",
                secondaryLine = "REFERENCE WILL APPEAR",
                kind = "placeholder",
                subState = "no_reference",
            },
        }
    """)
    hud["draw"](vm)
    rect_count = lua.execute("return #_draw_rect_filled_calls")
    assert rect_count >= 1, "hud.draw must render at least one drawRectFilled (panel chrome)"
    assert lua.execute('return _count_dwrite_text("ACTIVE SUGGESTION")') >= 1, (
        "hud.draw must render 'ACTIVE SUGGESTION' title via dwriteDrawText"
    )
    assert lua.execute('return _count_dwrite_text("DRIVE A LAP")') >= 1, (
        "empty state must render 'DRIVE A LAP' placeholder"
    )


# ---------------------------------------------------------------------------
# ETE-02: Persistence loaded, no current-session lap (the user's actual scenario)
# ---------------------------------------------------------------------------


def test_ete02_persisted_state_no_current_lap_fires_brake_hint(lua):
    """ETE-02: With persisted brake points + trace + segments BUT empty
    lastLapCornerFeats (current code's kill switch), the new live-frame engine
    MUST fire 'BRAKE NOW' when 50 m before a brake point at 142 km/h vs target 95.
    This is the test that PROVES the bug — buildRealTime returns nil today."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    rtc["reset"]()
    trace = _build_trace(lua)
    brakes = _build_brake_points(lua)
    segments = _build_segments(lua)
    # T4 brake-point spline is 0.45; with trackLength 4500 m, splinePos 0.443
    # puts the car ~31 m before the brake point (inside the 50 m BRAKE_NOW window).
    opts = lua.eval("""
        {
            splinePos = 0.443,
            currentSpeedKmh = 142,
            bestSortedTrace = nil,
            brakingPoints = nil,
            segments = nil,
            trackLengthM = 4500,
        }
    """)
    opts["bestSortedTrace"] = trace
    opts["brakingPoints"] = brakes
    opts["segments"] = segments
    view = rtc["tick"](opts)
    assert view is not None, "tick must return a viewmodel"
    primary = view["primaryLine"] or ""
    assert "BRAKE" in primary.upper(), (
        f"~31 m before T4 (target 95) at 142 km/h must say 'BRAKE NOW', got: {primary!r}"
    )
    assert view["kind"] == "brake", f"kind must be 'brake', got {view['kind']}"
    assert view["cornerLabel"] == "T4", f"cornerLabel must be 'T4', got {view['cornerLabel']}"


# ---------------------------------------------------------------------------
# ETE-03: Same persisted state but on a straight, far from any brake point
# ---------------------------------------------------------------------------


def test_ete03_persisted_state_straight_returns_on_pace(lua):
    """ETE-03: On a long straight, far from the next brake point, return
    'ON PACE' / 'NEXT: <corner>'."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    rtc["reset"]()
    trace = _build_trace(lua)
    brakes = _build_brake_points(lua)
    segments = _build_segments(lua)
    opts = lua.eval("""
        {
            splinePos = 0.30,
            currentSpeedKmh = 200,
            bestSortedTrace = nil, brakingPoints = nil, segments = nil,
            trackLengthM = 4500,
        }
    """)
    opts["bestSortedTrace"] = trace
    opts["brakingPoints"] = brakes
    opts["segments"] = segments
    view = rtc["tick"](opts)
    assert view is not None
    primary = (view["primaryLine"] or "").upper()
    # On a long straight, far from a brake point, we should see informational copy
    assert "PACE" in primary or "NEXT" in primary or "FREE" in primary, (
        f"long-straight viewmodel should be informational, got: {primary!r}"
    )
    assert view["kind"] == "info", (
        f"kind must be 'info' on a long straight with valid persisted data, got {view['kind']}"
    )


# ---------------------------------------------------------------------------
# ETE-04: In a corner segment, slower than reference
# ---------------------------------------------------------------------------


def test_ete04_in_corner_slower_than_reference_says_carry_more_speed(lua):
    """ETE-04: Mid-corner with current speed 12 km/h slower than the reference
    speed at the same spline position must produce a 'CARRY MORE SPEED' hint."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    rtc["reset"]()
    trace = _build_trace(lua)
    brakes = _build_brake_points(lua)
    segments = _build_segments(lua)
    # Inside T4 apex window only (first 30% of segment, capped — see
    # realtime_coaching.inCornerSegment). s0=0.45, span=0.07 → apexEnd≈0.471.
    sp = 0.465
    # Compute reference speed at sp (matches our trace formula)
    import math

    ref_speed = 100 + 60 * math.sin(sp * 6.28)
    cur_speed = ref_speed - 12  # 12 km/h slower

    opts = lua.eval(f"""
        {{
            splinePos = {sp},
            currentSpeedKmh = {cur_speed},
            bestSortedTrace = nil, brakingPoints = nil, segments = nil,
            trackLengthM = 4500,
        }}
    """)
    opts["bestSortedTrace"] = trace
    opts["brakingPoints"] = brakes
    opts["segments"] = segments
    view = rtc["tick"](opts)
    assert view is not None
    primary = (view["primaryLine"] or "").upper()
    assert "CARRY" in primary and "SPEED" in primary, (
        f"in-corner-slow viewmodel must say 'CARRY MORE SPEED', got: {primary!r}"
    )
    assert view["kind"] == "line", f"in-corner kind must be 'line', got {view['kind']}"


# ---------------------------------------------------------------------------
# ETE-04b: PREPARE TO BRAKE in the 50-100 m window with mild over-speed
# ---------------------------------------------------------------------------


def test_ete04b_prepare_to_brake_mid_distance(lua):
    """ETE-04b: At ~80 m before T4 with target 95, current 105 (over+10) the
    engine fires PREPARE TO BRAKE — neither too far for any hint nor close
    enough for the urgent BRAKE NOW threshold."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    rtc["reset"]()
    trace = _build_trace(lua)
    brakes = _build_brake_points(lua)
    segments = _build_segments(lua)
    # T4 brake spline 0.45; ~80 m before at 4500 m → splinePos 0.4322
    opts = lua.eval(
        "{ splinePos = 0.4322, currentSpeedKmh = 105, "
        "  bestSortedTrace = nil, brakingPoints = nil, segments = nil, trackLengthM = 4500 }"
    )
    opts["bestSortedTrace"] = trace
    opts["brakingPoints"] = brakes
    opts["segments"] = segments
    view = rtc["tick"](opts)
    assert view is not None
    primary = (view["primaryLine"] or "").upper()
    assert "PREPARE" in primary, (
        f"~80 m before T4 (target 95) at 105 km/h must say 'PREPARE TO BRAKE', got: {primary!r}"
    )
    assert view["kind"] == "brake", f"kind must be 'brake', got {view['kind']}"


# ---------------------------------------------------------------------------
# ETE-04c: EASE OFF when in-corner and faster than reference
# ---------------------------------------------------------------------------


def test_ete04c_ease_off_in_corner_faster_than_reference(lua):
    """ETE-04c: In a corner segment, current speed 12 km/h faster than the
    reference at the same spline → EASE OFF."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    rtc["reset"]()
    trace = _build_trace(lua)
    brakes = _build_brake_points(lua)
    segments = _build_segments(lua)
    import math

    sp = 0.465  # within T4 apex window (see test_ete04)
    ref_speed = 100 + 60 * math.sin(sp * 6.28)
    cur_speed = ref_speed + 12
    opts = lua.eval(
        f"{{ splinePos = {sp}, currentSpeedKmh = {cur_speed}, "
        "  bestSortedTrace = nil, brakingPoints = nil, segments = nil, trackLengthM = 4500 }"
    )
    opts["bestSortedTrace"] = trace
    opts["brakingPoints"] = brakes
    opts["segments"] = segments
    view = rtc["tick"](opts)
    assert view is not None
    primary = (view["primaryLine"] or "").upper()
    assert "EASE" in primary, f"in-corner-fast viewmodel must say 'EASE OFF', got: {primary!r}"
    assert view["kind"] == "line"


# ---------------------------------------------------------------------------
# ETE-04d: dedupe must NOT collapse PREPARE TO BRAKE → BRAKE NOW
# ---------------------------------------------------------------------------


def test_ete04d_dedupe_allows_prepare_to_brake_escalation(lua):
    """ETE-04d: Within 600 ms, escalating from PREPARE TO BRAKE to BRAKE NOW
    must NOT be collapsed by the dedupe key. The dedupe key must include
    primaryLine or subState so the urgent message is shown immediately."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    rtc["reset"]()
    trace = _build_trace(lua)
    brakes = _build_brake_points(lua)
    segments = _build_segments(lua)

    # Frame 1: ~80 m before T4 at 105 km/h → PREPARE TO BRAKE
    opts1 = lua.eval(
        "{ splinePos = 0.4322, currentSpeedKmh = 105, dt = 0.016, "
        "  bestSortedTrace = nil, brakingPoints = nil, segments = nil, trackLengthM = 4500 }"
    )
    opts1["bestSortedTrace"] = trace
    opts1["brakingPoints"] = brakes
    opts1["segments"] = segments
    view1 = rtc["tick"](opts1)
    assert "PREPARE" in (view1["primaryLine"] or "").upper()

    # Frame 2 (50 ms later): ~31 m before T4 at 142 km/h → BRAKE NOW
    # This MUST NOT be collapsed by the (kind=brake, cornerLabel=T4) key
    opts2 = lua.eval(
        "{ splinePos = 0.443, currentSpeedKmh = 142, dt = 0.05, "
        "  bestSortedTrace = nil, brakingPoints = nil, segments = nil, trackLengthM = 4500 }"
    )
    opts2["bestSortedTrace"] = trace
    opts2["brakingPoints"] = brakes
    opts2["segments"] = segments
    view2 = rtc["tick"](opts2)
    primary2 = (view2["primaryLine"] or "").upper()
    assert "BRAKE NOW" in primary2 or primary2.split()[0] == "BRAKE", (
        f"escalation PREPARE→BRAKE NOW must not be dedupe-collapsed, got: {primary2!r}"
    )


# ---------------------------------------------------------------------------
# ETE-04e: in-corner cornerLabel must be the CURRENT corner, not the next
# ---------------------------------------------------------------------------


def test_ete04e_in_corner_label_overrides_next_corner(lua):
    """ETE-04e: When the car is INSIDE T4, the viewmodel.cornerLabel must be
    'T4', not the label of the next brake point ahead."""
    rtc = lua.execute('local m = require("realtime_coaching"); return m')
    rtc["reset"]()
    trace = _build_trace(lua)
    brakes = _build_brake_points(lua)
    segments = _build_segments(lua)
    # Inside T4 apex window (not the full s0..s1 span — see inCornerSegment).
    opts = lua.eval(
        "{ splinePos = 0.465, currentSpeedKmh = 60, "
        "  bestSortedTrace = nil, brakingPoints = nil, segments = nil, trackLengthM = 4500 }"
    )
    opts["bestSortedTrace"] = trace
    opts["brakingPoints"] = brakes
    opts["segments"] = segments
    view = rtc["tick"](opts)
    assert view is not None
    assert view["cornerLabel"] == "T4", (
        f"in-corner cornerLabel must be the current corner T4, got {view['cornerLabel']}"
    )


# ---------------------------------------------------------------------------
# ETE-05: Manifest contract — FIXED_SIZE + PADDING=0,0
# ---------------------------------------------------------------------------


def test_ete05_manifest_contract():
    """ETE-05: manifest.ini WINDOW_0 and WINDOW_1 have FIXED_SIZE + PADDING=0,0
    + reasonable defaults. The user's 132x456 saved geometry is recovered by
    FIXED_SIZE."""
    text = MANIFEST.read_text(encoding="utf-8")
    # Extract WINDOW_0 block
    m0 = re.search(r"\[WINDOW_0\](.*?)(\[WINDOW_1\]|\Z)", text, re.DOTALL)
    assert m0, "WINDOW_0 block not found"
    body0 = m0.group(1)
    assert "FIXED_SIZE" in body0, "WINDOW_0 must have FIXED_SIZE flag"
    assert re.search(r"PADDING\s*=\s*0\s*,\s*0", body0), "WINDOW_0 must have PADDING=0,0"
    assert re.search(r"NO_BACKGROUND", body0), "WINDOW_0 must keep NO_BACKGROUND"

    m1 = re.search(r"\[WINDOW_1\](.*?)(\[WINDOW_2\]|\Z)", text, re.DOTALL)
    assert m1, "WINDOW_1 block not found"
    body1 = m1.group(1)
    assert "FIXED_SIZE" in body1, "WINDOW_1 must have FIXED_SIZE flag"
    assert re.search(r"PADDING\s*=\s*0\s*,\s*0", body1), "WINDOW_1 must have PADDING=0,0"

    # WINDOW_1 must be at least 560 wide so the bottom tile fits the Figma layout
    size_match = re.search(r"SIZE\s*=\s*(\d+)\s*,\s*(\d+)", body1)
    assert size_match, "WINDOW_1 must have SIZE"
    w, h = int(size_match.group(1)), int(size_match.group(2))
    assert w >= 560, f"WINDOW_1 width must be >= 560, got {w}"
    assert h >= 200, f"WINDOW_1 height must be >= 200, got {h}"


# ---------------------------------------------------------------------------
# ETE-06: Font bundling contract
# ---------------------------------------------------------------------------


def test_ete06_fonts_bundled_in_repo():
    """ETE-06: 4 .ttf files + OFL.txt are committed; each .ttf has a valid
    TrueType signature and is at least 50 kB."""
    expected = [
        "Michroma-Regular.ttf",
        "Montserrat-Regular.ttf",
        "Montserrat-Bold.ttf",
        "Syncopate-Bold.ttf",
    ]
    for name in expected:
        f = FONTS_DIR / name
        assert f.exists(), f"{f} not bundled"
        size = f.stat().st_size
        assert size >= 50_000, f"{name} too small ({size} bytes), likely an LFS pointer or 404"
        with f.open("rb") as fh:
            head = fh.read(4)
        # TrueType v1.0 signature is 00 01 00 00; OpenType is 'OTTO'
        assert head in (b"\x00\x01\x00\x00", b"OTTO"), (
            f"{name} has invalid TTF/OTF header: {head.hex()}"
        )

    license_file = FONTS_DIR / "OFL.txt"
    assert license_file.exists(), "OFL.txt license file missing"
    license_text = license_file.read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in license_text.upper()


def test_ete06b_bloom_asset_bundled():
    """ETE-06b: bloom.png asset is committed (used for kind=brake glow effect)."""
    bloom = ASSETS_DIR / "bloom.png"
    assert bloom.exists(), f"{bloom} must be bundled"
    assert bloom.stat().st_size >= 100, "bloom.png too small"
    # PNG signature
    with bloom.open("rb") as fh:
        head = fh.read(8)
    assert head == b"\x89PNG\r\n\x1a\n", f"bloom.png has invalid PNG header: {head.hex()}"


# ---------------------------------------------------------------------------
# ETE-07: autoPlaceOnce persists ac.storage flag and runs exactly once
# ---------------------------------------------------------------------------


def test_ete07_auto_place_once_runs_once_then_skips(lua) -> None:
    """ETE-07: autoPlaceOnce applies manifest geometry once per load, then gates
    repeats via ``state._autoPlaceChecked`` (issue #75: imgui.ini could not be
    cleared with an ac.storage flag alone).

    This test executes the function twice via the lupa stub and asserts:
      - first call moves at least one target window
      - second call performs zero further moves (idempotent)
    """
    entry_src = ENTRY.read_text(encoding="utf-8")
    # The entry script must define an autoPlaceOnce-style function
    assert re.search(
        r"function\s+\w*[Aa]utoPlace\w*\s*\(",
        entry_src,
    ), "entry script must define an autoPlaceOnce-style function"

    assert re.search(
        r"_autoPlaceChecked",
        entry_src,
    ), "autoPlaceOnce must gate via state._autoPlaceChecked after successful placement"

    # Extract the autoPlaceOnce function body and execute it standalone
    m = re.search(
        r"local function autoPlaceOnce\(\).*?^end$",
        entry_src,
        re.MULTILINE | re.DOTALL,
    )
    assert m, "autoPlaceOnce function body not found"
    func_src = m.group(0)
    # Strip `local` so the function becomes a global we can call
    func_src_global = func_src.replace(
        "local function autoPlaceOnce()", "function autoPlaceOnce()", 1
    )

    # Reset stub state and inject the function
    lua.execute("state = {}")
    lua.execute("_move_calls = {}")
    lua.execute("_resize_calls = {}")
    lua.execute("_storage_state = {}")
    lua.execute(func_src_global)

    # First call: should move at least one target window (resize may run too
    # — issue #75 forces resize+move so imgui-persisted geometry cannot win).
    lua.execute("autoPlaceOnce()")
    move_calls_1 = lua.execute("return #_move_calls")
    resize_calls_1 = lua.execute("return #_resize_calls")
    assert move_calls_1 >= 1, (
        f"first autoPlaceOnce call must move at least one window, got {move_calls_1}"
    )
    assert resize_calls_1 >= 1, (
        "first autoPlaceOnce call should resize tracked windows to manifest sizes, "
        f"got {resize_calls_1} resize calls"
    )

    # Second call: storage flag persisted, must be a no-op
    lua.execute("autoPlaceOnce()")
    move_calls_2 = lua.execute("return #_move_calls")
    assert move_calls_2 == move_calls_1, (
        "second autoPlaceOnce call must NOT re-move windows, got "
        f"{move_calls_2 - move_calls_1} extra moves"
    )


# ---------------------------------------------------------------------------
# ETE-08: hud.lua uses ui.dwriteDrawText / pushDWriteFont, not ui.text
# ---------------------------------------------------------------------------


def test_ete08_hud_uses_absolute_positioned_drawing() -> None:
    """ETE-08: hud.lua renders the panel via dwriteDrawText + drawRectFilled
    (gearbox-style absolute positioning), NOT via ui.text/ui.textColored."""
    src = MODULES.joinpath("hud.lua").read_text(encoding="utf-8")
    # Must use dwriteDrawText for the title and corner label
    assert "dwriteDrawText" in src or "dwriteText" in src, (
        "hud.lua must use ui.dwriteDrawText for the active suggestion text"
    )
    # Must use drawRectFilled for the panel chrome
    assert "drawRectFilled" in src, "hud.lua must use drawRectFilled for panel background"
    # Must push named DWrite fonts via the coaching_font wrapper (which calls
    # ui.pushDWriteFont internally with the bundled-font references)
    assert "pushNamed" in src or "pushDWriteFont" in src, (
        "hud.lua must push a DWrite font (via fontMod.pushNamed or ui.pushDWriteFont)"
    )


def test_ete08b_coaching_font_uses_inline_path_syntax():
    """ETE-08b: coaching_font.lua constructs ui.DWriteFont with the
    inline-path syntax `Family:/content/fonts;Weight=...` that the gearbox
    reference uses."""
    src = MODULES.joinpath("coaching_font.lua").read_text(encoding="utf-8")
    assert "ui.DWriteFont" in src, "coaching_font.lua must call ui.DWriteFont"
    # Must reference the bundled fonts directory inline
    assert re.search(
        r'"[\w ]+:/content/fonts',
        src,
    ), "coaching_font.lua must use inline path 'Family:/content/fonts;...'"
    # Must reference at least Michroma + Montserrat + Syncopate
    for family in ("Michroma", "Montserrat", "Syncopate"):
        assert family in src, f"coaching_font.lua must reference {family} family"


def test_ete08c_coaching_overlay_bottom_tile_always_renders(lua):
    """ETE-08c: drawApproachPanel ALWAYS renders chrome + footer, even when
    approachData is nil. Today it returns false and renders nothing."""
    overlay = lua.execute('local m = require("coaching_overlay"); return m')
    lua.execute("_reset_recorders()")
    # nil approach data — should still render chrome + AG PORSCHE ACADEMY footer
    overlay["drawApproachPanel"](None)
    rects = lua.execute("return #_draw_rect_filled_calls")
    assert rects >= 1, "drawApproachPanel(nil) must still render panel chrome"
    assert lua.execute('return _count_dwrite_text("AG PORSCHE ACADEMY")') >= 1, (
        "drawApproachPanel(nil) must render 'AG PORSCHE ACADEMY' footer"
    )


# ---------------------------------------------------------------------------
# ETE: realtime_coaching does NOT depend on lap-aggregate features
# ---------------------------------------------------------------------------


def test_ete_realtime_does_not_use_last_lap_corner_feats():
    """The new realtime_coaching engine MUST NOT reference lastLapCornerFeats
    or bestCornerFeatures. It works from live-frame inputs only."""
    src = MODULES.joinpath("realtime_coaching.lua").read_text(encoding="utf-8")
    assert "lastLapCornerFeats" not in src, (
        "realtime_coaching.lua must not reference lastLapCornerFeats (lap-aggregate dead path)"
    )
    assert "bestCornerFeatures" not in src, (
        "realtime_coaching.lua must not reference bestCornerFeatures (lap-aggregate dead path)"
    )
    assert "buildRealTime" not in src, (
        "realtime_coaching.lua must not call coaching_hints.buildRealTime"
    )


def test_ete_build_realtime_deleted():
    """coaching_hints.buildRealTime must be deleted (proves we removed the dead path)."""
    src = MODULES.joinpath("coaching_hints.lua").read_text(encoding="utf-8")
    assert "function M.buildRealTime" not in src, (
        "M.buildRealTime must be deleted from coaching_hints.lua"
    )
