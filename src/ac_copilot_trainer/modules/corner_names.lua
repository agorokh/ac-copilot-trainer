-- Track corner display names from corners.ini + left/right from reference trace (issue #57 Part A).

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

local function trim(s)
  if not s then
    return ""
  end
  return (tostring(s):gsub("^%s+", ""):gsub("%s+$", ""))
end

--- Parse Assetto Corsa-style `corners.ini` sections `[CORNER_N]` with `NAME=`.
---@param content string|nil
---@return table byId map corner section id -> { name = string }
function M.parseCornersIni(content)
  local byId = {}
  if type(content) ~= "string" or content == "" then
    return byId
  end
  local currentId ---@type integer|nil
  for line in content:gmatch("[^\r\n]+") do
    local l = trim(line)
    if l ~= "" and l:sub(1, 1) ~= ";" and l:sub(1, 1) ~= "#" then
      local sec = l:match("^%[CORNER_(%d+)%]")
      if sec then
        currentId = tonumber(sec)
      elseif l:match("^%[") then
        currentId = nil
      elseif currentId ~= nil then
        local k, v = l:match("^([%w_]+)%s*=%s*(.*)$")
        if k and v ~= nil then
          k = k:upper()
          v = trim(v)
          if k == "NAME" and v ~= "" then
            byId[currentId] = byId[currentId] or {}
            byId[currentId].name = v
          end
        end
      end
    end
  end
  return byId
end

--- Kunos-style `CORNER_0` is turn 1. Prefer `CORNER_(turnIndex-1)` then `CORNER_turnIndex`.
---@param byId table
---@param turnIndex integer @1-based (T1 -> 1)
---@return string|nil
function M.iniNameForTurnIndex(byId, turnIndex)
  if type(byId) ~= "table" or type(turnIndex) ~= "number" then
    return nil
  end
  local ti = math.floor(turnIndex)
  if ti < 1 then
    return nil
  end
  local row = byId[ti - 1] or byId[ti]
  if row and type(row.name) == "string" and row.name ~= "" then
    return row.name
  end
  return nil
end

--- Average steering sign in spline range (same wrap semantics as `corner_analysis.statsInSplineRange`).
---@param trace table[]|nil
---@param s0 number
---@param s1 number
---@param wrap boolean
---@return string|nil @ "Left", "Right", or nil if ambiguous
function M.steerSideForRange(trace, s0, s1, wrap)
  if not trace or #trace < 2 then
    return nil
  end
  s0, s1 = wrap01(s0), wrap01(s1)
  local sum = 0
  local n = 0
  for i = 1, #trace do
    local p = trace[i]
    local sp = wrap01(p.spline or 0)
    local inside
    if wrap then
      inside = sp >= s0 or sp < s1
    else
      inside = sp >= s0 and sp < s1
    end
    if inside then
      sum = sum + (tonumber(p.steer) or 0)
      n = n + 1
    end
  end
  if n == 0 then
    return nil
  end
  local avg = sum / n
  if avg > 0.02 then
    return "Right"
  end
  if avg < -0.02 then
    return "Left"
  end
  return nil
end

local function splineNear(a, b, tol)
  a, b = wrap01(a), wrap01(b)
  local d = math.abs(a - b)
  d = math.min(d, 1 - d)
  return d <= tol
end

--- Find corner segment whose `brakeSpline` matches `brakeSpline`.
---@param segments table[]|nil
---@param brakeSpline number
---@param tol number|nil
---@return table|nil
function M.cornerSegmentForBrakeSpline(segments, brakeSpline, tol)
  if type(segments) ~= "table" or type(brakeSpline) ~= "number" then
    return nil
  end
  local t = tol or 0.012
  local best, bestD = nil, math.huge
  for i = 1, #segments do
    local seg = segments[i]
    if type(seg) == "table" and seg.kind == "corner" and type(seg.brakeSpline) == "number" then
      local bs = wrap01(seg.brakeSpline)
      local d = math.abs(bs - wrap01(brakeSpline))
      d = math.min(d, 1 - d)
      if d < bestD then
        bestD = d
        best = seg
      end
    end
  end
  if best and bestD <= (t * 2.5) then
    return best
  end
  return nil
end

---@param corners table[]|nil
---@param brakeSpline number
---@param tol number|nil
---@return string|nil
function M.cornerLabelFromFeatures(corners, brakeSpline, tol)
  if type(corners) ~= "table" or type(brakeSpline) ~= "number" then
    return nil
  end
  local t = tol or 0.012
  for i = 1, #corners do
    local c = corners[i]
    if type(c) == "table" and type(c.brakePointSpline) == "number" and type(c.label) == "string" then
      if splineNear(c.brakePointSpline, brakeSpline, t) then
        return c.label
      end
    end
  end
  return nil
end

--- Human-readable label: ini name or Tn, plus Left/Right from precomputed map or trace fallback.
---@param opts table
---@return string
function M.resolveApproachLabel(opts)
  local brakeSpline = opts.brakeSpline
  local brakeIndex = opts.brakeIndex
  local segments = opts.segments
  local iniById = opts.iniById
  local trace = opts.trace
  local cornerFeats = opts.cornerFeats
  local steerMap = opts.steerSideByLabel

  local base = "Brake"
  local turnNum ---@type integer|nil
  local seg = M.cornerSegmentForBrakeSpline(segments, brakeSpline or 0, opts.tol)
  if seg and type(seg.label) == "string" then
    base = seg.label
    turnNum = tonumber(seg.label:match("^T(%d+)$"))
  else
    local lab = M.cornerLabelFromFeatures(cornerFeats, brakeSpline or 0, opts.tol)
    if lab then
      base = lab
      turnNum = tonumber(lab:match("^T(%d+)$"))
    elseif type(brakeIndex) == "number" then
      -- Brake list index is not the same as turn number; do not drive corners.ini lookup (Bugbot #58).
      base = "Brake " .. tostring(math.floor(brakeIndex))
      turnNum = nil
    end
  end

  local iniName = nil
  if type(iniById) == "table" and turnNum then
    iniName = M.iniNameForTurnIndex(iniById, turnNum)
  end
  local head = iniName or base

  local side ---@type string|nil
  if type(steerMap) == "table" and seg and type(seg.label) == "string" then
    side = steerMap[seg.label]
  end
  if side == nil and seg and type(seg.s0) == "number" and type(seg.s1) == "number" then
    local tr = trace
    if tr and #tr >= 2 then
      local wrap = seg.s1 <= seg.s0
      side = M.steerSideForRange(tr, seg.s0, seg.s1, wrap)
    end
  end

  if side then
    return head .. " " .. side
  end
  return head
end

return M
