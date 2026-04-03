-- Runtime render diagnostics -- MANDATORY for first 60 seconds of session.
-- Logs every render API probe, draw call attempt, and visual output.
-- Provides unfakeable visual indicators (colored spheres at known positions).
--
-- Usage:
--   local renderDiag = require("render_diag")
--   -- In script.update:  renderDiag.tick(dt)
--   -- In script.Draw3D:  renderDiag.draw3D(car)
--   -- In windowMain:     renderDiag.drawUI()

local M = {}

local DIAG_DURATION = 60.0
local LOG_INTERVAL = 5.0

local elapsed = 0
local probeRan = false
local apiProbeResults = {}
local drawCallLog = {}
local drawCallCount = 0
local drawCallSuccess = 0
local drawCallFail = 0
local uiDrawCount = 0
local lastLogT = 0
local diagActive = true
local visualCheckpoints = {}

-- ── 1. API Surface Probe (once at startup) ──

local function probeRenderAPI()
  if probeRan then return end
  probeRan = true

  local targets = {
    "debugLine", "debugSphere", "debugCross", "debugPoint",
    "debugArrow", "debugText", "debugPlane",
    "circle", "mesh", "shaderedQuad",
    "setDepthMode", "setBlendMode", "setCullMode",
    "createMesh", "billboard", "fullscreenPass",
    -- Known non-existent (should be false)
    "quad", "triangle", "line",
    "glBegin", "glEnd", "glVertex", "glSetColor",
    "GLPrimitiveType",
  }
  local enums = { "DepthMode", "BlendMode", "CullMode" }

  if not ac or type(ac.log) ~= "function" then return end

  ac.log("[DIAG] ========== CSP RENDER API PROBE ==========")
  local ver = "unknown"
  if type(ac.getPatchVersionCode) == "function" then
    local ok, v = pcall(ac.getPatchVersionCode)
    if ok then ver = tostring(v) end
  end
  ac.log("[DIAG] CSP version: " .. ver)

  for _, key in ipairs(targets) do
    local exists, kind = false, "nil"
    if render then
      local ok, val = pcall(function() return render[key] end)
      if ok and val ~= nil then exists = true; kind = type(val) end
    end
    apiProbeResults["render." .. key] = { exists = exists, kind = kind }
    ac.log(string.format("[DIAG] render.%s: %s (%s)",
      key, exists and "EXISTS" or "MISSING", kind))
  end

  for _, key in ipairs(enums) do
    local exists, values = false, {}
    if render then
      local ok, ns = pcall(function() return render[key] end)
      if ok and ns ~= nil then
        exists = true
        if type(ns) == "table" then
          for k, v in pairs(ns) do values[#values + 1] = k .. "=" .. tostring(v) end
        end
      end
    end
    apiProbeResults["render." .. key] = { exists = exists, kind = "enum" }
    ac.log(string.format("[DIAG] render.%s: %s [%s]",
      key, exists and "EXISTS" or "MISSING", table.concat(values, ", ")))
  end

  ac.log("[DIAG] vec3=" .. tostring(vec3 ~= nil)
    .. " rgbm=" .. tostring(rgbm ~= nil)
    .. " ui=" .. tostring(ui ~= nil)
    .. " physics=" .. tostring(physics ~= nil))
  ac.log("[DIAG] ========== END PROBE ==========")
end

-- ── 2. Draw Call Tracking ──

---@return boolean ok Lua pcall success for fn
function M.trackedDraw(name, fn)
  drawCallCount = drawCallCount + 1
  local ok, err = pcall(fn)
  if ok then
    drawCallSuccess = drawCallSuccess + 1
  else
    drawCallFail = drawCallFail + 1
    if ac and type(ac.log) == "function" then
      ac.log(string.format("[DIAG] DRAW FAIL: %s -- %s", name, tostring(err)))
    end
  end
  if not drawCallLog[name] then drawCallLog[name] = { ok = 0, fail = 0 } end
  if ok then
    drawCallLog[name].ok = drawCallLog[name].ok + 1
  else
    drawCallLog[name].fail = drawCallLog[name].fail + 1
  end
  return ok
end

-- ── 3. Visual Verification Indicators ──

local function drawVisualIndicators(car)
  if not car or not car.position or not vec3 or not rgbm or not render then return end
  local cx, cy, cz = car.position.x, car.position.y, car.position.z

  local cp1, cp2, cp3 = false, false, false

  if type(render.debugSphere) == "function" then
    local lx, lz = 0, 1
    if car.look then
      local okL, llx, llz = pcall(function() return car.look.x, car.look.z end)
      if okL then lx, lz = llx, llz end
    end
    -- Right vector in XZ plane (90° CCW from forward) so "green = right" matches car heading.
    local rx, rz = lz, -lx
    cp1 = M.trackedDraw("diag_sphere_ahead", function()
      render.debugSphere(vec3(cx + lx * 5, cy + 1, cz + lz * 5), 0.3, rgbm(1, 0, 0, 0.9))
    end)
    cp2 = M.trackedDraw("diag_sphere_right", function()
      render.debugSphere(vec3(cx + rx * 5, cy + 1.5, cz + rz * 5), 0.3, rgbm(0, 1, 0, 0.9))
    end)
  end

  if type(render.debugLine) == "function" then
    cp3 = M.trackedDraw("diag_debug_line", function()
      render.debugLine(vec3(cx, cy, cz), vec3(cx, cy + 3, cz), rgbm(0, 0, 1, 1), rgbm(0, 0, 1, 1))
    end)
  end

  visualCheckpoints = {
    { name = "RED sphere 5m ahead", ok = cp1 },
    { name = "GREEN sphere 5m right", ok = cp2 },
    { name = "BLUE vertical line", ok = cp3 },
  }
end

-- ── 4. Periodic Summary ──

local function logSummary()
  if not ac or type(ac.log) ~= "function" then return end
  ac.log(string.format("[DIAG] t=%.0fs  draw=%d ok=%d fail=%d ui=%d",
    elapsed, drawCallCount, drawCallSuccess, drawCallFail, uiDrawCount))
  for name, s in pairs(drawCallLog) do
    if s.fail > 0 then
      ac.log(string.format("[DIAG]   %s: %d ok %d FAIL", name, s.ok, s.fail))
    end
  end
  for _, cp in ipairs(visualCheckpoints) do
    ac.log(string.format("[DIAG] CHECKPOINT: %s -- %s",
      cp.name, cp.ok and "VISIBLE" or "NOT_RENDERED"))
  end
end

-- ── 5. Public API ──

function M.tick(dt)
  if not diagActive then return end
  elapsed = elapsed + (dt or 0)
  if not probeRan then probeRenderAPI() end
  if elapsed - lastLogT >= LOG_INTERVAL then lastLogT = elapsed; logSummary() end
  if elapsed >= DIAG_DURATION then
    logSummary()
    if ac and type(ac.log) == "function" then
      ac.log("[DIAG] Diagnostic period ended (60s).")
      if drawCallSuccess == 0 and drawCallCount > 0 then
        ac.log("[DIAG] *** CRITICAL: ZERO successful tracked draws in 60s ***")
      elseif drawCallCount == 0 then
        ac.log("[DIAG] No tracked draw attempts (debugSphere/debugLine missing?)")
      end
    end
    diagActive = false
  end
end

function M.draw3D(car)
  if not diagActive then return end
  drawVisualIndicators(car)
end

function M.drawUI()
  if not diagActive then return end
  uiDrawCount = uiDrawCount + 1
  if not ui or type(ui.textColored) ~= "function" or not rgbm then return end
  local h = rgbm(1, 0.8, 0, 1)
  ui.textColored(h, string.format("[DIAG] %.0fs/%ds", elapsed, DIAG_DURATION))
  ui.textColored(h, string.format("Draw: %d ok / %d fail", drawCallSuccess, drawCallFail))
  for _, cp in ipairs(visualCheckpoints) do
    local col = cp.ok and rgbm(0, 1, 0, 1) or rgbm(1, 0, 0, 1)
    ui.textColored(col, string.format("  %s: %s", cp.name, cp.ok and "OK" or "FAIL"))
  end
end

--- Reset all diagnostic state (e.g. after leaving track / new session without Lua reload).
function M.reset()
  elapsed = 0
  probeRan = false
  apiProbeResults = {}
  drawCallLog = {}
  drawCallCount = 0
  drawCallSuccess = 0
  drawCallFail = 0
  uiDrawCount = 0
  lastLogT = 0
  diagActive = true
  visualCheckpoints = {}
end

return M
