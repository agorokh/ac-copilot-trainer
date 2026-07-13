-- Active setup INI snapshot + hash; copilot auto-load stub (issue #8 H + comment I).

local M = {}

local ch = require("csp_helpers")

local COPILOT_GLOB = "copilot_"
local RACE_INI_NO_SETUP = false

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

local function trim(s)
  return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function documentsRoot()
  local okDoc, doc = pcall(function()
    return ac.getFolder(ac.FolderID.Documents)
  end)
  if not okDoc or not doc or doc == "" then
    return nil
  end
  return doc
end

local function safeStringField(obj, key)
  if not obj then
    return nil
  end
  local ok, value = pcall(function()
    return obj[key]
  end)
  if not ok or value == nil then
    return nil
  end
  if type(value) == "string" and value == "" then
    return nil
  end
  return tostring(value)
end

local function readablePath(path)
  if not path or path == "" then
    return nil
  end
  local h = io.open(path, "r")
  if h then
    h:close()
    return path
  end
  return nil
end

--- Applied-setup INI path from the launch `cfg/race.ini` (`[CAR_0] _EXT_SETUP_FILENAME`).
--- AC and Content Manager record the *selected* setup there as an absolute path, and the #461
--- autonomous harness bakes it there before spawn — so it is the authoritative "which setup is
--- applied" pointer whenever CSP does not expose `car.setupFilename` (most builds). Without this
--- a harness-driven (or CM-selected) lap archived an EMPTY setup snapshot pointing at a
--- non-existent `setups/<car>/<track>/race.ini` (live-found #461). Returns the absolute INI path
--- only when it resolves to a readable file, else nil.
---@param doc string
---@return string|false|nil value  path | RACE_INI_NO_SETUP (confirmed none) | nil (vanilla folder-guess)
---@return boolean transient  true when race.ini could not be opened/read this call — momentarily
---  missing or locked while CM rewrites it; the caller must retry, NOT folder-guess (#466 B2).
local function readActiveSetupPathFromRaceIni(doc)
  local f = io.open(doc .. "/Assetto Corsa/cfg/race.ini", "r")
  if not f then
    return nil, true
  end
  local text = f:read("*a")
  f:close()
  if not text then
    return nil, true
  end
  local section = ""
  local ext_setup_filename = nil
  local setup_val = nil
  for line in string.gmatch(text .. "\n", "([^\r\n]*)[\r\n]") do
    local sec = line:match("^%s*%[([^%]]+)%]%s*$")
    if sec then
      section = sec
    elseif section == "CAR_0" then
      local key, value = line:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
      if key == "_EXT_SETUP_FILENAME" then
        ext_setup_filename = trim(value or "")
      elseif key == "SETUP" then
        setup_val = trim(value or "")
      end
    end
  end
  if ext_setup_filename then
    if ext_setup_filename == "" then
      return RACE_INI_NO_SETUP, false
    end
    return (readablePath(ext_setup_filename) or RACE_INI_NO_SETUP), false
  end
  if setup_val and setup_val ~= "" then
    -- Vanilla `SETUP=<name>` without `_EXT_SETUP_FILENAME`: a real (readable) race.ini that simply
    -- does not name an absolute setup path. NOT transient — let the caller fall through to the
    -- legacy folder guess (preserves the vanilla-setup fallback added in 927b07ed for #461).
    return nil, false
  end
  return RACE_INI_NO_SETUP, false
end

local raceIniSetupCache = { key = nil, path = RACE_INI_NO_SETUP }

local function raceIniSetupCacheKey(sim)
  local doc = documentsRoot()
  if not doc then
    return nil, nil
  end
  local carId = ch.sanitizeId(ch.safeCarIdRaw(), "unknown")
  local trackId = ch.sanitizeId(ch.safeTrackIdRaw(), "unknown")
  local layoutRaw = ch.safeTrackLayoutRaw()
  local layoutId = layoutRaw ~= nil and ch.sanitizeId(layoutRaw, "") or ""
  local parts = { doc, carId, trackId, layoutId }
  for _, key in ipairs({ "currentSessionIndex", "sessionIndex", "sessionType", "raceSessionType" }) do
    parts[#parts + 1] = key .. "=" .. (safeStringField(sim, key) or "")
  end
  return table.concat(parts, "|"), doc
end

---@return string|false|nil value  path | RACE_INI_NO_SETUP | nil (vanilla folder-guess this call)
---@return boolean transient  true when race.ini was momentarily unreadable (retry, no folder guess)
local function activeSetupPathFromRaceIni(sim)
  local key, doc = raceIniSetupCacheKey(sim)
  if not key or not doc then
    return nil, false
  end
  if raceIniSetupCache.key == key then
    return raceIniSetupCache.path, false
  end
  local path, transient = readActiveSetupPathFromRaceIni(doc)
  if transient then
    -- race.ini momentarily missing/locked while CM rewrites it: do NOT cache and do NOT let the
    -- caller folder-guess (that can archive the wrong setup). Signal retry (#466 B2).
    return nil, true
  end
  if path == nil then
    -- Vanilla `SETUP=` (no `_EXT_SETUP_FILENAME`): caller folder-guesses; not cached (the guess is
    -- cheap and a later launch may bake an absolute `_EXT_SETUP_FILENAME` this session should pick up).
    return nil, false
  end
  -- Cache confirmed reads (a path or a confirmed no-setup) so a stable race.ini within one spawn is
  -- not re-parsed per frame. A new spawn/stint refreshes the cache via M.resetRaceIniCache() (#466 B1).
  raceIniSetupCache.key = key
  raceIniSetupCache.path = path or RACE_INI_NO_SETUP
  return path, false
end

--- Reset the per-spawn race.ini setup cache. The trainer calls this on a new session/stint (a real
--- car re-spawn) so a long-lived acs.exe that REUSES a Quick-Drive session index with a different
--- baked setup re-reads race.ini instead of serving the prior spawn's setup (#466 B1). Within one
--- spawn the cache holds — the applied setup is a spawn-time fact, so an in-place race.ini edit the
--- car has not re-read must not flap the archived setup, and resolution stays off the per-frame IO path.
function M.resetRaceIniCache()
  raceIniSetupCache.key = nil
  raceIniSetupCache.path = RACE_INI_NO_SETUP
end

---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@return string|nil
local function guessSetupIniPath(car, sim)
  if not car then
    return nil, false
  end
  local fromCar = activeSetupPathFromCar(car)
  if fromCar then
    return fromCar, false
  end
  -- The active setup baked/selected into race.ini beats a folder guess: it names the actual applied
  -- setup file (e.g. Realistic_BB_v3.ini), so the lap archive records that setup, not an empty snap.
  local fromRace, transient = activeSetupPathFromRaceIni(sim)
  if transient then
    -- race.ini momentarily missing/locked (#466 B2): archive nothing this call and retry rather
    -- than attributing a legacy folder guess (which can be the WRONG setup). NOT confirmed-no-setup,
    -- so callers keep the prior spawn's snapshot instead of clearing it.
    return nil, false
  end
  if fromRace == RACE_INI_NO_SETUP then
    return nil, true
  end
  if fromRace then
    return fromRace, false
  end
  -- fromRace == nil and not transient → vanilla `SETUP=` without `_EXT_SETUP_FILENAME`: fall through
  -- to the folder guess below (the intended resolution for a vanilla-selected setup).
  local doc = documentsRoot()
  if not doc then
    return nil, false
  end
  local carId = ch.sanitizeId(ch.safeCarIdRaw(), "unknown")
  -- Use CSP global API (C-structs throw on invalid field access, not nil).
  local trackId = ch.sanitizeId(ch.safeTrackIdRaw(), "unknown")
  local layoutRaw = ch.safeTrackLayoutRaw()
  local layoutId = layoutRaw ~= nil and ch.sanitizeId(layoutRaw, "") or ""
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
        return p, false
      end
    end
  end
  return trackRoot .. "/race.ini", false
end

--- Absolute path to the active setup INI (same resolution as `snapshotActive`).
--- The snapshot table stores only the basename in `path`; callers that need a
--- disk path for correlation (e.g. lap archive → Pocket Technician BEST) should
--- use this helper (chatgpt-codex P1 on PR #91).
---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@return string|nil
function M.activeSetupIniPath(car, sim)
  -- Deliberately SINGLE-valued: correlation callers (and their Lua tail-returns) treat the
  -- path as the whole result. Broadcast callers that also need the confirmed-no-setup flag
  -- use `activeSetupState` below.
  local path = guessSetupIniPath(car, sim)
  return path
end

--- Path + confirmed-no-setup flag for callers that BROADCAST the active setup (#531 /
--- PR #547): a cleared `setup.active` may be published only on a CONFIRMED race.ini
--- no-setup — a transient miss (race.ini locked / unresolvable) must publish nothing,
--- or a valid name would be wrongly wiped.
---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@return string|nil path
---@return boolean noSetupConfirmed
function M.activeSetupState(car, sim)
  local path, noSetupConfirmed = guessSetupIniPath(car, sim)
  return path, noSetupConfirmed == true
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
---@return boolean noSetupConfirmed true when race.ini was read and confirmed no applied setup
function M.snapshotActive(car, sim)
  local path, noSetupConfirmed = guessSetupIniPath(car, sim)
  local snap = M.readIniSnapshot(path)
  if not snap then
    return nil, "", noSetupConfirmed == true
  end
  return snap, digestSetup(canonicalSetupString(snap)), false
end

--- Part I: auto-load `copilot_*.ini` — CSP setup application APIs differ by build; try pcall hooks only.
---@param car ac.StateCar|nil
---@param sim ac.StateSim|nil
---@param autoLoad boolean|nil
---@return string|nil message
function M.tryAutoLoadCopilotSetup(_car, _sim, autoLoad)
  if autoLoad == false then
    return nil
  end
  -- Defer to future CSP API: physics.loadSetup, car.applySetup, etc.
  local okDoc, doc = pcall(function()
    return ac.getFolder(ac.FolderID.Documents)
  end)
  if not okDoc or not doc then
    return nil
  end
  local carId = ch.sanitizeId(ch.safeCarIdRaw(), "unknown")
  local trackId = ch.sanitizeId(ch.safeTrackIdRaw(), "unknown")
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
