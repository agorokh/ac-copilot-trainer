-- 3D brake markers: gradient discs on track (render.circle center + borderColor fade).
-- Best = crimson, last = bright blue; ReadOnlyLessEqual depth for occlusion without z-fight.
-- Issue #35: brighter last-lap color, larger radius, concentric gradient circles.

local ch = require("csp_helpers")

local M = {}

local MAX_MARKERS = 30
local FADE_NEAR = 80
local FADE_FAR = 400
local MAX_SNAPY_KEYS = 256
local DISC_RADIUS = 6.0

local snapSig = ""
local snapY = {} ---@type table<string, number>
local snapYCount = 0
local circleMissingLogged = false
--- Cached flag: does render.circle accept borderColor (5-arg form)?
--- nil = not yet probed, true/false = probed result.
local circleSupportsBorder = nil

--- Module-level base colors: avoid per-marker allocation (#23/#25).
local BEST_BASE_COL = { r = 1.0, g = 0.05, b = 0.05 }
local LAST_BASE_COL = { r = 0.4, g = 0.6, b = 1.0 }

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

--- Probe once whether render.circle accepts the 5-arg borderColor form.
--- Result cached in circleSupportsBorder; hot path then calls directly.
local function probeBorderSupport(pos, up, radius, col, borderCol)
  if circleSupportsBorder ~= nil then return end
  local ok = pcall(render.circle, pos, up, radius, col, borderCol)
  circleSupportsBorder = ok
end

--- Draw concentric gradient circles for a single marker.
--- Renders 3 circles from large to small with increasing alpha for gradient effect.
--- Uses cached border-support probe to avoid repeated pcall in hot path.
local function drawGradientDisc(pos, up, radius, baseCol, fade)
  -- Outer ring: large, faint
  local outerAlpha = math.max(0.08, 0.20 * fade)
  local outerCol = rgbm(baseCol.r, baseCol.g, baseCol.b, outerAlpha)
  local outerBorder = rgbm(baseCol.r * 0.5, baseCol.g * 0.5, baseCol.b * 0.5, 0)
  -- First call probes border support; subsequent calls skip pcall.
  if circleSupportsBorder == nil then
    probeBorderSupport(pos, up, radius, outerCol, outerBorder)
    if not circleSupportsBorder then
      render.circle(pos, up, radius, outerCol)
    end
  elseif circleSupportsBorder then
    render.circle(pos, up, radius, outerCol, outerBorder)
  else
    render.circle(pos, up, radius, outerCol)
  end

  -- Middle ring
  local midAlpha = math.max(0.12, 0.40 * fade)
  local midCol = rgbm(baseCol.r, baseCol.g, baseCol.b, midAlpha)
  local midBorder = rgbm(baseCol.r * 0.4, baseCol.g * 0.4, baseCol.b * 0.4, 0)
  if circleSupportsBorder then
    render.circle(pos, up, radius * 0.6, midCol, midBorder)
  else
    render.circle(pos, up, radius * 0.6, midCol)
  end

  -- Inner core: small, bright
  local innerAlpha = math.max(0.15, 0.65 * fade)
  local innerCol = rgbm(baseCol.r, baseCol.g, baseCol.b, innerAlpha)
  render.circle(pos, up, radius * 0.3, innerCol)
end

---@param car ac.StateCar|nil
---@param _sim ac.StateSim|nil kept for call-site stability (Draw3D passes sim)
---@param best table[]|nil
---@param last table[]|nil
function M.draw(car, _sim, best, last)
  if not car or not car.position then return end
  if not render or not vec3 then return end

  local hasCircle = type(render.circle) == "function"
  if not hasCircle then
    if not circleMissingLogged and ac and type(ac.log) == "function" then
      circleMissingLogged = true
      ac.log("[COPILOT] track_markers: render.circle missing — brake discs disabled (#33)")
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
          items[#items + 1] = { d = d, x = p.px, y = p.py, z = p.pz, kind = kind }
        end
      end
    end
  end
  addList(best, "best")
  addList(last, "last")
  table.sort(items, function(a, b) return a.d < b.d end)

  local nDraw = math.min(#items, MAX_MARKERS)

  pcall(function()
    -- ReadOnlyLessEqual is AC::DepthMode in CSP (acc-lua-sdk common/ac_render_enums.lua).
    if type(render.setDepthMode) == "function" and render.DepthMode and render.DepthMode.ReadOnlyLessEqual ~= nil then
      pcall(render.setDepthMode, render.DepthMode.ReadOnlyLessEqual)
    end
    if type(render.setBlendMode) == "function" and render.BlendMode and render.BlendMode.AlphaBlend then
      pcall(render.setBlendMode, render.BlendMode.AlphaBlend)
    end
    if type(render.setCullMode) == "function" and render.CullMode and render.CullMode.None then
      pcall(render.setCullMode, render.CullMode.None)
    end

    local up = vec3(0, 1, 0)
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

      pcall(function()
        local pos = vec3(it.x, sy, it.z)
        if it.kind == "best" then
          drawGradientDisc(pos, up, DISC_RADIUS, BEST_BASE_COL, fade)
        else
          -- Brightened last-lap color (#35 Part B)
          drawGradientDisc(pos, up, DISC_RADIUS, LAST_BASE_COL, fade)
        end
      end)
    end
  end)
  ch.restoreRenderDefaults()
end

return M
