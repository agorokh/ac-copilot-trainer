-- Project setup BEST metadata from bounded archive chunks. Telemetry is scanned
-- for framing and discarded, never retained or passed through JSON.parse.
local M = {}
local KEEP = { car = true, track = true, setup = true, lap = true }
local CHUNK_BYTES, MAX_METADATA_BYTES = 32768, 65536

local function project(readChunk)
  if not (JSON and type(JSON.parse) == "function") then return nil end
  local buffer, pos, capture, capturedBytes = "", 1, nil, 2
  local function consume(finish)
    if capture then
      capturedBytes = capturedBytes + finish - pos + 1
      if capturedBytes > MAX_METADATA_BYTES then error("metadata too large") end
      capture[#capture + 1] = buffer:sub(pos, finish)
    end
    pos = finish + 1
  end
  local function refill()
    if pos <= #buffer then return true end
    buffer, pos = readChunk() or "", 1
    return #buffer > 0
  end
  local function peek()
    return refill() and buffer:sub(pos, pos) or nil
  end
  local function nonspace()
    while refill() do
      local at = buffer:find('%S', pos)
      if at then consume(at - 1); return buffer:sub(pos, pos) end
      consume(#buffer)
    end
  end
  -- Plain searches run in C. Large numeric arrays have no structural tokens
  -- until their closing bracket; do not pattern-match each numeric character.
  local function nextToken(tokens)
    while refill() do
      local at
      for i = 1, #tokens do
        local found = buffer:find(tokens:sub(i, i), pos, true)
        if found and (not at or found < at) then at = found end
      end
      if at then consume(at - 1); return buffer:sub(pos, pos) end
      consume(#buffer)
    end
  end
  local function stringValue()
    consume(pos) -- opening quote
    while true do
      local token = nextToken('"\\')
      if not token then return false end
      consume(pos)
      if token == '"' then return true end
      if not peek() then return false end
      consume(pos) -- escaped character, possibly in the next chunk
    end
  end
  local function value()
    local first = peek()
    if first == '"' then return stringValue() end
    if first ~= "{" and first ~= "[" then return nextToken(',}') ~= nil end
    local stack = { first }
    consume(pos)
    while #stack > 0 do
      local token = nextToken('"[]{}')
      if not token then return false end
      if token == '"' then
        if not stringValue() then return false end
      else
        consume(pos)
        if token == "[" or token == "{" then stack[#stack + 1] = token
        else
          if stack[#stack] ~= (token == "}" and "{" or "[") then return false end
          stack[#stack] = nil
        end
      end
    end
    return true
  end
  if nonspace() ~= "{" then return nil end
  consume(pos)
  local fields = {}
  while nonspace() do
    if peek() ~= '"' then return nil end
    capture = {}
    if not stringValue() then return nil end
    local keyRaw = table.concat(capture)
    capture = nil
    local okKey, key = pcall(JSON.parse, keyRaw)
    if not okKey or type(key) ~= "string" or nonspace() ~= ":" then return nil end
    consume(pos)
    if not nonspace() then return nil end
    if KEEP[key] then capture = {} end
    if not value() then return nil end
    if capture then
      fields[#fields + 1] = keyRaw .. ":" .. table.concat(capture)
      capturedBytes = capturedBytes + 2 -- colon and separating comma
      if capturedBytes > MAX_METADATA_BYTES then return nil end
      capture = nil
    end
    local delimiter = nonspace()
    if delimiter == "}" then
      consume(pos)
      if nonspace() then return nil end
      local ok, record = pcall(JSON.parse, "{" .. table.concat(fields, ",") .. "}")
      return ok and type(record) == "table" and record or nil
    end
    if delimiter ~= "," then return nil end
    consume(pos)
  end
end

--- Project metadata; selected fields and root framing must be valid.
function M.parse(raw)
  if type(raw) ~= "string" then return nil end
  local pos = 1
  local ok, result = pcall(project, function()
    local chunk = raw:sub(pos, pos + CHUNK_BYTES - 1)
    pos = pos + CHUNK_BYTES
    return chunk
  end)
  return ok and result or nil
end

function M.read(path)
  local file = io.open(path, "rb")
  if not file then return nil end
  local ok, result = pcall(project, function() return file:read(CHUNK_BYTES) end)
  file:close()
  return ok and result or nil
end

return M
