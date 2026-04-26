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
  if dt > 0 and dt < 1.0 then  -- guard against pause/resume jumps
    _accumDt = _accumDt + dt
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
  local cur = 0
  local readOk = false
  if car then
    local okSpeed, sp = pcall(function() return car.speedKmh end)
    if okSpeed and type(sp) == "number" then
      cur = sp
      readOk = true
    end
  end
  if not readOk and _lastSpeed then
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

  if type(view) == "table" then
    primary = tostring(view.primaryLine or primary)
    secondary = tostring(view.secondaryLine or secondary)
    kind = tostring(view.kind or kind)
    subState = tostring(view.subState or subState)
    if type(view.cornerLabel) == "string" and view.cornerLabel ~= "" then
      cornerLabel = view.cornerLabel
    end
    target = tonumber(view.targetSpeedKmh)
    dist = tonumber(view.distToBrakeM)
    local p = tonumber(view.progressPct)
    if p then
      -- realtime_coaching emits 0..1; the screen contract is 0..100 for
      -- the bar fill so the screen-side LVGL bar sets value(0..100) directly.
      progress = math.max(0, math.min(100, p * 100))
    end
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
    sub_state = subState,
    target_speed_kmh = target,
    current_speed_kmh = cur,
    dist_to_brake_m = dist,
    progress_pct = progress,
  }

  return wsBridge.publishTopic(TOPIC, payload) == true
end

--- Reset rate-limiter / cached speed (e.g. on session change).
function M.reset()
  _accumDt = 0.0
  _lastSpeed = nil
end

return M
