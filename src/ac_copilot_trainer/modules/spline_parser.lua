-- AI fast_lane.ai binary reader + reference lookup (issue #8 Part E).
-- Format varies by mod/tool; this uses a conservative stride (16-byte header + 92-byte records).

local M = {}

local ch = require("csp_helpers")

local HEADER = 16
local STRIDE = 92
local XYZ_OFF_IN_RECORD = 0 -- try XYZ at start of payload; override if your files differ

local function readU32LE(s, i)
  local a, b, c, d = string.byte(s, i, i + 3)
  return a + b * 256 + c * 65536 + d * 16777216
end

local function readF32LE(s, i)
  local u = readU32LE(s, i)
  local sign = u >= 2147483648 and -1 or 1
  local rest = u % 2147483648
  local exp = math.floor(rest / 8388608)
  local mant = rest % 8388608
  if exp == 0 and mant == 0 then
    return 0 * sign
  end
  if exp == 255 then
    return mant == 0 and sign * math.huge or 0 / 0
  end
  if exp == 0 then
    -- Subnormal: exponent is fixed at -126, implicit leading 0.
    return sign * math.ldexp(mant / 8388608, -126)
  end
  local e = exp - 127
  local m = mant / 8388608 + 1
  return sign * math.ldexp(m, e)
end

local function isFiniteF32(v)
  return v == v and v ~= math.huge and v ~= -math.huge
end

local function readPointAt(s, base1)
  local x = readF32LE(s, base1 + XYZ_OFF_IN_RECORD)
  local y = readF32LE(s, base1 + XYZ_OFF_IN_RECORD + 4)
  local z = readF32LE(s, base1 + XYZ_OFF_IN_RECORD + 8)
  if not isFiniteF32(x) or not isFiniteF32(y) or not isFiniteF32(z) then
    return nil
  end
  return { x = x, y = y, z = z }
end

--- Ordered candidates: layout-specific first, then track root (parse may still fail per file).
---@param _sim ac.StateSim|nil unused (paths use global CSP APIs + Content folder)
---@return string[]
local function fastLaneCandidatePaths(_sim)
  local ok, folder = pcall(function()
    return ac.getFolder(ac.FolderID.Content)
  end)
  if not ok or not folder or folder == "" then
    return {}
  end
  local trackId = ch.sanitizeId(ch.safeTrackIdRaw(), "unknown")
  local layoutRaw = ch.safeTrackLayoutRaw()
  local layoutId = layoutRaw ~= nil and ch.sanitizeId(layoutRaw, "") or ""
  local root = folder .. "/tracks/" .. trackId .. "/ai/fast_lane.ai"
  local paths = {}
  if layoutId ~= "" and layoutId ~= "unknown" then
    paths[#paths + 1] = folder .. "/tracks/" .. trackId .. "/" .. layoutId .. "/ai/fast_lane.ai"
  end
  paths[#paths + 1] = root
  return paths
end

---@param path string
---@return table|nil ref
function M.loadFastLane(path)
  if not path or path == "" then
    return nil
  end
  local f = io.open(path, "rb")
  if not f then
    return nil
  end
  local data = f:read("*a")
  f:close()
  if not data or #data < HEADER + STRIDE then
    return nil
  end
  local n = math.floor((#data - HEADER) / STRIDE)
  if n < 2 then
    return nil
  end
  n = math.min(n, 120000)
  local pts = {}
  for i = 1, n do
    local base = HEADER + (i - 1) * STRIDE + 1
    local p = readPointAt(data, base)
    if p then
      pts[#pts + 1] = p
    end
  end
  if #pts < 2 then
    return { path = path, points = {}, bytes = #data, note = "parse_fail_try_stride" }
  end
  return { path = path, points = pts, bytes = #data }
end

---@param sim ac.StateSim|nil
---@return table|nil
function M.loadForTrack(sim)
  for _, p in ipairs(fastLaneCandidatePaths(sim)) do
    local ref = M.loadFastLane(p)
    if ref and ref.points and #ref.points >= 2 then
      return ref
    end
  end
  return nil
end

local centerlineCacheKey, centerlineCache

--- Derived midpoint of CSP's authored track boundaries, NOT the AI racing line.
--- SDK ac_apps/lib.lua:3114-3143: spline sides are authored boundary distances;
--- trackCoordinateToWorld X=-1/+1 selects the left/right boundary at progress Z.
--- No guessing of fast_lane.ai record strides, widths, or normals is involved.
function M.loadTrackCenterline()
  if not ac or type(ac.getTrackAISplineSides) ~= "function"
      or type(ac.trackCoordinateToWorld) ~= "function" or type(ac.getSim) ~= "function"
      or vec3 == nil then
    return nil, "authored track-boundary API unavailable"
  end
  local trackId = ch.safeTrackIdRaw()
  local layout = ch.safeTrackLayoutRaw()
  local ok, sim = pcall(ac.getSim)
  local length = ok and sim and tonumber(sim.trackLengthM) or nil
  if type(trackId) ~= "string" or trackId == "" or type(layout) ~= "string"
      or not length or not isFiniteF32(length) or length < 100 or length > 100000 then
    return nil, "authored track-boundary identity/length unavailable"
  end
  local key = trackId .. "/" .. tostring(layout) .. ":" .. tostring(length)
  if key == centerlineCacheKey and centerlineCache then return centerlineCache end
  -- Never retain a different track's geometry after an unsuccessful replacement.
  centerlineCacheKey, centerlineCache = nil, nil
  local count = math.max(96, math.min(2048, math.ceil(length / 4)))
  local points = {}
  local function sample(progress)
    local good, p = pcall(function()
      local sides = ac.getTrackAISplineSides(progress)
      if not sides or not isFiniteF32(sides.x) or not isFiniteF32(sides.y)
          or sides.x <= 0 or sides.y <= 0 then return nil end
      local left = ac.trackCoordinateToWorld(vec3(-1, 0, progress))
      local right = ac.trackCoordinateToWorld(vec3(1, 0, progress))
      if not left or not right then return nil end
      for _, axis in ipairs({ "x", "y", "z" }) do
        if not isFiniteF32(left[axis]) or not isFiniteF32(right[axis]) then return nil end
      end
      local dx, dy, dz = right.x-left.x, right.y-left.y, right.z-left.z
      local width = math.sqrt(dx*dx + dy*dy + dz*dz)
      local authoredWidth = sides.x + sides.y
      if width < 1 or width > 100 or width < authoredWidth * 0.5
          or width > authoredWidth * 1.5 then return nil end
      return { x=(left.x+right.x)*0.5, y=(left.y+right.y)*0.5,
        z=(left.z+right.z)*0.5, spline=progress, width_m=width }
    end)
    return good and p or nil
  end
  for i = 1, count do
    local p = sample((i-1)/count)
    if not p then return nil, "invalid authored track boundary" end
    points[i] = p
  end
  local finish = sample(1)
  local first = points[1]
  if not finish or (finish.x-first.x)^2 + (finish.y-first.y)^2
      + (finish.z-first.z)^2 > 4 then
    return nil, "authored track boundaries are not a closed circuit"
  end
  local arc = 0
  for i = 1, count do
    local a, b = points[i], points[i % count + 1]
    local distance = math.sqrt((a.x-b.x)^2 + (a.y-b.y)^2 + (a.z-b.z)^2)
    if distance < 0.05 or distance > length/count*4 then
      return nil, "discontinuous authored track boundaries"
    end
    arc = arc + distance
  end
  if arc < length*0.5 or arc > length*2 then
    return nil, "authored track-boundary length mismatch"
  end
  centerlineCacheKey = key
  centerlineCache = { source="csp_authored_boundaries_midpoint", derived=true,
    closed=true, track_id=trackId, layout=tostring(layout), length_m=arc, points=points }
  return centerlineCache
end

function M.clearTrackCenterlineCache()
  centerlineCacheKey, centerlineCache = nil, nil
end

--- Squared XZ distance from point to segment AB (ground plane).
local function distSqPointSegXZ(px, pz, ax, az, bx, bz)
  local dx, dz = bx - ax, bz - az
  local l2 = dx * dx + dz * dz
  if l2 < 1e-12 then
    local ex, ez = px - ax, pz - az
    return ex * ex + ez * ez
  end
  local t = ((px - ax) * dx + (pz - az) * dz) / l2
  if t < 0 then
    t = 0
  elseif t > 1 then
    t = 1
  end
  local qx, qz = ax + t * dx, az + t * dz
  local ex, ez = px - qx, pz - qz
  return ex * ex + ez * ez
end

--- Nearest XZ distance to reference polyline (true segment distance; windowed scan from last segment index).
---@param ref table|nil
---@param px number
---@param _py number|nil unused (API symmetry; lateral is XZ / ground)
---@param pz number
---@return number|nil dist
function M.lateralDistanceMeters(ref, px, _py, pz)
  if not ref or not ref.points or #ref.points < 2 then
    return nil
  end
  local pts = ref.points
  local n = #pts
  local nSeg = n - 1
  local WINDOW = 400

  local function distSqSeg(j)
    local a, b = pts[j], pts[j + 1]
    return distSqPointSegXZ(px, pz, a.x, a.z, b.x, b.z)
  end

  local center = ref._latScanSegIdx
  if center == nil and ref._latScanIdx ~= nil then
    center = math.max(1, math.min(nSeg, ref._latScanIdx))
  end
  if center == nil or center < 1 or center > nSeg then
    center = 1
  end

  local bestD2 = math.huge
  local bestJ = center
  local j0 = math.max(1, center - WINDOW)
  local j1 = math.min(nSeg, center + WINDOW)
  for j = j0, j1 do
    local d2 = distSqSeg(j)
    if d2 < bestD2 then
      bestD2 = d2
      bestJ = j
    end
  end

  if bestJ <= j0 + 8 or bestJ >= j1 - 8 then
    local stride = math.max(1, math.floor(nSeg / 2048))
    for j = 1, nSeg, stride do
      local d2 = distSqSeg(j)
      if d2 < bestD2 then
        bestD2 = d2
        bestJ = j
      end
    end
    local lo = math.max(1, bestJ - WINDOW)
    local hi = math.min(nSeg, bestJ + WINDOW)
    for j = lo, hi do
      local d2 = distSqSeg(j)
      if d2 < bestD2 then
        bestD2 = d2
        bestJ = j
      end
    end
  end

  ref._latScanSegIdx = bestJ
  ref._latScanIdx = nil
  return math.sqrt(bestD2)
end

return M
