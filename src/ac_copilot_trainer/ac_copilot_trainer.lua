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

local tel = telemetryMod.new({ bufferSeconds = config.bufferSeconds })
local brakes = brakeMod.new({
  brakeThreshold = config.brakeThreshold,
  brakeDurationMin = config.brakeDurationMin,
})

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
}

local function applyLoaded(data)
  if not data or type(data) ~= "table" then
    return
  end
  if data.bestLapMs and tonumber(data.bestLapMs) then
    state.bestLapMs = tonumber(data.bestLapMs)
  end
  if data.bestBrakePoints and type(data.bestBrakePoints) == "table" then
    state.brakingPoints.best = data.bestBrakePoints
  end
end

local function persistSnapshot()
  car = ac.getCar(0)
  sim = ac.getSim()
  if sim.isInMainMenu or not car then
    return
  end
  persistence.save(car, sim, {
    bestLapMs = state.bestLapMs,
    bestBrakePoints = state.brakingPoints.best,
  })
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
  hud.draw({
    recording = state.recording,
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
      persistSnapshot()
    end
    state.wasDriving = false
    state.lastLapCount = -1
    return
  end

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
  if state.lastLapCount >= 0 and lc > state.lastLapCount then
    local lastMs = car.previousLapTimeMs or car.lastLapTimeMs or 0
    state.lastLapMs = lastMs > 0 and lastMs or state.lastLapMs
    if lastMs > 0 and (state.bestLapMs == nil or lastMs <= state.bestLapMs) then
      state.bestLapMs = lastMs
      state.brakingPoints.best = copyBpList(state.brakingPoints.session)
      persistSnapshot()
    end
    state.brakingPoints.last = copyBpList(state.brakingPoints.session)
    state.brakingPoints.session = {}
  end
  state.lastLapCount = lc
end

function script.onWindowHide()
  persistSnapshot()
end

function script.draw3D(dt)
  local s = ac.getSim()
  if not s or s.isInMainMenu then
    return
  end
  -- Phase 1 follow-up: render brake markers from state.brakingPoints
end
