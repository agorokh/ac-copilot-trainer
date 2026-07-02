"""Racing Atelier in-game card conformance (issue #432 Part A2).

Drives coaching_overlay.drawApproachPanel through a recording Lua stub with the
EXACT state the design render models (templates/ingame-hud/InGameHud.dc.html:
T4 / 196 km/h / BRAKE / 86 m / fill 0.66 zone 0.34 / entry delta +14 ref 182)
and asserts the card reproduces the template's algorithms:

- SegmentBar.jsx: filledCount = round(fill*12), zoneStart = 12 - round(zone*12),
  cell colors chalk / amber leading / red in-zone / zone tint / raise.
- DeltaBar.jsx: tone by slack=4, fill anchored at the trough center, signed
  "+14" readout.
- CommandVerb: one loud verb, tone-colored, from the realtime primary line.

The stub measures text deterministically (len * px * 0.55) so geometry
assertions are stable without DirectWrite.
"""

from __future__ import annotations

import pathlib

import pytest

lupa = pytest.importorskip("lupa", reason="lupa Lua runtime not installed (pip install lupa)")

REPO = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = REPO / "src" / "ac_copilot_trainer" / "modules"
FONTS_DIR = REPO / "src" / "ac_copilot_trainer" / "content" / "fonts"

CARD_W = 560.0
CARD_H = 480.0
PAD_X = 26.0

STUB_LUA = r"""
ui = {}
_rects = {}
_texts = {}

function ui.drawRectFilled(p0, p1, color, rounding)
    _rects[#_rects + 1] = {
        x0 = p0.x, y0 = p0.y, x1 = p1.x, y1 = p1.y,
        r = color.r, g = color.g, b = color.b, mult = color.mult,
        rounding = rounding or 0,
    }
end

function ui.drawRect() end

function ui.dwriteDrawText(text, px, pos, color)
    _texts[#_texts + 1] = {
        text = text, px = px, x = pos.x, y = pos.y,
        r = color.r, g = color.g, b = color.b, mult = color.mult,
    }
end

function ui.measureDWriteText(text, px)
    return _vec2(string.len(text or "") * px * 0.55, px)
end

function ui.windowSize() return _vec2(560, 480) end
function ui.DWriteFont(spec) return { spec = spec } end
function ui.pushDWriteFont() end
function ui.popDWriteFont() end
function ui.textColored() end

local _rgbm_meta = {}
function _rgbm_meta.__call(_, r, g, b, m)
    return { r = r or 0, g = g or 0, b = b or 0, mult = m or 1, _isRgbm = true }
end
rgbm = setmetatable({}, _rgbm_meta)

function _vec2(x, y) return { x = x or 0, y = y or 0 } end
vec2 = _vec2

ac = { log = function() end }
"""

# The state the render / template models (ui_kits/ingame_hud + InGameHud.dc.html)
# plus the main-dashboard vitals (gear/speed/rpm — operator-signed extension).
RENDER_PAYLOAD = """
{
  turnLabel        = "T4",
  targetSpeedKmh   = 182,
  currentSpeedKmh  = 196,
  distanceToBrakeM = 86,
  progressPct      = 0.66,
  zonePct          = 0.34,
  approachMeters   = 200,
  subState         = "braking",
  status           = "braking",
  gear             = 2,
  trackName        = "Magione",
  kind             = "brake",
  primaryLine      = "BRAKE NOW",
  rpm              = 7412,
  rpmLimiter       = 8400,
  shiftZonePct     = 0.92,
  redZonePct       = 0.97,
}
"""


def _hex(hexstr: str) -> tuple[float, float, float]:
    return tuple(int(hexstr[i : i + 2], 16) / 255.0 for i in (1, 3, 5))


CHALK = _hex("#EEF1F3")
BRAKE = _hex("#F23B2C")
LIFT = _hex("#F4A52C")
RAISE = _hex("#20242A")
BRASS = _hex("#C8983E")


def _is_color(rec, rgb, eps=0.004):
    return all(abs(rec[k] - v) < eps for k, v in zip(("r", "g", "b"), rgb, strict=True))


@pytest.fixture
def lua():
    rt = lupa.LuaRuntime(unpack_returned_tuples=False)
    rt.execute(STUB_LUA)
    modules_path = str(MODULES_DIR).replace("\\", "/")
    rt.execute(f'package.path = package.path .. ";{modules_path}/?.lua"')
    return rt


@pytest.fixture
def card(lua):
    """Render the design-state card once; return (rects, texts)."""
    drew = lua.execute(
        f'local ov = require("coaching_overlay");return ov.drawApproachPanel({RENDER_PAYLOAD})'
    )
    assert drew is True
    rects = list(lua.globals()["_rects"].values())
    texts = list(lua.globals()["_texts"].values())
    return rects, texts


def _segment_cells(rects):
    return [
        r
        for r in rects
        if abs((r["y1"] - r["y0"]) - 26.0) < 0.01 and 30.0 < (r["x1"] - r["x0"]) < 50.0
    ]


def test_segment_bar_matches_design_algorithm(card):
    """SegmentBar.jsx with fill=0.66, zone=0.34, count=12 -> 7 chalk + 1 amber
    leading + 4 translucent zone cells (the exact render state)."""
    rects, _ = card
    cells = _segment_cells(rects)
    assert len(cells) == 12, f"expected 12 segment cells, got {len(cells)}"
    cells.sort(key=lambda r: r["x0"])
    for i, cell in enumerate(cells[:7]):
        assert _is_color(cell, CHALK), f"cell {i} should be chalk (filled)"
    assert _is_color(cells[7], LIFT), "cell 7 should be the amber leading cell"
    for i, cell in enumerate(cells[8:], start=8):
        assert _is_color(cell, BRAKE), f"cell {i} should be the zone tint"
        assert abs(cell["mult"] - 0.16) < 0.01, f"cell {i} zone tint alpha 0.16"


def test_segment_bar_geometry(card):
    rects, _ = card
    cells = sorted(_segment_cells(rects), key=lambda r: r["x0"])
    content_w = CARD_W - 2 * PAD_X
    cell_w = (content_w - 3.0 * 11) / 12
    assert abs((cells[0]["x1"] - cells[0]["x0"]) - cell_w) < 0.01
    assert abs(cells[0]["x0"] - PAD_X) < 0.01
    assert abs(cells[-1]["x1"] - (CARD_W - PAD_X)) < 0.01


def test_command_verb_is_brake_red(card):
    _, texts = card
    verbs = [t for t in texts if t["text"] == "BRAKE" and t["px"] == 66]
    assert len(verbs) == 1, "exactly one 66px BRAKE CommandVerb"
    assert _is_color(verbs[0], BRAKE)


def test_brake_point_readout(card):
    _, texts = card
    label = [t for t in texts if t["text"] == "BRAKE POINT" and t["px"] == 11]
    num = [t for t in texts if t["text"] == "86" and t["px"] == 58]
    unit = [t for t in texts if t["text"] == "m" and t["px"] == 15]
    assert label and num and unit
    assert _is_color(num[0], CHALK)


def test_header_badge_and_name(card):
    rects, texts = card
    badge = [t for t in texts if t["text"] == "T4" and t["px"] == 14]
    name = [t for t in texts if t["text"] == "MAGIONE" and t["px"] == 22]
    assert badge and name
    badge_fields = [r for r in rects if _is_color(r, BRASS) and (r["y1"] - r["y0"]) == 20.0]
    assert badge_fields, "brass badge field behind T4"


def test_vitals_row_gear_speed_left_and_loud(card):
    """Main-dashboard hierarchy (operator sign-off): GEAR + KM/H are 62px
    Saira readouts anchored LEFT — louder than any context text."""
    _, texts = card
    for lbl in ("GEAR", "KM/H"):
        hits = [t for t in texts if t["text"] == lbl and t["px"] == 10]
        assert hits, f"vitals label {lbl} at 10px"
    gear = [t for t in texts if t["text"] == "2" and t["px"] == 62]
    speed = [t for t in texts if t["text"] == "196" and t["px"] == 62]
    assert gear and speed, "62px gear + speed readouts"
    assert abs(gear[0]["x"] - PAD_X) < 0.01, "GEAR value anchored at left pad"
    assert _is_color(speed[0], BRAKE), "196 over 182+8 renders brake-red"


def _rpm_cells(rects):
    return [
        r
        for r in rects
        if abs((r["y1"] - r["y0"]) - 18.0) < 0.01 and 15.0 < (r["x1"] - r["x0"]) < 30.0
    ]


def test_rpm_strip_zones(card):
    """20-cell RPM strip: rpm 7412 / limiter 8400 -> 18 filled chalk cells,
    standing amber shift zone from cell 18 (0.92), red band at cell 19 (0.97)."""
    rects, texts = card
    cells = sorted(_rpm_cells(rects), key=lambda r: r["x0"])
    assert len(cells) == 20, f"expected 20 rpm cells, got {len(cells)}"
    for i, cell in enumerate(cells[:18]):
        assert _is_color(cell, CHALK), f"rpm cell {i} filled chalk"
    assert _is_color(cells[18], LIFT) and abs(cells[18]["mult"] - 0.16) < 0.01, (
        "cell 18 = standing shift-zone tint"
    )
    assert _is_color(cells[19], BRAKE) and abs(cells[19]["mult"] - 0.16) < 0.01, (
        "cell 19 = standing redline tint"
    )
    assert [t for t in texts if t["text"] == "RPM · 7412" and t["px"] == 11]
    assert [t for t in texts if t["text"] == "SHIFT ZONE" and t["px"] == 11]


def test_rpm_strip_lights_solid_in_zone(lua):
    """When revs enter the zones the cells light solid (amber then red)."""
    lua.execute('_ov = require("coaching_overlay")')
    lua.execute(
        "_ov.drawApproachPanel({turnLabel='T1', targetSpeedKmh=100, "
        "currentSpeedKmh=100, distanceToBrakeM=500, approachMeters=200, "
        "progressPct=0, zonePct=0.25, subState='cruising', primaryLine='SHIFT UP', "
        "kind='line', rpm=8380, rpmLimiter=8400, shiftZonePct=0.92, redZonePct=0.97})"
    )
    rects = list(lua.globals()["_rects"].values())
    cells = sorted(_rpm_cells(rects), key=lambda r: r["x0"])
    assert len(cells) == 20
    assert _is_color(cells[18], LIFT) and cells[18]["mult"] > 0.9, "shift cell solid amber"
    assert _is_color(cells[19], BRAKE) and cells[19]["mult"] > 0.9, "redline cell solid red"
    texts = [t for t in lua.globals()["_texts"].values()]
    shift = [t for t in texts if t["text"] == "SHIFT" and t["px"] == 66]
    assert shift and _is_color(shift[0], LIFT), "SHIFT verb amber at 66px"


def test_delta_bar_matches_design_algorithm(card):
    """DeltaBar.jsx: v=+14 (196-182), slack 4 -> brake tone; fill from center,
    width = |v|/max * 50% of trough; big +14 readout."""
    rects, texts = card
    num = [t for t in texts if t["text"] == "+14" and t["px"] == 40]
    assert len(num) == 1
    assert _is_color(num[0], BRAKE)

    content_w = CARD_W - 2 * PAD_X
    trough_w = content_w - 14 - 84
    troughs = [
        r
        for r in rects
        if abs((r["y1"] - r["y0"]) - 24.0) < 0.01
        and abs((r["x1"] - r["x0"]) - trough_w) < 0.5
        and _is_color(r, RAISE)
    ]
    assert len(troughs) == 1, "one raise-toned delta trough"
    trough = troughs[0]
    center = trough["x0"] + trough_w * 0.5
    expect_fill_w = trough_w * (14.0 / 20.0) * 0.5
    fills = [
        r
        for r in rects
        if abs((r["y1"] - r["y0"]) - 24.0) < 0.01
        and _is_color(r, BRAKE)
        and abs(r["x0"] - center) < 0.5
        and abs((r["x1"] - r["x0"]) - expect_fill_w) < 0.5
    ]
    assert len(fills) == 1, "delta fill anchored at center with |v|/max*50% width"

    for lbl in ("ENTRY Δ · REF 182 KM/H", "TOO HOT — LIFT"):
        assert [t for t in texts if t["text"] == lbl and t["px"] == 12], lbl
    status = [t for t in texts if t["text"] == "TOO HOT — LIFT"][0]
    assert _is_color(status, BRAKE)


def test_delta_number_clamps_without_overshoot(lua):
    """Live-capture regression: v=-60 clamps to -20 and renders '-20' —
    floor(v - 0.5) rounding overshot the clamp to '-21' on the rig."""
    lua.execute('_ov = require("coaching_overlay")')
    lua.execute(
        "_ov.drawApproachPanel({turnLabel='T1', targetSpeedKmh=160, "
        "currentSpeedKmh=100, distanceToBrakeM=90, approachMeters=200, "
        "progressPct=0.5, zonePct=0.25, subState='approaching', "
        "primaryLine='APPROACHING', kind='info'})"
    )
    texts = [t["text"] for t in lua.globals()["_texts"].values()]
    assert "-20" in texts, f"clamped delta must render -20, texts={texts}"
    assert "-21" not in texts, "clamp overshoot regression"


def test_segment_captions(card):
    _, texts = card
    now = [t for t in texts if t["text"] == "NOW" and t["px"] == 11]
    zone = [t for t in texts if t["text"] == "BRAKE ZONE" and t["px"] == 11]
    assert now and zone
    assert _is_color(zone[0], BRAKE)


def test_brass_corner_brackets(card):
    """Four L-brackets = 8 brass 2px arms hugging the card corners."""
    rects, _ = card
    arms = [
        r
        for r in rects
        if _is_color(r, BRASS)
        and (
            (abs((r["y1"] - r["y0"]) - 2.0) < 0.01 and abs((r["x1"] - r["x0"]) - 14.0) < 0.01)
            or (abs((r["x1"] - r["x0"]) - 2.0) < 0.01 and abs((r["y1"] - r["y0"]) - 14.0) < 0.01)
        )
    ]
    assert len(arms) == 8, f"expected 8 bracket arms, got {len(arms)}"
    corners = {(0.0, 0.0), (CARD_W, 0.0), (0.0, CARD_H), (CARD_W, CARD_H)}
    touched = set()
    for r in arms:
        for cx, cy in corners:
            if (r["x0"] == cx or r["x1"] == cx) and (r["y0"] == cy or r["y1"] == cy):
                touched.add((cx, cy))
    assert touched == corners, "brackets must touch all four corners"


def test_placeholder_state_never_blank(lua):
    """ETE-08c contract at the new composition: nil payload still draws the
    full chrome with placeholders and returns true."""
    drew = lua.execute('local ov = require("coaching_overlay");return ov.drawApproachPanel(nil)')
    assert drew is True
    texts = [t["text"] for t in lua.globals()["_texts"].values()]
    assert "DRIVE" in texts, "placeholder CommandVerb"
    assert "WAITING" in texts, "placeholder delta status"
    assert "—" in texts, "em-dash placeholders present"
    rects = list(lua.globals()["_rects"].values())
    cells = _segment_cells(rects)
    assert len(cells) == 12, "segment bar renders in placeholder state"


def test_verb_vocabulary_preserved(lua):
    """Every realtime primary line maps to a distinct CommandVerb (substance
    preservation for #432: no engine state loses its visual)."""
    cases = {
        "BRAKE NOW": "BRAKE",
        "PREPARE TO BRAKE": "PREPARE",
        "EASE OFF": "LIFT",
        "CARRY MORE SPEED": "PUSH",
        "SHIFT UP": "SHIFT",
        "APPROACHING": "READY",
        "ON PACE": "ON PACE",
    }
    lua.execute('_ov = require("coaching_overlay")')
    for primary, verb in cases.items():
        lua.execute("_texts = {}; _rects = {}")
        lua.execute(
            "_ov.drawApproachPanel({turnLabel='T1', targetSpeedKmh=100, "
            "currentSpeedKmh=100, distanceToBrakeM=50, progressPct=0.5, "
            f"zonePct=0.25, subState='approaching', primaryLine='{primary}', kind='info'}})"
        )
        texts = [t["text"] for t in lua.globals()["_texts"].values()]
        assert verb in texts, f"{primary!r} must render verb {verb!r}"


def test_atelier_fonts_bundled():
    """The Racing Atelier faces ship with the app (single font source for the
    Lua HUD; same OFL families the firmware embeds)."""
    for name in (
        "SairaSemiCondensed-ExtraBold.ttf",
        "SairaSemiCondensed-Bold.ttf",
        "SairaSemiCondensed-SemiBold.ttf",
        "Saira-Bold.ttf",
        "SplineSansMono-Medium.ttf",
    ):
        assert (FONTS_DIR / name).is_file(), f"missing bundled font {name}"


def test_coaching_font_registers_atelier_roles():
    """The DWrite specs must use the TTFs' REAL family names — the bundled
    statics say 'Saira SemiCondensed' (no space; the spaced form is only the
    Google Fonts web name and FindFamilyName is exact) — and the numeric 800
    weight (ExtraBold is not a documented CSP weight token)."""
    src = (MODULES_DIR / "coaching_font.lua").read_text(encoding="utf-8")
    for spec in (
        "Saira SemiCondensed:/content/fonts;Weight=800",
        "Saira SemiCondensed:/content/fonts;Weight=Bold",
        "Saira SemiCondensed:/content/fonts;Weight=SemiBold",
        "Saira:/content/fonts;Weight=Bold",
        "Spline Sans Mono:/content/fonts;Weight=Medium",
    ):
        assert spec in src, f"coaching_font.lua must register {spec!r}"
    assert "Saira Semi Condensed:/content/fonts" not in src, (
        "spaced family name would miss DirectWrite's FindFamilyName"
    )


def test_bundled_font_family_names_match_specs():
    """Anti-drift lock: parse the bundled TTF name tables and assert the
    families the Lua registers actually exist in the files (would have caught
    both the spaced-family miss and the mislabeled Saira-Bold-that-was-Thin)."""
    fontTools = pytest.importorskip("fontTools.ttLib", reason="fontTools not installed")
    expectations = {
        "SairaSemiCondensed-ExtraBold.ttf": ("Saira SemiCondensed", 800),
        "SairaSemiCondensed-Bold.ttf": ("Saira SemiCondensed", 700),
        "SairaSemiCondensed-SemiBold.ttf": ("Saira SemiCondensed", 600),
        "Saira-Bold.ttf": ("Saira", 700),
        "SplineSansMono-Medium.ttf": ("Spline Sans Mono", 500),
    }
    for fname, (family, weight) in expectations.items():
        font = fontTools.TTFont(FONTS_DIR / fname)
        name = font["name"]
        got_family = name.getDebugName(16) or name.getDebugName(1)
        assert got_family == family, f"{fname}: family {got_family!r} != {family!r}"
        assert font["OS/2"].usWeightClass == weight, (
            f"{fname}: usWeightClass {font['OS/2'].usWeightClass} != {weight}"
        )


def test_delta_signal_tones_gated_by_approach_window(lua):
    """Outside the approach window the entry delta is reference data, not a
    command: no red TOO HOT — LIFT while the verb ladder says ON PACE."""
    lua.execute('_ov = require("coaching_overlay")')
    lua.execute(
        "_ov.drawApproachPanel({turnLabel='T1', targetSpeedKmh=120, "
        "currentSpeedKmh=250, distanceToBrakeM=500, approachMeters=200, "
        "progressPct=0, zonePct=0.25, subState='cruising', "
        "primaryLine='ON PACE', kind='positive'})"
    )
    texts = [t["text"] for t in lua.globals()["_texts"].values()]
    assert "TOO HOT — LIFT" not in texts, "imperative must not fire on a straight"
    assert "ABOVE REF" in texts, "neutral reference status expected outside the window"
