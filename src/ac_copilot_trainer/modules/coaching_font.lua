-- Font system: multi-font DWriteFont support for polished panels (issue #57 Part C).
-- Extends the original single-font BMW resolver with named font roles.

local M = {}

-- ---------------------------------------------------------------------------
-- Cache / state
-- ---------------------------------------------------------------------------

local dwriteStr ---@type string|nil          -- legacy BMW fallback descriptor
local dwriteTried = false

local FONT_PT = 22                            -- legacy default point size

--- Named font descriptors resolved lazily.
--- Keys: "numbers" (Michroma / Consolas), "labels" (Montserrat / Segoe UI),
---        "brand" (Syncopate / Segoe UI), "legacy" (BMW.txt).
---@type table<string, string|false>
local namedCache = {}

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

---@param body string
---@return string|nil filename with extension
local function extractFontFilename(body)
  if not body then
    return nil
  end
  for line in body:gmatch("[^\r\n]+") do
    local trimmed = line:match("^%s*(.-)%s*$") or line
    local low = trimmed:lower()
    if low ~= "" and not low:match("^;") and not low:match("^#") then
      local eq = trimmed:match("=%s*(.+)$")
      local seg = eq or trimmed
      local fn = seg:match("([%w%s_%-%.]+%.[tT][tT][fF])")
        or seg:match("([%w%s_%-%.]+%.[oO][tT][fF])")
      if fn then
        return fn:match("^%s*(.-)%s*$") or fn
      end
    end
  end
  local fb = body:match("([%w%s_%-%.]+%.[tT][tT][fF])") or body:match("([%w%s_%-%.]+%.[oO][tT][fF])")
  if fb then
    return fb:match("^%s*(.-)%s*$") or fb
  end
  return nil
end

-- ---------------------------------------------------------------------------
-- Legacy BMW descriptor (backward compat)
-- ---------------------------------------------------------------------------

---@return string|nil @Descriptor string for ui.pushDWriteFont, or nil
function M.dwriteDescriptor()
  if dwriteTried then
    return dwriteStr
  end
  dwriteTried = true
  if not ac or type(ac.getFolder) ~= "function" or not ui or not ui.DWriteFont then
    return nil
  end
  local okRoot, root = pcall(function()
    return ac.getFolder(ac.FolderID.Root)
  end)
  if not okRoot or not root or root == "" then
    return nil
  end
  local dirSep = root:find("\\", 1, true) and "\\" or "/"
  local baseRoot = root:gsub("[\\/]+$", "")
  local path = baseRoot .. dirSep .. "content" .. dirSep .. "fonts" .. dirSep .. "bmw.txt"
  local f = io.open(path, "r")
  if not f then
    path = baseRoot .. dirSep .. "content" .. dirSep .. "fonts" .. dirSep .. "BMW.txt"
    f = io.open(path, "r")
  end
  if not f then
    return nil
  end
  local body = f:read("*a")
  f:close()
  if not body then
    return nil
  end
  local ttf = extractFontFilename(body)
  if not ttf then
    return nil
  end
  local base = ttf:gsub("%.[^.]+$", ""):gsub("^%s+", ""):gsub("%s+$", "")
  local ok, s = pcall(function()
    return tostring(ui.DWriteFont(base, "content/fonts"):allowRealSizes(true))
  end)
  if ok and type(s) == "string" and s ~= "" then
    dwriteStr = s
    return dwriteStr
  end
  return nil
end

-- ---------------------------------------------------------------------------
-- Named font resolution (Part C)
-- ---------------------------------------------------------------------------

--- Try to create a DWriteFont descriptor for a system-installed font.
--- Returns the descriptor string or nil.
---@param familyName string   e.g. "Michroma", "Montserrat", "Consolas"
---@return string|nil
local function trySystemFont(familyName)
  if not ui or not ui.DWriteFont then
    return nil
  end
  local ok, desc = pcall(function()
    return tostring(ui.DWriteFont(familyName):allowRealSizes(true))
  end)
  if ok and type(desc) == "string" and desc ~= "" then
    return desc
  end
  return nil
end

--- Resolve a named font role. Tries preferred fonts in order, falls back.
--- Results are cached per role name.
---@param role 'numbers'|'labels'|'brand'|'legacy'
---@return string|nil @DWriteFont descriptor or nil (use builtin fallback)
function M.namedDescriptor(role)
  if namedCache[role] ~= nil then
    local v = namedCache[role]
    return v ~= false and v or nil
  end

  local desc
  if role == "numbers" then
    -- Michroma (Google Font, motorsport display) -> Consolas -> BMW legacy
    desc = trySystemFont("Michroma")
      or trySystemFont("Consolas")
      or M.dwriteDescriptor()
  elseif role == "labels" then
    -- Montserrat (Google Font, clean labels) -> Segoe UI -> BMW legacy
    desc = trySystemFont("Montserrat")
      or trySystemFont("Segoe UI")
      or M.dwriteDescriptor()
  elseif role == "brand" then
    -- Syncopate (Google Font, branding) -> Segoe UI -> BMW legacy
    desc = trySystemFont("Syncopate")
      or trySystemFont("Segoe UI")
      or M.dwriteDescriptor()
  else
    desc = M.dwriteDescriptor()
  end

  namedCache[role] = desc or false
  return desc
end

-- ---------------------------------------------------------------------------
-- Push / pop (named)
-- ---------------------------------------------------------------------------

--- Push a named font at a given size. Returns a kind token for pop().
---@param role 'numbers'|'labels'|'brand'|nil  (nil = legacy)
---@param size number|nil  point size (default 22)
---@return "dwrite"|"builtin"|nil
function M.pushNamed(role, size)
  local pt = size or FONT_PT
  local desc = M.namedDescriptor(role or "legacy")
  if desc and type(ui.pushDWriteFont) == "function" then
    local ok = pcall(function()
      ui.pushDWriteFont(desc, pt)
    end)
    if ok then
      return "dwrite"
    end
    ok = pcall(function()
      ui.pushDWriteFont(desc)
    end)
    if ok then
      return "dwrite"
    end
  end
  if ui and ui.Font and type(ui.pushFont) == "function" then
    local ok = pcall(function()
      ui.pushFont(ui.Font.Title)
    end)
    if ok then
      return "builtin"
    end
  end
  return nil
end

-- ---------------------------------------------------------------------------
-- Legacy push / pop (backward compat)
-- ---------------------------------------------------------------------------

---@return "dwrite"|"builtin"|nil
function M.push()
  return M.pushNamed(nil, FONT_PT)
end

---@param kind "dwrite"|"builtin"|nil
function M.pop(kind)
  if kind == "dwrite" and type(ui.popDWriteFont) == "function" then
    pcall(ui.popDWriteFont)
  elseif kind == "builtin" and type(ui.popFont) == "function" then
    pcall(ui.popFont)
  end
end

return M
