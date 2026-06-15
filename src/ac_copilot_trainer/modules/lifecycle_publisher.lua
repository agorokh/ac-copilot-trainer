-- Lifecycle WS topic publishers (issue #180, EPIC #154 Part D step 2).
--
-- Owns the three *lifecycle* topics the autonomous self-test harness's sequence
-- assertions need (session -> lap boundary -> ...):
--   * `connection`  — ~1 Hz heartbeat (car/track/session identity + app version).
--   * `session`     — event-driven; published only when track/car/session changes.
--   * `lap`         — published once per `car.lapCount` boundary (lap time + validity).
--
-- Model mirrors `coaching_publisher.lua`: each publish is a no-op when the WS
-- isn't open (`wsBridge.publishTopic` returns false until the v1 hello handshake
-- completes, see ws_bridge.lua / the #170 fix), so these are safe to call every
-- frame at any frame rate. The topic strings are declared as `local` constants so
-- the `test_ws_topic_allowlist` drift-guard can statically resolve them against
-- `external_protocol.KNOWN_TOPICS`.
--
-- The richer telemetry topics (`delta`, `tire_temps`) are intentionally NOT here —
-- they need current-elapsed-ms / per-wheel-temp data-source wiring and ship as a
-- follow-up (see #180), keeping this module to the low-risk lifecycle set.

local M = {}

local CONNECTION_INTERVAL_SEC = 1.0
local TOPIC_CONNECTION = "connection"
local TOPIC_SESSION = "session"
local TOPIC_LAP = "lap"

-- Module-level rate-limiter / change-detector state. Reset via M.reset() on
-- session change so a new session re-emits `session` and the heartbeat re-aligns.
local _connAccum = 0.0
local _lastSessionKey = nil


local function _wsReady(opts)
  local wsBridge = opts.wsBridge
  if not wsBridge or type(wsBridge.publishTopic) ~= "function" then
    return nil
  end
  return wsBridge
end


local function _carId(car)
  -- ac.getCarID(0) is the stable content id; fall back to car.id if present.
  if ac and type(ac.getCarID) == "function" then
    local ok, v = pcall(ac.getCarID, 0)
    if ok and type(v) == "string" and v ~= "" then
      return v
    end
  end
  if car then
    local ok, v = pcall(function()
      return car.id
    end)
    if ok and type(v) == "string" and v ~= "" then
      return v
    end
  end
  return nil
end


local function _trackId()
  if ac then
    -- Prefer the full id (track/layout) so multi-layout tracks (e.g. a GP vs national
    -- layout) are distinguished; fall back to the bare track id.
    if type(ac.getTrackFullID) == "function" then
      local ok, v = pcall(ac.getTrackFullID, "/")
      if ok and type(v) == "string" and v ~= "" then
        return v
      end
    end
    if type(ac.getTrackID) == "function" then
      local ok, v = pcall(ac.getTrackID)
      if ok and type(v) == "string" and v ~= "" then
        return v
      end
    end
  end
  return nil
end


local function _sessionIndex(sim)
  if sim then
    local ok, v = pcall(function()
      return sim.currentSessionIndex
    end)
    if ok and type(v) == "number" then
      return v
    end
  end
  return nil
end


--- ~1 Hz connection heartbeat.
---@param opts table  {dt:number, car?, sim?, wsBridge, appVersion?}
---@return boolean  true if a frame was actually published this call
function M.publishConnectionIfDue(opts)
  if type(opts) ~= "table" then
    return false
  end
  local wsBridge = _wsReady(opts)
  if not wsBridge then
    return false
  end
  local dt = tonumber(opts.dt) or 0
  -- Cap a single frame's contribution so a long pause/resume doesn't burst, but
  -- still wakes on the next call (same shape as coaching_publisher's accumulator).
  if dt > 0 then
    _connAccum = _connAccum + math.min(dt, CONNECTION_INTERVAL_SEC)
  end
  if _connAccum < CONNECTION_INTERVAL_SEC then
    return false
  end
  _connAccum = _connAccum - CONNECTION_INTERVAL_SEC
  if _connAccum < 0 then
    _connAccum = 0.0
  end
  return wsBridge.publishTopic(TOPIC_CONNECTION, {
    car_id = _carId(opts.car),
    track_id = _trackId(),
    session_index = _sessionIndex(opts.sim),
    app_version = (opts.appVersion ~= nil) and tostring(opts.appVersion) or nil,
  }) == true
end


--- Publish `session` only when track/car/session-index changes since the last call.
---@param opts table  {car?, sim?, wsBridge}
---@return boolean  true if a frame was actually published this call
function M.publishSessionIfChanged(opts)
  if type(opts) ~= "table" then
    return false
  end
  local wsBridge = _wsReady(opts)
  if not wsBridge then
    return false
  end
  local trackId = _trackId()
  local carId = _carId(opts.car)
  local sessIdx = _sessionIndex(opts.sim)
  local key = tostring(trackId) .. "|" .. tostring(carId) .. "|" .. tostring(sessIdx)
  if key == _lastSessionKey then
    return false
  end
  -- Only record the key once the publish actually SUCCEEDS: if the WS is down
  -- when the session first changes, publishTopic returns false (no-op) and we
  -- must retry on the next call rather than swallow the initial `session` frame
  -- the harness's session->lap sequence assertion depends on.
  local ok = wsBridge.publishTopic(TOPIC_SESSION, {
    track_id = trackId,
    car_id = carId,
    session_index = sessIdx,
  }) == true
  if ok then
    _lastSessionKey = key
  end
  return ok
end


--- Publish `lap` once, at a `car.lapCount` boundary (caller detects the boundary).
---@param opts table  {lap?, lastLapMs?, bestLapMs?, lapsCompleted?, valid?:boolean, wsBridge}
---@return boolean  true if a frame was actually published this call
function M.publishLap(opts)
  if type(opts) ~= "table" then
    return false
  end
  local wsBridge = _wsReady(opts)
  if not wsBridge then
    return false
  end
  return wsBridge.publishTopic(TOPIC_LAP, {
    lap = tonumber(opts.lap),
    last_lap_ms = tonumber(opts.lastLapMs),
    best_lap_ms = tonumber(opts.bestLapMs),
    laps_completed = tonumber(opts.lapsCompleted),
    -- Treat missing as valid; only an explicit false marks an invalidated lap.
    valid = opts.valid ~= false,
  }) == true
end


--- Reset rate-limiter + change-detector (call on session change).
function M.reset()
  _connAccum = 0.0
  _lastSessionKey = nil
end


return M
