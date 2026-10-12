-- Read setup/lap identity without sending telemetry samples through CSP's
-- decimal parser. Archive keys are unordered, so project at the JSON root.
local M = {}

local KEEP = { car = true, track = true, setup = true, lap = true }
local MAX_METADATA_BYTES = 65536

local function stringEnd(raw, pos)
  while true do
    local nextPos = raw:find('["\\]', pos + 1)
    if not nextPos then return nil end
    if raw:sub(nextPos, nextPos) == '"' then return nextPos end
    pos = nextPos + 1 -- skip the escaped character, including escaped quotes
  end
end

local function valueEnd(raw, pos)
  local first = raw:sub(pos, pos)
  if first == '"' then return stringEnd(raw, pos) end
  if first ~= "{" and first ~= "[" then
    local delimiter = raw:find('[,}]', pos)
    return delimiter and delimiter - 1 or nil
  end
  local stack = { first }
  while #stack > 0 do
    local nextPos = raw:find('["%[%]{}]', pos + 1)
    if not nextPos then return nil end
    local token = raw:sub(nextPos, nextPos)
    if token == '"' then
      nextPos = stringEnd(raw, nextPos)
      if not nextPos then return nil end
    elseif token == "{" or token == "[" then
      stack[#stack + 1] = token
    else
      local expected = token == "}" and "{" or "["
      if stack[#stack] ~= expected then return nil end
      stack[#stack] = nil
    end
    pos = nextPos
  end
  return pos
end

--- Project only metadata; sample values are not decoded or validated here.
--- Broken framing fails closed. JSON.parse still validates selected fields.
---@param raw string
---@return table|nil
function M.parse(raw)
  if type(raw) ~= "string" or not (JSON and type(JSON.parse) == "function") then return nil end
  local pos = raw:find('%S')
  if not pos or raw:sub(pos, pos) ~= "{" then return nil end
  pos = raw:find('%S', pos + 1)
  local fields, bytes = {}, 2
  if pos and raw:sub(pos, pos) == "}" then return nil end
  while pos do
    if raw:sub(pos, pos) ~= '"' then return nil end
    local keyEnd = stringEnd(raw, pos)
    if not keyEnd then return nil end
    local keyRaw = raw:sub(pos, keyEnd)
    local okKey, key = pcall(JSON.parse, keyRaw)
    if not okKey or type(key) ~= "string" then return nil end
    local colon = raw:find('%S', keyEnd + 1)
    if not colon or raw:sub(colon, colon) ~= ":" then return nil end
    local valueStart = raw:find('%S', colon + 1)
    if not valueStart then return nil end
    local finish = valueEnd(raw, valueStart)
    if not finish or finish < valueStart then return nil end
    if KEEP[key] then
      bytes = bytes + #keyRaw + finish - valueStart + 3
      if bytes > MAX_METADATA_BYTES then return nil end
      fields[#fields + 1] = keyRaw .. ":" .. raw:sub(valueStart, finish)
    end
    pos = raw:find('%S', finish + 1)
    if not pos then return nil end
    local delimiter = raw:sub(pos, pos)
    if delimiter == "}" then
      if raw:find('%S', pos + 1) then return nil end
      local ok, record = pcall(JSON.parse, "{" .. table.concat(fields, ",") .. "}")
      return ok and type(record) == "table" and record or nil
    end
    if delimiter ~= "," then return nil end
    pos = raw:find('%S', pos + 1)
  end
  return nil
end

---@param path string
---@return table|nil
function M.read(path)
  local file = io.open(path, "rb")
  if not file then return nil end
  local ok, raw = pcall(function() return file:read("*a") end)
  file:close()
  return ok and M.parse(raw) or nil
end

return M
