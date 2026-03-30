-- AC Copilot Trainer v0.1.0
-- https://github.com/agorokh/ac-copilot-trainer
-- Issue #6: telemetry, brake detection, persistence, lap-aware brake sets.

do
  local origin = ac.getFolder(ac.FolderID.ScriptOrigin)
  if origin and origin ~= "" then
    package.path = origin .. "/modules/?.lua;" .. package.path
  end
end

local telemetryMod = require("telemetry")
local brakeMod = require("brake_detection")
local persistence = require("persistence")
local hud = require("hud")

local sim ---@type ac.StateSim
local car ---@type ac.StateCar

local config = {
  brakeThreshold = 0.3,
  brakeDurationMin = 0.5,
  bufferSeconds = 30,
  hudEnabled = true,
}

local function newTelemetry()
  return telemetryMod.new({ bufferSeconds = config.bufferSeconds })
end

local function newBrakes()
  return brakeMod.new({
    brakeThreshold = config.brakeThreshold,
    brakeDurationMin = config.brakeDurationMin,
  })
end

local tel = newTelemetry()
local brakes = newBrakes()

--- Last valid driving-frame refs for persistence when sim is already on main menu.
local lastDriveCar ---@type ac.StateCar|nil
local lastDriveSim ---@type ac.StateSim|nil

local function copyBpList(list)
  local out = {}
  for i = 1, #list do
    local e = list[i]
    out[i] = {
      spline = e.spline,
      px = e.px,
      py = e.py,
      pz = e.pz,
      entrySpeed = e.entrySpeed,
      heading = e.heading,
    }
  end
  return out
end

local state = {
  initialized = false,
  bestLapMs = nil,
  lastLapMs = nil,
  lastLapCount = -1,
  wasDriving = false,
  brakingPoints = {
    best = {},
    last = {},
    session = {},
  },
  recording = true,
  ---@type number|nil
  lastSplinePos = nil,
}

local function applyLoaded(data)
  if not data or type(data) ~= "table" then
    return
  end
  local bestMs = tonumber(data.bestLapMs)
  if bestMs and bestMs > 0 then
    state.bestLapMs = bestMs
  end
  if data.bestBrakePoints and type(data.bestBrakePoints) == "table" then
    state.brakingPoints.best = data.bestBrakePoints
  end
end

local function persistPayload()
  return {
    bestLapMs = state.bestLapMs,
    bestBrakePoints = state.brakingPoints.best,
  }
end

--- Save while still in-session (uses car/sim from current frame; no re-fetch).
---@return boolean
local function persistSnapshotLive()
  if not sim or sim.isInMainMenu or not car then
    return false
  end
  return persistence.save(car, sim, persistPayload()) == true
end

--- Save using last driving frame (exit to menu / window hide).
---@return boolean
local function persistSnapshotCached()
  local c, s = lastDriveCar, lastDriveSim
  if not c or not s then
    return false
  end
  return persistence.save(c, s, persistPayload()) == true
end

local function resetRuntimeAfterLeavingTrack()
  state.initialized = false
  state.bestLapMs = nil
  state.lastLapMs = nil
  state.lastLapCount = -1
  state.brakingPoints = {
    best = {},
    last = {},
    session = {},
  }
  tel = newTelemetry()
  brakes = newBrakes()
  lastDriveCar = nil
  lastDriveSim = nil
  state.lastSplinePos = nil
end

local function resetRollingDrivingState()
  state.brakingPoints.session = {}
  tel = newTelemetry()
  brakes = newBrakes()
end

local function tryLoadDisk()
  car = ac.getCar(0)
  sim = ac.getSim()
  if sim.isInMainMenu or not car then
    return
  end
  applyLoaded(persistence.load(car, sim))
  state.initialized = true
end

function script.windowMain(dt)
  if not config.hudEnabled then
    return
  end
  sim = ac.getSim()
  car = ac.getCar(0)
  if sim.isInMainMenu then
    ui.text("AC Copilot Trainer v0.1.0")
    ui.separator()
    ui.text("Waiting for session...")
    return
  end
  if not car then
    ui.text("AC Copilot Trainer v0.1.0")
    ui.separator()
    ui.text("Waiting for car data...")
    return
  end
  hud.draw({
    recording = tel:isRecording(),
    telemetrySamples = tel:sampleCount(),
    speed = car.speedKmh or 0,
    brake = car.brake or 0,
    lapCount = car.lapCount or 0,
    bestLapMs = state.bestLapMs or (car.bestLapTimeMs or nil),
    lastLapMs = state.lastLapMs or (car.previousLapTimeMs or nil),
    brakeBest = #state.brakingPoints.best,
    brakeLast = #state.brakingPoints.last,
    brakeSession = #state.brakingPoints.session,
  })
end

function script.update(dt)
  sim = ac.getSim()
  car = ac.getCar(0)

  if sim.isInMainMenu then
    if state.wasDriving then
      if persistSnapshotCached() then
        resetRuntimeAfterLeavingTrack()
        state.wasDriving = false
      end
    else
      state.wasDriving = false
    end
    state.lastLapCount = -1
    return
  end

  if not car then
    return
  end

  lastDriveCar = car
  lastDriveSim = sim
  state.wasDriving = true

  if not state.initialized then
    tryLoadDisk()
  end

  tel:setRecording(state.recording)
  tel:update(dt, car, sim)

  local ev = brakes:update(car, dt)
  if ev then
    state.brakingPoints.session[#state.brakingPoints.session + 1] = ev
  end

  local lc = car.lapCount or 0
  local sp = car.splinePosition or 0
  if state.lastLapCount >= 0 and lc < state.lastLapCount then
    resetRollingDrivingState()
  elseif state.lastLapCount >= 0 and lc == state.lastLapCount and state.lastSplinePos then
    local lastSp = state.lastSplinePos
    local d = sp - lastSp
    local likelyWrap = lastSp > 0.8 and sp < 0.25
    if d < -0.2 and not likelyWrap then
      resetRollingDrivingState()
    end
  end

  if state.lastLapCount >= 0 and lc > state.lastLapCount then
    local evLap = brakes:finalizeQualifiedWhileHolding(car)
    if evLap then
      state.brakingPoints.session[#state.brakingPoints.session + 1] = evLap
    end
    local lastMs = car.previousLapTimeMs or car.lastLapTimeMs or 0
    state.lastLapMs = lastMs > 0 and lastMs or state.lastLapMs
    if lastMs > 0 and (state.bestLapMs == nil or lastMs <= state.bestLapMs) then
      state.bestLapMs = lastMs
      state.brakingPoints.best = copyBpList(state.brakingPoints.session)
      local _persistPb = persistSnapshotLive() or persistSnapshotLive()
    end
    state.brakingPoints.last = copyBpList(state.brakingPoints.session)
    state.brakingPoints.session = {}
  end
  state.lastLapCount = lc
  state.lastSplinePos = sp
end

function script.onWindowHide()
  local _persistHide = persistSnapshotCached() or persistSnapshotCached()
end

function script.draw3D(dt)
  local s = ac.getSim()
  if not s or s.isInMainMenu then
    return
  end
  -- Phase 1 follow-up: render brake markers from state.brakingPoints
end
