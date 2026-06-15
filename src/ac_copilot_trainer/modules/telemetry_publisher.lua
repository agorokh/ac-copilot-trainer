-- Telemetry WS topic publishers (issue #180, EPIC #154 Part D step 2 — telemetry subset).
--
-- The two high-rate, continuous telemetry topics declared in `external_protocol.KNOWN_TOPICS`:
--   * `delta`       — live time delta vs the reference lap (reuses delta.deltaSecondsAtSpline).
--   * `tire_temps`  — current per-wheel core temps {fl, fr, rl, rr}.
--
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
local TOPIC_DELTA = "delta"
local TOPIC_TIRE_TEMPS = "tire_temps"

local _deltaAccum = 0.0
local _tireAccum = 0.0


local function _wsReady(opts)
  local wsBridge = opts.wsBridge
  if not wsBridge or type(wsBridge.publishTopic) ~= "function" then
    return nil
  end
  return wsBridge
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
  local deltaS = tonumber(opts.deltaS)
  if deltaS == nil then
    return false  -- no reference lap yet / delta unavailable: nothing meaningful to send
  end
  local due, accum = _due(_deltaAccum, tonumber(opts.dt) or 0, DELTA_INTERVAL_SEC)
  _deltaAccum = accum
  if not due then
    return false
  end
  return wsBridge.publishTopic(TOPIC_DELTA, {
    delta_s = deltaS,
    spline = tonumber(opts.spline),
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
  local due, accum = _due(_tireAccum, tonumber(opts.dt) or 0, TIRE_INTERVAL_SEC)
  _tireAccum = accum
  if not due then
    return false
  end
  return wsBridge.publishTopic(TOPIC_TIRE_TEMPS, {
    fl = tonumber(temps.fl),
    fr = tonumber(temps.fr),
    rl = tonumber(temps.rl),
    rr = tonumber(temps.rr),
  }) == true
end


--- Reset the rate-limiters (e.g. on session/stint reset).
function M.reset()
  _deltaAccum = 0.0
  _tireAccum = 0.0
end


return M
