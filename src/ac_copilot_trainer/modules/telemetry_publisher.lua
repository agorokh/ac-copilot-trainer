-- Telemetry WS topic publishers (issue #180, EPIC #154 Part D step 2 — telemetry subset).
--
-- The two high-rate, continuous telemetry topics declared in `external_protocol.KNOWN_TOPICS`:
--   * `delta`       — live time delta vs the reference lap (reuses delta.deltaSecondsAtSpline).
--   * `tire_temps`  — current per-wheel core temps {fl, fr, rl, rr}.
--
-- M0 (#341): also emits client→server `telemetry_tick` frames (20 Hz) via `wsBridge.sendJson`
-- so the sidecar observer receives spline + lap from the in-game Lua producer.
-- Unlike the lifecycle topics (`lifecycle_publisher.lua`) these carry NO ordering contract and
-- need no reconnect machinery — they are continuous streams like `coaching.snapshot`, so a
-- (re)connected consumer simply gets the next sample within the publish interval. Both are
-- thin, STATELESS rate-limited publishers (no publish-then-record): the caller computes the
-- value, this module rate-limits and forwards via `wsBridge.publishTopic`, and is a no-op when
-- the WS isn't open (`publishTopic` returns false until the v1 hello handshake completes).
--
-- Wired into `ac_copilot_trainer.lua` `script.update` AFTER `wsBridge.tick()`/`pollInbound()`
-- (current-frame WS state), alongside the lifecycle block. Topic strings are `local` consts so
-- the `test_ws_topic_allowlist` drift-guard can resolve them against KNOWN_TOPICS.

local wheelRead = require("wheel_read")
local shiftProfileModel = require("shift_profile")

local M = {}

local DELTA_INTERVAL_SEC = 0.1  -- ~10 Hz, matches the HUD delta refresh
local TIRE_INTERVAL_SEC = 0.2  -- ~5 Hz; temps move slowly, no need for 10 Hz
local TICK_INTERVAL_SEC = 0.05  -- 20 Hz, matches the sidecar telemetry_tick cap (M0 #341)
local TOPIC_DELTA = "delta"
local TOPIC_TIRE_TEMPS = "tire_temps"

local _deltaAccum = 0.0
local _tireAccum = 0.0
local _tickAccum = 0.0
local _tickSeq = 0


local function _wsReady(opts)
  local wsBridge = opts.wsBridge
  if not wsBridge or type(wsBridge.publishTopic) ~= "function" then
    return nil
  end
  return wsBridge
end


--- Coerce to a FINITE number, or nil. Rejects NaN and ±inf so a non-finite value never reaches
--- the wire (JSON cannot represent them). Defense-in-depth at the publish boundary: the wheel
--- reader already filters non-finite temps, but the publisher must not trust its caller (#185).
local function _finite(v)
  v = tonumber(v)
  if v == nil or v ~= v or v == math.huge or v == -math.huge then
    return nil
  end
  return v
end


--- Advance an accumulator by dt (capped at one interval so a long pause/resume doesn't burst),
--- returning true + the carried-over remainder when a publish is due. Mirrors coaching_publisher.
local function _due(accum, dt, interval)
  if dt > 0 then
    accum = accum + math.min(dt, interval)
  end
  if accum < interval then
    return false, accum
  end
  accum = accum - interval
  if accum < 0 then
    accum = 0.0
  end
  return true, accum
end


--- Publish `delta` at ~10 Hz. The caller passes the already-computed delta seconds (from
--- delta.deltaSecondsAtSpline) so this module never duplicates the delta math.
---@param opts table  {dt:number, deltaS:number, spline?:number, wsBridge}
---@return boolean  true if a frame was actually published this call
function M.publishDeltaIfDue(opts)
  if type(opts) ~= "table" then
    return false
  end
  local wsBridge = _wsReady(opts)
  if not wsBridge then
    return false
  end
  local deltaS = _finite(opts.deltaS)
  if deltaS == nil then
    return false  -- no reference lap yet / delta unavailable / non-finite: nothing to send
  end
  local due, accum = _due(_deltaAccum, tonumber(opts.dt) or 0, DELTA_INTERVAL_SEC)
  _deltaAccum = accum
  if not due then
    return false
  end
  -- #531 Part D remainder: the delta's OWN baseline (the active reference trace's lap time)
  -- rides with it so the sidecar's predicted lap adds the gap to the RIGHT lap time — the
  -- stint best is the wrong baseline when an imported reference drives the delta. Omitted
  -- when unknown (never 0).
  local referenceLapMs = _finite(opts.referenceLapMs)
  if referenceLapMs ~= nil and referenceLapMs <= 0 then
    referenceLapMs = nil
  end
  return wsBridge.publishTopic(TOPIC_DELTA, {
    delta_s = deltaS,
    spline = _finite(opts.spline),  -- omit a non-finite spline rather than emit unserializable JSON (#185)
    reference_lap_ms = referenceLapMs,
  }) == true
end


local function _field(obj, key)
  if obj == nil then
    return nil
  end
  local ok, value = pcall(function()
    return obj[key]
  end)
  if ok then
    return value
  end
  return nil
end


local function _cornerMap(values)
  if type(values) ~= "table" then
    return nil
  end
  local out = {}
  local any = false
  for _, key in ipairs({ "fl", "fr", "rl", "rr" }) do
    local v = _finite(values[key])
    if v ~= nil then
      out[key] = v
      any = true
    end
  end
  if any then
    return out
  end
  return nil
end


-- #531 Part F: cross-tread temps (inner/mid/outer) for the STINT page, from the #490 Tier-1
-- wheel channels. Per-wheel pcall-free (wheel_read guards its own field reads); a wheel or
-- channel that does not resolve is simply absent from its map, and an entirely-empty map is
-- omitted from the payload (unknown, never zero-filled).
local function _treadMaps(car)
  local inner, middle, outer = {}, {}, {}
  local wheels = car and _field(car, "wheels")
  if wheels == nil then
    return nil, nil, nil
  end
  for i = 0, 3 do
    local key = wheelRead.WHEEL_KEYS[i]
    local one = _field(wheels, i)
    if one ~= nil then
      inner[key] = wheelRead.tyreTempInner(one)
      middle[key] = wheelRead.tyreTempMid(one)
      outer[key] = wheelRead.tyreTempOuter(one)
    end
  end
  return inner, middle, outer
end


--- Publish `tire_temps` at ~5 Hz. `opts.temps` is {fl, fr, rl, rr} (numbers or nil), e.g. from
--- `tire_monitor`'s :currentTemps(car). `opts.car` (optional) additionally sources the
--- inner/mid/outer cross-tread maps for the STINT page (#531 Part F).
---@param opts table  {dt:number, temps:table, wsBridge, car?:any}
---@return boolean  true if a frame was actually published this call
function M.publishTireTempsIfDue(opts)
  if type(opts) ~= "table" then
    return false
  end
  local wsBridge = _wsReady(opts)
  if not wsBridge then
    return false
  end
  local temps = opts.temps
  if type(temps) ~= "table" then
    return false
  end
  local fl = _finite(temps.fl)
  local fr = _finite(temps.fr)
  local rl = _finite(temps.rl)
  local rr = _finite(temps.rr)
  if fl == nil and fr == nil and rl == nil and rr == nil then
    -- No wheel temp resolvable on this CSP build/car: treat the sample as UNAVAILABLE rather
    -- than publishing an empty {} every interval (Lua drops nil-valued keys), which would
    -- mask the data-source failure as apparently-live-but-empty samples (codex on #185).
    return false
  end
  local due, accum = _due(_tireAccum, tonumber(opts.dt) or 0, TIRE_INTERVAL_SEC)
  _tireAccum = accum
  if not due then
    return false
  end
  local payload = {
    fl = fl,
    fr = fr,
    rl = rl,
    rr = rr,
  }
  local inner, middle, outer = _treadMaps(opts.car)
  payload.inner = _cornerMap(inner)
  payload.middle = _cornerMap(middle)
  payload.outer = _cornerMap(outer)
  return wsBridge.publishTopic(TOPIC_TIRE_TEMPS, payload) == true
end


local function _clamp(v, lo, hi)
  v = tonumber(v)
  if v == nil or v ~= v or v == math.huge or v == -math.huge then
    return lo
  end
  if v < lo then
    return lo
  end
  if v > hi then
    return hi
  end
  return v
end

-- #531 Part D: CSP `ac.StateWheel.tyreWear` is 0..1 wear CONSUMED — 0.0 is a NEW tyre and the
-- value grows with use. Matches the wire field `tyre_wear_pct` (0 = new, 100 = gone), which the
-- sidecar's `race_management._tyre_advisory` reads to fire "tyre wear is high" (and its voice
-- cue) at `>= 70`, so this is a plain x100 with no inversion.
--
-- Rig-verified 2026-07-14 against 321 checked-in lap archives (4 cars) rather than assumed: the
-- SDK's "from 0 to 1" is direction-ambiguous, and reading it as CONDITION-remaining (1.0 = new)
-- inverts to 100 on a fresh set — a permanent false wear alarm on lap one. Observed range across
-- every nonzero corner was 0.000268..0.0720 (i.e. 0.03%..7.2%), growing from an exact 0.0 on new
-- tyres, which also matches reference_mock.html's illustrative "4% / 7% / 9% wear".
local function _wearPct(raw)
  raw = _finite(raw)
  if raw == nil then
    return nil
  end
  return _clamp(raw, 0, 1) * 100
end


--- Read the live per-wheel dashboard vitals (#531 Part D) into {fl,fr,rl,rr} maps, via the shared
--- `wheel_read` accessors so the finicky parts (CSP field names — `tyrePressure`/`discTemperature`/
--- `tyreWear`, NOT the SimHub/ACC spellings — and the 0-based wheel order) have one source of
--- truth. Each read is pcall-guarded there and degrades to nil, so a CSP build or car that lacks a
--- channel omits that corner rather than throwing out of the 20 Hz publish path.
---
--- `brake_temps_c` has NO dashboard slot (the frozen design puts core temp + pressure on RACE and
--- I/M/O + wear on STINT) but it is NOT dead wiring: the sidecar's `race_management._brake_advisory`
--- consumes it to raise brake-management coaching cues at `>= 650 C` (hot) / `>= 850 C` (critical).
--- The dash is not the only consumer of the tick. Safe on cars whose brake-thermal model is
--- inactive: `discTemperature` reads a flat ambient ~26 C there (the #488 caveat in
--- `wheel_read.brakeTemp`), which is far below both thresholds, so it raises no false cue.
---@param car any
---@return table pressures, table brakeTemps, table wearPct  (values number|nil per corner)
local function _readWheelVitals(car)
  local pressures, brakeTemps, wearPct = {}, {}, {}
  local wheels = _field(car, "wheels")
  if wheels == nil then
    return pressures, brakeTemps, wearPct
  end
  for i = 0, 3 do
    local key = wheelRead.WHEEL_KEYS[i]
    local one = _field(wheels, i)
    if one ~= nil then
      pressures[key] = wheelRead.pressure(one)
      brakeTemps[key] = wheelRead.brakeTemp(one)
      wearPct[key] = _wearPct(wheelRead.wear(one))
    end
  end
  return pressures, brakeTemps, wearPct
end


--- Read a CSP boolean that only exists when the car's physics expose it (`tractionControlInAction`
--- / `absInAction` are "Physics-only" per the lua-sdk `ac.StateCar` stubs). Returns nil — so the
--- publisher OMITS the key — for anything that is not a real boolean, keeping the tick's sentinel
--- discipline: missing = unknown, `false` = the system is present and idle.
local function _physicsFlag(car, key)
  local v = _field(car, key)
  if type(v) ~= "boolean" then
    return nil
  end
  return v
end


--- Publish client→server ``telemetry_tick`` at ~20 Hz (M0 #341). Requires ``wsBridge.sendJson``.
---@param opts table  {dt:number, car:any, wsBridge, lat_g?:number, long_g?:number, temps?:table, shiftProfile?:table}
---@return boolean
function M.publishTelemetryTickIfDue(opts)
  if type(opts) ~= "table" then
    return false
  end
  local wsBridge = _wsReady(opts)
  if not wsBridge or type(wsBridge.sendJson) ~= "function" then
    return false
  end
  local car = opts.car
  -- CSP state objects can be FFI cdata/userdata rather than plain tables. Tests use tables,
  -- but the live rig path must accept either shape and read fields defensively.
  if car == nil then
    return false
  end
  local due, accum = _due(_tickAccum, tonumber(opts.dt) or 0, TICK_INTERVAL_SEC)
  _tickAccum = accum
  if not due then
    return false
  end
  _tickSeq = _tickSeq + 1
  local gear = 0
  local rawGear = _field(car, "gear")
  if rawGear ~= nil then
    local g = tonumber(rawGear)
    if g ~= nil and g == g then
      gear = math.max(0, math.floor(g))
    end
  end
  local payload = {
    speed_kmh = math.max(0, _finite(_field(car, "speedKmh")) or 0),
    rpm = math.max(0, _finite(_field(car, "rpm")) or 0),
    throttle = _clamp(_field(car, "gas") or 0, 0, 1),
    brake = _clamp(_field(car, "brake") or 0, 0, 1),
    steer = _clamp(_field(car, "steer") or 0, -1, 1),
    gear = gear,
    lat_g = _finite(opts.lat_g) or 0,
    long_g = _finite(opts.long_g) or 0,
    spline = _clamp(_field(car, "splinePosition") or 0, 0, 1),
    lap = math.max(0, math.floor(tonumber(_field(car, "lapCount")) or 0)),
  }
  -- #531 Part C-min: the tablet dashboard's shift ribbon is rpm-banded from the car's real
  -- redline (never hardcoded), and its lap clock needs the running lap time. Both are optional
  -- in the validator contract; a CSP build that lacks the field (pcall in `_field`) omits it.
  local rpmMax = _finite(_field(car, "rpmLimiter"))
  if rpmMax ~= nil and rpmMax > 0 then
    payload.rpm_max = rpmMax
  end
  -- #531 Part E: the shift-profile model's resolved upshift target rides the tick so the
  -- sidecar shift observer cues from the same LEARNED per-gear point the in-game HUD
  -- teaches (#442), not a re-derived limiter fraction. Only meaningful in a forward gear;
  -- resolveShiftTarget returns nil when neither a learned profile nor a limiter is known,
  -- in which case both keys are omitted (unknown, never 0).
  if gear >= 1 then
    local shiftRpm, _, shiftProvenance =
      shiftProfileModel.resolveShiftTarget(opts.shiftProfile, gear, rpmMax)
    if shiftRpm ~= nil and shiftRpm > 0 then
      payload.shift_rpm = shiftRpm
      payload.shift_rpm_source = shiftProvenance
    end
  end
  local lapTimeMs = _finite(_field(car, "lapTimeMs"))
  if lapTimeMs ~= nil and lapTimeMs >= 0 then
    payload.lap_time_ms = lapTimeMs
  end
  local fuel = _finite(_field(car, "fuel"))
  if fuel ~= nil then
    payload.fuel_l = math.max(0, fuel)
  end
  local fuelCapacity = _finite(_field(car, "fuelCapacity") or _field(car, "maxFuel"))
  if fuelCapacity ~= nil then
    payload.fuel_capacity_l = math.max(0, fuelCapacity)
  end
  local tyreTemps = _cornerMap(opts.temps)
  if tyreTemps ~= nil then
    payload.tyre_temps_c = tyreTemps
  end
  -- #531 Part D: the live vitals the tablet dashboard's tyre board and STINT page read. They were
  -- captured to the lap trace but never streamed, so the board printed a temp with an empty
  -- pressure slot its own header advertised. Each map is omitted entirely when no corner resolved
  -- (`_cornerMap` returns nil) — an absent vital must render as an explicit unknown on the dash,
  -- never as a frozen last value.
  local pressures, brakeTemps, wearPct = _readWheelVitals(opts.car)
  local pressureMap = _cornerMap(pressures)
  if pressureMap ~= nil then
    payload.tyre_pressures_psi = pressureMap
  end
  -- Consumed by `race_management._brake_advisory` (not by the dash). `_cornerMap` returns nil when
  -- NO corner resolved, so the map is omitted only when the channel is entirely unavailable —
  -- never zero-filled, and never suppressed on a car whose brake model IS active (Codex on #590).
  local brakeTempMap = _cornerMap(brakeTemps)
  if brakeTempMap ~= nil then
    payload.brake_temps_c = brakeTempMap
  end
  local wearMap = _cornerMap(wearPct)
  if wearMap ~= nil then
    payload.tyre_wear_pct = wearMap
  end
  -- #531 Part D: the electronics intervention flash — brass segments are "what I dialled", the
  -- transient signal colour is "what the car is doing". The dashboard already read `abs_active`
  -- but NO producer ever sent it, so the flash could never fire; `tc_active` had no slot at all.
  local tcActive = _physicsFlag(car, "tractionControlInAction")
  if tcActive ~= nil then
    payload.tc_active = tcActive
  end
  local absActive = _physicsFlag(car, "absInAction")
  if absActive ~= nil then
    payload.abs_active = absActive
  end
  return wsBridge.sendJson({
    v = 1,
    type = "telemetry_tick",
    seq = _tickSeq,
    payload = payload,
  }) == true
end


--- Reset the rate-limiters and ``telemetry_tick`` sequence (e.g. on session/stint reset).
function M.reset()
  _deltaAccum = 0.0
  _tireAccum = 0.0
  _tickAccum = 0.0
  _tickSeq = 0
end


return M
