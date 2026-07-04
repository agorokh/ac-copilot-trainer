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

-- Tier-1 base-AC dynamic channels (issue #490). CSP field names verified against the lua-sdk
-- `ac.StateWheel` stubs (extension/internal/lua-sdk). All base-AC shared memory — no CSP extended
-- physics dependency. Every read is pcall-guarded + finite-filtered so a wrong/absent field
-- degrades to nil (serialized as 0 by traceSampleToColumnRow), never throwing out of the hot loop.

--- Tyre temperature across the tread (degC): inner / middle / outer. The cross-tread gradient
--- (inner-vs-outer) is the camber/pressure/load diagnosis signal (inner-hot=camber, outer-hot=low
--- psi). nil if unreadable.
function M.tyreTempInner(one)
  return finite(M.field(one, "tyreInsideTemperature") or M.field(one, "insideTemperature"))
end

function M.tyreTempMid(one)
  return finite(M.field(one, "tyreMiddleTemperature") or M.field(one, "middleTemperature"))
end

function M.tyreTempOuter(one)
  return finite(M.field(one, "tyreOutsideTemperature") or M.field(one, "outsideTemperature"))
end

--- Brake disc temperature (degC). CSP `discTemperature` — brake heat into the tyre; brake-bias /
--- duct attribution + braking-abuse. nil if unreadable.
function M.brakeTemp(one)
  return finite(M.field(one, "discTemperature"))
end

--- Vertical tyre load Fz (N). Normalizes slip->grip; strongest nonlinearity in wear. CSP `load` is
--- exact for the local player car (its `loadK` sibling is the remote/replay estimate). nil if
--- unreadable.
function M.load(one)
  return finite(M.field(one, "load"))
end

--- Tyre wear (0..1). AC's wear scale is NOT a simple 0-100% remaining — document before using as an
--- ML target. nil if unreadable.
function M.wear(one)
  return finite(M.field(one, "tyreWear"))
end

--- Tyre dirt level (0..1) — exclude off-track/dirty samples from degradation fits. nil if unreadable.
function M.dirty(one)
  return finite(M.field(one, "tyreDirty") or M.field(one, "dirt"))
end

--- Dynamic (running) camber angle in DEGREES (CSP `camber`; the issue named base-SM `camberRAD` in
--- radians, but our capture path reads CSP Lua, which exposes degrees — units recorded in the schema
--- doc). Running vs set camber; ties the cross-tread temp gradient to geometry under load. nil if
--- unreadable.
function M.camber(one)
  return finite(M.field(one, "camber"))
end

--- Suspension travel (m) — load transfer; spring/ARB attribution; the raw signal damper velocity is
--- derived from (d/dt in telemetry.lua). nil if unreadable.
function M.suspTravel(one)
  return finite(M.field(one, "suspensionTravel"))
end

--- Read all four wheels into {omega={fl,fr,rl,rr}, slip={...}, temp={...}, pressure={...}, and the
--- issue #490 Tier-1 channels tyreTempInner/Mid/Outer, brakeTemp, load, wear, dirty, camber,
--- suspTravel} (each value number|nil). pcall-guards the `car.wheels` access and every per-wheel read.
---@param car any
---@return table
function M.readPerWheel(car)
  local out = {
    omega = {},
    slip = {},
    temp = {},
    pressure = {},
    -- issue #490 Tier-1 base-AC dynamic channels
    tyreTempInner = {},
    tyreTempMid = {},
    tyreTempOuter = {},
    brakeTemp = {},
    load = {},
    wear = {},
    dirty = {},
    camber = {},
    suspTravel = {},
  }
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
      -- issue #490 Tier-1 base-AC dynamic channels
      out.tyreTempInner[k] = M.tyreTempInner(one)
      out.tyreTempMid[k] = M.tyreTempMid(one)
      out.tyreTempOuter[k] = M.tyreTempOuter(one)
      out.brakeTemp[k] = M.brakeTemp(one)
      out.load[k] = M.load(one)
      out.wear[k] = M.wear(one)
      out.dirty[k] = M.dirty(one)
      out.camber[k] = M.camber(one)
      out.suspTravel[k] = M.suspTravel(one)
    end
  end
  return out
end

return M
