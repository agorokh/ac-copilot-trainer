-- Coaching overlay: panel + per-hint colors (issue #39 Part F).

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

  local fadeStart = 5.0
  local alpha = 1.0
  if timeRemaining < fadeStart then
    alpha = math.max(0, timeRemaining / fadeStart)
  end
  local hold = holdSeconds or 30
  local fadeIn = math.min(1, math.max(0, (hold - timeRemaining) / 0.5))
  alpha = alpha * fadeIn

  local w, h = 400, 300
  if ui.windowSize then
    local sz = ui.windowSize()
    if sz and sz.x and sz.y then
      w, h = sz.x, sz.y
    end
  end
  if ui.drawRectFilled and vec2 then
    ui.drawRectFilled(vec2(0, 0), vec2(w, h), rgbm(0.05, 0.05, 0.08, 0.75 * alpha), 12)
  end
  if ui.drawRect and vec2 then
    ui.drawRect(vec2(0, 0), vec2(w, h), rgbm(0.3, 0.3, 0.4, 0.5 * alpha), 12, nil, 1)
  end

  local titleColor = rgbm(0.35, 0.82, 0.95, alpha)
  ui.textColored(titleColor, "COACHING")
  if ui.separator then
    ui.separator()
  end

  for i = 1, math.min(3, #coachingLines) do
    local body = hintText(coachingLines[i])
    if body ~= "" then
      local a = accentForKind(hintKind(coachingLines[i]))
      ui.textColored(rgbm(a.r, a.g, a.b, a.mult * alpha * 0.95), body)
    end
  end

  if timeRemaining < hold * 0.5 then
    ui.textColored(rgbm(0.4, 0.4, 0.45, alpha * 0.5), string.format("(%.0fs)", timeRemaining))
  end
end

function M.drawFallback()
  if not ui or type(ui.textColored) ~= "function" then
    return
  end
  if ui.drawRectFilled and vec2 and ui.windowSize then
    local sz = ui.windowSize()
    if sz and sz.x and sz.y then
      ui.drawRectFilled(vec2(0, 0), vec2(sz.x, sz.y), rgbm(0.05, 0.05, 0.08, 0.5), 12)
    end
  end
  ui.textColored(rgbm(0.5, 0.5, 0.55, 0.6), "Complete a lap for coaching hints")
end

return M
