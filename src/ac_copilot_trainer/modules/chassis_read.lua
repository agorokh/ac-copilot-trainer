-- Shared chassis-dynamics accessors (issue #478 Part A).
--
-- Single source of truth for the measured g-force + yaw-rate channels the coaching brain's balance
-- and rotation rules confirm from (corner_attribution `turn_in_lag` / under-vs-oversteer direction),
-- so the trace capture (telemetry.lua) and the live telemetry_tick publish (ac_copilot_trainer.lua)
-- cannot drift on the finicky parts:
--   * CSP `car.acceleration` is a vec3 already in **G** (NOT m/s^2): `.x` = lateral (sideways,
--     relative to the car), `.z` = longitudinal (forwards/backwards). Confirmed from the CSP Lua SDK
--     (`ac_apps/lib.lua`: "@G-forces, X for sideways relative to car, Z for forwards/backwards").
--   * CSP `car.localAngularVelocity` is a vec3 in rad/s in the car's local frame; `.y` (the vertical
--     axis) is the yaw rate — the clean rotation signal.
--   * Neither field is on the CSP "confirmed valid" list (see csp-api-field-safety), so a struct that
--     lacks them THROWS on access rather than returning nil. Every read is pcall-guarded and degrades
--     to nil — mirroring wheel_read.lua so the two accessors behave identically.
--   * Non-finite reads (NaN / +-inf) are rejected to nil so they never serialize as invalid JSON
--     downstream (a CSP field can be present-but-non-finite; NaN ~= itself, +-inf == math.huge).

local M = {}

local function finite(n)
  n = tonumber(n)
  if n == nil or n ~= n or n == math.huge or n == -math.huge then
    return nil
  end
  return n
end

--- Read `obj[key]`, pcall-guarded (an unknown CSP struct field throws instead of returning nil).
function M.field(obj, key)
  local ok, v = pcall(function()
    return obj[key]
  end)
  if ok and v ~= nil then
    return v
  end
  return nil
end

--- Read a vec3 component (`.x`/`.y`/`.z`), pcall-guarded and finite-filtered. nil if unreadable.
local function component(vec, axis)
  if vec == nil then
    return nil
  end
  return finite(M.field(vec, axis))
end

--- Read a 0-indexed numeric array element (`arr[i]`), pcall-guarded and finite-filtered. CSP array
--- fields like `car.rideHeight` are 0-based `number[]` ([0]=front, [1]=rear). nil if unreadable.
local function indexed(arr, i)
  if arr == nil then
    return nil
  end
  return finite(M.field(arr, i))
end

--- Read chassis dynamics + car-level scalar channels into a flat table (each value number|nil):
--- {accG_long, accG_lat, accG_vert, yaw_rate, rideHeight_front, rideHeight_rear, brakeBias,
--- turboBoost, fuel}. pcall-guards every struct/component/index read so a missing field degrades to
--- nil (serialized as 0 downstream). accG_vert + the car scalars are issue #490; the rest are #478.
---@param car any
---@return table
function M.read(car)
  local out = {
    accG_long = nil,
    accG_lat = nil,
    accG_vert = nil,
    yaw_rate = nil,
    rideHeight_front = nil,
    rideHeight_rear = nil,
    brakeBias = nil,
    turboBoost = nil,
    fuel = nil,
  }
  if car == nil then
    return out
  end
  local accel = M.field(car, "acceleration")
  if accel ~= nil then
    out.accG_lat = component(accel, "x")   -- sideways (lateral) G
    out.accG_vert = component(accel, "y")  -- vertical G — completes the g-cube (issue #490)
    out.accG_long = component(accel, "z")  -- forwards/backwards (longitudinal) G
  end
  local angVel = M.field(car, "localAngularVelocity")
  if angVel ~= nil then
    out.yaw_rate = component(angVel, "y")  -- rotation about the vertical axis = yaw rate (rad/s)
  end
  -- Car-level scalars (issue #490). rideHeight is a 0-indexed number[] ([0]=front, [1]=rear).
  local rideH = M.field(car, "rideHeight")
  if rideH ~= nil then
    out.rideHeight_front = indexed(rideH, 0)  -- aero platform ⇒ downforce ⇒ tyre load (m)
    out.rideHeight_rear = indexed(rideH, 1)
  end
  out.brakeBias = finite(M.field(car, "brakeBias"))    -- runtime bias, 0=rear .. 1=front (physics-only)
  out.turboBoost = finite(M.field(car, "turboBoost"))  -- boost delivery, 0 and upwards
  out.fuel = finite(M.field(car, "fuel"))              -- remaining fuel (L) ⇒ car mass ⇒ tyre load
  return out
end

return M
