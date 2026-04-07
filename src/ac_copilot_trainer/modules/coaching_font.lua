-- Font system: bundled DWriteFont references via inline-path syntax (issue #72).
-- Pattern lifted from CMRT-Essential-HUD/common/settings.lua: construct each
-- DWriteFont once at module load with `Family:/content/fonts;Weight=...` so the
-- file is resolved against the script root. CSP serves the bundled .ttf files
-- from src/ac_copilot_trainer/content/fonts/ — no system-font fallback needed.

local M = {}

-- ---------------------------------------------------------------------------
-- Bundled font references (constructed once, reused every frame).
-- The :/content/fonts segment is a CSP shorthand for "directory under the
-- running script's root". Each font name maps to a real .ttf inside that dir.
-- ---------------------------------------------------------------------------

local function safeDWrite(spec)
  if type(ui) ~= "table" or type(ui.DWriteFont) ~= "function" then
    return nil
  end
  local ok, font = pcall(function()
    return ui.DWriteFont(spec)
  end)
  if ok and font then
    return font
  end
  return nil
end

--- Bundled font cache. Built lazily on first access so test stubs that don't
--- supply ui.DWriteFont don't crash.
local cache = nil

local function loadCache()
  if cache then
    return cache
  end
  cache = {
    -- Michroma — display/numbers font (corner labels, big speed numbers)
    michroma = safeDWrite("Michroma:/content/fonts"),
    -- Montserrat — UI labels (regular and bold weights)
    montserrat = safeDWrite("Montserrat:/content/fonts;Weight=Regular"),
    montserrat_bold = safeDWrite("Montserrat:/content/fonts;Weight=Bold"),
    -- Syncopate — Porsche-style brand wordmark in the footer
    syncopate_bold = safeDWrite("Syncopate:/content/fonts;Weight=Bold"),
  }
  return cache
end

-- ---------------------------------------------------------------------------
-- Public API
-- ---------------------------------------------------------------------------

--- Font handles for use with `ui.pushDWriteFont(...)` and
--- `ui.dwriteDrawText(...)`. Returns the cached table.
---@return table
function M.fonts()
  return loadCache()
end

--- Push a named font onto the DWriteFont stack. Pair with `M.pop()`. Returns
--- a token that should be passed to `M.pop()` so unsupported builds don't
--- accidentally pop something they didn't push.
---@param role 'numbers'|'labels'|'labels_bold'|'brand'|'legacy'|nil
---@return string|nil token
function M.pushNamed(role, _size)
  if type(ui) ~= "table" or type(ui.pushDWriteFont) ~= "function" then
    return nil
  end
  local fonts = loadCache()
  local font
  if role == "numbers" then
    font = fonts.michroma
  elseif role == "labels" then
    font = fonts.montserrat
  elseif role == "labels_bold" then
    font = fonts.montserrat_bold
  elseif role == "brand" then
    font = fonts.syncopate_bold
  else
    font = fonts.michroma
  end
  if not font then
    return nil
  end
  local ok = pcall(function()
    ui.pushDWriteFont(font)
  end)
  if not ok then
    return nil
  end
  return "dwrite"
end

---@param token string|nil
function M.pop(token)
  if token == "dwrite" and type(ui) == "table" and type(ui.popDWriteFont) == "function" then
    pcall(ui.popDWriteFont)
  end
end

-- Backward-compat shims (some legacy code paths call .push() / .dwriteDescriptor()).
function M.push()
  return M.pushNamed("numbers")
end

function M.namedDescriptor(role)
  local fonts = loadCache()
  if role == "labels" then
    return fonts.montserrat
  elseif role == "labels_bold" then
    return fonts.montserrat_bold
  elseif role == "brand" then
    return fonts.syncopate_bold
  end
  return fonts.michroma
end

function M.dwriteDescriptor()
  return loadCache().michroma
end

return M
