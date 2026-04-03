-- 3D brake markers: vertical gradient walls via render.shaderedQuad (issue #39).

local ch = require("csp_helpers")

local M = {}

local MAX_MARKERS = 30
local FADE_NEAR = 80
local FADE_FAR = 400
local MAX_SNAPY_KEYS = 256

local WALL_HEIGHT = 0.6
local WALL_HALF_WIDTH = 4.0

local snapSig = ""
local snapY = {} ---@type table<string, number>
local snapYCount = 0
local noMarkersLogged = false
local sqMissingLogged = false

local BRAKE_WALL_SHADER = [[
float4 main(PS_IN pin) {
  float vertGrad = 1.0 - pin.Tex.y;
  float alpha = gCol.a * vertGrad;
  return pin.ApplyFog(float4(gCol.rgb * 1.5, alpha));
}
]]

local wallQuad ---@type table|nil

local function ensureWallQuad()
  if wallQuad then
    return wallQuad
  end
  if not vec3 or not rgbm or not render then
    return nil
  end
  wallQuad = {
    async = true,
    p1 = vec3(),
    p2 = vec3(),
    p3 = vec3(),
    p4 = vec3(),
    values = { gCol = rgbm(1, 0.1, 0.05, 0.65) },
    shader = BRAKE_WALL_SHADER,
  }
  if render.BlendMode and render.BlendMode.AlphaBlend then
    wallQuad.blendMode = render.BlendMode.AlphaBlend
  end
  if render.DepthMode and render.DepthMode.ReadOnlyLessEqual ~= nil then
    wallQuad.depthMode = render.DepthMode.ReadOnlyLessEqual
  end
  if render.CullMode and render.CullMode.None then
    wallQuad.cullMode = render.CullMode.None
  end
  return wallQuad
end

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

local function snapToTrack(px, py, pz)
  local y = py
  if not physics or type(physics.raycastTrack) ~= "function" then
    return y
  end
  local ok, hit = pcall(function()
    if not vec3 then
      return nil
    end
    return physics.raycastTrack(vec3(px, py + 80, pz), vec3(0, -1, 0))
  end)
  if ok and hit and type(hit) == "table" and hit.position then
    local okY, posY = pcall(function()
      return hit.position.y
    end)
    if okY and type(posY) == "number" then
      y = posY + 0.05
    end
  elseif ok and hit and type(hit) == "userdata" then
    local okY, yy = pcall(function()
      return hit.y
    end)
    if okY and type(yy) == "number" then
      y = yy + 0.05
    end
  end
  return y
end

---@param _list table|nil
---@param _idx number
---@param car ac.StateCar|nil
local function wallPerpendicular(_list, _idx, car)
  if car and car.look then
    local okLook, lx, lz = pcall(function()
      return car.look.x, car.look.z
    end)
    if okLook and type(lx) == "number" and type(lz) == "number" then
      local len = math.sqrt(lx * lx + lz * lz)
      if len > 0.01 then
        return -lz / len, lx / len
      end
    end
  end
  return 1, 0
end

local BEST_RGB = { r = 1.0, g = 0.1, b = 0.05 }
local BEST_ALPHA_BOTTOM = 0.65
local LAST_RGB = { r = 1.0, g = 0.6, b = 0.0 }
local LAST_ALPHA_BOTTOM = 0.4

---@param car ac.StateCar|nil
---@param _sim ac.StateSim|nil
---@param best table[]|nil
---@param last table[]|nil
function M.draw(car, _sim, best, last)
  if not car or not car.position then
    return
  end
  if not render or not vec3 then
    return
  end

  local hasSq = type(render.shaderedQuad) == "function"
  local wq = ensureWallQuad()
  if not hasSq or not wq then
    if not sqMissingLogged and ac and type(ac.log) == "function" then
      sqMissingLogged = true
      ac.log("[COPILOT] track_markers: render.shaderedQuad missing — brake walls off (#39)")
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
    if not list then
      return
    end
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
  table.sort(items, function(a, b)
    return a.d < b.d
  end)

  local nDraw = math.min(#items, MAX_MARKERS)
  if nDraw < 1 then
    if not noMarkersLogged and ac and type(ac.log) == "function" then
      noMarkersLogged = true
      ac.log("[COPILOT] track_markers: no markers in draw range (nDraw=0)")
    end
    return
  end

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

      local nx, nz = wallPerpendicular(nil, 0, car)
      local hw = WALL_HALF_WIDTH

      local glx, gly, glz = it.x - nx * hw, sy, it.z - nz * hw
      local grx, gry, grz = it.x + nx * hw, sy, it.z + nz * hw
      local tlx, tly, tlz = it.x - nx * hw, sy + WALL_HEIGHT, it.z - nz * hw
      local trx, try_, trz = it.x + nx * hw, sy + WALL_HEIGHT, it.z + nz * hw

      ch.setV3(wq.p1, glx, gly, glz)
      ch.setV3(wq.p2, grx, gry, grz)
      ch.setV3(wq.p3, trx, try_, trz)
      ch.setV3(wq.p4, tlx, tly, tlz)

      if it.kind == "best" then
        ch.setRgbmField(wq.values, "gCol", BEST_RGB.r, BEST_RGB.g, BEST_RGB.b, BEST_ALPHA_BOTTOM * fade)
      else
        ch.setRgbmField(wq.values, "gCol", LAST_RGB.r, LAST_RGB.g, LAST_RGB.b, LAST_ALPHA_BOTTOM * fade)
      end

      pcall(render.shaderedQuad, wq)
    end
  end)
  ch.restoreRenderDefaults()
end

return M
