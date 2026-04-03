-- Racing line: filled quads on track via CSP render.shaderedQuad (issue #39).
-- Replaces render.quad / GL immediate mode (not in production CSP Lua).

local ch = require("csp_helpers")

local M = {}

local MAX_POINTS = 1000
local CULL_M = 300
local STRIP_HALF_W = 0.8
local Y_OFFSET = 0.05
M.MAX_QUADS = 800

local shaderedFallbackLogged = false
local earlyReturnLogged = {}

--- HLSL: soft horizontal edges, fog-aware (acc-lua-sdk quad UVs).
local RACING_LINE_SHADER = [[
float4 main(PS_IN pin) {
  float edgeSoft = saturate(min(pin.Tex.x, 1.0 - pin.Tex.x) * 6.0);
  return pin.ApplyFog(float4(gColor.rgb, gColor.a * edgeSoft));
}
]]

local quadArgs ---@type table|nil

local function ensureQuadArgs()
  if quadArgs then
    return quadArgs
  end
  if not vec3 or not rgbm or not render then
    return nil
  end
  quadArgs = {
    async = true,
    p1 = vec3(),
    p2 = vec3(),
    p3 = vec3(),
    p4 = vec3(),
    values = { gColor = rgbm(1, 1, 1, 0.8) },
    shader = RACING_LINE_SHADER,
  }
  if render.BlendMode and render.BlendMode.AlphaBlend then
    quadArgs.blendMode = render.BlendMode.AlphaBlend
  end
  if render.DepthMode and render.DepthMode.ReadOnlyLessEqual ~= nil then
    quadArgs.depthMode = render.DepthMode.ReadOnlyLessEqual
  end
  if render.CullMode and render.CullMode.None then
    quadArgs.cullMode = render.CullMode.None
  end
  return quadArgs
end

local function setRgbm(qa0, c, r, g, b, a)
  if c.set then
    local ok = pcall(c.set, c, r, g, b, a)
    if not ok then
      qa0.values.gColor = rgbm(r, g, b, a)
    end
  else
    qa0.values.gColor = rgbm(r, g, b, a)
  end
end

local function distSq(ax, ay, az, bx, by, bz)
  local dx, dy, dz = ax - bx, ay - by, az - bz
  return dx * dx + dy * dy + dz * dz
end

local function speedColor(speed)
  if speed > 150 then
    return rgbm(0.1, 0.95, 0.2, 0.8)
  end
  if speed >= 80 then
    local t = (speed - 80) / 70
    return rgbm(1.0 - t * 0.9, 0.75 + t * 0.2, 0.05 + t * 0.15, 0.8)
  end
  local t = math.max(0, speed / 80)
  return rgbm(1.0, 0.15 + t * 0.6, 0.05, 0.8 + (1 - t) * 0.05)
end

local speedColorCache = {}
for s = 0, 200, 5 do
  speedColorCache[s] = speedColor(s)
end

local function speedColorCached(speed)
  local bucket = math.max(0, math.min(200, math.floor(speed / 5 + 0.5) * 5))
  local cached = speedColorCache[bucket]
  if cached then
    return rgbm(cached.r, cached.g, cached.b, cached.mult)
  end
  return speedColor(speed)
end

local function calcTiltHeight(speedA, speedB, segLen)
  if segLen < 0.01 then
    return 0
  end
  local decel = (speedA - speedB) / segLen
  if decel <= 0 then
    return 0
  end
  return math.min(0.5, math.max(0, decel / 15.0) * 0.5)
end

local function lineContentId(line)
  if not line or #line < 1 then
    return "0"
  end
  local a, b = line[1], line[#line]
  return string.format(
    "%d:%.1f,%.1f,%.1f:%.1f,%.1f,%.1f",
    #line,
    a.x,
    a.y,
    a.z,
    b.x,
    b.y,
    b.z
  )
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
        speed = tonumber(p.speed),
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
      speed = tonumber(p.speed),
    }
  end
  return out
end

---@param car ac.StateCar|nil
---@param line table[]|nil
---@param fallbackColor rgbm
---@param maxQuads number|nil
---@param lineStyle string|nil
function M.drawLineStrip(car, line, fallbackColor, maxQuads, lineStyle)
  if not car or not car.position or not line or #line < 2 or not fallbackColor then
    if ac and type(ac.log) == "function" and not earlyReturnLogged.miss then
      earlyReturnLogged.miss = true
      ac.log("[COPILOT] racing_line: skip draw (missing car, line, or color)")
    end
    return
  end
  if not render or not vec3 then
    if ac and type(ac.log) == "function" and not earlyReturnLogged.api then
      earlyReturnLogged.api = true
      ac.log("[COPILOT] racing_line: skip draw (render or vec3 unavailable)")
    end
    return
  end

  local lineId = lineContentId(line)
  if not earlyReturnLogged[lineId] and ac and type(ac.log) == "function" then
    earlyReturnLogged[lineId] = true
    local withSpeed = 0
    for si = 1, #line do
      if line[si].speed ~= nil then
        withSpeed = withSpeed + 1
      end
    end
    ac.log(string.format(
      "[COPILOT] racing_line speed diag: %d/%d points have speed data",
      withSpeed,
      #line
    ))
    if #line >= 2 and line[1].speed ~= nil and line[2].speed ~= nil then
      local sampleLen = math.sqrt((line[2].x - line[1].x) ^ 2 + (line[2].z - line[1].z) ^ 2)
      local sampleTilt = calcTiltHeight(line[1].speed, line[2].speed, sampleLen)
      ac.log(string.format(
        "[COPILOT] racing_line tilt diag: sample tiltH=%.4f (spd %.1f->%.1f, len=%.1f)",
        sampleTilt,
        line[1].speed,
        line[2].speed,
        sampleLen
      ))
    end
  end

  local hasSq = type(render.shaderedQuad) == "function"
  local qa = ensureQuadArgs()
  if not hasSq or not qa then
    if not shaderedFallbackLogged and ac and type(ac.log) == "function" then
      shaderedFallbackLogged = true
      ac.log("[COPILOT] racing_line: render.shaderedQuad missing — no racing line (#39)")
    end
    return
  end

  local cap = maxQuads or M.MAX_QUADS
  local cx, cy, cz = car.position.x, car.position.y, car.position.z
  local cullSq = CULL_M * CULL_M
  local hw = STRIP_HALF_W
  local style = lineStyle or "tilt"
  if style ~= "tilt" and style ~= "flat" then
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT] racing_line: unsupported lineStyle '" .. tostring(style) .. "', flat")
    end
    style = "flat"
  end
  local useTilt = style == "tilt"
  local prevTiltH = 0

  pcall(function()
    if type(render.setBlendMode) == "function" and render.BlendMode and render.BlendMode.AlphaBlend then
      pcall(render.setBlendMode, render.BlendMode.AlphaBlend)
    end
    if type(render.setDepthMode) == "function" and render.DepthMode and render.DepthMode.ReadOnlyLessEqual ~= nil then
      pcall(render.setDepthMode, render.DepthMode.ReadOnlyLessEqual)
    end
    if type(render.setCullMode) == "function" and render.CullMode and render.CullMode.None then
      pcall(render.setCullMode, render.CullMode.None)
    end

    local remaining = cap
    for i = 1, #line - 1 do
      if remaining < 1 then
        break
      end
      local a, b = line[i], line[i + 1]
      local mx = (a.x + b.x) * 0.5
      local my = (a.y + b.y) * 0.5
      local mz = (a.z + b.z) * 0.5
      local segDrawn = false
      if distSq(cx, cy, cz, mx, my, mz) <= cullSq then
        local dx, dz = b.x - a.x, b.z - a.z
        local len = math.sqrt(dx * dx + dz * dz)
        if len > 0.01 then
          local nx, nz = -dz / len * hw, dx / len * hw
          local ay_off = a.y + Y_OFFSET
          local by_off = b.y + Y_OFFSET
          local frontTiltH, backTiltH = 0, 0
          if useTilt then
            local sA = a.speed or 0
            local sB = b.speed or 0
            backTiltH = calcTiltHeight(sA, sB, len)
            frontTiltH = prevTiltH
          end
          prevTiltH = backTiltH

          local v1x, v1y, v1z = a.x - nx, ay_off + frontTiltH, a.z - nz
          local v2x, v2y, v2z = a.x + nx, ay_off + frontTiltH, a.z + nz
          local v3x, v3y, v3z = b.x + nx, by_off + backTiltH, b.z + nz
          local v4x, v4y, v4z = b.x - nx, by_off + backTiltH, b.z - nz

          local color
          if a.speed ~= nil or b.speed ~= nil then
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

          ch.setV3(qa.p1, v1x, v1y, v1z)
          ch.setV3(qa.p2, v2x, v2y, v2z)
          ch.setV3(qa.p3, v3x, v3y, v3z)
          ch.setV3(qa.p4, v4x, v4y, v4z)
          setRgbm(qa, qa.values.gColor, color.r, color.g, color.b, color.mult)

          local okDraw = pcall(render.shaderedQuad, qa)
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
