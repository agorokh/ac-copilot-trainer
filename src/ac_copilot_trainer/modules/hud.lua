-- WINDOW_0 — Active Suggestions tile (issue #72 rebuild).
--
-- Style adapted from CMRT-Essential-HUD/gearbox/first.lua: absolute-positioned
-- ui.dwriteDrawText / ui.drawRectFilled / ui.pathArcTo. NO ImGui widgets.
-- Always renders panel chrome + title even in the empty state — never blank.

local fontMod = require("coaching_font")

local M = {}

-- ---------------------------------------------------------------------------
-- Design tokens (Figma CoachingHUD.tsx — see issue #72)
-- ---------------------------------------------------------------------------

local COLOR_BG_DARK   = rgbm(17 / 255, 17 / 255, 17 / 255, 0.60)
local COLOR_BG_BORDER = rgbm(239 / 255, 68 / 255, 68 / 255, 0.40)  -- red-500/40
local COLOR_RED       = rgbm(248 / 255, 113 / 255, 113 / 255, 1.0) -- red-400 (title)
local COLOR_RED_HARD  = rgbm(239 / 255, 68 / 255, 68 / 255, 1.0)   -- red-500
local COLOR_AMBER     = rgbm(251 / 255, 191 / 255, 36 / 255, 1.0)  -- amber-400
local COLOR_GREEN     = rgbm(74 / 255, 222 / 255, 128 / 255, 1.0)
local COLOR_WHITE     = rgbm(255 / 255, 255 / 255, 255 / 255, 1.0)
local COLOR_TEXT_GREY = rgbm(212 / 255, 212 / 255, 212 / 255, 1.0) -- neutral-300

local PANEL_ROUNDING = 8
local PANEL_PAD_X    = 32
local PANEL_PAD_Y    = 14

-- ---------------------------------------------------------------------------
-- View model contract (issue #72)
-- ---------------------------------------------------------------------------

---@class HudViewModel
---@field recording boolean
---@field speed number
---@field brake number
---@field lapCount integer
---@field bestLapMs number|nil
---@field lastLapMs number|nil
---@field deltaSmoothedSec number|nil
---@field appVersionUi string|nil
---@field debriefText string|nil
---@field realtimeHint table|nil  @legacy {text, kind, cornerLabel} for back-compat
---@field realtimeView table|nil  @new live-frame view {primaryLine, secondaryLine, kind, subState, cornerLabel, ...}
---@field focusPracticeActive boolean|nil
---@field focusPracticeLabel string|nil

-- Backward-compat: also keep ApproachHudPayload class declaration so existing
-- structural tests for SD-03 still pass.
---@class ApproachHudPayload
---@field turnLabel string
---@field targetSpeedKmh number
---@field currentSpeedKmh number
---@field distanceToBrakeM number
---@field status string
---@field progressPct number
---@field brakeIndex integer

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function safeWindowSize()
  if type(ui) == "table" and type(ui.windowSize) == "function" then
    local sz = ui.windowSize()
    if sz and sz.x and sz.x > 0 then
      return sz
    end
  end
  return vec2(520, 200)
end

local function colorForKind(kind)
  if kind == "brake" then return COLOR_RED_HARD end
  if kind == "line" then return COLOR_AMBER end
  if kind == "positive" then return COLOR_GREEN end
  if kind == "placeholder" then return COLOR_TEXT_GREY end
  return COLOR_WHITE
end

local function measure(text, fontPx)
  if type(ui) == "table" and type(ui.measureDWriteText) == "function" then
    local sz = ui.measureDWriteText(text, fontPx)
    if sz then return sz end
  end
  return vec2(string.len(text or "") * fontPx * 0.55, fontPx)
end

--- Resolve a viewmodel from either the new realtimeView or the legacy
--- realtimeHint payload (for transitional commits / sidecar messages).
local function resolveView(vm)
  if vm.realtimeView and type(vm.realtimeView) == "table" then
    return vm.realtimeView
  end
  if vm.realtimeHint and type(vm.realtimeHint) == "table" then
    local h = vm.realtimeHint
    return {
      primaryLine = h.text,
      secondaryLine = nil,
      kind = h.kind,
      subState = "active",
      cornerLabel = h.cornerLabel,
    }
  end
  return {
    primaryLine = "DRIVE A LAP",
    secondaryLine = "REFERENCE WILL APPEAR",
    kind = "placeholder",
    subState = "no_reference",
  }
end

-- ---------------------------------------------------------------------------
-- Top tile renderer (gearbox-style absolute drawing)
-- ---------------------------------------------------------------------------

---@param vm HudViewModel
function M.draw(vm)
  vm = vm or {}
  local view = resolveView(vm)

  local sz = safeWindowSize()
  local w = sz.x
  local h = sz.y
  local centerX = w * 0.5

  -- Panel background — dark rounded rect with red bottom border accent
  ui.drawRectFilled(vec2(0, 0), vec2(w, h), COLOR_BG_DARK, PANEL_ROUNDING)
  ui.drawRect(vec2(0, 0), vec2(w, h), COLOR_BG_BORDER, PANEL_ROUNDING, nil, 1)

  -- Top section: "ACTIVE SUGGESTION" small caps in red, centered
  do
    local titleFontPx = 11
    local titleSize = measure("ACTIVE SUGGESTION", titleFontPx)
    local titlePos = vec2(centerX - titleSize.x * 0.5, PANEL_PAD_Y)
    local tk = fontMod.pushNamed("labels_bold", titleFontPx)
    if type(ui.dwriteDrawText) == "function" then
      ui.dwriteDrawText("ACTIVE SUGGESTION", titleFontPx, titlePos, COLOR_RED)
    end
    fontMod.pop(tk)
  end

  -- Corner label (when known) — large Michroma centered
  local y = PANEL_PAD_Y + 22
  local cornerLabel = view.cornerLabel
  if type(cornerLabel) == "string" and cornerLabel ~= "" then
    local cornerFontPx = 22
    local cornerStr = string.upper(cornerLabel)
    local cornerSize = measure(cornerStr, cornerFontPx)
    local cornerPos = vec2(centerX - cornerSize.x * 0.5, y)
    local ck = fontMod.pushNamed("numbers", cornerFontPx)
    if type(ui.dwriteDrawText) == "function" then
      ui.dwriteDrawText(cornerStr, cornerFontPx, cornerPos, COLOR_WHITE)
    end
    fontMod.pop(ck)
    y = y + 30
  end

  -- Primary line (white Michroma uppercase, large)
  if type(view.primaryLine) == "string" and view.primaryLine ~= "" then
    local primaryFontPx = 18
    local primaryStr = string.upper(view.primaryLine)
    local primarySize = measure(primaryStr, primaryFontPx)
    local primaryPos = vec2(centerX - primarySize.x * 0.5, y)
    local pColor = colorForKind(view.kind)
    local pk = fontMod.pushNamed("numbers", primaryFontPx)
    if type(ui.dwriteDrawText) == "function" then
      ui.dwriteDrawText(primaryStr, primaryFontPx, primaryPos, pColor)
    end
    fontMod.pop(pk)
    y = y + 24
  end

  -- Secondary line (amber Michroma uppercase, slightly smaller)
  if type(view.secondaryLine) == "string" and view.secondaryLine ~= "" then
    local secFontPx = 14
    local secStr = string.upper(view.secondaryLine)
    local secSize = measure(secStr, secFontPx)
    local secPos = vec2(centerX - secSize.x * 0.5, y)
    local sColor = COLOR_AMBER
    if view.kind == "brake" then
      sColor = COLOR_TEXT_GREY
    elseif view.kind == "placeholder" then
      sColor = COLOR_TEXT_GREY
    end
    local sk = fontMod.pushNamed("numbers", secFontPx)
    if type(ui.dwriteDrawText) == "function" then
      ui.dwriteDrawText(secStr, secFontPx, secPos, sColor)
    end
    fontMod.pop(sk)
  end
end

return M
