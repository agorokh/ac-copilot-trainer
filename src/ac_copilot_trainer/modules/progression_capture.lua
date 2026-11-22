-- Measured conditions for the session-only progression capture (#957).
local ch = require("csp_helpers")

local M = {}
local policyMode = { off = 0, factory = 1, on = 2 }
local coreFields = { "tyreCoreTemp_fl", "tyreCoreTemp_fr", "tyreCoreTemp_rl", "tyreCoreTemp_rr" }

function M.finite(value)
  if type(value) == "number" and value == value and math.abs(value) < math.huge then
    return value
  end
  return nil
end

local function effectiveMode(car, modeField, countField)
  local count = M.finite(ch.safeCarField(car, countField, nil))
  if count == nil or count < 0 or count ~= math.floor(count) then return nil end
  if count == 0 then return 0 end
  local mode = M.finite(ch.safeCarField(car, modeField, nil))
  if mode == nil or mode < 0 or mode ~= math.floor(mode) then return nil end
  return mode
end

function M.readAssists(car)
  -- getAssists is optional on older CSP builds and can return nil without physics.
  if not ac or type(ac.getAssists) ~= "function"
      or ch.safeCarField(car, "physicsAvailable", nil) ~= true then return nil end
  local ok, state = pcall(ac.getAssists)
  if not ok or type(state) ~= "table" then return nil end
  local abs = policyMode[state.abs]
  local tc = policyMode[state.tractionControl]
  local stability = M.finite(state.stability)
  local absMode = effectiveMode(car, "absMode", "absModes")
  local tcMode = effectiveMode(car, "tractionControlMode", "tractionControlModes")
  if abs == nil or tc == nil or stability == nil or stability < 0 or stability > 1
      or absMode == nil or tcMode == nil or type(state.autoClutch) ~= "boolean"
      or type(state.autoShifter) ~= "boolean" or type(state.autoBlip) ~= "boolean" then
    return nil
  end
  return {
    abs = abs, traction_control = tc, stability_control = stability,
    auto_clutch = state.autoClutch, auto_shifter = state.autoShifter, auto_blip = state.autoBlip,
    abs_mode = absMode, tc_mode = tcMode,
  }
end

function M.sameAssists(previous, current)
  for key, value in pairs(previous) do
    if current[key] ~= value then return false end
  end
  return true
end

--- Read the retained raw samples before the archive's trace encoding zero-fills missing values.
function M.traceConditions(trace)
  local startFuelL = trace[1] and M.finite(trace[1].fuel)
  if startFuelL ~= nil and startFuelL < 0 then startFuelL = nil end
  local sum = 0
  for _, row in ipairs(trace) do
    for _, field in ipairs(coreFields) do
      local temp = M.finite(row[field])
      if temp == nil then return startFuelL, nil end
      sum = sum + temp
    end
  end
  return startFuelL, #trace > 0 and M.finite(sum / (#trace * #coreFields)) or nil
end

return M
