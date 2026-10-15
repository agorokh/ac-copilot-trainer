-- Coaching snapshot publisher (issue #86 Part C3).
--
-- 10 Hz `state.snapshot topic="coaching.snapshot"` push to the rig screen.
-- Consumes the existing realtime view-model (state._cachedRealtimeView,
-- produced by `realtime_coaching.tick`) plus current car/sim context, and
-- ships exactly the fields the screen-side `screen_ac_copilot.cpp` parser
-- expects.
--
-- Rate-limited to 10 Hz (`PUBLISH_INTERVAL_SEC = 0.1`) so it does not flood
-- the WS even when `script.update` runs at 60+ Hz. The publisher is also
-- deliberately a no-op when the WS isn't open — we don't want to spam logs
-- during a sidecar-down session, and the screen will simply hold the last
-- snapshot it has on its side until reconnect.
--
-- This module is a *thin adapter* over the existing realtime engine — it
-- never duplicates any rules-engine logic. If `realtime_coaching` changes
-- its viewmodel shape, only the field-mapping in `M.publishIfDue` here
-- needs to track that.

local M = {}
local cspHelpers = require("csp_helpers")

local PUBLISH_INTERVAL_SEC = 0.1
local TOPIC = "coaching.snapshot"

local _accumDt = 0.0
-- _lastSpeed is the last speed we successfully read from the car. We only
-- substitute it when the underlying car.speedKmh read FAILED (pcall raised
-- or returned a non-number), not when it returned a genuine 0. Conflating
-- "stopped" with "missing" used to freeze the screen on a prior speed for a
-- parked driver (Cursor + CodeRabbit on PR #91); separate the success-of-read
-- from the numeric value to fix.
local _lastSpeed = nil

local ACTIONS = {
  BRAKE = true, LIFT = true, UPSHIFT = true, CARRY_MORE_SPEED = true,
  HOLD = true, CLEAR = true, UNAVAILABLE = true,
}
local LEGACY_ACTIONS = {
  ["BRAKE NOW"] = "BRAKE", ["PREPARE TO BRAKE"] = "BRAKE",
  ["EASE OFF"] = "LIFT", ["SHIFT UP"] = "UPSHIFT",
  ["CARRY MORE SPEED"] = "CARRY_MORE_SPEED", ["APPROACHING"] = "HOLD",
  ["ON PACE"] = "HOLD", ["NEXT TURN"] = "CLEAR",
}

local function label(value)
  if type(value) == "string" and value ~= "" then return value:sub(1, 64) end
  return nil
end

local function nonnegative(value)
  local n = tonumber(value)
  if n and n == n and n >= 0 and n < math.huge then return n end
  return nil
end

local function speed(value)
  local n = nonnegative(value)
  if n and n <= 1000 then return n end
  return nil
end

local function targetFields(value, phase, provenance, available)
  local n = speed(value)
  local valid = available == true and n ~= nil
    and ((phase == "brake_onset" and provenance == "reference_brake")
      or (phase == "entry" and provenance == "segment_entry")
      or (phase == "reference_at_position" and provenance == "reference_trace"))
  if valid then return n, phase, provenance, true end
  return nil, "unavailable", "unavailable", false
end

--- Publish at most once every PUBLISH_INTERVAL_SEC sim seconds.
---
---@param opts table
---  opts.dt          (number, required)  frame delta seconds
---  opts.view        (table|nil, optional)  realtime_coaching viewmodel
---  opts.car         (ac.StateCar|nil)
---  opts.sim         (ac.StateSim|nil)
---  opts.wsBridge    (table)               module returned by require("ws_bridge")
---@return boolean   true if a frame was actually published this call
function M.publishIfDue(opts)
  if type(opts) ~= "table" then return false end
  local dt = tonumber(opts.dt) or 0
  if dt > 0 then
    -- Cap a single-frame contribution at PUBLISH_INTERVAL_SEC so a long
    -- pause/resume frame doesn't "burst publish" once we cross the boundary,
    -- but the publisher still wakes up on the very next call instead of
    -- being skipped entirely. (CodeRabbit follow-up nit on PR #91: the prior
    -- `dt < 1.0` guard dropped the long-frame contribution, so a paused-
    -- then-resumed session could stall publishing for one extra quantum.)
    _accumDt = _accumDt + math.min(dt, PUBLISH_INTERVAL_SEC)
  end
  if _accumDt < PUBLISH_INTERVAL_SEC then
    return false
  end
  -- Carry residual time across the boundary instead of zeroing the
  -- accumulator: zeroing would discard the leftover fraction and slowly
  -- drop the effective rate below 10 Hz over time. (CodeRabbit nit on PR
  -- #91.)
  _accumDt = _accumDt - PUBLISH_INTERVAL_SEC
  if _accumDt < 0 then _accumDt = 0.0 end

  local wsBridge = opts.wsBridge
  if not wsBridge or type(wsBridge.publishTopic) ~= "function" then
    return false
  end

  local view = opts.view
  local car = opts.car

  -- Always send a payload, even when the view-model is empty / placeholder
  -- so the screen can render the "DRIVE A LAP" empty state instead of
  -- staying frozen on the last live snapshot from a prior session.
  --
  -- Speed read: separate the SUCCESS of the pcall from the value. When the
  -- read succeeds and returns 0 (parked / paused), forward that 0 — the
  -- screen contract treats 0 as a legitimate value and only -1 / nil as
  -- "missing". When the read raised, fall back to the cached last-known
  -- value so transient CSP nil/cdata flips do not make the screen flicker.
  local cur = -1
  local readOk = false
  if car then
    local okSpeed, sp = pcall(function() return car.speedKmh end)
    if okSpeed and type(sp) == "number" and speed(sp) ~= nil then
      cur = speed(sp)
      readOk = true
    end
  end
  if car and not readOk and _lastSpeed then
    cur = _lastSpeed
  end
  if readOk then
    _lastSpeed = cur
  end

  local primary = "DRIVE A LAP"
  local secondary = "REFERENCE WILL APPEAR"
  local kind = "placeholder"
  local subState = "no_reference"
  local cornerLabel = nil
  local target = nil
  local dist = nil
  local progress = 0.0
  local action = "UNAVAILABLE"
  local currentCornerLabel, approachLabel
  local targetPhase, targetProvenance, targetAvailable = "unavailable", "unavailable", false
  local currentTarget, currentPhase, currentProvenance, currentAvailable
  local selectedTarget, selectedPhase, selectedProvenance, selectedAvailable, selectedCorner

  if type(view) == "table" then
    primary = tostring(view.primaryLine or primary):sub(1, 160)
    secondary = tostring(view.secondaryLine or secondary):sub(1, 240)
    kind = tostring(view.kind or kind)
    subState = tostring(view.subState or subState)
    if type(view.cornerLabel) == "string" and view.cornerLabel ~= "" then
      cornerLabel = label(view.cornerLabel)
    end
    -- Backwards compatibility is exact-command only. `kind=line` includes
    -- upshift and carrying speed, so it cannot imply LIFT.
    if view.action == nil then action = LEGACY_ACTIONS[primary] or "UNAVAILABLE"
    elseif ACTIONS[view.action] then action = view.action end
    currentCornerLabel = label(view.currentCornerLabel)
    approachLabel = label(view.approachLabel)
    target, targetPhase, targetProvenance, targetAvailable = targetFields(
      view.targetSpeedKmh, view.targetPhase, view.targetProvenance, view.targetAvailable)
    currentTarget, currentPhase, currentProvenance, currentAvailable = targetFields(
      view.currentTargetSpeedKmh, view.currentTargetPhase,
      view.currentTargetProvenance, view.currentTargetAvailable)
    selectedTarget, selectedPhase, selectedProvenance, selectedAvailable = targetFields(
      view.selectedTargetSpeedKmh, view.selectedTargetPhase,
      view.selectedTargetProvenance, view.selectedTargetAvailable)
    selectedCorner = label(view.selectedTargetCornerLabel)
    dist = nonnegative(view.distToBrakeM)
    local p = tonumber(view.progressPct)
    if p and p == p and p < math.huge then
      -- realtime_coaching emits 0..1; the screen contract is 0..100 for
      -- the bar fill so the screen-side LVGL bar sets value(0..100) directly.
      progress = math.max(0, math.min(100, p * 100))
    end
  end

  -- A fresh envelope cannot make an old viewmodel actionable. The speed
  -- read is part of the live predicate, so a cached/failed read parks the
  -- command and every position-dependent corner/target field together.
  if not readOk then
    action = "UNAVAILABLE"
    primary = "COACHING UNAVAILABLE"
    secondary = "LIVE SPEED UNAVAILABLE"
    kind = "placeholder"
    subState = "telemetry_unavailable"
    cornerLabel, currentCornerLabel, approachLabel, selectedCorner = nil, nil, nil, nil
    target, currentTarget, selectedTarget, dist = nil, nil, nil, nil
    targetPhase, currentPhase, selectedPhase = "unavailable", "unavailable", "unavailable"
    targetProvenance, currentProvenance, selectedProvenance = "unavailable", "unavailable", "unavailable"
    targetAvailable, currentAvailable, selectedAvailable = false, false, false
    progress = 0
  end

  local payload = {
    -- Issue #86 Part C3 contract: stable string keys, all numeric fields
    -- explicit. `corner_id` is the short label (e.g. "T3") and matches the
    -- key the screen uses to correlate `corner_advice` overrides.
    corner_id = cornerLabel,
    corner_label = cornerLabel,
    primary_line = primary,
    secondary_line = secondary,
    kind = kind,
    action = action,
    sub_state = subState,
    target_speed_kmh = target,
    -- Legacy target_speed_kmh and all target_* metadata refer to NEXT.
    -- Current speed comparisons use current_target_* / selected_target_*.
    current_corner_id = currentCornerLabel,
    current_corner_label = currentCornerLabel,
    approach_corner_id = approachLabel,
    approach_corner_label = approachLabel,
    target_corner_id = approachLabel,
    target_phase = targetPhase,
    target_provenance = targetProvenance,
    target_available = targetAvailable,
    approach_target_speed_kmh = target,
    approach_target_phase = targetPhase,
    approach_target_provenance = targetProvenance,
    approach_target_available = targetAvailable,
    current_target_speed_kmh = currentTarget,
    current_target_phase = currentPhase or "unavailable",
    current_target_provenance = currentProvenance or "unavailable",
    current_target_available = currentAvailable == true,
    selected_target_speed_kmh = selectedTarget,
    selected_target_corner_id = selectedCorner,
    selected_target_phase = selectedPhase or "unavailable",
    selected_target_provenance = selectedProvenance or "unavailable",
    selected_target_available = selectedAvailable == true,
    current_speed_kmh = cur,
    current_speed_available = readOk,
    current_speed_source = readOk and "live" or (cur >= 0 and "cached" or "unavailable"),
    dist_to_brake_m = dist,
    progress_pct = progress,
    corner_catalog_available = false,
    corner_catalog_source = "lua_active_reference",
    corner_catalog_reason = "canonical corners unavailable",
  }

  -- Existing topic carries the applied post-lap focus separately from the immediate
  -- action. The producer owns its lap identity and countdown; repeats cannot renew it.
  local focus = opts.postLapFocus
  local completed = tonumber(opts.completedLap)
  if readOk and type(focus) == "table" and focus.source == "model"
      and type(focus.text) == "string" and #focus.text > 0 and #focus.text <= 120
      and type(focus.focus_id) == "string" and #focus.focus_id <= 64
      and type(focus.corner) == "string" and focus.corner:match("^T%d+$")
      and completed and completed == completed and completed >= 0 and completed % 1 == 0
      and focus.lap == completed and type(focus.remaining_ms) == "number"
      and focus.remaining_ms > 0 and focus.remaining_ms <= 12000 then
    payload.completed_lap = completed
    payload.post_lap_focus = focus
  end

  if readOk and type(view) == "table" then
    payload.corner_catalog_reason = label(view.cornerCatalogReason) or payload.corner_catalog_reason
    local carId = cspHelpers.safeCarIdRaw()
    local trackId = cspHelpers.safeTrackIdRaw()
    local layout = cspHelpers.safeTrackLayoutRaw()
    local identityOk = type(carId) == "string" and #carId > 0 and #carId <= 128
      and type(trackId) == "string" and #trackId > 0 and #trackId <= 128
      and type(layout) == "string" and #layout <= 128
    if view.cornerCatalogAvailable == true and identityOk then
      payload.corner_catalog = view.cornerCatalog
      payload.corner_catalog_available = true
      payload.corner_catalog_car_id = carId
      payload.corner_catalog_track_id = trackId
      payload.corner_catalog_layout = layout
      payload.corner_catalog_reference_source = label(view.referenceSource) or "active_lua_reference"
      payload.corner_catalog_reference_lap_ms = nonnegative(view.referenceLapMs)
      -- The rig's normal USB parser accepts at most 8192 bytes per frame.
      -- Count the full envelope, including any advisory/string escaping.
      local ok, serialized = false, nil
      if JSON and type(JSON.stringify) == "function" then
        ok, serialized = pcall(JSON.stringify,
          { v = 1, type = "state.snapshot", topic = TOPIC, payload = payload }, false)
      end
      if not ok or type(serialized) ~= "string" or #serialized > 8192 then
        payload.corner_catalog = nil
        payload.corner_catalog_available = false
        payload.corner_catalog_reason = "canonical catalog frame budget unavailable"
      end
    elseif view.cornerCatalogAvailable == true then
      payload.corner_catalog_reason = "canonical combo identity unavailable"
    end
  elseif not readOk then
    payload.corner_catalog_reason = "live speed unavailable"
  end

  return wsBridge.publishTopic(TOPIC, payload) == true
end

--- Reset rate-limiter / cached speed (e.g. on session change).
function M.reset()
  _accumDt = 0.0
  _lastSpeed = nil
end

return M
