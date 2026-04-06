-- Active Suggestion window (WINDOW_0) — issue #57 Part E.
-- Clean coaching display replacing legacy debug dump.
-- Dark semi-transparent panel; text 100% opaque; hidden on straights.

local fontMod = require("coaching_font")
local coachingOverlay = require("coaching_overlay")

local M = {}

-- Design tokens (match coaching_overlay.lua for visual consistency)
local COLOR_BG        = rgbm(0.067, 0.067, 0.067, 0.60)
local COLOR_BG_BORDER = rgbm(0.30, 0.32, 0.38, 0.40)
local COLOR_TITLE     = rgbm(0.35, 0.82, 0.95, 1.0)  -- accent cyan
local COLOR_WHITE     = rgbm(0.95, 0.95, 0.97, 1.0)
local COLOR_BRAND     = rgbm(0.45, 0.48, 0.52, 1.0)
local COLOR_POSITIVE  = rgbm(0.20, 0.85, 0.35, 1.0)
local COLOR_BRAKE     = rgbm(0.95, 0.55, 0.20, 1.0)
local COLOR_LINE      = rgbm(0.85, 0.75, 0.30, 1.0)

local PANEL_ROUNDING = 12
local PANEL_PAD_X    = 20
local PANEL_PAD_Y    = 16

-- Fade state for smooth hint transitions
local fadeAlpha = 0
local fadeTarget = 0
local FADE_SPEED = 4.0  -- alpha units per second
local lastHintText = nil
local lastHintKind = nil
local lastCornerLabel = nil

--- Map hint kind to accent color.
---@param kind string|nil
---@return userdata rgbm
local function colorForKind(kind)
  if kind == "brake"    then return COLOR_BRAKE end
  if kind == "line"     then return COLOR_LINE end
  if kind == "positive" then return COLOR_POSITIVE end
  return COLOR_TITLE
end

---@class ApproachHudPayload
---@field turnLabel string @always set by `approachHudData` (`corner_names.resolveApproachLabel`)
---@field targetSpeedKmh number
---@field currentSpeedKmh number
---@field distanceToBrakeM number
---@field status string
---@field progressPct number
---@field brakeIndex integer

---@class HudViewModel
---@field recording boolean
---@field speed number
---@field brake number
---@field lapCount integer
---@field bestLapMs number|nil
---@field lastLapMs number|nil
---@field deltaSmoothedSec number|nil
---@field sectorMessage string|nil
---@field approachData ApproachHudPayload|nil @Producer `approachHudData`; fields match `ApproachHudPayload` (incl. brakeIndex).
---@field postLapLines string[]|nil
---@field coastWarn boolean|nil
---@field tireLockupFlash boolean|nil
---@field setupChangeMsg string|nil
---@field autoSetupLine string|nil
---@field coachingLines (string|{ kind: string, text: string })[]|nil
---@field coachingRemaining number|nil
---@field coachingHoldSeconds number|nil
---@field coachingMaxVisibleHints integer|nil
---@field coachingShowPrimer boolean|nil
---@field appVersionUi string|nil @e.g. "v0.4.2"
---@field debriefText string|nil @sidecar post-lap paragraph (issue #46)
---@field realtimeHint table|nil @{text, kind, cornerLabel} from realtime_coaching (issue #57 Part D)
---@field focusPracticeActive boolean|nil
---@field focusPracticeLabel string|nil

--- UTF-8 FULL BLOCK (U+2588) for delta bar segments.
local BLK = string.char(226, 150, 136)

local function formatLapMs(ms)
  if not ms or ms ~= ms or ms <= 0 then
    return "â"  -- em dash (U+2014)
  end
  return string.format("%.3f s", ms / 1000)
end

--- Graphical delta bar: center = neutral, left green = faster, right red = slower.
local function drawDeltaBar(d)
  local n = 28
  local center = (n + 1) / 2
  local mag = math.min(1, math.abs(d) / 0.12)
  local spread = math.floor(mag * (n / 2) + 0.5)
  for i = 1, n do
    if i > 1 then
      ui.sameLine(0, 0)
    end
    local c = rgbm(0.22, 0.22, 0.24, 1)
    if math.abs(i - center) < 0.51 then
      c = rgbm(0.92, 0.92, 0.95, 1)
    elseif d > 0.015 and i > center and i <= center + spread then
      c = rgbm(0.92, 0.22, 0.22, 1)
    elseif d < -0.015 and i < center and i >= center - spread then
      c = rgbm(0.2, 0.78, 0.3, 1)
    end
    ui.textColored(c, BLK)
  end
end

--- Draw the active suggestion panel (Part E design spec).
--- Shows real-time hint in a polished panel; hidden when no active coaching.
---@param vm HudViewModel
local function drawActiveSuggestion(vm)
  local hint = vm.realtimeHint
  local hasHint = hint and type(hint) == "table" and type(hint.text) == "string" and hint.text ~= ""

  -- Fade target: 1 when hint active, 0 when not
  fadeTarget = hasHint and 1 or 0
  local dt = ui.deltaTime() or 0.016
  if fadeAlpha < fadeTarget then
    fadeAlpha = math.min(fadeAlpha + FADE_SPEED * dt, fadeTarget)
  elseif fadeAlpha > fadeTarget then
    fadeAlpha = math.max(fadeAlpha - FADE_SPEED * dt, fadeTarget)
  end

  -- Track hint text and kind for smooth transitions
  if hasHint then
    lastHintText = hint.text
    lastHintKind = hint.kind
    lastCornerLabel = hint.cornerLabel
  end

  if fadeAlpha < 0.01 then
    lastHintText = nil
    lastHintKind = nil
    lastCornerLabel = nil
    return
  end

  ui.separator()

  local sz = ui.windowSize()
  local w = sz.x
  local cur = ui.getCursor()
  local curY = cur and cur.y or 0

  -- Panel background
  local panelH = 120
  local bgAlpha = 0.60 * fadeAlpha
  ui.drawRectFilled(vec2(0, curY), vec2(w, curY + panelH), rgbm(COLOR_BG.r, COLOR_BG.g, COLOR_BG.b, bgAlpha), PANEL_ROUNDING)
  if fadeAlpha > 0.5 then
    ui.drawRect(vec2(0, curY), vec2(w, curY + panelH), rgbm(COLOR_BG_BORDER.r, COLOR_BG_BORDER.g, COLOR_BG_BORDER.b, 0.40 * fadeAlpha), PANEL_ROUNDING, nil, 1)
  end

  local textAlpha = 1.0  -- text 100% opaque per design brief; only background fades
  local y = curY + PANEL_PAD_Y

  -- Title: "ACTIVE SUGGESTION"
  ui.setCursor(vec2(PANEL_PAD_X, y))
  local titleK = fontMod.pushNamed("labels", 14)
  ui.textColored(rgbm(COLOR_TITLE.r, COLOR_TITLE.g, COLOR_TITLE.b, textAlpha), "ACTIVE SUGGESTION")
  fontMod.pop(titleK)
  y = y + 22

  -- Corner label (preserved through fade-out)
  local cLabel = lastCornerLabel or (hasHint and hint.cornerLabel or nil)
  if cLabel and cLabel ~= "" then
    ui.setCursor(vec2(PANEL_PAD_X, y))
    local numK = fontMod.pushNamed("numbers", 22)
    ui.textColored(rgbm(COLOR_WHITE.r, COLOR_WHITE.g, COLOR_WHITE.b, textAlpha), cLabel)
    fontMod.pop(numK)
    y = y + 30
  end

  -- Main hint text (large)
  if lastHintText then
    ui.setCursor(vec2(PANEL_PAD_X, y))
    local hintK = fontMod.pushNamed("labels", 16)
    local hintColor = colorForKind(lastHintKind)
    ui.textColored(rgbm(hintColor.r, hintColor.g, hintColor.b, textAlpha), lastHintText)
    fontMod.pop(hintK)
    y = y + 24
  end

  -- Focus practice indicator
  if vm.focusPracticeActive and vm.focusPracticeLabel then
    ui.setCursor(vec2(PANEL_PAD_X, y))
    local brandK = fontMod.pushNamed("brand", 11)
    ui.textColored(rgbm(COLOR_BRAND.r, COLOR_BRAND.g, COLOR_BRAND.b, textAlpha), "Focus: " .. vm.focusPracticeLabel)
    fontMod.pop(brandK)
  end

  -- Advance cursor past panel so subsequent widgets render below
  ui.setCursor(vec2(0, curY + panelH))
end

--- Reset fade state (call on session/track exit).
function M.reset()
  fadeAlpha = 0
  fadeTarget = 0
  lastHintText = nil
  lastHintKind = nil
  lastCornerLabel = nil
end

--- Main draw entry point for WINDOW_0.
---@param vm HudViewModel
function M.draw(vm)
  -- Compact telemetry strip (always visible at top)
  ui.textColored(
    rgbm(0.5, 0.55, 0.62, 1),
    "AC Copilot Trainer " .. (type(vm.appVersionUi) == "string" and vm.appVersionUi ~= "" and vm.appVersionUi or "v?.?.?")
  )
  if vm.recording then
    ui.sameLine(0, 12)
    ui.textColored(rgbm(0, 1, 0, 1), "REC")
  else
    ui.sameLine(0, 12)
    ui.textColored(rgbm(0.65, 0.65, 0.65, 1), "PAUSED")
  end

  ui.separator()
  ui.text(string.format("%.0f km/h", vm.speed or 0))
  if (vm.brake or 0) > 0.05 then
    ui.text(string.format("Brake %.0f%%", (vm.brake or 0) * 100))
  end

  -- Delta vs best
  ui.textColored(rgbm(0.7, 0.72, 0.78, 1), "Delta vs best")
  local dSmooth = vm.deltaSmoothedSec
  if dSmooth == nil or dSmooth ~= dSmooth then
    ui.textColored(rgbm(0.55, 0.55, 0.58, 1), "No reference")
  else
    local d = dSmooth
    local col = rgbm(0.25, 0.9, 0.35, 1)
    if d > 0.02 then
      col = rgbm(0.92, 0.28, 0.25, 1)
    elseif d < -0.02 then
      col = rgbm(0.35, 0.6, 0.95, 1)
    end
    ui.textColored(col, string.format("%+.2f s", d))
    drawDeltaBar(d)
  end

  ui.text(string.format(
    "Lap %d   Best %s   Last %s",
    vm.lapCount or 0,
    formatLapMs(vm.bestLapMs),
    formatLapMs(vm.lastLapMs)
  ))

  -- Active suggestion panel (Part E)
  drawActiveSuggestion(vm)

  -- Coaching strip (post-lap coaching hints, issue #9 UX)
  coachingOverlay.drawMainWindowStrip(vm)
end

return M
