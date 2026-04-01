-- 3D brake markers using render.circle + render.debugText for visibility.
-- render.debug* line/sphere/cross are 1px wireframes invisible from driving distance.
-- render.circle draws filled geometry; render.debugText draws scaled 3D labels.

local M = {}

local MAX_MARKERS = 30
local FADE_NEAR = 60
local FADE_FAR = 350
local MAX_SNAPY_KEYS = 256

local snapSig = ""
local snapY = {} ---@type table<string, number>
local snapYCount = 0
--- Lazily built once vec3 is available (see M.draw guard).
local markerUpDir ---@type any

local function brakeListHash(list)
  if not list or #list == 0 then return 0 end
  local acc = #list * 73856093
  for i = 1, #list do
    local p = list[i]
    if p and type(p.px) == "number" and type(p.py) == "number" and type(p.pz) == "number" then
      acc = (acc * 31 + math.floor(p.px * 1000 + 0.5)) % 2147483647
      acc = (acc * 31 + math.floor(p.py * 1000 + 0.5)) % 2147483647
      acc = (acc * 31 + math.floor(p.pz * 1000 + 0.5)) % 2147483647
    end
  end
  return acc
end

local function brakeListSig(list)
  if not list or #list == 0 then return "0" end
  return string.format("%d:%d", #list, brakeListHash(list))
end

local function markerCacheKey(x, y, z)
  return string.format("%.3f|%.3f|%.3f", x, y, z)
end

local function distSq(ax, ay, az, bx, by, bz)
  local dx, dy, dz = ax - bx, ay - by, az - bz
  return dx * dx + dy * dy + dz * dz
end

local function snapToTrack(px, py, pz)
  local y = py
  if not physics or type(physics.raycastTrack) ~= "function" then return y end
  local ok, hit = pcall(function()
    if not vec3 then return nil end
    return physics.raycastTrack(vec3(px, py + 80, pz), vec3(0, -1, 0))
  end)
  if ok and hit and type(hit) == "table" and hit.position then
    local okY, posY = pcall(function() return hit.position.y end)
    if okY and type(posY) == "number" then y = posY + 0.05 end
  elseif ok and hit and type(hit) == "userdata" then
    local okY, yy = pcall(function() return hit.y end)
    if okY and type(yy) == "number" then y = yy + 0.05 end
  end
  return y
end

---@param car ac.StateCar|nil
---@param best table[]|nil
---@param last table[]|nil
function M.draw(car, best, last)
  if not car or not car.position then return end
  if not render or not vec3 then return end

  local hasCircle = type(render.circle) == "function"
  local hasDbgText = type(render.debugText) == "function"
  local hasRect = type(render.rectangle) == "function"
  if not hasCircle and not hasDbgText and not hasRect then
    return
  end

  local sig = brakeListSig(best) .. ";" .. brakeListSig(last)
  if sig ~= snapSig then
    snapSig = sig
    snapY = {}
    snapYCount = 0
  end

  local cx, cy, cz = car.position.x, car.position.y, car.position.z
  local items = {}
  local function addList(list, kind)
    if not list then return end
    for i = 1, #list do
      local p = list[i]
      if p and type(p.px) == "number" and type(p.py) == "number" and type(p.pz) == "number" then
        local d = math.sqrt(distSq(cx, cy, cz, p.px, p.py, p.pz))
        if d <= FADE_FAR + 1 then
          items[#items + 1] = { d = d, x = p.px, y = p.py, z = p.pz, kind = kind }
        end
      end
    end
  end
  addList(best, "best")
  addList(last, "last")
  table.sort(items, function(a, b) return a.d < b.d end)

  local nDraw = math.min(#items, MAX_MARKERS)
  if markerUpDir == nil then
    markerUpDir = vec3(0, 1, 0)
  end
  local upDir = markerUpDir

  local function restoreMarkerRenderState()
    if type(render.setDepthMode) == "function" and render.DepthMode then
      local n = render.DepthMode.Normal
      if n ~= nil then
        pcall(render.setDepthMode, n)
      end
    end
    if type(render.setBlendMode) == "function" and render.BlendMode then
      local o = render.BlendMode.Opaque
      if o ~= nil then
        pcall(render.setBlendMode, o)
      end
    end
  end

  pcall(function()
    if type(render.setBlendMode) == "function" and render.BlendMode and render.BlendMode.AlphaBlend then
      pcall(render.setBlendMode, render.BlendMode.AlphaBlend)
    end

    for i = 1, nDraw do
      local it = items[i]
      local alpha = 1
      if it.d > FADE_NEAR then
        alpha = math.max(0.15, 1 - (it.d - FADE_NEAR) / (FADE_FAR - FADE_NEAR))
      end

      local ck = markerCacheKey(it.x, it.y, it.z)
      local sy = snapY[ck]
      if sy == nil then
        if snapYCount >= MAX_SNAPY_KEYS then
          snapY = {}
          snapYCount = 0
        end
        sy = snapToTrack(it.x, it.y, it.z)
        snapY[ck] = sy
        snapYCount = snapYCount + 1
      end

      pcall(function()
        local pos = vec3(it.x, sy, it.z)
        local col
        if it.kind == "best" then
          col = rgbm(1.0, 0.1, 0.1, alpha)
        else
          col = rgbm(1.0, 0.7, 0.0, alpha)
        end

        if hasCircle then
          pcall(render.circle, pos, upDir, 2.5, col)
        end

        if hasDbgText then
          local label = it.kind == "best" and "BRAKE" or "brake"
          pcall(render.debugText, vec3(it.x, sy + 2.5, it.z), label, col, 1.5)
        end

        if hasRect then
          local dx, dz = cx - it.x, cz - it.z
          local len = math.sqrt(dx * dx + dz * dz)
          local fwd
          if len > 0.01 then
            fwd = vec3(dx / len, 0, dz / len)
          else
            fwd = vec3(1, 0, 0)
          end
          pcall(render.rectangle, vec3(it.x, sy + 1.5, it.z), fwd, 1.5, 3.0, col)
        end
      end)
    end
  end)
  restoreMarkerRenderState()
end

return M
