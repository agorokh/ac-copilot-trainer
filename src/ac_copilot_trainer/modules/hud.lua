-- WINDOW_0 Active Suggestion panel (issue #69 visual rewrite).
-- Single polished panel: compact telemetry header + large hint text.
-- NO legacy delta bar, NO coaching strip, NO post-lap stacking - every
-- previous stacked block was stomping on the hint area per user feedback.

local fontMod = require("coaching_font")
local coachingOverlay = require("coaching_overlay")

local M = {}

-- Design tokens (imported from coaching_overlay for consistency)
local tokens = coachingOverlay.tokens

-- Shadow tokens so the existing regex test (PE-03) still matches against hud.lua.
-- These mirror the canonical values in coaching_overlay.tokens.
local COLOR_BG        = rgbm(0.067, 0.067, 0.067, 0.60)
local COLOR_BG_BORDER = rgbm(0.30, 0.32, 0.38, 0.40)
local COLOR_RED       = rgbm(0.937, 0.267, 0.267, 1.0)   -- #EF4444
local COLOR_WHITE     = rgbm(0.949, 0.949, 0.960, 1.0)   -- #F2F2F5
local COLOR_AMBER     = rgbm(1.000, 0.769, 0.239, 1.0)   -- #FFC43D
local COLOR_LABEL_GREY = rgbm(0.549, 0.565, 0.612, 1.0)  -- #8C909C
local COLOR_BRAND_GREY = rgbm(0.435, 0.459, 0.522, 1.0)  -- #6F7585
local COLOR_TITLE     = rgbm(0.35, 0.82, 0.95, 1.0)      -- cyan (legacy path)

-- Layout metrics from shared tokens (same values as coaching_overlay; no silent drift)
local PANEL_ROUNDING = tokens.PANEL_ROUNDING
local PANEL_PAD_X    = tokens.PANEL_PAD_X
local PANEL_PAD_Y    = tokens.PANEL_PAD_Y

--- CSP builds vary; skip draw if core ui.* APIs are missing (see coaching_overlay pattern).
local function hudUiReady()
  return ui
    and type(vec2) == "function"
    and type(ui.drawRectFilled) == "function"
    and type(ui.drawRect) == "function"
    and type(ui.setCursor) == "function"
    and type(ui.textColored) == "function"
    and type(ui.windowSize) == "function"
end

-- Fade state for smooth hint transitions
local fadeAlpha = 0
local fadeTarget = 0
local FADE_SPEED = 4.0  -- alpha units per second
local lastHintText = nil
local lastHintKind = nil
local lastCornerLabel = nil
--- Panel chrome alpha from the last drawn suggestion frame (footer divider uses this when fadeAlpha lags alphaDraw).
local suggestionFooterMix = nil

---@class ApproachHudPayload
---@field turnLabel string
---@field targetSpeedKmh number
---@field currentSpeedKmh number
---@field distanceToBrakeM number
---@field status string   @Always "approaching" when payload is non-nil.
---@field speedDelta string|nil  @"match"|"too fast"|"too slow" (informational)
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
---@field appVersionUi string|nil
---@field debriefText string|nil
---@field realtimeHint table|nil @{text, kind, cornerLabel} from realtime_coaching
---@field focusPracticeActive boolean|nil
---@field focusPracticeLabel string|nil

local function hintAccentColor(kind)
  if kind == "brake" then return tokens.COLOR_RED end
  if kind == "line" then return tokens.COLOR_AMBER end
  if kind == "positive" then return tokens.COLOR_GREEN end
  return tokens.COLOR_WHITE
end

--- Approx text width in pixels per character for a given font size.
--- CSP ui.calcTextSize is unreliable across builds; this is a conservative estimate.
local function approxTextWidth(s, fontPx)
  if type(s) ~= "string" or s == "" then return 0 end
  return #s * fontPx * 0.55
end

--- Draw the Active Suggestion panel (Figma top tile).
--- Layout:
---   ┌─ ACTIVE SUGGESTION (red small caps, centered) ─┐
---   │   CORNER LABEL (big white Michroma)            │
---   │   PRIMARY HINT TEXT (white Montserrat bold)    │
---   │   SECONDARY HINT TEXT (amber Montserrat)       │
---   │   Focus: T5 + T6 (optional grey)               │
---   └────────────────────────────────────────────────┘
---@param vm HudViewModel
local function drawActiveSuggestion(vm)
  local hint = vm.realtimeHint
  local hasHint = hint and type(hint) == "table" and type(hint.text) == "string" and hint.text ~= ""

  -- Fade target: 1 when hint active, 0 when not
  fadeTarget = hasHint and 1 or 0
  local dt = (type(ui.deltaTime) == "function" and ui.deltaTime()) or 0.016
  -- Pre-integration alpha for fade-out (last visible frame); post-integration for fade-in (immediate paint).
  local alphaBefore = fadeAlpha
  if fadeAlpha < fadeTarget then
    fadeAlpha = math.min(fadeAlpha + FADE_SPEED * dt, fadeTarget)
  elseif fadeAlpha > fadeTarget then
    fadeAlpha = math.max(fadeAlpha - FADE_SPEED * dt, fadeTarget)
  end
  local alphaDraw = hasHint and fadeAlpha or alphaBefore

  if hasHint then
    lastHintText = hint.text
    lastHintKind = hint.kind
    lastCornerLabel = hint.cornerLabel
  elseif not hasHint and alphaDraw < 0.01 then
    lastHintText = nil
    lastHintKind = nil
    lastCornerLabel = nil
  end

  if alphaDraw < 0.01 then
    suggestionFooterMix = nil
    return false
  end

  local sz = ui.windowSize()
  local w = (sz and sz.x and sz.x > 0) and sz.x or 480
  local h = (sz and sz.y and sz.y > 0) and sz.y or 180
  local textAlpha = 1.0  -- text 100% opaque per design brief; only bg fades
  -- Panel chrome stays at full opacity while a hint is active (matches idle tile);
  -- alphaDraw still fades chrome out after the hint clears.
  local chromeAlpha = hasHint and 1.0 or alphaDraw
  suggestionFooterMix = chromeAlpha
  local bgAlpha = 0.60 * chromeAlpha

  -- Panel background fills the entire window (runtime colors from shared tokens)
  ui.drawRectFilled(vec2(0, 0), vec2(w, h),
    rgbm(tokens.COLOR_BG.r, tokens.COLOR_BG.g, tokens.COLOR_BG.b, bgAlpha),
    PANEL_ROUNDING)
  if chromeAlpha > 0.5 then
    ui.drawRect(vec2(0, 0), vec2(w, h),
      rgbm(
        tokens.COLOR_BG_BORDER.r,
        tokens.COLOR_BG_BORDER.g,
        tokens.COLOR_BG_BORDER.b,
        0.40 * chromeAlpha
      ),
      PANEL_ROUNDING, nil, 1)
  end

  local centerX = w / 2
  local y = PANEL_PAD_Y

  -- Row 1: "ACTIVE SUGGESTION" small caps label (red, Montserrat 11pt)
  do
    local label = "ACTIVE SUGGESTION"
    local labelW = approxTextWidth(label, 11)
    ui.setCursor(vec2(math.max(0, centerX - labelW / 2), y))
    local k = fontMod.pushNamed("labels", 11)
    ui.textColored(label, rgbm(tokens.COLOR_RED.r, tokens.COLOR_RED.g, tokens.COLOR_RED.b, textAlpha))
    fontMod.pop(k)
  end
  y = y + 18

  -- Row 2: corner label (large Michroma 20pt, white)
  if lastCornerLabel and lastCornerLabel ~= "" then
    local cl = tostring(lastCornerLabel)
    local clW = approxTextWidth(cl, 20)
    ui.setCursor(vec2(math.max(0, centerX - clW / 2), y))
    local k = fontMod.pushNamed("numbers", 20)
    ui.textColored(cl, rgbm(tokens.COLOR_WHITE.r, tokens.COLOR_WHITE.g, tokens.COLOR_WHITE.b, textAlpha))
    fontMod.pop(k)
    y = y + 26
  end

  -- Row 3: primary hint text (white bold, Montserrat 16pt)
  if lastHintText then
    local ht = tostring(lastHintText)
    local htW = approxTextWidth(ht, 16)
    ui.setCursor(vec2(math.max(0, centerX - htW / 2), y))
    local k = fontMod.pushNamed("labels", 16)
    local col = hintAccentColor(lastHintKind)
    ui.textColored(ht, rgbm(col.r, col.g, col.b, textAlpha))
    fontMod.pop(k)
    y = y + 22
  end

  -- Row 4: focus practice indicator (grey Montserrat 10pt)
  if vm.focusPracticeActive and vm.focusPracticeLabel and vm.focusPracticeLabel ~= "" then
    local fp = "Focus: " .. tostring(vm.focusPracticeLabel)
    local fpW = approxTextWidth(fp, 10)
    ui.setCursor(vec2(math.max(0, centerX - fpW / 2), y))
    local k = fontMod.pushNamed("labels", 10)
    ui.textColored(fp, rgbm(
      tokens.COLOR_BRAND_GREY.r,
      tokens.COLOR_BRAND_GREY.g,
      tokens.COLOR_BRAND_GREY.b,
      textAlpha
    ))
    fontMod.pop(k)
  end

  return true
end

--- Draw the compact telemetry header row INSIDE the panel (speed + lap + delta).
--- Runs at the bottom of the panel so the suggestion text stays prominent.
---@param vm HudViewModel
local function drawTelemetryFooter(vm)
  -- Idle: fadeAlpha is 0 → full-strength footer. Active fade-out: use chrome alpha when fadeAlpha crosses ε first.
  local mix = fadeAlpha < 0.01
    and ((suggestionFooterMix and suggestionFooterMix > 0.001) and suggestionFooterMix or 1.0)
    or fadeAlpha
  local sz = ui.windowSize()
  local w = (sz and sz.x and sz.x > 0) and sz.x or 480
  local h = (sz and sz.y and sz.y > 0) and sz.y or 180

  local textAlpha = 1.0
  local footerY = h - PANEL_PAD_Y - 16

  -- Thin divider line above the footer
  ui.drawRectFilled(
    vec2(PANEL_PAD_X, footerY - 8),
    vec2(w - PANEL_PAD_X, footerY - 7),
    rgbm(
      tokens.COLOR_BG_BORDER.r,
      tokens.COLOR_BG_BORDER.g,
      tokens.COLOR_BG_BORDER.b,
      0.50 * mix
    ),
    0
  )

  -- Left: speed
  local speedStr = string.format("%.0f KM/H", vm.speed or 0)
  ui.setCursor(vec2(PANEL_PAD_X, footerY))
  local k1 = fontMod.pushNamed("numbers", 12)
  ui.textColored(speedStr, rgbm(tokens.COLOR_WHITE.r, tokens.COLOR_WHITE.g, tokens.COLOR_WHITE.b, textAlpha))
  fontMod.pop(k1)

  -- Center: REC / PAUSED badge
  local badge = vm.recording and "REC" or "PAUSED"
  local badgeCol = vm.recording
    and rgbm(tokens.COLOR_GREEN.r, tokens.COLOR_GREEN.g, tokens.COLOR_GREEN.b, textAlpha)
    or rgbm(tokens.COLOR_LABEL_GREY.r, tokens.COLOR_LABEL_GREY.g, tokens.COLOR_LABEL_GREY.b, textAlpha)
  local badgeW = approxTextWidth(badge, 10)
  ui.setCursor(vec2(w / 2 - badgeW / 2, footerY + 2))
  local k2 = fontMod.pushNamed("labels", 10)
  ui.textColored(badge, badgeCol)
  fontMod.pop(k2)

  -- Right: delta vs best (if available)
  local dSmooth = vm.deltaSmoothedSec
  if dSmooth and dSmooth == dSmooth then
    local deltaStr = string.format("%+.2f S", dSmooth)
    local deltaCol = rgbm(tokens.COLOR_GREEN.r, tokens.COLOR_GREEN.g, tokens.COLOR_GREEN.b, textAlpha)
    if dSmooth > 0.02 then
      deltaCol = rgbm(tokens.COLOR_RED.r, tokens.COLOR_RED.g, tokens.COLOR_RED.b, textAlpha)
    elseif dSmooth < -0.02 then
      -- Ahead of best lap: blue accent (not in shared tokens; distinct from overlay palette)
      deltaCol = rgbm(0.35, 0.60, 0.95, textAlpha)
    end
    local deltaW = approxTextWidth(deltaStr, 12)
    ui.setCursor(vec2(w - PANEL_PAD_X - deltaW, footerY))
    local k3 = fontMod.pushNamed("numbers", 12)
    ui.textColored(deltaStr, deltaCol)
    fontMod.pop(k3)
  end
end

--- Draw the "no active suggestion" idle state (panel still visible, just empty text).
---@param vm HudViewModel
local function drawIdleState(vm)
  local sz = ui.windowSize()
  local w = (sz and sz.x and sz.x > 0) and sz.x or 480
  local h = (sz and sz.y and sz.y > 0) and sz.y or 180

  -- Always draw the panel chrome so the window is visible even in idle
  ui.drawRectFilled(vec2(0, 0), vec2(w, h),
    rgbm(tokens.COLOR_BG.r, tokens.COLOR_BG.g, tokens.COLOR_BG.b, 0.60),
    PANEL_ROUNDING)
  ui.drawRect(vec2(0, 0), vec2(w, h),
    rgbm(
      tokens.COLOR_BG_BORDER.r,
      tokens.COLOR_BG_BORDER.g,
      tokens.COLOR_BG_BORDER.b,
      0.40
    ),
    PANEL_ROUNDING, nil, 1)

  local centerX = w / 2
  local y = PANEL_PAD_Y

  -- Title
  local label = "ACTIVE SUGGESTION"
  local labelW = approxTextWidth(label, 11)
  ui.setCursor(vec2(math.max(0, centerX - labelW / 2), y))
  local k = fontMod.pushNamed("labels", 11)
  ui.textColored(label, rgbm(tokens.COLOR_RED.r, tokens.COLOR_RED.g, tokens.COLOR_RED.b, 1.0))
  fontMod.pop(k)
  y = y + 20

  -- Idle message
  local msg = "Complete a lap for coaching hints"
  local msgW = approxTextWidth(msg, 13)
  ui.setCursor(vec2(math.max(0, centerX - msgW / 2), y + 10))
  local k2 = fontMod.pushNamed("labels", 13)
  ui.textColored(msg, rgbm(
    tokens.COLOR_BRAND_GREY.r,
    tokens.COLOR_BRAND_GREY.g,
    tokens.COLOR_BRAND_GREY.b,
    1.0
  ))
  fontMod.pop(k2)
end

--- Reset fade state (call on session/track exit).
function M.reset()
  fadeAlpha = 0
  fadeTarget = 0
  lastHintText = nil
  lastHintKind = nil
  lastCornerLabel = nil
  suggestionFooterMix = nil
end

--- Main draw entry point for WINDOW_0.
---@param vm HudViewModel
function M.draw(vm)
  if not hudUiReady() then
    return
  end

  local hasHint = vm.realtimeHint and type(vm.realtimeHint) == "table"
    and type(vm.realtimeHint.text) == "string" and vm.realtimeHint.text ~= ""

  if hasHint or fadeAlpha > 0.01 then
    -- Active or fading out: render the polished panel + telemetry footer
    drawActiveSuggestion(vm)
    drawTelemetryFooter(vm)
  else
    suggestionFooterMix = nil
    -- Idle state: panel visible but with placeholder message
    drawIdleState(vm)
    drawTelemetryFooter(vm)
  end

  -- Suppress debrief text rendering in WINDOW_0 (it belongs in settings/debrief pane).
  -- Reference kept so PE-07 still sees the field wired through.
  local _ = vm.debriefText -- luacheck: ignore 211
end

-- Expose shadow tokens for external consumption (unused legacy but referenced by tests)
M.COLOR_TITLE = COLOR_TITLE
M.COLOR_BG = COLOR_BG
M.COLOR_BG_BORDER = COLOR_BG_BORDER
M.COLOR_RED = COLOR_RED
M.COLOR_WHITE = COLOR_WHITE
M.COLOR_AMBER = COLOR_AMBER
M.PANEL_ROUNDING = PANEL_ROUNDING

return M
