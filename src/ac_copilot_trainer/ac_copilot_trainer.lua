-- AC Copilot Trainer v0.4.2
local APP_VERSION_UI = "v0.4.2"
-- https://github.com/agorokh/ac-copilot-trainer
-- Issues #6–#8: telemetry, traces, delta, markers, throttle, corner analysis, tires, setup.

do
  local origin = ac.getFolder(ac.FolderID.ScriptOrigin)
  if origin and origin ~= "" then
    package.path = origin .. "/modules/?.lua;" .. package.path
  end
end

local telemetryMod = require("telemetry")
local brakeMod = require("brake_detection")
local persistence = require("persistence")
local hud = require("hud")
local delta = require("delta")
local trackMarkers = require("track_markers")
local throttleDet = require("throttle_detection")
local cornerAnalysis = require("corner_analysis")
local splineParser = require("spline_parser")
local racingLine = require("racing_line")
local tireMonitor = require("tire_monitor")
local setupReader = require("setup_reader")
local coachingHints = require("coaching_hints")
local coachingOverlay = require("coaching_overlay")
local wsBridge = require("ws_bridge")
local sessionJournal = require("session_journal")
local ch = require("csp_helpers")
local renderDiag = require("render_diag")

local sim ---@type ac.StateSim
local car ---@type ac.StateCar

local config = {
  brakeThreshold = 0.3,
  brakeDurationMin = 0.5,
  bufferSeconds = 30,
  hudEnabled = true,
  approachMeters = 200,
  coastWarnSeconds = 1.0,
  postLapHoldSeconds = 5,
  sectorMessageSeconds = 3,
  autoLoadSetup = true,
  racingLineMode = "best",
  --- Verbose: log Draw3D/data counts every ~2s to `ac.log` (troubleshooting only).
  enableDraw3DDiagnostics = false,
  --- When true, runs `render_diag` (60s API probe, debug spheres/lines, [DIAG] UI). Default off (issue #41).
  enableRenderDiagnostics = false,
  --- After each lap; issue #9 Part A mentioned ~8s for minimal HUD intrusion — default 30 keeps the
  --- Coaching window readable; tune down if you want shorter toasts (issue #43).
  coachingHoldSeconds = 30,
  --- Max coaching lines shown in the Coaching window and reflected in the main-window strip (1–3).
  --- `coaching_hints.buildAfterLap` still ranks weakest corners first; this only caps display density.
  coachingMaxVisibleHints = 3,
  --- Racing line 3D style: "flat" = constant Y offset; "tilt" = back edge rises under braking.
  lineStyle = "tilt",
  --- Optional `ws://127.0.0.1:8765` when Python sidecar is running — see `WARP.md` § WebSocket sidecar (issue #45).
  wsSidecarUrl = "",
}

--- Non-negative numeric hold for UI and countdown (invalid config → 30).
local function normalizedCoachingHoldSeconds()
  local holdSec = tonumber(config.coachingHoldSeconds)
  if not holdSec or holdSec ~= holdSec or holdSec < 0 then
    return 30
  end
  return holdSec
end

--- Integer in [1, 3] for how many `buildAfterLap` hints to show (invalid → 3). Logic lives in `coaching_overlay`.
local function normalizedCoachingMaxVisibleHints()
  return coachingOverlay.normalizedCoachingMaxVisibleHints(config.coachingMaxVisibleHints)
end

local SMOOTH_N = 30
local deltaBuf = {}
local deltaBufN = 0

local function smoothDelta(x)
  if x == nil then
    return nil
  end
  deltaBufN = deltaBufN + 1
  deltaBuf[((deltaBufN - 1) % SMOOTH_N) + 1] = x
  local sum, c = 0, 0
  for i = 1, SMOOTH_N do
    if deltaBuf[i] ~= nil then
      sum = sum + deltaBuf[i]
      c = c + 1
    end
  end
  return c > 0 and (sum / c) or x
end

local function resetDeltaSmoother()
  deltaBuf = {}
  deltaBufN = 0
end

local function newTelemetry()
  return telemetryMod.new({ bufferSeconds = config.bufferSeconds })
end

local function newBrakes()
  return brakeMod.new({
    brakeThreshold = config.brakeThreshold,
    brakeDurationMin = config.brakeDurationMin,
  })
end

local tel = newTelemetry()
local brakes = newBrakes()
local td = throttleDet.new()
local tires = tireMonitor.new()

wsBridge.configure(config.wsSidecarUrl or "")

local lastDriveCar ---@type ac.StateCar|nil
local lastDriveSim ---@type ac.StateSim|nil

local function copyBpList(list)
  local out = {}
  for i = 1, #list do
    local e = list[i]
    out[i] = {
      spline = e.spline,
      px = e.px,
      py = e.py,
      pz = e.pz,
      entrySpeed = e.entrySpeed,
      heading = e.heading,
    }
  end
  return out
end

local function copyTrace(list)
  local out = {}
  for i = 1, #list do
    local e = list[i]
    out[i] = {
      spline = e.spline,
      eMs = e.eMs,
      speed = e.speed,
      brake = e.brake,
      throttle = e.throttle,
      steer = e.steer,
      gear = e.gear,
      px = e.px,
      py = e.py,
      pz = e.pz,
    }
  end
  return out
end

local function normalizeTrace(t)
  if not t or type(t) ~= "table" then
    return {}
  end
  local out = {}
  for i = 1, #t do
    local r = t[i]
    if type(r) == "table" then
      out[#out + 1] = {
        spline = tonumber(r.spline) or 0,
        eMs = tonumber(r.eMs) or 0,
        speed = tonumber(r.speed) or 0,
        brake = tonumber(r.brake) or 0,
        throttle = tonumber(r.throttle) or 0,
        steer = tonumber(r.steer) or 0,
        gear = math.floor(tonumber(r.gear) or 0),
        px = tonumber(r.px) or 0,
        py = tonumber(r.py) or 0,
        pz = tonumber(r.pz) or 0,
      }
    end
  end
  return out
end

local function cloneCornerFeats(f)
  if not f or type(f) ~= "table" then
    return {}
  end
  local out = {}
  for i = 1, #f do
    local c = f[i]
    if type(c) == "table" then
      out[#out + 1] = {
        label = c.label,
        s0 = c.s0,
        s1 = c.s1,
        entrySpeed = c.entrySpeed,
        minSpeed = c.minSpeed,
        exitSpeed = c.exitSpeed,
        brakePointSpline = c.brakePointSpline,
        trailBrakeRatio = c.trailBrakeRatio,
        steerReversals = c.steerReversals,
        tractionCircleProxy = c.tractionCircleProxy,
        throttleAvg = c.throttleAvg,
      }
    end
  end
  return out
end

--- Build ``telemetry.corners`` for sidecar ranking / debrief (issues #49, #46).
local function buildSidecarTelemetryCorners(feats)
  if not feats or type(feats) ~= "table" or #feats == 0 then
    return nil
  end
  local corners = {}
  for i = 1, #feats do
    local c = feats[i]
    local minS = tonumber(c.minSpeed)
    if minS then
      -- Apex / minimum speed through the corner: use min speed only (entry/exit average
      -- inflates vs true apex and breaks ranking vs reference laps — PR #55 review).
      local apex = minS
      corners[#corners + 1] = {
        id = i,
        minSpeedKmh = math.floor(minS + 0.5),
        apexSpeedKmh = math.floor(apex + 0.5),
      }
    end
  end
  if #corners == 0 then
    return nil
  end
  return { corners = corners }
end

--- Reject traces that never saw most of the lap spline (e.g. telemetry started mid-lap).
local function traceHasPbSplineCoverage(trace)
  if not trace or #trace < 2 then
    return false
  end
  local lo, hi = math.huge, -math.huge
  for i = 1, #trace do
    local s = trace[i].spline
    if type(s) == "number" then
      if s < lo then
        lo = s
      end
      if s > hi then
        hi = s
      end
    end
  end
  if lo == math.huge or hi == -math.huge then
    return false
  end
  local span = hi - lo
  if lo <= 0.06 and hi >= 0.94 then
    return true
  end
  if span < 0.78 then
    return false
  end
  if lo > 0.10 or hi < 0.90 then
    return false
  end
  return true
end

local state = {
  initialized = false,
  bestLapMs = nil,
  lastLapMs = nil,
  lastLapCount = -1,
  wasDriving = false,
  brakingPoints = {
    best = {},
    last = {},
    session = {},
  },
  recording = true,
  lastSplinePos = nil,
  bestLapTrace = {},
  --- Lap time (ms) for the lap that produced `bestLapTrace`; used to omit stale trace from saves when PB improves without a new reference trace.
  bestReferenceLapMs = nil,
  bestSortedTrace = nil,
  bestSectorMs = { 0, 0, 0 },
  sectorIndex = 1,
  sectorStartSimT = nil,
  lastSplineSector = nil,
  sectorHudMsg = "",
  sectorHudUntil = 0,
  postLapLines = {},
  postLapUntil = 0,
  lastThrottleSummary = "",
  trackSegments = {},
  lapFeatureHistory = {},
  bestCornerFeatures = {},
  lapsCompleted = 0,
  splineRef = nil,
  splineSessionPrimed = false,
  refLatDistance = nil,
  racingBestLine = {},
  racingLastLine = {},
  setupHash = "",
  lastSetupSnap = nil,
  setupChangeMsg = "",
  autoSetupMsg = "",
  consistencyHud = "",
  styleHud = "",
  tireHud = "",
  autoSetupUntil = 0,
  coachingLines = {},
  --- Wall-clock style countdown (`script.update(dt)`); avoids sim clock ms vs s ambiguity (#9).
  coachingRemainSec = 0,
  --- Last sidecar ``debrief`` paragraph (issue #46); persists until replaced or session reset.
  sidecarDebriefText = "",
}

local function rebuildBestReference()
  state.bestSortedTrace = delta.prepareTrace(state.bestLapTrace)
  local b = delta.sectorBoundariesMs(state.bestSortedTrace)
  if b then
    state.bestSectorMs = { b[1], b[2] - b[1], b[3] - b[2] }
  else
    state.bestSectorMs = { 0, 0, 0 }
  end
  resetDeltaSmoother()
end

local function applyLoaded(data)
  if not data or type(data) ~= "table" then
    return
  end
  local bestMs = tonumber(data.bestLapMs)
  if bestMs and bestMs > 0 then
    state.bestLapMs = bestMs
  end
  if data.bestBrakePoints and type(data.bestBrakePoints) == "table" then
    state.brakingPoints.best = data.bestBrakePoints
  end
  if data.bestLapTrace and type(data.bestLapTrace) == "table" then
    state.bestLapTrace = normalizeTrace(data.bestLapTrace)
  end
  local refMs = tonumber(data.bestReferenceLapMs)
  if refMs and refMs > 0 then
    state.bestReferenceLapMs = refMs
  elseif state.bestLapTrace and #state.bestLapTrace >= 2 and state.bestLapMs and state.bestLapMs > 0 then
    state.bestReferenceLapMs = state.bestLapMs
  else
    state.bestReferenceLapMs = nil
  end
  rebuildBestReference()
  if state.bestLapTrace and #state.bestLapTrace >= 2 then
    state.racingBestLine = racingLine.traceToLine(state.bestLapTrace)
  else
    state.racingBestLine = {}
  end
  if data.trackSegments and type(data.trackSegments) == "table" then
    state.trackSegments = data.trackSegments
  end
  if data.lapFeatureHistory and type(data.lapFeatureHistory) == "table" then
    state.lapFeatureHistory = data.lapFeatureHistory
    while #state.lapFeatureHistory > cornerAnalysis.maxHistoryLaps() do
      table.remove(state.lapFeatureHistory, 1)
    end
  end
  if data.setupHash and type(data.setupHash) == "string" then
    state.setupHash = data.setupHash
  end
  if data.setupSnapshot and type(data.setupSnapshot) == "table" then
    state.lastSetupSnap = data.setupSnapshot
  end
  if data.bestCornerFeatures and type(data.bestCornerFeatures) == "table" then
    state.bestCornerFeatures = data.bestCornerFeatures
  end
end

local function persistPayload()
  -- Always persist non-empty `bestLapTrace` together with `bestReferenceLapMs` so a new PB time
  -- does not erase a still-valid reference trace when the span guard rejected the new lap's trace.
  return {
    bestLapMs = state.bestLapMs,
    bestBrakePoints = state.brakingPoints.best,
    bestLapTrace = state.bestLapTrace,
    bestReferenceLapMs = state.bestReferenceLapMs,
    trackSegments = state.trackSegments,
    lapFeatureHistory = state.lapFeatureHistory,
    setupHash = state.setupHash,
    setupSnapshot = state.lastSetupSnap,
    bestCornerFeatures = state.bestCornerFeatures,
  }
end

---@return boolean
local function persistSnapshotLive()
  if not sim or sim.isInMainMenu or not car then
    return false
  end
  return persistence.save(car, sim, persistPayload()) == true
end

---@return boolean
local function persistSnapshotCached()
  local c, s = lastDriveCar, lastDriveSim
  if not c or not s then
    return false
  end
  return persistence.save(c, s, persistPayload()) == true
end

local function resetRuntimeAfterLeavingTrack()
  state.initialized = false
  state.bestLapMs = nil
  state.lastLapMs = nil
  state.lastLapCount = -1
  state.brakingPoints = {
    best = {},
    last = {},
    session = {},
  }
  state._coachDiagT = nil
  state._coachDiagCount = nil
  tel = newTelemetry()
  brakes = newBrakes()
  td = throttleDet.new()
  tires = tireMonitor.new()
  lastDriveCar = nil
  lastDriveSim = nil
  state.lastSplinePos = nil
  state.bestLapTrace = {}
  state.bestReferenceLapMs = nil
  state.bestSortedTrace = nil
  state.bestSectorMs = { 0, 0, 0 }
  state.sectorIndex = 1
  state.sectorStartSimT = nil
  state.lastSplineSector = nil
  state.sectorHudMsg = ""
  state.sectorHudUntil = 0
  state.postLapLines = {}
  state.postLapUntil = 0
  state.lastThrottleSummary = ""
  state.trackSegments = {}
  state.lapFeatureHistory = {}
  state.bestCornerFeatures = {}
  state.lapsCompleted = 0
  state.splineRef = nil
  state.splineSessionPrimed = false
  state.refLatDistance = nil
  state.racingBestLine = {}
  state.racingLastLine = {}
  state.setupHash = ""
  state.lastSetupSnap = nil
  state.setupChangeMsg = ""
  state.autoSetupMsg = ""
  state.consistencyHud = ""
  state.styleHud = ""
  state.tireHud = ""
  state.autoSetupUntil = 0
  state.coachingLines = {}
  state.coachingRemainSec = 0
  state.sidecarDebriefText = ""
  wsBridge.reset()
  renderDiag.reset()
  resetDeltaSmoother()
end

local function resetRollingDrivingState()
  state.brakingPoints.session = {}
  state._coachDiagT = nil
  state._coachDiagCount = nil
  -- New session / lap counter rolled back (Gemini #50): do not carry coaching UI across sessions.
  state.coachingLines = {}
  state.coachingRemainSec = 0
  state.sidecarDebriefText = ""
  state.lapsCompleted = 0
  tel = newTelemetry()
  brakes = newBrakes()
  td:resetLapAggregates()
  tires:resetLap()
  state.sectorIndex = 1
  state.sectorStartSimT = nil
  state.lastSplineSector = nil
  state.sectorHudMsg = ""
  state.sectorHudUntil = 0
  wsBridge.clearPendingCoaching()
  resetDeltaSmoother()
end

local function tryLoadDisk()
  car = ac.getCar(0)
  sim = ac.getSim()
  if sim.isInMainMenu or not car then
    return
  end
  applyLoaded(persistence.load(car, sim))
  state.initialized = true
end

---@param simTime number
local function sectorMessage(refMs, actualMs, simTime)
  if not refMs or refMs <= 0 or not actualMs then
    return
  end
  local d = actualMs - refMs
  if d < -5 then
    state.sectorHudMsg = string.format("Sector: %.2f s faster than ref lap", -d / 1000)
  elseif d > 5 then
    state.sectorHudMsg = string.format("Sector: %.2f s slower than ref lap", d / 1000)
  else
    state.sectorHudMsg = string.format("Sector: on pace (Δ %+d ms)", math.floor(d + 0.5))
  end
  state.sectorHudUntil = simTime + config.sectorMessageSeconds
end

---@param sim0 ac.StateSim|nil
local function trackLengthMeters(sim0)
  if not sim0 then
    return nil
  end
  -- CSP ac.StateSim uses trackLengthM (confirmed from CMRT-Essential-HUD).
  -- C-structs throw on invalid fields, so only access the known-valid one.
  local tl = tonumber(sim0.trackLengthM)
  if tl and tl > 50 then
    return tl
  end
  return nil
end

---@param sim0 ac.StateSim|nil
local function buildPostLapLines(bestBps, lastBps, coastMs, sim0)
  local lines = {}
  local tlM = trackLengthMeters(sim0)
  if #bestBps == 0 then
    if coastMs and coastMs > 200 then
      lines[1] = string.format("Coasting (lap): %.1f s", coastMs / 1000)
    end
    return lines
  end
  local n = math.min(#lastBps, 8)
  for i = 1, n do
    local L = lastBps[i]
    local bestJ, bestD = 1, 99.0
    for j = 1, #bestBps do
      local B = bestBps[j]
      local ds = math.abs((L.spline or 0) - (B.spline or 0))
      ds = math.min(ds, 1 - ds)
      if ds < bestD then
        bestD = ds
        bestJ = j
      end
    end
    local B = bestBps[bestJ]
    if B then
      local wrap = (L.spline or 0) - (B.spline or 0)
      if wrap > 0.5 then
        wrap = wrap - 1
      elseif wrap < -0.5 then
        wrap = wrap + 1
      end
      local dv = (L.entrySpeed or 0) - (B.entrySpeed or 0)
      if tlM then
        local estM = wrap * tlM
        lines[#lines + 1] = string.format("Brake %d: dSpline %+.3f (~%+.0f m) dV %+.0f km/h", i, wrap, estM, dv)
      else
        lines[#lines + 1] = string.format("Brake %d: dSpline %+.3f  dV %+.0f km/h", i, wrap, dv)
      end
    end
  end
  if coastMs and coastMs > 200 then
    lines[#lines + 1] = string.format("Coasting (lap): %.1f s", coastMs / 1000)
  end
  return lines
end

--- Forward spline distance from car to point along lap, in [0, 1).
local function splineForwardDelta(carSpline, ptSpline)
  local d = (ptSpline or 0) - (carSpline or 0)
  if d < 0 then
    d = d + 1
  end
  if d >= 1 then
    d = d - 1
  end
  return d
end

---@param sim0 ac.StateSim|nil
local function approachHudLines(car0, sortedTrace, sim0)
  local best = state.brakingPoints.best
  if not car0 or not car0.position or #best == 0 then
    return nil
  end
  local carSp = car0.splinePosition or 0
  local cx, cy, cz = car0.position.x, car0.position.y, car0.position.z
  local bestI, bestSplineD, bestDistSq ---@type integer|nil, number|nil, number|nil
  for i = 1, #best do
    local p = best[i]
    local dx, dy, dz = cx - p.px, cy - p.py, cz - p.pz
    local distSq = dx * dx + dy * dy + dz * dz
    local dS = splineForwardDelta(carSp, p.spline or 0)
    if dS < 1e-9 then
      dS = 1e-9
    end
    if bestI == nil or dS < bestSplineD - 1e-12 or (math.abs(dS - bestSplineD) <= 1e-12 and distSq < bestDistSq) then
      bestI = i
      bestSplineD = dS
      bestDistSq = distSq
    end
  end
  if not bestI or not bestDistSq or not bestSplineD then
    return nil
  end
  local dM = math.sqrt(bestDistSq)
  local tlM = trackLengthMeters(sim0)
  if tlM and tlM > 0 then
    dM = bestSplineD * tlM
  end
  if dM > config.approachMeters then
    return nil
  end
  local bp = best[bestI]
  local refSpd = bp.entrySpeed or 0
  if sortedTrace then
    refSpd = delta.bestSpeedKmhAtSpline(sortedTrace, bp.spline or 0) or refSpd
  end
  local cur = car0.speedKmh or 0
  local dv = cur - refSpd
  local tag = "match"
  if dv > 8 then
    tag = "too fast"
  elseif dv < -8 then
    tag = "too slow"
  end
  return {
    string.format("Dist brake #%d: %.0f m", bestI, dM),
    string.format("Ref speed: %.0f  Current: %.0f (%s)", refSpd, cur, tag),
  }
end

function script.windowMain(_dt)
  if not config.hudEnabled then
    return
  end
  sim = ac.getSim()
  car = ac.getCar(0)
  if sim.isInMainMenu then
    ui.text("AC Copilot Trainer " .. APP_VERSION_UI)
    ui.separator()
    ui.text("Waiting for session...")
    return
  end
  if not car then
    ui.text("AC Copilot Trainer " .. APP_VERSION_UI)
    ui.separator()
    ui.text("Waiting for car data...")
    return
  end

  local now = ch.simSeconds(sim)
  local dSmooth = nil
  if state.bestSortedTrace and tel:lapStartTime() then
    local eMs = (now - tel:lapStartTime()) * 1000
    local sp = car.splinePosition or 0
    local raw = delta.deltaSecondsAtSpline(state.bestSortedTrace, sp, eMs)
    dSmooth = smoothDelta(raw)
  end

  local secMsg = ""
  if state.sectorHudMsg ~= "" and now < state.sectorHudUntil then
    secMsg = state.sectorHudMsg
  end

  local postLines = {}
  if now < state.postLapUntil then
    postLines = state.postLapLines
  end

  local coastWarn = false
  if td.coastStreak and td.coastStreak >= config.coastWarnSeconds then
    coastWarn = true
  end

  local autoSetupLine = nil
  if state.autoSetupMsg ~= "" and now < (state.autoSetupUntil or 0) then
    autoSetupLine = state.autoSetupMsg
  end

  local coachingHudLines = nil
  local coachRem = nil
  if state.coachingLines and #state.coachingLines > 0 and (state.coachingRemainSec or 0) > 0 then
    coachingHudLines = state.coachingLines
    coachRem = state.coachingRemainSec
  end
  local coachPrimer = (state.lapsCompleted or 0) == 0

  hud.draw({
    recording = tel:isRecording(),
    telemetrySamples = tel:sampleCount(),
    speed = car.speedKmh or 0,
    brake = car.brake or 0,
    lapCount = car.lapCount or 0,
    bestLapMs = state.bestLapMs or (car.bestLapTimeMs or nil),
    lastLapMs = state.lastLapMs or (car.previousLapTimeMs or nil),
    brakeBest = #state.brakingPoints.best,
    brakeLast = #state.brakingPoints.last,
    brakeSession = #state.brakingPoints.session,
    deltaSmoothedSec = dSmooth,
    sectorMessage = secMsg,
    approachLines = approachHudLines(car, state.bestSortedTrace, sim),
    postLapLines = postLines,
    coastWarn = coastWarn,
    throttleLapHint = state.lastThrottleSummary,
    consistencyHud = state.consistencyHud,
    styleHud = state.styleHud,
    tireHud = state.tireHud,
    tireLockupFlash = tires:lockupFlash(),
    setupChangeMsg = state.setupChangeMsg,
    autoSetupLine = autoSetupLine,
    refAiDistanceM = state.refLatDistance,
    segmentCount = #(state.trackSegments or {}),
    coachingLines = coachingHudLines,
    coachingRemaining = coachRem,
    coachingHoldSeconds = normalizedCoachingHoldSeconds(),
    coachingMaxVisibleHints = normalizedCoachingMaxVisibleHints(),
    coachingShowPrimer = coachPrimer,
    appVersionUi = APP_VERSION_UI,
    debriefText = (state.sidecarDebriefText ~= "") and state.sidecarDebriefText or nil,
  })
  if config.enableRenderDiagnostics then
    renderDiag.drawUI()
  end
end

--- Separate coaching overlay window (issue #35 Part C, #37 Part C fix).
--- Registered as a second CSP app window; transparent background, top-right.
--- Issue #37: added diagnostic logging and fallback message for empty state.
function script.windowCoaching(_dt)
  if not config.hudEnabled then return end
  sim = sim or ac.getSim()
  if not sim or sim.isInMainMenu then return end
  local now = ch.simSeconds(sim)
  local remaining = state.coachingRemainSec or 0
  local laps = state.lapsCompleted or 0

  -- #5: Periodic coaching diag (every 5s for first 60s, then stops)
  if not state._coachDiagT then state._coachDiagT = 0 end
  if not state._coachDiagCount then state._coachDiagCount = 0 end
  state._coachDiagT = state._coachDiagT + (_dt or 0)
  if state._coachDiagCount < 12 and state._coachDiagT > 5.0 and ac and type(ac.log) == "function" then
    state._coachDiagT = 0
    state._coachDiagCount = state._coachDiagCount + 1
    ac.log(string.format(
      "[COPILOT] coaching: simT=%.1f remainSec=%.2f lines=%d laps=%d (timer=dt not sim clock)",
      now, remaining, state.coachingLines and #state.coachingLines or 0, laps))
  end

  if laps == 0 then
    coachingOverlay.drawFallback()
    return
  end

  if remaining > 0 then
    if state.coachingLines and #state.coachingLines > 0 then
      coachingOverlay.draw(
        state.coachingLines,
        remaining,
        normalizedCoachingHoldSeconds(),
        normalizedCoachingMaxVisibleHints()
      )
    else
      coachingOverlay.drawHoldNoHints(remaining)
    end
    coachingOverlay.drawSidecarDebrief(state.sidecarDebriefText)
    return
  end

  coachingOverlay.drawBetweenLapsIdle(normalizedCoachingHoldSeconds())
  coachingOverlay.drawSidecarDebrief(state.sidecarDebriefText)
end

function script.update(dt)
  sim = ac.getSim()
  car = ac.getCar(0)

  if sim.isInMainMenu then
    if state.wasDriving then
      if persistSnapshotCached() then
        -- Issue #47: training journal JSON under ScriptConfig (after persist, before state reset).
        local journalLaps = state.lapsCompleted or 0
        local callOk, journalOkOrErr = pcall(sessionJournal.writeSessionEnd, lastDriveCar, lastDriveSim, {
          lapsCompleted = state.lapsCompleted,
          bestLapMs = state.bestLapMs,
          lastLapMs = state.lastLapMs,
          lapFeatureHistory = state.lapFeatureHistory,
          coachingLines = state.coachingLines,
          appVersionUi = APP_VERSION_UI,
          sidecarDebriefText = state.sidecarDebriefText,
        })
        local journalOk = callOk and journalOkOrErr == true
        -- writeSessionEnd returns false for intentional no-op (0 laps); log only real failures / throws.
        if journalLaps >= 1 and ac and type(ac.log) == "function" then
          if not callOk then
            ac.log("[COPILOT] session_journal: export raised error after persist: " .. tostring(journalOkOrErr))
          elseif not journalOk then
            ac.log("[COPILOT] session_journal: export failed after persist (I/O or encode error; see session_journal logs)")
          end
        end
        resetRuntimeAfterLeavingTrack()
        state.wasDriving = false
      end
    else
      state.wasDriving = false
    end
    state.lastLapCount = -1
    return
  end

  -- Tick coaching hold even when `car` is briefly nil so the countdown does not freeze (review #50).
  local dtf = (type(dt) == "number" and dt == dt and dt >= 0) and dt or 0
  if (state.coachingRemainSec or 0) > 0 then
    state.coachingRemainSec = math.max(0, (state.coachingRemainSec or 0) - dtf)
  end

  if not car then
    return
  end

  lastDriveCar = car
  lastDriveSim = sim
  state.wasDriving = true

  if not state.initialized then
    tryLoadDisk()
  end

  wsBridge.tick(ch.simSeconds(sim))
  wsBridge.pollInbound(8)
  local sidecarHints, sidecarDebrief = wsBridge.takeCoachingForLap(state.lapsCompleted or 0)
  if type(sidecarDebrief) == "string" and sidecarDebrief ~= "" then
    state.sidecarDebriefText = sidecarDebrief
  end
  if sidecarHints and #sidecarHints > 0 then
    state.coachingLines = sidecarHints
    -- Late sidecar (e.g. slow Ollama): still show hints; refresh hold if it already expired.
    if (state.coachingRemainSec or 0) <= 0 then
      state.coachingRemainSec = normalizedCoachingHoldSeconds()
    end
  end

  if state.initialized and not state.splineSessionPrimed then
    state.splineSessionPrimed = true
    state.splineRef = splineParser.loadForTrack(sim)
    if config.autoLoadSetup then
      local msg = setupReader.tryAutoLoadCopilotSetup(car, sim, true)
      if msg and msg ~= "" then
        state.autoSetupMsg = msg
        state.autoSetupUntil = ch.simSeconds(sim) + 8
      end
    end
  end

  local lc = car.lapCount or 0
  local sp = car.splinePosition or 0

  -- After menu, lastLapCount is -1 until end-of-frame; prime now so lap clock can arm on the first driving frame.
  if state.lastLapCount < 0 then
    state.lastLapCount = lc
  end

  -- Lap boundary: finalize trace before appending this frame's sample.
  if state.lastLapCount >= 0 and lc > state.lastLapCount then
    local completedTrace = tel:finalizeLapTrace()
    tel:beginLapClock(ch.simSeconds(sim))
    resetDeltaSmoother()
    -- car.previousLapTimeMs is valid; car.lastLapTimeMs may not exist on the C-struct (throws, not nil).
    local lastMs = car.previousLapTimeMs or 0
    state.lastLapMs = lastMs > 0 and lastMs or state.lastLapMs

    local s3 = (state.sectorIndex == 3 and state.sectorStartSimT)
        and ((ch.simSeconds(sim) - state.sectorStartSimT) * 1000) or nil
    if s3 and state.bestSectorMs[3] and state.bestSectorMs[3] > 0 then
      sectorMessage(state.bestSectorMs[3], s3, ch.simSeconds(sim))
    end

    local evLap = brakes:finalizeQualifiedWhileHolding(car)
    if evLap then
      state.brakingPoints.session[#state.brakingPoints.session + 1] = evLap
    end

    local thA = throttleDet.analyzeTrace(completedTrace)
    if thA then
      state.lastThrottleSummary = string.format(
        "FT%% %.0f  coast %.1fs  throttle-on %d  sawtooth~ %d",
        thA.fullThrottlePct or 0,
        (thA.coastingMs or 0) / 1000,
        thA.applyEvents or 0,
        thA.reversals or 0
      )
    else
      state.lastThrottleSummary = ""
    end

    local segBrakes = state.brakingPoints.session
    if #segBrakes == 0 then
      segBrakes = state.brakingPoints.best
    end
    state.lapsCompleted = (state.lapsCompleted or 0) + 1
    local spanForAnalytics = 0
    if #completedTrace >= 2 then
      spanForAnalytics = completedTrace[#completedTrace].eMs - completedTrace[1].eMs
    end
    local traceAnalyticsOk = lastMs > 0 and #completedTrace > 0 and spanForAnalytics >= lastMs * 0.45 and traceHasPbSplineCoverage(completedTrace)

    local feats = {}
    local consForHints = nil
    if traceAnalyticsOk then
      if state.lapsCompleted >= 2 then
        local ns = cornerAnalysis.buildSegments(completedTrace, state.brakingPoints.best)
        if #ns > 0 then
          state.trackSegments = ns
        end
      end
      if #state.trackSegments == 0 then
        local ns = cornerAnalysis.buildSegments(completedTrace, segBrakes)
        if #ns > 0 then
          state.trackSegments = ns
        end
      end
      feats = cornerAnalysis.cornerFeaturesForLap(completedTrace, state.trackSegments)
      cornerAnalysis.appendHistory(state.lapFeatureHistory, { lapMs = lastMs, corners = feats })
      consForHints = cornerAnalysis.consistencySummary(state.lapFeatureHistory)
      state.consistencyHud = ""
      if consForHints and consForHints.worstThree and #consForHints.worstThree > 0 then
        state.consistencyHud = "Least consistent: " .. table.concat(consForHints.worstThree, ", ")
      end
      state.styleHud = ""
      local div = cornerAnalysis.styleDivergence(feats, state.bestCornerFeatures)
      if div ~= nil then
        state.styleHud = string.format(
          "Style vs ref: %.0f%% match",
          math.max(0, math.min(100, (1 - div) * 100))
        )
      end
    else
      state.consistencyHud = state.consistencyHud or ""
      state.styleHud = state.styleHud or ""
    end

    state.coachingLines = coachingHints.buildAfterLap(feats, state.bestCornerFeatures, consForHints, thA, traceAnalyticsOk)
    state.coachingRemainSec = normalizedCoachingHoldSeconds()

    -- Diagnostic: log if coaching lines were generated but empty (#35 Part E)
    if ac and type(ac.log) == "function" then
      if state.coachingLines and #state.coachingLines > 0 then
        ac.log(string.format(
          "[COPILOT] coaching: %d hints generated, hold=%.1fs, maxVisible=%d",
          #state.coachingLines,
          normalizedCoachingHoldSeconds(),
          normalizedCoachingMaxVisibleHints()
        ))
      else
        ac.log("[COPILOT] coaching: buildAfterLap returned empty — feats=" .. tostring(#feats)
          .. " bestCorner=" .. tostring(#state.bestCornerFeatures)
          .. " traceOk=" .. tostring(traceAnalyticsOk))
      end
    end

    local _snap, hnew = setupReader.snapshotActive(car, sim)
    state.setupChangeMsg = setupReader.describeChange(state.setupHash, hnew) or ""
    if hnew and hnew ~= "" then
      state.setupHash = hnew
    end
    if _snap then
      state.lastSetupSnap = _snap
    end

    state.tireHud = tires:lapSummaryLine() or ""
    tires:resetLap()

    state.racingLastLine = racingLine.traceToLine(completedTrace)

    local prevBestBp = copyBpList(state.brakingPoints.best)
    if lastMs > 0 and (state.bestLapMs == nil or lastMs <= state.bestLapMs) then
      state.bestLapMs = lastMs
      state.brakingPoints.best = copyBpList(state.brakingPoints.session)
      if traceAnalyticsOk and #feats > 0 then
        state.bestCornerFeatures = cloneCornerFeats(feats)
      end
      local spanMs = 0
      if #completedTrace >= 2 then
        spanMs = completedTrace[#completedTrace].eMs - completedTrace[1].eMs
      end
      -- Ignore reference trace when time span is short (mid-lap clock / gaps) or spline range is too narrow.
      if #completedTrace > 0 and spanMs >= lastMs * 0.45 and traceHasPbSplineCoverage(completedTrace) then
        state.bestLapTrace = copyTrace(completedTrace)
        state.bestReferenceLapMs = lastMs
        state.racingBestLine = racingLine.traceToLine(completedTrace)
      end
      -- Guards failed: keep prior `bestLapTrace` / `bestReferenceLapMs`; persist still saves both with `bestReferenceLapMs`.
      rebuildBestReference()
    end
    state.brakingPoints.last = copyBpList(state.brakingPoints.session)
    state.brakingPoints.session = {}
    td:resetLapAggregates()

    local coastMs = thA and thA.coastingMs or 0
    state.postLapLines = buildPostLapLines(prevBestBp, state.brakingPoints.last, coastMs, sim)
    state.postLapUntil = ch.simSeconds(sim) + config.postLapHoldSeconds

    if lastMs > 0 then
      local hintsJson = {}
      if state.coachingLines then
        for i = 1, #state.coachingLines do
          local e = state.coachingLines[i]
          if type(e) == "table" and type(e.text) == "string" then
            hintsJson[i] = e.text
          else
            hintsJson[i] = tostring(e)
          end
        end
      end
      local lapPayload = {
        protocol = wsBridge.PROTOCOL_VERSION,
        event = "lap_complete",
        lap = state.lapsCompleted,
        lapTimeMs = lastMs,
        coachingHints = hintsJson,
      }
      if traceAnalyticsOk and #feats > 0 then
        local telc = buildSidecarTelemetryCorners(feats)
        if telc then
          lapPayload.telemetry = telc
        end
      end
      wsBridge.sendJson(lapPayload)
    end

    state.sectorIndex = 1
    state.sectorStartSimT = ch.simSeconds(sim)
    state.lastSplineSector = sp

    persistSnapshotLive()
  end

  -- Start collecting after lap counter is synced; span guard above avoids saving a partial trace as PB reference.
  if tel:lapStartTime() == nil and not sim.isInMainMenu and state.lastLapCount >= 0 then
    tel:beginLapClock(ch.simSeconds(sim))
    resetDeltaSmoother()
    state.sectorStartSimT = ch.simSeconds(sim)
    state.sectorIndex = 1
    state.lastSplineSector = sp
  end

  tel:setRecording(state.recording)
  tel:update(dt, car, sim)

  local ev = brakes:update(car, dt)
  if ev then
    state.brakingPoints.session[#state.brakingPoints.session + 1] = ev
  end
  td:update(car, dt)

  -- Sector boundaries (spline thirds)
  if state.lastLapCount >= 0 and lc == state.lastLapCount and state.sectorStartSimT and state.lastSplineSector ~= nil then
    local lsp = state.lastSplineSector
    local b1, b2 = 1 / 3, 2 / 3
    if state.sectorIndex == 1 and lsp < b1 and sp >= b1 then
      local aMs = (ch.simSeconds(sim) - state.sectorStartSimT) * 1000
      sectorMessage(state.bestSectorMs[1], aMs, ch.simSeconds(sim))
      state.sectorIndex = 2
      state.sectorStartSimT = ch.simSeconds(sim)
    elseif state.sectorIndex == 2 and lsp < b2 and sp >= b2 then
      local aMs = (ch.simSeconds(sim) - state.sectorStartSimT) * 1000
      sectorMessage(state.bestSectorMs[2], aMs, ch.simSeconds(sim))
      state.sectorIndex = 3
      state.sectorStartSimT = ch.simSeconds(sim)
    end
  end

  tires:update(car, dt, sp)

  if config.enableRenderDiagnostics then
    renderDiag.tick(dt)
  end

  if car.position and state.splineRef then
    state.refLatDistance = splineParser.lateralDistanceMeters(
      state.splineRef,
      car.position.x,
      car.position.y,
      car.position.z
    )
  else
    state.refLatDistance = nil
  end

  if state.lastLapCount >= 0 and lc < state.lastLapCount then
    resetRollingDrivingState()
  elseif state.lastLapCount >= 0 and lc == state.lastLapCount and state.lastSplinePos then
    local lastSp = state.lastSplinePos
    local d = sp - lastSp
    local likelyWrap = lastSp > 0.8 and sp < 0.25
    if d < -0.2 and not likelyWrap then
      resetRollingDrivingState()
    end
  end

  state.lastLapCount = lc
  state.lastSplinePos = sp
  state.lastSplineSector = sp
end

function script.onWindowHide()
  persistSnapshotCached()
end

function script.Draw3D(_dt)
  local s = ac.getSim()
  if not s or s.isInMainMenu then
    return
  end
  local c = ac.getCar(0)

  if config.enableRenderDiagnostics then
    renderDiag.draw3D(c)
  end

  if config.enableDraw3DDiagnostics then
    if not state._draw3dLogT then state._draw3dLogT = 0 end
    state._draw3dLogT = state._draw3dLogT + (_dt or 0)
    if state._draw3dLogT > 2.0 then
      state._draw3dLogT = 0
      local bestN = state.brakingPoints and state.brakingPoints.best and #state.brakingPoints.best or -1
      local lastN = state.brakingPoints and state.brakingPoints.last and #state.brakingPoints.last or -1
      local bestLineN = state.racingBestLine and #state.racingBestLine or -1
      local lastLineN = state.racingLastLine and #state.racingLastLine or -1
      local hasVec3 = vec3 ~= nil
      local hasDbgSphere = render and render.debugSphere ~= nil
      local hasDbgLine = render and render.debugLine ~= nil
      local mode0 = config.racingLineMode or "best"
      ac.log("[COPILOT] Draw3D: best_bp=" .. tostring(bestN)
        .. " last_bp=" .. tostring(lastN)
        .. " bestLine=" .. tostring(bestLineN)
        .. " lastLine=" .. tostring(lastLineN)
        .. " mode=" .. mode0
        .. " vec3=" .. tostring(hasVec3)
        .. " debugSphere=" .. tostring(hasDbgSphere)
        .. " debugLine=" .. tostring(hasDbgLine))
      -- Log car position and first brake point/line point coords to check if world coords are valid
      if c and c.position then
        ac.log("[COPILOT] carPos=" .. string.format("%.1f,%.1f,%.1f", c.position.x, c.position.y, c.position.z))
      end
      if bestN > 0 then
        local bp = state.brakingPoints.best[1]
        if bp then
          ac.log("[COPILOT] bp[1] px=" .. tostring(bp.px) .. " py=" .. tostring(bp.py) .. " pz=" .. tostring(bp.pz)
            .. " spline=" .. tostring(bp.spline))
        end
      end
      if bestLineN > 0 then
        local lp = state.racingBestLine[1]
        if lp then
          ac.log("[COPILOT] line[1] x=" .. tostring(lp.x) .. " y=" .. tostring(lp.y) .. " z=" .. tostring(lp.z))
        end
        local midIdx = math.max(1, math.floor((bestLineN + 1) / 2))
        local mid = state.racingBestLine[midIdx]
        if mid then
          ac.log("[COPILOT] line[mid i=" .. tostring(midIdx) .. "] x=" .. tostring(mid.x) .. " y=" .. tostring(mid.y) .. " z=" .. tostring(mid.z))
        end
      end
    end
  end

  trackMarkers.draw(c, s, state.brakingPoints.best, state.brakingPoints.last)
  local mode = config.racingLineMode or "best"
  local style = config.lineStyle or "tilt"
  if mode == "best" or mode == "both" then
    racingLine.drawLineStrip(c, state.racingBestLine, rgbm(0.0, 0.85, 0.25, 0.80), nil, style)
  end
  if mode == "last" or mode == "both" then
    racingLine.drawLineStrip(c, state.racingLastLine, rgbm(0.85, 0.75, 0.0, 0.55), nil, style)
  end
end
