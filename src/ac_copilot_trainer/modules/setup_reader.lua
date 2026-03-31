-- Active setup INI snapshot + hash; copilot auto-load stub (issue #8 H + comment I).

local M = {}

local COPILOT_GLOB = "copilot_"

---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@return string|nil
local function guessSetupIniPath(car, sim)
  if not car or not sim then
    return nil
  end
  local okDoc, doc = pcall(function()
    return ac.getFolder(ac.FolderID.Documents)
  end)
  if not okDoc or not doc or doc == "" then
    return nil
  end
  local carId = tostring(car.id or car.name or "unknown"):gsub("[^%w%.%-_]+", "_")
  local trackId = tostring(sim.track or sim.trackName or sim.trackConfiguration or "unknown"):gsub("[^%w%.%-_]+", "_")
  -- AC default: Documents/Assetto Corsa/setups/<car>/<track>/*.ini
  local base = doc .. "/Assetto Corsa/setups/" .. carId .. "/" .. trackId
  for _, name in ipairs({ "race.ini", "default.ini" }) do
    local p = base .. "/" .. name
    local f = io.open(p, "r")
    if f then
      f:close()
      return p
    end
  end
  return base .. "/race.ini"
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
        local lk = string.lower(k)
        if
          lk:find("spring", 1, true)
          or lk:find("arb", 1, true)
          or lk:find("camber", 1, true)
          or lk:find("toe", 1, true)
          or lk:find("diff", 1, true)
          or lk:find("wing", 1, true)
          or lk:find("brake", 1, true)
        then
          keys[#keys + 1] = { section = section, key = k, value = v }
        end
      end
    end
  end
  return { path = path, keys = keys }
end

local function hashSnapshot(snap)
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

---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@return table|nil snap
---@return string hash
function M.snapshotActive(car, sim)
  local path = guessSetupIniPath(car, sim)
  local snap = M.readIniSnapshot(path)
  if not snap then
    return nil, ""
  end
  return snap, hashSnapshot(snap)
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
  local carId = tostring(car.id or car.name or "unknown"):gsub("[^%w%.%-_]+", "_")
  local trackId = tostring(sim.track or sim.trackName or "unknown"):gsub("[^%w%.%-_]+", "_")
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
  return "Setup hash changed vs prior lap"
end

return M
