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

local function computeAlpha(timeRemaining, holdSeconds)
  local fadeStart = 5.0
  local alpha = 1.0
  if timeRemaining < fadeStart then
    alpha = math.max(0, timeRemaining / fadeStart)
  end
  local hold = holdSeconds or 30
  local fadeIn = math.min(1, math.max(0, (hold - timeRemaining) / 0.5))
  return alpha * fadeIn
end

---@param coachingLines table[]|string[]|nil
---@param timeRemaining number
---@param holdSeconds number
function M.draw(coachingLines, timeRemaining, holdSeconds)
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

  for i = 1, math.min(3, #coachingLines) do
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
  local w, h = 400, 120
  if ui.windowSize then
    local sz = ui.windowSize()
    if sz and sz.x and sz.y then
      w, h = sz.x, sz.y
    end
  end
  if ui.drawRectFilled and vec2 then
    ui.drawRectFilled(vec2(0, 0), vec2(w, h), rgbm(0.04, 0.04, 0.07, 0.78), 12)
  end
  if ui.drawRect and vec2 then
    ui.drawRect(vec2(0, 0), vec2(w, h), rgbm(0.4, 0.43, 0.5, 0.5), 12, nil, 1)
  end
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

--- Main telemetry window: primer or primary coaching line (issue #41).
---@class CoachingHudStrip
---@field coachingLines (string|{ kind: string, text: string })[]|nil
---@field coachingRemaining number|nil
---@field coachingHoldSeconds number|nil
---@field coachingShowPrimer boolean|nil

---@param vm CoachingHudStrip
function M.drawMainWindowStrip(vm)
  if not ui or type(ui.textColored) ~= "function" or not vec2 then
    return
  end
  local lines = vm.coachingLines
  local rem = vm.coachingRemaining
  local hold = vm.coachingHoldSeconds or 30
  local primer = vm.coachingShowPrimer

  local showActive = lines and #lines > 0 and rem and rem > 0
  local showPrimerBand = primer and not showActive
  if not showActive and not showPrimerBand then
    return
  end

  local alpha = 1.0
  local title = "COACHING"
  local body
  local detail = ""
  local accent

  if showActive then
    alpha = computeAlpha(rem, hold)
    body = hintText(lines[1])
    accent = accentForKind(hintKind(lines[1]))
    if #lines > 1 then
      detail = string.format("+%d more in Coaching window", #lines - 1)
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
end

return M
