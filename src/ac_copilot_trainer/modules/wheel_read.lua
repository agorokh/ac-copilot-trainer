-- Shared per-wheel telemetry accessors (issue #266).
--
-- Single source of truth for reading `car.wheels` so telemetry.lua (trace capture) and
-- tire_monitor.lua (live lockup/temp HUD) cannot drift on the finicky parts:
--   * CSP `car.wheels` is **0-indexed** per `ac.Wheel`: FrontLeft=0, FrontRight=1, RearLeft=2,
--     RearRight=3. A 1-based read shifts every corner and reads an out-of-bounds zero for RR
--     (the `tire_temps.rr=0` regression in #180). Always iterate `for i=0,3`.
--   * Every access is pcall-guarded: a schema-gated mock `car` (trace_replay) or a missing field
--     raises, and we degrade to nil rather than throwing out of the hot update loop.
--   * Non-finite reads (NaN / +-inf) are rejected to nil so they never serialize as invalid JSON
--     downstream (a CSP field can be present-but-non-finite; NaN ~= itself, +-inf == math.huge).

local M = {}

-- 0-based CSP wheel index -> our FL/FR/RL/RR label.
M.WHEEL_KEYS = { [0] = "fl", [1] = "fr", [2] = "rl", [3] = "rr" }

--- Read a field from a table or userdata wheel object, pcall-guarded.
function M.field(one, key)
  local ok, v = pcall(function()
    return one[key]
  end)
  if ok and v ~= nil then
    return v
  end
  return nil
end

local function finite(n)
  n = tonumber(n)
  if n == nil or n ~= n or n == math.huge or n == -math.huge then
    return nil
  end
  return n
end

--- Tyre core temperature (degC). Falls back across CSP field names; unwraps a `{average=}` table.
function M.temp(one)
  local t = M.field(one, "tyreCoreTemperature")
    or M.field(one, "temperature")
    or M.field(one, "tyreTemperature")
  if type(t) == "table" and t.average ~= nil then
    t = t.average
  end
  return finite(t)
end

--- Longitudinal slip ratio (signed; <0 = wheel slower than ground = locking). nil if unreadable.
function M.slip(one)
  return finite(M.field(one, "slipRatio") or M.field(one, "slip") or M.field(one, "ndSlip"))
end

--- Wheel angular speed (rad/s). The canonical longitudinal signal the analysis layer derives slip
--- from (corner_attribution.corner_live_signals); nil if unreadable.
function M.omega(one)
  return finite(M.field(one, "angularSpeed") or M.field(one, "wheelAngularSpeed"))
end

--- Dynamic (HOT) tyre pressure (psi). CSP `tyrePressure` is the live/dynamic value the pressure
--- attribution rule confirms from; `tyreStaticPressure` is the cold set value (not this). nil if
--- unreadable (issue #478 Part B).
function M.pressure(one)
  return finite(M.field(one, "tyrePressure") or M.field(one, "dynamicPressure"))
end

--- Read all four wheels into {omega={fl,fr,rl,rr}, slip={...}, temp={...}, pressure={...}} (each
--- value number|nil). pcall-guards the `car.wheels` access and every per-wheel read.
---@param car any
---@return table
function M.readPerWheel(car)
  local out = { omega = {}, slip = {}, temp = {}, pressure = {} }
  if car == nil then
    return out
  end
  local okW, wheels = pcall(function()
    return car.wheels
  end)
  if not okW or wheels == nil then
    return out
  end
  for i = 0, 3 do
    local k = M.WHEEL_KEYS[i]
    local oki, one = pcall(function()
      return wheels[i]
    end)
    if oki and one ~= nil then
      out.omega[k] = M.omega(one)
      out.slip[k] = M.slip(one)
      out.temp[k] = M.temp(one)
      out.pressure[k] = M.pressure(one)
    end
  end
  return out
end

return M
