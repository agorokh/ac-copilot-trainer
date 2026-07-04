-- Rolling telemetry buffer plus per-lap trace (downsampled on finalize, max ~2000 samples).

local ch = require("csp_helpers")
local wheel_read = require("wheel_read")
local chassis_read = require("chassis_read")

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
---@field rpm number
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
---@field rpm number
---@field px number
---@field py number
---@field pz number
---@field wheelAngularSpeed_fl number|nil
---@field wheelAngularSpeed_fr number|nil
---@field wheelAngularSpeed_rl number|nil
---@field wheelAngularSpeed_rr number|nil
---@field wheelSlip_fl number|nil
---@field wheelSlip_fr number|nil
---@field wheelSlip_rl number|nil
---@field wheelSlip_rr number|nil
---@field tyreCoreTemp_fl number|nil
---@field tyreCoreTemp_fr number|nil
---@field tyreCoreTemp_rl number|nil
---@field tyreCoreTemp_rr number|nil
---@field accG_long number|nil
---@field accG_lat number|nil
---@field yaw_rate number|nil
---@field wheelsPressure_fl number|nil
---@field wheelsPressure_fr number|nil
---@field wheelsPressure_rl number|nil
---@field wheelsPressure_rr number|nil
--- issue #490 Tier-1 base-AC dynamic channels (per-wheel FL/FR/RL/RR unless noted; scalars at end)
---@field tyreTempInner_fl number|nil
---@field tyreTempInner_fr number|nil
---@field tyreTempInner_rl number|nil
---@field tyreTempInner_rr number|nil
---@field tyreTempMid_fl number|nil
---@field tyreTempMid_fr number|nil
---@field tyreTempMid_rl number|nil
---@field tyreTempMid_rr number|nil
---@field tyreTempOuter_fl number|nil
---@field tyreTempOuter_fr number|nil
---@field tyreTempOuter_rl number|nil
---@field tyreTempOuter_rr number|nil
---@field brakeTemp_fl number|nil
---@field brakeTemp_fr number|nil
---@field brakeTemp_rl number|nil
---@field brakeTemp_rr number|nil
---@field wheelLoad_fl number|nil
---@field wheelLoad_fr number|nil
---@field wheelLoad_rl number|nil
---@field wheelLoad_rr number|nil
---@field tyreWear_fl number|nil
---@field tyreWear_fr number|nil
---@field tyreWear_rl number|nil
---@field tyreWear_rr number|nil
---@field tyreDirty_fl number|nil
---@field tyreDirty_fr number|nil
---@field tyreDirty_rl number|nil
---@field tyreDirty_rr number|nil
---@field camber_fl number|nil
---@field camber_fr number|nil
---@field camber_rl number|nil
---@field camber_rr number|nil
---@field suspTravel_fl number|nil
---@field suspTravel_fr number|nil
---@field suspTravel_rl number|nil
---@field suspTravel_rr number|nil
---@field damperVel_fl number|nil
---@field damperVel_fr number|nil
---@field damperVel_rl number|nil
---@field damperVel_rr number|nil
---@field rideHeightFront number|nil
---@field rideHeightRear number|nil
---@field brakeBias number|nil
---@field turboBoost number|nil
---@field fuel number|nil
---@field accG_vert number|nil

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
    -- issue #490 damper-velocity carry-over (prev suspensionTravel + sim time for the d/dt derive)
    _damperPrevT = nil,
    _damperPrevTravel = nil,
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
  local t = ch.simSeconds(sim)
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
  local rpm = tonumber(car.rpm) or 0
  ---@type TelemetrySample
  local s = {
    t = t,
    speed = car.speedKmh or 0,
    brake = car.brake or 0,
    throttle = car.gas or 0,
    steering = steer,
    gear = gear,
    rpm = rpm,
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
    -- Per-wheel channels (issue #266): angular speed is the canonical longitudinal signal the
    -- analysis layer derives slip from (which axle locks / exit wheelspin); slip + tyre core temp
    -- ride along for the tyre model. nil reads serialize as 0 via traceSampleToColumnRow; the
    -- Python loader treats an all-zero omega column as "no live wheel data" so it never confirms a
    -- false lockup when wheels are unreadable.
    local w = wheel_read.readPerWheel(car)
    -- Chassis dynamics (issue #478): measured g-forces (accG, in G) + yaw rate (rad/s) confirm the
    -- balance/rotation rules; dynamic hot tyre pressure (per wheel) confirms the pressure rule. nil
    -- reads serialize as 0 via traceSampleToColumnRow; the analysis layer treats an all-zero column
    -- as "no live data" so an unreadable field never fabricates a verdict.
    local chassis = chassis_read.read(car)
    -- Damper velocity (m/s) = d(suspensionTravel)/dt per wheel, derived from the previous lap
    -- sample's travel + the sim-time delta (issue #490). First sample, an unreadable wheel, or a
    -- non-positive dt (e.g. the lap boundary where eMs resets) yields 0. Uses monotonic sim time
    -- `t` (not per-lap eMs) so it stays correct across laps.
    local damperVel = { fl = 0, fr = 0, rl = 0, rr = 0 }
    local prevT, prevTravel = self._damperPrevT, self._damperPrevTravel
    if prevT ~= nil and prevTravel ~= nil then
      local dt = t - prevT
      if dt > 1e-6 then
        for wk in pairs(damperVel) do
          local cur, prv = w.suspTravel[wk], prevTravel[wk]
          if cur ~= nil and prv ~= nil then
            damperVel[wk] = (cur - prv) / dt
          end
        end
      end
    end
    self._damperPrevT = t
    self._damperPrevTravel = w.suspTravel
    ---@type LapTraceSample
    local lp = {
      spline = car.splinePosition or 0,
      eMs = eMs,
      speed = s.speed,
      brake = s.brake,
      throttle = s.throttle,
      steer = steer,
      gear = s.gear,
      rpm = s.rpm,
      px = px,
      py = py,
      pz = pz,
      wheelAngularSpeed_fl = w.omega.fl,
      wheelAngularSpeed_fr = w.omega.fr,
      wheelAngularSpeed_rl = w.omega.rl,
      wheelAngularSpeed_rr = w.omega.rr,
      wheelSlip_fl = w.slip.fl,
      wheelSlip_fr = w.slip.fr,
      wheelSlip_rl = w.slip.rl,
      wheelSlip_rr = w.slip.rr,
      tyreCoreTemp_fl = w.temp.fl,
      tyreCoreTemp_fr = w.temp.fr,
      tyreCoreTemp_rl = w.temp.rl,
      tyreCoreTemp_rr = w.temp.rr,
      accG_long = chassis.accG_long,
      accG_lat = chassis.accG_lat,
      yaw_rate = chassis.yaw_rate,
      wheelsPressure_fl = w.pressure.fl,
      wheelsPressure_fr = w.pressure.fr,
      wheelsPressure_rl = w.pressure.rl,
      wheelsPressure_rr = w.pressure.rr,
      -- issue #490 Tier-1 base-AC dynamic channels (per-wheel), read via wheel_read/chassis_read
      tyreTempInner_fl = w.tyreTempInner.fl,
      tyreTempInner_fr = w.tyreTempInner.fr,
      tyreTempInner_rl = w.tyreTempInner.rl,
      tyreTempInner_rr = w.tyreTempInner.rr,
      tyreTempMid_fl = w.tyreTempMid.fl,
      tyreTempMid_fr = w.tyreTempMid.fr,
      tyreTempMid_rl = w.tyreTempMid.rl,
      tyreTempMid_rr = w.tyreTempMid.rr,
      tyreTempOuter_fl = w.tyreTempOuter.fl,
      tyreTempOuter_fr = w.tyreTempOuter.fr,
      tyreTempOuter_rl = w.tyreTempOuter.rl,
      tyreTempOuter_rr = w.tyreTempOuter.rr,
      brakeTemp_fl = w.brakeTemp.fl,
      brakeTemp_fr = w.brakeTemp.fr,
      brakeTemp_rl = w.brakeTemp.rl,
      brakeTemp_rr = w.brakeTemp.rr,
      wheelLoad_fl = w.load.fl,
      wheelLoad_fr = w.load.fr,
      wheelLoad_rl = w.load.rl,
      wheelLoad_rr = w.load.rr,
      tyreWear_fl = w.wear.fl,
      tyreWear_fr = w.wear.fr,
      tyreWear_rl = w.wear.rl,
      tyreWear_rr = w.wear.rr,
      tyreDirty_fl = w.dirty.fl,
      tyreDirty_fr = w.dirty.fr,
      tyreDirty_rl = w.dirty.rl,
      tyreDirty_rr = w.dirty.rr,
      camber_fl = w.camber.fl,
      camber_fr = w.camber.fr,
      camber_rl = w.camber.rl,
      camber_rr = w.camber.rr,
      suspTravel_fl = w.suspTravel.fl,
      suspTravel_fr = w.suspTravel.fr,
      suspTravel_rl = w.suspTravel.rl,
      suspTravel_rr = w.suspTravel.rr,
      damperVel_fl = damperVel.fl,
      damperVel_fr = damperVel.fr,
      damperVel_rl = damperVel.rl,
      damperVel_rr = damperVel.rr,
      -- issue #490 car-level scalar channels (from chassis_read)
      rideHeightFront = chassis.rideHeight_front,
      rideHeightRear = chassis.rideHeight_rear,
      brakeBias = chassis.brakeBias,
      turboBoost = chassis.turboBoost,
      fuel = chassis.fuel,
      accG_vert = chassis.accG_vert,
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
  local now = ch.simSeconds(sim)
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
