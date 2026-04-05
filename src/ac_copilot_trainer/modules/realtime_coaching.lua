-- Real-time per-corner coaching engine (issue #57 Part D).
-- State machine: straight -> approaching -> braking -> corner -> exiting -> straight.
-- O(1) spline lookup via quantized bucket index for Nordschleife (170+ segments).

local coachingHints = require("coaching_hints")

local M = {}

-- ---------------------------------------------------------------------------
-- Constants
-- ---------------------------------------------------------------------------

local NUM_BUCKETS = 1000          -- quantization resolution for O(1) lookup
local EXIT_WINDOW_SPLINE = 0.008  -- spline distance past corner s1 for "exiting" phase
local APPROACH_DEFAULT_M = 200    -- fallback approach distance in meters

-- ---------------------------------------------------------------------------
-- Module state (reset via M.reset)
-- ---------------------------------------------------------------------------

local phase = "straight"           ---@type string
local currentCornerLabel = nil     ---@type string|nil
local activeHint = nil             ---@type table|nil  {text, kind, cornerLabel}
local hintShownThisLap = {}        ---@type table<string, boolean>  "T5_3" -> true
local lastLapCount = 0
local exitSplineTarget = nil       ---@type number|nil  spline position where exiting ends

-- Segment index: buckets[i] = segment index or nil
local buckets = {}                 ---@type (integer|nil)[]
local indexedSegments = {}         ---@type table[]
local indexBuilt = false

-- Precomputed sorted list of brake/corner segment spline starts for O(1) approach scan.
local brakeCornerStarts = {}       ---@type {s0: number, idx: integer}[]

-- ---------------------------------------------------------------------------
-- Bucket-based O(1) segment index
-- ---------------------------------------------------------------------------

local function wrap01(x)
  local s = x % 1
  if s < 0 then s = s + 1 end
  return s
end

--- Circular spline distance (handles wrap-around near start/finish).
---@param a number
---@param b number
---@return number  always in [0, 0.5]
local function splineDist(a, b)
  local d = math.abs(a - b)
  return math.min(d, 1 - d)
end

--- Build the quantized bucket index from segments.
--- Each bucket maps to the segment that covers that spline range.
--- Also precomputes brakeCornerStarts for O(1) approach detection.
---@param segments table[]
function M.rebuildSegmentIndex(segments)
  buckets = {}
  indexedSegments = segments or {}
  indexBuilt = false
  brakeCornerStarts = {}
  if not segments or #segments == 0 then
    return
  end
  for b = 1, NUM_BUCKETS do
    buckets[b] = nil
  end
  for i = 1, #segments do
    local seg = segments[i]
    local s0 = seg.s0 or 0
    local s1 = seg.s1 or 0
    local isWrap = s1 <= s0
    local b0 = math.floor(s0 * NUM_BUCKETS) + 1
    local b1 = math.floor(s1 * NUM_BUCKETS) + 1
    if b0 > NUM_BUCKETS then b0 = NUM_BUCKETS end
    if b1 > NUM_BUCKETS then b1 = NUM_BUCKETS end
    if isWrap then
      for b = b0, NUM_BUCKETS do
        buckets[b] = i
      end
      for b = 1, b1 do
        buckets[b] = i
      end
    else
      for b = b0, b1 do
        buckets[b] = i
      end
    end
    -- Collect brake/corner entries for approach lookahead
    if seg.kind == "brake" or seg.kind == "corner" then
      brakeCornerStarts[#brakeCornerStarts + 1] = { s0 = s0, idx = i }
    end
  end
  -- Sort by s0 for binary search
  table.sort(brakeCornerStarts, function(a, b) return a.s0 < b.s0 end)
  indexBuilt = true
end

--- O(1) lookup: find which segment contains the given spline position.
---@param splinePos number
---@return table|nil segment, integer|nil index
local function findSegment(splinePos)
  if not indexBuilt or #indexedSegments == 0 then
    return nil, nil
  end
  local b = math.floor(wrap01(splinePos) * NUM_BUCKETS) + 1
  if b > NUM_BUCKETS then b = NUM_BUCKETS end
  local idx = buckets[b]
  if idx then
    local seg = indexedSegments[idx]
    -- Validate position is within segment range (handles quantization boundary)
    if seg then
      local s0 = seg.s0 or 0
      local s1 = seg.s1 or 0
      local sp = wrap01(splinePos)
      local inRange
      if s1 > s0 then
        inRange = sp >= s0 and sp <= s1
      else
        -- Wrap-around segment (crosses start/finish)
        inRange = sp >= s0 or sp <= s1
      end
      if inRange then
        return seg, idx
      end
    end
  end
  return nil, nil
end

-- ---------------------------------------------------------------------------
-- Next-segment lookahead (precomputed O(1) via sorted brakeCornerStarts)
-- ---------------------------------------------------------------------------

--- Find the next brake or corner segment ahead of the current spline position.
--- Uses the precomputed sorted brakeCornerStarts list for efficient lookup.
---@param splinePos number
---@return table|nil nextSeg, number|nil splineDist
local function findNextBrakeOrCorner(splinePos)
  if #brakeCornerStarts == 0 then
    return nil, nil
  end
  local sp = wrap01(splinePos)
  -- Binary search: find the first entry with s0 > sp
  local lo, hi = 1, #brakeCornerStarts
  local bestIdx = nil
  while lo <= hi do
    local mid = math.floor((lo + hi) / 2)
    if brakeCornerStarts[mid].s0 > sp then
      bestIdx = mid
      hi = mid - 1
    else
      lo = mid + 1
    end
  end
  -- If nothing ahead, wrap to the first entry
  if not bestIdx then
    bestIdx = 1
  end
  local entry = brakeCornerStarts[bestIdx]
  local seg = indexedSegments[entry.idx]
  local d = (entry.s0 - sp) % 1
  if d < 1e-9 then d = 1 end
  return seg, d
end

--- Resolve the corner label for a brake segment by finding the adjacent corner.
---@param brakeSeg table
---@param segments table[]
---@return string
local function cornerLabelForBrake(brakeSeg, segments)
  local label = brakeSeg.label or "?"
  for i = 1, #segments do
    local s = segments[i]
    if s.kind == "corner" and s.brakeSpline then
      if splineDist(s.brakeSpline, brakeSeg.s0 or 0) < 0.03 then
        return s.label
      end
    end
  end
  return label
end

-- ---------------------------------------------------------------------------
-- Hint selection (delegates to coaching_hints.buildRealTime)
-- ---------------------------------------------------------------------------

---@param cornerLabel string
---@param lapCount integer
---@param lastFeats table[]|nil
---@param bestFeats table[]|nil
---@return table|nil  {text, kind, cornerLabel}
local function selectHint(cornerLabel, lapCount, lastFeats, bestFeats)
  local key = cornerLabel .. "_" .. tostring(lapCount)
  if hintShownThisLap[key] then
    return nil
  end

  local result = coachingHints.buildRealTime(cornerLabel, lastFeats, bestFeats)
  if not result then
    return nil
  end

  hintShownThisLap[key] = true
  return {
    text = result.text,
    kind = result.kind,
    cornerLabel = cornerLabel,
  }
end

-- ---------------------------------------------------------------------------
-- State machine tick
-- ---------------------------------------------------------------------------

--- Advance the phase state machine and select hints.
--- Called once per frame from script.update.
---@param opts table
---@return table|nil activeHint  {text, kind, cornerLabel} or nil
function M.tick(opts)
  local sp = opts.splinePos or 0
  local lc = opts.lapCount or 0
  local segments = opts.segments
  local bestFeats = opts.bestCornerFeatures
  local lastFeats = opts.lastLapCornerFeats
  local trackLenM = opts.trackLengthM
  local approachM = opts.approachMeters or APPROACH_DEFAULT_M

  -- Clear dedup map and reset state on new lap
  if lc ~= lastLapCount then
    hintShownThisLap = {}
    lastLapCount = lc
    activeHint = nil
    phase = "straight"
    currentCornerLabel = nil
    exitSplineTarget = nil
  end

  -- Rebuild index if segments changed
  if segments ~= indexedSegments then
    M.rebuildSegmentIndex(segments)
  end

  if not indexBuilt or #indexedSegments == 0 then
    phase = "straight"
    activeHint = nil
    return nil
  end

  local seg, segIdx = findSegment(sp)
  local segKind = seg and seg.kind or nil

  -- Detect approaching: on a straight (or gap), check if next brake/corner is within approachMeters
  if (segKind == "straight" or segKind == nil) and trackLenM and trackLenM > 0 then
    local nextSeg, nextDist = findNextBrakeOrCorner(sp)
    if nextSeg and nextDist then
      local distM = nextDist * trackLenM
      if distM <= approachM then
        local label = nextSeg.kind == "brake"
          and cornerLabelForBrake(nextSeg, indexedSegments)
          or nextSeg.label
        if currentCornerLabel ~= label then
          currentCornerLabel = label
          activeHint = selectHint(label, lc, lastFeats, bestFeats)
        end
        phase = "approaching"
        return activeHint
      end
    end
  end

  -- Transition based on current segment kind
  if segKind == "brake" then
    local label = cornerLabelForBrake(seg, indexedSegments)
    if currentCornerLabel ~= label then
      currentCornerLabel = label
      activeHint = selectHint(label, lc, lastFeats, bestFeats)
    end
    phase = "braking"

  elseif segKind == "corner" then
    if currentCornerLabel ~= seg.label then
      currentCornerLabel = seg.label
      activeHint = selectHint(seg.label, lc, lastFeats, bestFeats)
    end
    phase = "corner"

  elseif segKind == "straight" or segKind == nil then
    if phase == "corner" then
      -- Transition to exiting: hold hint for EXIT_WINDOW_SPLINE distance
      phase = "exiting"
      exitSplineTarget = wrap01(sp + EXIT_WINDOW_SPLINE)
    elseif phase == "exiting" then
      -- Check if we have passed the exit window
      local pastExit
      if exitSplineTarget then
        local d = (sp - exitSplineTarget) % 1
        pastExit = d < 0.5
      else
        pastExit = true
      end
      if pastExit then
        phase = "straight"
        activeHint = nil
        currentCornerLabel = nil
        exitSplineTarget = nil
      end
    else
      phase = "straight"
      activeHint = nil
      currentCornerLabel = nil
      exitSplineTarget = nil
    end
  end

  return activeHint
end

-- ---------------------------------------------------------------------------
-- Accessors
-- ---------------------------------------------------------------------------

---@return 'straight'|'approaching'|'braking'|'corner'|'exiting'
function M.phase()
  return phase
end

-- ---------------------------------------------------------------------------
-- Reset
-- ---------------------------------------------------------------------------

function M.reset()
  phase = "straight"
  currentCornerLabel = nil
  activeHint = nil
  hintShownThisLap = {}
  lastLapCount = 0
  exitSplineTarget = nil
  buckets = {}
  indexedSegments = {}
  indexBuilt = false
  brakeCornerStarts = {}
end

return M
