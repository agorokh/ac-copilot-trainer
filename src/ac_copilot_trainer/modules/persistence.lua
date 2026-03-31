-- JSON load/save for brake points (per car + track) under CSP ScriptConfig.

local M = {}

local APP_SUBDIR = "ac_copilot_trainer"
local DATA_VERSION = 3

local function safeName(s)
  s = tostring(s or "unknown"):gsub("[^%w%.%-_]+", "_")
  if s == "" then
    s = "unknown"
  end
  return s
end

function M.sessionKey(car, sim)
  -- CSP C-structs throw on invalid field access (not nil like Lua tables).
  -- Use the global CSP API functions (verified from PocketTechnician, CMRT-Essential-HUD).
  local track = ac.getTrackFullID("/") or ac.getTrackID() or "unknown_track"
  local carKey = ac.getCarID(0) or "unknown_car"
  return safeName(carKey) .. "__" .. safeName(track)
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
