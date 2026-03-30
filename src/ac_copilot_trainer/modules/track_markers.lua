-- 3D brake markers: distance culling, max ~50 draw calls, optional track raycast (CSP API varies by version).

local M = {}

local MAX_PRIMITIVES = 50
local FADE_NEAR = 40
local FADE_FAR = 200

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
  if ok and hit and type(hit) == "table" and hit.position and hit.position.y then
    y = hit.position.y + 0.15
  elseif ok and hit and type(hit) == "userdata" then
    -- Some builds return vec3
    local yy = hit.y
    if yy then
      y = yy + 0.15
    end
  end
  return y
end

---@class BrakePt
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
  local cx, cy, cz = car.position.x, car.position.y, car.position.z
  local items = {}
  local function addList(list, kind)
    if not list then
      return
    end
    for i = 1, #list do
      local p = list[i]
      if p and p.px and p.py and p.pz then
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
  local nDraw = math.min(#items, MAX_PRIMITIVES)
  for i = 1, nDraw do
    local it = items[i]
    local alpha = 1
    if it.d > FADE_NEAR then
      alpha = math.max(0.15, 1 - (it.d - FADE_NEAR) / (FADE_FAR - FADE_NEAR))
    end
    local r = 0.65
    local col ---@type any
    if rgbm then
      if it.kind == "best" then
        col = rgbm(0.2, 0.95, 0.25, alpha)
      else
        col = rgbm(0.95, 0.9, 0.15, alpha)
      end
    end
    local sy = snapToTrack(it.x, it.y, it.z)
    pcall(function()
      -- CSP: prefer debugSphere (documented for transparent render pass). Fallbacks for older builds.
      local c ---@type any
      if vec3 then
        c = vec3(it.x, sy, it.z)
      end
      if c and render.debugSphere then
        render.debugSphere(c, r, col)
      elseif c and render.drawSphere then
        render.drawSphere(c, r, col)
      end
    end)
  end
end

return M
