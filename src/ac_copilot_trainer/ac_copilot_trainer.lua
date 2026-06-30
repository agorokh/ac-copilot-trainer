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
-- Issue #86 Part C/D: rig-screen-driven features.
local coachingPublisher = require("coaching_publisher")
local lifecyclePublisher = require("lifecycle_publisher")
local telemetryPublisher = require("telemetry_publisher")
local setupLibrary = require("setup_library")

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
  --- Issue #79: imported MoTeC laps are reference candidates only when explicitly enabled.
  useImportedReference = false,
}

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
local _useImportedReferenceStorage = nil
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
  local ok5, sv5 = pcall(ac.storage, "ac_copilot_trainer.useImportedReference_v1", 0)
  if ok5 and sv5 and type(sv5.get) == "function" then
    _useImportedReferenceStorage = sv5
  end
end

local function isDedicatedPerKeyConfig(key)
  return key == "wsSidecarUrl"
    or key == "approachMeters"
    or key == "lapArchiveEnabled"
    or key == "lapArchiveMaxMB"
    or key == "useImportedReference"
end

local function coercePersistedConfigValue(defaultValue, storedValue)
  local defaultType = type(defaultValue)
  if defaultType == "boolean" then
    if type(storedValue) == "boolean" then
      return storedValue
    end
    local n = tonumber(storedValue)
    if n ~= nil then
      return n ~= 0
    end
    return nil
  end
  if defaultType == "number" then
    local n = tonumber(storedValue)
    if n ~= nil then
      return n
    end
    return nil
  end
  if defaultType == "string" then
    if storedValue == nil then
      return nil
    end
    return tostring(storedValue)
  end
  return nil
end

local function overlayLegacyPerKeyConfig(cfg)
  if not (ac and type(ac.storage) == "function") then
    return
  end
  for key, defaultValue in pairs(CONFIG_DEFAULTS) do
    if not isDedicatedPerKeyConfig(key) then
      local initDefault = defaultValue
      if type(defaultValue) == "boolean" then
        initDefault = defaultValue and 1 or 0
      end
      local okStore, store = pcall(ac.storage, key, initDefault)
      if okStore and store and type(store.get) == "function" then
        local okGet, persisted = pcall(function() return store:get() end)
        if okGet then
          local coerced = coercePersistedConfigValue(defaultValue, persisted)
          if coerced ~= nil then
            cfg[key] = coerced
          end
        end
      end
    end
  end
end

local function persistLegacyPerKeyConfig(key, defaultValue, value)
  if not (ac and type(ac.storage) == "function") then
    return
  end
  local initDefault = defaultValue
  if type(defaultValue) == "boolean" then
    initDefault = defaultValue and 1 or 0
  end
  local okStore, store = pcall(ac.storage, key, initDefault)
  if not (okStore and store and type(store.set) == "function") then
    return
  end
  local persistValue = value
  if type(defaultValue) == "boolean" and type(value) == "boolean" then
    persistValue = value and 1 or 0
  end
  pcall(function() store:set(persistValue) end)
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
  -- External `config.set` writes per-key stores (`ac.storage(key)`) for fields
  -- not covered by dedicated storages. Overlay them here so values survive
  -- reloads even when table-form `ac.storage(defaults)` is unreliable.
  overlayLegacyPerKeyConfig(cfg)
  -- Overlay the per-key wsSidecarUrl (table-form is broken on this CSP build).
  -- Issue #78: empty stored URL used to mean "cleared"; with auto-launch + no URL
  -- editor in Settings, migrate empty back to localhost and persist so wsBridge.tick connects.
  if _wsUrlStorage and type(_wsUrlStorage.get) == "function" then
    local ok, val = pcall(function() return _wsUrlStorage:get() end)
    if ok and type(val) == "string" then
      local migrated = false
      if val == "" then
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
  if _useImportedReferenceStorage and type(_useImportedReferenceStorage.get) == "function" then
    local ok, val = pcall(function() return _useImportedReferenceStorage:get() end)
    if ok and val ~= nil then
      local n = tonumber(val)
      if n ~= nil then
        cfg.useImportedReference = (n ~= 0)
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

local refreshActiveReference

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

local function setUseImportedReferenceAndPersist(enabled)
  config.useImportedReference = enabled and true or false
  local v = config.useImportedReference and 1 or 0
  if _useImportedReferenceStorage and type(_useImportedReferenceStorage.set) == "function" then
    pcall(function() _useImportedReferenceStorage:set(v) end)
  end
  if refreshActiveReference then
    pcall(refreshActiveReference)
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
local pendingLapArchiveJobs = {}
local pendingLapArchiveRecordPaths = {}
local bestLapArchivePath = nil
local LAP_ARCHIVE_ROWS_PER_FRAME = 64
-- Per-step row budget used by the synchronous session-end drain (issue #305). Far above any
-- real lap's downsampled trace (~2000 rows) so a single step finishes the whole job.
local LAP_ARCHIVE_FLUSH_ROWS = 1000000

-- Forward-declare so closures registered with wsBridge below capture the
-- main state table as an upvalue (Lua resolves locals lexically at compile
-- time; without this they would compile to globals and stay nil — issue #81).
local state

local function shallowCopy(tbl)
  local out = {}
  if type(tbl) ~= "table" then
    return out
  end
  for k, v in pairs(tbl) do
    out[k] = v
  end
  return out
end

local function queueLapArchiveJob(archiveOpts, notifyOpts)
  local job, err = lapArchive.createWriteJob(
    archiveOpts,
    lapArchive.clampArchiveCapMB(config.lapArchiveMaxMB)
  )
  if not job then
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT][ARCHIVE] queue failed: " .. tostring(err))
    end
    return
  end
  if type(notifyOpts) == "table" then
    job._copilotNotify = notifyOpts
  end
  pendingLapArchiveJobs[#pendingLapArchiveJobs + 1] = job
  if ac and type(ac.log) == "function" then
    ac.log("[COPILOT][ARCHIVE] queued async write samples=" .. tostring(job.samplesCount or 0)
      .. " queue=" .. tostring(#pendingLapArchiveJobs))
  end
end

local function pumpLapArchiveJobs(maxRows)
  local job = pendingLapArchiveJobs[1]
  if not job then return end
  local done, ok, pathOrErr = job:step(maxRows or LAP_ARCHIVE_ROWS_PER_FRAME)
  if not done then return end
  table.remove(pendingLapArchiveJobs, 1)
  if ac and type(ac.log) == "function" then
    if ok then
      ac.log("[COPILOT][ARCHIVE] wrote " .. tostring(pathOrErr))
    else
      ac.log("[COPILOT][ARCHIVE] write failed: " .. tostring(pathOrErr))
    end
  end
  if ok and type(pathOrErr) == "string" then
    local notification = {
      path = pathOrErr,
      setupRecordSent = false,
      archiveLapSent = false,
    }
    local notify = type(job._copilotNotify) == "table" and job._copilotNotify or nil
    if notify and type(notify.archiveLapPayload) == "table" then
      local payload = shallowCopy(notify.archiveLapPayload)
      payload.archivePath = pathOrErr
      if type(notify.referenceArchivePath) == "string" and notify.referenceArchivePath ~= "" then
        payload.referenceArchivePath = notify.referenceArchivePath
      end
      notification.archiveLapPayload = payload
    end
    if notify and notify.isBestLapArchive == true then
      bestLapArchivePath = pathOrErr
    end
    pendingLapArchiveRecordPaths[#pendingLapArchiveRecordPaths + 1] = notification
  end
end

--- Synchronously force EVERY pending archive job to completion (issue #305).
--- The per-frame `pumpLapArchiveJobs` only advances the queue while `script.update`
--- reaches its body. When a session ends (back to the main menu) update() returns
--- early — before the per-frame pump — so a job queued for the LAST lap driven (the
--- common "hot lap, then pit / stop" case) would otherwise be abandoned mid-stream as
--- a partial `.tmp` and its trace lost. Drain it here instead, before that early return.
--- `LAP_ARCHIVE_FLUSH_ROWS` finishes each front job in a single step; a hard iteration
--- cap guarantees this can never spin even if a job's step path ever misbehaves.
local function flushPendingLapArchiveJobs(reason)
  if #pendingLapArchiveJobs == 0 then
    return
  end
  if ac and type(ac.log) == "function" then
    ac.log("[COPILOT][ARCHIVE] flushing " .. tostring(#pendingLapArchiveJobs)
      .. " pending job(s) on " .. tostring(reason or "session end"))
  end
  local guard = 0
  while #pendingLapArchiveJobs > 0 and guard < 4096 do
    guard = guard + 1
    local before = #pendingLapArchiveJobs
    pumpLapArchiveJobs(LAP_ARCHIVE_FLUSH_ROWS)
    if #pendingLapArchiveJobs == before then
      -- A step with the flush budget always reaches `done`, so the front job is removed
      -- above; this guard only fires if that contract ever breaks — drop it rather than spin.
      table.remove(pendingLapArchiveJobs, 1)
    end
  end
end

local function pumpLapArchiveNotifications()
  if not (wsBridge and type(wsBridge.sendSetupExperimentRecord) == "function") then
    return
  end
  while #pendingLapArchiveRecordPaths > 0 do
    local item = pendingLapArchiveRecordPaths[1]
    if type(item) == "string" then
      item = { path = item, setupRecordSent = false, archiveLapSent = true }
      pendingLapArchiveRecordPaths[1] = item
    end
    local path = type(item) == "table" and item.path or nil
    if type(path) ~= "string" or path == "" then
      table.remove(pendingLapArchiveRecordPaths, 1)
    else
      if not item.setupRecordSent then
        local sent = false
        pcall(function()
          sent = wsBridge.sendSetupExperimentRecord(path) == true
        end)
        if sent then
          item.setupRecordSent = true
        else
          -- Keep the path queued; handshake/reconnect can become ready on a later frame.
          return
        end
      end
      if type(item.archiveLapPayload) == "table" and not item.archiveLapSent then
        local sent = false
        pcall(function()
          sent = wsBridge.sendJson(item.archiveLapPayload) == true
        end)
        if sent then
          item.archiveLapSent = true
        else
          -- Avoid re-sending the setup record; retry only the archive-backed lap_complete later.
          return
        end
      end
      table.remove(pendingLapArchiveRecordPaths, 1)
    end
  end
end

wsBridge.configure(config.wsSidecarUrl or "")
if wsBridge.setSetupExperimentStorePath then
  pcall(function()
    wsBridge.setSetupExperimentStorePath(
      persistence.dataDir() .. "/journal/setup_experiments/experiments.jsonl")
  end)
end

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

-- Issue #86 Part D4: bidirectional setup picker. The screen sends
-- `setup.list` to enumerate, then `setup.load` to apply by name. Both
-- responses go back over the existing v1 envelope.
if wsBridge.registerRequestHandler then
  wsBridge.registerRequestHandler("setup.list", "setup.list.result", function(_payload)
    local ident = setupLibrary.activeIdentity()
    local list = setupLibrary.list()
    -- Precompute BEST once per list refresh — `bestForSetup` walks matching
    -- lap JSONs (full journal, sorted newest-first) per row. Doing that
    -- inside the per-row loop was O(rows×N) disk reads (CodeRabbit on PR #91).
    local bestCache = {}
    for j = 1, #list do
      local e = list[j]
      local key = (type(e.path) == "string" and e.path ~= "") and e.path or ("n:" .. tostring(e.name))
      if bestCache[key] == nil then
        bestCache[key] = setupLibrary.bestForSetup(e.name, e.path)
      end
    end
    local items = {}
    for i = 1, #list do
      local entry = list[i]
      local name = entry.name
      local mtime = tonumber(entry.mtime)
      local mtimeIso = nil
      if mtime and os and type(os.date) == "function" then
        local okIso, s = pcall(os.date, "!%Y-%m-%dT%H:%M:%SZ", mtime)
        if okIso and type(s) == "string" then
          mtimeIso = s
        end
      end
      -- Per-row summary: brake bias / abs / tc / wing front+rear from the
      -- INI. Bounded: this opens each setup file once when the list is
      -- requested. With per-track filter capping at <50 setups in a busy
      -- session this is well under a frame budget.
      local sum = {}
      local okSum, sumOrErr = pcall(setupLibrary.summaryForSetup, entry.path)
      if okSum and type(sumOrErr) == "table" then
        sum = sumOrErr
      elseif ac and type(ac.log) == "function" then
        local detail = okSum and "non-table return" or tostring(sumOrErr)
        ac.log("[COPILOT][setup.list] summaryForSetup failed for "
          .. tostring(entry.path) .. ": " .. detail)
      end
      local bkey = (type(entry.path) == "string" and entry.path ~= "") and entry.path
        or ("n:" .. tostring(name))
      -- Round-trip chip fields as integers so the screen JSON parser never
      -- drops BB on float/string shapes (issue #93).
      local function chipInt(v)
        if v == nil then return nil end
        local n = tonumber(v)
        if n == nil then return nil end
        return math.floor(n + 0.5)
      end
      items[i] = {
        name = name,
        mtime_iso = mtimeIso,
        best_ms = bestCache[bkey],
        path = entry.path,
        brake_bias = chipInt(sum.brake_bias),
        abs = chipInt(sum.abs),
        tc = chipInt(sum.tc),
        wing_f = chipInt(sum.wing_f),
        wing_r = chipInt(sum.wing_r),
      }
    end
    return {
      ok = true,
      car_id = ident.car_id,
      car_name = ident.car_name,        -- "Porsche 911 GT3 R 2016"
      car_brand = ident.car_brand,      -- "Porsche"
      car_class = ident.car_class,      -- "race"
      track_id = ident.track_id,
      track_name = ident.track_name,    -- "Monza"
      track_country = ident.track_country,
      setups = items,
    }
  end)

  -- D5 safety gate: refuse loads when CSP says reset is not allowed (i.e.
  -- not in the pits / not on an out-lap). Same gate PT enforces by hiding
  -- its window. The screen renders the red toast on `ok=false`.
  wsBridge.registerRequestHandler("setup.load", "setup.load.ack", function(payload)
    local name = (type(payload) == "table" and tostring(payload.name or "")) or ""
    local path = nil
    if type(payload) == "table" and type(payload.path) == "string" and payload.path ~= "" then
      path = payload.path
    end
    if name == "" and not path then
      return { ok = false, name = name, error = "missing name" }
    end
    -- Fail closed: only allow when CSP explicitly reports reset is allowed.
    -- Missing API / pcall failure must NOT bypass the pits gate (Cursor +
    -- CodeRabbit on PR #91).
    local resetOk = false
    if ac and type(ac.isCarResetAllowed) == "function" then
      local okCall, allowed = pcall(ac.isCarResetAllowed)
      resetOk = okCall and (allowed == true)
    end
    if not resetOk then
      return { ok = false, name = name, error = "must be in pits" }
    end
    -- Pass both name and path so the library can disambiguate same-basename
    -- files across track/layout folders. Normalize a non-table return into
    -- a well-formed ack so the screen never sees an ambiguous response
    -- (CodeRabbit on PR #91: nil/non-table from loadByName used to ship a
    -- malformed ack with no `ok` field, which the screen contract treats
    -- as success).
    local ack = setupLibrary.loadByName({ name = name, path = path })
    if type(ack) ~= "table" then
      ack = { ok = false, name = name, error = "library returned no ack" }
    elseif ack.ok == nil then
      ack.ok = false
      if ack.error == nil then ack.error = "library returned malformed ack" end
    end
    if ack.name == nil then ack.name = name end
    if ack and ack.ok and wsBridge.publishTopic then
      -- D4: broadcast `setup.active` so PT and the launcher stay in sync.
      -- Setup hash is computed via setup_reader on the next tick when
      -- snapshotActive runs; for the immediate broadcast we send the path
      -- and let the screen UI treat hash as advisory.
      pcall(function()
        wsBridge.publishTopic("setup.active", {
          name = ack.name,
          path = ack.path,
          changed_at = (os and os.time and os.time()) or 0,
        })
      end)
    end
    return ack
  end)

  wsBridge.registerRequestHandler("setup.spinner.list", "setup.spinner.list.result", function(payload)
    local result = setupLibrary.listSpinners(payload)
    if type(result) ~= "table" then
      return { ok = false, error = "library returned no spinner list" }
    end
    return result
  end)

  wsBridge.registerRequestHandler("setup.spinner.set", "setup.spinner.set.ack", function(payload)
    local section = ""
    if type(payload) == "table" then
      section = tostring(payload.section or payload.name or "")
    end
    if section == "" then
      return { ok = false, error = "missing section" }
    end
    local resetOk = false
    if ac and type(ac.isCarResetAllowed) == "function" then
      local okCall, allowed = pcall(ac.isCarResetAllowed)
      resetOk = okCall and (allowed == true)
    end
    if not resetOk then
      return { ok = false, section = section, error = "must be in pits" }
    end
    local ack = setupLibrary.setSpinner(payload)
    if type(ack) ~= "table" then
      ack = { ok = false, section = section, error = "library returned no ack" }
    elseif ack.ok == nil then
      ack.ok = false
      if ack.error == nil then ack.error = "library returned malformed ack" end
    end
    if ack.ok and wsBridge.publishTopic then
      pcall(function()
        local activeName = nil
        if type(ack.path) == "string" and ack.path ~= "" then
          local base = ack.path:match("([^/\\]+)$")
          if base then
            activeName = base:gsub("%.[iI][nN][iI]$", "")
            if activeName == "" then activeName = nil end
          end
        end
        wsBridge.publishTopic("setup.active", {
          name = activeName,
          path = ack.path,
          changed_at = (os and os.time and os.time()) or 0,
        })
      end)
    end
    return ack
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
  if key == "useImportedReference" then
    if type(value) ~= "boolean" then return false, "value must be boolean" end
    setUseImportedReferenceAndPersist(value)
    return true, nil
  end
  if key == "wsSidecarUrl" then
    if type(value) ~= "string" then
      return false, "value must be string"
    end
    local u = value
    if u ~= "" and not (u:match("^ws://") or u:match("^wss://")) then
      return false, "value must start with ws:// or wss://"
    end
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
    local strValue = tostring(value)
    if key == "racingLineMode" then
      if strValue ~= "best" and strValue ~= "last" and strValue ~= "both" then
        return false, "value must be one of: best,last,both"
      end
    elseif key == "lineStyle" then
      if strValue ~= "flat" and strValue ~= "tilt" then
        return false, "value must be one of: flat,tilt"
      end
    elseif key == "focusPracticeCornerLabels" then
      if #strValue > 128 then
        return false, "value too long"
      end
      if not strValue:match("^[%w%s,%-_]*$") then
        return false, "value contains unsupported characters"
      end
    end
    config[key] = strValue
  else
    return false, "unsupported config type"
  end
  persistLegacyPerKeyConfig(key, CONFIG_DEFAULTS[key], config[key])
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

local function cloneSegments(segs)
  if not segs or type(segs) ~= "table" then
    return {}
  end
  local out = {}
  for i = 1, #segs do
    local s = segs[i]
    if type(s) == "table" then
      local row = {}
      for k, v in pairs(s) do
        row[k] = v
      end
      out[#out + 1] = row
    end
  end
  return out
end

local function speedAtSpline(trace, spline)
  if type(trace) ~= "table" or #trace == 0 or type(spline) ~= "number" then
    return 0
  end
  local best = trace[1]
  local bestD = math.huge
  for i = 1, #trace do
    local sp = tonumber(trace[i].spline)
    if sp ~= nil then
      local d = math.abs(sp - spline)
      d = math.min(d, 1 - d)
      if d < bestD then
        bestD = d
        best = trace[i]
      end
    end
  end
  return tonumber(best and best.speed) or 0
end

local function brakePointsFromTrace(trace)
  local out = {}
  if type(trace) ~= "table" then
    return out
  end
  local braking = false
  for i = 1, #trace do
    local p = trace[i]
    local b = tonumber(p and p.brake) or 0
    if b > 0.12 and not braking then
      out[#out + 1] = {
        spline = tonumber(p.spline) or 0,
        px = tonumber(p.px) or 0,
        py = tonumber(p.py) or 0,
        pz = tonumber(p.pz) or 0,
        entrySpeed = tonumber(p.speed) or 0,
        heading = 0,
      }
      braking = true
    elseif b < 0.04 then
      braking = false
    end
  end
  return out
end

local function brakePointsFromSegments(trace, segments)
  local out = {}
  if type(segments) ~= "table" then
    return out
  end
  for i = 1, #segments do
    local seg = segments[i]
    if type(seg) == "table" and seg.kind == "corner" then
      local sp = tonumber(seg.brakeSpline) or tonumber(seg.s0)
      if sp ~= nil then
        out[#out + 1] = {
          spline = sp,
          px = 0,
          py = 0,
          pz = 0,
          entrySpeed = speedAtSpline(trace, sp),
          heading = 0,
        }
      end
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
  sessionReviewRequested = false,
  brakingPoints = {
    best = {},
    last = {},
    session = {},
  },
  recording = true,
  lastSplinePos = nil,
  -- car.resetCounter from the previous frame; a change = teleport/return-to-garage/pit reset (a
  -- wrap-shaped rewind the spline heuristic can't classify). Drives delta-skip + rolling reset (#185).
  lastResetCounter = nil,
  -- True while the lap clock is NOT aligned to a clean start/finish boundary, so `delta` (elapsed
  -- vs the reference lap's elapsed-at-spline, both measured from s/f) would be misaligned. The
  -- `delta` producer stays SILENT while set. Cleared ONLY when beginLapClock fires at a real lap
  -- boundary (lapCount increment at the s/f line); SET on init, reset/teleport, backward jump, and
  -- any mid-track clock seed (app load/reload mid-lap, post-reset re-arm) — Cursor + codex on #185.
  -- Defaults true: no delta until the first clean lap is started (an out-lap clock is mid-track).
  deltaRefStale = true,
  -- One-frame confirmation for wrap-shaped same-lap spline jumps on CSP builds without
  -- resetCounter: if lapCount does not catch up on the next frame, reset rolling state (#188).
  pendingWrapResetLapCount = nil,
  bestLapTrace = {},
  -- Local in-game PB/reference snapshot. When an imported reference is active,
  -- realtime code still reads `bestLapTrace`, but persistence saves these local fields.
  localBestLapTrace = {},
  localBestBrakePoints = {},
  localBestTrackSegments = {},
  localBestCornerFeatures = {},
  localBestReferenceLapMs = nil,
  --- Lap time (ms) for the lap that produced `bestLapTrace`; used to omit stale trace from saves when PB improves without a new reference trace.
  bestReferenceLapMs = nil,
  activeReferenceSource = nil,
  activeReferenceFormat = nil,
  activeReferenceLapMs = nil,
  activeReferencePath = nil,
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

local function cacheLocalReferenceState()
  state.localBestLapTrace = copyTrace(state.bestLapTrace or {})
  state.localBestBrakePoints = copyBpList(state.brakingPoints.best or {})
  state.localBestTrackSegments = cloneSegments(state.trackSegments or {})
  state.localBestCornerFeatures = cloneCornerFeats(state.bestCornerFeatures or {})
  state.localBestReferenceLapMs = state.bestReferenceLapMs
end

local function restoreLocalReferenceState()
  state.bestLapTrace = copyTrace(state.localBestLapTrace or {})
  state.brakingPoints.best = copyBpList(state.localBestBrakePoints or {})
  state.trackSegments = cloneSegments(state.localBestTrackSegments or {})
  state.bestCornerFeatures = cloneCornerFeats(state.localBestCornerFeatures or {})
  state.bestReferenceLapMs = state.localBestReferenceLapMs
  if state.bestLapTrace and #state.bestLapTrace >= 2 then
    state.racingBestLine = racingLine.traceToLine(state.bestLapTrace)
  else
    state.racingBestLine = {}
  end
  state.activeReferenceSource = (#(state.bestLapTrace or {}) >= 2) and "in_game" or nil
  state.activeReferenceFormat = nil
  state.activeReferenceLapMs = state.bestReferenceLapMs or state.bestLapMs
  state.activeReferencePath = nil
  rebuildBestReference()
  realtimeCoaching.rebuildSegmentIndex(state.trackSegments or {})
end

local function applyImportedReference(imported)
  if type(imported) ~= "table" or type(imported.trace) ~= "table" or #imported.trace < 2 then
    return false
  end
  local trace = copyTrace(imported.trace)
  local brakesForImport = brakePointsFromTrace(trace)
  local segments = cornerAnalysis.buildSegments(trace, brakesForImport)
  if #brakesForImport == 0 then
    brakesForImport = brakePointsFromSegments(trace, segments)
  end
  local feats = cornerAnalysis.cornerFeaturesForLap(trace, segments)
  state.bestLapTrace = trace
  state.bestReferenceLapMs = tonumber(imported.lapMs)
  state.brakingPoints.best = brakesForImport
  state.trackSegments = segments
  state.bestCornerFeatures = feats
  state.racingBestLine = racingLine.traceToLine(trace)
  state.activeReferenceSource = "imported"
  state.activeReferenceFormat = imported.importFormat or "motec_csv"
  state.activeReferenceLapMs = tonumber(imported.lapMs)
  state.activeReferencePath = imported.path
  rebuildBestReference()
  realtimeCoaching.rebuildSegmentIndex(segments)
  if ac and type(ac.log) == "function" then
    ac.log(string.format(
      "[COPILOT][REFERENCE] activated imported %s reference lap %.0f ms (%d trace, %d brakes, %d segs)",
      tostring(state.activeReferenceFormat),
      tonumber(imported.lapMs) or 0,
      #trace,
      #brakesForImport,
      #segments
    ))
  end
  return true
end

refreshActiveReference = function()
  if not state then
    return
  end
  restoreLocalReferenceState()
  local imported = persistence.chooseImportedReference(
    state.bestLapMs,
    persistence.bestImportedReference(car, sim),
    config.useImportedReference == true
  )
  if imported then
    applyImportedReference(imported)
  elseif ac and type(ac.log) == "function" then
    ac.log("[COPILOT][REFERENCE] active reference: " .. tostring(state.activeReferenceSource or "none"))
  end
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
  state.activeReferenceSource = (#(state.bestLapTrace or {}) >= 2) and "in_game" or nil
  state.activeReferenceFormat = nil
  state.activeReferenceLapMs = state.bestReferenceLapMs or state.bestLapMs
  state.activeReferencePath = nil
end

local function persistPayload()
  -- Always persist non-empty `bestLapTrace` together with `bestReferenceLapMs` so a new PB time
  -- does not erase a still-valid reference trace when the span guard rejected the new lap's trace.
  local useLocalSnapshot = state.activeReferenceSource == "imported"
  return {
    bestLapMs = state.bestLapMs,
    bestBrakePoints = useLocalSnapshot and state.localBestBrakePoints or state.brakingPoints.best,
    bestLapTrace = useLocalSnapshot and state.localBestLapTrace or state.bestLapTrace,
    bestReferenceLapMs = useLocalSnapshot and state.localBestReferenceLapMs or state.bestReferenceLapMs,
    trackSegments = useLocalSnapshot and state.localBestTrackSegments or state.trackSegments,
    lapFeatureHistory = state.lapFeatureHistory,
    setupHash = state.setupHash,
    setupSnapshot = state.lastSetupSnap,
    bestCornerFeatures = useLocalSnapshot and state.localBestCornerFeatures or state.bestCornerFeatures,
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
  state.sessionReviewRequested = false
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
  state.lastResetCounter = nil  -- re-prime teleport detection on next track entry
  state.deltaRefStale = true  -- re-entry: no boundary-aligned clock yet, delta silent until first lap
  state.pendingWrapResetLapCount = nil
  state.bestLapTrace = {}
  state.localBestLapTrace = {}
  state.localBestBrakePoints = {}
  state.localBestTrackSegments = {}
  state.localBestCornerFeatures = {}
  state.localBestReferenceLapMs = nil
  state.bestReferenceLapMs = nil
  state.activeReferenceSource = nil
  state.activeReferenceFormat = nil
  state.activeReferenceLapMs = nil
  state.activeReferencePath = nil
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
  state.sessionReviewRequested = false
  bestLapArchivePath = nil
  -- Drop any archive-backed lap_complete follow-ups left unsent: they reference the prior
  -- stint's archives and must not leak into the next session (drained best-effort above on
  -- the session-end path). CodeRabbit #321.
  pendingLapArchiveRecordPaths = {}
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
  lifecyclePublisher.reset()  -- #180: re-emit `session` after a reset (else stale key suppresses it)
  telemetryPublisher.reset()  -- #180: reset delta/tire_temps rate-limiters
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
  state.sessionReviewRequested = false
  bestLapArchivePath = nil
  -- Rolling reset starts a disjoint session (new SESSION_UUID below); drop prior-stint
  -- archive follow-ups so they cannot attach to the new session. CodeRabbit #321.
  pendingLapArchiveRecordPaths = {}
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
  lifecyclePublisher.reset()  -- #180: same-session/stint restart must re-emit `session`
  telemetryPublisher.reset()  -- #180: reset delta/tire_temps rate-limiters
  state.deltaRefStale = true  -- #180/#185: clock reset; delta silent until the next clean lap boundary
  state.pendingWrapResetLapCount = nil
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
  cacheLocalReferenceState()
  refreshActiveReference()
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

local function formatReferenceLapMs(ms)
  local n = tonumber(ms)
  if not n or n <= 0 then
    return "n/a"
  end
  local total = math.floor(n + 0.5)
  local minutes = math.floor(total / 60000)
  local seconds = math.floor((total % 60000) / 1000)
  local millis = total % 1000
  return string.format("%d:%02d.%03d", minutes, seconds, millis)
end

local function referenceStatusLine()
  if state.activeReferenceSource == "imported" then
    return "Active reference: imported "
      .. tostring(state.activeReferenceFormat or "motec_csv")
      .. " "
      .. formatReferenceLapMs(state.activeReferenceLapMs)
  end
  if state.activeReferenceSource == "in_game" then
    return "Active reference: your PB " .. formatReferenceLapMs(state.activeReferenceLapMs)
  end
  return "Active reference: none"
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
    referenceStatus = referenceStatusLine(),
    referenceLapsDir = persistence.lapArchiveDir(),
    setApproachMeters = setApproachMetersAndPersist,
    setLapArchiveEnabled = setLapArchiveEnabledAndPersist,
    setLapArchiveMaxMB = setLapArchiveMaxMBAndPersist,
    setUseImportedReference = setUseImportedReferenceAndPersist,
    openReferenceLapsFolder = persistence.openLapArchiveDir,
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

    -- Issue #86 Part C3: 10 Hz `coaching.snapshot` publish to the rig screen.
    -- No-op when the WS isn't open. coaching_publisher accumulates dt
    -- internally so this call is safe at any frame rate.
    pcall(function()
      coachingPublisher.publishIfDue({
        dt = dt,
        view = rtView,
        car = car,
        sim = sim,
        wsBridge = wsBridge,
      })
    end)

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
      -- Issue #305: we just left the track. update() returns a few lines below on every menu
      -- frame, so the per-frame archive pump further down never runs again — drain any job
      -- queued for the last lap NOW so its full trace is written instead of being abandoned as
      -- a partial `.tmp` stub. Gated by `wasDriving` so it runs once on the driving→menu
      -- transition (a job can only be queued while driving), not on every idle menu frame;
      -- runs before resetRuntimeAfterLeavingTrack rebuilds runtime state.
      flushPendingLapArchiveJobs("session end (main menu)")
      -- Drain the notifications flush just enqueued: update() returns a few lines below
      -- before the per-frame pump runs again, and resetRuntimeAfterLeavingTrack (which
      -- also calls wsBridge.reset) is imminent — so the last lap's archive-backed brain
      -- follow-up gets its one send attempt here instead of being stranded. CodeRabbit #321.
      pumpLapArchiveNotifications()
      local sessionReviewLaps = tonumber(state.lapsCompleted) or 0
      if sessionReviewLaps >= 1 and not state.sessionReviewRequested and wsBridge
          and type(wsBridge.sendSessionReviewGenerate) == "function" then
        state.sessionReviewRequested = true
        local reviewOk, reviewSentOrErr = pcall(
          wsBridge.sendSessionReviewGenerate,
          persistence.lapArchiveDir(),
          SESSION_UUID
        )
        if ac and type(ac.log) == "function" then
          if not reviewOk then
            ac.log("[COPILOT][SESSION-REVIEW] generate request raised: "
              .. tostring(reviewSentOrErr))
          elseif reviewSentOrErr ~= true then
            ac.log("[COPILOT][SESSION-REVIEW] generate request not sent; sidecar not ready")
          end
        end
      end
      if persistSnapshotCached() then
        -- Issue #47: training journal JSON under ScriptConfig (after persist, before state reset).
        local journalLaps = sessionReviewLaps
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

  -- car.resetCounter is NOT a confirmed-safe StateCar field (csp-api-field-safety decision /
  -- issue #24: unknown StateCar fields THROW, and this read runs outside the pcall blocks below
  -- as well). Read it ONCE through the guarded helper and reuse `teleported` for both the
  -- delta-skip and the end-of-update rolling reset. nil on builds lacking the field => teleport
  -- detection is gracefully off (the spline heuristic + lap-count rollback still apply). (#185)
  local resetCounterNow = ch.safeCarField(car, "resetCounter")
  local teleported = state.lastResetCounter ~= nil
    and resetCounterNow ~= nil
    and resetCounterNow ~= state.lastResetCounter

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
  pumpLapArchiveJobs()
  pumpLapArchiveNotifications()

  -- Issue #180 Part D step 2: lifecycle topics, published AFTER wsBridge.tick()/pollInbound()
  -- so they observe the CURRENT-frame WS state and always precede the `lap` boundary below
  -- (Cursor HIGH on #182: publishing before the tick let a mid-frame-ready WS send `lap`
  -- without a preceding `session`). `session` fires only on track/car/session change;
  -- `connection` is a ~1 Hz heartbeat; both no-op when the WS isn't open. (`car` is non-nil
  -- here — guaranteed by the `if not car then return end` guard above.)
  pcall(function()
    -- Per-frame WS-reconnect detection: on a sidecar (re)connect, re-arm `session` so it
    -- re-emits THIS frame — before any subsequent `lap` — without resetting the stint best.
    -- The boolean catches normal false->true connects; openEpoch catches a CSP auto-reconnect
    -- that opens and drains hello_ack between two script.update samples, leaving the boolean
    -- true on both samples (#183).
    local wsConn = type(wsBridge.sidecarConnected) == "function" and wsBridge.sidecarConnected()
    local wsEpoch = type(wsBridge.openEpoch) == "function" and wsBridge.openEpoch() or nil
    local wsEpochChanged = wsEpoch ~= nil
      and state._wsPrevOpenEpoch ~= nil
      and wsEpoch ~= state._wsPrevOpenEpoch
    if wsConn and (not state._wsPrevConnected or wsEpochChanged) then
      lifecyclePublisher.rearmSession()
    end
    state._wsPrevConnected = wsConn
    if wsEpoch ~= nil then
      state._wsPrevOpenEpoch = wsEpoch
    end
    if type(wsBridge.consumeSessionReplayRequest) == "function" then
      local okReplay, replayRequested = pcall(wsBridge.consumeSessionReplayRequest)
      if okReplay and replayRequested == true then
        lifecyclePublisher.rearmSession()
      end
    end
    lifecyclePublisher.publishConnectionIfDue({
      dt = dt,
      car = car,
      sim = sim,
      wsBridge = wsBridge,
      appVersion = APP_VERSION_UI,
    })
    lifecyclePublisher.publishSessionIfChanged({ car = car, sim = sim, wsBridge = wsBridge })
  end)

  -- Issue #180 Part D step 2: telemetry topics (continuous streams, no ordering contract).
  -- `delta` is published only once a reference lap exists (state.bestSortedTrace) using the
  -- same delta.deltaSecondsAtSpline computation the HUD uses; `tire_temps` streams current
  -- per-wheel core temps. Both rate-limited internally and no-op when the WS isn't open.
  pcall(function()
    -- Skip `delta` on ANY lap-count change frame (forward boundary OR a session/pit-restart
    -- rollback). On such a frame `tel:lapStartTime()` and the reference trace still belong to
    -- the prior lap/stint while car state has moved on (spline wrapped, or car reset), so
    -- deltaSecondsAtSpline would emit a bogus cross-lap/cross-stint delta (Cursor + codex on
    -- #185). `state.lastLapCount` here still holds the pre-handler value; `~=` covers both the
    -- forward crossing (reset by beginLapClock below) and the rollback (reset later this frame).
    -- Also skip a SAME-LAP pit/session reset: the spline jumps backward without a lap-count
    -- change, and the end-of-update reset guard detects it AFTER this block runs. Mirror that
    -- discontinuity test via the shared delta.isBackwardSplineReset so producer and reset guard
    -- cannot drift; otherwise one bogus delta leaks out against the rewound spline (codex on #185).
    local lcNow = car.lapCount or 0
    local spNow = car.splinePosition or 0
    local atLapCountChange = (state.lastLapCount or -1) >= 0 and lcNow ~= state.lastLapCount
    -- For the delta SKIP we use the LIBERAL isBackwardSplineJump (includes wrap-shaped jumps):
    -- skipping a delta frame is harmless, and since this only runs with lapCount unchanged
    -- (`not atLapCountChange`), any backward jump here is a reset/teleport, not a lap wrap. This
    -- also covers builds where resetCounter is unavailable, so a wrap-shaped same-lap teleport
    -- never leaks a bogus delta even when `teleported` can't be determined (codex on #185).
    local splineJump = delta.isBackwardSplineJump(state.lastSplinePos, spNow)
    if splineJump or teleported then
      -- Mark the reference clock stale until a clean lap boundary re-arms it (cleared at
      -- beginLapClock). Without this, delta resumes the very next frame against the abandoned
      -- stint's lap clock — the leak codex flagged on resetCounter-less builds (#185 / #188).
      state.deltaRefStale = true
    end
    if
      state.bestSortedTrace
      and tel:lapStartTime()
      and not atLapCountChange
      and not splineJump
      and not teleported
      and not state.deltaRefStale
    then
      local eMs = (ch.simSeconds(sim) - tel:lapStartTime()) * 1000
      local rawDelta = delta.deltaSecondsAtSpline(state.bestSortedTrace, spNow, eMs)
      telemetryPublisher.publishDeltaIfDue({
        dt = dt,
        deltaS = rawDelta,
        spline = spNow,
        wsBridge = wsBridge,
      })
    end
    local currentTireTemps = tires:currentTemps(car)
    telemetryPublisher.publishTireTempsIfDue({
      dt = dt,
      temps = currentTireTemps,
      wsBridge = wsBridge,
    })
    telemetryPublisher.publishTelemetryTickIfDue({
      dt = dt,
      car = car,
      wsBridge = wsBridge,
      lat_g = 0,
      long_g = 0,
      temps = currentTireTemps,
    })
  end)
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

  -- Lap boundary: finalize trace before appending this frame's sample. Skip on a teleport frame
  -- (`teleported`, the guarded resetCounter signal computed above): a return-to-garage/pit reset
  -- can coincide with a lapCount increase, and finalizing/publishing/archiving here would record a
  -- bogus lap from the abandoned stint before the end-of-update rolling reset runs (codex on #185).
  if state.lastLapCount >= 0 and lc > state.lastLapCount and not teleported then
    -- Last frame of the completed lap may still carry invalidation (CSP `ac.StateCar`).
    if carLapInvalidatedFlag(car) then
      state.lapInvalidatedThisLap = true
    end
    local completedTrace = tel:finalizeLapTrace()
    tel:beginLapClock(ch.simSeconds(sim))
    resetDeltaSmoother()
    state.deltaRefStale = false  -- clean lap clock re-armed at the s/f line: delta valid again (#185)
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
    -- Issue #180 Part D step 2: publish the `lap` topic once at the boundary. No-op when
    -- the WS isn't open. Review-fixes: `lap`/`laps_completed` both use the app's completed
    -- counter (not car.lapCount) so they agree; `best_lap_ms` folds in THIS lap so a new PB
    -- / the first lap isn't reported stale; an untimed boundary (out-lap,
    -- previousLapTimeMs == 0) sends `last_lap_ms = nil` rather than a misleading 0.
    pcall(function()
      lifecyclePublisher.publishLap({
        lap = state.lapsCompleted,
        lastLapMs = lastMs,  -- raw; the producer treats <=0 as untimed and tracks the stint best
        lapsCompleted = state.lapsCompleted,
        valid = not state.lapInvalidatedThisLap,
        wsBridge = wsBridge,
      })
    end)
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
    local referenceArchivePathForBrain = bestLapArchivePath

    local prevBestBp = copyBpList(state.brakingPoints.best)
    local localBestChanged = false
    if lastMs > 0 and (state.bestLapMs == nil or lastMs <= state.bestLapMs) then
      if state.activeReferenceSource == "imported" then
        restoreLocalReferenceState()
      end
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
      localBestChanged = true
    end
    if localBestChanged then
      cacheLocalReferenceState()
      refreshActiveReference()
    end
    state.brakingPoints.last = copyBpList(state.brakingPoints.session)
    state.brakingPoints.session = {}
    td:resetLapAggregates()

    local coastMs = thA and thA.coastingMs or 0
    state.postLapLines = buildPostLapLines(prevBestBp, state.brakingPoints.last, coastMs, sim)
    state.postLapUntil = ch.simSeconds(sim) + config.postLapHoldSeconds

    -- Hoisted out of the `if lastMs > 0` block below: the deferred archive follow-up
    -- (`shallowCopy(lapPayload)` further down) must see the populated table. In Lua 5.1 a
    -- `local` declared inside that `if ... end` is out of scope by the archive block, so a
    -- nested declaration would copy nil and strip the base `lap_complete` fields
    -- (event/lap/lapTimeMs) — silently disabling the brain follow-up. CodeRabbit #321.
    local lapPayload
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
      lapPayload = {
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

    -- Issue #77 Part C / #246: archive this lap (trace + setup + corners + coaching).
    -- Runs independently of sidecar / coaching success, but queue the file work
    -- instead of compact-encoding/flushing the full trace on the S/F render frame.
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
        setup_ini_path = setupReader.activeSetupIniPath(car, sim),
        setup_hash = state.setupHash,
        rules_hints = state.coachingLines,
        -- Omit async sidecar debrief: it is applied on later frames than lap_complete, so stamping it
        -- here would mis-label the archived lap (Codex #78).
        sidecar_debrief = nil,
        -- `lapsCompleted` was incremented above; corner_query / corner_advice use the in-lap index
        -- (Codex + Cursor Bugbot #78 post-5f0ce39).
        corner_advice = wsBridge.cornerAdvisorySnapshotForLap((state.lapsCompleted or 0) - 1),
      }
      local archiveLapPayload = shallowCopy(lapPayload)
      archiveLapPayload.brainOnly = true
      queueLapArchiveJob(archiveOpts, {
        archiveLapPayload = archiveLapPayload,
        referenceArchivePath = referenceArchivePathForBrain,
        isBestLapArchive = isPbThisLap,
      })
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
    -- This is a MID-TRACK seed (app load/reload or post-reset re-arm), NOT a start/finish boundary,
    -- so the clock is not aligned to s/f: keep delta silent until the next real lap boundary clears
    -- this. Publishing now would give subscribers elapsed-from-reload vs reference-from-s/f (codex on #185).
    state.deltaRefStale = true
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

  local resetDecision = delta.rollingResetDecision({
    pendingWrapLapCount = state.pendingWrapResetLapCount,
    lastLapCount = state.lastLapCount,
    lapCount = lc,
    prevSpline = state.lastSplinePos,
    spline = sp,
    teleported = teleported,
  })
  state.pendingWrapResetLapCount = resetDecision.pendingWrapLapCount
  if resetDecision.reset then
    -- Teleport/resetCounter, lap rollback, non-wrap same-lap spline rewind, or a deferred
    -- wrap-shaped same-lap jump whose lapCount did not catch up on the following frame (#188).
    resetRollingDrivingState()
  end

  state.lastLapCount = lc
  state.lastSplinePos = sp
  state.lastSplineSector = sp
  state.lastResetCounter = resetCounterNow
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
