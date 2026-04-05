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
local currentSegIdx = nil          ---@type integer|nil
local currentCornerLabel = nil     ---@type string|nil
local activeHint = nil             ---@type table|nil  {text, kind, cornerLabel}
local hintShownThisLap = {}        ---@type table<string, boolean>  "T5_3" -> true
local lastLapCount = 0

-- Segment index: buckets[i] = segment index or nil
local buckets = {}                 ---@type (integer|nil)[]
local indexedSegments = {}         ---@type table[]
local indexBuilt = false

-- ---------------------------------------------------------------------------
-- Bucket-based O(1) segment index
-- ---------------------------------------------------------------------------

local function wrap01(x)
  local s = x % 1
  if s < 0 then s = s + 1 end
  return s
end

--- Build the quantized bucket index from segments.
--- Each bucket maps to the segment that covers that spline range.
---@param segments table[]
function M.rebuildSegmentIndex(segments)
  buckets = {}
  indexedSegments = segments or {}
  indexBuilt = false
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
  end
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
    return indexedSegments[idx], idx
  end
  return nil, nil
end

-- ---------------------------------------------------------------------------
-- Next-segment lookahead (for approaching detection)
-- ---------------------------------------------------------------------------

--- Find the next brake or corner segment ahead of the current spline position.
---@param splinePos number
---@param segments table[]
---@return table|nil nextSeg, number|nil splineDist
local function findNextBrakeOrCorner(splinePos, segments)
  if not segments or #segments == 0 then
    return nil, nil
  end
  local sp = wrap01(splinePos)
  local bestSeg, bestDist = nil, math.huge
  for i = 1, #segments do
    local seg = segments[i]
    if seg.kind == "brake" or seg.kind == "corner" then
      local d = (seg.s0 - sp) % 1
      if d < 1e-9 then d = 1 end
      if d < bestDist then
        bestDist = d
        bestSeg = seg
      end
    end
  end
  return bestSeg, bestDist
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
      local brakeDist = math.abs(s.brakeSpline - (brakeSeg.s0 or 0))
      if brakeDist < 0.03 then
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

  -- Clear dedup map on new lap
  if lc ~= lastLapCount then
    hintShownThisLap = {}
    lastLapCount = lc
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
    local nextSeg, nextDist = findNextBrakeOrCorner(sp, indexedSegments)
    if nextSeg and nextDist then
      local distM = nextDist * trackLenM
      if distM <= approachM then
        local label = nextSeg.kind == "brake"
          and cornerLabelForBrake(nextSeg, indexedSegments)
          or nextSeg.label
        if phase ~= "approaching" or currentCornerLabel ~= label then
          currentCornerLabel = label
          activeHint = selectHint(label, lc, lastFeats, bestFeats)
        end
        phase = "approaching"
        currentSegIdx = segIdx
        return activeHint
      end
    end
  end

  -- Transition based on current segment kind
  if segKind == "brake" then
    if phase ~= "braking" then
      local label = cornerLabelForBrake(seg, indexedSegments)
      currentCornerLabel = label
      if not activeHint then
        activeHint = selectHint(label, lc, lastFeats, bestFeats)
      end
    end
    phase = "braking"

  elseif segKind == "corner" then
    currentCornerLabel = seg.label
    if phase ~= "corner" and not activeHint then
      activeHint = selectHint(seg.label, lc, lastFeats, bestFeats)
    end
    phase = "corner"

  elseif segKind == "straight" or segKind == nil then
    if phase == "corner" then
      phase = "exiting"
    elseif phase == "exiting" then
      phase = "straight"
      activeHint = nil
      currentCornerLabel = nil
    elseif phase == "braking" then
      phase = "straight"
      activeHint = nil
      currentCornerLabel = nil
    elseif phase == "approaching" then
      phase = "straight"
      activeHint = nil
      currentCornerLabel = nil
    else
      phase = "straight"
      activeHint = nil
      currentCornerLabel = nil
    end
  end

  currentSegIdx = segIdx
  return activeHint
end

-- ---------------------------------------------------------------------------
-- Accessors
-- ---------------------------------------------------------------------------

---@return 'straight'|'approaching'|'braking'|'corner'|'exiting'
function M.phase()
  return phase
end

---@return table|nil  {text, kind, cornerLabel}
function M.activeHint()
  return activeHint
end

-- ---------------------------------------------------------------------------
-- Reset
-- ---------------------------------------------------------------------------

function M.reset()
  phase = "straight"
  currentSegIdx = nil
  currentCornerLabel = nil
  activeHint = nil
  hintShownThisLap = {}
  lastLapCount = 0
  buckets = {}
  indexedSegments = {}
  indexBuilt = false
end

return M
