-- JSON load/save for brake points (per car + track) under CSP ScriptConfig.

local M = {}

local ch = require("csp_helpers")

local APP_SUBDIR = "ac_copilot_trainer"
local DATA_VERSION = 3

--- Best-effort track/car labels from structs when globals are missing (e.g. menu save); one pcall per field (C-structs throw per-field).
local function tryTrackFromSim(sim)
  if not sim then
    return nil
  end
  for _, key in ipairs({ "trackName", "track", "trackConfiguration" }) do
    local ok, v = pcall(function()
      return sim[key]
    end)
    if ok and v ~= nil and tostring(v) ~= "" then
      return tostring(v)
    end
  end
  return nil
end

local function tryCarFromCar(car)
  if not car then
    return nil
  end
  for _, key in ipairs({ "id", "name", "driverName" }) do
    local ok, v = pcall(function()
      return car[key]
    end)
    local wasCallable = ok and type(v) == "function"
    if wasCallable then
      local called, resolved = pcall(v)
      if not called then
        called, resolved = pcall(v, car)
      end
      if called then
        v = resolved
      else
        v = nil
      end
    end
    if ok and type(v) == "string" and v ~= "" then
      return v
    end
    -- Direct CSP scalar/userdata fields historically stringify to useful content identifiers.
    -- Keep that compatibility, but never stringify a callable result: accessors must resolve to a
    -- real string so function/table address text cannot masquerade as stable archive identity.
    if ok and not wasCallable and (type(v) == "number" or type(v) == "userdata") then
      local rendered = tostring(v)
      if rendered ~= "" then
        return rendered
      end
    end
  end
  return nil
end

--- Lap archive / filenames: prefer the stable content id from ``ac.getCarID(0)``. Some CSP
--- ``StateCar`` builds expose ``car.id`` as a callable accessor; stringifying that value produces
--- an address-shaped ``function_0x...`` id, which cannot match the harness combo and makes a real
--- thermal lap unusable for plant identification. Only fall back to StateCar labels when the
--- global content-id API is unavailable.
---@param car ac.StateCar|nil
---@return string|nil
function M.archiveCarIdFromCar(car)
  local globalId = ch.safeCarIdRaw()
  if type(globalId) == "string" and globalId ~= "" then
    return ch.sanitizeId(globalId, "unknown")
  end
  local raw = tryCarFromCar(car)
  if not raw then
    return nil
  end
  return ch.sanitizeId(raw, "unknown")
end

---@param sim ac.StateSim|nil
---@return string|nil
function M.archiveTrackIdFromSim(sim)
  local raw = tryTrackFromSim(sim)
  if not raw then
    return nil
  end
  return ch.sanitizeId(raw, "unknown")
end

--- Session filename key: car id + track id. Prefer `ac.get*` globals; fall back to `car`/`sim` when globals yield unknown (menu / edge cases).
function M.sessionKey(car, sim)
  local track = ch.trackIdRawFromGlobals() or "unknown_track"
  local carKey = ch.carIdRawFromGlobals() or "unknown_car"
  if track == "unknown_track" then
    local t2 = tryTrackFromSim(sim)
    if t2 then
      track = t2
    end
  end
  if carKey == "unknown_car" then
    local c2 = tryCarFromCar(car)
    if c2 then
      carKey = c2
    end
  end
  return ch.sanitizeId(carKey, "unknown") .. "__" .. ch.sanitizeId(track, "unknown")
end

function M.dataDir()
  local base = ac.getFolder(ac.FolderID.ScriptConfig)
  return base .. "/" .. APP_SUBDIR
end

function M.lapArchiveDir()
  return M.dataDir() .. "/journal/laps"
end

function M.dataPath(car, sim)
  return M.dataDir() .. "/" .. M.sessionKey(car, sim) .. ".json"
end

local function jsonEncode(t)
  if JSON and JSON.stringify ~= nil then
    local ok, out = pcall(JSON.stringify, t, true)
    if ok and type(out) == "string" then
      return out
    end
  end
  return nil
end

--- One-line JSON for JSONL append (no pretty-print newlines).
local function jsonEncodeCompact(t)
  if JSON and JSON.stringify ~= nil then
    local ok, out = pcall(JSON.stringify, t, false)
    if ok and type(out) == "string" then
      return out
    end
    ok, out = pcall(JSON.stringify, t)
    if ok and type(out) == "string" then
      return out
    end
  end
  return nil
end

local function jsonDecode(s)
  if not s or s == "" then
    return nil
  end
  if JSON and JSON.parse ~= nil then
    local ok, out = pcall(JSON.parse, s)
    if ok and type(out) == "table" then
      return out
    end
  end
  return nil
end

--- Rebuild a 1..n dense array from possibly sparse / string-keyed decoded JSON.
local function denseArray(t)
  if type(t) ~= "table" then
    return nil
  end
  local keys = {}
  for k in pairs(t) do
    if type(k) == "number" and k == math.floor(k) and k >= 1 then
      keys[#keys + 1] = k
    end
  end
  if #keys == 0 then
    return {}
  end
  table.sort(keys)
  local out = {}
  for i = 1, #keys do
    out[i] = t[keys[i]]
  end
  return out
end

--- Normalize decoded JSON: reject future `version`, coerce bad `bestLapTrace` (v1 omits version and trace).
---@param data table|nil
---@return table|nil
local function normalizeLoaded(data)
  if not data or type(data) ~= "table" then
    return nil
  end
  local v = tonumber(data.version)
  if v ~= nil and v > DATA_VERSION then
    return nil
  end
  if data.bestLapTrace ~= nil and type(data.bestLapTrace) ~= "table" then
    data.bestLapTrace = nil
  end
  if data.trackSegments ~= nil then
    if type(data.trackSegments) ~= "table" then
      data.trackSegments = nil
    else
      data.trackSegments = denseArray(data.trackSegments)
    end
  end
  if data.lapFeatureHistory ~= nil then
    if type(data.lapFeatureHistory) ~= "table" then
      data.lapFeatureHistory = nil
    else
      local hist = denseArray(data.lapFeatureHistory)
      if hist then
        for i = 1, #hist do
          local lap = hist[i]
          if type(lap) == "table" then
            if type(lap.corners) == "table" then
              lap.corners = denseArray(lap.corners) or {}
            else
              lap.corners = {}
            end
          end
        end
      end
      data.lapFeatureHistory = hist
    end
  end
  if data.setupSnapshot ~= nil and type(data.setupSnapshot) ~= "table" then
    data.setupSnapshot = nil
  end
  if data.setupHash ~= nil and type(data.setupHash) ~= "string" then
    data.setupHash = nil
  end
  -- v3: array of corner feature tables; reject wrong type, densify sparse JSON arrays.
  if data.bestCornerFeatures ~= nil then
    if type(data.bestCornerFeatures) ~= "table" then
      data.bestCornerFeatures = nil
    else
      data.bestCornerFeatures = denseArray(data.bestCornerFeatures)
    end
  end
  return data
end

--- Reject paths that could break out of a quoted shell argument.
local function pathSafeForShell(p)
  if not p or p == "" then
    return false
  end
  if p:find("[\1-\31\"]") then
    return false
  end
  if p:find("[&|<>%%^!`']") then
    return false
  end
  return true
end

local function ensureDir(path)
  local dir = path:match("^(.*)/[^/]+$")
  if not dir or dir == "" then
    return
  end
  if not pathSafeForShell(dir) then
    return
  end
  local sep = package.config:sub(1, 1)
  local cmd
  if sep == "\\" then
    cmd = 'mkdir "' .. dir:gsub("/", "\\") .. '" 2>nul'
  else
    cmd = 'mkdir -p "' .. dir .. '"'
  end
  pcall(os.execute, cmd)
end

--- Create parent directories for a file path (same safety rules as save()).
function M.ensureParentDirForFile(path)
  ensureDir(path)
end

--- Open the shared lap archive folder in Windows Explorer when CSP exposes a process launcher.
---@return boolean ok, string message
function M.openLapArchiveDir()
  local dir = M.lapArchiveDir()
  M.ensureParentDirForFile(dir .. "/_dummy")
  if type(os) == "table" and type(os.runConsoleProcess) == "function" then
    local ok, accepted, err = pcall(function()
      return os.runConsoleProcess({
        filename = "explorer.exe",
        arguments = { dir },
        workingDirectory = dir,
        timeout = 0,
        terminateWithScript = false,
        inheritEnvironment = true,
      }, function() end)
    end)
    if ok and accepted ~= false and accepted ~= nil then
      return true, dir
    end
    return false, tostring(err or accepted or "runConsoleProcess returned nil")
  end
  if package and package.config and package.config:sub(1, 1) == "\\" and pathSafeForShell(dir) then
    local winDir = dir:gsub("/", "\\")
    local ok = pcall(os.execute, 'start "" "' .. winDir .. '"')
    if ok then
      return true, dir
    end
  end
  return false, "folder opener unavailable"
end

--- Serialize a table to JSON when CSP `JSON.stringify` is available.
---@param t table
---@return string|nil
function M.encodeJson(t)
  return jsonEncode(t)
end

--- Compact JSON (single line) for JSONL streams; see `session_journal` index append.
---@param t table
---@return string|nil
function M.encodeJsonCompact(t)
  return jsonEncodeCompact(t)
end

--- Parse JSON to table when CSP `JSON.parse` is available.
---@param s string|nil
---@return table|nil
function M.decodeJson(s)
  return jsonDecode(s)
end

local function archiveRecordCarTrackMatches(rec, car, sim)
  if type(rec) ~= "table" then
    return false
  end
  local recCar = rec.car and rec.car.id
  local recTrack = rec.track and rec.track.id
  if type(recCar) ~= "string" or recCar == "" or type(recTrack) ~= "string" or recTrack == "" then
    return false
  end
  local carId = M.archiveCarIdFromCar(car) or ch.sanitizeId(ch.safeCarIdRaw(), "unknown")
  local trackId = M.archiveTrackIdFromSim(sim) or ch.sanitizeId(ch.safeTrackIdRaw(), "unknown")
  if recCar ~= carId or recTrack ~= trackId then
    return false
  end
  local recLayout = rec.track and rec.track.layout
  if type(recLayout) == "string" and recLayout ~= "" then
    local curLayout = ch.safeTrackLayoutRaw()
    if type(curLayout) == "string" and curLayout ~= "" and recLayout ~= ch.sanitizeId(curLayout, "") then
      return false
    end
  end
  return true
end

local function archiveTraceToObjects(rec)
  if type(rec) ~= "table" or type(rec.trace) ~= "table" then
    return {}
  end
  local fields = rec.trace.fields
  local samples = rec.trace.samples
  if type(fields) ~= "table" or type(samples) ~= "table" then
    return {}
  end
  local idx = {}
  for i = 1, #fields do
    if type(fields[i]) == "string" then
      idx[fields[i]] = i
    end
  end
  if not idx.spline or not idx.speed or not idx.eMs then
    return {}
  end
  local out = {}
  for i = 1, #samples do
    local row = samples[i]
    if type(row) == "table" then
      local spline = tonumber(row[idx.spline])
      local speed = tonumber(row[idx.speed])
      local eMs = tonumber(row[idx.eMs])
      if spline ~= nil and speed ~= nil and eMs ~= nil then
        out[#out + 1] = {
          spline = spline,
          speed = speed,
          eMs = eMs,
          throttle = tonumber(row[idx.throttle]) or 0,
          brake = tonumber(row[idx.brake]) or 0,
          steer = tonumber(row[idx.steer]) or 0,
          gear = tonumber(row[idx.gear]) or 0,
          rpm = (idx.rpm and tonumber(row[idx.rpm])) or 0,
          px = tonumber(row[idx.px]) or 0,
          py = tonumber(row[idx.py]) or 0,
          pz = tonumber(row[idx.pz]) or 0,
        }
      end
    end
  end
  table.sort(out, function(a, b)
    return (a.spline or 0) < (b.spline or 0)
  end)
  return out
end

M.archiveTraceToObjects = archiveTraceToObjects

local function readLapRecord(path)
  local f = io.open(path, "r")
  if not f then
    return nil
  end
  local raw = f:read("*a")
  f:close()
  return jsonDecode(raw)
end

--- Compact form our JSON encoder emits for the discriminating key, e.g. `"source":"in_game"`.
local SOURCE_KEY = '"source":"'
local SOURCE_IMPORTED = '"source":"imported"'

--- Cheap EXCLUSION test: can this archive possibly be an imported reference?
---
--- #627: `bestImportedReference` used to fully JSON-decode every `lap_*.json` just to read one
--- string. Measured on the rig: 403 archives / 480 MB, of which ZERO were imported -- half a
--- gigabyte decoded to find nothing, on every reference refresh, growing with every lap driven.
--- Those decodes run through CSP's slow decimal->float loop (`accRenderingAdv`), which is what
--- turned this into a multi-second main-thread stall.
---
--- This reads the same bytes but does NOT decode them: two `plain` substring scans (a C memchr in
--- the Lua runtime) instead of allocating thousands of numbers. Measured over the rig's real
--- journal: 405 ms vs 9024 ms even against Python's C-speed JSON, excluding 403 of 403.
---
--- A tail-only window was tried first and REJECTED by measurement: our encoder emits keys in hash
--- order, so `"source"` sat a median of 247 KB from EOF and 58 of 80 sampled archives had it
--- outside an 8 KiB tail. Scanning the whole buffer is key-order independent.
---
--- **Fails OPEN by design.** A `false` return must be PROOF, never a guess: an unopenable file, or
--- one that does not contain the compact key form at all (a future format change), returns `true`
--- and the caller decodes it. Being slow is recoverable; silently dropping a lap the user
--- imported is not.
---@param path string
---@return boolean mayBeImported
local function archiveMayBeImported(path)
  local f = io.open(path, "rb")
  if not f then
    return true
  end
  local ok, raw = pcall(function()
    return f:read("*a")
  end)
  f:close()
  if not ok or type(raw) ~= "string" then
    return true
  end
  -- Fast path: the compact form our encoder actually emits. Two `plain` scans, no pattern engine.
  if raw:find(SOURCE_IMPORTED, 1, true) then
    return true
  end
  if raw:find(SOURCE_KEY, 1, true) then
    return false -- key present and it is not "imported": proven
  end
  -- Tolerant path: a differently-spaced encoder (`"source": "in_game"`). Never taken for archives
  -- this app wrote, so the pattern engine stays off the hot path, but it keeps the filter correct
  -- for hand-edited or externally-produced files instead of forcing a full decode.
  --
  -- Scan EVERY match, not just the first. The fast path above is a whole-buffer OR; taking only
  -- the first spaced match here would break that symmetry and violate this function's contract:
  -- a pretty-printed archive with a nested `source` key ahead of a top-level `"source":
  -- "imported"` would be reported as PROVEN not-imported and silently skipped.
  local found = false
  local pos = 1
  while true do
    local s, e, value = raw:find('"source"%s*:%s*"([^"]*)"', pos)
    if not s then
      break
    end
    if value == "imported" then
      return true
    end
    found = true
    pos = e + 1
  end
  if found then
    return false -- key present in every occurrence and none said "imported": proven
  end
  return true -- key absent in any recognised form: unknown shape, decode it
end

M._archiveMayBeImported = archiveMayBeImported

--- Find the fastest valid imported MoTeC reference lap for the current car/track.
---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@return table|nil reference
function M.bestImportedReference(car, sim)
  local dir = M.lapArchiveDir()
  local best = nil
  pcall(function()
    if not (io and type(io.scanDir) == "function") then
      return
    end
    local files = io.scanDir(dir, "lap_*.json")
    if type(files) ~= "table" then
      return
    end
    for i = 1, #files do
      local name = files[i]
      if type(name) == "string" then
        local path = dir .. "/" .. name
        -- Skip the 250 KB decode when a plain scan PROVES this is not imported (#627).
        local rec = archiveMayBeImported(path) and readLapRecord(path) or nil
        local lap = rec and rec.lap
        local lapMs = lap and tonumber(lap.lap_ms)
        if rec
            and rec.schema_version == 1
            and rec.source == "imported"
            and rec.import_format == "motec_csv"
            and type(lap) == "table"
            and lap.is_valid ~= false
            and lapMs ~= nil
            and lapMs > 0
            and archiveRecordCarTrackMatches(rec, car, sim) then
          local trace = archiveTraceToObjects(rec)
          if #trace >= 2 and (best == nil or lapMs < best.lapMs) then
            best = {
              source = "imported",
              importFormat = rec.import_format,
              lapMs = lapMs,
              trace = trace,
              path = path,
              record = rec,
            }
          end
        end
      end
    end
  end)
  return best
end

--- Apply the user-facing import preference without mutating the user's local PB.
---@param localBestMs number|nil
---@param importedRef table|nil
---@param enabled boolean
---@return table|nil
function M.chooseImportedReference(localBestMs, importedRef, enabled)
  if enabled ~= true or type(importedRef) ~= "table" then
    return nil
  end
  local importedMs = tonumber(importedRef.lapMs)
  if importedMs == nil or importedMs <= 0 then
    return nil
  end
  local localMs = tonumber(localBestMs)
  if localMs ~= nil and localMs > 0 and importedMs >= localMs then
    return nil
  end
  return importedRef
end

---@return table|nil
function M.load(car, sim)
  local path = M.dataPath(car, sim)
  local f = io.open(path, "r")
  if not f then
    return nil
  end
  local raw = f:read("*a")
  f:close()
  -- All loads go through normalizeLoaded so DATA_VERSION and schema stay centralized.
  return normalizeLoaded(jsonDecode(raw))
end

function M.save(car, sim, data)
  data.version = DATA_VERSION
  local path = M.dataPath(car, sim)
  ensureDir(path)
  local raw = jsonEncode(data)
  if not raw then
    return false
  end
  local f = io.open(path, "w")
  if not f then
    return false
  end
  if not f:write(raw) then
    f:close()
    return false
  end
  f:close()
  return true
end

return M
