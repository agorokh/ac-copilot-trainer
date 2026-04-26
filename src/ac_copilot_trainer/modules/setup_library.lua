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

-- Re-list callbacks. Wired once on first use of M.list/loadByName so the
-- module works even if the entry script never calls a setup hook
-- explicitly. CSP's `ac.onSetupsListRefresh` fires when SX drops a new
-- file or AC reloads setups; we just bust the local cache.
local _cachedList = nil  -- {name, mtime, path}[] — invalidated by SetupsListRefresh
local _hookInstalled = false

local function installRefreshHookOnce()
  if _hookInstalled then return end
  _hookInstalled = true
  if ac and type(ac.onSetupsListRefresh) == "function" then
    pcall(function()
      ac.onSetupsListRefresh(function() _cachedList = nil end)
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

--- Enumerate setups for the current car. Filenames have `.ini` stripped
--- before being returned. mtime comes from `io.fileModified` when CSP
--- exposes it; otherwise nil (the screen renders "—" in that case).
---
--- AC layout note: setups live at
---   `<UserSetups>/<carID>/<trackID>[/<layoutID>]/<name>.ini`
--- but we only care about the per-car bucket since AC's own setup picker
--- folds track/layout into a single list (which is also how PT/SX surface
--- them). We scan recursively two levels deep so layouts come along.
---
---@return table[]   {name, mtime, path}[]
function M.list()
  installRefreshHookOnce()
  if _cachedList then return _cachedList end

  local out = {}
  local root = userSetupsRoot()
  if not root then return out end
  local carId = activeCarId()
  if not carId or carId == "unknown" then return out end
  local carDir = root .. "/" .. carId
  if not (io and type(io.scanDir) == "function") then return out end

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

  -- Top-level (some users keep flat per-car setups).
  local okTop, topList = pcall(io.scanDir, carDir, "*.ini")
  if okTop and type(topList) == "table" then
    for i = 1, #topList do
      tryAdd(carDir .. "/" .. topList[i], topList[i])
    end
  end
  -- Per-track sub-directories.
  local okSubs, subDirs = pcall(io.scanDir, carDir)
  if okSubs and type(subDirs) == "table" then
    for i = 1, #subDirs do
      local sub = subDirs[i]
      if type(sub) == "string" and not sub:match("%.") then
        local subPath = carDir .. "/" .. sub
        local okIni, iniList = pcall(io.scanDir, subPath, "*.ini")
        if okIni and type(iniList) == "table" then
          for j = 1, #iniList do
            tryAdd(subPath .. "/" .. iniList[j], iniList[j])
          end
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
---@return integer|nil  fastest lap_ms, or nil
function M.bestForSetup(setupName)
  if type(setupName) ~= "string" or setupName == "" then return nil end
  if not (io and type(io.scanDir) == "function") then return nil end

  local dir = persistence.dataDir() .. "/journal/laps"
  local files
  local ok = pcall(function()
    files = io.scanDir(dir, "lap_*.json")
  end)
  if not ok or type(files) ~= "table" or #files == 0 then return nil end

  local wantCar = activeCarId()
  local wantTrack = activeTrackId()
  local wantName = setupName:lower()
  local best  ---@type integer|nil

  -- Avoid pulling JSON globally (CSP build dependent). Rely on `JSON.parse`
  -- the same way `lap_archive` does — falls through to nil if missing.
  local hasJson = (JSON and type(JSON.parse) == "function")
  if not hasJson then return nil end

  -- Cap walk to first 200 most recent files so this is bounded for users
  -- with multi-thousand-lap journals. Filenames sort chronologically (see
  -- lap_archive.write — `lap_<UTC>_<sess>_<n>_<lap_ms>_<uuid>.json`), so
  -- alpha-descending == time-descending.
  table.sort(files, function(a, b) return tostring(a) > tostring(b) end)
  local maxScan = math.min(#files, 200)

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
            local snap = rec.setup.snapshot
            local nameOk = false
            if type(snap) == "table" then
              -- The lap-archive flatten format keys snapshot entries as
              -- "SECTION.KEY" with no top-level setup name. Until the
              -- schema is extended to record the setup name, we look at
              -- the legacy `path` field on the same record (set by
              -- `setup_reader.readIniSnapshot`) which IS the basename.
              local snapPath = nil
              if rec.setup.path then snapPath = tostring(rec.setup.path) end
              if snapPath and snapPath:lower():gsub("%.ini$", "") == wantName then
                nameOk = true
              end
            end
            if lapMs and lapMs > 0 and carOk and trackOk and nameOk
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

--- Load a setup by basename (no `.ini`). Returns `{ok:bool, name, message?, error?}`
--- shaped like the WS ack the screen consumes.
---
--- Caller MUST gate on `ac.isCarResetAllowed()` before invoking — see
--- the entry script's `setup.load` request handler. The gate is the
--- single source of truth so it can be unit-tested in one place.
---@param name string
---@return table  ack payload
function M.loadByName(name)
  if type(name) ~= "string" or name == "" then
    return { ok = false, name = name or "", error = "empty name" }
  end
  installRefreshHookOnce()

  -- Resolve to a full path via the cached listing (busts on SetupsListRefresh).
  local list = M.list()
  local match
  for i = 1, #list do
    if list[i].name == name then
      match = list[i]
      break
    end
  end
  if not match then
    return { ok = false, name = name, error = "not found" }
  end

  if not (ac and type(ac.loadSetup) == "function") then
    return { ok = false, name = name, error = "ac.loadSetup unavailable" }
  end

  local okCall, err = pcall(ac.loadSetup, match.path)
  if not okCall then
    return { ok = false, name = name, error = "loadSetup raised: " .. tostring(err) }
  end
  -- Bust the cache so a follow-up `setup.list` re-reads BEST values that
  -- might now reference the freshly-loaded setup.
  _cachedList = nil
  return {
    ok = true,
    name = name,
    message = "loaded: " .. match.path,
    path = match.path,
  }
end

--- Lightweight track/car identity for the screen's meta bar — keeps the
--- entry script from having to plumb car/sim into the request handler.
---@return table  {car_id, track_id, layout_id}
function M.activeIdentity()
  return {
    car_id = activeCarId(),
    track_id = activeTrackId(),
    layout_id = activeTrackLayoutId(),
  }
end

return M
