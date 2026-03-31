-- Subsampled driven racing line + optional 3D strip (issue #8 Part F).
-- Cost is bounded by distance culling (CULL_M) and a per-strip cap on debugLine calls so track_markers (drawn first) keeps headroom.

local M = {}

local MAX_POINTS = 500
local CULL_M = 200
-- Default max render.debugLine invocations per strip per frame (see ac_copilot_trainer draw order vs track_markers).
M.MAX_DEBUG_LINE_CALLS = 220

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

--- Height offsets for "thicker" multi-line rendering (debug lines are 1px; stacking
--- at different Y levels makes the strip visible from cockpit/chase cam).
local LINE_Y_OFFSETS = { 0.04, 0.10, 0.16, 0.22, 0.28 }

---@param car ac.StateCar|nil
---@param line table[]|nil
---@param color rgbm segment color (required; callers must pass explicit rgbm)
---@param maxCalls number|nil cap on render.debugLine calls (default M.MAX_DEBUG_LINE_CALLS)
function M.drawLineStrip(car, line, color, maxCalls)
  if not car or not car.position or not line or #line < 2 or not color then
    return
  end
  if not render then
    return
  end
  local cap = maxCalls or M.MAX_DEBUG_LINE_CALLS
  if cap < 1 then
    return
  end
  local cx, cy, cz = car.position.x, car.position.y, car.position.z
  local col = color
  local cullSq = CULL_M * CULL_M
  pcall(function()
    if not render.debugLine or not vec3 then
      return
    end
    local remaining = cap
    for i = 1, #line - 1 do
      if remaining < 1 then
        return
      end
      local a, b = line[i], line[i + 1]
      local mx = (a.x + b.x) * 0.5
      local my = (a.y + b.y) * 0.5
      local mz = (a.z + b.z) * 0.5
      if distSq(cx, cy, cz, mx, my, mz) <= cullSq then
        -- Fresh vec3 per segment/offset so the renderer cannot retain stale references (mutable reuse broke layering).
        for j = 1, #LINE_Y_OFFSETS do
          if remaining < 1 then
            return
          end
          local yOff = LINE_Y_OFFSETS[j]
          render.debugLine(
            vec3(a.x, a.y + yOff, a.z),
            vec3(b.x, b.y + yOff, b.z),
            col, col
          )
          remaining = remaining - 1
        end
      end
    end
  end)
end

return M
