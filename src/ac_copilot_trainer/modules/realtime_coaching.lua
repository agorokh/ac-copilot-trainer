-- Live-frame coaching engine (issue #72 rebuild).
--
-- DESIGN PRINCIPLES (per issue #72):
--   1. Operates on LIVE FRAME inputs only — no lap-aggregate features.
--   2. Always returns a viewmodel (never nil). Empty state returns a
--      placeholder so the UI is never blank.
--   3. Uses persisted reference data the moment the session starts:
--        - state.bestSortedTrace      → reference speed at any spline pos
--        - state.brakingPoints.best   → next brake point lookup
--        - state.trackSegments        → corner labels and spline ranges
--   4. Does NOT depend on lap-aggregate corner features at all
--      (those used to gate hints behind a 2-lap warm-up).
--
-- The viewmodel contract is shared by both windows: top tile reads
-- {primaryLine, secondaryLine, kind} and bottom tile reads
-- {turnLabel, targetSpeedKmh, currentSpeedKmh, distToBrakeM, progressPct}.

local M = {}

-- ---------------------------------------------------------------------------
-- Tunable thresholds (live-frame deltas, not lap aggregates).
-- ---------------------------------------------------------------------------

local BRAKE_NOW_DIST_M     = 50    -- inside this distance, "BRAKE NOW" if too fast
local PREPARE_DIST_M       = 100   -- inside this, "PREPARE TO BRAKE" if a bit fast
local BRAKE_OVER_KMH       = 8     -- "too fast" delta for BRAKE NOW
local PREPARE_OVER_KMH     = 5     -- "too fast" delta for PREPARE TO BRAKE
local CORNER_DELTA_KMH     = 8     -- in-corner ±delta for "carry more / ease off"
local APPROACH_DEFAULT_M   = 200   -- max distance ahead we even look at the next brake
local DEDUP_HOLD_SEC       = 0.6   -- minimum time before re-firing the same hint kind

-- ---------------------------------------------------------------------------
-- Module state (reset via M.reset).
-- ---------------------------------------------------------------------------

local lastView = nil               -- last returned viewmodel (for dedupe / fade)
local lastEmittedKey = nil         -- {kind .. ":" .. cornerLabel}
local lastEmittedAt = -1e9         -- monotonic time of last emission (seconds)
local monoClock = 0                -- accumulated dt for dedupe (no os.time dependency)

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function clamp(v, lo, hi)
  if v < lo then return lo end
  if v > hi then return hi end
  return v
end

local function wrap01(x)
  local s = x % 1
  if s < 0 then s = s + 1 end
  return s
end

--- Forward spline distance (always positive, in [0, 1)).
local function forwardSplineDelta(carSp, targetSp)
  local d = (targetSp - carSp) % 1
  if d < 0 then d = d + 1 end
  return d
end

--- Find the next brake point ahead of the car. Returns the brake-point table
--- and the spline-distance ahead (0..1). Falls back through the segment list
--- if brakingPoints.best is empty.
local function findNextBrake(carSp, brakes, segments)
  local bestEntry, bestDelta
  if type(brakes) == "table" and #brakes > 0 then
    for i = 1, #brakes do
      local bp = brakes[i]
      if bp and bp.spline then
        local d = forwardSplineDelta(carSp, bp.spline)
        if d > 1e-9 and (bestDelta == nil or d < bestDelta) then
          bestEntry = bp
          bestDelta = d
        end
      end
    end
  end
  if bestEntry then
    return bestEntry, bestDelta
  end
  -- Fallback: scan segments for the next brake-or-corner kind.
  if type(segments) == "table" and #segments > 0 then
    for i = 1, #segments do
      local seg = segments[i]
      if seg and (seg.kind == "brake" or seg.kind == "corner") then
        local sp = seg.brakeSpline or seg.s0 or 0
        local d = forwardSplineDelta(carSp, sp)
        if d > 1e-9 and (bestDelta == nil or d < bestDelta) then
          bestEntry = {
            spline = sp,
            entrySpeed = seg.entrySpeed,
            label = seg.label,
          }
          bestDelta = d
        end
      end
    end
  end
  return bestEntry, bestDelta
end

--- Resolve a corner label for a brake-point spline by walking the segment
--- list. Used when brakingPoints.best entries don't carry their own labels.
local function resolveCornerLabel(brakePoint, segments)
  if not brakePoint then return nil end
  if type(brakePoint.label) == "string" and brakePoint.label ~= "" then
    return brakePoint.label
  end
  if type(segments) ~= "table" then return nil end
  local target = brakePoint.spline or 0
  local bestLabel, bestDist
  for i = 1, #segments do
    local seg = segments[i]
    if seg and seg.kind == "corner" then
      local s = seg.brakeSpline or seg.s0 or 0
      local d = math.abs(s - target)
      if d > 0.5 then d = 1 - d end
      if bestDist == nil or d < bestDist then
        bestDist = d
        bestLabel = seg.label
      end
    end
  end
  return bestLabel
end

--- Is the car currently inside a corner segment?
local function inCornerSegment(carSp, segments)
  if type(segments) ~= "table" then return false, nil end
  local sp = wrap01(carSp)
  for i = 1, #segments do
    local seg = segments[i]
    if seg and seg.kind == "corner" then
      local s0, s1 = seg.s0 or 0, seg.s1 or 0
      local inside
      if s1 > s0 then
        inside = sp >= s0 and sp <= s1
      else
        inside = sp >= s0 or sp <= s1
      end
      if inside then
        return true, seg
      end
    end
  end
  return false, nil
end

--- Linear interpolate the reference speed at a spline position from a
--- best-lap trace (sorted by spline ascending). Each sample must have
--- `.spline` and `.speed`. Returns nil if the trace is missing or too short.
local function refSpeedAtSpline(trace, sp)
  if type(trace) ~= "table" or #trace < 2 then return nil end
  local n = #trace
  local s = wrap01(sp)
  if s <= trace[1].spline then return tonumber(trace[1].speed) end
  if s >= trace[n].spline then return tonumber(trace[n].speed) end
  local lo, hi = 1, n
  while hi - lo > 1 do
    local mid = math.floor((lo + hi) / 2)
    if trace[mid].spline <= s then lo = mid else hi = mid end
  end
  local a, b = trace[lo], trace[hi]
  local ds = b.spline - a.spline
  if ds <= 1e-9 then return tonumber(a.speed) end
  local t = (s - a.spline) / ds
  local va, vb = tonumber(a.speed), tonumber(b.speed)
  if not va or not vb then return nil end
  return va + t * (vb - va)
end

-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

--- Place-holder viewmodel for the empty state. Returned when the app has zero
--- reference data — keeps both tiles painted with sensible copy.
local function placeholderView(carSp, curSpeed)
  return {
    primaryLine = "DRIVE A LAP",
    secondaryLine = "REFERENCE WILL APPEAR",
    kind = "placeholder",
    subState = "no_reference",
    cornerLabel = nil,
    targetSpeedKmh = nil,
    currentSpeedKmh = curSpeed,
    distToBrakeM = nil,
    progressPct = 0,
    brakeIndex = nil,
  }
end

--- Live-frame tick. Always returns a viewmodel (never nil).
---@param opts table  {splinePos, currentSpeedKmh, bestSortedTrace, brakingPoints, segments, trackLengthM, approachMeters, dt}
---@return table viewmodel
function M.tick(opts)
  opts = opts or {}
  local sp        = wrap01(tonumber(opts.splinePos) or 0)
  local cur       = tonumber(opts.currentSpeedKmh) or 0
  local trace     = opts.bestSortedTrace
  local brakes    = opts.brakingPoints or {}
  local segments  = opts.segments or {}
  local trackLen  = tonumber(opts.trackLengthM) or 0
  local approachM = tonumber(opts.approachMeters)
  if not approachM or approachM ~= approachM or approachM <= 0 then
    approachM = APPROACH_DEFAULT_M
  end
  local dt = tonumber(opts.dt) or 0
  if dt > 0 then monoClock = monoClock + dt end

  -- Empty state — no reference at all
  local hasTrace    = type(trace) == "table" and #trace >= 2
  local hasBrakes   = type(brakes) == "table" and #brakes > 0
  local hasSegments = type(segments) == "table" and #segments > 0
  if not hasTrace and not hasBrakes and not hasSegments then
    lastView = placeholderView(sp, cur)
    return lastView
  end

  -- Find the next braking opportunity ahead of the car
  local nextBrake, nextDelta = findNextBrake(sp, brakes, segments)
  local distToBrakeM
  if nextBrake and nextDelta and trackLen > 0 then
    distToBrakeM = nextDelta * trackLen
  end
  local cornerLabel = resolveCornerLabel(nextBrake, segments)
  local targetSpeed = nextBrake and tonumber(nextBrake.entrySpeed) or nil

  -- Are we currently inside a corner segment?
  -- In-corner override: when the car is INSIDE a known corner segment,
  -- the in-corner label takes priority over any next-corner-ahead label.
  -- Otherwise the HUD would say "CARRY MORE SPEED" while showing the next
  -- corner's label, which is misleading mid-turn.
  local inCorner, cornerSeg = inCornerSegment(sp, segments)
  if inCorner and cornerSeg and cornerSeg.label then
    cornerLabel = cornerSeg.label
  end

  -- Reference speed at this exact spline position
  local refSpeed = hasTrace and refSpeedAtSpline(trace, sp) or nil

  -- Build the structured viewmodel that BOTH tiles consume
  local view = {
    primaryLine     = nil,
    secondaryLine   = nil,
    kind            = "info",
    subState        = "cruising",
    cornerLabel     = cornerLabel,
    targetSpeedKmh  = targetSpeed,
    currentSpeedKmh = cur,
    distToBrakeM    = distToBrakeM,
    progressPct     = 0,
    brakeIndex      = nil,
  }

  if distToBrakeM and distToBrakeM <= approachM then
    view.progressPct = clamp(1 - (distToBrakeM / approachM), 0, 1)
  end

  -- ----- Live-frame priority rules (one hint at a time) -----

  if distToBrakeM and targetSpeed and distToBrakeM <= BRAKE_NOW_DIST_M
      and cur > targetSpeed + BRAKE_OVER_KMH then
    view.primaryLine = "BRAKE NOW"
    view.secondaryLine = string.format("TARGET %.0f KM/H", targetSpeed)
    view.kind = "brake"
    view.subState = "braking"

  elseif distToBrakeM and targetSpeed and distToBrakeM <= PREPARE_DIST_M
      and cur > targetSpeed + PREPARE_OVER_KMH then
    view.primaryLine = "PREPARE TO BRAKE"
    view.secondaryLine = cornerLabel and ("NEXT: " .. cornerLabel) or "NEXT TURN"
    view.kind = "brake"
    view.subState = "approaching"

  elseif inCorner and refSpeed and cur < refSpeed - CORNER_DELTA_KMH then
    view.primaryLine = "CARRY MORE SPEED"
    view.secondaryLine = string.format("%+.0f KM/H VS REFERENCE", cur - refSpeed)
    view.kind = "line"
    view.subState = "in_corner"

  elseif inCorner and refSpeed and cur > refSpeed + CORNER_DELTA_KMH then
    view.primaryLine = "EASE OFF"
    view.secondaryLine = string.format("%+.0f KM/H VS REFERENCE", cur - refSpeed)
    view.kind = "line"
    view.subState = "in_corner"

  elseif distToBrakeM and distToBrakeM <= approachM and cornerLabel then
    -- We're inside the approach window but not yet too fast — show "approaching"
    -- copy so the bottom tile has something to display.
    view.primaryLine = "APPROACHING"
    view.secondaryLine = "NEXT: " .. cornerLabel
    view.kind = "info"
    view.subState = "approaching"

  else
    -- Free flowing
    view.primaryLine = "ON PACE"
    view.secondaryLine = cornerLabel and ("NEXT: " .. cornerLabel) or "FREE LAP"
    view.kind = "info"
    view.subState = "cruising"
  end

  -- Dedupe: hold the last hint for ~600 ms before re-emitting an identical
  -- (kind, subState, cornerLabel, primaryLine) tuple so the UI doesn't flicker
  -- on threshold edges. Including subState + primaryLine ensures escalations
  -- like PREPARE TO BRAKE → BRAKE NOW (same kind, same corner) are NOT
  -- collapsed and the urgent hint is shown immediately.
  local key = table.concat({
    tostring(view.kind or "?"),
    tostring(view.subState or "?"),
    tostring(view.cornerLabel or "?"),
    tostring(view.primaryLine or "?"),
  }, ":")
  if key == lastEmittedKey and (monoClock - lastEmittedAt) < DEDUP_HOLD_SEC and lastView then
    -- Inherit primary/secondary from the previous frame to avoid flicker
    view.primaryLine = lastView.primaryLine or view.primaryLine
    view.secondaryLine = lastView.secondaryLine or view.secondaryLine
    view.kind = lastView.kind or view.kind
  else
    lastEmittedKey = key
    lastEmittedAt = monoClock
  end

  lastView = view
  return view
end

--- Reset all module state. Called from the entry script when leaving the
--- track or starting a fresh session.
function M.reset()
  lastView = nil
  lastEmittedKey = nil
  lastEmittedAt = -1e9
  monoClock = 0
end

--- No-op kept for backward compatibility. The current live-frame engine
--- does NOT consume a precomputed segment index — `tick()` may perform short
--- linear scans over `segments` (e.g. inCornerSegment, resolveCornerLabel,
--- findNextBrake fallback). For tracks with many segments (Nordschleife 170+)
--- this could be re-introduced as a bucket index if profiling shows it matters.
---@diagnostic disable-next-line: unused-local
function M.rebuildSegmentIndex(_segments)
  -- intentionally empty (kept so existing call sites in the entry script work)
end

return M
