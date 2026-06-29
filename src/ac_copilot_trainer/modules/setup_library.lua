-- Setup library (issue #86 Part D3).
--
-- Enumerate user setup INI files for the active car, load a setup by name
-- via `ac.loadSetup` (same call PT uses), and look up the best-archived
-- lap time for a given setup against the per-lap journal (PR #78 schema v1).
--
-- Pure adapter over `ac.*` + `io.scanDir` + per-lap JSON files. No HUD or
-- networking — the WS contract lives in `ac_copilot_trainer.lua` request
-- handlers, which call into this module.
--
-- Safety: this module does NOT enforce the in-pits gate. The caller in
-- the entry script wraps `M.loadByName` with a `ac.isCarResetAllowed()`
-- check before invoking it, so the gate is a single source of truth and
-- can be tested independently.

local M = {}

local ch = require("csp_helpers")
local persistence = require("persistence")  -- shares the journal/laps dir layout
local meta = require("ac_content_meta")    -- ui_car.json / ui_track.json reader
local setupReader = require("setup_reader") -- INI key harvest for per-row params

-- Re-list callbacks. Wired once on first use of M.list/loadByName so the
-- module works even if the entry script never calls a setup hook
-- explicitly. CSP's `ac.onSetupsListRefresh` fires when SX drops a new
-- file or AC reloads setups; we just bust the local cache.
local _cachedList = nil  -- {name, mtime, path}[] — invalidated by SetupsListRefresh
local _listCacheKey = nil ---@type string|nil  -- car/track/layout tuple; busts on session change
local _hookInstalled = false

local SPINNER_DEFS = {
  FRONT_BIAS = { label = "Brake bias", unit = "%", min = 40, max = 80, step = 1, order = 10 },
  ABS = { label = "ABS", unit = "", min = 0, max = 12, step = 1, order = 20 },
  TRACTION_CONTROL = { label = "TC", unit = "", min = 0, max = 12, step = 1, order = 30 },
  WING_1 = { label = "Front wing", unit = "", min = 0, max = 40, step = 1, order = 40 },
  WING_2 = { label = "Rear wing", unit = "", min = 0, max = 40, step = 1, order = 50 },
}

local function installRefreshHookOnce()
  if _hookInstalled then return end
  _hookInstalled = true
  if ac and type(ac.onSetupsListRefresh) == "function" then
    pcall(function()
      ac.onSetupsListRefresh(function()
        _cachedList = nil
        _listCacheKey = nil
      end)
    end)
  end
end

-- Same Documents/Assetto Corsa root that `setup_reader` uses, but
-- enumerated rather than guessed-at — `ac.getFolder(ac.FolderID.UserSetups)`
-- maps to `Documents/Assetto Corsa/setups/` on every CSP build we care
-- about (verified in csp-app-pocket-tech-setup-exchange-2026-04-21).
local function userSetupsRoot()
  if not (ac and type(ac.getFolder) == "function") then return nil end
  if not (ac.FolderID and ac.FolderID.UserSetups) then return nil end
  local ok, p = pcall(ac.getFolder, ac.FolderID.UserSetups)
  if not ok or type(p) ~= "string" or p == "" then return nil end
  return p
end

local function activeCarId()
  return ch.sanitizeId(ch.safeCarIdRaw(), "unknown")
end

local function activeTrackId()
  return ch.sanitizeId(ch.safeTrackIdRaw(), "unknown")
end

local function activeTrackLayoutId()
  local raw = ch.safeTrackLayoutRaw()
  if raw == nil then return "" end
  return ch.sanitizeId(raw, "")
end

-- Must sit *below* activeCarId/activeTrackId/activeTrackLayoutId so Lua 5.1
-- resolves locals, not globals (chatgpt-codex P1 on PR #91).
local function listCacheKey()
  return table.concat({
    activeCarId(),
    "\t",
    activeTrackId(),
    "\t",
    activeTrackLayoutId(),
  })
end

--- Enumerate setups for the current car AND track. Filenames have `.ini`
--- stripped. mtime comes from `io.fileModified` when CSP exposes it.
---
--- AC layout: `<UserSetups>/<carID>/<trackID>[/<layoutID>]/<name>.ini`. We
--- include:
---   * top-level `<carID>/<name>.ini` — global setups (no track tag)
---   * `<carID>/<trackID>/...` recursively — only the active track's folder
--- The previous "include every track's setups" pile was confusing on the
--- screen — picking a Spa setup at Monza wouldn't actually load right.
--- Filtering at the source keeps the screen list focused on what's drivable
--- right now.
---
---@return table[]   {name, mtime, path}[]
function M.list()
  installRefreshHookOnce()
  local key = listCacheKey()
  if _cachedList and _listCacheKey == key then
    return _cachedList
  end
  _cachedList = nil
  _listCacheKey = nil

  local out = {}
  local root = userSetupsRoot()
  if not root then return out end
  local carId = activeCarId()
  if not carId or carId == "unknown" then return out end
  local carDir = root .. "/" .. carId
  if not (io and type(io.scanDir) == "function") then return out end
  local trackId = activeTrackId()
  local hasTrack = trackId and trackId ~= "" and trackId ~= "unknown"

  local function tryAdd(filePath, baseName)
    if type(baseName) ~= "string" then return end
    if not baseName:lower():match("%.ini$") then return end
    local stem = baseName:sub(1, -5)  -- strip .ini
    local mtime
    if type(io.fileModified) == "function" then
      local okMt, m = pcall(io.fileModified, filePath)
      if okMt then mtime = tonumber(m) end
    end
    out[#out + 1] = {
      name = stem,
      mtime = mtime,
      path = filePath,
    }
  end

  -- Top-level setups in the car folder are always included (these are
  -- "global" not-yet-track-tagged setups; AC's own picker shows them too).
  local okTop, topList = pcall(io.scanDir, carDir, "*.ini")
  if okTop and type(topList) == "table" then
    for i = 1, #topList do
      tryAdd(carDir .. "/" .. topList[i], topList[i])
    end
  end
  -- Per-track folder for the ACTIVE track only — plus its layout subfolders.
  -- We don't want Spa setups showing in the list while driving Monza.
  if hasTrack then
    local function scanIniDir(dirPath)
      local okIni, iniList = pcall(io.scanDir, dirPath, "*.ini")
      if okIni and type(iniList) == "table" then
        for j = 1, #iniList do
          tryAdd(dirPath .. "/" .. iniList[j], iniList[j])
        end
      end
    end
    local trackDir = carDir .. "/" .. trackId
    scanIniDir(trackDir)
    -- Layout subfolders (track has multiple layouts, e.g. monza/junior).
    local okLay, layList = pcall(io.scanDir, trackDir)
    if okLay and type(layList) == "table" then
      for k = 1, #layList do
        local lay = layList[k]
        if type(lay) == "string" and not lay:match("%.") then
          scanIniDir(trackDir .. "/" .. lay)
        end
      end
    end
  end

  -- Sort newest-first by mtime, falling back to alpha.
  table.sort(out, function(a, b)
    local am = tonumber(a.mtime) or 0
    local bm = tonumber(b.mtime) or 0
    if am ~= bm then return am > bm end
    return tostring(a.name) < tostring(b.name)
  end)
  _cachedList = out
  _listCacheKey = key
  return out
end

--- Walk per-lap archive JSONs and find the fastest lap_ms for the given
--- setup name on the current car + track + layout combo. Returns nil if
--- no matching lap is on disk.
---
--- Per-lap files are written under `journal/laps/lap_<...>_<name>.json`
--- with body `{car:{id}, track:{id, layout?}, setup:{snapshot:{...}}, lap:{lap_ms}}`.
--- We use the SETUP NAME (not hash) for matching: the user's UI reads
--- "BEST under setup `aggressive`" rather than "BEST under hash 0xab12",
--- and naming-by-name happens to be exactly what the per-lap snapshot
--- stores in `setup.snapshot["NAME"]` if it was loaded by name. Since
--- the existing schema doesn't store the setup *name* as a top-level
--- field, we conservatively walk all files for the current car/track
--- and surface the fastest lap with a matching setup.snapshot.path.
---
--- Performance: O(N) over the journal, but typical sessions have <500
--- laps and the screen calls this per-row only when refreshing the list,
--- not per-frame. CSP exposes `io.scanDir` + `io.open`, both blocking.
---@param setupName string  basename without `.ini`
---@param setupPath string|nil  optional absolute path — when present, lap
---   records are matched on normalized full path first so two `race.ini`
---   files under different track folders cannot cross-contaminate BEST
---   (chatgpt-codex P2 on PR #91).
---@return integer|nil  fastest lap_ms, or nil
function M.bestForSetup(setupName, setupPath)
  if type(setupName) ~= "string" or setupName == "" then return nil end
  if type(setupPath) ~= "string" then setupPath = nil end
  if setupPath == "" then setupPath = nil end
  if not (io and type(io.scanDir) == "function") then return nil end

  local dir = persistence.dataDir() .. "/journal/laps"
  local files
  local ok = pcall(function()
    files = io.scanDir(dir, "lap_*.json")
  end)
  if not ok or type(files) ~= "table" or #files == 0 then return nil end

  local wantCar = activeCarId()
  local wantTrack = activeTrackId()
  local wantLayout = activeTrackLayoutId()
  local wantName = setupName:lower()
  local wantPathNorm ---@type string|nil
  if setupPath then
    wantPathNorm = setupPath:lower():gsub("\\", "/")
  end
  local best  ---@type integer|nil

  -- Avoid pulling JSON globally (CSP build dependent). Rely on `JSON.parse`
  -- the same way `lap_archive` does — falls through to nil if missing.
  local hasJson = (JSON and type(JSON.parse) == "function")
  if not hasJson then return nil end

  -- Filenames sort chronologically (see lap_archive.write —
  -- `lap_<UTC>_<sess>_<n>_<lap_ms>_<uuid>.json`), so alpha-descending ==
  -- time-descending. Scan the full journal so BEST is never truncated by an
  -- arbitrary cap (chatgpt-codex P2 on PR #91 — the prior 200-file limit
  -- could miss a faster older lap when the journal is large).
  table.sort(files, function(a, b) return tostring(a) > tostring(b) end)
  local maxScan = #files

  for i = 1, maxScan do
    local name = files[i]
    if type(name) == "string" then
      local path = dir .. "/" .. name
      local f = io.open(path, "r")
      if f then
        local raw = f:read("*a")
        f:close()
        if raw and #raw > 0 then
          local okParse, rec = pcall(JSON.parse, raw)
          if okParse and type(rec) == "table"
              and type(rec.lap) == "table"
              and type(rec.setup) == "table"
              and type(rec.car) == "table"
              and type(rec.track) == "table" then
            local lapMs = tonumber(rec.lap.lap_ms)
            local carOk = tostring(rec.car.id or ""):lower() == wantCar:lower()
            local trackOk = tostring(rec.track.id or ""):lower() == wantTrack:lower()
            -- Filter by layout when one is active (CodeRabbit on PR #91).
            -- A faster lap on a different layout (e.g. monza_junior vs
            -- monza) must NOT surface as BEST for the current layout. When
            -- the session has no layout, we accept any layout-tagged record
            -- (treat the layout filter as soft).
            local layoutOk = true
            if wantLayout ~= "" then
              local recLayout = tostring(rec.track.layout or ""):lower()
              -- Only reject when the archive *named* a different layout.
              -- `lap_archive` historically omits `track.layout` on many records;
              -- treating empty as non-match made BEST vanish for all layout
              -- sessions (codex P1 on PR #91).
              if recLayout ~= "" and recLayout ~= wantLayout:lower() then
                layoutOk = false
              end
            end
            -- The path comparison does not depend on snapshot CONTENTS, so
            -- check it outside the snapshot-table guard (Cursor on PR #91).
            -- Read both `setup.path` (current schema, written by lap_archive
            -- as of PR #91 follow-up) and `setup.snapshot.path` (legacy
            -- archives written before PR #91) so previously-saved laps still
            -- show their BEST after the schema bump.
            local snapPath
            if type(rec.setup.path) == "string" and rec.setup.path ~= "" then
              snapPath = rec.setup.path
            elseif type(rec.setup.snapshot) == "table"
                and type(rec.setup.snapshot.path) == "string"
                and rec.setup.snapshot.path ~= "" then
              snapPath = rec.setup.snapshot.path
            end
            local nameOk = false
            if snapPath then
              local lower = snapPath:lower():gsub("\\", "/")
              if wantPathNorm then
                -- Strict path match when the list row carried a disambiguator
                -- so `.../monza/race.ini` and `.../spa/race.ini` never share BEST.
                nameOk = (lower == wantPathNorm)
              else
                -- Basename-only when no path on the row (legacy / sparse archives).
                local base = lower:match("([^/]+)$") or lower
                base = base:gsub("%.ini$", "")
                if base == wantName then nameOk = true end
              end
            end
            if lapMs and lapMs > 0 and carOk and trackOk and layoutOk and nameOk
                and rec.lap.is_valid ~= false then
              if best == nil or lapMs < best then
                best = lapMs
              end
            end
          end
        end
      end
    end
  end

  return best
end

--- Load a setup. Returns `{ok:bool, name, message?, error?}` shaped like the
--- WS ack the screen consumes. Accepts either a basename (legacy) or a full
--- path; when both are provided the path wins (chatgpt-codex P1 on PR #91:
--- two setups with the same basename across track/layout folders used to
--- collide on first-match).
---
--- Caller MUST gate on `ac.isCarResetAllowed()` before invoking - see
--- the entry script's `setup.load` request handler. The gate is the
--- single source of truth so it can be unit-tested in one place.
---@param nameOrOpts string|table  basename, or { name=..., path=... }
---@return table  ack payload
function M.loadByName(nameOrOpts)
  local name, wantPath
  if type(nameOrOpts) == "table" then
    name = tostring(nameOrOpts.name or "")
    wantPath = nameOrOpts.path
    if type(wantPath) ~= "string" or wantPath == "" then wantPath = nil end
  else
    name = (type(nameOrOpts) == "string") and nameOrOpts or ""
  end
  if name == "" and not wantPath then
    return { ok = false, name = "", error = "empty name" }
  end
  installRefreshHookOnce()

  -- Resolve to a full path via the cached listing (busts on SetupsListRefresh).
  -- Path match wins over name when both are present so callers can carry the
  -- exact track/layout selection forward.
  local list = M.list()
  local match
  if wantPath then
    for i = 1, #list do
      if list[i].path == wantPath then match = list[i]; break end
    end
  end
  if not match and name ~= "" then
    for i = 1, #list do
      if list[i].name == name then match = list[i]; break end
    end
  end
  if not match then
    return { ok = false, name = name, error = "not found" }
  end

  local resolvedName = match.name

  if not (ac and type(ac.loadSetup) == "function") then
    return { ok = false, name = resolvedName, error = "ac.loadSetup unavailable" }
  end

  local okCall, loadRet = pcall(ac.loadSetup, match.path)
  if not okCall then
    return {
      ok = false,
      name = resolvedName,
      error = "loadSetup raised: " .. tostring(loadRet),
    }
  end
  -- CSP may return false/nil instead of throwing when a load is refused.
  -- Treat any non-truthy return as failure (Cursor Bugbot on PR #91).
  if loadRet == nil or loadRet == false then
    return {
      ok = false,
      name = resolvedName,
      error = "loadSetup refused or returned failure",
    }
  end
  -- Bust the cache so a follow-up `setup.list` re-reads BEST values that
  -- might now reference the freshly-loaded setup.
  _cachedList = nil
  _listCacheKey = nil
  return {
    ok = true,
    -- Echo the listing's canonical basename so path-only loads still surface
    -- a usable name for `setup.active` + UI correlation (codex P2 on PR #91).
    name = resolvedName,
    message = "loaded: " .. match.path,
    path = match.path,
  }
end

--- Lightweight track/car identity for the screen's meta bar — keeps the
--- entry script from having to plumb car/sim into the request handler.
--- Also supplies human-readable display names so the screen can show
--- "Porsche 911 GT3 R 2016" instead of "ks_porsche_911_gt3_r_2016".
---@return table  {car_id, car_name, track_id, track_name, layout_id}
function M.activeIdentity()
  local carId = activeCarId()
  local trackId = activeTrackId()
  local layoutId = activeTrackLayoutId()
  -- Read AC's ui_*.json directly. CSP `ac.getCarName` / `ac.getCarUIData`
  -- aren't exposed on every build; the file path is stable.
  local carUI = meta.carUI(carId)
  local trackUI = meta.trackUI(trackId, layoutId)
  return {
    car_id = carId,
    car_name = (carUI and carUI.name) or ch.carDisplayName() or carId,
    car_brand = (carUI and carUI.brand) or nil,
    car_class = (carUI and carUI.class) or nil,
    track_id = trackId,
    track_name = (trackUI and trackUI.name) or ch.trackDisplayName() or trackId,
    track_country = (trackUI and trackUI.country) or nil,
    layout_id = layoutId,
  }
end

--- Read a setup INI and return a small summary table the screen renders
--- under each row. Maps the AC section conventions verified against a real
--- ks_porsche_911_gt3_r_2016 setup file:
---   [FRONT_BIAS] VALUE=N         -> brake_bias (front bias %)
---   [ABS] VALUE=N                -> abs
---   [TRACTION_CONTROL] VALUE=N   -> tc
---   [WING_1] VALUE=N             -> wing_f (front wing or splitter)
---   [WING_2] VALUE=N             -> wing_r (rear wing angle)
--- Anything missing comes back nil so the screen leaves the chip out.
---@param iniPath string  absolute path to the .ini
---@return table  {brake_bias, abs, tc, wing_f, wing_r}
function M.summaryForSetup(iniPath)
  local snap = setupReader.readIniSnapshot(iniPath)
  if not snap or type(snap.keys) ~= "table" then
    return {}
  end
  local out = {}
  for i = 1, #snap.keys do
    local e = snap.keys[i]
    local sec = tostring(e.section or ""):upper()
    local key = tostring(e.key or ""):upper()
    if key == "VALUE" then
      if sec == "FRONT_BIAS" then
        out.brake_bias = tonumber(e.value)
      elseif sec == "ABS" then
        out.abs = tonumber(e.value)
      elseif sec == "TRACTION_CONTROL" then
        out.tc = tonumber(e.value)
      elseif sec == "WING_1" then
        out.wing_f = tonumber(e.value)
      elseif sec == "WING_2" then
        out.wing_r = tonumber(e.value)
      end
    end
  end
  return out
end

local function numberOrNil(v)
  local n = tonumber(v)
  if n == nil or n ~= n or n == math.huge or n == -math.huge then
    return nil
  end
  return n
end

local function normalizeSetupPath(p)
  if type(p) ~= "string" or p == "" or p:find("%z") then
    return nil
  end
  return p:gsub("\\", "/")
end

local function safeUserSetupPath(p)
  local norm = normalizeSetupPath(p)
  if not norm then
    return nil, "missing setup path"
  end
  local root = normalizeSetupPath(userSetupsRoot())
  if not root then
    return nil, "user setups folder unavailable"
  end
  root = root:gsub("/+$", "")
  local low = norm:lower()
  local rootLow = root:lower()
  if low ~= rootLow and low:sub(1, #rootLow + 1) ~= (rootLow .. "/") then
    return nil, "setup path outside user setups folder"
  end
  return norm, nil
end

local function activeSetupPath()
  local car, sim
  if ac and type(ac.getCar) == "function" then
    local okCar, c = pcall(ac.getCar, 0)
    if okCar then car = c end
  end
  if ac and type(ac.getSim) == "function" then
    local okSim, s = pcall(ac.getSim)
    if okSim then sim = s end
  end
  return setupReader.activeSetupIniPath(car, sim)
end

local function setupPathFromPayload(payload)
  local p
  if type(payload) == "table" and type(payload.path) == "string" and payload.path ~= "" then
    p = payload.path
  else
    p = activeSetupPath()
  end
  return safeUserSetupPath(p)
end

local function readTextFile(path)
  local f = io.open(path, "r")
  if not f then
    return nil, "setup file not found"
  end
  local text = f:read("*a")
  f:close()
  if type(text) ~= "string" then
    return nil, "setup file unreadable"
  end
  return text, nil
end

local function writeTextFile(path, text)
  local f = io.open(path, "w")
  if not f then
    return false, "setup file not writable"
  end
  local ok, err = pcall(function()
    f:write(text)
  end)
  f:close()
  if not ok then
    return false, tostring(err)
  end
  return true, nil
end

local function parseSetupIni(text)
  local newline = text:find("\r\n", 1, true) and "\r\n" or "\n"
  local hadTrailingNewline = text:sub(-1) == "\n"
  local source = hadTrailingNewline and text or (text .. "\n")
  local lines, order, sections = {}, {}, {}
  local current = nil
  for raw in source:gmatch("([^\n]*)\n") do
    local line = raw
    if line:sub(-1) == "\r" then line = line:sub(1, -2) end
    lines[#lines + 1] = line
    local sec = line:match("^%s*%[([^%]]+)%]%s*$")
    if sec then
      current = tostring(sec):upper()
      if not sections[current] then
        sections[current] = { fields = {}, field_lines = {} }
        order[#order + 1] = current
      end
    elseif current then
      local k, v = line:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
      if k then
        k = tostring(k):upper()
        sections[current].fields[k] = v
        sections[current].field_lines[k] = #lines
      end
    end
  end
  return {
    newline = newline,
    hadTrailingNewline = hadTrailingNewline,
    lines = lines,
    order = order,
    sections = sections,
  }
end

local function encodeSetupIni(parsed)
  local text = table.concat(parsed.lines, parsed.newline)
  if parsed.hadTrailingNewline then
    text = text .. parsed.newline
  end
  return text
end

local function labelForSection(section)
  local def = SPINNER_DEFS[section]
  if def and def.label then return def.label end
  local out = tostring(section or ""):lower():gsub("_", " ")
  return (out:gsub("(%a)([%w_']*)", function(a, b)
    return a:upper() .. b
  end))
end

local function spinnerFromSection(section, data)
  local value = numberOrNil(data.fields.VALUE)
  if value == nil then return nil end
  local def = SPINNER_DEFS[section] or {}
  local minV = numberOrNil(data.fields.MIN) or def.min
  local maxV = numberOrNil(data.fields.MAX) or def.max
  local step = numberOrNil(data.fields.STEP) or def.step or 1
  if step <= 0 then step = 1 end
  if minV == nil then minV = value - (10 * step) end
  if maxV == nil then maxV = value + (10 * step) end
  if maxV < minV then
    local tmp = minV
    minV = maxV
    maxV = tmp
  end
  return {
    name = section,
    section = section,
    label = labelForSection(section),
    value = value,
    min = minV,
    max = maxV,
    step = step,
    unit = def.unit or "",
    order = def.order or (1000 + #section),
  }
end

local function formatNumber(n)
  local rounded = math.floor(n + 0.5)
  if math.abs(n - rounded) < 0.000001 then
    return tostring(rounded)
  end
  local s = string.format("%.3f", n)
  s = s:gsub("0+$", ""):gsub("%.$", "")
  return s
end

local function snapToStep(value, minV, step)
  if not step or step <= 0 then return value end
  return minV + (math.floor(((value - minV) / step) + 0.5) * step)
end

--- List active setup spinner-style controls from the current user setup INI.
--- Returns `{ok=true,path,spinners=[{section,label,value,min,max,step,unit}]}`.
---@param payload table|nil
---@return table
function M.listSpinners(payload)
  local path, pathErr = setupPathFromPayload(payload)
  if not path then
    return { ok = false, error = pathErr or "setup path unavailable" }
  end
  local text, readErr = readTextFile(path)
  if not text then
    return { ok = false, path = path, error = readErr }
  end
  local parsed = parseSetupIni(text)
  local spinners = {}
  for _, section in ipairs(parsed.order) do
    local row = spinnerFromSection(section, parsed.sections[section])
    if row then
      row.order = nil
      spinners[#spinners + 1] = row
    end
  end
  table.sort(spinners, function(a, b)
    local ao = (SPINNER_DEFS[a.section] and SPINNER_DEFS[a.section].order) or 1000
    local bo = (SPINNER_DEFS[b.section] and SPINNER_DEFS[b.section].order) or 1000
    if ao ~= bo then return ao < bo end
    return tostring(a.label) < tostring(b.label)
  end)
  return { ok = true, path = path, spinners = spinners }
end

--- Set one active setup spinner value. The value is written to the user setup
--- INI and applied through `ac.loadSetup`; failed apply attempts restore the
--- previous file contents.
---@param payload table|nil
---@return table
function M.setSpinner(payload)
  if type(payload) ~= "table" then
    return { ok = false, error = "missing payload" }
  end
  local section = payload.section or payload.name
  if type(section) ~= "string" or section == "" then
    return { ok = false, error = "missing section" }
  end
  section = section:upper()
  if not section:match("^[A-Z0-9_]+$") then
    return { ok = false, section = section, error = "invalid section" }
  end
  local value = numberOrNil(payload.value)
  if value == nil then
    return { ok = false, section = section, error = "invalid value" }
  end
  local path, pathErr = setupPathFromPayload(payload)
  if not path then
    return { ok = false, section = section, value = value, error = pathErr or "setup path unavailable" }
  end
  local text, readErr = readTextFile(path)
  if not text then
    return { ok = false, path = path, section = section, value = value, error = readErr }
  end
  local parsed = parseSetupIni(text)
  local data = parsed.sections[section]
  if not data or not data.field_lines.VALUE then
    return { ok = false, path = path, section = section, value = value, error = "spinner not found" }
  end
  local spinner = spinnerFromSection(section, data)
  if not spinner then
    return { ok = false, path = path, section = section, value = value, error = "spinner value is not numeric" }
  end
  if value < spinner.min or value > spinner.max then
    return {
      ok = false,
      path = path,
      section = section,
      value = value,
      error = string.format("value out of range %.3f..%.3f", spinner.min, spinner.max),
    }
  end
  local appliedValue = snapToStep(value, spinner.min, spinner.step)
  if appliedValue < spinner.min then appliedValue = spinner.min end
  if appliedValue > spinner.max then appliedValue = spinner.max end

  local idx = data.field_lines.VALUE
  local prefix = parsed.lines[idx]:match("^(%s*[%w_]+%s*=%s*)") or "VALUE="
  parsed.lines[idx] = prefix .. formatNumber(appliedValue)
  local newText = encodeSetupIni(parsed)
  local okWrite, writeErr = writeTextFile(path, newText)
  if not okWrite then
    return { ok = false, path = path, section = section, value = appliedValue, error = writeErr }
  end
  if not (ac and type(ac.loadSetup) == "function") then
    writeTextFile(path, text)
    return { ok = false, path = path, section = section, value = appliedValue, error = "ac.loadSetup unavailable" }
  end
  local okLoad, loadRet = pcall(ac.loadSetup, path)
  if not okLoad or loadRet == nil or loadRet == false then
    writeTextFile(path, text)
    return {
      ok = false,
      path = path,
      section = section,
      value = appliedValue,
      error = okLoad and "loadSetup refused or returned failure" or ("loadSetup raised: " .. tostring(loadRet)),
    }
  end
  _cachedList = nil
  _listCacheKey = nil
  return {
    ok = true,
    path = path,
    section = section,
    name = section,
    label = spinner.label,
    value = appliedValue,
    min = spinner.min,
    max = spinner.max,
    step = spinner.step,
    unit = spinner.unit,
  }
end

return M
