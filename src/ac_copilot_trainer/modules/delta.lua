-- Live delta-to-best: interpolate reference lap elapsed by spline (binary search on sorted spline).

local M = {}

--- Telemetry row used for delta / sector math after `prepareTrace`.
---@class LapTraceSample
---@field spline number
---@field eMs number
---@field speed number|nil

local function sortBySpline(trace)
  local idx = {}
  for i = 1, #trace do
    idx[i] = i
  end
  table.sort(idx, function(a, b)
    return trace[a].spline < trace[b].spline
  end)
  local sorted = {}
  for i = 1, #idx do
    sorted[i] = trace[idx[i]]
  end
  return sorted
end

--- Build sorted-by-spline view for O(log n) lookup (call when reference trace changes).
---@param trace LapTraceSample[]|nil
---@return LapTraceSample[]|nil
function M.prepareTrace(trace)
  if not trace or #trace < 2 then
    return nil
  end
  return sortBySpline(trace)
end

--- Reference elapsed (ms) at spline position using linear interpolation between neighbors.
---@param sortedTrace LapTraceSample[]|nil
---@param splinePos number
---@return number|nil
local function interpAtSpline(sortedTrace, splinePos, fieldA, fieldB)
  if not sortedTrace or #sortedTrace < 2 then
    return nil
  end
  local n = #sortedTrace
  local sp = splinePos
  if sp <= sortedTrace[1].spline then
    local v = sortedTrace[1][fieldA]
    return type(v) == "number" and v or nil
  end
  if sp >= sortedTrace[n].spline then
    local v = sortedTrace[n][fieldA]
    return type(v) == "number" and v or nil
  end
  local lo, hi = 1, n
  while hi - lo > 1 do
    local mid = math.floor((lo + hi) / 2)
    if sortedTrace[mid].spline <= sp then
      lo = mid
    else
      hi = mid
    end
  end
  local a, b = sortedTrace[lo], sortedTrace[hi]
  local ds = b.spline - a.spline
  if ds <= 1e-9 then
    local v = a[fieldA]
    return type(v) == "number" and v or nil
  end
  local t = (sp - a.spline) / ds
  local va, vb = a[fieldA], b[fieldB or fieldA]
  if type(va) ~= "number" or type(vb) ~= "number" then
    return nil
  end
  return va + t * (vb - va)
end

function M.bestElapsedMsAtSpline(sortedTrace, splinePos)
  return interpAtSpline(sortedTrace, splinePos, "eMs", "eMs")
end

--- Reference speed (km/h) at spline (same geometry as elapsed interpolation).
---@param sortedTrace LapTraceSample[]|nil
---@param splinePos number
---@return number|nil
function M.bestSpeedKmhAtSpline(sortedTrace, splinePos)
  return interpAtSpline(sortedTrace, splinePos, "speed", "speed")
end

--- Delta in seconds: positive = slower than reference at this track position.
---@param sortedTrace LapTraceSample[]|nil
---@param splinePos number
---@param currentElapsedMs number|nil
---@return number|nil
function M.deltaSecondsAtSpline(sortedTrace, splinePos, currentElapsedMs)
  if currentElapsedMs == nil then
    return nil
  end
  local bestE = M.bestElapsedMsAtSpline(sortedTrace, splinePos)
  if not bestE then
    return nil
  end
  return (currentElapsedMs - bestE) / 1000
end

--- Sector durations (ms) for three spline thirds: [0,1/3), [1/3,2/3), [2/3,1).
---@param sortedTrace LapTraceSample[]|nil
---@return number[]|nil three cumulative boundaries ms at 1/3 and 2/3, and lap end
function M.sectorBoundariesMs(sortedTrace)
  if not sortedTrace or #sortedTrace < 2 then
    return nil
  end
  local e1 = M.bestElapsedMsAtSpline(sortedTrace, 1 / 3)
  local e2 = M.bestElapsedMsAtSpline(sortedTrace, 2 / 3)
  local eEnd = sortedTrace[#sortedTrace].eMs
  if not e1 or not e2 or not eEnd then
    return nil
  end
  return { e1, e2, eEnd }
end

return M
