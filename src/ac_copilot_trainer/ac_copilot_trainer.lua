-- AC Copilot Trainer v0.1.0
-- AI-powered driving trainer for Assetto Corsa
-- https://github.com/agorokh/ac-copilot-trainer

local sim = ac.getSim()
local car = ac.getCar(0)

-- App state
local state = {
  initialized = false,
  bestLap = nil,
  lastLap = nil,
  currentLapTelemetry = {},
  brakingPoints = {
    best = {},
    last = {},
    current = {}
  },
  recording = true
}

-- Configuration
local config = {
  brakeThreshold = 0.3,        -- minimum brake input to detect
  brakeDurationMin = 0.5,      -- seconds held to count as braking point
  hudEnabled = true,
  markersEnabled = true,
  markerAheadDistance = 200,    -- meters ahead to show markers
}

function script.windowMain(dt)
  ui.text("AC Copilot Trainer v0.1.0")
  ui.separator()

  if not sim.isInMainMenu then
    ui.text(string.format("Speed: %.0f km/h", car.speedKmh))
    ui.text(string.format("Brake: %.0f%%", car.brake * 100))
    ui.text(string.format("Throttle: %.0f%%", car.gas * 100))
    ui.text(string.format("Lap: %d", car.lapCount))
    ui.text(string.format("Position: %.4f", car.splinePosition))

    if state.recording then
      ui.textColored(rgbm(0, 1, 0, 1), "REC")
    end
  else
    ui.text("Waiting for session...")
  end
end

function script.update(dt)
  if sim.isInMainMenu then return end

  -- TODO: Phase 1 implementation
  -- 1. Record telemetry each frame
  -- 2. Detect braking points
  -- 3. Compare with best lap
  -- 4. Update HUD state
end

function script.draw3D(dt)
  if sim.isInMainMenu then return end

  -- TODO: Phase 1 implementation
  -- 1. Draw brake point markers on track surface
  -- 2. Color code: green = best lap, yellow = last lap
end
