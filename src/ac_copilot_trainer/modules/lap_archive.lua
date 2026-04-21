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
--     import_format = nil | "motec_csv" | "ibt" | "delta",
--     lap_uuid, session_uuid, exported_at,
--     car = { id, displayName? },
--     track = { id, layout?, lengthM? },
--     conditions = { trackGripLevel?, ambientTempC?, trackTempC?, weatherType? },
--     lap = { lap_n, lap_ms, is_pb, is_valid },
--     setup = { hash, snapshot = { <flat INI key=value map> } },
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

-- Trace sample field order. MUST match the order produced by `traceToColumns`.
-- Documented in the schema header so future imports map columns identically.
local TRACE_FIELDS = {
  "spline", "speed", "eMs", "throttle", "brake", "steer", "gear", "px", "py", "pz",
}

local function lapArchiveDir()
  return persistence.copilotStateDir() .. "/journal/laps"
end

--- Generate a short stable-ish UUID-like ID. Not RFC4122 — Lua 5.1 has no
--- crypto, so we use os.time + math.random + a counter. Good enough for
--- debug-friendly filenames; not for cryptographic uniqueness.
local _uuidCounter = 0
local function shortUuid()
  _uuidCounter = _uuidCounter + 1
  local t = (os and os.time and os.time()) or 0
  local r = math.random(0, 0xFFFFFF)
  return string.format("%x%06x%x", t % 0xFFFFFFFF, r, _uuidCounter % 0xFFFF)
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
    local s = trace[i]
    if type(s) == "table" and type(s.spline) == "number" then
      out[#out + 1] = {
        s.spline,
        tonumber(s.speed) or 0,
        tonumber(s.eMs) or 0,
        tonumber(s.throttle) or 0,
        tonumber(s.brake) or 0,
        tonumber(s.steer) or 0,
        tonumber(s.gear) or 0,
        tonumber(s.px) or 0,
        tonumber(s.py) or 0,
        tonumber(s.pz) or 0,
      }
    end
  end
  return out
end

--- Build a flat snapshot table from setupReader output.
--- Input: snap = { path, keys = {{section, key, value}, ...} }
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
---  opts.rules_hints (string list), opts.sidecar_debrief (string|nil),
---  opts.corner_advice (table label->text|nil)
---@return table|nil
function M.buildRecord(opts)
  if type(opts) ~= "table" then return nil end
  if not opts.lap_n or not opts.lap_ms or opts.lap_ms <= 0 then return nil end

  local car = opts.car
  local sim = opts.sim
  local carId = ch.sanitizeId(ch.safeCarIdRaw(), "unknown")
  local trackId = ch.sanitizeId(ch.safeTrackIdRaw(), "unknown")

  local trackLengthM = nil
  if sim and type(sim) == "table" then
    pcall(function() trackLengthM = tonumber(sim.trackLengthM) end)
  end

  local trackGrip = nil
  pcall(function() trackGrip = tonumber(sim and sim.trackGripLevel) end)
  local ambient = nil
  pcall(function() ambient = tonumber(sim and sim.ambientTemperature) end)
  local trackTemp = nil
  pcall(function() trackTemp = tonumber(sim and sim.trackTemperature) end)

  local samplesColumnar = traceToColumns(opts.trace)
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
      snapshot = flattenSetupSnapshot(opts.setup_snap),
    },
    trace = {
      samples_count = #samplesColumnar,
      fields = TRACE_FIELDS,
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

--- Walk archive dir, sum file sizes, delete oldest until total <= capMB.
--- Returns (filesKept, mbUsed, filesDeleted).
---@param capMB number
---@return integer, number, integer
function M.rotate(capMB)
  capMB = tonumber(capMB) or 500
  if capMB <= 0 then capMB = 500 end
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
  local total = 0
  for i = 1, #files do
    if files[i].size > 0 then total = total + files[i].size end
  end
  local deleted = 0
  local idx = 1
  while total > capBytes and idx <= #files do
    local f = files[idx]
    if f.size > 0 then
      local okRm = pcall(function() os.remove(f.path) end)
      if okRm then
        total = total - f.size
        deleted = deleted + 1
      end
    end
    idx = idx + 1
  end
  return #files - deleted, total / (1024 * 1024), deleted
end

--- Write a record to disk. Returns (true, path) on success, (false, errmsg) on failure.
---@param rec table
---@param capMB number|nil
---@return boolean, string
function M.write(rec, capMB)
  if type(rec) ~= "table" then return false, "not a table" end
  local dir = lapArchiveDir()
  persistence.ensureParentDirForFile(dir .. "/_dummy")  -- create dir
  local lapMs = (rec.lap and tonumber(rec.lap.lap_ms)) or 0
  local lapN = (rec.lap and tonumber(rec.lap.lap_n)) or 0
  local sessShort = tostring(rec.session_uuid or "x"):sub(1, 8)
  local fname = string.format("lap_%s_%s_%d_%d.json",
    fileTimestampUtc(), sessShort, lapN, lapMs)
  local path = dir .. "/" .. fname
  local raw = persistence.encodeJson(rec)
  if not raw then return false, "encodeJson returned nil" end
  local f, ferr = io.open(path, "w")
  if not f then return false, "open failed: " .. tostring(ferr) end
  f:write(raw)
  f:close()
  -- Rotate after every successful write. Cheap if under cap.
  pcall(function() M.rotate(capMB or 500) end)
  return true, path
end

--- Lightweight stats for the Settings UI: count + total MB used.
---@return integer count, number mb
function M.stats()
  local dir = lapArchiveDir()
  local count = 0
  local total = 0
  pcall(function()
    if io and type(io.scanDir) == "function" then
      local list = io.scanDir(dir, "lap_*.json")
      if type(list) == "table" then
        count = #list
        for i = 1, #list do
          if io.fileSize then
            local ok, s = pcall(io.fileSize, dir .. "/" .. list[i])
            if ok then total = total + (tonumber(s) or 0) end
          end
        end
      end
    end
  end)
  return count, total / (1024 * 1024)
end

return M
