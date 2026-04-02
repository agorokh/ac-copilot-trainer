-- Racing line rendered as filled quad strip on track surface.
-- render.debugLine is 1px wireframe (invisible from cockpit); render.quad draws filled geometry.
-- Issue #35: speed-based coloring, deceleration tilt, increased caps.

local ch = require("csp_helpers")

local M = {}

local MAX_POINTS = 1000
local CULL_M = 300
--- Half-width of the quad strip in meters.
local STRIP_HALF_W = 0.8
--- Y offset above track to avoid z-fighting (match Mavil ~40-50mm).
local Y_OFFSET = 0.05
--- Max quads per frame per strip call.
M.MAX_QUADS = 800
--- Log once if we fall back to 1px debugLine (issue #24 visibility caveat).
local debugLineFallbackLogged = false

local function distSq(ax, ay, az, bx, by, bz)
  local dx, dy, dz = ax - bx, ay - by, az - bz
  return dx * dx + dy * dy + dz * dz
end

--- Speed-based color: green (>150 km/h) -> yellow (80-150) -> red (<80).
--- Smooth interpolation at boundaries to avoid color discontinuities.
---@param speed number km/h
---@return rgbm color
local function speedColor(speed)
  if speed > 150 then
    return rgbm(0.1, 0.95, 0.2, 0.8)
  end
  if speed >= 80 then
    -- Yellow-to-green blend: t=0 at 80km/h (yellow), t=1 at 150km/h (green)
    local t = (speed - 80) / 70
    return rgbm(1.0 - t * 0.9, 0.75 + t * 0.2, 0.05 + t * 0.15, 0.8)
  end
  -- Red-to-yellow blend: t=0 at 0km/h (deep red), t=1 at 80km/h (orange-yellow)
  local t = math.max(0, speed / 80)
  return rgbm(1.0, 0.15 + t * 0.6, 0.05, 0.8 + (1 - t) * 0.05)
end


--- Pre-computed color cache to avoid per-segment rgbm allocation (#22).
--- Buckets at 5 km/h resolution (0-200 km/h = 41 entries).
local speedColorCache = {}
for s = 0, 200, 5 do
  speedColorCache[s] = speedColor(s)
end

--- Cached speed color lookup: snaps to nearest 5 km/h bucket.
--- Returns a fresh rgbm copy so callers cannot corrupt the cache (#31).
---@param speed number km/h
---@return rgbm
local function speedColorCached(speed)
  local bucket = math.max(0, math.min(200, math.floor(speed / 5 + 0.5) * 5))
  local cached = speedColorCache[bucket]
  if cached then
    return rgbm(cached.r, cached.g, cached.b, cached.mult)
  end
  return speedColor(speed)
end

--- Calculate tilt height from deceleration between consecutive points.
--- Higher deceleration = more tilt (trailing edge rises under braking).
---@param speedA number speed at point A (km/h)
---@param speedB number speed at point B (km/h)
---@param segLen number segment length (meters)
---@return number tiltHeight 0 to 0.5m
local function calcTiltHeight(speedA, speedB, segLen)
  if segLen < 0.01 then return 0 end
  -- decel in km/h per meter (positive when slowing down)
  local decel = (speedA - speedB) / segLen
  if decel <= 0 then return 0 end
  -- Map decel to 0-0.5m: 15 km/h/m is full tilt
  return math.min(0.5, math.max(0, decel / 15.0) * 0.5)
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
        speed = tonumber(p.speed),  -- nil preserved: "no data" vs 0 km/h
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
      speed = tonumber(p.speed),  -- nil preserved: "no data" vs 0 km/h
    }
  end
  return out
end

--- Draw the racing line with per-segment speed coloring and optional tilt.
---@param car ac.StateCar|nil
---@param line table[]|nil  Array of {x,y,z,speed}
---@param fallbackColor rgbm  Used only when speed data is unavailable
---@param maxQuads number|nil
---@param lineStyle string|nil  "flat" or "tilt" (default "tilt")
function M.drawLineStrip(car, line, fallbackColor, maxQuads, lineStyle)
  if not car or not car.position or not line or #line < 2 or not fallbackColor then return end
  if not render or not vec3 then return end

  local cap = maxQuads or M.MAX_QUADS
  local cx, cy, cz = car.position.x, car.position.y, car.position.z
  local cullSq = CULL_M * CULL_M
  local hw = STRIP_HALF_W
  local style = lineStyle or "tilt"
  if style ~= "tilt" and style ~= "flat" then
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT] racing_line: unsupported lineStyle '"
        .. tostring(style) .. "', falling back to flat")
    end
    style = "flat"
  end
  local useTilt = style == "tilt"

  local hasQuad = type(render.quad) == "function"
  local hasGl = type(render.glBegin) == "function" and type(render.glVertex) == "function"
    and type(render.glEnd) == "function" and type(render.glSetColor) == "function"
  local hasDebugLine = type(render.debugLine) == "function"
  local glQuadEnum = render.GLPrimitiveType and render.GLPrimitiveType.Quads

  if not hasQuad and not (hasGl and glQuadEnum) and not hasDebugLine then
    return
  end

  pcall(function()
    if type(render.setBlendMode) == "function" and render.BlendMode and render.BlendMode.AlphaBlend then
      pcall(render.setBlendMode, render.BlendMode.AlphaBlend)
    end
    -- ReadOnlyLessEqual: acc-lua-sdk render.DepthMode (AC::DepthMode), value 4.
    if type(render.setDepthMode) == "function" and render.DepthMode and render.DepthMode.ReadOnlyLessEqual ~= nil then
      pcall(render.setDepthMode, render.DepthMode.ReadOnlyLessEqual)
    end
    if type(render.setCullMode) == "function" and render.CullMode and render.CullMode.None then
      pcall(render.setCullMode, render.CullMode.None)
    end

    local remaining = cap
    -- Track tilt from previous segment so consecutive quads share edge heights.
    -- prevTiltH is the tilt applied to point b of the previous quad (which is
    -- point a of the current quad), so the front edge matches seamlessly.
    local prevTiltH = 0
    for i = 1, #line - 1 do
      if remaining < 1 then
        break
      end
      local a, b = line[i], line[i + 1]
      local mx = (a.x + b.x) * 0.5
      local my = (a.y + b.y) * 0.5
      local mz = (a.z + b.z) * 0.5
      -- Reset tilt state when segments are culled so stale tilt
      -- does not leak across large gaps (Bugbot #18).
      local segDrawn = false
      if distSq(cx, cy, cz, mx, my, mz) <= cullSq then
        local dx, dz = b.x - a.x, b.z - a.z
        local len = math.sqrt(dx * dx + dz * dz)
        if len > 0.01 then
          local nx, nz = -dz / len * hw, dx / len * hw
          local ay_off = a.y + Y_OFFSET
          local by_off = b.y + Y_OFFSET

          -- Deceleration-based tilt: forward edge (b, ahead of car) rises
          -- under braking like a domino. Point a's tilt inherits from the
          -- previous segment's b-edge so consecutive quads connect seamlessly.
          local frontTiltH = 0
          local backTiltH = 0
          if useTilt then
            local sA = a.speed or 0
            local sB = b.speed or 0
            backTiltH = calcTiltHeight(sA, sB, len)
            frontTiltH = prevTiltH
          end
          prevTiltH = backTiltH

          local v1 = vec3(a.x - nx, ay_off + frontTiltH, a.z - nz)
          local v2 = vec3(a.x + nx, ay_off + frontTiltH, a.z + nz)
          local v3 = vec3(b.x + nx, by_off + backTiltH, b.z + nz)
          local v4 = vec3(b.x - nx, by_off + backTiltH, b.z - nz)

          -- Per-segment speed color (use average of a and b speeds)
          -- Use speed-based color when either point has speed data;
          -- 0 km/h is valid (stationary) and maps to red via speedColor.
          local color
          if a.speed ~= nil or b.speed ~= nil then
            -- Average only available speeds; don't drag average toward 0 with nil
            local segSpeed
            if a.speed ~= nil and b.speed ~= nil then
              segSpeed = (a.speed + b.speed) * 0.5
            else
              segSpeed = a.speed or b.speed
            end
            color = speedColorCached(segSpeed)
          else
            color = fallbackColor
          end

          local okDraw = false
          if hasQuad then
            okDraw = pcall(render.quad, v1, v2, v3, v4, color)
          end
          if not okDraw and hasGl and glQuadEnum then
            okDraw = pcall(function()
              render.glSetColor(color)
              render.glBegin(glQuadEnum)
              render.glVertex(v1)
              render.glVertex(v2)
              render.glVertex(v3)
              render.glVertex(v4)
              render.glEnd()
            end)
          end
          if not okDraw and hasDebugLine then
            if not debugLineFallbackLogged and ac and type(ac.log) == "function" then
              debugLineFallbackLogged = true
              ac.log(
                "[COPILOT] racing_line: render.debugLine fallback (quad/GL missing or failed); "
                  .. "1px line may be invisible from cockpit — see #24."
              )
            end
            okDraw = pcall(
              render.debugLine,
              vec3(a.x, ay_off, a.z),
              vec3(b.x, by_off, b.z),
              color,
              color
            )
          end
          if okDraw then
            remaining = remaining - 1
            segDrawn = true
          end
        end
      end
      if not segDrawn then
        prevTiltH = 0
      end
    end
  end)
  ch.restoreRenderDefaults()
end

return M
