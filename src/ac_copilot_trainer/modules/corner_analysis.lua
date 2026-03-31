-- Track segmentation, per-corner features, consistency, style-divergence (issue #8).
-- K-means/DBSCAN clustering deferred — export `lapFeatureHistory` for offline Phase 3.

local M = {}

local MAX_HISTORY_LAPS = 12
local MIN_TRACE_FOR_SEGMENTS = 24
local SPLINE_NEAR = 0.012

local function wrap01(x)
  local s = x % 1
  if s < 0 then
    s = s + 1
  end
  return s
end

---@param trace table[]
---@return number|nil, number|nil
local function traceSplineRange(trace)
  if not trace or #trace < 2 then
    return nil, nil
  end
  local lo, hi = math.huge, -math.huge
  for i = 1, #trace do
    local s = trace[i].spline
    if type(s) == "number" then
      if s < lo then
        lo = s
      end
      if s > hi then
        hi = s
      end
    end
  end
  if lo == math.huge then
    return nil, nil
  end
  return lo, hi
end

---@param brakes table[]
---@return number[]
local function brakeSplinesSorted(brakes)
  local xs = {}
  if not brakes then
    return xs
  end
  for i = 1, #brakes do
    local s = brakes[i] and brakes[i].spline
    if type(s) == "number" then
      xs[#xs + 1] = wrap01(s)
    end
  end
  table.sort(xs, function(a, b)
    return a < b
  end)
  local out = {}
  local last = nil
  for i = 1, #xs do
    if last == nil or math.abs(xs[i] - last) > 1e-6 then
      out[#out + 1] = xs[i]
      last = xs[i]
    end
  end
  return out
end

---@param trace table[]
---@param s0 number
---@param s1 number
---@param wrap boolean
---@return table|nil stats
local function statsInSplineRange(trace, s0, s1, wrap)
  s0, s1 = wrap01(s0), wrap01(s1)
  local samples = {}
  for i = 1, #trace do
    local p = trace[i]
    local sp = p.spline
    if type(sp) == "number" then
      sp = wrap01(sp)
      local inside
      if wrap then
        inside = sp >= s0 or sp < s1
      else
        inside = sp >= s0 and sp < s1
      end
      if inside then
        local ord
        if wrap then
          if sp >= s0 then
            ord = sp - s0
          else
            ord = (1 - s0) + sp
          end
        else
          ord = sp - s0
        end
        samples[#samples + 1] = { ord = ord, p = p }
      end
    end
  end
  if #samples == 0 then
    return nil
  end
  table.sort(samples, function(a, b)
    return a.ord < b.ord
  end)

  local n, sumSpd, minSpd, maxBrk, sumBrk, sumThr, sumAbsSteer = 0, 0, math.huge, 0, 0, 0, 0
  local revs = 0
  local lastSteer = nil
  for i = 1, #samples do
    local p = samples[i].p
    n = n + 1
    local v = tonumber(p.speed) or 0
    sumSpd = sumSpd + v
    if v < minSpd then
      minSpd = v
    end
    local b = tonumber(p.brake) or 0
    if b > maxBrk then
      maxBrk = b
    end
    sumBrk = sumBrk + b
    sumThr = sumThr + (tonumber(p.throttle) or 0)
    local st = tonumber(p.steer)
    if st == nil then
      st = 0
    end
    sumAbsSteer = sumAbsSteer + math.abs(st)
    if lastSteer ~= nil and (st * lastSteer < 0) and (math.abs(st - lastSteer) > 0.08) then
      revs = revs + 1
    end
    lastSteer = st
  end
  if minSpd == math.huge then
    minSpd = 0
  end
  local firstP, lastP = samples[1].p, samples[#samples].p
  local entrySpd = tonumber(firstP.speed) or 0
  local exitSpd = tonumber(lastP.speed) or 0
  return {
    n = n,
    avgSpeed = sumSpd / n,
    minSpeed = minSpd,
    maxBrake = maxBrk,
    avgBrake = sumBrk / n,
    avgThrottle = sumThr / n,
    avgAbsSteer = sumAbsSteer / n,
    steerReversals = revs,
    entrySpeed = entrySpd,
    exitSpeed = exitSpd,
  }
end

--- Build coarse segments: braking zones at brake splines + corner/straight between.
---@param trace table[]
---@param brakePoints table[]
---@return table[]
function M.buildSegments(trace, brakePoints)
  if not trace or #trace < MIN_TRACE_FOR_SEGMENTS then
    return {}
  end
  local brakes = brakeSplinesSorted(brakePoints)
  if #brakes == 0 then
    -- Single lap heuristic: speed minima as pseudo-corners
    local mins = {}
    for i = 2, #trace - 1 do
      local a, b, c = trace[i - 1].speed, trace[i].speed, trace[i + 1].speed
      if type(a) == "number" and type(b) == "number" and type(c) == "number" then
        if b <= a and b <= c and b + 8 < math.min(a, c) then
          mins[#mins + 1] = wrap01(trace[i].spline or 0)
        end
      end
    end
    table.sort(mins)
    brakes = mins
  end
  if #brakes == 0 then
    return {
      {
        kind = "straight",
        s0 = 0,
        s1 = 1,
        label = "FULL",
      },
    }
  end
  local segs = {}
  local m = #brakes
  for i = 1, m do
    local bs = brakes[i]
    local b0 = wrap01(bs - SPLINE_NEAR)
    local b1 = wrap01(bs + SPLINE_NEAR)
    segs[#segs + 1] = {
      kind = "brake",
      s0 = b0,
      s1 = b1,
      label = "B" .. tostring(i),
    }
  end
  for i = 1, m do
    local sStart = wrap01(brakes[i] + SPLINE_NEAR)
    local sEnd = wrap01(brakes[(i % m) + 1] - SPLINE_NEAR)
    local wrap = sEnd <= sStart and sEnd + 1 > sStart
    local st = statsInSplineRange(trace, sStart, sEnd, wrap)
    if st then
      local kind = "straight"
      if st.avgAbsSteer > 0.12 or st.maxBrake > 0.08 or (st.avgSpeed < 120 and st.minSpeed + 25 < st.avgSpeed) then
        kind = "corner"
      end
      segs[#segs + 1] = {
        kind = kind,
        s0 = sStart,
        s1 = sEnd,
        label = (kind == "corner") and ("T" .. tostring(i)) or ("S" .. tostring(i)),
        -- Raw brake spline for this sector (corner s0 is already offset by SPLINE_NEAR).
        brakeSpline = wrap01(brakes[i]),
      }
    end
  end
  table.sort(segs, function(a, b)
    return (a.s0 or 0) < (b.s0 or 0)
  end)
  -- Stable corner labels T1.. by spline order
  local tc = 0
  for j = 1, #segs do
    if segs[j].kind == "corner" then
      tc = tc + 1
      segs[j].label = "T" .. tostring(tc)
    end
  end
  return segs
end

---@param trace table[]
---@param segments table[]
---@return table[]
function M.cornerFeaturesForLap(trace, segments)
  if not trace or not segments then
    return {}
  end
  local out = {}
  for i = 1, #segments do
    local seg = segments[i]
    if seg.kind == "corner" then
      local s0, s1 = seg.s0, seg.s1
      local wrap = s1 <= s0
      local st = statsInSplineRange(trace, s0, s1, wrap)
      if st then
        local trailBrakeRatio = 0
        if st.maxBrake > 1e-6 then
          trailBrakeRatio = math.min(1, st.avgBrake / st.maxBrake)
        end
        -- Traction circle utilization proxy: use speed delta in sector (Phase 3 can add G-load).
        local tcUtil = math.min(1, (st.avgAbsSteer * 2.2 + st.avgBrake * 1.4 + st.avgThrottle * 0.6) / 3)
        local brg = 0
        if st.maxBrake > 1e-6 then
          brg = math.min(1, (st.maxBrake - st.avgBrake) / st.maxBrake)
        end
        local bps = seg.brakeSpline
        if type(bps) ~= "number" then
          bps = s0
        end
        out[#out + 1] = {
          label = seg.label,
          s0 = s0,
          s1 = s1,
          entrySpeed = st.entrySpeed,
          minSpeed = st.minSpeed,
          exitSpeed = st.exitSpeed,
          brakePointSpline = wrap01(bps),
          trailBrakeRatio = trailBrakeRatio,
          steerReversals = st.steerReversals,
          tractionCircleProxy = tcUtil,
          throttleAvg = st.avgThrottle,
          brakeReleaseGradient = brg,
        }
      end
    end
  end
  return out
end

---@param history table[] each { corners = table[] }
---@return table|nil summary
function M.consistencySummary(history)
  if not history or #history < 2 then
    return nil
  end
  -- Map label -> arrays of metrics
  local byLabel = {}
  for _, lap in ipairs(history) do
    local cf = lap.corners
    if type(cf) == "table" then
      for j = 1, #cf do
        local c = cf[j]
        local lab = c.label or ("T" .. tostring(j))
        local bucket = byLabel[lab]
        if not bucket then
          bucket = { entry = {}, brakeS = {}, minS = {}, exit = {} }
          byLabel[lab] = bucket
        end
        bucket.entry[#bucket.entry + 1] = tonumber(c.entrySpeed) or 0
        bucket.brakeS[#bucket.brakeS + 1] = tonumber(c.brakePointSpline) or 0
        bucket.minS[#bucket.minS + 1] = tonumber(c.minSpeed) or 0
        bucket.exit[#bucket.exit + 1] = tonumber(c.exitSpeed) or 0
      end
    end
  end
  local function stddev(arr)
    local n = #arr
    if n < 2 then
      return 0
    end
    local sum = 0
    for i = 1, n do
      sum = sum + arr[i]
    end
    local m = sum / n
    local v = 0
    for i = 1, n do
      local d = arr[i] - m
      v = v + d * d
    end
    return math.sqrt(v / (n - 1))
  end
  local scores = {}
  -- Dimensionless spread: speed stddevs scaled to ~O(1); brake spline stddev in [0,~0.5].
  local speedScale = 120
  for lab, bucket in pairs(byLabel) do
    local se = stddev(bucket.entry)
    local sm = stddev(bucket.minS)
    local sx = stddev(bucket.exit)
    local sb = stddev(bucket.brakeS)
    -- Weights sum to 1.0; brake spline spread is down-weighted (wrap risk on short tracks).
    local spread = (se / speedScale) * 0.35 + (sm / speedScale) * 0.30 + (sx / speedScale) * 0.30 + sb * 0.05
    local score = math.max(0, math.min(100, 100 - spread * 45))
    scores[#scores + 1] = { label = lab, score = score, spread = spread }
  end
  table.sort(scores, function(a, b)
    return a.score < b.score
  end)
  local worst = {}
  for i = 1, math.min(3, #scores) do
    worst[i] = string.format("%s %.0f%%", scores[i].label, scores[i].score)
  end
  return {
    perCorner = scores,
    worstThree = worst,
  }
end

--- Lightweight divergence vs best lap corner vector (not full clustering).
---@param sessionCorners table[]
---@param bestCorners table[]
---@return number|nil divergence01
function M.styleDivergence(sessionCorners, bestCorners)
  if not sessionCorners or not bestCorners or #sessionCorners == 0 or #bestCorners == 0 then
    return nil
  end
  local function pack(c)
    local rev = math.min(1, (tonumber(c.steerReversals) or 0) / 8)
    return {
      tonumber(c.trailBrakeRatio) or 0,
      rev,
      tonumber(c.tractionCircleProxy) or 0,
      tonumber(c.throttleAvg) or 0,
    }
  end
  local bestByLabel = {}
  for i = 1, #bestCorners do
    local c = bestCorners[i]
    local lab = c.label
    if type(lab) == "string" and lab ~= "" then
      bestByLabel[lab] = c
    end
  end
  local sum, ncmp = 0, 0
  for i = 1, #sessionCorners do
    local sc = sessionCorners[i]
    local lab = sc.label
    local bc = type(lab) == "string" and bestByLabel[lab] or nil
    if bc then
      local a, b = pack(sc), pack(bc)
      for k = 1, #a do
        local d = a[k] - b[k]
        sum = sum + d * d
      end
      ncmp = ncmp + 1
    end
  end
  if ncmp <= 0 then
    return nil
  end
  return math.min(1, math.sqrt(sum / (ncmp * 4)) / 1.25)
end

function M.maxHistoryLaps()
  return MAX_HISTORY_LAPS
end

function M.appendHistory(history, lapEntry)
  history[#history + 1] = lapEntry
  while #history > MAX_HISTORY_LAPS do
    table.remove(history, 1)
  end
end

M._traceSplineRange = traceSplineRange

return M
