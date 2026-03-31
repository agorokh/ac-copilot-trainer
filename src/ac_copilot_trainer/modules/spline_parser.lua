-- AI fast_lane.ai binary reader + reference lookup (issue #8 Part E).
-- Format varies by mod/tool; this uses a conservative stride (16-byte header + 92-byte records).

local M = {}

local function sanitizeId(s, fallback)
  s = tostring(s or fallback or "unknown"):gsub("[^%w%.%-_]+", "_")
  if s == "" then
    s = fallback or "unknown"
  end
  return s
end

local function safeTrackIdRaw()
  if not ac or type(ac.getTrackID) ~= "function" then
    return nil
  end
  local ok, v = pcall(ac.getTrackID)
  if not ok then
    return nil
  end
  return v
end

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
---@param sim ac.StateSim|nil
---@return string[]
local function fastLaneCandidatePaths(sim)
  if not sim then
    return {}
  end
  local ok, folder = pcall(function()
    return ac.getFolder(ac.FolderID.Content)
  end)
  if not ok or not folder or folder == "" then
    return {}
  end
  local trackId = sanitizeId(safeTrackIdRaw(), "unknown")
  local layoutRaw = ac.getTrackLayout and ac.getTrackLayout() or nil
  local layoutId = layoutRaw ~= nil and sanitizeId(layoutRaw, "") or ""
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
