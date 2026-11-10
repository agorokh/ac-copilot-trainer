---
type: investigation
status: active
memory_tier: canonical
created: 2026-11-10
updated: 2026-11-10
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-86-pt-long-names-2026-10-18.md
  - AcCopilotTrainer/03_Investigations/issue-627-stable-ac-chain-2026-10-18.md
---

# #86 CSP 0.3.1 FFI `cdata` reset gate and loopback `screen.touch` automation (2026-11-10)

While running autonomous `#86` pit acceptance on the Windows rig (`pc`, CSP `0.3.1` / patch `4302`,
`ks_porsche_911_gt3_r_2016` at `spa`), `acs.exe` reached live pits cleanly (`acpmf_graphics`
`is_live=True`, `is_in_pit=True`, `session.start` `ok=true`), and `setup.spinner.list` returned live
CSP spinners (`source="csp"`), yet `reset_allowed` stayed `false` with
`lock_reason="Reset capability unavailable"`.

## Root cause of the false pit lock

Binary inspection of CSP's `dwrite.dll` alongside `extension/lua/new-modes/pocket-technician/`
showed why CSP's own `PocketTechnician.lua` (`if not ac.isCarResetAllowed() then`) worked while our
trainer refused `setup.load`:

- CSP `0.3.1` exposes `ac.getSetupSpinners` as a Lua C closure (`type(...) == "function"`), but
  binds `ac.isCarResetAllowed` directly via LuaJIT FFI (`type(ac.isCarResetAllowed) == "cdata"`).
- `src/ac_copilot_trainer/modules/setup_library.lua` and duplicate guards in
  `src/ac_copilot_trainer/ac_copilot_trainer.lua` required `type(ac.isCarResetAllowed) == "function"`,
  causing `M.capability()`, `setup.load`, `setup.spinner.set`, and `telemetry.tick.setup_reset_allowed`
  to fail closed even when parked in offline Practice pits.

## Fixes

1. **Callable CSP binding check (`setup_library.lua`, `ac_copilot_trainer.lua`):**
   - Added `isCallable(fn)` in `setup_library.lua` accepting `"function"`, `"cdata"`, and tables or
     userdata with a `__call` metatable. Every call remains wrapped in `pcall(...)` so non-callable
     `cdata` or runtime faults still fail closed.
   - Delegated `setup.load` and `setup.spinner.set` in `ac_copilot_trainer.lua` to
     `setupLibrary.capability()` so all pit/reset checks share one implementation.
2. **Authenticated loopback `screen.touch` / `screen.touch.ack` (`external_protocol.py`, `server.py`, `main.cpp`, `screen_capture.py`):**
   - Added `screen.touch` (tap or smooth `(x, y) -> (to_x, to_y)` scroll drag on the `320x480`
     portrait LVGL input driver) and `screen.touch.ack` so the agent can drive the physical `COM6`
     screen end-to-end on `pc` without human touch delegation.
   - Authorized `screen.touch` with the same loopback HTTP Upgrade gate (`X-AC-Copilot-Client: screen-touch`
     plus `X-AC-Copilot-Token` when configured, excluding `browser` peers) used for `session.start`
     (`#726`), preventing browser peers over `adb reverse` or LAN clients from injecting touches.
   - Real hardware touches (`jc_touch_read`) always preempt synthetic touches in `lv_indev_read_cb`.
