-- Rolling telemetry buffer (speed, inputs, spline, world position).

local M = {}

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
  local maxSamples = math.max(240, math.floor(bufferSeconds * 120))
  return setmetatable({
    bufferSeconds = bufferSeconds,
    maxSamples = maxSamples,
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
  if self.n > self.maxSamples then
    local drop = self.n - self.maxSamples
    for i = 1, self.n - drop do
      self.samples[i] = self.samples[i + drop]
    end
    for j = self.n - drop + 1, self.n do
      self.samples[j] = nil
    end
    self.n = self.n - drop
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
