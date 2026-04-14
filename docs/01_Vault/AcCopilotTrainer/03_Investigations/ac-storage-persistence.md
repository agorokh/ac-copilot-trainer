---
type: investigation
status: active
created: 2026-04-07
updated: 2026-04-08
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# ac.storage persistence

## Finding

CSP `ac.storage(table)` table-form silently fails to persist on some CSP builds. No `.ini` file is ever created in `cfg/extension/state/lua/app/`.

Every other CSP app (CMRT-Essential-HUD, RallyCopilot, CspDebug, RaceHUD, etc.) uses the per-key form `ac.storage("name", default)` which returns an `ac.StoredValue` with `:get()` and `:set()` methods. This form creates a proper `.ini` file and persists across reloads.

## Evidence

```bash
# Other apps have .ini files:
ls cfg/extension/state/lua/app/*.ini
# CMRT-Essential-HUD.ini, RallyCopilot.ini, RaceHUD.ini, ...

# Our app does NOT:
# No AC_Copilot_Trainer.ini exists

# grep for our config keys returns nothing:
grep -r "wsSidecarUrl" cfg/  # empty
```

## Fix

For critical settings that must persist (wsSidecarUrl, approachMeters), use per-key form:

```lua
local _wsUrlStorage = nil
if ac and type(ac.storage) == "function" then
  local ok, sv = pcall(ac.storage, "ac_copilot_trainer.wsSidecarUrl_v1", "")
  if ok and sv and type(sv.get) == "function" then
    _wsUrlStorage = sv
  end
end
```

The table-form `ac.storage(defaults)` can remain as the in-memory config table for non-critical settings that reset to defaults on each reload.
