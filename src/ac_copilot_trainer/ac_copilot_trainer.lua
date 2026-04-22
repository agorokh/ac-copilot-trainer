-- AC Copilot Trainer v0.4.2
local APP_VERSION_UI = "v0.5.0"
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
-- Issue #77 Part C: per-lap archive (full trace + setup + corners + coaching).
local lapArchive = require("lap_archive")
local coachingOverlay = require("coaching_overlay")
local wsBridge = require("ws_bridge")
local sessionJournal = require("session_journal")
local ch = require("csp_helpers")
local renderDiag = require("render_diag")
local focusPractice = require("focus_practice")
local cornerNames = require("corner_names")
local hudSettings = require("hud_settings")
local realtimeCoaching = require("realtime_coaching")

--- Pixel sizes per window title; must match ``manifest.ini`` WINDOW_* ``SIZE=``.
local MANIFEST_WINDOW_SIZES = {
  ["AC Copilot Trainer"] = {520, 200},
  ["Coaching"]           = {640, 240},
  ["Settings"]           = {480, 580},
}

local sim ---@type ac.StateSim
local car ---@type ac.StateCar

--- Defaults for `ac.storage` (issue #57 Part A). Keys must stay stable across versions.
local CONFIG_DEFAULTS = {
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
  -- Issue #77 Part A: default URL points at our auto-launched sidecar.
  -- Setting this here means a fresh install dials 127.0.0.1:8765 immediately
  -- without the user touching Settings.
  wsSidecarUrl = "ws://127.0.0.1:8765",
  --- Focus practice (issue #44): comma-separated corner labels `T1,T2`; empty = auto from worst consistency rows.
  focusPracticeCornerLabels = "",
  --- Auto-pick up to this many worst corners when `focusPracticeCornerLabels` is empty (1–3).
  focusPracticeAutoCount = 3,
  --- When focus mode is on and corner geometry exists, dim brake walls outside the focus set.
  focusPracticeDimNonFocus = true,
  --- 3D overlays (issue #57 Part B); default on — toggles in Settings window.
  racingLineEnabled = true,
  brakeMarkersEnabled = true,
  --- Issue #77 Part C: write one JSON per completed lap to journal/laps/.
  --- Includes full per-sample trace (2000 samples), corner features, active
  --- car setup snapshot, coaching context. Append-only with disk cap.
  lapArchiveEnabled = true,
  --- Hard cap on archive disk usage in MB. Oldest files deleted first.
  lapArchiveMaxMB = 500,
}

--- Auto-launch always serves the sidecar on localhost:8765; other persisted URLs strand coaching (Codex #78).
local function wsUrlMatchesAutolaunchTarget(s)
  if type(s) ~= "string" then
    return false
  end
  local u = s:lower():gsub("%s+", ""):gsub("/+$", "")
  return u == "ws://127.0.0.1:8765" or u == "ws://localhost:8765"
end

--- Shallow copy so `CONFIG_DEFAULTS` is never aliased or mutated by `ac.storage()` (review #58).
local function shallowCopyDefaults()
  local c = {}
  for k, v in pairs(CONFIG_DEFAULTS) do
    c[k] = v
  end
  return c
end

--- Per-key storage for critical settings.
---
--- Issue #75 in-game test: `ac.storage(layout)` table-form silently fails to
--- persist on this CSP build (no `cfg/extension/state/lua/app/AC Copilot
--- Trainer.ini` is ever written). Every other CSP app uses the per-key form
--- `ac.storage("name", default)` which is known to work. We use it here for
--- `wsSidecarUrl` so the URL persists across reloads and the WebSocket
--- bridge can actually dial the sidecar.
local _wsUrlStorage = nil
local _approachMetersStorage = nil
local _lapArchiveEnabledStorage = nil
local _lapArchiveMaxMBStorage = nil
if ac and type(ac.storage) == "function" then
  local ok1, sv1 = pcall(ac.storage, "ac_copilot_trainer.wsSidecarUrl_v1", "")
  if ok1 and sv1 and type(sv1.get) == "function" then
    _wsUrlStorage = sv1
  end
  local ok2, sv2 = pcall(ac.storage, "ac_copilot_trainer.approachMeters_v1", 200)
  if ok2 and sv2 and type(sv2.get) == "function" then
    _approachMetersStorage = sv2
  end
  -- Lap archive toggles must use per-key storage too (table-form `ac.storage` is broken on target CSP — Codex #78).
  local ok3, sv3 = pcall(ac.storage, "ac_copilot_trainer.lapArchiveEnabled_v1", 1)
  if ok3 and sv3 and type(sv3.get) == "function" then
    _lapArchiveEnabledStorage = sv3
  end
  local ok4, sv4 = pcall(ac.storage, "ac_copilot_trainer.lapArchiveMaxMB_v1", 500)
  if ok4 and sv4 and type(sv4.get) == "function" then
    _lapArchiveMaxMBStorage = sv4
  end
end

--- Persistent app settings (CSP `ac.storage`); shallow copy fallback when API missing (tests / old CSP).
local function loadConfig()
  local cfg
  if ac and type(ac.storage) == "function" then
    local ok, st = pcall(ac.storage, shallowCopyDefaults())
    if ok and type(st) == "table" then
      cfg = st
    end
  end
  if not cfg then
    cfg = shallowCopyDefaults()
  end
  -- Overlay the per-key wsSidecarUrl (table-form is broken on this CSP build).
  -- Issue #78: empty stored URL used to mean "cleared"; with auto-launch + no URL
  -- editor in Settings, migrate empty back to localhost and persist so wsBridge.tick connects.
  if _wsUrlStorage and type(_wsUrlStorage.get) == "function" then
    local ok, val = pcall(function() return _wsUrlStorage:get() end)
    if ok and type(val) == "string" then
      local migrated = false
      if val == "" or not wsUrlMatchesAutolaunchTarget(val) then
        cfg.wsSidecarUrl = CONFIG_DEFAULTS.wsSidecarUrl
        migrated = true
      else
        cfg.wsSidecarUrl = val
      end
      if migrated and type(_wsUrlStorage.set) == "function" then
        pcall(function() _wsUrlStorage:set(cfg.wsSidecarUrl) end)
      end
    end
  end
  -- Overlay approachMeters too (table-form is broken).
  if _approachMetersStorage and type(_approachMetersStorage.get) == "function" then
    local ok, val = pcall(function() return _approachMetersStorage:get() end)
    if ok and type(val) == "number" and val > 0 then
      cfg.approachMeters = val
    end
  end
  if _lapArchiveEnabledStorage and type(_lapArchiveEnabledStorage.get) == "function" then
    local ok, val = pcall(function() return _lapArchiveEnabledStorage:get() end)
    if ok and val ~= nil then
      local n = tonumber(val)
      if n ~= nil then
        cfg.lapArchiveEnabled = (n ~= 0)
      end
    end
  end
  if _lapArchiveMaxMBStorage and type(_lapArchiveMaxMBStorage.get) == "function" then
    local ok, val = pcall(function() return _lapArchiveMaxMBStorage:get() end)
    if ok and val ~= nil then
      local n = tonumber(val)
      if n ~= nil and n > 0 then
        cfg.lapArchiveMaxMB = n
      end
    end
  end
  cfg.lapArchiveMaxMB = lapArchive.clampArchiveCapMB(cfg.lapArchiveMaxMB)
  return cfg
end

local config = loadConfig()

-- Issue #77 Part C: stable session id stamped on every archived lap from this script load.
-- Use 16-bit math.random bounds only (Lua 5.1 / some LuaJIT builds reject 0xFFFFFFFF as int32).
math.randomseed((os and os.time and os.time()) or 0)
local SESSION_UUID = string.format(
  "%04x%04x%04x",
  math.random(0, 0xFFFF),
  math.random(0, 0xFFFF),
  math.random(0, 0xFFFF)
)

--- Persist `approachMeters` to per-key storage and log the change so we can
--- verify the slider is wired correctly (issue #75 round 5: user reported the
--- slider feels reversed; the formula is correct, but without persistence the
--- value reset to 200 on every reload).
local function setApproachMetersAndPersist(meters)
  local m = tonumber(meters)
  if not m or m ~= m then return end
  m = math.max(50, math.min(500, math.floor(m + 0.5)))
  config.approachMeters = m
  if _approachMetersStorage and type(_approachMetersStorage.set) == "function" then
    pcall(function() _approachMetersStorage:set(m) end)
  end
  if ac and type(ac.log) == "function" then
    ac.log("[COPILOT][APPROACH-DIAG] slider set to " .. tostring(m) .. " m")
  end
end

local function setLapArchiveEnabledAndPersist(enabled)
  config.lapArchiveEnabled = enabled and true or false
  local v = (config.lapArchiveEnabled ~= false) and 1 or 0
  if _lapArchiveEnabledStorage and type(_lapArchiveEnabledStorage.set) == "function" then
    pcall(function() _lapArchiveEnabledStorage:set(v) end)
  end
end

local function setLapArchiveMaxMBAndPersist(mb)
  local m = lapArchive.clampArchiveCapMB(mb)
  config.lapArchiveMaxMB = m
  if _lapArchiveMaxMBStorage and type(_lapArchiveMaxMBStorage.set) == "function" then
    pcall(function() _lapArchiveMaxMBStorage:set(m) end)
  end
end

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
local pendingWsSidecarUrl = nil

-- Forward-declare so closures registered with wsBridge below capture the
-- main state table as an upvalue (Lua resolves locals lexically at compile
-- time; without this they would compile to globals and stay nil — issue #81).
local state

wsBridge.configure(config.wsSidecarUrl or "")

-- Issue #81: external WS clients (rig touchscreen) drive these via the sidecar.
-- Each handler returns (applied:boolean, reason:string|nil); the bridge fans an
-- `action.ack` back to the originator.
if wsBridge.registerActionHandler then
  wsBridge.registerActionHandler("toggleFocusPractice", function()
    state.focusPracticeActive = not (state.focusPracticeActive or false)
    return true, nil
  end)
  wsBridge.registerActionHandler("cycleRacingLine", function()
    -- "best" -> "last" -> "both" -> "best" cycle (matches Draw3D modes).
    local cur = config.racingLineMode or "best"
    local nxt
    if cur == "best" then nxt = "last"
    elseif cur == "last" then nxt = "both"
    else nxt = "best" end
    config.racingLineMode = nxt
    return true, "now: " .. nxt
  end)
  wsBridge.registerActionHandler("tareDelta", function()
    -- Drop any in-flight queued coaching/corner advice for the current lap;
    -- next sample will rebuild a clean delta baseline.
    pcall(function() wsBridge.clearPendingCoaching() end)
    pcall(function() wsBridge.clearCornerAdvisories() end)
    return true, nil
  end)
  wsBridge.registerActionHandler("reloadSetup", function(_)
    return false, "reloadSetup not yet implemented (issue #81 phase-2)"
  end)
  wsBridge.registerActionHandler("applySetupFromPath", function(_)
    return false, "applySetupFromPath not yet implemented (issue #81 phase-2)"
  end)
end

local function applyExternalConfigSet(key, value)
  if config[key] == nil then
    return false, "unknown config key"
  end
  if key == "approachMeters" then
    local n = tonumber(value)
    if n == nil then return false, "value must be numeric" end
    setApproachMetersAndPersist(n)
    return true, nil
  end
  if key == "lapArchiveEnabled" then
    if type(value) ~= "boolean" then return false, "value must be boolean" end
    setLapArchiveEnabledAndPersist(value)
    return true, nil
  end
  if key == "lapArchiveMaxMB" then
    local n = tonumber(value)
    if n == nil then return false, "value must be numeric" end
    setLapArchiveMaxMBAndPersist(n)
    return true, nil
  end
  if key == "wsSidecarUrl" then
    local u = tostring(value or "")
    config.wsSidecarUrl = u
    if _wsUrlStorage and type(_wsUrlStorage.set) == "function" then
      pcall(function() _wsUrlStorage:set(u) end)
    end
    -- Delay reconfigure so pollInbound can send config.ack on the current socket first.
    pendingWsSidecarUrl = u
    return true, nil
  end
  -- Type-match the persisted/default value so the screen cannot inject a string
  -- where a boolean is expected.
  local existing = config[key]
  if type(existing) == "boolean" then
    if type(value) ~= "boolean" then return false, "value must be boolean" end
    config[key] = value
  elseif type(existing) == "number" then
    local n = tonumber(value)
    if n == nil then return false, "value must be numeric" end
    config[key] = n
  elseif type(existing) == "string" then
    config[key] = tostring(value)
  else
    return false, "unsupported config type"
  end
  return true, nil
end

if wsBridge.registerConfigBridge then
  wsBridge.registerConfigBridge(
    function(key)
      return config[key]
    end,
    function(key, value)
      return applyExternalConfigSet(key, value)
    end
  )
end

-- Issue #77 Part A: resolve the deployed app dir (where start_sidecar.bat lives)
-- so wsBridge can spawn the sidecar without hardcoded paths.
local appDir = nil
do
  local info = debug.getinfo(1, "S")
  if info and type(info.source) == "string" then
    local src = info.source
    if src:sub(1, 1) == "@" then src = src:sub(2) end
    -- src is the absolute path to ac_copilot_trainer.lua; strip filename
    appDir = src:match("^(.*)[/\\][^/\\]+$")
  end
end
if not appDir or appDir == "" then
  appDir = "."  -- fallback; .bat will fail and log clearly
end

-- Kick off sidecar spawn at script load. Subsequent wsBridge.tick calls also
-- invoke startSidecarIfNeeded so a crashed child gets relaunched after the
-- LAUNCH_RETRY_SEC gap.
pcall(function() wsBridge.startSidecarIfNeeded(appDir) end)

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
      -- Only emit min speed: we do not have a distinct apex sample yet; duplicating the
      -- same value as both min and apex would double-count metrics in sidecar ranking (#55).
      corners[#corners + 1] = {
        id = i,
        minSpeedKmh = math.floor(minS + 0.5),
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

-- `state` is forward-declared above so wsBridge closures capture the upvalue slot.
-- Do not read `state.<field>` before this assignment.
state = {
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
  -- Round 10: per-corner LLM advisories. Populated by wsBridge
  -- corner_advice replies; consumed by realtime_coaching.tick.
  cornerAdvisories = {},
  --- Lap invalidation ORed each frame (`carLapInvalidatedFlag`) for archive `is_valid`.
  lapInvalidatedThisLap = false,
  --- Issue #44: runtime toggle (HUD checkbox); survives rolling session reset; cleared on full track exit.
  focusPracticeActive = false,
  --- Copy of `consistencySummary().worstThree` strings after each analytics lap.
  focusWorstThree = {},
  --- Last lap corner features for spline matching (clone).
  lastLapCornerFeats = {},
  --- One-line HUD summary for focus targets.
  focusPracticeHudSummary = "",
  --- Invalidation key for `focusPracticeHudSummary` (avoid rebuilding every frame).
  focusPracticeHudSummarySig = nil,
  --- Parsed `corners.ini` by section id; invalidated when `cornerIniTrackKey` changes (issue #57).
  cornerIniById = {},
  cornerIniTrackKey = nil,
  --- Precomputed `T1` -> "Left"|"Right" from best reference trace (invalidated with segments/trace).
  cornerSteerSideByLabel = {},
  cornerSteerSideCacheKey = nil,
}

-- HUD sees only focus-practice fields (checkbox + summary), not the full `state` table.
local focusPracticeUiProxy = setmetatable({}, {
  __index = function(_, k)
    if k == "focusPracticeActive" then
      return state.focusPracticeActive
    end
    if k == "focusPracticeHudSummary" then
      return state.focusPracticeHudSummary
    end
    return nil
  end,
  __newindex = function(_, k, v)
    if k == "focusPracticeActive" then
      state.focusPracticeActive = v
      return
    end
    if k == "focusPracticeHudSummary" then
      state.focusPracticeHudSummary = v
      return
    end
  end,
})

--- Issue #44: map of corner labels -> true for marker emphasis + coaching filter.
---@return table<string, boolean>|nil, boolean manualUsed
local function focusLabelMap()
  if not state.focusPracticeActive then
    return nil, false
  end
  local manual = config.focusPracticeCornerLabels
  if type(manual) == "string" and manual:match("%S") then
    return focusPractice.cornerLabelsMapFromString(manual), true
  end
  return focusPractice.cornerLabelsMapFromWorst(state.focusWorstThree, config.focusPracticeAutoCount), false
end

--- Stable string for when `describeFocusMap` output can change (lap / worst corners / manual labels / toggle).
local function focusHudSummarySig()
  if not state.focusPracticeActive then
    return "off"
  end
  local manual = config.focusPracticeCornerLabels
  if type(manual) == "string" and manual:match("%S") then
    return "m:" .. manual
  end
  local w = state.focusWorstThree
  local wstr = ""
  if type(w) == "table" then
    for i = 1, #w do
      wstr = wstr .. tostring(w[i]) .. "|"
    end
  end
  return "a:"
    .. tostring(config.focusPracticeAutoCount or 0)
    .. ":"
    .. wstr
    .. ":"
    .. tostring(state.lapsCompleted or -1)
end

local function rebuildBestReference()
  state.bestSortedTrace = delta.prepareTrace(state.bestLapTrace)
  local b = delta.sectorBoundariesMs(state.bestSortedTrace)
  if b then
    state.bestSectorMs = { b[1], b[2] - b[1], b[3] - b[2] }
  else
    state.bestSectorMs = { 0, 0, 0 }
  end
  resetDeltaSmoother()
  state.cornerSteerSideCacheKey = nil
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
    state.cornerSteerSideCacheKey = nil
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
  state.cornerIniById = {}
  state.cornerIniTrackKey = nil
  state.cornerSteerSideByLabel = {}
  state.cornerSteerSideCacheKey = nil
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
  state.cornerAdvisories = {}
  state.lapInvalidatedThisLap = false
  state.focusPracticeActive = false
  state.focusWorstThree = {}
  state.lastLapCornerFeats = {}
  state.focusPracticeHudSummary = ""
  state.focusPracticeHudSummarySig = nil
  -- New driving stint without Lua reload: keep archive session ids disjoint (Codex #78).
  SESSION_UUID = string.format(
    "%04x%04x%04x",
    math.random(0, 0xFFFF),
    math.random(0, 0xFFFF),
    math.random(0, 0xFFFF)
  )
  wsBridge.reset()
  renderDiag.reset()
  realtimeCoaching.reset()
  state.realtimeActiveHint = nil
  state._cachedRealtimeView = nil
  hud.reset()
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
  state.cornerAdvisories = {}
  state.lapInvalidatedThisLap = false
  state.lapsCompleted = 0
  state.focusWorstThree = {}
  state.lastLapCornerFeats = {}
  state.focusPracticeHudSummary = ""
  state.focusPracticeHudSummarySig = nil
  state.realtimeActiveHint = nil
  state._cachedRealtimeView = nil
  -- Rolling reset without leaving track: disjoint archive `session_uuid` vs prior stint (Codex #78).
  SESSION_UUID = string.format(
    "%04x%04x%04x",
    math.random(0, 0xFFFF),
    math.random(0, 0xFFFF),
    math.random(0, 0xFFFF)
  )
  hud.reset()
  realtimeCoaching.reset()
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
  if wsBridge.clearCornerAdvisories then
    pcall(wsBridge.clearCornerAdvisories)
  end
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

--- Key changes when track, segment layout, or reference trace length changes.
local function cornerSteerSidesCacheKey()
  local segs = state.trackSegments
  local tr = state.bestSortedTrace
  local n = type(segs) == "table" and #segs or 0
  local t = type(tr) == "table" and #tr or 0
  local tk = ch.trackIdRawFromGlobals() or ""
  local h = 0.0
  if n > 0 and type(segs[1]) == "table" then
    h = (tonumber(segs[1].s0) or 0) * 1e6 + (tonumber(segs[1].s1) or 0)
  end
  return string.format("%s|%d|%d|%.6f", tk, n, t, h)
end

--- One full trace scan per (segments × reference trace) change; HUD reads O(1) map (PR #58).
local function rebuildCornerSteerSideCache()
  state.cornerSteerSideByLabel = {}
  local segs = state.trackSegments
  local tr = state.bestSortedTrace
  if type(segs) ~= "table" or type(tr) ~= "table" or #tr < 2 then
    return
  end
  for i = 1, #segs do
    local seg = segs[i]
    if type(seg) == "table" and seg.kind == "corner" and type(seg.label) == "string" then
      local s0, s1 = seg.s0, seg.s1
      if type(s0) == "number" and type(s1) == "number" then
        local wrap = s1 <= s0
        state.cornerSteerSideByLabel[seg.label] = cornerNames.steerSideForRange(tr, s0, s1, wrap)
      end
    end
  end
end

local function ensureCornerSteerSides()
  local key = cornerSteerSidesCacheKey()
  if state.cornerSteerSideCacheKey == key then
    return
  end
  rebuildCornerSteerSideCache()
  state.cornerSteerSideCacheKey = key
end

local function ensureCornerIniLoaded()
  local tk = ch.trackIdRawFromGlobals() or "unknown"
  if state.cornerIniTrackKey == tk and type(state.cornerIniById) == "table" then
    return
  end
  state.cornerIniTrackKey = tk
  state.cornerIniById = {}
  if not ac or type(ac.getTrackDataFilename) ~= "function" then
    return
  end
  local okPath, path = pcall(ac.getTrackDataFilename, "corners.ini")
  if not okPath or type(path) ~= "string" or path == "" then
    return
  end
  local f = io.open(path, "r")
  if not f then
    return
  end
  local body = f:read("*a")
  f:close()
  state.cornerIniById = cornerNames.parseCornersIni(body)
end

--- Structured approach telemetry for HUD + coaching panel (issue #57 Part A).
---@param sim0 ac.StateSim|nil
---@return table|nil
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
    speed = car.speedKmh or 0,
    brake = car.brake or 0,
    lapCount = car.lapCount or 0,
    bestLapMs = state.bestLapMs or (car.bestLapTimeMs or nil),
    lastLapMs = state.lastLapMs or (car.previousLapTimeMs or nil),
    deltaSmoothedSec = dSmooth,
    sectorMessage = secMsg,
    realtimeHint = state.realtimeActiveHint,
    realtimeView = state._cachedRealtimeView,
    postLapLines = postLines,
    coastWarn = coastWarn,
    tireLockupFlash = tires:lockupFlash(),
    setupChangeMsg = state.setupChangeMsg,
    autoSetupLine = autoSetupLine,
    coachingLines = coachingHudLines,
    coachingRemaining = coachRem,
    coachingHoldSeconds = normalizedCoachingHoldSeconds(),
    coachingMaxVisibleHints = normalizedCoachingMaxVisibleHints(),
    coachingShowPrimer = coachPrimer,
    appVersionUi = APP_VERSION_UI,
    debriefText = (state.sidecarDebriefText ~= "") and state.sidecarDebriefText or nil,
    focusPracticeActive = state.focusPracticeActive or false,
    focusPracticeLabel = (state.focusPracticeHudSummary ~= "") and state.focusPracticeHudSummary or nil,
  })
end

function script.windowSettings(_dt)
  sim = ac.getSim()
  if not sim or sim.isInMainMenu then
    ui.text("Open Settings after loading a session (not from the main menu).")
    return
  end
  car = ac.getCar(0)
  if not car then
    ui.text("Waiting for car data…")
    return
  end
  hudSettings.draw({
    config = config,
    stats = {
      telemetrySamples = tel:sampleCount(),
      brakeBest = #state.brakingPoints.best,
      brakeLast = #state.brakingPoints.last,
      brakeSession = #state.brakingPoints.session,
      refAiDistanceM = state.refLatDistance,
      segmentCount = #(state.trackSegments or {}),
      throttleLapHint = state.lastThrottleSummary,
      consistencyHud = state.consistencyHud,
      styleHud = state.styleHud,
      tireHud = state.tireHud,
    },
    focusPracticeUi = focusPracticeUiProxy,
    -- Issue #77 Part A: Settings UI shows sidecar process + connection status.
    sidecarSpawnedAlive = wsBridge.sidecarSpawnedAlive,
    sidecarConnected = wsBridge.sidecarConnected,
    -- Issue #77 Part C: lap archive stats for Settings UI.
    lapArchiveStats = lapArchive.stats,
    lapArchiveClampCapMB = lapArchive.clampArchiveCapMB,
    setApproachMeters = setApproachMetersAndPersist,
    setLapArchiveEnabled = setLapArchiveEnabledAndPersist,
    setLapArchiveMaxMB = setLapArchiveMaxMBAndPersist,
  })
  if config.enableRenderDiagnostics then
    renderDiag.drawUI()
  end
end

--- Coaching window (WINDOW_1) - issue #72 rebuild.
--- Always renders the structured approach panel (chrome + footer + placeholders).
function script.windowCoaching(_dt)
  if not config.hudEnabled then return end
  sim = sim or ac.getSim()
  if not sim or sim.isInMainMenu then return end
  car = car or ac.getCar(0)
  local now = ch.simSeconds(sim)
  local remaining = state.coachingRemainSec or 0
  local laps = state.lapsCompleted or 0

  -- Periodic coaching diag (every 5s for first 60s, then stops)
  if not state._coachDiagT then state._coachDiagT = 0 end
  if not state._coachDiagCount then state._coachDiagCount = 0 end
  state._coachDiagT = state._coachDiagT + (_dt or 0)
  if state._coachDiagCount < 12 and state._coachDiagT > 5.0 and ac and type(ac.log) == "function" then
    state._coachDiagT = 0
    state._coachDiagCount = state._coachDiagCount + 1
    ac.log(string.format(
      "[COPILOT] coaching: simT=%.1f remainSec=%.2f lines=%d laps=%d (rebuild #72)",
      now, remaining, state.coachingLines and #state.coachingLines or 0, laps))
  end

  -- Always render the bottom tile (issue #72: never an empty box).
  -- Build the viewmodel from the cached realtime view; pass nil to render
  -- chrome + placeholders when no data exists yet.
  local view = state._cachedRealtimeView
  local payload
  if view then
    -- Bottom tile shows the UPCOMING brake target (always), not the current
    -- corner. view.approachLabel/targetSpeedKmh/distToBrakeM all point to the
    -- next braking opportunity ahead. view.cornerLabel is the in-corner label
    -- (used by the TOP tile only) — falls back to approachLabel if not in a
    -- corner apex.
    payload = {
      turnLabel        = view.approachLabel or view.cornerLabel,
      targetSpeedKmh   = view.targetSpeedKmh,
      currentSpeedKmh  = view.currentSpeedKmh,
      distanceToBrakeM = view.distToBrakeM,
      progressPct     = view.progressPct or 0,
      subState        = view.subState or "no_reference",
      status          = view.subState or "no_reference",
    }
  end
  -- Round 10: the approach panel is the sole content of WINDOW_1.
  -- Post-lap debrief was rejected by the user in favor of in-race per-
  -- corner LLM coaching delivered via view.secondaryLine overrides on
  -- the TOP tile (WINDOW_0). See realtime_coaching.lua round 10 block.
  coachingOverlay.drawApproachPanel(payload)
end

-- Issue #72: place each window once on first install (persisted via ac.storage),
-- then leave the user alone forever. Position is user-controlled after this runs.
-- Window SIZE is locked by the FIXED_SIZE manifest flag (not by this function).
-- Issue #75: force window geometry on EVERY app load. The previous
-- once-per-install gate (`hud_auto_placed_v1` storage flag) caused the
-- imgui-persisted Pos+Size from `Documents/Assetto Corsa/cfg/extension/state/imgui.ini`
-- to leak in and override the manifest defaults forever. CSP's FIXED_SIZE
-- flag only disables interactive resizing — it does NOT clear persisted
-- imgui state — so the only reliable fix is to call win:resize+win:move on
-- every cold start until both succeed for all three windows.
local function autoPlaceOnce()
  if state._autoPlaceChecked then return end
  if type(ac) ~= "table" then return end
  if type(ac.getAppWindows) ~= "function" or type(ac.accessAppWindow) ~= "function" then
    -- API not available yet — try again next frame instead of permanently
    -- skipping the recovery path on a cold start.
    return
  end

  local localSim = ac.getSim() or {}
  local screenW = tonumber(localSim.windowWidth) or 1920
  local screenH = tonumber(localSim.windowHeight) or 1080
  local sizes = {}
  for title, wh in pairs(MANIFEST_WINDOW_SIZES) do
    sizes[title] = vec2(wh[1], wh[2])
  end
  local positions = {
    ["AC Copilot Trainer"] = vec2(math.floor(screenW * 0.5 - 260), math.floor(screenH * 0.04)),
    ["Coaching"]           = vec2(math.floor(screenW * 0.5 - 320), math.floor(screenH * 0.78)),
    ["Settings"]           = vec2(math.floor(screenW * 0.05),     math.floor(screenH * 0.10)),
  }
  local required = 0
  for _ in pairs(sizes) do required = required + 1 end

  local windows = ac.getAppWindows() or {}
  if #windows == 0 then
    -- Window list still empty (e.g. very early frame). Try again next frame.
    return
  end

  local applied = 0
  for i = 1, #windows do
    local entry = windows[i]
    local title = entry and entry.title or nil
    local sizeTarget = title and sizes[title] or nil
    local posTarget  = title and positions[title] or nil
    if sizeTarget and posTarget then
      local ok, win = pcall(ac.accessAppWindow, entry.name)
      if ok and win and win:valid() then
        local resizeOk = pcall(function() win:resize(sizeTarget) end)
        local moveOk   = pcall(function() win:move(posTarget) end)
        if resizeOk and moveOk then applied = applied + 1 end
      end
    end
  end

  if applied >= required then
    state._autoPlaceChecked = true
    if ac and type(ac.log) == "function" then
      ac.log(string.format(
        "[COPILOT][AUTOPLACE] forced %d/%d windows to manifest geometry on this load",
        applied, required))
    end
  end
end

--- CSP lap invalidation flags differ by build; probe known names without throwing.
--- `ac.StateCar` is userdata in real CSP — never gate on `type(...) == "table"` (Codex #78).
local function carLapInvalidatedFlag(carObj)
  if carObj == nil then
    return false
  end
  for _, key in ipairs({ "isLapInvalidated", "isCurrentLapInvalid", "currentLapInvalid" }) do
    local ok, v = pcall(function()
      return carObj[key]
    end)
    if ok and v == true then
      return true
    end
  end
  return false
end

function script.update(dt)
  sim = ac.getSim()
  car = ac.getCar(0)

  autoPlaceOnce()

  -- Live-frame coaching tick (issue #72 rebuild).
  -- Inputs are LIVE FRAME values and persisted reference data, NOT lap aggregates.
  -- The engine returns a viewmodel even with no reference (no_reference subState).
  if car then
    local sp = car.splinePosition or 0
    local cur = car.speedKmh or 0
    local tlM = sim and sim.trackLengthM or nil
    local approachM = tonumber(config.approachMeters)
    if not approachM or approachM ~= approachM or approachM <= 0 then
      approachM = 200
    end
    -- Round 10: pass wsBridge so realtime engine can fire corner_query
    -- on corner transitions, and state.cornerAdvisories for the override.
    local rtView = realtimeCoaching.tick({
      splinePos = sp,
      currentSpeedKmh = cur,
      bestSortedTrace = state.bestSortedTrace,
      brakingPoints = state.brakingPoints and state.brakingPoints.best or nil,
      segments = state.trackSegments,
      trackLengthM = tlM,
      approachMeters = approachM,
      dt = dt,
      wsBridge = wsBridge,
      cornerAdvisories = state.cornerAdvisories,
      lap = state.lapsCompleted or 0,
      simT = ch.simSeconds(sim),
    })
    state._cachedRealtimeView = rtView
    state.realtimeActiveHint = rtView

    -- Periodic [RT-DIAG] log (every 3 sec) to verify what the engine sees
    -- live. Issue #75 round 3: prove the in-corner / brake-distance pipeline.
    state._rtDiagT = (state._rtDiagT or 0) + (dt or 0)
    if state._rtDiagT >= 3.0 and ac and type(ac.log) == "function" then
      state._rtDiagT = 0
      local function fmt(v, w)
        if v == nil then return "nil" end
        if type(v) == "number" then return string.format(w or "%.1f", v) end
        return tostring(v)
      end
      ac.log(string.format(
        "[COPILOT][RT-DIAG] sp=%s cur=%s primary=%s sub=%s topCorner=%s nextCorner=%s tgt=%s dist=%sm trace=%d brakes=%d segs=%d trackLen=%s",
        fmt(sp, "%.4f"), fmt(cur, "%.0f"),
        fmt(rtView and rtView.primaryLine), fmt(rtView and rtView.subState),
        fmt(rtView and rtView.cornerLabel), fmt(rtView and rtView.approachLabel),
        fmt(rtView and rtView.targetSpeedKmh, "%.0f"),
        fmt(rtView and rtView.distToBrakeM, "%.0f"),
        (state.bestSortedTrace and #state.bestSortedTrace) or 0,
        (state.brakingPoints and state.brakingPoints.best and #state.brakingPoints.best) or 0,
        (state.trackSegments and #state.trackSegments) or 0,
        fmt(tlM, "%.0f")
      ))
    end
  else
    state._cachedRealtimeView = nil
    state.realtimeActiveHint = nil
  end

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

  -- Issue #77 Part A: start sidecar before tick so we do not duplicate tryOpen() in the same frame.
  pcall(function() wsBridge.startSidecarIfNeeded(appDir) end)
  wsBridge.tick(ch.simSeconds(sim))
  wsBridge.pollInbound(8)
  if pendingWsSidecarUrl ~= nil then
    wsBridge.configure(pendingWsSidecarUrl)
    pendingWsSidecarUrl = nil
  end
  -- Round 10: drain any corner_advice replies into state.cornerAdvisories.
  -- The takeCornerAdvisory API returns the cached text for a label without
  -- consuming it — we walk known corner labels from trackSegments and copy.
  if state.trackSegments and type(state.trackSegments) == "table" then
    for i = 1, #state.trackSegments do
      local seg = state.trackSegments[i]
      if seg and seg.kind == "corner" and type(seg.label) == "string" then
        local txt = wsBridge.takeCornerAdvisory(seg.label, state.lapsCompleted)
        if txt then
          state.cornerAdvisories[seg.label] = txt
        else
          state.cornerAdvisories[seg.label] = nil
        end
      end
    end
  end
  local sidecarHints, sidecarDebrief = wsBridge.takeCoachingForLap(state.lapsCompleted or 0)
  if type(sidecarDebrief) == "string" and sidecarDebrief ~= "" then
    state.sidecarDebriefText = sidecarDebrief
  end
  if sidecarHints and #sidecarHints > 0 then
    local fmSide = select(1, focusLabelMap())
    state.coachingLines = focusPractice.filterCoachingHints(
      sidecarHints,
      state.focusPracticeActive,
      fmSide
    )
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
    -- Last frame of the completed lap may still carry invalidation (CSP `ac.StateCar`).
    if carLapInvalidatedFlag(car) then
      state.lapInvalidatedThisLap = true
    end
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
          state.cornerSteerSideCacheKey = nil
          realtimeCoaching.rebuildSegmentIndex(ns)
        end
      end
      if #state.trackSegments == 0 then
        local ns = cornerAnalysis.buildSegments(completedTrace, segBrakes)
        if #ns > 0 then
          state.trackSegments = ns
          state.cornerSteerSideCacheKey = nil
          realtimeCoaching.rebuildSegmentIndex(ns)
        end
      end
      feats = cornerAnalysis.cornerFeaturesForLap(completedTrace, state.trackSegments)
      cornerAnalysis.appendHistory(state.lapFeatureHistory, { lapMs = lastMs, corners = feats })
      consForHints = cornerAnalysis.consistencySummary(state.lapFeatureHistory)
      state.consistencyHud = ""
      if consForHints and consForHints.worstThree and #consForHints.worstThree > 0 then
        state.consistencyHud = "Least consistent: " .. table.concat(consForHints.worstThree, ", ")
      end
      state.focusWorstThree = {}
      if consForHints and type(consForHints.worstThree) == "table" then
        for wi = 1, #consForHints.worstThree do
          state.focusWorstThree[wi] = consForHints.worstThree[wi]
        end
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
      -- Keep prior `focusWorstThree` (like consistency HUD text): lap history still
      -- holds usable worst-corner rows; clearing here dropped auto-focus after one bad lap (#44).
    end

    if traceAnalyticsOk and #feats > 0 then
      state.lastLapCornerFeats = cloneCornerFeats(feats)
    end

    local rawCoaching = coachingHints.buildAfterLap(feats, state.bestCornerFeatures, consForHints, thA, traceAnalyticsOk)
    local fmForFilter = select(1, focusLabelMap())
    state.coachingLines = focusPractice.filterCoachingHints(rawCoaching, state.focusPracticeActive, fmForFilter)
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

    -- PB flag must use pre-update `bestLapMs` (Cursor #78); archive runs after PB block mutates it.
    local isPbThisLap = lastMs > 0 and (state.bestLapMs == nil or lastMs <= state.bestLapMs)

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

    -- Issue #77 Part C: archive this lap (trace + setup + corners + coaching).
    -- Runs INDEPENDENTLY of sidecar / coaching success. Captures the dataset
    -- for future RAG / classifier / fine-tune work. Forward-compatible schema
    -- so imported MoTeC CSVs (Initiative B) drop into the same shape.
    if config.lapArchiveEnabled ~= false and lastMs > 0 then
      local archiveOpts = {
        session_uuid = SESSION_UUID,
        car = car,
        sim = sim,
        lap_n = state.lapsCompleted,
        lap_ms = lastMs,
        is_pb = isPbThisLap,
        is_valid = not state.lapInvalidatedThisLap,
        trace = completedTrace,
        corners = feats,
        setup_snap = state.lastSetupSnap,
        setup_hash = state.setupHash,
        rules_hints = state.coachingLines,
        -- Omit async sidecar debrief: it is applied on later frames than lap_complete, so stamping it
        -- here would mis-label the archived lap (Codex #78).
        sidecar_debrief = nil,
        -- `lapsCompleted` was incremented above; corner_query / corner_advice use the in-lap index
        -- (Codex + Cursor Bugbot #78 post-5f0ce39).
        corner_advice = wsBridge.cornerAdvisorySnapshotForLap((state.lapsCompleted or 0) - 1),
      }
      local rec = lapArchive.buildRecord(archiveOpts)
      if rec then
        local ok, pathOrErr = lapArchive.write(rec, lapArchive.clampArchiveCapMB(config.lapArchiveMaxMB))
        if ac and type(ac.log) == "function" then
          if ok then
            ac.log("[COPILOT][ARCHIVE] wrote " .. tostring(pathOrErr))
          else
            ac.log("[COPILOT][ARCHIVE] write failed: " .. tostring(pathOrErr))
          end
        end
      end
    end

    state.lapInvalidatedThisLap = false
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

  if not sim.isInMainMenu and state.lastLapCount >= 0 and lc == state.lastLapCount then
    if carLapInvalidatedFlag(car) then
      state.lapInvalidatedThisLap = true
    end
  end

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

  -- `script.update` already returns while `sim.isInMainMenu`; only recompute summary when inputs change.
  if state.focusPracticeActive then
    local sig = focusHudSummarySig()
    if sig ~= state.focusPracticeHudSummarySig then
      state.focusPracticeHudSummarySig = sig
      local flm, man = focusLabelMap()
      state.focusPracticeHudSummary = focusPractice.describeFocusMap(flm, man)
    end
  else
    state.focusPracticeHudSummary = ""
    state.focusPracticeHudSummarySig = nil
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

  if config.brakeMarkersEnabled ~= false then
    local flMap = select(1, focusLabelMap())
    -- Issue #75 round 4: brake marker source follows racingLineMode so the
    -- user only sees what they asked for. "best" hides the orange last-lap
    -- walls, "last" hides the red best walls, "both" shows everything.
    local mode = config.racingLineMode or "best"
    local bestList = (mode == "best" or mode == "both") and state.brakingPoints.best or nil
    local lastList = (mode == "last" or mode == "both") and state.brakingPoints.last or nil
    trackMarkers.draw(c, s, bestList, lastList, {
      active = state.focusPracticeActive == true,
      labels = flMap,
      corners = state.lastLapCornerFeats,
      dimNonFocus = config.focusPracticeDimNonFocus ~= false,
    })
  end
  if config.racingLineEnabled ~= false then
    local mode = config.racingLineMode or "best"
    local style = config.lineStyle or "tilt"
    if mode == "best" or mode == "both" then
      racingLine.drawLineStrip(c, state.racingBestLine, rgbm(0.0, 0.85, 0.25, 0.80), nil, style)
    end
    if mode == "last" or mode == "both" then
      racingLine.drawLineStrip(c, state.racingLastLine, rgbm(0.85, 0.75, 0.0, 0.55), nil, style)
    end
  end
end
