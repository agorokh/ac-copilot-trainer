-- 3D brake markers: vertical gradient walls perpendicular to track direction.
-- Opaque at ground -> transparent at top (0.6m). Visible from cockpit at 100m+.
-- Issue #37 Part A: full rewrite from flat circles to vertical walls.
-- Issue #37 Part D: last-lap color changed from blue to orange.

local ch = require("csp_helpers")

local M = {}

local MAX_MARKERS = 30
local FADE_NEAR = 80
local FADE_FAR = 400
local MAX_SNAPY_KEYS = 256

--- Wall dimensions
local WALL_HEIGHT = 0.6     -- meters above track surface
local WALL_HALF_WIDTH = 4.0 -- half of 8m total width

local snapSig = ""
local snapY = {} ---@type table<string, number>
local snapYCount = 0
local glMissingLogged = false

--- Base colors (issue #37 Part D: last changed from blue to orange).
local BEST_COLOR_BASE = { r = 1.0, g = 0.1, b = 0.05 }
local BEST_ALPHA_BOTTOM = 0.65
local LAST_COLOR_BASE = { r = 1.0, g = 0.6, b = 0.0 }
local LAST_ALPHA_BOTTOM = 0.4

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
    if okY and type(posY) == "number" then y = posY + 0.02 end
  elseif ok and hit and type(hit) == "userdata" then
    local okY, yy = pcall(function() return hit.y end)
    if okY and type(yy) == "number" then y = yy + 0.02 end
  end
  return y
end

--- Compute a perpendicular direction for the wall at a given brake point.
--- Uses the direction from the previous brake point to the next in the list,
--- or car.look if available and the list has only one point.
---@param list table[] brake point list
---@param idx number index of current point in list
---@param car ac.StateCar|nil
---@return number nx perpendicular X component (unit)
---@return number nz perpendicular Z component (unit)
local function wallPerpendicular(_list, _idx, car)
  -- #7: Prefer car.look -- brake event neighbors are sparse and produce wrong angles.
  if car and car.look then
    local okLook, lx, lz = pcall(function() return car.look.x, car.look.z end)
    if okLook and type(lx) == "number" and type(lz) == "number" then
      local len = math.sqrt(lx * lx + lz * lz)
      if len > 0.01 then
        return -lz / len, lx / len
      end
    end
  end
  -- Last resort: wall along X axis
  return 1, 0
end

--- Draw a single vertical gradient wall quad.
--- Bottom edge is opaque, top edge is transparent.
---@param groundLeft vec3
---@param groundRight vec3
---@param topLeft vec3
---@param topRight vec3
---@param baseColor table {r, g, b}
---@param bottomAlpha number
---@param fade number 0-1 distance fade
local function drawWallQuad(groundLeft, groundRight, topLeft, topRight, baseColor, bottomAlpha, fade)
  local ba = bottomAlpha * fade
  -- #1: Pre-compute colors once per wall (not 4 separate rgbm allocations)
  local bottomCol = rgbm(baseColor.r, baseColor.g, baseColor.b, ba)
  local topCol = rgbm(baseColor.r, baseColor.g, baseColor.b, 0)
  render.glSetColor(bottomCol)
  render.glVertex(groundLeft)
  render.glSetColor(bottomCol)
  render.glVertex(groundRight)
  render.glSetColor(topCol)
  render.glVertex(topRight)
  render.glSetColor(topCol)
  render.glVertex(topLeft)
end

---@param car ac.StateCar|nil
---@param _sim ac.StateSim|nil kept for call-site stability (Draw3D passes sim)
---@param best table[]|nil
---@param last table[]|nil
function M.draw(car, _sim, best, last)
  if not car or not car.position then return end
  if not render or not vec3 then return end

  local hasGl = type(render.glBegin) == "function"
    and type(render.glVertex) == "function"
    and type(render.glEnd) == "function"
    and type(render.glSetColor) == "function"
  local glQuadEnum = render.GLPrimitiveType and render.GLPrimitiveType.Quads

  if not hasGl or not glQuadEnum then
    if not glMissingLogged and ac and type(ac.log) == "function" then
      glMissingLogged = true
      ac.log("[COPILOT] track_markers: render.glBegin/Quads missing — brake walls disabled (#37)")
    end
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
          items[#items + 1] = { d = d, x = p.px, y = p.py, z = p.pz, kind = kind, listIdx = i, list = list }
        end
      end
    end
  end
  addList(best, "best")
  addList(last, "last")
  table.sort(items, function(a, b) return a.d < b.d end)

  local nDraw = math.min(#items, MAX_MARKERS)

  pcall(function()
    if type(render.setDepthMode) == "function" and render.DepthMode and render.DepthMode.ReadOnlyLessEqual ~= nil then
      pcall(render.setDepthMode, render.DepthMode.ReadOnlyLessEqual)
    end
    if type(render.setBlendMode) == "function" and render.BlendMode and render.BlendMode.AlphaBlend then
      pcall(render.setBlendMode, render.BlendMode.AlphaBlend)
    end
    if type(render.setCullMode) == "function" and render.CullMode and render.CullMode.None then
      pcall(render.setCullMode, render.CullMode.None)
    end

    for i = 1, nDraw do
      local it = items[i]
      local fade = 1
      if it.d > FADE_NEAR then
        fade = math.max(0, 1 - (it.d - FADE_NEAR) / (FADE_FAR - FADE_NEAR))
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

      -- Compute wall perpendicular direction from brake point neighbors
      local nx, nz = wallPerpendicular(nil, 0, car)
      local hw = WALL_HALF_WIDTH

      local groundLeft = vec3(it.x - nx * hw, sy, it.z - nz * hw)
      local groundRight = vec3(it.x + nx * hw, sy, it.z + nz * hw)
      local topLeft = vec3(it.x - nx * hw, sy + WALL_HEIGHT, it.z - nz * hw)
      local topRight = vec3(it.x + nx * hw, sy + WALL_HEIGHT, it.z + nz * hw)

      render.glBegin(glQuadEnum)
      if it.kind == "best" then
        drawWallQuad(groundLeft, groundRight, topLeft, topRight,
          BEST_COLOR_BASE, BEST_ALPHA_BOTTOM, fade)
      else
        drawWallQuad(groundLeft, groundRight, topLeft, topRight,
          LAST_COLOR_BASE, LAST_ALPHA_BOTTOM, fade)
      end
      render.glEnd()
    end
  end)
  ch.restoreRenderDefaults()
end

return M
