-- Throttle application after braking, coasting, sawtooth / smoothness heuristics, full-throttle %.

local M = {}

---@class ThrottleDetectState
---@field wasBraking boolean
---@field inCoast boolean
---@field coastStreak number

local Detector = {}
Detector.__index = Detector

function M.new()
  return setmetatable({
    wasBraking = false,
    inCoast = false,
    coastStreak = 0,
  }, Detector)
end

---@param car ac.StateCar
---@param dt number
---@return boolean inCoastingNow
---@return number coastStreakSeconds
function Detector:update(car, dt)
  local d = dt or 0
  local br = car.brake or 0
  local th = car.gas or 0
  local braking = br > 0.15
  if braking then
    self.wasBraking = true
  end
  local coast = br < 0.05 and th < 0.1
  if coast then
    self.coastStreak = self.coastStreak + d
    self.inCoast = true
  else
    self.coastStreak = 0
    self.inCoast = false
  end
  -- throttle apply after braking (state only; lap-level metrics use analyzeTrace)
  if self.wasBraking and not braking and th > 0.25 then
    self.wasBraking = false
  end
  if not braking and th > 0.25 then
    self.wasBraking = false
  end
  return coast, self.coastStreak
end

function Detector:resetLapAggregates()
  self.coastStreak = 0
  self.inCoast = false
end

---@param trace { throttle: number, brake: number }[]|nil
---@return table|nil
function M.analyzeTrace(trace)
  if not trace or #trace < 2 then
    return nil
  end
  local wasBraking = false
  local applyEvents = 0
  local coastMs = 0
  local inCoast = false
  local coastStart = 0
  local reversals = 0
  local lastTh = trace[1].throttle or 0
  local prevDth = nil
  local derivSum = 0
  local ft = 0
  local n = #trace
  local dtEst = (trace[n].eMs - trace[1].eMs) / math.max(1, n - 1) / 1000
  for i = 1, n do
    local s = trace[i]
    local th = s.throttle or 0
    local br = s.brake or 0
    if th > 0.9 then
      ft = ft + 1
    end
    local braking = br > 0.15
    if braking then
      wasBraking = true
    end
    if wasBraking and not braking and th > 0.25 then
      applyEvents = applyEvents + 1
      wasBraking = false
    end
    if not braking and th > 0.25 then
      wasBraking = false
    end
    local coast = br < 0.05 and th < 0.1
    if coast then
      if not inCoast then
        inCoast = true
        coastStart = s.eMs
      end
    else
      if inCoast then
        coastMs = coastMs + (s.eMs - coastStart)
        inCoast = false
      end
    end
    if i > 1 then
      local dth = th - lastTh
      derivSum = derivSum + math.abs(dth)
      if prevDth ~= nil and dth * prevDth < 0 and math.abs(dth) > 0.05 then
        reversals = reversals + 1
      end
      prevDth = dth
    end
    lastTh = th
  end
  if inCoast then
    coastMs = coastMs + (trace[n].eMs - coastStart)
  end
  local ftPct = n > 0 and (100 * ft / n) or 0
  local smooth = (derivSum / math.max(1, n - 1))
  return {
    applyEvents = applyEvents,
    coastingMs = coastMs,
    reversals = reversals,
    fullThrottlePct = ftPct,
    smoothness = smooth,
    dtEst = dtEst,
  }
end

return M
