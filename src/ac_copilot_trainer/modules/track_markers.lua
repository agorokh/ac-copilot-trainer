-- 3D brake markers: distance culling, primitive budget (see MAX_*), optional track raycast (CSP API varies by version).

local M = {}

-- Max markers considered per frame; each marker may use up to three debug primitives (cross/sphere/pillar).
local MAX_MARKERS = 50
-- Total debug draw calls budget (~50 markers × 3 primitives, when all APIs exist).
local MAX_DEBUG_PRIMITIVES = 150
local FADE_NEAR = 60
local FADE_FAR = 300
-- Cap snap cache entries so long sessions cannot grow `snapY` without bound if marker keys drift.
local MAX_SNAPY_KEYS = 256

local snapSig = ""
local snapY = {} ---@type table<string, number>

--- Fingerprint all brake points (coords + spline when present) so any edit invalidates snap cache.
local function brakeListHash(list)
  if not list or #list == 0 then
    return 0
  end
  local acc = #list * 73856093
  for i = 1, #list do
    local p = list[i]
    if p and type(p.px) == "number" and type(p.py) == "number" and type(p.pz) == "number" then
      acc = (acc * 31 + math.floor(p.px * 1000 + 0.5)) % 2147483647
      acc = (acc * 31 + math.floor(p.py * 1000 + 0.5)) % 2147483647
      acc = (acc * 31 + math.floor(p.pz * 1000 + 0.5)) % 2147483647
      if type(p.spline) == "number" then
        acc = (acc * 31 + math.floor(p.spline * 1e6 + 0.5)) % 2147483647
      end
    end
  end
  return acc
end

local function brakeListSig(list)
  if not list or #list == 0 then
    return "0"
  end
  return string.format("%d:%d", #list, brakeListHash(list))
end

local function markerCacheKey(x, y, z)
  return string.format("%.3f|%.3f|%.3f", x, y, z)
end

local function distSq(ax, ay, az, bx, by, bz)
  local dx, dy, dz = ax - bx, ay - by, az - bz
  return dx * dx + dy * dy + dz * dz
end

--- Try to drop marker onto track mesh. Signature differs across CSP builds; failures are ignored.
---@param px number
---@param py number
---@param pz number
---@return number pyAdjusted
local function snapToTrack(px, py, pz)
  local y = py
  if not physics or type(physics.raycastTrack) ~= "function" then
    return y
  end
  local ok, hit = pcall(function()
    -- Common pattern: cast down from above world point. If API differs, pcall absorbs it.
    local o ---@type any
    local d ---@type any
    if vec3 then
      o = vec3(px, py + 80, pz)
      d = vec3(0, -1, 0)
    else
      return nil
    end
    return physics.raycastTrack(o, d)
  end)
  if ok and hit and type(hit) == "table" and hit.position then
    local okPosY, posY = pcall(function()
      local pos = hit.position ---@type any
      return pos.y
    end)
    if okPosY and type(posY) == "number" then
      y = posY + 0.15
    end
  elseif ok and hit and type(hit) == "userdata" then
    local okY, yy = pcall(function()
      return hit.y
    end)
    if okY and type(yy) == "number" then
      y = yy + 0.15
    end
  end
  return y
end

---@class BrakePt
---@field spline number|nil
---@field px number
---@field py number
---@field pz number

---@param car ac.StateCar|nil
---@param best BrakePt[]|nil
---@param last BrakePt[]|nil
function M.draw(car, best, last)
  if not car or not car.position then
    return
  end
  if not render then
    return
  end
  local sig = brakeListSig(best) .. ";" .. brakeListSig(last)
  if sig ~= snapSig then
    snapSig = sig
    snapY = {}
  end
  local cx, cy, cz = car.position.x, car.position.y, car.position.z
  local items = {}
  local function addList(list, kind)
    if not list then
      return
    end
    for i = 1, #list do
      local p = list[i]
      if p and type(p.px) == "number" and type(p.py) == "number" and type(p.pz) == "number" then
        local dsq = distSq(cx, cy, cz, p.px, p.py, p.pz)
        local d = math.sqrt(dsq)
        if d <= FADE_FAR + 1 then
          items[#items + 1] = { d = d, dsq = dsq, x = p.px, y = p.py, z = p.pz, kind = kind }
        end
      end
    end
  end
  addList(best, "best")
  addList(last, "last")
  table.sort(items, function(a, b)
    return a.d < b.d
  end)
  local primitivesPerMarker = 0
  if render.debugCross then
    primitivesPerMarker = primitivesPerMarker + 1
  end
  if render.debugSphere then
    primitivesPerMarker = primitivesPerMarker + 1
  end
  if render.debugLine then
    primitivesPerMarker = primitivesPerMarker + 1
  end
  if primitivesPerMarker == 0 then
    return
  end
  local markerBudget = math.max(1, math.floor(MAX_DEBUG_PRIMITIVES / primitivesPerMarker))
  local nDraw = math.min(#items, MAX_MARKERS, markerBudget)
  for i = 1, nDraw do
    local it = items[i]
    local alpha = 1
    if it.d > FADE_NEAR then
      alpha = math.max(0.15, 1 - (it.d - FADE_NEAR) / (FADE_FAR - FADE_NEAR))
    end
    local r = 1.2
    local col ---@type any
    if type(rgbm) == "function" then
      if it.kind == "best" then
        col = rgbm(1.0, 0.15, 0.15, alpha)    -- bright red for best brake points
      else
        col = rgbm(0.95, 0.65, 0.1, alpha)     -- orange for last-lap brake points
      end
    end
    if not col then
      -- Without rgbm we cannot supply a valid color to render.* — skip this primitive.
    else
      local ck = markerCacheKey(it.x, it.y, it.z)
      local sy = snapY[ck]
      if sy == nil then
        local nKeys = 0
        for _ in pairs(snapY) do
          nKeys = nKeys + 1
        end
        if nKeys >= MAX_SNAPY_KEYS then
          snapY = {}
        end
        sy = snapToTrack(it.x, it.y, it.z)
        snapY[ck] = sy
      end
      pcall(function()
        if not vec3 then return end
        local c = vec3(it.x, sy, it.z)
        -- Draw cross + sphere + vertical pillar for maximum visibility
        if render.debugCross then
          render.debugCross(c, r, col)
        end
        if render.debugSphere then
          render.debugSphere(c, r * 0.8, col)
        end
        -- Vertical pillar so marker is visible from distance
        if render.debugLine then
          render.debugLine(c, vec3(it.x, sy + 3.0, it.z), col, col)
        end
      end)
    end
  end
end

return M
