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

--- Round 10: per-corner LLM advisories keyed by corner label.
--- Populated by pollInbound when corner_advice events arrive.
local cornerAdvisories = {}  ---@type table<string, { lap: number, text: string, ts: number }>
--- Round 10d: wall-clock reference updated via M.tick(simT). Replaces
--- os.clock() which is process CPU time (advances too slowly for a
--- low-CPU Lua script, so the 6s staleness expiry never triggered).
local currentSimT = 0
--- Per-corner last-query timestamp (unused after round 10c moved the
--- debounce to realtime_coaching; kept for backward compat with M.reset).
local lastCornerQueryAt = {}  ---@type table<string, number>

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
  cornerAdvisories = {}
  lastCornerQueryAt = {}
  currentSimT = 0
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

local _wsDiagLogged = false
local _wsDiagAttempts = 0
local _recvQueue = {}  -- CSP web.socket is callback-based; messages land here

local function _logWsDiagOnce(stage, extra)
  if _wsDiagLogged then return end
  _wsDiagLogged = true
  if not (ac and type(ac.log) == "function") then return end
  ac.log(string.format(
    "[COPILOT][WS-DIAG] stage=%s url=%s web=%s web.socket=%s extra=%s",
    tostring(stage),
    tostring(url),
    type(web),
    (type(web) == "table" and tostring(web.socket)) or "missing",
    tostring(extra or "")
  ))
end

--- CSP web.socket callback: invoked when a message arrives from the server.
--- Round 8: log EVERY recv so we can see exactly what comes back and when.
local _recvCount = 0
local function _onRecv(data)
  _recvCount = _recvCount + 1
  local preview = ""
  local bytes = 0
  if type(data) == "string" then
    bytes = #data
    preview = data:sub(1, 120)
  elseif type(data) == "table" then
    preview = "<binary table>"
  else
    preview = "<" .. type(data) .. ">"
  end
  if ac and type(ac.log) == "function" then
    ac.log(string.format("[COPILOT][WS-RECV] #%d (%d bytes) %s",
      _recvCount, bytes, preview))
  end
  if type(data) == "string" and data ~= "" then
    _recvQueue[#_recvQueue + 1] = data
  end
end

local function _onError(err)
  if ac and type(ac.log) == "function" then
    ac.log("[COPILOT][WS-DIAG] socket error: " .. tostring(err))
  end
  -- Round 8: DO NOT clear sock here. With reconnect:true, CSP auto-retries
  -- and onClose only fires when we explicitly call sock:close(). Clearing
  -- sock in onError would drop the reference mid-reconnect.
end

local function _onClose(reason)
  if ac and type(ac.log) == "function" then
    ac.log("[COPILOT][WS-DIAG] socket closed: " .. tostring(reason))
  end
  sock = nil
  lastTry = -RECONNECT_SEC
end

--- Open a WebSocket using CSP's callback-based API.
---
--- CSP signature (from lua-sdk/ac_apps/lib.lua):
---   web.socket(url, headers?, callback, params?) -> web.Socket
--- with overload
---   web.socket(url, callback, params) -> web.Socket
---
--- The returned socket is a polymorphic {close: fun()}|fun(data: binary) --
--- call it as a function to SEND, call :close() to close. Inbound messages
--- are pushed to the callback, NOT pulled via receive(). Issue #75 round 6:
--- our old implementation used the wrong API (no callback passed, sock:send /
--- sock:receive), which produced "Callback should be a function" on tryOpen.
local function tryOpen()
  _wsDiagAttempts = _wsDiagAttempts + 1
  if not url or url == "" then
    _logWsDiagOnce("empty-url")
    return false
  end
  if not web or type(web) ~= "table" then
    _logWsDiagOnce("no-web-table")
    return false
  end
  if web.socket == nil then
    _logWsDiagOnce("no-web-socket")
    return false
  end
  _recvQueue = {}
  local params = {
    onError = _onError,
    onClose = _onClose,
    encoding = "utf8",
    -- Round 8: reconnect=true. Per SDK doc, onClose only fires on explicit
    -- sock:close() with this flag, so CSP auto-reconnects on transient drops
    -- and keeps the callback reference alive across blips.
    reconnect = true,
  }
  local ok, s = pcall(function()
    -- 3-arg overload: (url, callback, params)
    return web.socket(url, _onRecv, params)
  end)
  if ok and s ~= nil then
    sock = s
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT][WS-DIAG] CONNECTED url=" .. tostring(url) .. " attempts=" .. tostring(_wsDiagAttempts))
    end
    return true
  end
  if ac and type(ac.log) == "function" then
    ac.log(string.format(
      "[COPILOT][WS-DIAG] tryOpen failed url=%s ok=%s err=%s attempts=%d",
      tostring(url), tostring(ok), tostring(s), _wsDiagAttempts
    ))
  end
  sock = nil
  return false
end

--- Drain one queued message from the callback queue. Nil if empty.
--- Issue #75 round 6: CSP web.socket pushes messages via the callback passed
--- at socket construction time -- there is NO pull-based receive().
local function tryRecvOne()
  if #_recvQueue == 0 then
    return nil
  end
  return table.remove(_recvQueue, 1)
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
        local source = tostring(data.debriefSource or "")
        if lap and type(hints) == "table" then
          local debrief ---@type string|nil
          if type(data.debrief) == "string" and data.debrief ~= "" then
            debrief = data.debrief
          end
          if source == "ollama" then
            if pendingCoaching and pendingCoaching.lap == lap then
              -- Round 8: Ollama follow-up overwrites the rules debrief with
              -- the LLM version. Hints are preserved from the immediate
              -- response (which has the richer rules-engine hints).
              pendingCoaching.debrief = debrief or pendingCoaching.debrief
              if ac and type(ac.log) == "function" then
                ac.log("[COPILOT][WS-DIAG] ollama follow-up applied for lap " .. tostring(lap))
              end
            elseif debrief and not pendingCoaching then
              -- Late Ollama debrief after the immediate payload was consumed:
              -- surface prose only — do not queue placeholder hints that would
              -- replace rules-engine lines in the HUD. Never clobber a pending
              -- payload for a newer lap with a stale follow-up for an older lap.
              pendingCoaching = {
                lap = lap,
                hints = {},
                debrief = debrief,
              }
            end
          else
            pendingCoaching = {
              lap = lap,
              hints = normalizeSidecarHints(hints),
              debrief = debrief,
            }
          end
        end
      elseif ev == "corner_advice" and pv == PROTOCOL_VERSION then
        -- Round 10: in-race per-corner LLM hint reply.
        local corner = tostring(data.corner or "")
        local text = tostring(data.text or "")
        local lap = tonumber(data.lap) or 0
        if corner ~= "" and text ~= "" then
          cornerAdvisories[corner] = {
            lap = lap,
            text = text,
            ts = currentSimT,
          }
          if ac and type(ac.log) == "function" then
            ac.log(string.format(
              "[COPILOT][WS-DIAG] corner_advice %s lap=%d text=%q",
              corner, lap, text:sub(1, 60)))
          end
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
  -- Round 10d: record the wall-clock sim time BEFORE any early return so
  -- pollInbound (called by the entry script right after tick) has a fresh
  -- reference for stamping inbound corner_advice entries, and
  -- takeCornerAdvisory has a fresh reference for its 6s staleness check.
  currentSimT = tonumber(simTime) or currentSimT
  if not url or url == "" then
    return
  end
  if sock then
    return
  end
  if currentSimT - lastTry < RECONNECT_SEC then
    return
  end
  lastTry = currentSimT
  tryOpen()
end

--- Send a JSON payload over the WebSocket.
---
--- CSP's web.Socket is a polymorphic {close: fun()}|fun(data: binary) -- call
--- it AS A FUNCTION to send data. We try the callable form first, then fall
--- back to :send() / :write() for any non-CSP socket implementation.
---@param payload table|nil
function M.sendJson(payload)
  if not payload then
    return
  end
  local js = jsonEncode(payload)
  if not js or not sock then
    return
  end
  local sendOk, sendErr = pcall(function()
    if type(sock) == "function" then
      sock(js)
      return
    end
    local callOk = pcall(function() sock(js) end)
    if callOk then return end
    if type(sock) == "table" and type(sock.send) == "function" then
      sock:send(js)
      return
    end
    if type(sock) == "table" and type(sock.write) == "function" then
      sock:write(js)
      return
    end
    error("no send method available")
  end)
  if not sendOk then
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT][WS-DIAG] sendJson failed: " .. tostring(sendErr))
    end
    sock = nil
    lastTry = -RECONNECT_SEC
  end
end

--- Round 10: send a corner_query event to the sidecar asking for a short
--- LLM-generated coaching hint for the given corner. Round 10c: debounce
--- logic moved to realtime_coaching.tick where it has full cur/dist context
--- and can re-query on significant state changes, not just time elapsed.
---@param corner string  corner label (e.g. "T1")
---@param cur number      current speed km/h
---@param ref number      reference brake entry speed km/h
---@param dist number     distance to brake point in meters
---@param lap number|nil  current lap number
---@return boolean        true if a query was sent
function M.sendCornerQuery(corner, cur, ref, dist, lap)
  if type(corner) ~= "string" or corner == "" then return false end
  if not sock or not url or url == "" then return false end
  M.sendJson({
    protocol = PROTOCOL_VERSION,
    event = "corner_query",
    corner = corner,
    cur = tonumber(cur) or 0,
    ref = tonumber(ref) or 0,
    dist = tonumber(dist) or 0,
    lap = tonumber(lap) or 0,
  })
  if ac and type(ac.log) == "function" then
    ac.log(string.format(
      "[COPILOT][WS-DIAG] sendCornerQuery %s cur=%.0f ref=%.0f dist=%.0fm",
      corner, tonumber(cur) or 0, tonumber(ref) or 0, tonumber(dist) or 0))
  end
  return true
end

--- Round 10d: return the most recent corner_advice text for the label,
--- or nil if none arrived OR it's older than CORNER_ADVISORY_MAX_AGE_SEC
--- of WALL-CLOCK time (via currentSimT from M.tick). Stale entries are
--- auto-deleted so the realtime engine falls back to the rules-based
--- secondary line — no more "BRAKE HARD NOW" stuck when the car has
--- slowed below target.
---@param corner string
---@return string|nil
local CORNER_ADVISORY_MAX_AGE_SEC = 6.0
function M.takeCornerAdvisory(corner)
  if type(corner) ~= "string" or corner == "" then return nil end
  local e = cornerAdvisories[corner]
  if not e or type(e.text) ~= "string" or e.text == "" then
    return nil
  end
  local age = currentSimT - (tonumber(e.ts) or 0)
  -- Negative age (sim time rewind / session reset) must not resurrect stale text.
  if age < 0 or age > CORNER_ADVISORY_MAX_AGE_SEC then
    cornerAdvisories[corner] = nil
    return nil
  end
  return e.text
end

return M
