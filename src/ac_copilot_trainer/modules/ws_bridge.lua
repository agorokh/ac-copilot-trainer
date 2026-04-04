-- Optional WebSocket to Python AI sidecar (issue #9 Part B, #45 protocol + inbound).
-- Safe no-op if CSP `web.socket` unavailable or socket has no receive API.

local M = {}

local sock ---@type any
local url ---@type string|nil
local RECONNECT_SEC = 5
local lastTry = -RECONNECT_SEC
local MAX_RECV_PER_TICK = 8
--- Sidecar WebSocket protocol version (must match Python `tools/ai_sidecar` v1 schema).
local PROTOCOL_VERSION = 1
M.PROTOCOL_VERSION = PROTOCOL_VERSION

--- Latest coaching_response waiting for application (lap index matches lapsCompleted).
local pendingCoaching ---@type { lap: number, hints: table[], debrief: string|nil }|nil

---@param u string|nil full ws URL, e.g. ws://127.0.0.1:8765
function M.configure(u)
  url = u
  sock = nil
  lastTry = -RECONNECT_SEC
  pendingCoaching = nil
end

--- Clear socket state (e.g. leaving track / new session). URL unchanged.
function M.reset()
  sock = nil
  lastTry = -RECONNECT_SEC
  pendingCoaching = nil
end

--- Drop queued sidecar response without closing the socket (e.g. lap counter reset).
function M.clearPendingCoaching()
  pendingCoaching = nil
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

local function jsonDecode(s)
  if type(s) ~= "string" or s == "" then
    return nil
  end
  if JSON and type(JSON.parse) == "function" then
    local ok, t = pcall(JSON.parse, s)
    if ok and type(t) == "table" then
      return t
    end
  end
  return nil
end

local function normalizeSidecarHints(hints)
  local out = {}
  if type(hints) ~= "table" then
    return out
  end
  for i = 1, #hints do
    if #out >= 3 then
      break
    end
    local h = hints[i]
    if type(h) == "string" and h ~= "" then
      out[#out + 1] = { kind = "general", text = h }
    elseif type(h) == "table" and type(h.text) == "string" and h.text ~= "" then
      local k = "general"
      if type(h.kind) == "string" and h.kind ~= "" then
        k = h.kind
      end
      out[#out + 1] = { kind = k, text = h.text }
    end
  end
  return out
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

--- Try to read one text frame; nil if none / unsupported / error (socket cleared on hard error).
local function tryRecvOne()
  if not sock then
    return nil
  end
  if type(sock.receive) ~= "function" and type(sock.read) ~= "function" and type(sock.recv) ~= "function" then
    return nil
  end
  local ok, res = pcall(function()
    if type(sock.receive) == "function" then
      return sock:receive()
    end
    if type(sock.read) == "function" then
      return sock:read()
    end
    return sock:recv()
  end)
  if not ok then
    sock = nil
    lastTry = -RECONNECT_SEC
    return nil
  end
  if type(res) == "string" and res ~= "" then
    return res
  end
  return nil
end

--- Drain up to `maxPerTick` inbound messages; queues `coaching_response` for `takeCoachingForLap`.
---@param maxPerTick number|nil
function M.pollInbound(maxPerTick)
  if not sock then
    return
  end
  local cap = tonumber(maxPerTick) or MAX_RECV_PER_TICK
  cap = math.max(1, math.min(32, math.floor(cap + 0.5)))
  for _ = 1, cap do
    local raw = tryRecvOne()
    if not raw then
      break
    end
    local data = jsonDecode(raw)
    if type(data) == "table" then
      local ev = data.event
      local pv = tonumber(data.protocol)
      if ev == "coaching_response" and pv == PROTOCOL_VERSION then
        local lap = tonumber(data.lap)
        local hints = data.hints
        if lap and type(hints) == "table" then
          local debrief ---@type string|nil
          if type(data.debrief) == "string" and data.debrief ~= "" then
            debrief = data.debrief
          end
          pendingCoaching = { lap = lap, hints = normalizeSidecarHints(hints), debrief = debrief }
        end
      end
    end
  end
end

--- If a sidecar response for `currentLapCompleted` is queued, consume and return hint list
--- and optional LLM/rules ``debrief`` paragraph (issue #46).
---@param currentLapCompleted number|nil
---@return table[]|nil, string|nil
function M.takeCoachingForLap(currentLapCompleted)
  local cur = tonumber(currentLapCompleted) or 0
  if not pendingCoaching then
    return nil, nil
  end
  if pendingCoaching.lap < cur then
    pendingCoaching = nil
    return nil, nil
  end
  if pendingCoaching.lap ~= cur then
    return nil, nil
  end
  local h = pendingCoaching.hints
  local d = pendingCoaching.debrief
  pendingCoaching = nil
  if h and #h > 0 then
    return h, d
  end
  return nil, d
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
  local sendOk = pcall(function()
    if sock.send then
      sock:send(js)
    elseif sock.write then
      sock:write(js)
    end
  end)
  if not sendOk then
    sock = nil
    lastTry = -RECONNECT_SEC
  end
end

return M
