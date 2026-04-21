---
type: investigation
status: active
created: 2026-04-07
updated: 2026-04-08
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# CSP web.socket API

## Finding

CSP's `web.socket` is callback-based, NOT request/response or pull-based.

### Correct API (from lua-sdk lib.lua lines 6712-6722)

```lua
local sock = web.socket(url, onRecvCallback, {
  onError = function(err) end,
  onClose = function(reason) end,
  encoding = "utf8",
  reconnect = true,
})
-- SEND: call the socket AS A FUNCTION
sock(jsonString)
-- RECV: pushed to onRecvCallback, NOT pulled via receive()
-- CLOSE: sock:close()
```

### reconnect flag

- `reconnect = false`: CSP drops socket silently on any glitch.
- `reconnect = true`: CSP auto-reconnects. onClose only fires on explicit close.

## Clock caveat

`os.clock()` in Lua returns process CPU time, NOT wall-clock. For staleness checks, use `sim.gameTime` passed through via `wsBridge.tick(simT)`.
