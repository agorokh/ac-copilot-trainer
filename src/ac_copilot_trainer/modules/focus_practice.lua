-- Focus practice mode (issue #44): corner label selection + coaching filter helpers.
-- Pure logic here is mirrored by tests/test_focus_practice.py for CI.

local coachingHints = require("coaching_hints")

local M = {}

local function wrap01(x)
  if type(x) ~= "number" then
    return 0
  end
  local s = x % 1
  if s < 0 then
    s = s + 1
  end
  return s
end

--- Parse "T1, T2 ,T3" or "T1;T2" into a map label -> true.
---@param s string|nil
---@return table<string, boolean>
function M.cornerLabelsMapFromString(s)
  local out = {}
  if type(s) ~= "string" then
    return out
  end
  for token in string.gmatch(s, "[^,;]+") do
    local lab = token:match("^%s*(%u%d+)%s*$")
    if lab then
      out[lab] = true
    end
  end
  return out
end

--- Build focus map from `consistencySummary().worstThree` rows (up to maxN labels).
---@param worstThree string[]|nil
---@param maxN number|nil
---@return table<string, boolean>
function M.cornerLabelsMapFromWorst(worstThree, maxN)
  local out = {}
  local nmax = tonumber(maxN) or 3
  if nmax < 1 then
    nmax = 1
  end
  if nmax > 3 then
    nmax = 3
  end
  if type(worstThree) ~= "table" then
    return out
  end
  for i = 1, #worstThree do
    if nmax <= 0 then
      break
    end
    local lab = coachingHints.labelFromConsistencyEntry(worstThree[i])
    if lab and not out[lab] then
      out[lab] = true
      nmax = nmax - 1
    end
  end
  return out
end

---@param a number
---@param b number
---@return number
local function splineDistWrap(a, b)
  a, b = wrap01(a), wrap01(b)
  local d = math.abs(a - b)
  if d > 0.5 then
    d = 1 - d
  end
  return d
end

--- True if brake spline sits on a focus corner's recorded brake spline (within tol).
---@param brakeSpline number|nil
---@param focusMap table<string, boolean>|nil
---@param corners table[]|nil corner feature rows with .label and .brakePointSpline
---@param tol number|nil default 0.012 (normalized spline delta; order of percent-of-lap, e.g. ~60 m on a 5 km lap)
---@return boolean
function M.brakeSplineMatchesFocus(brakeSpline, focusMap, corners, tol)
  if brakeSpline == nil or type(brakeSpline) ~= "number" then
    return false
  end
  if type(focusMap) ~= "table" or next(focusMap) == nil then
    return false
  end
  if type(corners) ~= "table" then
    return false
  end
  local t = tonumber(tol) or 0.012
  for i = 1, #corners do
    local c = corners[i]
    if type(c) == "table" then
      local lab = c.label
      if type(lab) == "string" and focusMap[lab] then
        local bs = tonumber(c.brakePointSpline)
        if bs and splineDistWrap(brakeSpline, bs) <= t then
          return true
        end
      end
    end
  end
  return false
end

--- When focus mode is on, keep corner-specific hints that reference a focus label; otherwise thin to one line.
---@param hints table[]|nil
---@param focusActive boolean|nil
---@param focusMap table<string, boolean>|nil
---@return table[]
function M.filterCoachingHints(hints, focusActive, focusMap)
  if not hints or type(hints) ~= "table" or #hints == 0 then
    return hints or {}
  end
  if not focusActive or type(focusMap) ~= "table" or next(focusMap) == nil then
    return hints
  end
  local function mentionsFocus(text)
    if type(text) ~= "string" then
      return false
    end
    for lab in pairs(focusMap) do
      local prefix = lab .. ":"
      if text:sub(1, #prefix) == prefix then
        return true
      end
      if text:find(prefix, 1, true) then
        return true
      end
    end
    return false
  end
  local focused = {}
  for i = 1, #hints do
    local h = hints[i]
    if type(h) == "table" and mentionsFocus(h.text) then
      focused[#focused + 1] = h
    end
  end
  if #focused > 0 then
    return focused
  end
  return { hints[1] }
end

--- Human-readable summary for HUD (which corners are targeted).
---@param focusMap table<string, boolean>|nil
---@param manualUsed boolean|nil
---@return string
function M.describeFocusMap(focusMap, manualUsed)
  if type(focusMap) ~= "table" or next(focusMap) == nil then
    return manualUsed and "Focus: (no labels parsed — check config)" or "Focus: waiting for consistency (drive 2+ laps)"
  end
  local labs = {}
  for k in pairs(focusMap) do
    labs[#labs + 1] = k
  end
  table.sort(labs)
  local src = manualUsed and "manual" or "auto worst"
  return "Focus corners (" .. src .. "): " .. table.concat(labs, ", ")
end

return M
