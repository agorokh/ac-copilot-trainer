-- Coaching overlay: panel + per-hint colors (issue #39 Part F); font + HUD strip (issue #41).

local fontMod = require("coaching_font")

local M = {}

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
  ui.textColored(titleColor, "COACHING")
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
        ui.textColored(col, body)
      end
    end
  end

  fontMod.pop(fk)

  if timeRemaining < hold * 0.5 then
    ui.textColored(rgbm(0.55, 0.58, 0.62, alpha * 0.65), string.format("(%.0fs)", timeRemaining))
  end
end

function M.drawFallback()
  if not ui or type(ui.textColored) ~= "function" then
    return
  end
  drawStandardCoachingPanel(400, 120, 100)
  local fk = fontMod.push()
  ui.textColored(rgbm(0.92, 0.93, 0.95, 0.95), "Complete a lap for coaching hints")
  fontMod.pop(fk)
  local sub = "Open the Coaching window (second app icon) for the full overlay after your first lap."
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, rgbm(0.65, 0.68, 0.74, 0.85))
    ui.textWrapped(sub)
    ui.popStyleColor()
  else
    ui.textColored(rgbm(0.65, 0.68, 0.74, 0.85), sub)
  end
end

--- Coaching window when session has started but no tip is active (timer expired or empty hints).
function M.drawBetweenLapsIdle(holdSeconds)
  if not ui or type(ui.textColored) ~= "function" then
    return
  end
  drawStandardCoachingPanel(400, 140, 120)
  local fk = fontMod.push()
  ui.textColored(rgbm(0.35, 0.82, 0.95, 0.95), "COACHING")
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
    ui.textColored(rgbm(0.72, 0.74, 0.78, 0.9), body)
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
  ui.textColored(rgbm(0.35, 0.82, 0.95, 0.95), "COACHING")
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
    ui.textColored(rgbm(0.78, 0.72, 0.55, 0.92), body)
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
  ui.textColored(rgbm(0.35, 0.82, 0.95, alpha), title)
  if ui.spacing then
    ui.spacing()
  end
  local colBody = rgbm(accent.r, accent.g, accent.b, accent.mult * alpha * 0.98)
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, colBody)
    ui.textWrapped(body)
    ui.popStyleColor()
  else
    ui.textColored(colBody, body)
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
      ui.textColored(colDet, detail)
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
  ui.textColored(rgbm(0.55, 0.82, 0.95, 0.95), "SESSION DEBRIEF (sidecar)")
  if ui.separator then
    ui.separator()
  end
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, rgbm(0.78, 0.80, 0.86, 0.92))
    ui.textWrapped(text)
    ui.popStyleColor()
  else
    ui.textColored(rgbm(0.78, 0.80, 0.86, 0.92), text)
  end
  fontMod.pop(fk)
end

return M
