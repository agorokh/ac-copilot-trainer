-- Coaching overlay: panel + per-hint colors (issue #39 Part F); font + HUD strip (issue #41).
-- Approach telemetry panel: polished structured data display (issue #57 Part C).

local fontMod = require("coaching_font")

local M = {}

-- ---------------------------------------------------------------------------
-- Design tokens (Figma design brief, issue #57 Part C)
-- ---------------------------------------------------------------------------

local COLOR_BG           = rgbm(0.067, 0.067, 0.067, 0.60)   -- rgba(17,17,17,0.6)
local COLOR_BG_BORDER    = rgbm(0.30, 0.32, 0.38, 0.40)
local COLOR_LABEL        = rgbm(0.55, 0.58, 0.65, 1.0)       -- muted labels (legacy)
local COLOR_LABEL_GREY   = rgbm(0.549, 0.565, 0.612, 1.0)    -- #8C909C small caps labels
local COLOR_BRAND_GREY   = rgbm(0.435, 0.459, 0.522, 1.0)    -- #6F7585 footer branding
local COLOR_TITLE        = rgbm(0.35, 0.82, 0.95, 1.0)       -- accent cyan (legacy)
local COLOR_WHITE        = rgbm(0.949, 0.949, 0.960, 1.0)    -- #F2F2F5 primary text
local COLOR_GREEN        = rgbm(0.20, 0.85, 0.35, 1.0)       -- speed OK
local COLOR_RED          = rgbm(0.937, 0.267, 0.267, 1.0)    -- #EF4444 warning
local COLOR_AMBER        = rgbm(1.000, 0.769, 0.239, 1.0)    -- #FFC43D secondary hint
local COLOR_BAR_BG       = rgbm(0.15, 0.15, 0.18, 0.85)      -- progress bar background
local COLOR_BAR_FILL     = rgbm(0.937, 0.267, 0.267, 0.95)   -- #EF4444 red progress fill
local COLOR_BAR_GLOW     = rgbm(0.937, 0.267, 0.267, 0.35)   -- red glow
local COLOR_BRAND        = rgbm(0.45, 0.48, 0.52, 1.0)       -- legacy branding

local PANEL_ROUNDING = 12
local PANEL_PAD_X    = 24
local PANEL_PAD_Y    = 20

-- Shared token table consumed by hud.lua (single source of truth)
M.tokens = {
  COLOR_BG         = COLOR_BG,
  COLOR_BG_BORDER  = COLOR_BG_BORDER,
  COLOR_LABEL_GREY = COLOR_LABEL_GREY,
  COLOR_BRAND_GREY = COLOR_BRAND_GREY,
  COLOR_WHITE      = COLOR_WHITE,
  COLOR_RED        = COLOR_RED,
  COLOR_AMBER      = COLOR_AMBER,
  COLOR_GREEN      = COLOR_GREEN,
  PANEL_ROUNDING   = PANEL_ROUNDING,
  PANEL_PAD_X      = PANEL_PAD_X,
  PANEL_PAD_Y      = PANEL_PAD_Y,
}

-- ---------------------------------------------------------------------------
-- Speed color logic: green <= target, red > target+8, white in between
-- ---------------------------------------------------------------------------

---@param currentSpd number
---@param targetSpd number
---@return table @rgbm color
local function speedColor(currentSpd, targetSpd)
  local delta = currentSpd - targetSpd
  if delta > 8 then
    return COLOR_RED
  elseif delta <= 0 then
    return COLOR_GREEN
  end
  return COLOR_WHITE
end

-- ---------------------------------------------------------------------------
-- Progress bar widget
-- ---------------------------------------------------------------------------

---@param x number    left edge
---@param y number    top edge
---@param w number    total width
---@param h number    bar height
---@param pct number  0..1 fill percentage
local function drawProgressBar(x, y, w, h, pct)
  if not ui or type(ui.drawRectFilled) ~= "function" or type(vec2) ~= "function" then return end
  local p0 = vec2(x, y)
  local p1 = vec2(x + w, y + h)
  -- Background
  ui.drawRectFilled(p0, p1, COLOR_BAR_BG, h / 2)
  -- Fill
  local fillW = math.max(0, math.min(1, pct)) * w
  if fillW > 1 then
    -- Glow layer behind fill (subtle wider bar for bloom effect)
    if fillW > 4 then
      ui.drawRectFilled(vec2(x, y - 1), vec2(x + fillW, y + h + 1), COLOR_BAR_GLOW, h / 2)
    end
    -- Fill layer on top
    ui.drawRectFilled(p0, vec2(x + fillW, y + h), COLOR_BAR_FILL, h / 2)
  end
end

-- ---------------------------------------------------------------------------
-- Approach telemetry panel (issue #72 rebuild — always-visible, gearbox-style)
-- ---------------------------------------------------------------------------

--- Helper: measure DWrite text safely (returns vec2)
local function _measureDW(text, fontPx)
  if type(ui.measureDWriteText) == "function" then
    local sz = ui.measureDWriteText(text, fontPx)
    if sz then return sz end
  end
  return vec2(string.len(text or "") * fontPx * 0.55, fontPx)
end

--- Helper: draw DWrite text safely
local function _drawDW(text, fontPx, position, color)
  if type(ui.dwriteDrawText) == "function" then
    pcall(function()
      ui.dwriteDrawText(text, fontPx, position, color)
    end)
  end
end

--- Bottom tile: structured approach telemetry panel.
--- ALWAYS renders panel chrome + footer + section labels — never returns false
--- and never produces an empty box. Missing data shows as `—` placeholders.
---@param approachData table|nil  ApproachHudPayload from approachHudData(), or nil
---@return boolean @always true (signals "panel was drawn")
function M.drawApproachPanel(approachData)
  if not ui or type(vec2) ~= "function" then
    return false
  end
  if type(ui.drawRectFilled) ~= "function" then
    return false
  end

  -- Resolve fields with placeholders so the layout NEVER collapses on empty state.
  local hasData       = type(approachData) == "table"
  local turnLabelRaw  = hasData and approachData.turnLabel or nil
  local turnLabel     = (type(turnLabelRaw) == "string" and turnLabelRaw ~= "") and turnLabelRaw or "—"
  local targetSpd     = hasData and tonumber(approachData.targetSpeedKmh) or nil
  local currentSpd    = hasData and tonumber(approachData.currentSpeedKmh) or nil
  local distanceM     = hasData and tonumber(approachData.distanceToBrakeM) or nil
  local progressPct   = hasData and tonumber(approachData.progressPct) or 0
  local subState      = hasData and tostring(approachData.subState or approachData.status or "no_reference") or "no_reference"
  local hasReference  = hasData and (turnLabelRaw ~= nil or targetSpd ~= nil)

  -- Window dimensions (from manifest FIXED_SIZE 640x240)
  local w, h = 640, 240
  if ui.windowSize then
    local sz = ui.windowSize()
    if sz and sz.x and sz.x > 0 and sz.y and sz.y > 0 then
      w, h = sz.x, sz.y
    end
  end

  -- Panel background — always rendered
  ui.drawRectFilled(vec2(0, 0), vec2(w, h), COLOR_BG, PANEL_ROUNDING)
  if type(ui.drawRect) == "function" then
    ui.drawRect(vec2(0, 0), vec2(w, h), COLOR_BG_BORDER, PANEL_ROUNDING, nil, 1)
  end

  local padX = PANEL_PAD_X
  local padY = PANEL_PAD_Y

  ------------------------------------------------------------------
  -- ROW 1: split L/R
  --   LEFT  : "APPROACHING" small caps + corner label (Michroma)
  --   RIGHT : shared box → TARGET ENTRY | CURRENT  (Michroma numbers)
  ------------------------------------------------------------------
  local row1Y      = padY
  local leftX      = padX
  local rightBoxX  = math.floor(w * 0.50)
  local rightBoxW  = w - rightBoxX - padX
  local rightBoxH  = 80
  local rightBoxY  = row1Y - 6

  -- Shared right-side box frame
  ui.drawRectFilled(
    vec2(rightBoxX, rightBoxY),
    vec2(rightBoxX + rightBoxW, rightBoxY + rightBoxH),
    rgbm(0.04, 0.04, 0.05, 0.55),
    8
  )
  if type(ui.drawRect) == "function" then
    ui.drawRect(
      vec2(rightBoxX, rightBoxY),
      vec2(rightBoxX + rightBoxW, rightBoxY + rightBoxH),
      COLOR_BG_BORDER,
      8,
      nil,
      1
    )
  end

  -- LEFT column: APPROACHING label
  do
    local labelStr = (subState == "no_reference") and "WAITING" or "APPROACHING"
    local lk = fontMod.pushNamed("labels_bold", 11)
    _drawDW(labelStr, 11, vec2(leftX, row1Y), COLOR_LABEL_GREY)
    fontMod.pop(lk)
  end

  -- LEFT column: corner label (large Michroma uppercase)
  do
    local cornerStr = string.upper(turnLabel)
    local ck = fontMod.pushNamed("numbers", 28)
    _drawDW(cornerStr, 28, vec2(leftX, row1Y + 18), COLOR_WHITE)
    fontMod.pop(ck)
  end

  -- RIGHT column: shared box vertical split
  local subColW = math.floor(rightBoxW / 2)
  local subPad  = 14
  local tgtX    = rightBoxX + subPad
  local curX    = rightBoxX + subColW + subPad

  -- Vertical divider between TARGET ENTRY and CURRENT
  ui.drawRectFilled(
    vec2(rightBoxX + subColW, rightBoxY + 12),
    vec2(rightBoxX + subColW + 1, rightBoxY + rightBoxH - 12),
    COLOR_BG_BORDER,
    0
  )

  -- TARGET ENTRY label
  do
    local lk = fontMod.pushNamed("labels_bold", 10)
    _drawDW("TARGET ENTRY", 10, vec2(tgtX, rightBoxY + 12), COLOR_LABEL_GREY)
    fontMod.pop(lk)
  end

  -- TARGET ENTRY value (placeholder when nil)
  do
    local tgtStr = targetSpd and string.format("%.0f", targetSpd) or "—"
    local nk = fontMod.pushNamed("numbers", 26)
    _drawDW(tgtStr, 26, vec2(tgtX, rightBoxY + 30), COLOR_WHITE)
    fontMod.pop(nk)
    -- KM/H unit
    local tgtSize = _measureDW(tgtStr, 26)
    local uk = fontMod.pushNamed("labels_bold", 9)
    _drawDW("KM/H", 9, vec2(tgtX + tgtSize.x + 4, rightBoxY + 48), COLOR_LABEL_GREY)
    fontMod.pop(uk)
  end

  -- CURRENT label
  do
    local lk = fontMod.pushNamed("labels_bold", 10)
    local labelColor = (currentSpd and targetSpd and currentSpd > targetSpd + 8)
      and COLOR_RED or COLOR_LABEL_GREY
    _drawDW("CURRENT", 10, vec2(curX, rightBoxY + 12), labelColor)
    fontMod.pop(lk)
  end

  -- CURRENT value (red when over target+8, white otherwise)
  do
    local curStr = currentSpd and string.format("%.0f", currentSpd) or "—"
    local spdCol
    if currentSpd and targetSpd then
      spdCol = speedColor(currentSpd, targetSpd)
    else
      spdCol = COLOR_WHITE
    end
    local nk = fontMod.pushNamed("numbers", 28)
    _drawDW(curStr, 28, vec2(curX, rightBoxY + 28), spdCol)
    fontMod.pop(nk)
    local curSize = _measureDW(curStr, 28)
    local uk = fontMod.pushNamed("labels_bold", 9)
    _drawDW("KM/H", 9, vec2(curX + curSize.x + 4, rightBoxY + 48), spdCol)
    fontMod.pop(uk)
  end

  ------------------------------------------------------------------
  -- ROW 2: DISTANCE TO BRAKING POINT label + big number + progress bar
  ------------------------------------------------------------------
  local row2Y = rightBoxY + rightBoxH + 18

  do
    local lk = fontMod.pushNamed("labels_bold", 11)
    _drawDW("DISTANCE TO BRAKING POINT", 11, vec2(padX, row2Y), COLOR_LABEL_GREY)
    fontMod.pop(lk)
  end

  -- Big distance value, right-aligned
  do
    local distStr = distanceM and string.format("%d M", math.floor(distanceM + 0.5)) or "—"
    local nk = fontMod.pushNamed("numbers", 24)
    local distSize = _measureDW(distStr, 24)
    _drawDW(distStr, 24, vec2(w - padX - distSize.x, row2Y - 4), COLOR_WHITE)
    fontMod.pop(nk)
  end

  -- Progress bar (taller, red fill per Figma)
  local barY = row2Y + 26
  local barW = w - padX * 2
  local barH = 14
  drawProgressBar(padX, barY, barW, barH, progressPct or 0)

  ------------------------------------------------------------------
  -- Footer: AG PORSCHE ACADEMY (Syncopate brand)
  ------------------------------------------------------------------
  local divY = barY + barH + 14
  ui.drawRectFilled(
    vec2(padX, divY),
    vec2(w - padX, divY + 1),
    COLOR_BG_BORDER,
    0
  )

  do
    local footerStr = "AG PORSCHE ACADEMY"
    local fontPx = 12
    local footerSize = _measureDW(footerStr, fontPx)
    local footerX = math.floor(w * 0.5 - footerSize.x * 0.5)
    local fk = fontMod.pushNamed("brand", fontPx)
    _drawDW(footerStr, fontPx, vec2(footerX, divY + 10), COLOR_WHITE)
    fontMod.pop(fk)
  end

  -- Mark the variable as referenced for static analysis (avoids "unused" warning)
  local _ = hasReference

  return true
end

local function accentForKind(kind)
  local k = type(kind) == "string" and kind or "general"
  if k == "brake" then
    return rgbm(0.95, 0.30, 0.25, 1)
  end
  if k == "throttle" then
    return rgbm(0.25, 0.85, 0.35, 1)
  end
  if k == "line" then
    return rgbm(0.30, 0.70, 0.95, 1)
  end
  if k == "positive" then
    return rgbm(0.40, 0.90, 0.70, 1)
  end
  return rgbm(0.85, 0.85, 0.40, 1)
end

local function hintText(entry)
  if type(entry) == "table" and type(entry.text) == "string" then
    return entry.text
  end
  if type(entry) == "string" then
    return entry
  end
  return ""
end

local function hintKind(entry)
  if type(entry) == "table" and type(entry.kind) == "string" then
    return entry.kind
  end
  return "general"
end

--- Single clamp for `config.coachingMaxVisibleHints` (issue #43). Used by the entry script and both draw paths.
---@param raw any
---@return integer
function M.normalizedCoachingMaxVisibleHints(raw)
  local n = tonumber(raw)
  if not n or n ~= n then
    return 3
  end
  n = math.floor(n + 0.5)
  if n < 1 then
    return 1
  end
  if n > 3 then
    return 3
  end
  return n
end

--- Fade out in the last min(5s, hold) seconds so short `coachingHoldSeconds` stays at full opacity
--- until its own tail (CodeRabbit PR #50).
local function computeAlpha(timeRemaining, holdSeconds)
  local rem = math.max(0, timeRemaining or 0)
  local hold = tonumber(holdSeconds)
  if not hold or hold ~= hold or hold <= 0 then
    hold = 30
  end
  local fadeWindow = math.min(5.0, hold)
  if fadeWindow < 0.001 then
    fadeWindow = 0.001
  end
  if rem >= fadeWindow then
    return 1.0
  end
  return math.max(0, rem / fadeWindow)
end

--- Shared panel chrome for Coaching window idle / fallback states (PR #50 review).
local function drawStandardCoachingPanel(defaultW, defaultH, minH)
  local w, h = defaultW or 400, defaultH or 140
  local minHeight = minH or 100
  if ui.windowSize then
    local sz = ui.windowSize()
    if sz and sz.x and sz.y then
      w, h = sz.x, math.max(minHeight, sz.y)
    end
  end
  if ui.drawRectFilled and vec2 then
    ui.drawRectFilled(vec2(0, 0), vec2(w, h), rgbm(0.04, 0.04, 0.07, 0.78), 12)
  end
  if ui.drawRect and vec2 then
    ui.drawRect(vec2(0, 0), vec2(w, h), rgbm(0.4, 0.43, 0.5, 0.45), 12, nil, 1)
  end
end

---@param coachingLines table[]|string[]|nil
---@param timeRemaining number
---@param holdSeconds number
---@param maxVisibleHints integer|nil
function M.draw(coachingLines, timeRemaining, holdSeconds, maxVisibleHints)
  if not coachingLines or #coachingLines == 0 or timeRemaining <= 0 then
    return
  end
  if not ui or type(ui.textColored) ~= "function" then
    return
  end

  local alpha = computeAlpha(timeRemaining, holdSeconds)
  local hold = holdSeconds or 30

  local w, h = 400, 300
  if ui.windowSize then
    local sz = ui.windowSize()
    if sz and sz.x and sz.y then
      w, h = sz.x, sz.y
    end
  end
  if ui.drawRectFilled and vec2 then
    ui.drawRectFilled(vec2(0, 0), vec2(w, h), rgbm(0.05, 0.05, 0.08, 0.82 * alpha), 12)
  end
  if ui.drawRect and vec2 then
    ui.drawRect(vec2(0, 0), vec2(w, h), rgbm(0.45, 0.48, 0.55, 0.55 * alpha), 12, nil, 1)
  end

  local fk = fontMod.push()
  local titleColor = rgbm(0.35, 0.82, 0.95, alpha)
  ui.textColored("COACHING", titleColor)
  if ui.separator then
    ui.separator()
  end

  local cap = M.normalizedCoachingMaxVisibleHints(maxVisibleHints)
  local showN = math.min(cap, #coachingLines)
  for i = 1, showN do
    local body = hintText(coachingLines[i])
    if body ~= "" then
      local a = accentForKind(hintKind(coachingLines[i]))
      local col = rgbm(a.r, a.g, a.b, a.mult * alpha * 0.98)
      if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
        ui.pushStyleColor(ui.StyleColor.Text, col)
        ui.textWrapped(body)
        ui.popStyleColor()
      else
        ui.textColored(body, col)
      end
    end
  end

  fontMod.pop(fk)

  if timeRemaining < hold * 0.5 then
    ui.textColored(string.format("(%.0fs)", timeRemaining), rgbm(0.55, 0.58, 0.62, alpha * 0.65))
  end
end

function M.drawFallback()
  if not ui or type(ui.textColored) ~= "function" then
    return
  end
  drawStandardCoachingPanel(400, 120, 100)
  local fk = fontMod.push()
  ui.textColored("Complete a lap for coaching hints", rgbm(0.92, 0.93, 0.95, 0.95))
  fontMod.pop(fk)
  local sub = "Open the Coaching window (second app icon) for the full overlay after your first lap."
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, rgbm(0.65, 0.68, 0.74, 0.85))
    ui.textWrapped(sub)
    ui.popStyleColor()
  else
    ui.textColored(sub, rgbm(0.65, 0.68, 0.74, 0.85))
  end
end

--- Coaching window when session has started but no tip is active (timer expired or empty hints).
function M.drawBetweenLapsIdle(holdSeconds)
  if not ui or type(ui.textColored) ~= "function" then
    return
  end
  drawStandardCoachingPanel(400, 140, 120)
  local fk = fontMod.push()
  ui.textColored("COACHING", rgbm(0.35, 0.82, 0.95, 0.95))
  if ui.separator then
    ui.separator()
  end
  local hs = holdSeconds or 30
  local body = string.format(
    "No active tip right now. After each completed lap, hints show here for ~%ds. "
      .. "Complete another lap for fresh coaching, or check the main app window for telemetry.",
    math.floor(hs + 0.5)
  )
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, rgbm(0.72, 0.74, 0.78, 0.9))
    ui.textWrapped(body)
    ui.popStyleColor()
  else
    ui.textColored(body, rgbm(0.72, 0.74, 0.78, 0.9))
  end
  fontMod.pop(fk)
end

--- Lap completed and hold timer running, but `buildAfterLap` produced no lines (trace quality / first lap).
function M.drawHoldNoHints(remainingSec)
  if not ui or type(ui.textColored) ~= "function" then
    return
  end
  drawStandardCoachingPanel(400, 120, 100)
  local fk = fontMod.push()
  ui.textColored("COACHING", rgbm(0.35, 0.82, 0.95, 0.95))
  if ui.separator then
    ui.separator()
  end
  local r = math.max(0, remainingSec or 0)
  local body = string.format(
    "No hints for the last lap (needs a cleaner full lap or more data). Timer ~%.0fs — complete another lap to try again.",
    r
  )
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, rgbm(0.78, 0.72, 0.55, 0.92))
    ui.textWrapped(body)
    ui.popStyleColor()
  else
    ui.textColored(body, rgbm(0.78, 0.72, 0.55, 0.92))
  end
  fontMod.pop(fk)
end

--- Main telemetry window: primer or primary coaching line (issue #41).
---@class CoachingHudStrip
---@field coachingLines (string|{ kind: string, text: string })[]|nil
---@field coachingRemaining number|nil
---@field coachingHoldSeconds number|nil
---@field coachingMaxVisibleHints integer|nil
---@field coachingShowPrimer boolean|nil

---@param vm CoachingHudStrip
---@return boolean @true if anything was drawn (caller may add spacing only then)
function M.drawMainWindowStrip(vm)
  if not ui or type(ui.textColored) ~= "function" or not vec2 then
    return false
  end
  local lines = vm.coachingLines
  local rem = vm.coachingRemaining
  local hold = vm.coachingHoldSeconds or 30
  local maxVis = vm.coachingMaxVisibleHints
  local primer = vm.coachingShowPrimer

  local showActive = lines and #lines > 0 and rem and rem > 0
  local showPrimerBand = primer and not showActive
  if not showActive and not showPrimerBand then
    return false
  end

  if ui.separator then
    ui.separator()
  end

  local alpha = 1.0
  local title = "COACHING"
  local body
  local detail = ""
  local accent

  if showActive then
    alpha = computeAlpha(rem, hold)
    local cap = M.normalizedCoachingMaxVisibleHints(maxVis)
    local vis = math.min(#lines, cap)
    body = hintText(lines[1])
    accent = accentForKind(hintKind(lines[1]))
    if vis > 1 then
      detail = string.format("+%d more in Coaching window", vis - 1)
    end
  else
    title = "COACHING"
    body = "Complete a lap for coaching hints"
    detail = "Full hints appear here and in the Coaching window."
    accent = rgbm(0.88, 0.9, 0.94, 1)
  end

  local pad = vec2(10, 8)
  local region = vec2(0, 0)
  if type(ui.getCursor) == "function" then
    local ok, cur = pcall(ui.getCursor)
    if ok and cur and type(cur.x) == "number" and type(cur.y) == "number" then
      region = cur
    end
  end
  local rw = 360
  if type(ui.availableSpaceX) == "function" then
    rw = ui.availableSpaceX() or rw
  end
  -- Taller band so wrapped coaching lines do not clip the panel edges.
  local boxH = showPrimerBand and 92 or 118
  local p0 = vec2(region.x, region.y)
  local p1 = vec2(region.x + rw, region.y + boxH)
  if ui.drawRectFilled then
    ui.drawRectFilled(p0, p1, rgbm(0.04, 0.04, 0.07, 0.78 * alpha), 8)
  end
  if ui.drawRect then
    ui.drawRect(p0, p1, rgbm(0.42, 0.45, 0.52, 0.5 * alpha), 8, nil, 1)
  end

  if ui.setCursor then
    ui.setCursor(vec2(region.x + pad.x, region.y + pad.y))
  end

  local fk = fontMod.push()
  ui.textColored(title, rgbm(0.35, 0.82, 0.95, alpha))
  if ui.spacing then
    ui.spacing()
  end
  local colBody = rgbm(accent.r, accent.g, accent.b, accent.mult * alpha * 0.98)
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, colBody)
    ui.textWrapped(body)
    ui.popStyleColor()
  else
    ui.textColored(body, colBody)
  end
  if detail ~= "" then
    if ui.spacing then
      ui.spacing()
    end
    local colDet = rgbm(0.62, 0.65, 0.7, alpha * 0.85)
    if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
      ui.pushStyleColor(ui.StyleColor.Text, colDet)
      ui.textWrapped(detail)
      ui.popStyleColor()
    else
      ui.textColored(detail, colDet)
    end
  end
  fontMod.pop(fk)

  if ui.setCursor then
    ui.setCursor(vec2(region.x, region.y + boxH + 6))
  elseif ui.dummy then
    ui.dummy(vec2(1, 6))
  end
  return true
end

--- Wrapped debrief text from Python sidecar when ``AC_COPILOT_OLLAMA_ENABLE=1`` (issue #46).
--- Long text relies on the parent ImGui region for scrolling unless we add a child window later.
---@param text string|nil
function M.drawSidecarDebrief(text)
  if not text or text == "" or not ui or type(ui.textColored) ~= "function" then
    return
  end
  if ui.separator then
    ui.separator()
  end
  local fk = fontMod.push()
  ui.textColored("SESSION DEBRIEF (sidecar)", rgbm(0.55, 0.82, 0.95, 0.95))
  if ui.separator then
    ui.separator()
  end
  local col = rgbm(0.78, 0.80, 0.86, 0.92)
  if ui.textWrapped then
    if ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
      ui.pushStyleColor(ui.StyleColor.Text, col)
      ui.textWrapped(text)
      ui.popStyleColor()
    else
      ui.textWrapped(text)
    end
  else
    ui.textColored(text, col)
  end
  fontMod.pop(fk)
end

return M
