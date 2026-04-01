-- Racing line rendered as filled quad strip on track surface.
-- render.debugLine is 1px wireframe (invisible from cockpit); render.quad draws filled geometry.

local M = {}

local MAX_POINTS = 500
local CULL_M = 250
--- Half-width of the quad strip in meters.
local STRIP_HALF_W = 0.6
--- Y offset above track to avoid z-fighting.
local Y_OFFSET = 0.08
--- Max quads per frame per strip call.
M.MAX_QUADS = 120

local function distSq(ax, ay, az, bx, by, bz)
  local dx, dy, dz = ax - bx, ay - by, az - bz
  return dx * dx + dy * dy + dz * dz
end

---@param trace table[]|nil
---@return table[]
function M.traceToLine(trace)
  if not trace or #trace < 2 then return {} end
  local n = #trace
  if n <= MAX_POINTS then
    local out = {}
    for i = 1, n do
      local p = trace[i]
      out[i] = {
        x = tonumber(p.px) or 0,
        y = tonumber(p.py) or 0,
        z = tonumber(p.pz) or 0,
        speed = tonumber(p.speed) or 0,
      }
    end
    return out
  end
  local out = {}
  local step = (n - 1) / (MAX_POINTS - 1)
  for k = 1, MAX_POINTS do
    local idx = math.min(n, math.max(1, math.floor(0.5 + 1 + (k - 1) * step)))
    local p = trace[idx]
    out[k] = {
      x = tonumber(p.px) or 0,
      y = tonumber(p.py) or 0,
      z = tonumber(p.pz) or 0,
      speed = tonumber(p.speed) or 0,
    }
  end
  return out
end

---@param car ac.StateCar|nil
---@param line table[]|nil
---@param color rgbm
---@param maxQuads number|nil
function M.drawLineStrip(car, line, color, maxQuads)
  if not car or not car.position or not line or #line < 2 or not color then return end
  if not render or not vec3 then return end

  local cap = maxQuads or M.MAX_QUADS
  local cx, cy, cz = car.position.x, car.position.y, car.position.z
  local cullSq = CULL_M * CULL_M
  local hw = STRIP_HALF_W

  local hasQuad = type(render.quad) == "function"
  local hasGl = type(render.glBegin) == "function" and type(render.glVertex) == "function"
    and type(render.glEnd) == "function" and type(render.glSetColor) == "function"
  local hasDebugLine = type(render.debugLine) == "function"

  if not hasQuad and not hasGl and not hasDebugLine then return end

  pcall(function()
    -- Set up alpha blending + depth read-only so line sits on top of track
    if type(render.setBlendMode) == "function" then
      pcall(render.setBlendMode, render.BlendMode.AlphaBlend)
    end
    if type(render.setDepthMode) == "function" then
      pcall(render.setDepthMode, render.DepthMode.ReadOnly)
    end

    local remaining = cap
    for i = 1, #line - 1 do
      if remaining < 1 then break end
      local a, b = line[i], line[i + 1]
      local mx = (a.x + b.x) * 0.5
      local my = (a.y + b.y) * 0.5
      local mz = (a.z + b.z) * 0.5
      if distSq(cx, cy, cz, mx, my, mz) <= cullSq then
        -- Direction vector and perpendicular for strip width
        local dx, dz = b.x - a.x, b.z - a.z
        local len = math.sqrt(dx * dx + dz * dz)
        if len > 0.01 then
          local nx, nz = -dz / len * hw, dx / len * hw
          local ay_off = a.y + Y_OFFSET
          local by_off = b.y + Y_OFFSET

          if hasQuad then
            pcall(render.quad,
              vec3(a.x - nx, ay_off, a.z - nz),
              vec3(a.x + nx, ay_off, a.z + nz),
              vec3(b.x + nx, by_off, b.z + nz),
              vec3(b.x - nx, by_off, b.z - nz),
              color)
          elseif hasGl then
            render.glSetColor(color)
            render.glBegin(render.GLPrimitiveType.Quads)
            render.glVertex(vec3(a.x - nx, ay_off, a.z - nz))
            render.glVertex(vec3(a.x + nx, ay_off, a.z + nz))
            render.glVertex(vec3(b.x + nx, by_off, b.z + nz))
            render.glVertex(vec3(b.x - nx, by_off, b.z - nz))
            render.glEnd()
          else
            -- Fallback: debugLine (1px, barely visible but better than nothing)
            render.debugLine(
              vec3(a.x, ay_off, a.z),
              vec3(b.x, by_off, b.z),
              color, color)
          end
          remaining = remaining - 1
        end
      end
    end
  end)
end

return M
