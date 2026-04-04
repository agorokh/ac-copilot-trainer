-- Session training journal (issue #9 Part H, milestone #47): JSON export under ScriptConfig.

local M = {}

local persistence = require("persistence")
local ch = require("csp_helpers")

local SCHEMA_VERSION = 1

local function safeSimField(sim, key)
  if not sim then
    return nil
  end
  local ok, v = pcall(function()
    return sim[key]
  end)
  if ok then
    return v
  end
  return nil
end

--- Match `persistence.sessionKey` fallbacks: globals first, then `car` / `sim` (pcall per field; C-structs throw).
local function resolveCarId(car)
  local g = ch.carIdRawFromGlobals()
  if g and g ~= "" then
    return g
  end
  if not car then
    return "unknown"
  end
  for _, key in ipairs({ "id", "name", "driverName" }) do
    local ok, v = pcall(function()
      return car[key]
    end)
    if ok and v ~= nil and tostring(v) ~= "" then
      return tostring(v)
    end
  end
  return "unknown"
end

local function resolveTrackId(sim)
  local g = ch.trackIdRawFromGlobals()
  if g and g ~= "" then
    return g
  end
  if not sim then
    return "unknown"
  end
  for _, key in ipairs({ "trackName", "track", "trackConfiguration" }) do
    local ok, v = pcall(function()
      return sim[key]
    end)
    if ok and v ~= nil and tostring(v) ~= "" then
      return tostring(v)
    end
  end
  return "unknown"
end

local function logJournal(msg)
  if ac and type(ac.log) == "function" then
    ac.log("[COPILOT] session_journal: " .. msg)
  end
end

local function isoUtcNow()
  return os.date("!%Y-%m-%dT%H:%M:%SZ")
end

local function fileTimestampUtc()
  return os.date("!%Y%m%d_%H%M%S")
end

local function journalDir()
  return persistence.dataDir() .. "/journal"
end

local function indexPath()
  return journalDir() .. "/journal_index.jsonl"
end

local function serializeCoaching(lines)
  if not lines or type(lines) ~= "table" or #lines == 0 then
    return {}
  end
  local out = {}
  for i = 1, #lines do
    local e = lines[i]
    if type(e) == "table" and type(e.text) == "string" then
      out[#out + 1] = {
        kind = type(e.kind) == "string" and e.kind or "general",
        text = e.text,
      }
    elseif type(e) == "string" then
      out[#out + 1] = { kind = "general", text = e }
    end
  end
  return out
end

local function simplifyCorners(corners)
  if not corners or type(corners) ~= "table" then
    return {}
  end
  local out = {}
  for i = 1, #corners do
    local c = corners[i]
    if type(c) == "table" then
      out[#out + 1] = {
        label = c.label,
        entrySpeed = tonumber(c.entrySpeed),
        minSpeed = tonumber(c.minSpeed),
        exitSpeed = tonumber(c.exitSpeed),
        brakePointSpline = tonumber(c.brakePointSpline),
        trailBrakeRatio = tonumber(c.trailBrakeRatio),
      }
    end
  end
  return out
end

---@return table[], number|nil, number|nil, number|nil
local function lapHistorySummaries(hist)
  if not hist or type(hist) ~= "table" then
    return {}, nil, nil, nil
  end
  local laps = {}
  local sum, n = 0, 0
  local bestMs, lastMs = nil, nil
  for i = 1, #hist do
    local lap = hist[i]
    if type(lap) == "table" then
      local ms = tonumber(lap.lapMs)
      if ms and ms > 0 then
        laps[#laps + 1] = {
          lap_ms = ms,
          corner_count = (lap.corners and type(lap.corners) == "table") and #lap.corners or 0,
        }
        sum = sum + ms
        n = n + 1
        lastMs = ms
        if bestMs == nil or ms < bestMs then
          bestMs = ms
        end
      end
    end
  end
  local avgMs = (n > 0) and math.floor(sum / n + 0.5) or nil
  return laps, bestMs, lastMs, avgMs
end

--- Build the on-disk record. Caller supplies `state` snapshot from the driving session.
---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@param state table
---@return table|nil
function M.buildRecord(car, sim, state)
  if not state or type(state) ~= "table" then
    return nil
  end
  local lapsDone = tonumber(state.lapsCompleted) or 0
  if lapsDone <= 0 then
    return nil
  end

  local hist = state.lapFeatureHistory
  local lap_history, histBest, histLast, histAvg = lapHistorySummaries(hist)
  local bestMs = tonumber(state.bestLapMs) or histBest
  local lastMs = tonumber(state.lastLapMs) or histLast
  local avgMs = histAvg

  local lastCorners = {}
  if hist and type(hist) == "table" and #hist > 0 then
    local last = hist[#hist]
    if type(last) == "table" and type(last.corners) == "table" then
      lastCorners = simplifyCorners(last.corners)
    end
  end

  local grip = safeSimField(sim, "trackGripLevel")
  grip = tonumber(grip)

  local sk = (car and sim) and persistence.sessionKey(car, sim) or "unknown"

  return {
    schema_version = SCHEMA_VERSION,
    exported_at = isoUtcNow(),
    app_version_ui = state.appVersionUi or "",
    session_key = sk,
    car = {
      id = resolveCarId(car),
    },
    track = {
      id = resolveTrackId(sim),
    },
    conditions = {
      track_grip = grip,
    },
    summary = {
      laps_completed = lapsDone,
      best_lap_ms = bestMs,
      last_lap_ms = lastMs,
      avg_lap_ms = avgMs,
    },
    lap_history = lap_history,
    corners_last_lap = lastCorners,
    coaching_hints_last = serializeCoaching(state.coachingLines),
  }
end

--- Write journal JSON + append one line to `journal_index.jsonl`. No-op if no laps completed.
---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@param state table
---@return boolean
function M.writeSessionEnd(car, sim, state)
  local rec = M.buildRecord(car, sim, state)
  if not rec then
    return false
  end
  local skSafe = rec.session_key:gsub("[^%w%.%-_]+", "_")
  local fname = "session_" .. fileTimestampUtc() .. "_" .. skSafe .. ".json"
  local path = journalDir() .. "/" .. fname
  persistence.ensureParentDirForFile(path)
  local raw = persistence.encodeJson(rec)
  if not raw then
    return false
  end
  local f = io.open(path, "w")
  if not f then
    logJournal("failed to open journal file for write: " .. tostring(path))
    return false
  end
  if not f:write(raw) then
    logJournal("failed to write journal file: " .. tostring(path))
    f:close()
    return false
  end
  f:close()

  local idxLine = persistence.encodeJson({
    journal_file = fname,
    exported_at = rec.exported_at,
    session_key = rec.session_key,
  })
  if idxLine then
    persistence.ensureParentDirForFile(indexPath())
    local ip = indexPath()
    local af = io.open(ip, "a")
    if af then
      af:write(idxLine .. "\n")
      af:close()
    else
      logJournal("failed to open journal index for append: " .. tostring(ip))
    end
  end
  return true
end

return M
