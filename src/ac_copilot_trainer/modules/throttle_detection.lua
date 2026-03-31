-- Throttle application after braking, coasting, sawtooth / smoothness heuristics, full-throttle %.

local M = {}

---@class ThrottleDetectState
---@field inCoast boolean
---@field coastStreak number

local Detector = {}
Detector.__index = Detector

function M.new()
  return setmetatable({
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
  local coast = br < 0.05 and th < 0.1
  if coast then
    self.coastStreak = self.coastStreak + d
    self.inCoast = true
  else
    self.coastStreak = 0
    self.inCoast = false
  end
  return coast, self.coastStreak
end

function Detector:resetLapAggregates()
  self.coastStreak = 0
  self.inCoast = false
end

---@param trace { throttle: number, brake: number, eMs: number }[]|nil
---@return table|nil
function M.analyzeTrace(trace)
  if not trace or #trace < 2 then
    return nil
  end
  local n0 = #trace
  for i = 1, n0 do
    local row = trace[i]
    if type(row) ~= "table" or type(row.eMs) ~= "number" then
      return nil
    end
    if i > 1 and row.eMs < trace[i - 1].eMs then
      return nil
    end
  end
  local wasBraking = false
  local applyEvents = 0
  local coastMs = 0
  local inCoast = false
  local coastStart = 0
  local reversals = 0
  local lastTh = trace[1].throttle or 0
  local prevRate = nil ---@type number|nil
  local derivSum = 0
  local rateSegs = 0
  local ftMs = 0
  local n = #trace
  local dtEst = (trace[n].eMs - trace[1].eMs) / math.max(1, n - 1) / 1000
  --- ~0.05 throttle delta per ~16.7 ms ≈ 3/s; scale reversals with sample spacing.
  local reversalRateMin = 0.05 / math.max(dtEst, 1e-4)
  for i = 1, n do
    local s = trace[i]
    local th = s.throttle or 0
    local br = s.brake or 0
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
      local prev = trace[i - 1]
      local dtMs = (s.eMs - prev.eMs)
      if dtMs > 0 and th > 0.9 then
        ftMs = ftMs + dtMs
      end
      local dtSec = dtMs / 1000
      if dtSec > 1e-9 then
        local dth = th - lastTh
        local rate = dth / dtSec
        derivSum = derivSum + math.abs(rate)
        if prevRate ~= nil and rate * prevRate < 0 and math.abs(rate) > reversalRateMin then
          reversals = reversals + 1
        end
        prevRate = rate
        rateSegs = rateSegs + 1
      end
    end
    lastTh = th
  end
  if inCoast then
    coastMs = coastMs + (trace[n].eMs - coastStart)
  end
  local lapMs = math.max(1, trace[n].eMs - trace[1].eMs)
  local ftPct = 100 * ftMs / lapMs
  local smooth = derivSum / math.max(1, rateSegs)
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
