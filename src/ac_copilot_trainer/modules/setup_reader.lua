-- Active setup INI snapshot + hash; copilot auto-load stub (issue #8 H + comment I).

local M = {}

local COPILOT_GLOB = "copilot_"

--- Shared with path guessing and operator messages (empty string → fallback).
local function sanitizeId(s, fallback)
  s = tostring(s or fallback or "unknown"):gsub("[^%w%.%-_]+", "_")
  if s == "" then
    s = fallback or "unknown"
  end
  return s
end

local function safeCarIdRaw()
  if not ac or type(ac.getCarID) ~= "function" then
    return nil
  end
  local ok, v = pcall(ac.getCarID, 0)
  if not ok then
    return nil
  end
  return v
end

local function safeTrackIdRaw()
  if not ac or type(ac.getTrackID) ~= "function" then
    return nil
  end
  local ok, v = pcall(ac.getTrackID)
  if not ok then
    return nil
  end
  return v
end

--- Prefer CSP-reported active setup path when the runtime exposes it (varies by CSP build).
---@param car ac.StateCar|nil
---@return string|nil
local function activeSetupPathFromCar(car)
  if not car then
    return nil
  end
  for _, key in ipairs({ "setupFilename", "currentSetupFilename", "setupFile", "setupINI" }) do
    local ok, p = pcall(function()
      return car[key]
    end)
    if ok and type(p) == "string" and p ~= "" then
      local f = io.open(p, "r")
      if f then
        f:close()
        return p
      end
    end
  end
  return nil
end

---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@return string|nil
local function guessSetupIniPath(car, sim)
  if not car or not sim then
    return nil
  end
  local fromCar = activeSetupPathFromCar(car)
  if fromCar then
    return fromCar
  end
  local okDoc, doc = pcall(function()
    return ac.getFolder(ac.FolderID.Documents)
  end)
  if not okDoc or not doc or doc == "" then
    return nil
  end
  local carId = sanitizeId(safeCarIdRaw(), "unknown")
  -- Use CSP global API (C-structs throw on invalid field access, not nil).
  local trackId = sanitizeId(safeTrackIdRaw(), "unknown")
  local layoutRaw = ac.getTrackLayout and ac.getTrackLayout() or nil
  local layoutId = layoutRaw ~= nil and sanitizeId(layoutRaw, "") or ""
  local trackRoot = doc .. "/Assetto Corsa/setups/" .. carId .. "/" .. trackId
  local bases = {}
  if layoutId ~= "" and layoutId ~= "unknown" then
    bases[1] = trackRoot .. "/" .. layoutId
    bases[2] = trackRoot
  else
    bases[1] = trackRoot
  end
  for b = 1, #bases do
    local base = bases[b]
    for _, name in ipairs({ "race.ini", "default.ini" }) do
      local p = base .. "/" .. name
      local f = io.open(p, "r")
      if f then
        f:close()
        return p
      end
    end
  end
  return trackRoot .. "/race.ini"
end

--- Naive INI key harvest (no full parser): [SECTION] and key=value lines.
---@param path string|nil
---@return table|nil
function M.readIniSnapshot(path)
  if not path or path == "" then
    return nil
  end
  local f = io.open(path, "r")
  if not f then
    return nil
  end
  local text = f:read("*a")
  f:close()
  if not text then
    return nil
  end
  local keys = {}
  local section = ""
  for line in string.gmatch(text .. "\n", "[^\r\n]+\n") do
    local sec = line:match("^%[([^%]]+)%]")
    if sec then
      section = sec
    else
      local k, v = line:match("^([%w_]+)%s*=%s*(.-)%s*$")
      if k and v then
        -- Full harvest for digest: pressures, dampers, gearing, aero, etc. (bounded by file read).
        keys[#keys + 1] = { section = section, key = k, value = v }
      end
    end
  end
  local base = path:match("[^/\\]+$") or path
  return { path = base, keys = keys }
end

local function canonicalSetupString(snap)
  if not snap or not snap.keys then
    return ""
  end
  local parts = {}
  for i = 1, #snap.keys do
    local e = snap.keys[i]
    parts[i] = e.section .. "|" .. e.key .. "=" .. tostring(e.value)
  end
  table.sort(parts)
  return table.concat(parts, ";")
end

--- Short stable digest (djb2) of canonical setup string — not the raw concatenation.
local function digestSetup(canonical)
  if not canonical or canonical == "" then
    return ""
  end
  local h = 5381
  for i = 1, #canonical do
    h = (h * 33 + string.byte(canonical, i)) % 4294967296
  end
  return string.format("%08x", h)
end

---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@return table|nil snap
---@return string digest compact hex signature for persistence/compare
function M.snapshotActive(car, sim)
  local path = guessSetupIniPath(car, sim)
  local snap = M.readIniSnapshot(path)
  if not snap then
    return nil, ""
  end
  return snap, digestSetup(canonicalSetupString(snap))
end

--- Part I: auto-load `copilot_*.ini` — CSP setup application APIs differ by build; try pcall hooks only.
---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@param autoLoad boolean|nil
---@return string|nil message
function M.tryAutoLoadCopilotSetup(car, sim, autoLoad)
  if autoLoad == false then
    return nil
  end
  if not car or not sim then
    return nil
  end
  -- Defer to future CSP API: physics.loadSetup, car.applySetup, etc.
  local okDoc, doc = pcall(function()
    return ac.getFolder(ac.FolderID.Documents)
  end)
  if not okDoc or not doc then
    return nil
  end
  local carId = sanitizeId(safeCarIdRaw(), "unknown")
  local trackId = sanitizeId(safeTrackIdRaw(), "unknown")
  local dir = doc .. "/Assetto Corsa/setups/" .. carId .. "/" .. trackId
  -- Without a portable directory list in Lua 5.1, surface intent for operators.
  return string.format("Copilot setup dir: %s (%s*.ini)", dir, COPILOT_GLOB)
end

---@param prevHash string|nil
---@param newHash string|nil
---@return string|nil
function M.describeChange(prevHash, newHash)
  if not prevHash or prevHash == "" or not newHash or newHash == "" then
    return nil
  end
  if prevHash == newHash then
    return nil
  end
  return "Setup signature changed vs prior lap"
end

return M
