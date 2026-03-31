-- Subsampled driven racing line + optional 3D strip (issue #8 Part F).

local M = {}

local MAX_POINTS = 500
local CULL_M = 200

local function distSq(ax, ay, az, bx, by, bz)
  local dx, dy, dz = ax - bx, ay - by, az - bz
  return dx * dx + dy * dy + dz * dz
end

---@param trace table[]|nil
---@return table[]
function M.traceToLine(trace)
  if not trace or #trace < 2 then
    return {}
  end
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
---@param color rgbm|nil
function M.drawLineStrip(car, line, color)
  if not car or not car.position or not line or #line < 2 then
    return
  end
  if not render then
    return
  end
  local cx, cy, cz = car.position.x, car.position.y, car.position.z
  local col = color or rgbm(0.2, 0.85, 0.95, 0.55)
  local cullSq = CULL_M * CULL_M
  pcall(function()
    if not render.line then
      return
    end
    for i = 1, #line - 1 do
      local a, b = line[i], line[i + 1]
      local mx = (a.x + b.x) * 0.5
      local my = (a.y + b.y) * 0.5
      local mz = (a.z + b.z) * 0.5
      if distSq(cx, cy, cz, mx, my, mz) <= cullSq then
        render.line(vec3(a.x, a.y + 0.05, a.z), vec3(b.x, b.y + 0.05, b.z), col)
      end
    end
  end)
end

return M
