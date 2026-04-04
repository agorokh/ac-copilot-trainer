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
    if ok and v ~= nil and tostring(v) ~= "" then
      return tostring(v)
    end
  end
  return nil
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

function M.dataPath(car, sim)
  return M.dataDir() .. "/" .. M.sessionKey(car, sim) .. ".json"
end

local function jsonEncode(t)
  if JSON and type(JSON.stringify) == "function" then
    local ok, out = pcall(JSON.stringify, t, true)
    if ok and type(out) == "string" then
      return out
    end
  end
  return nil
end

--- One-line JSON for JSONL append (no pretty-print newlines).
local function jsonEncodeCompact(t)
  if JSON and type(JSON.stringify) == "function" then
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
  if JSON and type(JSON.parse) == "function" then
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
