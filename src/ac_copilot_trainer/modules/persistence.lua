-- JSON load/save for brake points (per car + track) under CSP ScriptConfig.

local M = {}

local APP_SUBDIR = "ac_copilot_trainer"
local DATA_VERSION = 1

local function safeName(s)
  s = tostring(s or "unknown"):gsub("[^%w%.%-_]+", "_")
  if s == "" then
    s = "unknown"
  end
  return s
end

function M.sessionKey(car, sim)
  local track = "unknown_track"
  if sim then
    track = sim.trackName or sim.track or sim.trackConfiguration or track
  end
  local carKey = "unknown_car"
  if car then
    carKey = car.carID or car.carModel or car.driverName or carKey
  end
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
    return JSON.stringify(t, true)
  end
  return "{}"
end

local function jsonDecode(s)
  if not s or s == "" then
    return nil
  end
  if JSON and type(JSON.parse) == "function" then
    return JSON.parse(s)
  end
  return nil
end

local function ensureDir(path)
  local dir = path:match("^(.*)/[^/]+$")
  if not dir or dir == "" then
    return
  end
  local sep = package.config:sub(1, 1)
  if sep == "\\" then
    os.execute('mkdir "' .. dir:gsub("/", "\\") .. '" 2>nul')
  else
    os.execute('mkdir -p "' .. dir .. '"')
  end
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
  return jsonDecode(raw)
end

function M.save(car, sim, data)
  data.version = DATA_VERSION
  local path = M.dataPath(car, sim)
  ensureDir(path)
  local f = io.open(path, "w")
  if not f then
    return false
  end
  f:write(jsonEncode(data))
  f:close()
  return true
end

return M
