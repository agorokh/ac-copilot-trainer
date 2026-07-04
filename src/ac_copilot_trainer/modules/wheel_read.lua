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
--- CAVEAT (#488, rig-verified 2026-07-04): `discTemperature` reads a flat ambient (~26 °C) when the
--- car's brake-thermal model is inactive — reproduced on the 911 GT3 R across a hard-braking lap
--- even with `car.extendedPhysics == true`. So it is CAR-physics-dependent, NOT extended-physics-
--- gated; it stays a Tier-1 base-AC channel (it heats in sessions where the model is active). Treat
--- a flat 26 °C as "not modelled for this car", not a capture bug.
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

-- Tier-2 CSP force/slip channels (issue #488 Part A) — the dynamic tyre FORCE + SLIP state: the
-- ground-truth grip labels ML needs and the earliest understeer-onset signal (Mz collapses before
-- lateral force saturates). CSP field names verified against THIS rig's lua-sdk `ac.StateWheel`
-- stubs (extension/internal/lua-sdk/*/lib.lua, class ac.StateWheel): `slipRatio` (unitless
-- longitudinal), `slipAngle` (DEGREES lateral — "angle between desired and actual direction"),
-- `mz` (self-aligning torque), `fx`/`fy` (contact-patch forces, N), `dy` (lateral friction
-- coefficient / peak mu). AC's Pacejka solver populates these via CSP Lua; the car-level
-- `extendedPhysics` flag (recorded in the lap header, not per-wheel) is the confound telling ML
-- whether the advanced tyre model was active. Every read is pcall-guarded + finite-filtered, so an
-- absent field degrades to nil (serialized as 0 downstream) — it never throws out of the hot loop
-- nor fails the archive, satisfying the "gate/record availability, never fail" contract.

--- Longitudinal slip ratio (unitless; CSP `slipRatio`). Traction-limit + frictional-heat driver.
--- Reads ONLY the explicit longitudinal ratio — distinct from `M.slip`/`wheelSlip` (AC ndSlip
--- fallback). nil if unreadable.
function M.slipRatioLong(one)
  return finite(M.field(one, "slipRatio"))
end

--- Lateral slip angle (DEGREES; CSP `slipAngle`). Cornering grip usage + lateral heat input; the
--- front-vs-rear slip-angle balance is the direct under/oversteer signal. nil if unreadable.
function M.slipAngle(one)
  return finite(M.field(one, "slipAngle"))
end

--- Self-aligning torque Mz (Nm; CSP `mz`). Collapses BEFORE lateral force saturates → earliest
--- understeer-onset signal. nil if unreadable.
function M.mz(one)
  return finite(M.field(one, "mz"))
end

--- Longitudinal contact-patch force Fx (N; CSP `fx`). Ground-truth traction/braking force label.
--- nil if unreadable.
function M.fx(one)
  return finite(M.field(one, "fx"))
end

--- Lateral contact-patch force Fy (N; CSP `fy`). Ground-truth cornering-force label. nil if
--- unreadable.
function M.fy(one)
  return finite(M.field(one, "fy"))
end

--- Lateral friction coefficient Dy / peak mu (unitless; CSP `dy`). Supervised grip-model label —
--- the friction the tyre is actually delivering. nil if unreadable.
function M.dy(one)
  return finite(M.field(one, "dy"))
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
    -- issue #488 Tier-2 CSP force/slip channels
    slipRatioLong = {},
    slipAngle = {},
    mz = {},
    fx = {},
    fy = {},
    dy = {},
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
      -- issue #488 Tier-2 CSP force/slip channels
      out.slipRatioLong[k] = M.slipRatioLong(one)
      out.slipAngle[k] = M.slipAngle(one)
      out.mz[k] = M.mz(one)
      out.fx[k] = M.fx(one)
      out.fy[k] = M.fy(one)
      out.dy[k] = M.dy(one)
    end
  end
  return out
end

return M
