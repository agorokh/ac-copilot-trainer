-- Rolling telemetry buffer (speed, inputs, spline, world position).

local M = {}

--- Hard cap so a broken sim clock cannot grow memory without bound.
local MAX_SAMPLES_SAFETY = 50000

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

local Telemetry = {}
Telemetry.__index = Telemetry

---@param cfg TelemetryConfig|nil
function M.new(cfg)
  cfg = cfg or {}
  local bufferSeconds = cfg.bufferSeconds or 30
  return setmetatable({
    bufferSeconds = bufferSeconds,
    samples = {},
    n = 0,
    recording = true,
  }, Telemetry)
end

function Telemetry:setRecording(on)
  self.recording = on and true or false
end

function Telemetry:isRecording()
  return self.recording
end

--- Current number of retained samples (post-eviction), O(1).
function Telemetry:sampleCount()
  return self.n
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
  local steer = 0
  if car.steer ~= nil then
    steer = car.steer
  elseif car.steering ~= nil then
    steer = car.steering
  end
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
