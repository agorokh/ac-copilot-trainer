-- AI fast_lane.ai binary reader + reference lookup (issue #8 Part E).
-- Format varies by mod/tool; this uses a conservative stride (16-byte header + 92-byte records).

local M = {}

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
  local e = exp - 127
  local m
  if exp == 0 then
    m = mant / 8388608
  else
    m = mant / 8388608 + 1
  end
  return sign * math.ldexp(m, e)
end

local function readPointAt(s, base1)
  local x = readF32LE(s, base1 + XYZ_OFF_IN_RECORD)
  local y = readF32LE(s, base1 + XYZ_OFF_IN_RECORD + 4)
  local z = readF32LE(s, base1 + XYZ_OFF_IN_RECORD + 8)
  if x ~= x or y ~= y or z ~= z then
    return nil
  end
  return { x = x, y = y, z = z }
end

---@param sim ac.StateSim|nil
---@return string|nil
local function guessFastLanePath(sim)
  if not sim then
    return nil
  end
  local ok, folder = pcall(function()
    return ac.getFolder(ac.FolderID.Content)
  end)
  if not ok or not folder or folder == "" then
    return nil
  end
  local track = sim.track or sim.trackName or sim.trackConfiguration or "unknown"
  track = tostring(track):gsub("[^%w%.%-_]+", "_")
  -- Common AC layout: content/tracks/<track>/ai/fast_lane.ai
  return folder .. "/tracks/" .. track .. "/ai/fast_lane.ai"
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
  local p = guessFastLanePath(sim)
  if not p then
    return nil
  end
  return M.loadFastLane(p)
end

--- Nearest XZ ground distance to reference polyline (windowed scan from last index; squared dist inside loop).
---@param ref table|nil
---@param px number
---@param py number
---@param pz number
---@return number|nil dist
function M.lateralDistanceMeters(ref, px, py, pz)
  if not ref or not ref.points or #ref.points < 2 then
    return nil
  end
  local pts = ref.points
  local n = #pts
  local WINDOW = 400

  local function distSqAt(i)
    local q = pts[i]
    local dx, dz = px - q.x, pz - q.z
    return dx * dx + dz * dz
  end

  local center = ref._latScanIdx or 1
  if center < 1 or center > n then
    center = 1
  end

  local bestD2 = math.huge
  local bestI = center
  local i0 = math.max(1, center - WINDOW)
  local i1 = math.min(n, center + WINDOW)
  for i = i0, i1 do
    local d2 = distSqAt(i)
    if d2 < bestD2 then
      bestD2 = d2
      bestI = i
    end
  end

  if bestI <= i0 + 8 or bestI >= i1 - 8 then
    local stride = math.max(1, math.floor(n / 2048))
    for i = 1, n, stride do
      local d2 = distSqAt(i)
      if d2 < bestD2 then
        bestD2 = d2
        bestI = i
      end
    end
    local lo = math.max(1, bestI - WINDOW)
    local hi = math.min(n, bestI + WINDOW)
    for i = lo, hi do
      local d2 = distSqAt(i)
      if d2 < bestD2 then
        bestD2 = d2
        bestI = i
      end
    end
  end

  ref._latScanIdx = bestI
  return math.sqrt(bestD2)
end

return M
