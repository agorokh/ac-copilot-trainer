-- Optional WebSocket to Python AI sidecar (issue #9 Part B, #45 protocol + inbound).
-- Safe no-op if CSP `web.socket` unavailable or socket has no receive API.
-- M0 (#341): client→server ``telemetry_tick`` (spline + lap) is emitted by ``telemetry_publisher.lua``
-- via ``wsBridge.sendJson`` from ``ac_copilot_trainer.lua`` script.update.

local M = {}

local sock ---@type any
local url ---@type string|nil
local RECONNECT_SEC = 5
local lastTry = -RECONNECT_SEC
local reconnectElapsed = 0
local MAX_RECV_PER_TICK = 8
--- Sidecar WebSocket protocol version (must match Python `tools/ai_sidecar` v1 schema).
local PROTOCOL_VERSION = 1
M.PROTOCOL_VERSION = PROTOCOL_VERSION

--- Issue #81: external-client `{v:1,type:...}` envelope. Handlers registered by
--- the main script; absent handlers reply with `{type="action.ack", applied=false}`.
local actionHandlers = {} ---@type table<string, fun(args:table|nil):boolean,string|nil>
--- Issue #86 Part D: external-client request handlers (`setup.list`,
--- `setup.load`). Stored keyed by request type with the ack type the
--- bridge will use when shipping the response payload. See
--- `M.registerRequestHandler` and the dispatch block in `pollInbound`.
local requestHandlers = {} ---@type table<string, { ackType: string, fn: fun(payload:table|nil):table,string|nil }>
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
--- Spawn/backoff pacing accumulates script.update's real frame delta, not sim time: the pre-drive
--- menu freezes currentSimT but update(dt) continues and must recover a failed child before it can
--- receive session.start (#726). Do not count frames here: the rig renders at ~114 Hz.
local spawnedAlive = false
--- True after this bridge successfully started a console child (used to drop only *our* stale sockets).
local sidecarChildEverLaunched = false
local sidecarMaintenanceElapsed = 0
local lastLaunchAttemptElapsed = -1e9
local LAUNCH_RETRY_SECONDS = 5
--- Back off `runConsoleProcess` after streak failures or bat exit 2 (missing repo/tools — Copilot #78).
local spawnFailStreak = 0
--- Count rapid nonzero child exits (bat starts then dies — Codex #78); not the same as spawn pcall failures.
local nonzeroExitStreak = 0
local spawnAbandonUntilElapsed = -1e9
local SPAWN_BACKOFF_SECONDS = 120
--- Throttle `tryOpen` during spawn backoff so we do not allocate a socket every frame (Cursor Bugbot #78).
local lastBackoffTryOpenElapsed = -1e9
local SIDECAR_BAT_RELATIVE = "start_sidecar.bat"  -- next to ws_bridge.lua's app dir
--- Per-corner last-query timestamp (unused after round 10c moved the
--- debounce to realtime_coaching; kept for backward compat with M.reset).
local lastCornerQueryAt = {}  ---@type table<string, number>
--- CSP web.socket is callback-based; inbound frames land here. Must live at
--- module scope before `M.configure` / `M.reset` assign to it (CodeRabbit #78).
local _recvQueue = {}
--- True after first inbound JSON with matching `protocol` (CodeRabbit #78).
local sidecarProtocolReady = false
-- v1-registration flag: true ONLY once a non-error v1 frame (hello_ack, or a
-- fanned action/config/state) arrives, proving the sidecar added us to its v1
-- `_external_peers`. Deliberately SEPARATE from `sidecarProtocolReady`, which the
-- legacy `protocol=1` recv path also sets — a legacy reply (e.g. corner_advice)
-- must NOT unblock the v1 `state.snapshot` publish path or stop the hello retry
-- before the v1 handshake actually completes (chatgpt-codex P1 on PR #171).
local externalHelloAcked = false
--- Hello-retry state for the v1 external surface: some CSP builds don't fire
--- params.onOpen reliably on the first connect. Without a hello we never
--- register as a v1 peer with the sidecar, and `state.snapshot` frames are
--- silently dropped (no loopback target). The retry MUST be paced on real
--- frames (a tick counter), NOT sim-time: in the pre-drive pit menu the sim
--- clock is frozen while the render loop (M.tick) keeps running, so a sim-time
--- gate fired the retry exactly once and never recovered from a first send that
--- lost the CSP `web.socket` writable race — stranding us connected-but-
--- unregistered so coaching.snapshot never fans out. Found in-sim on AG_PC
--- (#170 / EPIC #154).
local externalHelloPending = false
local helloRetryFrames = 0
local helloSendCount = 0
--- Monotonic transport-open counter. Incremented only from CSP's `onOpen`
--- callback, including auto-reconnects that do not pass through `tryOpen`.
local socketOpenEpoch = 0
--- One-shot flag set when a late external tap subscribes to `session`.
--- The entry script consumes it and re-arms lifecycle_publisher so the current
--- event-driven session is replayed without making the sidecar topic-aware (#190).
local sessionReplayRequested = false
--- Resend hello every N M.tick frames (~0.2 s at 60 Hz) until hello_ack flips
--- `sidecarProtocolReady`. Frame-paced so a frozen sim clock cannot stall it.
local EXTERNAL_HELLO_RETRY_FRAMES = 12
--- Emit at most one hello-retry diagnostic per this many actual sends so a
--- (briefly) unresponsive sidecar cannot spam the CSP console (Qodo on PR #91).
local EXTERNAL_HELLO_LOG_EVERY_SENDS = 10
local SETUP_EXPERIMENT_STORE_RETRY_FRAMES = 300
--- Canonical setup experiment JSONL path, registered with the trusted local
--- sidecar after each v1 handshake so compare/suggest can read rebuilt rows
--- immediately after sidecar restart.
local setupExperimentStorePath = nil
local setupExperimentStoreSent = false
local setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
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
  reconnectElapsed = 0
  lastTry = -RECONNECT_SEC
  sidecarMaintenanceElapsed = 0
  lastLaunchAttemptElapsed = -1e9
  pendingCoaching = nil
  _recvQueue = {}
  sidecarProtocolReady = false
  -- Explicit URL/socket reset must not leave zombie-latch set for the next dial (Codex #78).
  sidecarChildEverLaunched = false
  spawnFailStreak = 0
  nonzeroExitStreak = 0
  spawnAbandonUntilElapsed = -1e9
  lastBackoffTryOpenElapsed = -1e9
  setupExperimentStoreSent = false
  setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
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
---   3. If we tried to launch within LAUNCH_RETRY_SECONDS, noop (avoid crash-loop).
---   4. Otherwise launch start_sidecar.bat (sibling of this Lua module's app dir).
---      The .bat handles Python discovery + env vars.
---
--- Stdout from the child streams into ac.log prefixed `[SIDECAR]`.
--- On unexpected child exit, we log the exit code; the next M.tick() will
--- naturally re-attempt the launch via this function once LAUNCH_RETRY_SECONDS have
--- elapsed.
---
---@param appDir string|nil  absolute path to the deployed app dir (where the .bat lives)
function M.startSidecarIfNeeded(appDir, dt)
  local elapsed = (type(dt) == "number" and dt == dt and dt >= 0) and dt or 0
  sidecarMaintenanceElapsed = sidecarMaintenanceElapsed + elapsed
  -- Child we spawned died but CSP kept a stale socket handle (reconnect=true); do not tear down
  -- sockets opened for a manually started sidecar (spawnedAlive was never true).
  if not spawnedAlive and sock ~= nil and sidecarChildEverLaunched then
    close_socket_if_any(sock)
    sock = nil
    lastTry = -RECONNECT_SEC
    sidecarProtocolReady = false
    setupExperimentStoreSent = false
    setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
    -- One-shot zombie cleanup: do not keep closing a user-opened manual socket (Codex #78).
    sidecarChildEverLaunched = false
  end
  if sock then return end
  if spawnedAlive then return end

  -- During backoff, only dial occasionally. update(dt) pacing is load-bearing: currentSimT is
  -- frozen at the pre-drive menu where the child must recover to receive session.start (#726).
  if sidecarMaintenanceElapsed < spawnAbandonUntilElapsed then
    if sidecarMaintenanceElapsed - lastBackoffTryOpenElapsed < LAUNCH_RETRY_SECONDS then
      return
    end
    lastBackoffTryOpenElapsed = sidecarMaintenanceElapsed
    if tryOpen() then
      nonzeroExitStreak = 0
    end
    return
  end

  if sidecarMaintenanceElapsed - lastLaunchAttemptElapsed < LAUNCH_RETRY_SECONDS then return end

  -- WebSocket dial first: if a sidecar is already listening, connect instead of spawning a second copy (CodeRabbit #78).
  if tryOpen() then
    nonzeroExitStreak = 0
    return
  end

  lastLaunchAttemptElapsed = sidecarMaintenanceElapsed

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
        spawnAbandonUntilElapsed = 1e12
        spawnFailStreak = 0
        nonzeroExitStreak = 0
      elseif codeNum == 0 then
        nonzeroExitStreak = 0
      elseif codeNum ~= 0 then
        -- Includes missing/unparseable exit metadata (`codeNum == nil`, Bugbot #78): do not treat as clean.
        nonzeroExitStreak = nonzeroExitStreak + 1
        if nonzeroExitStreak >= 8 then
          spawnAbandonUntilElapsed = math.max(
            spawnAbandonUntilElapsed,
            sidecarMaintenanceElapsed + SPAWN_BACKOFF_SECONDS
          )
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
      spawnAbandonUntilElapsed = math.max(
        spawnAbandonUntilElapsed,
        sidecarMaintenanceElapsed + SPAWN_BACKOFF_SECONDS
      )
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

--- Public read-only transport-open epoch. The entry script uses this to detect
--- reconnects that close/open/hello_ack between two per-frame boolean samples.
---@return number
function M.openEpoch()
  return socketOpenEpoch
end

--- One-shot signal: did an external client just subscribe to `session`?
---@return boolean
function M.consumeSessionReplayRequest()
  local out = sessionReplayRequested
  sessionReplayRequested = false
  return out
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
  reconnectElapsed = 0
  sidecarMaintenanceElapsed = 0
  lastLaunchAttemptElapsed = -1e9
  _recvQueue = {}
  sidecarProtocolReady = false
  sessionReplayRequested = false
  -- Do not clear `spawnedAlive`: the console child can outlive this reset; clearing it risks a second spawn on port 8765 (Cursor #78).
  sidecarChildEverLaunched = false
  spawnFailStreak = 0
  nonzeroExitStreak = 0
  spawnAbandonUntilElapsed = -1e9
  lastBackoffTryOpenElapsed = -1e9
  setupExperimentStoreSent = false
  setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
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

local function trimText(text, maxLen)
  local s = tostring(text or "")
  local n = tonumber(maxLen) or 220
  if #s <= n then
    return s
  end
  if n <= 3 then
    return s:sub(1, n)
  end
  return s:sub(1, n - 3) .. "..."
end

local function brainKindForCause(causeClass)
  local c = tostring(causeClass or "")
  if c:find("technique", 1, true) then
    return "line"
  end
  if c:find("setup", 1, true) then
    return "brake"
  end
  if c:find("grip", 1, true) then
    return "throttle"
  end
  return "general"
end

local function firstAttribution(corner)
  local attrs = type(corner) == "table" and corner.attributions or nil
  if type(attrs) ~= "table" then
    return nil
  end
  local best = nil
  local bestConf = -1
  for i = 1, #attrs do
    local a = attrs[i]
    if type(a) == "table" then
      local conf = tonumber(a.confidence) or 0
      if not best or conf > bestConf then
        best = a
        bestConf = conf
      end
    end
  end
  return best
end

local function normalizeBrainHints(data, fallbackHints)
  local out = {}
  local corners = type(data) == "table" and data.cornerAnalysis or nil
  if type(corners) == "table" then
    for i = 1, #corners do
      if #out >= 3 then
        break
      end
      local corner = corners[i]
      if type(corner) == "table" then
        local attr = firstAttribution(corner)
        local headline = type(corner.headline) == "string" and corner.headline or ""
        if headline == "" then
          headline = "Corner " .. tostring(corner.index or i)
        end
        local loss = tonumber(corner.time_loss_s)
        local lossText = ""
        if loss and loss > 0.05 then
          lossText = string.format(" (+%.2fs)", loss)
        end
        local detail = ""
        local kind = "general"
        if attr then
          kind = brainKindForCause(attr.cause_class)
          if type(attr.coaching) == "string" and attr.coaching ~= "" then
            detail = attr.coaching
          elseif type(attr.symptom) == "string" and attr.symptom ~= "" then
            detail = attr.symptom
          end
        end
        local text = headline .. lossText
        if detail ~= "" then
          text = text .. ": " .. detail
        end
        out[#out + 1] = { kind = kind, text = trimText(text, 220) }
      end
    end
  end
  local balance = type(data) == "table" and data.balance or nil
  if #out < 3 and type(balance) == "table" and type(balance.coaching) == "string"
      and balance.coaching ~= "" then
    out[#out + 1] = { kind = "positive", text = trimText("Balance: " .. balance.coaching, 220) }
  end
  if #out > 0 then
    return out
  end
  return normalizeSidecarHints(fallbackHints)
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
  setupExperimentStoreSent = false
  setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
  -- Mark that we owe the sidecar a hello on this socket. The actual send is
  -- retried from M.tick() until `sidecarProtocolReady` flips (set when the
  -- sidecar's v1 hello_ack arrives) — this is the only reliable signal that
  -- our hello landed and we're registered as an external peer.
  externalHelloPending = true
  externalHelloAcked = false
  helloRetryFrames = 0
  helloSendCount = 0
  local function announceExternalHello()
    M.sendJson({
      v = PROTOCOL_VERSION,
      type = "hello",
      client = "ac-copilot-trainer-lua",
    })
  end
  local opened = nil
  local params = {
    onOpen = function()
      -- Ignore stale onOpen from a socket handle replaced by configure/reset.
      if opened ~= nil and sock ~= opened then
        return
      end
      socketOpenEpoch = socketOpenEpoch + 1
      -- Re-arm v1 (and legacy) registration gating on every transport open. With
      -- `reconnect = true` CSP auto-reconnects on a transient drop by firing this
      -- callback WITHOUT going through `tryOpen`, so the tryOpen resets are skipped;
      -- a stale `externalHelloAcked = true` would then suppress the hello retry on
      -- the new socket and leave us unregistered with the sidecar's new connection
      -- (CodeRabbit Major on PR #171).
      sidecarProtocolReady = false
      externalHelloAcked = false
      externalHelloPending = true
      setupExperimentStoreSent = false
      setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
      helloRetryFrames = 0
      helloSendCount = 0
      -- Always announce hello on onOpen. The previous "inline hello + dedup"
      -- pattern silently dropped the registration when the inline send fired
      -- before the socket was actually open: sendJson returned false, and
      -- the dedup window then suppressed the onOpen retry, leaving the peer
      -- connected at WS level but never v1-registered with the sidecar (so
      -- coaching.snapshot frames never flowed). The sidecar's
      -- `_external_peers.add()` is idempotent — a duplicate hello is a no-op
      -- on the server side, so always sending here is safe.
      announceExternalHello()
      if ac and type(ac.log) == "function" then
        ac.log("[COPILOT][WS-DIAG] onOpen: hello announced")
      end
    end,
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
        setupExperimentStoreSent = false
        setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
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
    -- DO NOT announce hello inline: web.socket() returns the socket handle
    -- before the underlying TCP+WS upgrade actually completes. Calling
    -- sendJson here writes to a not-yet-open socket; CSP web.Socket either
    -- buffers or silently drops, and we have no reliable signal of which.
    -- Rely on the params.onOpen callback for hello — that's only invoked
    -- once the socket is genuinely ready to receive frames, and the sidecar's
    -- `_external_peers.add()` is idempotent so duplicate hellos are safe
    -- if a future CSP build also fires hello from somewhere else.
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
          if source == "brain" then
            pendingCoaching = {
              lap = lap,
              hints = normalizeBrainHints(data, hints),
              debrief = debrief,
            }
          elseif source == "ollama" then
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
        local t = data.type
        -- A non-error v1 frame (hello_ack, or a fanned action/config/state/
        -- request) proves the sidecar registered us as a peer. An `error`
        -- frame must NOT flip readiness: the sidecar emits {v=1,type="error"}
        -- to REJECT a frame (e.g. a state.snapshot sent before our hello
        -- landed), and treating that as "registered" cancels the hello retry
        -- below — stranding us connected-but-unregistered so coaching.snapshot
        -- never fans out to the rig screen / harness tap. Found in-sim on
        -- AG_PC delivering #170 / EPIC #154 (off-sim L0/L1 can't see this).
        if t ~= "error" then
          sidecarProtocolReady = true
          -- A non-error v1 frame proves the sidecar registered us as a v1 peer
          -- (hello_ack, or a fanned action/config/state). This — not the
          -- legacy-inclusive `sidecarProtocolReady` — gates the v1 publish path
          -- and the hello-retry stop (chatgpt-codex P1 on PR #171).
          externalHelloAcked = true
          M.sendSetupExperimentStorePath()
        end
        if t == "error" then
          if ac and type(ac.log) == "function" then
            pcall(ac.log, "[COPILOT][WS-DIAG] sidecar rejected frame: "
              .. tostring(data.message) .. " ref=" .. tostring(data.ref_type))
          end
        elseif t == "action" then
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
        elseif t == "hello" or t == "hello_ack" then
          -- Sidecar / trainer lifecycle frames — intentionally ignored here
          -- (see comment after the generic-dispatch block). Do not route them
          -- through the request-handler `else` or they spam diagnostics.
        elseif t == "setup.experiment.store.ack"
            or t == "setup.experiment.record.ack"
            or t == "setup.compare.result"
            or t == "setup.suggest.result" then
          -- Sidecar-local setup optimizer replies. Lua only initiates record
          -- store registration and record ingestion; compare/suggest are for
          -- external clients, so accept these quietly if fanned back.
          if t == "setup.experiment.store.ack" and data.ok == false then
            setupExperimentStoreSent = false
            setupExperimentStoreRetryFrames = 0
          end
          if (t == "setup.experiment.store.ack" or t == "setup.experiment.record.ack")
              and data.ok == false
              and ac and type(ac.log) == "function" then
            pcall(ac.log, "[COPILOT][SETUP-OPT] sidecar ack failed: " .. tostring(data.error))
          end
        elseif t == "state.subscribe" then
          local topics = data.topics
          if type(topics) == "table" then
            for _, topic in ipairs(topics) do
              if topic == "session" then
                sessionReplayRequested = true
                break
              end
            end
          end
          -- Passive subscription envelope; sidecar owns fan-out. Lua only uses
          -- a session subscription as a replay hint for the event-driven producer.
        elseif type(t) == "string" and t:sub(1, 6) == "state." then
          -- Passive telemetry envelopes (`state.snapshot`, etc.) are fanned by
          -- the sidecar to peers; Lua does not register handlers for them.
          -- Treat as silent accepts (Cursor Bugbot on PR #91: the generic
          -- `else` used to log every `state.*` as "unhandled request type").
        else
          -- Issue #86 Part D: generic request dispatch. The screen sends
          -- `{v:1, type:"setup.list"|"setup.load", ...}` and we look up a
          -- pre-registered handler that returns the ack payload. Handlers
          -- live in the entry script (registered via `registerRequestHandler`)
          -- so the bridge stays stateless about app-level features.
          local entry = requestHandlers[t]
          if entry then
            local okCall, resp, errExtra = pcall(entry.fn, data.payload or data)
            if not okCall then
              M.sendJson({
                v = PROTOCOL_VERSION,
                type = entry.ackType,
                ok = false,
                error = "handler error: " .. tostring(resp),
              })
            else
              local ackBody = type(resp) == "table" and resp or {}
              ackBody.v = PROTOCOL_VERSION
              ackBody.type = entry.ackType
              -- Only propagate the secondary `errExtra` return when the
              -- handler did NOT report success. If a successful handler
              -- returns a warning string in the second slot, surfacing it
              -- as `error` would trigger the screen's red-toast path
              -- (CodeRabbit on PR #91). Drop it silently.
              if errExtra and ackBody.error == nil and ackBody.ok ~= true then
                ackBody.error = tostring(errExtra)
              end
              M.sendJson(ackBody)
            end
          else
            -- Unknown request type: do NOT silently drop. Emit a single
            -- diagnostic so the failure mode is debuggable from `ac.log`.
            -- (CodeRabbit on PR #91 — the action branch already replies
            -- with `applied=false`, but the generic dispatch has no
            -- canonical ackType to send here, so we log instead.)
            if ac and type(ac.log) == "function" then
              pcall(ac.log, string.format(
                "[COPILOT][WS-DIAG] unhandled request type=%q (no handler registered)", t))
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
---@param dt number|nil real script.update delta; continues while simTime is frozen in menus
function M.tick(simTime, dt)
  -- Round 10d: record the wall-clock sim time BEFORE any early return so
  -- pollInbound (called by the entry script right after tick) has a fresh
  -- reference for stamping inbound corner_advice entries, and
  -- takeCornerAdvisory has a fresh reference for its 6s staleness check.
  local previousSimT = currentSimT
  currentSimT = tonumber(simTime) or currentSimT
  local elapsed = (type(dt) == "number" and dt == dt and dt >= 0) and dt or nil
  if elapsed ~= nil then
    reconnectElapsed = reconnectElapsed + elapsed
  elseif currentSimT > previousSimT then
    -- Backward-compatible fallback for callers outside script.update (tests/tools): an advancing
    -- sim clock still paces reconnects, while production passes dt for frozen menu clocks.
    reconnectElapsed = reconnectElapsed + (currentSimT - previousSimT)
  end
  if not url or url == "" then
    return
  end
  if sock then
    -- Issue #86 follow-up: retry the v1 hello until the sidecar acks it.
    -- `params.onOpen` is unreliable across CSP builds (some never fire it
    -- on the initial connect, only on later reconnects), and the original
    -- "send hello inline right after web.socket()" pattern dropped silently
    -- because the socket isn't actually writable at that point. The retry
    -- here closes the gap: every tick (rate-limited to 1 s) we resend
    -- hello until we observe a v1 frame back from the sidecar (which sets
    -- `sidecarProtocolReady`), at which point we stop retrying. The sidecar's
    -- `_external_peers.add()` is idempotent so duplicate hellos are no-ops.
    if externalHelloPending and not externalHelloAcked then
      -- Frame-paced retry (see EXTERNAL_HELLO_RETRY_FRAMES note above): immune to
      -- the frozen pit-menu sim clock that previously let the hello be attempted
      -- only once.
      helloRetryFrames = helloRetryFrames + 1
      if helloRetryFrames >= EXTERNAL_HELLO_RETRY_FRAMES then
        helloRetryFrames = 0
        local sent = M.sendJson({
          v = PROTOCOL_VERSION,
          type = "hello",
          client = "ac-copilot-trainer-lua",
        })
        helloSendCount = helloSendCount + 1
        -- Log the first send and then every EXTERNAL_HELLO_LOG_EVERY_SENDS so a
        -- (briefly) unresponsive sidecar cannot spam the CSP console.
        if ac and type(ac.log) == "function"
            and (helloSendCount % EXTERNAL_HELLO_LOG_EVERY_SENDS) == 1 then
          ac.log("[COPILOT][WS-DIAG] hello retry sent=" .. tostring(sent)
            .. " try=" .. tostring(helloSendCount))
        end
      end
    elseif externalHelloAcked then
      externalHelloPending = false
      M.sendSetupExperimentStorePath()
    end
    return
  end
  if reconnectElapsed - lastTry < RECONNECT_SEC then
    return
  end
  lastTry = reconnectElapsed
  tryOpen()
end

--- True when the external WS peer is registered for non-hello client frames.
---
--- Socket presence alone is not enough: the sidecar rejects every frame type
--- other than `hello` until the peer is in `_external_peers` ("peer must send
--- hello before other frame types"). Shared by `publishTopic`, `sendClientFrame`,
--- and the setup/session helpers so those gates cannot drift apart (#671 / PR #171).
---@return boolean
function M.isExternalReady()
  return sock ~= nil and externalHelloAcked == true
end

--- Send a JSON payload over the WebSocket.
---
--- CSP's web.Socket is a polymorphic {close: fun()}|fun(data: binary) -- call
--- it AS A FUNCTION to send data. We try the callable form first, then fall
--- back to :send() / :write() for any non-CSP socket implementation.
---
--- Does NOT gate on `externalHelloAcked` — the hello retry path must keep
--- using this entry point. Non-hello client→server frames use `sendClientFrame`.
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
    setupExperimentStoreSent = false
    setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
    return false
  end
  return true
end

--- Send a non-hello client→server frame once the v1 external peer is registered.
---
--- Returns `false` (not-ready) without touching the socket when
--- `isExternalReady()` is false — distinct from `sendJson`'s send-failure path
--- so a permanently-unacked hello stays visible in WS-DIAG as missing sends
--- rather than a broken socket (#671). Hello itself must keep using `sendJson`.
---@param payload table|nil
---@return boolean
function M.sendClientFrame(payload)
  if not M.isExternalReady() then
    return false
  end
  return M.sendJson(payload)
end

--- Issue #86 Part C/D: external-client `state.snapshot` push.
--- Wraps `M.sendJson` with the v1 envelope expected by the rig screen
--- (`{v=1, type="state.snapshot", topic=<t>, payload=<p>}`). Returns
--- `false` silently when no socket is present so the caller can keep
--- calling unconditionally from a 10 Hz tick without log spam.
---@param topic string  topic name (e.g. "coaching.snapshot", "setup.active")
---@param payload table|nil  topic payload, JSON-encodable
---@return boolean
function M.publishTopic(topic, payload)
  if type(topic) ~= "string" or topic == "" then return false end
  -- Only publish after the v1 hello handshake completes (a non-error v1 frame
  -- seen, so we are in the sidecar's v1 `_external_peers`). Gate via
  -- `isExternalReady()` (v1-specific `externalHelloAcked`), NOT
  -- `sidecarConnected()`/`sidecarProtocolReady` — the latter is also set by the
  -- legacy `protocol=1` flow, and a legacy reply arriving before hello_ack would
  -- otherwise unblock this v1 publish path while we are still unregistered, so
  -- the sidecar would reject the snapshot ("peer must send hello before other
  -- frame types") (chatgpt-codex P1, PR #171). Shared with `sendClientFrame`
  -- so topic and tick gates cannot drift (#671). Early readiness probe avoids
  -- allocating the envelope when gated; the actual send still goes through
  -- `sendClientFrame` so every non-hello client frame shares one transport.
  if not M.isExternalReady() then return false end
  return M.sendClientFrame({
    v = PROTOCOL_VERSION,
    type = "state.snapshot",
    topic = topic,
    payload = payload or {},
  })
end

--- Register the canonical setup experiment JSONL path with the sidecar.
---@param storePath string|nil
---@return boolean
function M.setSetupExperimentStorePath(storePath)
  if type(storePath) ~= "string" or storePath == "" then return false end
  setupExperimentStorePath = storePath
  setupExperimentStoreSent = false
  setupExperimentStoreRetryFrames = SETUP_EXPERIMENT_STORE_RETRY_FRAMES
  if M.isExternalReady() then
    return M.sendSetupExperimentStorePath()
  end
  return true
end

--- Return true when path-bearing frames are allowed to leave the Lua app.
---@return boolean
local function localPathFramesAllowed()
  local u = tostring(url or ""):lower()
  local host = u:match("^wss?://%[([^%]]+)%]") or u:match("^wss?://([^:/]+)")
  if host == "localhost" or host == "::1" then
    return true
  end
  return type(host) == "string" and host:match("^127%.%d+%.%d+%.%d+$") ~= nil
end

--- Send the setup experiment store path after the v1 sidecar handshake.
---@return boolean
function M.sendSetupExperimentStorePath()
  if type(setupExperimentStorePath) ~= "string" or setupExperimentStorePath == "" then return false end
  if setupExperimentStoreSent then return true end
  if not M.isExternalReady() then return false end
  if not localPathFramesAllowed() then return false end
  if setupExperimentStoreRetryFrames < SETUP_EXPERIMENT_STORE_RETRY_FRAMES then
    setupExperimentStoreRetryFrames = setupExperimentStoreRetryFrames + 1
    return false
  end
  local ok = M.sendClientFrame({
    v = PROTOCOL_VERSION,
    type = "setup.experiment.store",
    store_path = setupExperimentStorePath,
  })
  if ok then
    setupExperimentStoreSent = true
    setupExperimentStoreRetryFrames = 0
  end
  return ok
end

--- Notify the Python sidecar that a PR #78 lap archive is available for setup
--- experiment ingestion. Best-effort: if the v1 sidecar registration is not
--- ready, the offline rebuild command can still recover from `journal/laps`.
---@param archivePath string|nil
---@return boolean
function M.sendSetupExperimentRecord(archivePath)
  if type(archivePath) ~= "string" or archivePath == "" then return false end
  if not M.isExternalReady() then return false end
  if not localPathFramesAllowed() then return false end
  return M.sendClientFrame({
    v = PROTOCOL_VERSION,
    type = "setup.experiment.record",
    archive_path = archivePath,
  })
end

--- Ask the Python sidecar to generate a saved post-session review artifact.
---@param lapDir string|nil
---@param sessionUuid string|nil
---@param referenceSource string|nil
---@param referenceFile string|nil
---@return boolean
function M.sendSessionReviewGenerate(lapDir, sessionUuid, referenceSource, referenceFile)
  if type(lapDir) ~= "string" or lapDir == "" then return false end
  if not M.isExternalReady() then return false end
  if not localPathFramesAllowed() then return false end
  local payload = {
    v = PROTOCOL_VERSION,
    type = "session.review.generate",
    lap_dir = lapDir,
    driver_id = "local-driver",
  }
  if type(sessionUuid) == "string" and sessionUuid ~= "" then
    payload.session = sessionUuid
  end
  if type(referenceSource) == "string" and referenceSource ~= "" then
    payload.reference_source = referenceSource
  end
  if type(referenceFile) == "string" and referenceFile ~= "" then
    payload.reference_file = referenceFile
  end
  return M.sendClientFrame(payload)
end

--- Issue #86 Part D: register a handler for an external `request` event
--- (e.g. screen → trainer `setup.list`, `setup.load`). Handler signature
--- mirrors action handlers: `(payload:table|nil) -> (response_payload, error?)`.
--- The bridge takes the returned table and ships it as the matching ack
--- type (`setup.list.result`, `setup.load.ack`).
---@param requestType string  e.g. "setup.list"
---@param ackType string      e.g. "setup.list.result"
---@param fn fun(payload:table|nil):table,string|nil
function M.registerRequestHandler(requestType, ackType, fn)
  if type(requestType) ~= "string" or requestType == "" then return end
  if type(ackType) ~= "string" or ackType == "" then return end
  if type(fn) ~= "function" then return end
  requestHandlers[requestType] = { ackType = ackType, fn = fn }
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
