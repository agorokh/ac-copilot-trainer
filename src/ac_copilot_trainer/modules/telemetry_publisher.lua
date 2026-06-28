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
  return wsBridge.publishTopic(TOPIC_DELTA, {
    delta_s = deltaS,
    spline = _finite(opts.spline),  -- omit a non-finite spline rather than emit unserializable JSON (#185)
  }) == true
end


--- Publish `tire_temps` at ~5 Hz. `opts.temps` is {fl, fr, rl, rr} (numbers or nil), e.g. from
--- `tire_monitor`'s :currentTemps(car).
---@param opts table  {dt:number, temps:table, wsBridge}
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
  return wsBridge.publishTopic(TOPIC_TIRE_TEMPS, {
    fl = fl,
    fr = fr,
    rl = rl,
    rr = rr,
  }) == true
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


--- Publish client→server ``telemetry_tick`` at ~20 Hz (M0 #341). Requires ``wsBridge.sendJson``.
---@param opts table  {dt:number, car:table, wsBridge, lat_g?:number, long_g?:number}
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
  if type(car) ~= "table" then
    return false
  end
  local due, accum = _due(_tickAccum, tonumber(opts.dt) or 0, TICK_INTERVAL_SEC)
  _tickAccum = accum
  if not due then
    return false
  end
  _tickSeq = _tickSeq + 1
  local gear = 0
  if car.gear ~= nil then
    local g = tonumber(car.gear)
    if g ~= nil and g == g then
      gear = math.max(0, math.floor(g))
    end
  end
  return wsBridge.sendJson({
    v = 1,
    type = "telemetry_tick",
    seq = _tickSeq,
    payload = {
      speed_kmh = math.max(0, _finite(car.speedKmh) or 0),
      rpm = math.max(0, _finite(car.rpm) or 0),
      throttle = _clamp(car.gas or 0, 0, 1),
      brake = _clamp(car.brake or 0, 0, 1),
      steer = _clamp(car.steer or 0, -1, 1),
      gear = gear,
      lat_g = _finite(opts.lat_g) or 0,
      long_g = _finite(opts.long_g) or 0,
      spline = _clamp(car.splinePosition or 0, 0, 1),
      lap = math.max(0, math.floor(tonumber(car.lapCount) or 0)),
    },
  }) == true
end


--- Reset the rate-limiters (e.g. on session/stint reset).
function M.reset()
  _deltaAccum = 0.0
  _tireAccum = 0.0
  _tickAccum = 0.0
end


return M
