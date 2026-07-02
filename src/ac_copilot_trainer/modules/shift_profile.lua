-- Derived shift coaching profile (#442).
--
-- Lap archives remain the source of truth. This module derives a small live
-- profile from the active reference trace so the HUD can teach the observed
-- upshift point for the current car/gear instead of a fixed limiter fraction.

local M = {}

local DEFAULT_SHIFT_ZONE_FRAC = 0.92
local DEFAULT_REDLINE_FRAC = 0.97
local MIN_SHIFT_RPM = 1000
local MIN_SHIFT_GAS = 0.45
local MAX_SHIFT_WINDOW_MS = 1500
local CORNER_EXIT_FRAC = 0.30
local CORNER_EXIT_MAX_SPLINE = 0.03

M.DEFAULT_SHIFT_ZONE_FRAC = DEFAULT_SHIFT_ZONE_FRAC
M.DEFAULT_REDLINE_FRAC = DEFAULT_REDLINE_FRAC

local function clamp(v, lo, hi)
  if v < lo then return lo end
  if v > hi then return hi end
  return v
end

local function median(values)
  if type(values) ~= "table" or #values == 0 then
    return nil
  end
  table.sort(values)
  local mid = math.floor((#values + 1) / 2)
  if #values % 2 == 1 then
    return values[mid]
  end
  return (values[mid] + values[mid + 1]) * 0.5
end

local function roundedGear(raw)
  local n = tonumber(raw)
  if not n or n ~= n then return nil end
  local g = math.floor(n + 0.5)
  if g <= 0 then return nil end
  return g
end

local function transitionRpm(...)
  local rpm = 0
  for i = 1, select("#", ...) do
    local frame = select(i, ...)
    local r = tonumber(frame and frame.rpm)
    if r and r == r and r > rpm then
      rpm = r
    end
  end
  if not rpm or rpm ~= rpm or rpm < MIN_SHIFT_RPM then
    return nil
  end
  return rpm
end

local function maxThrottle(...)
  local gas = 0
  for i = 1, select("#", ...) do
    local frame = select(i, ...)
    local g = tonumber(frame and frame.throttle) or tonumber(frame and frame.gas)
    if g and g == g and g > gas then
      gas = g
    end
  end
  return gas
end

local function mergeShiftWindow(window, frame)
  if type(frame) ~= "table" then
    return window
  end
  window = window or { rpm = 0, throttle = 0 }
  local rpm = tonumber(frame.rpm)
  if rpm and rpm == rpm and rpm > (tonumber(window.rpm) or 0) then
    window.rpm = rpm
  end
  local gas = tonumber(frame.throttle) or tonumber(frame.gas)
  if gas and gas == gas and gas > (tonumber(window.throttle) or 0) then
    window.throttle = gas
  end
  return window
end

local function elapsedMs(prev, cur)
  local a = tonumber(prev and prev.eMs)
  local b = tonumber(cur and cur.eMs)
  if a and b and a == a and b == b then
    return math.abs(b - a)
  end
  return nil
end

local function forwardDelta(s0, s1)
  local d = (s1 - s0) % 1
  if d < 0 then d = d + 1 end
  return d
end

local function nearestFrameInWindow(trace, s0, s1)
  if type(trace) ~= "table" or #trace == 0 then
    return nil
  end
  local span = forwardDelta(s0, s1)
  if span <= 1e-6 then
    return nil
  end
  local exitLen = math.min(span * CORNER_EXIT_FRAC, CORNER_EXIT_MAX_SPLINE)
  local target = (s0 + exitLen) % 1
  local best, bestD
  for i = 1, #trace do
    local frame = trace[i]
    local sp = tonumber(frame and frame.spline)
    if sp and sp == sp then
      local fromStart = forwardDelta(s0, sp)
      if fromStart <= span + 1e-6 then
        local d = math.abs(sp - target)
        if d > 0.5 then d = 1 - d end
        if bestD == nil or d < bestD then
          best = frame
          bestD = d
        end
      end
    end
  end
  return best
end

local function learnCornerExitGears(trace, segments)
  local out = {}
  if type(segments) ~= "table" then
    return out
  end
  for i = 1, #segments do
    local seg = segments[i]
    if type(seg) == "table" and seg.kind == "corner" and type(seg.label) == "string" then
      local s0 = tonumber(seg.s0)
      local s1 = tonumber(seg.s1)
      if s0 and s1 then
        local frame = nearestFrameInWindow(trace, s0, s1)
        local g = frame and roundedGear(frame.gear)
        if g then
          out[seg.label] = g
        end
      end
    end
  end
  return out
end

---@param trace table[]|nil
---@param segments table[]|nil
---@param opts table|nil
---@return table
function M.learnFromReferenceTrace(trace, segments, opts)
  local buckets = {}
  local transitions = 0
  if type(trace) == "table" then
    local lastActive = nil
    local neutralWindow = nil
    for i = 1, #trace do
      local cur = trace[i]
      local curGear = roundedGear(cur and cur.gear)
      if curGear then
        if lastActive and curGear == lastActive.gear + 1 then
          local gas = maxThrottle(lastActive.frame, neutralWindow, cur)
          local elapsed = elapsedMs(lastActive.frame, cur)
          if gas >= MIN_SHIFT_GAS and (elapsed == nil or elapsed <= MAX_SHIFT_WINDOW_MS) then
            local rpm = transitionRpm(lastActive.frame, neutralWindow, cur)
            if rpm then
              buckets[lastActive.gear] = buckets[lastActive.gear] or {}
              buckets[lastActive.gear][#buckets[lastActive.gear] + 1] = rpm
              transitions = transitions + 1
            end
          end
        end
        lastActive = { gear = curGear, frame = cur }
        neutralWindow = nil
      elseif lastActive then
        neutralWindow = mergeShiftWindow(neutralWindow, cur)
      end
    end
  end

  local byGear = {}
  local all = {}
  local gearCount = 0
  for gear, values in pairs(buckets) do
    local rpm = median(values)
    if rpm then
      byGear[gear] = math.floor(rpm + 0.5)
      all[#all + 1] = rpm
      gearCount = gearCount + 1
    end
  end

  local defaultRpm = median(all)
  local cornerExitGears = learnCornerExitGears(trace, segments)
  local cornerCount = 0
  for _ in pairs(cornerExitGears) do
    cornerCount = cornerCount + 1
  end

  local profile = {
    source = (opts and opts.source) or "reference",
    byGear = byGear,
    defaultRpm = defaultRpm and math.floor(defaultRpm + 0.5) or nil,
    transitions = transitions,
    learnedGearCount = gearCount,
    cornerExitGears = cornerExitGears,
    cornerExitGearCount = cornerCount,
  }
  profile.hasLearnedShift = profile.defaultRpm ~= nil
  return profile
end

---@param profile table|nil
---@param gear any
---@param rpmLimiter any
---@return number|nil targetRpm, number zonePct, string provenance
function M.resolveShiftTarget(profile, gear, rpmLimiter)
  local limiter = tonumber(rpmLimiter)
  local g = roundedGear(gear)
  local target = nil
  if type(profile) == "table" and profile.hasLearnedShift then
    if g and type(profile.byGear) == "table" then
      target = tonumber(profile.byGear[g])
    end
    target = target or tonumber(profile.defaultRpm)
  end

  if target and limiter and limiter > 0 then
    target = clamp(target, limiter * 0.50, limiter * 0.99)
    return target, target / limiter, "learned"
  end
  if target then
    return target, DEFAULT_SHIFT_ZONE_FRAC, "learned"
  end
  if limiter and limiter > 0 then
    return limiter * DEFAULT_SHIFT_ZONE_FRAC, DEFAULT_SHIFT_ZONE_FRAC, "heuristic"
  end
  return nil, DEFAULT_SHIFT_ZONE_FRAC, "heuristic"
end

function M.redZonePctFor(shiftZonePct)
  local z = tonumber(shiftZonePct) or DEFAULT_SHIFT_ZONE_FRAC
  return clamp(math.max(DEFAULT_REDLINE_FRAC, z + 0.04), 0, 0.995)
end

function M.statsLine(profile)
  if type(profile) == "table" and profile.hasLearnedShift then
    local src = tostring(profile.source or "reference")
    local gears = tonumber(profile.learnedGearCount) or 0
    local rpm = tonumber(profile.defaultRpm) or 0
    local corners = tonumber(profile.cornerExitGearCount) or 0
    return string.format(
      "Shift points: learned from %s (%d gear%s, median %.0f rpm, %d corner exit gear%s)",
      src,
      gears,
      gears == 1 and "" or "s",
      rpm,
      corners,
      corners == 1 and "" or "s")
  end
  return string.format("Shift points: heuristic %.0f%% of rev limiter", DEFAULT_SHIFT_ZONE_FRAC * 100)
end

return M
