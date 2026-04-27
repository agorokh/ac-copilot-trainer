-- AC content-metadata reader: parses `ui_car.json` and `ui_track.json`
-- straight off disk so we get human-readable names + brand even on CSP
-- builds where `ac.getCarName` / `ac.getCarUIData` aren't exposed.
--
-- Cached once per (carId / trackId) — ui files don't change during a
-- session. Returns nil entries on any read/parse failure; callers fall
-- back to the directory ID.

local M = {}

local _carCache = {}    -- carId -> {name=, brand=, class=}
local _trackCache = {}  -- "trackId" or "trackId/layoutId" -> {name=, country=}

-- ----------------------------------------------------------------------------
-- AC root resolution. We try several FolderID names in order; whichever the
-- current CSP build exposes wins. If none work, fall back to the registry-
-- style guess derived from the UserSetups path's neighbour.
local function tryFolder(name)
  if not (ac and type(ac.getFolder) == "function") then return nil end
  if not (ac.FolderID and ac.FolderID[name]) then return nil end
  local ok, p = pcall(ac.getFolder, ac.FolderID[name])
  if ok and type(p) == "string" and p ~= "" then return p end
  return nil
end

local function acRoot()
  -- Most likely names across CSP versions.
  for _, name in ipairs({ "Root", "ACRoot", "ACMain", "ACInstall", "Game" }) do
    local p = tryFolder(name)
    if p then return p end
  end
  -- Direct content-folder IDs let us short-circuit (we'll branch on these
  -- in carUiPath / trackUiPath if root is nil).
  return nil
end

local function carContentRoot()
  local r = tryFolder("ContentCars")
  if r then return r end
  local root = acRoot()
  if root then return root .. "/content/cars" end
  return nil
end

local function trackContentRoot()
  local r = tryFolder("ContentTracks")
  if r then return r end
  local root = acRoot()
  if root then return root .. "/content/tracks" end
  return nil
end

-- ----------------------------------------------------------------------------
local function parseJson(text)
  if not text or text == "" then return nil end
  if not (JSON and type(JSON.parse) == "function") then return nil end
  -- Strip UTF-8 BOM (AC ui_*.json sometimes has one) before handing to JSON.
  if text:byte(1) == 0xEF and text:byte(2) == 0xBB and text:byte(3) == 0xBF then
    text = text:sub(4)
  end
  local ok, t = pcall(JSON.parse, text)
  if ok and type(t) == "table" then return t end
  return nil
end

local function readFile(path)
  if type(path) ~= "string" or path == "" then return nil end
  local f = io.open(path, "rb")
  if not f then return nil end
  local s = f:read("*a")
  f:close()
  return s
end

-- ----------------------------------------------------------------------------
--- Load the parsed `ui_car.json` for carId. Cached.
---@param carId string
---@return table|nil  {name, brand, class} (any may be missing) or nil on failure
function M.carUI(carId)
  if type(carId) ~= "string" or carId == "" or carId == "unknown" then return nil end
  local cached = _carCache[carId]
  if cached ~= nil then return cached end
  _carCache[carId] = false  -- negative-cache while we try
  local root = carContentRoot()
  if not root then return nil end
  local raw = readFile(root .. "/" .. carId .. "/ui/ui_car.json")
  local d = parseJson(raw)
  if not d then return nil end
  local out = {
    name  = (type(d.name)  == "string" and d.name  ~= "") and d.name  or nil,
    brand = (type(d.brand) == "string" and d.brand ~= "") and d.brand or nil,
    class = (type(d.class) == "string" and d.class ~= "") and d.class or nil,
  }
  _carCache[carId] = out
  return out
end

--- Load the parsed `ui_track.json` for trackId (and optional layoutId).
---@param trackId string
---@param layoutId string|nil
---@return table|nil  {name, country} or nil on failure
function M.trackUI(trackId, layoutId)
  if type(trackId) ~= "string" or trackId == "" or trackId == "unknown" then return nil end
  local key = (layoutId and layoutId ~= "") and (trackId .. "/" .. layoutId) or trackId
  local cached = _trackCache[key]
  if cached ~= nil then return cached end
  _trackCache[key] = false  -- negative-cache while we try
  local root = trackContentRoot()
  if not root then return nil end
  -- Layout-specific ui_track.json wins when present, otherwise fall back to
  -- the track-root one.
  local candidates = {}
  if layoutId and layoutId ~= "" then
    candidates[#candidates + 1] = root .. "/" .. trackId .. "/" .. layoutId .. "/ui/ui_track.json"
  end
  candidates[#candidates + 1] = root .. "/" .. trackId .. "/ui/ui_track.json"
  for i = 1, #candidates do
    local d = parseJson(readFile(candidates[i]))
    if d then
      local out = {
        name    = (type(d.name)    == "string" and d.name    ~= "") and d.name    or nil,
        country = (type(d.country) == "string" and d.country ~= "") and d.country or nil,
      }
      _trackCache[key] = out
      return out
    end
  end
  return nil
end

--- Convenience: car display name (full, includes brand). Empty string if missing.
function M.carDisplayName(carId)
  local d = M.carUI(carId)
  return (d and d.name) or ""
end

function M.carBrand(carId)
  local d = M.carUI(carId)
  return (d and d.brand) or ""
end

function M.trackDisplayName(trackId, layoutId)
  local d = M.trackUI(trackId, layoutId)
  return (d and d.name) or ""
end

return M
