-- Per-lap archive (issue #77 Part C).
--
-- Append-only JSON-per-lap archive under `journal/laps/`. Designed for forward
-- compatibility with future MoTeC CSV / .ibt imports (Initiative B): both
-- in-game laps and imported reference laps share the same schema, distinguished
-- only by the `source` and `import_format` top-level fields.
--
-- Disk-bounded rotation (cap MB, not lap count). Default 500 MB.
--
-- Schema v1:
--   {
--     schema_version = 1,
--     source = "in_game" | "imported",
--     import_format = nil | "motec_csv" | "ibt" | "delta" | "generated_reference_v1",
--     lap_uuid, session_uuid, exported_at,
--     car = { id, displayName? },
--     track = { id, layout?, lengthM? },
--     conditions = { trackGripLevel?, ambientTempC?, trackTempC?, weatherType? },
--     lap = { lap_n, lap_ms, is_pb, is_valid },
--     setup = { hash, path?, snapshot = { <flat INI key=value map> } },
--     trace = {
--       samples_count = N,
--       fields = { "spline","speed","eMs","throttle","brake","steer","gear","px","py","pz" },
--       samples = { { ...10 numbers... }, ... }   -- columnar; ~50% smaller than per-sample objects
--     },
--     corners = [ { label, entrySpeed, minSpeed, exitSpeed, brakePointSpline, trailBrakeRatio, throttleAvg, steerReversals, tractionCircleProxy } ],
--     coaching = {
--       rules_hints = { "...", ... },
--       sidecar_debrief = "..." | nil,
--       corner_advice_used = { ["T1"] = "BRAKE HARD NOW.", ... } | nil
--     }
--   }

local M = {}

local persistence = require("persistence")
local ch = require("csp_helpers")

local SCHEMA_VERSION = 1

--- Same bounds as Settings slider (issue #77 / PR #78).
local ARCHIVE_CAP_MIN_MB = 50
local ARCHIVE_CAP_MAX_MB = 5000

---@param raw number|string|nil
---@return number
function M.clampArchiveCapMB(raw)
  local n = tonumber(raw) or 500
  if n ~= n or n <= 0 then
    n = 500
  end
  n = math.max(ARCHIVE_CAP_MIN_MB, math.min(ARCHIVE_CAP_MAX_MB, n))
  return math.floor(n + 0.5)
end

-- Trace sample field order. `traceToColumns` builds rows by iterating this list (single source of
-- truth). MUST stay byte-identical to tools/ac_harness/reference_lap.py::TRACE_FIELDS (the Python
-- generator + analysis loader read by name, and test_reference_lap asserts the two agree).
-- Per-wheel channels (issue #266) are appended last; older archives lacking them export as blanks.
local TRACE_FIELDS = {
  "spline", "speed", "eMs", "throttle", "brake", "steer", "gear", "px", "py", "pz",
  "wheelAngularSpeed_fl", "wheelAngularSpeed_fr", "wheelAngularSpeed_rl", "wheelAngularSpeed_rr",
  "wheelSlip_fl", "wheelSlip_fr", "wheelSlip_rl", "wheelSlip_rr",
  "tyreCoreTemp_fl", "tyreCoreTemp_fr", "tyreCoreTemp_rl", "tyreCoreTemp_rr",
}

local function lapArchiveDir()
  return persistence.lapArchiveDir()
end

local function isTraceSampleArchivable(s)
  return type(s) == "table" and type(s.spline) == "number"
end

local function traceSampleToColumnRow(s)
  if not isTraceSampleArchivable(s) then
    return nil
  end
  ---@cast s table
  local row = {}
  for fi = 1, #TRACE_FIELDS do
    local fname = TRACE_FIELDS[fi]
    if fname == "spline" then
      row[fi] = s.spline
    else
      row[fi] = tonumber(s[fname]) or 0
    end
  end
  return row
end

local function countTraceRows(trace)
  if type(trace) ~= "table" then return 0 end
  local n = 0
  for i = 1, #trace do
    if isTraceSampleArchivable(trace[i]) then
      n = n + 1
    end
  end
  return n
end

--- Settings UI calls `stats()` every frame; cache full-directory scan for a short TTL (Gemini #78).
--- Uses `os.time` (wall-ish seconds), not `os.clock` (CPU time can stall the TTL — Cursor #78).
local _statsCacheT = -1e9
local _statsCacheCount = 0
local _statsCacheMb = 0
local STATS_CACHE_TTL_SEC = 2.0

local function bustStatsCache()
  _statsCacheT = -1e9
end

--- Generate a short stable-ish UUID-like ID. Not RFC4122 — Lua 5.1 has no
--- crypto, so we use os.time + math.random + a counter. Good enough for
--- debug-friendly filenames; not for cryptographic uniqueness.
local _uuidCounter = 0
local function shortUuid()
  _uuidCounter = _uuidCounter + 1
  local t = (os and os.time and os.time()) or 0
  -- 16-bit bounds only (same constraint as SESSION_UUID in ac_copilot_trainer.lua — Cursor #78).
  local r1 = math.random(0, 0xFFFF)
  local r2 = math.random(0, 0xFFFF)
  return string.format("%x%04x%04x%x", t % 0xFFFFFFFF, r1, r2, _uuidCounter % 0xFFFF)
end

local function isoUtcNow()
  if os and os.date then
    local ok, s = pcall(os.date, "!%Y-%m-%dT%H:%M:%SZ")
    if ok and type(s) == "string" then return s end
  end
  return ""
end

local function fileTimestampUtc()
  if os and os.date then
    local ok, s = pcall(os.date, "!%Y%m%d-%H%M%S")
    if ok and type(s) == "string" then return s end
  end
  return tostring(os and os.time and os.time() or 0)
end

--- Convert per-sample-object trace ({spline=, speed=, ...}, ...) to columnar
--- ({{0.001, 200, 0, 1.0, ...}, ...}). Drops samples missing the spline field.
---@param trace table[]|nil
---@return table[]
local function traceToColumns(trace)
  if type(trace) ~= "table" then return {} end
  local out = {}
  for i = 1, #trace do
    local row = traceSampleToColumnRow(trace[i])
    if row then
      out[#out + 1] = row
    end
  end
  return out
end

--- Build a flat snapshot table from setupReader output.
--- Input: snap = { path, keys = { { section = ..., key = ..., value = ... }, ... } }
--- Output: { ["SECTION.KEY"] = "value", ... }  (flat map for easy diffing)
---@param snap table|nil
---@return table
local function flattenSetupSnapshot(snap)
  local flat = {}
  if type(snap) ~= "table" or type(snap.keys) ~= "table" then
    return flat
  end
  for i = 1, #snap.keys do
    local e = snap.keys[i]
    if type(e) == "table" and type(e.key) == "string" and e.value ~= nil then
      local sec = e.section or ""
      local k = (sec ~= "" and (sec .. ".") or "") .. e.key
      flat[k] = tostring(e.value)
    end
  end
  return flat
end

--- Build the per-lap record. Caller supplies all the structured pieces.
---@param opts table
---  opts.session_uuid (string), opts.car (StateCar|nil), opts.sim (StateSim|nil),
---  opts.lap_n (int), opts.lap_ms (int), opts.is_pb (bool), opts.is_valid (bool),
---  opts.trace (per-sample objects), opts.corners (corner_features list),
---  opts.setup_snap (setupReader snap), opts.setup_hash (string),
---  opts.setup_ini_path (string|nil) absolute active INI path (preferred over snap.path),
---  opts.rules_hints (string list), opts.sidecar_debrief (string|nil),
---  opts.corner_advice (table label->text|nil)
---@return table|nil
local function buildRecordEnvelope(opts, samplesColumnar, samplesCount)
  if type(opts) ~= "table" then return nil end
  if not opts.lap_n or not opts.lap_ms or opts.lap_ms <= 0 then return nil end

  local archiveSetupPath = nil
  if type(opts.setup_ini_path) == "string" and opts.setup_ini_path ~= "" then
    archiveSetupPath = opts.setup_ini_path
  elseif type(opts.setup_snap) == "table" and type(opts.setup_snap.path) == "string"
      and opts.setup_snap.path ~= "" then
    local sp = opts.setup_snap.path
    if string.find(sp, "[/\\]") then
      archiveSetupPath = sp
    end
  end

  local sim = opts.sim
  local carId = persistence.archiveCarIdFromCar(opts.car) or ch.sanitizeId(ch.safeCarIdRaw(), "unknown")
  local trackId = persistence.archiveTrackIdFromSim(sim) or ch.sanitizeId(ch.safeTrackIdRaw(), "unknown")

  local trackLengthM = nil
  -- `ac.StateSim` is userdata in CSP — same pattern as grip/temps (Cursor Bugbot #78).
  pcall(function() trackLengthM = tonumber(sim and sim.trackLengthM) end)

  local trackGrip = nil
  pcall(function() trackGrip = tonumber(sim and sim.trackGripLevel) end)
  local ambient = nil
  pcall(function() ambient = tonumber(sim and sim.ambientTemperature) end)
  local trackTemp = nil
  pcall(function() trackTemp = tonumber(sim and sim.trackTemperature) end)

  samplesColumnar = samplesColumnar or {}
  samplesCount = tonumber(samplesCount) or #samplesColumnar
  local cornersOut = {}
  if type(opts.corners) == "table" then
    for i = 1, #opts.corners do
      local c = opts.corners[i]
      if type(c) == "table" then
        cornersOut[#cornersOut + 1] = {
          label = tostring(c.label or ""),
          entrySpeed = tonumber(c.entrySpeed),
          minSpeed = tonumber(c.minSpeed),
          exitSpeed = tonumber(c.exitSpeed),
          brakePointSpline = tonumber(c.brakePointSpline),
          trailBrakeRatio = tonumber(c.trailBrakeRatio),
          throttleAvg = tonumber(c.throttleAvg),
          steerReversals = tonumber(c.steerReversals),
          tractionCircleProxy = tonumber(c.tractionCircleProxy),
        }
      end
    end
  end

  local traceFieldNames = {}
  for i = 1, #TRACE_FIELDS do
    traceFieldNames[i] = TRACE_FIELDS[i]
  end

  local rulesHints = {}
  if type(opts.rules_hints) == "table" then
    for i = 1, #opts.rules_hints do
      local h = opts.rules_hints[i]
      if type(h) == "string" and h ~= "" then
        rulesHints[#rulesHints + 1] = h
      elseif type(h) == "table" and type(h.text) == "string" then
        rulesHints[#rulesHints + 1] = h.text
      end
    end
  end

  return {
    schema_version = SCHEMA_VERSION,
    source = "in_game",
    import_format = nil,
    lap_uuid = shortUuid(),
    session_uuid = tostring(opts.session_uuid or shortUuid()),
    exported_at = isoUtcNow(),
    car = {
      id = carId,
      displayName = nil,
    },
    track = {
      id = trackId,
      layout = nil,
      lengthM = trackLengthM,
    },
    conditions = {
      trackGripLevel = trackGrip,
      ambientTempC = ambient,
      trackTempC = trackTemp,
      weatherType = nil,
    },
    lap = {
      lap_n = tonumber(opts.lap_n) or 0,
      lap_ms = tonumber(opts.lap_ms) or 0,
      is_pb = opts.is_pb == true,
      is_valid = opts.is_valid ~= false,
    },
    setup = {
      hash = tostring(opts.setup_hash or ""),
      -- Persist a path `bestForSetup` can match against list rows. Prefer the
      -- canonical absolute INI from the trainer (`setup_ini_path`); `snap.path`
      -- is usually basename-only from `readIniSnapshot` (codex P1 on PR #91).
      path = archiveSetupPath,
      snapshot = flattenSetupSnapshot(opts.setup_snap),
    },
    trace = {
      samples_count = samplesCount,
      fields = traceFieldNames,
      samples = samplesColumnar,
    },
    corners = cornersOut,
    coaching = {
      rules_hints = rulesHints,
      sidecar_debrief = (type(opts.sidecar_debrief) == "string" and opts.sidecar_debrief ~= "")
          and opts.sidecar_debrief or nil,
      corner_advice_used = (type(opts.corner_advice) == "table" and next(opts.corner_advice) ~= nil)
          and opts.corner_advice or nil,
    },
  }
end

function M.buildRecord(opts)
  local samplesColumnar = traceToColumns(type(opts) == "table" and opts.trace or nil)
  return buildRecordEnvelope(opts, samplesColumnar, #samplesColumnar)
end

--- Walk archive dir, sum file sizes, delete oldest until total <= capMB.
--- Returns (filesKept, mbUsed, filesDeleted).
---@param capMB number
---@return integer, number, integer
function M.rotate(capMB)
  capMB = M.clampArchiveCapMB(capMB)
  local capBytes = capMB * 1024 * 1024
  local dir = lapArchiveDir()
  -- io.scanDir is a CSP API; fall back to noop if unavailable
  local files = {}
  local okScan = pcall(function()
    if io and type(io.scanDir) == "function" then
      local list = io.scanDir(dir, "lap_*.json")
      if type(list) == "table" then
        for i = 1, #list do
          local name = list[i]
          if type(name) == "string" then
            local path = dir .. "/" .. name
            local sz = -1
            if io.fileSize then
              local ok, s = pcall(io.fileSize, path)
              if ok then sz = tonumber(s) or -1 end
            end
            files[#files + 1] = { path = path, name = name, size = sz }
          end
        end
      end
    end
  end)
  if not okScan or #files == 0 then
    return 0, 0, 0
  end
  -- Sort by name (filename starts with `lap_<YYYYMMDD-HHMMSS>_...` so alpha == chronological)
  table.sort(files, function(a, b) return a.name < b.name end)
  -- Per-file `charge` must match what we subtract on delete (Bugbot #78 / zero-byte asymmetry).
  local unknownCount = 0
  for i = 1, #files do
    local sz = files[i].size
    if sz > 0 then
      files[i].charge = sz
    elseif sz < 0 then
      files[i].charge = 250 * 1024
      unknownCount = unknownCount + 1
    else
      files[i].charge = 0
    end
  end
  local total = 0
  for i = 1, #files do
    total = total + files[i].charge
  end
  if unknownCount > 0 and ac and type(ac.log) == "function" then
    ac.log("[COPILOT][ARCHIVE] rotate: " .. tostring(unknownCount) .. " lap file(s) lacked size; using ~250KB each in cap math")
  end
  if total == 0 and #files > 0 then
    for j = 1, #files do
      files[j].charge = 250 * 1024
    end
    total = #files * (250 * 1024)
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT][ARCHIVE] rotate: lap file sizes unknown; using ~250KB each for cap math")
    end
  end
  local deleted = 0
  local idx = 1
  while total > capBytes and idx <= #files do
    local f = files[idx]
    local okRm, rmRes = pcall(os.remove, f.path)
    if okRm and rmRes ~= nil and rmRes ~= false then
      local delta = f.charge or 0
      total = math.max(0, total - delta)
      deleted = deleted + 1
    end
    idx = idx + 1
  end
  return #files - deleted, total / (1024 * 1024), deleted
end

local function archivePathForRecord(rec)
  local dir = lapArchiveDir()
  local lapMs = (rec.lap and tonumber(rec.lap.lap_ms)) or 0
  local lapN = (rec.lap and tonumber(rec.lap.lap_n)) or 0
  local sessShort = tostring(rec.session_uuid or "x"):gsub("[^%w]", ""):sub(1, 8)
  if sessShort == "" then
    sessShort = "sess"
  end
  local lapKey = tostring(rec.lap_uuid or ""):gsub("[^%w]", ""):sub(1, 12)
  if lapKey == "" then
    lapKey = shortUuid()
  end
  local fname = string.format("lap_%s_%s_%d_%d_%s.json",
    fileTimestampUtc(), sessShort, lapN, lapMs, lapKey)
  return dir .. "/" .. fname
end

--- Write a record to disk. Returns (true, path) on success, (false, errmsg) on failure.
---@param rec table
---@param capMB number|nil
---@return boolean, string
function M.write(rec, capMB)
  if type(rec) ~= "table" then return false, "not a table" end
  capMB = M.clampArchiveCapMB(capMB)
  local dir = lapArchiveDir()
  persistence.ensureParentDirForFile(dir .. "/_dummy")  -- create dir
  local path = archivePathForRecord(rec)
  -- Large trace arrays: compact JSON avoids pretty-print whitespace blowing the cap (Cursor #78).
  local raw = persistence.encodeJsonCompact(rec)
  if not raw then return false, "encodeJsonCompact returned nil" end
  local f, ferr = io.open(path, "w")
  if not f then return false, "open failed: " .. tostring(ferr) end
  local writeOk, writeRes = pcall(function() return f:write(raw) end)
  if not writeOk or not writeRes then
    pcall(function() f:close() end)
    pcall(os.remove, path)
    local writeMsg = (not writeOk) and tostring(writeRes) or "write returned nil"
    return false, "write failed: " .. writeMsg
  end
  local flushOk, flushRes = pcall(function() return f:flush() end)
  -- Lua 5.1 / LuaJIT: flush returns true on success, nil+err on failure (never boolean false — CodeRabbit #78).
  if not flushOk or not flushRes then
    pcall(function() f:close() end)
    pcall(os.remove, path)
    local flushMsg = (not flushOk) and tostring(flushRes) or "flush returned nil"
    return false, "flush failed: " .. flushMsg
  end
  local closeOk, closeRes = pcall(function() return f:close() end)
  if not closeOk or not closeRes then
    pcall(os.remove, path)
    local closeMsg = (not closeOk) and tostring(closeRes) or "close returned nil"
    return false, "close failed: " .. closeMsg
  end
  pcall(function() M.rotate(capMB) end)
  bustStatsCache()
  return true, path
end

local function jsonValue(value, label)
  local raw = persistence.encodeJsonCompact(value)
  if not raw then
    return nil, "encodeJsonCompact returned nil for " .. tostring(label)
  end
  return raw, nil
end

--- Create a budgeted lap-archive write job.
---
--- This keeps the completed-lap frame from compact-encoding and flushing a
--- whole trace on CSP's render thread. Call `job:step(maxRows)` once per frame;
--- it writes at most `maxRows` trace rows, then returns `(done, ok, pathOrErr)`.
---@param opts table
---@param capMB number|nil
---@return table|nil, string|nil
function M.createWriteJob(opts, capMB)
  if type(opts) ~= "table" then
    return nil, "opts must be a table"
  end
  local samplesCount = countTraceRows(opts.trace)
  local rec = buildRecordEnvelope(opts, {}, samplesCount)
  if not rec then
    return nil, "invalid archive record options"
  end

  capMB = M.clampArchiveCapMB(capMB)
  local path = archivePathForRecord(rec)
  local job = {
    _state = "open",
    _file = nil,
    _path = path,
    _tmpPath = path .. ".tmp",
    _rec = rec,
    _trace = opts.trace or {},
    _sampleIndex = 1,
    _samplesWritten = 0,
    samplesCount = samplesCount,
    done = false,
    ok = nil,
    result = nil,
  }

  function job:_write(chunk)
    if chunk == nil or chunk == "" then return true, nil end
    if not self._file then return false, "archive temp file is not open" end
    local writeOk, writeRes = pcall(function() return self._file:write(chunk) end)
    if not writeOk or not writeRes then
      local msg = (not writeOk) and tostring(writeRes) or "write returned nil"
      return false, "write failed: " .. msg
    end
    return true, nil
  end

  function job:_flush()
    if not self._file then return true, nil end
    local flushOk, flushRes = pcall(function() return self._file:flush() end)
    if not flushOk or not flushRes then
      local msg = (not flushOk) and tostring(flushRes) or "flush returned nil"
      return false, "flush failed: " .. msg
    end
    return true, nil
  end

  function job:_fail(message)
    if self._file then
      pcall(function() self._file:close() end)
      self._file = nil
    end
    pcall(os.remove, self._tmpPath)
    self.done = true
    self.ok = false
    self.result = tostring(message or "archive job failed")
    return true, false, self.result
  end

  function job:_writeField(name, value)
    if value == nil then return true, nil end
    local raw, encErr = jsonValue(value, name)
    if not raw then return false, encErr end
    local prefix = self._fieldWritten and "," or ""
    local ok, err = self:_write(prefix .. "\"" .. name .. "\":" .. raw)
    if not ok then return false, err end
    self._fieldWritten = true
    return true, nil
  end

  function job:_open()
    persistence.ensureParentDirForFile(lapArchiveDir() .. "/_dummy")
    local f, ferr = io.open(self._tmpPath, "w")
    if not f then
      return self:_fail("open failed: " .. tostring(ferr))
    end
    self._file = f
    self._fieldWritten = false

    local ok, err = self:_write("{")
    if not ok then return self:_fail(err) end
    local fields = {
      { "schema_version", self._rec.schema_version },
      { "source", self._rec.source },
      { "import_format", self._rec.import_format },
      { "lap_uuid", self._rec.lap_uuid },
      { "session_uuid", self._rec.session_uuid },
      { "exported_at", self._rec.exported_at },
      { "car", self._rec.car },
      { "track", self._rec.track },
      { "conditions", self._rec.conditions },
      { "lap", self._rec.lap },
      { "setup", self._rec.setup },
    }
    for i = 1, #fields do
      ok, err = self:_writeField(fields[i][1], fields[i][2])
      if not ok then return self:_fail(err) end
    end

    local traceFieldsRaw
    traceFieldsRaw, err = jsonValue(self._rec.trace.fields, "trace.fields")
    if not traceFieldsRaw then return self:_fail(err) end
    local prefix = self._fieldWritten and "," or ""
    ok, err = self:_write(prefix
      .. "\"trace\":{\"samples_count\":" .. tostring(self.samplesCount)
      .. ",\"fields\":" .. traceFieldsRaw
      .. ",\"samples\":[")
    if not ok then return self:_fail(err) end
    self._fieldWritten = true
    self._state = "samples"
    -- Fall through to sample writes in the same step so a new job does useful
    -- bounded work immediately after opening the temp file.
    return false, nil, nil
  end

  function job:_finish()
    local ok, err = self:_write("]}")
    if not ok then return self:_fail(err) end
    ok, err = self:_writeField("corners", self._rec.corners)
    if not ok then return self:_fail(err) end
    ok, err = self:_writeField("coaching", self._rec.coaching)
    if not ok then return self:_fail(err) end
    ok, err = self:_write("}")
    if not ok then return self:_fail(err) end

    ok, err = self:_flush()
    if not ok then return self:_fail(err) end
    local closeOk, closeRes = pcall(function() return self._file:close() end)
    self._file = nil
    if not closeOk or not closeRes then
      local msg = (not closeOk) and tostring(closeRes) or "close returned nil"
      return self:_fail("close failed: " .. msg)
    end
    local renameOk, renameRes, renameErr = pcall(os.rename, self._tmpPath, self._path)
    if not renameOk or not renameRes then
      local msg = (not renameOk) and tostring(renameRes)
        or tostring(renameErr or "rename returned nil")
      return self:_fail("rename failed: " .. msg)
    end
    pcall(function() M.rotate(capMB) end)
    bustStatsCache()
    self.done = true
    self.ok = true
    self.result = self._path
    return true, true, self._path
  end

  function job:step(maxRows)
    if self.done then
      return true, self.ok == true, self.result
    end
    local rowsBudget = math.max(1, math.floor(tonumber(maxRows) or 64))
    if self._state == "open" then
      local done, ok, res = self:_open()
      if done then return done, ok, res end
    end
    if self._state == "samples" then
      local processed = 0
      while self._sampleIndex <= #self._trace and processed < rowsBudget do
        local row = traceSampleToColumnRow(self._trace[self._sampleIndex])
        self._sampleIndex = self._sampleIndex + 1
        processed = processed + 1
        if row then
          local raw, encErr = jsonValue(row, "trace.sample")
          if not raw then return self:_fail(encErr) end
          local prefix = self._samplesWritten > 0 and "," or ""
          local ok, err = self:_write(prefix .. raw)
          if not ok then return self:_fail(err) end
          self._samplesWritten = self._samplesWritten + 1
        end
      end
      if self._sampleIndex <= #self._trace then
        local ok, err = self:_flush()
        if not ok then return self:_fail(err) end
        return false, nil, nil
      end
      self._state = "finish"
    end
    if self._state == "finish" then
      return self:_finish()
    end
    return false, nil, nil
  end

  return job, nil
end

--- Lightweight stats for the Settings UI: count + total MB used.
---@return integer count, number mb
function M.stats()
  local now = (os and os.time and os.time()) or 0
  if now - _statsCacheT < STATS_CACHE_TTL_SEC then
    return _statsCacheCount, _statsCacheMb
  end
  local dir = lapArchiveDir()
  local count = 0
  local total = 0
  pcall(function()
    if io and type(io.scanDir) == "function" then
      local list = io.scanDir(dir, "lap_*.json")
      if type(list) == "table" then
        for i = 1, #list do
          local name = list[i]
          if type(name) == "string" then
            count = count + 1
            if io.fileSize then
              local ok, s = pcall(io.fileSize, dir .. "/" .. name)
              if ok then
                local sz = tonumber(s)
                if sz and sz > 0 then
                  total = total + sz
                elseif sz and sz < 0 then
                  -- Match `rotate` unknown-size heuristic (Bugbot #78).
                  total = total + (250 * 1024)
                end
              end
            end
          end
        end
      end
    end
  end)
  _statsCacheT = now
  _statsCacheCount = count
  _statsCacheMb = total / (1024 * 1024)
  return _statsCacheCount, _statsCacheMb
end

return M
