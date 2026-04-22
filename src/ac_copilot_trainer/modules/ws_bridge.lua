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

--- Issue #81: external-client `{v:1,type:...}` envelope. Handlers registered by
--- the main script; absent handlers reply with `{type="action.ack", applied=false}`.
local actionHandlers = {} ---@type table<string, fun(args:table|nil):boolean,string|nil>
local configGetter ---@type (fun(key:string):any)|nil
local configSetter ---@type (fun(key:string,value:any):boolean,string|nil)|nil

--- Public: register an action handler invoked when the sidecar forwards
--- `{v:1, type:"action", name=<n>, args=<t>}`. Handler returns
--- `(applied:boolean, reason:string|nil)`.
---@param name string
---@param fn fun(args:table|nil):boolean,string|nil
function M.registerActionHandler(name, fn)
  if type(name) == "string" and name ~= "" and type(fn) == "function" then
    actionHandlers[name] = fn
  end
end

---@param getter (fun(key:string):any)|nil
---@param setter (fun(key:string,value:any):boolean,string|nil)|nil
function M.registerConfigBridge(getter, setter)
  if type(getter) == "function" then
    configGetter = getter
  end
  if type(setter) == "function" then
    configSetter = setter
  end
end

--- Latest coaching_response waiting for application (lap index matches lapsCompleted).
local pendingCoaching ---@type { lap: number, hints: table[], debrief: string|nil }|nil

--- Round 10: per-corner LLM advisories keyed by corner label.
--- Populated by pollInbound when corner_advice events arrive.
local cornerAdvisories = {}  ---@type table<string, { lap: number, text: string, ts: number }>
--- Round 10d: wall-clock reference updated via M.tick(simT). Replaces
--- os.clock() which is process CPU time (advances too slowly for a
--- low-CPU Lua script, so the 6s staleness expiry never triggered).
local currentSimT = 0

--- Issue #77 Part A: sidecar auto-launch state.
--- spawnedAlive: true while CSP believes the console child is running; cleared
---               from os.runConsoleProcess exit callback so we can relaunch.
--- lastLaunchAttemptT: sim-time seconds of the last spawn attempt (gate against
---                     double-launch + crash-loop restart).
--- LAUNCH_RETRY_SEC: minimum gap between launch attempts (also our
---                   "settling time" before we stop retrying transparently).
local spawnedAlive = false
--- True after this bridge successfully started a console child (used to drop only *our* stale sockets).
local sidecarChildEverLaunched = false
local lastLaunchAttemptT = -1e9
local LAUNCH_RETRY_SEC = 5.0
--- Back off `runConsoleProcess` after streak failures or bat exit 2 (missing repo/tools — Copilot #78).
local spawnFailStreak = 0
--- Count rapid nonzero child exits (bat starts then dies — Codex #78); not the same as spawn pcall failures.
local nonzeroExitStreak = 0
local spawnAbandonUntilT = -1e9
--- Throttle `tryOpen` during spawn backoff so we do not allocate a socket every frame (Cursor Bugbot #78).
local lastBackoffTryOpenT = -1e9
local SIDECAR_BAT_RELATIVE = "start_sidecar.bat"  -- next to ws_bridge.lua's app dir
--- Per-corner last-query timestamp (unused after round 10c moved the
--- debounce to realtime_coaching; kept for backward compat with M.reset).
local lastCornerQueryAt = {}  ---@type table<string, number>
--- CSP web.socket is callback-based; inbound frames land here. Must live at
--- module scope before `M.configure` / `M.reset` assign to it (CodeRabbit #78).
local _recvQueue = {}
--- True after first inbound JSON with matching `protocol` (CodeRabbit #78).
local sidecarProtocolReady = false
--- Forward declaration — assigned where `tryOpen` is defined (used before spawn).
local tryOpen

local function close_socket_if_any(s)
  if s == nil then
    return
  end
  -- CSP sockets are often cdata callables; still expose :close() (Codex/Copilot).
  pcall(function()
    s:close()
  end)
end

---@param u string|nil full ws URL, e.g. ws://127.0.0.1:8765
function M.configure(u)
  close_socket_if_any(sock)
  url = u
  sock = nil
  lastTry = -RECONNECT_SEC
  pendingCoaching = nil
  _recvQueue = {}
  sidecarProtocolReady = false
  -- Explicit URL/socket reset must not leave zombie-latch set for the next dial (Codex #78).
  sidecarChildEverLaunched = false
  spawnFailStreak = 0
  nonzeroExitStreak = 0
  spawnAbandonUntilT = -1e9
  lastBackoffTryOpenT = -1e9
end

--- Issue #77 Part A: spawn the Python sidecar if it isn't already listening.
---
--- CSP exposes os.runConsoleProcess(params, callback) with terminateWithScript=true
--- which ties the child process to the Lua script lifetime (also dies with AC on
--- Win 8+). Pattern mirrored from the shipped CSP app `joypad-assist/mobile`.
---
--- Behaviour:
---   1. If we already have a live socket, noop.
---   2. If we already spawned a child this session and it's still alive, noop.
---   3. If we tried to launch within LAUNCH_RETRY_SEC, noop (avoid crash-loop).
---   4. Otherwise launch start_sidecar.bat (sibling of this Lua module's app dir).
---      The .bat handles Python discovery + env vars.
---
--- Stdout from the child streams into ac.log prefixed `[SIDECAR]`.
--- On unexpected child exit, we log the exit code; the next M.tick() will
--- naturally re-attempt the launch via this function once LAUNCH_RETRY_SEC has
--- elapsed.
---
---@param appDir string|nil  absolute path to the deployed app dir (where the .bat lives)
function M.startSidecarIfNeeded(appDir)
  -- Child we spawned died but CSP kept a stale socket handle (reconnect=true); do not tear down
  -- sockets opened for a manually started sidecar (spawnedAlive was never true).
  if not spawnedAlive and sock ~= nil and sidecarChildEverLaunched then
    close_socket_if_any(sock)
    sock = nil
    lastTry = -RECONNECT_SEC
    sidecarProtocolReady = false
    -- One-shot zombie cleanup: do not keep closing a user-opened manual socket (Codex #78).
    sidecarChildEverLaunched = false
  end
  if sock then return end
  if spawnedAlive then return end

  -- During backoff, only dial occasionally — `lastLaunchAttemptT` is not advanced on this path (Cursor Bugbot #78).
  if currentSimT < spawnAbandonUntilT then
    if currentSimT - lastBackoffTryOpenT < LAUNCH_RETRY_SEC then
      return
    end
    lastBackoffTryOpenT = currentSimT
    if tryOpen() then
      nonzeroExitStreak = 0
    end
    return
  end

  if currentSimT - lastLaunchAttemptT < LAUNCH_RETRY_SEC then return end

  -- WebSocket dial first: if a sidecar is already listening, connect instead of spawning a second copy (CodeRabbit #78).
  if tryOpen() then
    nonzeroExitStreak = 0
    return
  end

  lastLaunchAttemptT = currentSimT

  if type(os) ~= "table" or type(os.runConsoleProcess) ~= "function" then
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT][SIDECAR] os.runConsoleProcess unavailable on this CSP build; manual launch required")
    end
    return
  end

  local batPath
  if type(appDir) == "string" and appDir ~= "" then
    batPath = appDir .. "/" .. SIDECAR_BAT_RELATIVE
  else
    batPath = SIDECAR_BAT_RELATIVE  -- relative to AC working dir; fragile fallback
  end

  if ac and type(ac.log) == "function" then
    ac.log("[COPILOT][SIDECAR] launching: " .. batPath)
  end

  spawnedAlive = false
  local spawnAccepted = false
  local okSpawn, errSpawn = pcall(function()
    local a, b = os.runConsoleProcess({
      filename = batPath,
      arguments = {},
      workingDirectory = appDir or "",
      timeout = 0,                   -- no per-call timeout; long-running server
      terminateWithScript = true,    -- die with AC + script reload
      inheritEnvironment = true,
      dataCallback = function(_err, line)
        if line and ac and type(ac.log) == "function" then
          ac.log("[COPILOT][SIDECAR] " .. tostring(line):gsub("[\r\n]+$", ""))
        end
      end,
    }, function(err, result)
      -- Process exited (clean or crash). Clear flag so next M.tick can relaunch.
      spawnedAlive = false
      if sock == nil then
        -- Clean exit: no stale handle — do not treat later manual sockets as zombies.
        sidecarChildEverLaunched = false
      end
      local exitCode = (type(result) == "table" and result.exitCode) or "?"
      local codeNum = tonumber(exitCode)
      -- `start_sidecar.bat` uses `exit /b 2` when `tools/ai_sidecar` cannot be resolved (Copilot #78).
      -- Must not depend on `ac.log` (Cursor #78 / Bugbot).
      if codeNum == 2 then
        spawnAbandonUntilT = 1e12
        spawnFailStreak = 0
        nonzeroExitStreak = 0
      elseif codeNum == 0 then
        nonzeroExitStreak = 0
      elseif codeNum ~= 0 then
        -- Includes missing/unparseable exit metadata (`codeNum == nil`, Bugbot #78): do not treat as clean.
        nonzeroExitStreak = nonzeroExitStreak + 1
        if nonzeroExitStreak >= 8 then
          spawnAbandonUntilT = math.max(spawnAbandonUntilT, currentSimT + 120)
          nonzeroExitStreak = 0
          if ac and type(ac.log) == "function" then
            ac.log("[COPILOT][SIDECAR] auto-launch backing off 120s after repeated nonzero child exits (Codex #78)")
          end
        end
      end
      if ac and type(ac.log) == "function" then
        ac.log(string.format("[COPILOT][SIDECAR] exited code=%s err=%s",
          tostring(exitCode), tostring(err or "nil")))
      end
    end)
    if not a then
      error(tostring(b or "runConsoleProcess returned nil/false"))
    end
    spawnAccepted = true
  end)
  spawnedAlive = okSpawn and spawnAccepted
  if okSpawn and spawnAccepted then
    sidecarChildEverLaunched = true
    spawnFailStreak = 0
    -- Do not clear `nonzeroExitStreak` here: spawn can succeed while the bat exits fast;
    -- streak must accumulate across attempts (Codex #78 / #3115226944).
  end
  if not okSpawn then
    spawnFailStreak = spawnFailStreak + 1
    if spawnFailStreak >= 10 then
      spawnAbandonUntilT = math.max(spawnAbandonUntilT, currentSimT + 120)
      spawnFailStreak = 0
      if ac and type(ac.log) == "function" then
        ac.log("[COPILOT][SIDECAR] auto-launch backing off 120s after repeated spawn failures (Copilot #78)")
      end
    end
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT][SIDECAR] runConsoleProcess failed: " .. tostring(errSpawn))
    end
  end
end

--- Public read-only status: is our spawned child sidecar process believed alive?
--- Used by the Settings UI to render a status line.
---@return boolean
function M.sidecarSpawnedAlive()
  return spawnedAlive
end

--- Public read-only status: inbound traffic validated against `PROTOCOL_VERSION` (CodeRabbit #78).
---@return boolean
function M.sidecarConnected()
  return sock ~= nil and sidecarProtocolReady
end

--- Clear socket state (e.g. leaving track / new session). URL unchanged.
function M.reset()
  close_socket_if_any(sock)
  sock = nil
  lastTry = -RECONNECT_SEC
  pendingCoaching = nil
  cornerAdvisories = {}
  lastCornerQueryAt = {}
  currentSimT = 0
  lastLaunchAttemptT = -1e9
  _recvQueue = {}
  sidecarProtocolReady = false
  -- Do not clear `spawnedAlive`: the console child can outlive this reset; clearing it risks a second spawn on port 8765 (Cursor #78).
  sidecarChildEverLaunched = false
  spawnFailStreak = 0
  nonzeroExitStreak = 0
  spawnAbandonUntilT = -1e9
  lastBackoffTryOpenT = -1e9
end

--- Drop queued sidecar response without closing the socket (e.g. lap counter reset).
function M.clearPendingCoaching()
  pendingCoaching = nil
end

--- Drop cached corner_advice payloads (e.g. rolling session reset / lap rewind).
function M.clearCornerAdvisories()
  cornerAdvisories = {}
end

local function jsonEncode(t)
  -- JSON.* may be a plain function (CSP) or a callable userdata (e.g. lupa tests).
  if JSON and JSON.stringify ~= nil then
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
  if JSON and JSON.parse ~= nil then
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
--- Cap noisy per-frame WS recv logs (Bugbot); diagnostics reset on new socket.
local _wsRecvLogsLeft = 0

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
  if ac and type(ac.log) == "function" and _wsRecvLogsLeft > 0 then
    _wsRecvLogsLeft = _wsRecvLogsLeft - 1
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
tryOpen = function()
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
  sidecarProtocolReady = false
  local opened = nil
  local params = {
    onError = _onError,
    onClose = function(reason)
      if ac and type(ac.log) == "function" then
        ac.log("[COPILOT][WS-DIAG] socket closed: " .. tostring(reason))
      end
      -- Ignore stale onClose from a replaced socket (Codex): shared callback
      -- table can outlive the handle we dropped during configure/reconnect.
      if opened ~= nil and sock == opened then
        sock = nil
        lastTry = -RECONNECT_SEC
        sidecarProtocolReady = false
      end
    end,
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
    opened = s
    sock = s
    _wsRecvLogsLeft = 4
    if ac and type(ac.log) == "function" then
      ac.log("[COPILOT][WS-DIAG] CONNECTED url=" .. tostring(url) .. " attempts=" .. tostring(_wsDiagAttempts))
    end
    -- Issue #81: announce ourselves so the sidecar registers us as an external
    -- peer and forwards screen-side `action`/`config.set` frames to us.
    M.sendJson({
      v = PROTOCOL_VERSION,
      type = "hello",
      client = "ac-copilot-trainer-lua",
    })
    return true
  end
  if ac and type(ac.log) == "function" then
    ac.log(string.format(
      "[COPILOT][WS-DIAG] tryOpen failed url=%s ok=%s err=%s attempts=%d",
      tostring(url), tostring(ok), tostring(s), _wsDiagAttempts
    ))
  end
  sock = nil
  sidecarProtocolReady = false
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
  local cap = tonumber(maxPerTick) or MAX_RECV_PER_TICK
  cap = math.max(1, math.min(32, math.floor(cap + 0.5)))
  -- Callback queue can still hold frames after sendJson nils `sock`; drain them
  -- so coaching_response / corner_advice are not dropped (Bugbot).
  if not sock and #_recvQueue == 0 then
    return
  end
  for _ = 1, cap do
    local raw = tryRecvOne()
    if not raw then
      break
    end
    local data = jsonDecode(raw)
    if type(data) == "table" then
      local ev = data.event
      local pv = tonumber(data.protocol)
      if pv == PROTOCOL_VERSION then
        sidecarProtocolReady = true
      end
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
            elseif debrief then
              -- Late Ollama debrief after the immediate payload was consumed:
              -- surface prose only — do not queue placeholder hints that would
              -- replace rules-engine lines in the HUD. If multiple follow-ups
              -- arrive in one drain, a newer lap must replace a stale debrief-only
              -- bucket for an older lap (Codex).
              local plap = pendingCoaching and tonumber(pendingCoaching.lap) or -1
              local ilap = tonumber(lap) or 0
              if not pendingCoaching or ilap > plap then
                pendingCoaching = {
                  lap = lap,
                  hints = {},
                  debrief = debrief,
                }
              end
            end
          else
            pendingCoaching = {
              lap = lap,
              hints = normalizeSidecarHints(hints),
              debrief = debrief,
            }
          end
        end
      elseif tonumber(data.v) == PROTOCOL_VERSION and type(data.type) == "string" then
        -- Issue #81: external-client envelope. The sidecar fans `config.set`,
        -- `action`, and `state.subscribe` here so we can apply them locally
        -- and emit acks/values that the sidecar broadcasts back to the screen.
        sidecarProtocolReady = true
        local t = data.type
        if t == "action" then
          local name = type(data.name) == "string" and data.name or ""
          local handler = actionHandlers[name]
          if not handler then
            M.sendJson({
              v = PROTOCOL_VERSION,
              type = "action.ack",
              name = name,
              applied = false,
              reason = "no handler",
            })
          else
            local okCall, applied, reason = pcall(handler, data.args)
            if not okCall then
              M.sendJson({
                v = PROTOCOL_VERSION,
                type = "action.ack",
                name = name,
                applied = false,
                reason = "handler error: " .. tostring(applied),
              })
            else
              M.sendJson({
                v = PROTOCOL_VERSION,
                type = "action.ack",
                name = name,
                applied = applied and true or false,
                reason = reason,
              })
            end
            if ac and type(ac.log) == "function" then
              ac.log(string.format("[COPILOT][WS-EXT] action %s applied=%s",
                name, tostring(applied)))
            end
          end
        elseif t == "config.get" then
          local key = type(data.key) == "string" and data.key or ""
          if key == "" then
            M.sendJson({
              v = PROTOCOL_VERSION,
              type = "config.ack",
              key = key,
              applied = false,
              reason = "empty key",
            })
          elseif not configGetter then
            M.sendJson({
              v = PROTOCOL_VERSION,
              type = "config.ack",
              key = key,
              applied = false,
              reason = "no config bridge",
            })
          else
            local okGet, val = pcall(configGetter, key)
            if okGet then
              M.sendJson({
                v = PROTOCOL_VERSION,
                type = "config.value",
                key = key,
                value = val,
              })
            else
              M.sendJson({
                v = PROTOCOL_VERSION,
                type = "config.ack",
                key = key,
                applied = false,
                reason = "getter error: " .. tostring(val),
              })
            end
          end
        elseif t == "config.set" then
          local key = type(data.key) == "string" and data.key or ""
          local value = data.value
          if key == "" then
            M.sendJson({
              v = PROTOCOL_VERSION,
              type = "config.ack",
              key = key,
              applied = false,
              reason = "empty key",
            })
          elseif not configSetter then
            M.sendJson({
              v = PROTOCOL_VERSION,
              type = "config.ack",
              key = key,
              applied = false,
              reason = "no config bridge",
            })
          else
            local okSet, applied, reason = pcall(configSetter, key, value)
            if not okSet then
              M.sendJson({
                v = PROTOCOL_VERSION,
                type = "config.ack",
                key = key,
                applied = false,
                reason = "setter error: " .. tostring(applied),
              })
            else
              M.sendJson({
                v = PROTOCOL_VERSION,
                type = "config.ack",
                key = key,
                applied = applied and true or false,
                reason = reason,
              })
            end
          end
        end
        -- hello / hello_ack / state.* are not consumed by Lua at this stage;
        -- the sidecar handles `hello`/`hello_ack` and we silently accept the
        -- rest until Phase-2 telemetry push lands.
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
---@return boolean  true if bytes were handed to the socket layer
function M.sendJson(payload)
  if not payload then
    return false
  end
  local js = jsonEncode(payload)
  if not js or not sock then
    return false
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
    -- Close before dropping the handle so reconnect:true cannot leave a zombie
    -- recv path while tick() opens a replacement socket (Codex).
    close_socket_if_any(sock)
    sock = nil
    lastTry = -RECONNECT_SEC
    sidecarProtocolReady = false
    return false
  end
  return true
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
---@return boolean        true if JSON was sent on the active socket (false on send failure)
function M.sendCornerQuery(corner, cur, ref, dist, lap)
  if type(corner) ~= "string" or corner == "" then return false end
  if not sock or not url or url == "" then return false end
  local sent = M.sendJson({
    protocol = PROTOCOL_VERSION,
    event = "corner_query",
    corner = corner,
    cur = tonumber(cur) or 0,
    ref = tonumber(ref) or 0,
    dist = tonumber(dist) or 0,
    lap = tonumber(lap) or 0,
  })
  if not sent then
    return false
  end
  if ac and type(ac.log) == "function" then
    ac.log(string.format(
      "[COPILOT][WS-DIAG] sendCornerQuery %s cur=%.0f ref=%.0f dist=%.0fm",
      corner, tonumber(cur) or 0, tonumber(ref) or 0, tonumber(dist) or 0))
  end
  return true
end

--- Label -> text for sidecar `corner_advice` entries matching `lap` (for lap archive; no HUD mutation).
---@param lap number|nil
---@return table<string, string>
function M.cornerAdvisorySnapshotForLap(lap)
  local want = tonumber(lap)
  local out = {}
  if not want then
    return out
  end
  for corner, e in pairs(cornerAdvisories) do
    if type(corner) == "string" and corner ~= "" and type(e) == "table" then
      local elap = tonumber(e.lap)
      local txt = e.text
      if elap == want and type(txt) == "string" and txt ~= "" then
        out[corner] = txt
      end
    end
  end
  return out
end

--- Round 10d: return the most recent corner_advice text for the label,
--- or nil if none arrived OR it's older than CORNER_ADVISORY_MAX_AGE_SEC
--- of WALL-CLOCK time (via currentSimT from M.tick). Stale entries are
--- auto-deleted so the realtime engine falls back to the rules-based
--- secondary line — no more "BRAKE HARD NOW" stuck when the car has
--- slowed below target.
---@param corner string
---@param currentLap number|nil  laps completed counter (must match advice lap)
---@return string|nil
local CORNER_ADVISORY_MAX_AGE_SEC = 6.0
function M.takeCornerAdvisory(corner, currentLap)
  if type(corner) ~= "string" or corner == "" then return nil end
  local e = cornerAdvisories[corner]
  if not e or type(e.text) ~= "string" or e.text == "" then
    return nil
  end
  local want = tonumber(currentLap)
  local elap = tonumber(e.lap)
  if want ~= nil and elap ~= nil and elap ~= want then
    cornerAdvisories[corner] = nil
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
