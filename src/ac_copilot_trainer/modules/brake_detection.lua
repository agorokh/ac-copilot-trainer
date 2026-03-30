-- Brake point detection: brake > threshold continuously for min duration.

local M = {}

---@class BrakeDetectConfig
---@field brakeThreshold number|nil
---@field brakeDurationMin number|nil

---@class BrakeEvent
---@field spline number
---@field px number
---@field py number
---@field pz number
---@field entrySpeed number
---@field heading number

local Detector = {}
Detector.__index = Detector

local function flatHeading(car)
  if car.look then
    return math.atan2(car.look.x, car.look.z)
  end
  if car.velocity and (car.velocity.x ~= 0 or car.velocity.z ~= 0) then
    return math.atan2(car.velocity.x, car.velocity.z)
  end
  return 0
end

---@param cfg BrakeDetectConfig|nil
function M.new(cfg)
  cfg = cfg or {}
  return setmetatable({
    brakeThreshold = cfg.brakeThreshold or 0.3,
    brakeDurationMin = cfg.brakeDurationMin or 0.5,
    braking = false,
    holdT = 0,
    startSpeed = 0,
    startSpline = 0,
    startPx = 0,
    startPy = 0,
    startPz = 0,
    startHeading = 0,
    qualified = false,
  }, Detector)
end

---@param car ac.StateCar
---@param dt number
---@return BrakeEvent|nil
function Detector:update(car, dt)
  local d = dt or 0
  local b = car.brake or 0
  if b > self.brakeThreshold then
    if not self.braking then
      self.braking = true
      self.holdT = 0
      self.startSpeed = car.speedKmh or 0
      self.startSpline = car.splinePosition or 0
      if car.position then
        self.startPx = car.position.x
        self.startPy = car.position.y
        self.startPz = car.position.z
      else
        self.startPx, self.startPy, self.startPz = 0, 0, 0
      end
      self.startHeading = flatHeading(car)
      self.qualified = false
    end
    self.holdT = self.holdT + d
    if not self.qualified and self.holdT >= self.brakeDurationMin then
      self.qualified = true
    end
    return nil
  end
  self.braking = false
  self.holdT = 0
  if self.qualified then
    self.qualified = false
    return {
      spline = self.startSpline,
      px = self.startPx,
      py = self.startPy,
      pz = self.startPz,
      entrySpeed = self.startSpeed,
      heading = self.startHeading,
    }
  end
  return nil
end

--- If the driver is still holding brake but the hold already qualified, emit the
--- brake point now (e.g. lap boundary) and re-seed the start snapshot for the
--- continued press so the next lap does not lose the event.
---@param car ac.StateCar
---@return BrakeEvent|nil
function Detector:finalizeQualifiedWhileHolding(car)
  if not (self.braking and self.qualified) then
    return nil
  end
  local ev = {
    spline = self.startSpline,
    px = self.startPx,
    py = self.startPy,
    pz = self.startPz,
    entrySpeed = self.startSpeed,
    heading = self.startHeading,
  }
  self.holdT = 0
  self.qualified = false
  self.startSpeed = car.speedKmh or 0
  self.startSpline = car.splinePosition or 0
  if car.position then
    self.startPx = car.position.x
    self.startPy = car.position.y
    self.startPz = car.position.z
  else
    self.startPx, self.startPy, self.startPz = 0, 0, 0
  end
  self.startHeading = flatHeading(car)
  return ev
end

return M
