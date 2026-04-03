-- Resolve BMW (or other) font from AC `content/fonts/*.txt` + DWriteFont (issue #41).

local M = {}

local dwriteStr ---@type string|nil
local dwriteTried = false

local FONT_PT = 22

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
      local fn = seg:match("([%w_%-]+%.[tT][tT][fF])") or seg:match("([%w_%-]+%.[oO][tT][fF])")
      if fn then
        return fn
      end
    end
  end
  return body:match("([%w_%-]+%.[tT][tT][fF])") or body:match("([%w_%-]+%.[oO][tT][fF])")
end

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
  local sep = root:match("[\\/]$") and "" or (root:find("\\") and "\\" or "/")
  local path = root .. sep .. "content" .. sep .. "fonts" .. sep .. "bmw.txt"
  local f = io.open(path, "r")
  if not f then
    path = root .. sep .. "content" .. sep .. "fonts" .. sep .. "BMW.txt"
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

---@return string|nil kind: "dwrite" | "builtin"
function M.push()
  local fs = M.dwriteDescriptor()
  if fs and type(ui.pushDWriteFont) == "function" then
    local ok = pcall(function()
      ui.pushDWriteFont(fs, FONT_PT)
    end)
    if ok then
      return "dwrite"
    end
    ok = pcall(function()
      ui.pushDWriteFont(fs)
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

---@param kind string|nil
function M.pop(kind)
  if kind == "dwrite" and type(ui.popDWriteFont) == "function" then
    pcall(ui.popDWriteFont)
  elseif kind == "builtin" and type(ui.popFont) == "function" then
    pcall(ui.popFont)
  end
end

return M
