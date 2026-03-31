-- Rolling telemetry buffer plus per-lap trace (downsampled on finalize, max ~2000 samples).

local M = {}

--- Hard cap so a broken sim clock cannot grow memory without bound.
local MAX_SAMPLES_SAFETY = 50000
--- Raw lap samples cap before finalize downsample (long hotlaps at high FPS).
local MAX_LAP_RAW = 24000
--- Stored / comparison trace length (issue #7 guardrail).
local MAX_LAP_TRACE = 2000

---@class TelemetryConfig
---@field bufferSeconds number|nil

---@class TelemetrySample
---@field t number
---@field speed number
---@field brake number
---@field throttle number
---@field steering number
---@field gear integer
---@field spline number
---@field px number
---@field py number
---@field pz number

---@class LapTraceSample
---@field spline number
---@field eMs number
---@field speed number
---@field brake number
---@field throttle number
---@field steer number
---@field gear integer
---@field px number
---@field py number
---@field pz number

local Telemetry = {}
Telemetry.__index = Telemetry

local function downsampleUniform(buf, n, maxOut)
  if n <= maxOut then
    local out = {}
    for i = 1, n do
      out[i] = buf[i]
    end
    return out, n
  end
  local out = {}
  out[1] = buf[1]
  if maxOut == 1 then
    return out, 1
  end
  out[maxOut] = buf[n]
  if maxOut == 2 then
    return out, 2
  end
  local step = (n - 1) / (maxOut - 1)
  for k = 2, maxOut - 1 do
    local pos = 1 + (k - 1) * step
    local idx = math.min(n, math.max(1, math.floor(pos + 0.5)))
    out[k] = buf[idx]
  end
  return out, maxOut
end

---@param cfg TelemetryConfig|nil
function M.new(cfg)
  cfg = cfg or {}
  local bufferSeconds = cfg.bufferSeconds or 30
  return setmetatable({
    bufferSeconds = bufferSeconds,
    samples = {},
    n = 0,
    recording = true,
    lapBuf = {},
    lapN = 0,
    lapT0 = nil,
  }, Telemetry)
end

function Telemetry:setRecording(on)
  self.recording = on and true or false
end

function Telemetry:isRecording()
  return self.recording
end

--- Current number of retained rolling-buffer samples (post-eviction), O(1).
function Telemetry:sampleCount()
  return self.n
end

--- Sim time (seconds) when the current lap trace started; nil until first lap clock set.
function Telemetry:lapStartTime()
  return self.lapT0
end

--- Begin a new lap trace clock (call on lap boundary or session start).
---@param simTime number
function Telemetry:beginLapClock(simTime)
  self.lapT0 = simTime
  self.lapBuf = {}
  self.lapN = 0
end

--- Drop samples older than (now - bufferSeconds).
function Telemetry:evictOlderThan(tCutoff)
  local i = 1
  while i <= self.n and self.samples[i] and self.samples[i].t < tCutoff do
    i = i + 1
  end
  if i > 1 then
    local newN = self.n - i + 1
    for j = 1, newN do
      self.samples[j] = self.samples[j + i - 1]
    end
    for j = newN + 1, self.n do
      self.samples[j] = nil
    end
    self.n = newN
  end
end

---@param car ac.StateCar
---@param sim ac.StateSim
function Telemetry:update(dt, car, sim)
  if not self.recording or sim.isInMainMenu then
    return
  end
  local t = sim.time or 0
  -- car.steer is a valid ac.StateCar field (confirmed from CMRT-Essential-HUD).
  -- car.steering does NOT exist on the C-struct and would throw — removed.
  local steer = car.steer or 0
  local px, py, pz = 0, 0, 0
  if car.position then
    px, py, pz = car.position.x, car.position.y, car.position.z
  end
  local gear = 0
  if car.gear ~= nil then
    gear = math.floor(tonumber(car.gear) or 0)
  end
  ---@type TelemetrySample
  local s = {
    t = t,
    speed = car.speedKmh or 0,
    brake = car.brake or 0,
    throttle = car.gas or 0,
    steering = steer,
    gear = gear,
    spline = car.splinePosition or 0,
    px = px,
    py = py,
    pz = pz,
  }
  self.n = self.n + 1
  self.samples[self.n] = s
  self:evictOlderThan(t - self.bufferSeconds)
  while self.n > MAX_SAMPLES_SAFETY do
    for j = 1, self.n - 1 do
      self.samples[j] = self.samples[j + 1]
    end
    self.samples[self.n] = nil
    self.n = self.n - 1
  end

  -- Lap trace (separate from rolling window)
  if self.lapT0 ~= nil then
    local eMs = (t - self.lapT0) * 1000
    self.lapN = self.lapN + 1
    ---@type LapTraceSample
    local lp = {
      spline = car.splinePosition or 0,
      eMs = eMs,
      speed = s.speed,
      brake = s.brake,
      throttle = s.throttle,
      steer = steer,
      gear = s.gear,
      px = px,
      py = py,
      pz = pz,
    }
    self.lapBuf[self.lapN] = lp
    if self.lapN > MAX_LAP_RAW then
      local tmp, newN = downsampleUniform(self.lapBuf, self.lapN, math.floor(MAX_LAP_RAW / 2))
      self.lapBuf = tmp
      self.lapN = newN
    end
  end
end

--- Finalize the just-finished lap: downsample to MAX_LAP_TRACE, clear lap buffer, return trace.
--- Caller should call beginLapClock(simTime) for the next lap immediately after.
---@return LapTraceSample[]
function Telemetry:finalizeLapTrace()
  if self.lapN <= 0 then
    self.lapBuf = {}
    self.lapN = 0
    return {}
  end
  local out = downsampleUniform(self.lapBuf, self.lapN, MAX_LAP_TRACE)
  self.lapBuf = {}
  self.lapN = 0
  return out
end

---@param sim ac.StateSim
---@return TelemetrySample[]
function Telemetry:getRecent(sim)
  local now = (sim and sim.time) or 0
  local t0 = now - self.bufferSeconds
  local out = {}
  local k = 0
  for i = 1, self.n do
    local s = self.samples[i]
    if s and s.t >= t0 then
      k = k + 1
      out[k] = s
    end
  end
  return out
end

return M
