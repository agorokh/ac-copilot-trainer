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

local SPLINE_REWIND_THRESHOLD = -0.2  -- a backward spline delta past this = discontinuity, not jitter

--- True when the spline jumped backward past the rewind threshold — ANY shape, INCLUDING a
--- wrap-shaped jump (prev near 1.0 -> now near 0.0). Use this where over-triggering is HARMLESS:
--- the `delta` producer's skip guard. Both producer callers run only with lapCount unchanged
--- (atLapCountChange already excludes real lap wraps), so a wrap-shaped backward jump there is a
--- teleport/return-to-garage/pit reset, not a lap completion — and skipping a delta frame on it is
--- always safe even on CSP builds where resetCounter is unavailable (codex on #185).
---@param prevSpline number|nil  previous frame's car.splinePosition (nil before the first frame)
---@param spline number          this frame's car.splinePosition
---@return boolean
function M.isBackwardSplineJump(prevSpline, spline)
  if prevSpline == nil then
    return false
  end
  return ((spline or 0) - prevSpline) < SPLINE_REWIND_THRESHOLD
end

local function isLikelyLapWrap(prevSpline, spline)
  return prevSpline ~= nil and prevSpline > 0.8 and (spline or 0) < 0.25
end

--- True when a backward jump has the same shape as a normal lap wrap.
---@param prevSpline number|nil
---@param spline number
---@return boolean
function M.isWrapShapedBackwardSplineJump(prevSpline, spline)
  return M.isBackwardSplineJump(prevSpline, spline) and isLikelyLapWrap(prevSpline, spline)
end

--- True when the spline jumped backward in a way that should CLEAR rolling driving state (lap
--- clock, coaching, aggregates) via resetRollingDrivingState. CONSERVATIVE: excludes a lap *wrap*
--- (prev near 1.0 -> now near 0.0), because over-triggering here is NOT harmless — a false positive
--- at the start/finish line would wipe coaching/session every lap if CSP ever exposes spline before
--- the matching lapCount increment. Use this where the cost of a false reset is high (the
--- end-of-update reset). Teleports are caught unambiguously by car.resetCounter; this is the
--- spline-only fallback for genuine backward driving (Cursor + codex on #185).
---@param prevSpline number|nil
---@param spline number
---@return boolean
function M.isBackwardSplineReset(prevSpline, spline)
  if not M.isBackwardSplineJump(prevSpline, spline) then
    return false
  end
  return not isLikelyLapWrap(prevSpline, spline)
end

--- Decide whether the end-of-update rolling state should reset.
---
--- Wrap-shaped same-lap jumps are ambiguous on CSP builds without `car.resetCounter`: they might
--- be a real lap wrap exposed one frame before `lapCount`, or a return-to-pits teleport landing
--- near the start line. Defer exactly one frame; if `lapCount` advances, it was a lap wrap; if it
--- does not, clear rolling state for the abandoned stint (#188).
---@param opts table
---@return table { reset: boolean, pendingWrapLapCount: number|nil }
function M.rollingResetDecision(opts)
  opts = opts or {}
  local pendingWrapLapCount = opts.pendingWrapLapCount
  local lastLapCount = opts.lastLapCount
  local lapCount = opts.lapCount

  if opts.teleported then
    return { reset = true, pendingWrapLapCount = nil }
  end

  if type(lastLapCount) == "number"
      and type(lapCount) == "number"
      and lastLapCount >= 0
      and lapCount < lastLapCount then
    return { reset = true, pendingWrapLapCount = nil }
  end

  if pendingWrapLapCount ~= nil then
    if type(lapCount) ~= "number" then
      return { reset = false, pendingWrapLapCount = pendingWrapLapCount }
    end
    if lapCount > pendingWrapLapCount then
      return { reset = false, pendingWrapLapCount = nil }
    end
    return { reset = true, pendingWrapLapCount = nil }
  end

  if type(lastLapCount) == "number"
      and type(lapCount) == "number"
      and lastLapCount >= 0
      and lapCount == lastLapCount
      and opts.prevSpline ~= nil then
    if M.isBackwardSplineReset(opts.prevSpline, opts.spline) then
      return { reset = true, pendingWrapLapCount = nil }
    end
    if M.isWrapShapedBackwardSplineJump(opts.prevSpline, opts.spline) then
      return { reset = false, pendingWrapLapCount = lapCount }
    end
  end

  return { reset = false, pendingWrapLapCount = nil }
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

--- Deterministic sector and micro-sector windows in spline space.
---@param microPerSector integer|nil subdivisions per sector (default 3)
---@return table { sectors: table[], microSectors: table[] }
function M.segmentWindows(microPerSector)
  local microN = tonumber(microPerSector) or 3
  microN = math.max(1, math.floor(microN))
  local sectors = {}
  local microSectors = {}
  for si = 1, 3 do
    local s0 = (si - 1) / 3
    local s1 = si / 3
    local label = "S" .. tostring(si)
    sectors[#sectors + 1] = {
      key = string.lower(label),
      label = label,
      splineStart = s0,
      splineEnd = s1,
      sectorIndex = si,
    }
    local span = s1 - s0
    for mi = 1, microN do
      local m0 = s0 + span * (mi - 1) / microN
      local m1 = s0 + span * mi / microN
      local mlabel = label .. "." .. tostring(mi)
      microSectors[#microSectors + 1] = {
        key = string.lower(mlabel),
        label = mlabel,
        splineStart = m0,
        splineEnd = m1,
        sectorIndex = si,
        microIndex = mi,
      }
    end
  end
  return { sectors = sectors, microSectors = microSectors }
end

--- Reference duration (ms) between two spline positions.
---@param sortedTrace LapTraceSample[]|nil
---@param splineLo number
---@param splineHi number
---@return number|nil
function M.segmentDurationMs(sortedTrace, splineLo, splineHi)
  if not sortedTrace or #sortedTrace < 2 then
    return nil
  end
  local a = M.bestElapsedMsAtSpline(sortedTrace, splineLo)
  local b = M.bestElapsedMsAtSpline(sortedTrace, splineHi)
  if not a or not b then
    return nil
  end
  local d = b - a
  if d < -1e-6 then
    return nil
  end
  return math.max(0, d)
end

--- Segment delta (ms): positive = slower than the reference segment.
---@param sortedTrace LapTraceSample[]|nil
---@param splineLo number
---@param splineHi number
---@param actualMs number|nil
---@return number|nil
function M.segmentDeltaMs(sortedTrace, splineLo, splineHi, actualMs)
  if actualMs == nil then
    return nil
  end
  local refMs = M.segmentDurationMs(sortedTrace, splineLo, splineHi)
  if not refMs then
    return nil
  end
  return actualMs - refMs
end

return M
