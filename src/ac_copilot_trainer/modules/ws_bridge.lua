-- Optional WebSocket to Python AI sidecar (issue #9 Part B). Safe no-op if CSP `web.socket` unavailable.

local M = {}

local sock ---@type any
local url ---@type string|nil
local lastTry = 0
local RECONNECT_SEC = 5

---@param u string|nil full ws URL, e.g. ws://127.0.0.1:8765
function M.configure(u)
  url = u
  sock = nil
end

local function jsonEncode(t)
  if JSON and type(JSON.stringify) == "function" then
    local ok, s = pcall(JSON.stringify, t, false)
    if ok and type(s) == "string" then
      return s
    end
  end
  return nil
end

local function tryOpen()
  if not url or url == "" then
    return false
  end
  if not web or type(web.socket) ~= "function" then
    return false
  end
  local ok, s = pcall(function()
    return web.socket(url)
  end)
  if ok and s ~= nil then
    sock = s
    return true
  end
  sock = nil
  return false
end

---@param simTime number|nil
function M.tick(simTime)
  if not url or url == "" then
    return
  end
  local t = simTime or 0
  if sock then
    return
  end
  if t - lastTry < RECONNECT_SEC then
    return
  end
  lastTry = t
  tryOpen()
end

---@param payload table|nil
function M.sendJson(payload)
  if not payload then
    return
  end
  local js = jsonEncode(payload)
  if not js or not sock then
    return
  end
  pcall(function()
    if sock.send then
      sock:send(js)
    elseif sock.write then
      sock:write(js)
    end
  end)
end

return M
