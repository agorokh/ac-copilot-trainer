---
type: handoff
status: active
created: 2026-11-10
updated: 2026-11-10
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
pr: https://github.com/agorokh/ac-copilot-trainer/pull/949
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-86-screen-touch-and-cdata-gate-2026-11-10.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-10-185600Z-backlog-steward-reconcile-c4a91e.md
---

# #86 post-merge (PR #949): CSP cdata reset gate and loopback screen.touch

[PR #949](https://github.com/agorokh/ac-copilot-trainer/pull/949) merged into `main` as `185414db16412241d935e601b80f62d868dc62b1` (`185414d`) from vetted head `e1f356b96df7cdb6a971c8db92fded6d0e35c200` (`e1f356b`, author vendor `google`, reviewed clean on exact head by gating lenses `cursor` and `grok` plus `antigravity`). Issue [#86](https://github.com/agorokh/ac-copilot-trainer/issues/86) intentionally remains `OPEN` (`Refs #86`) pending live deployment and the four-leg Spa pit-capture acceptance run on `pc` + `COM6`.

## Delivered

- **CSP 0.3+ LuaJIT FFI `cdata` callable support (`src/ac_copilot_trainer/modules/setup_library.lua`, `src/ac_copilot_trainer/ac_copilot_trainer.lua`)**:
  - Added `isCallable(fn)` accepting `"function"`, `"cdata"`, and `__call` metatables while wrapping calls in `pcall(...)` so non-callable `cdata` still fails closed.
  - Delegated `setup.load` and `setup.spinner.set` reset gating in `ac_copilot_trainer.lua` to `setupLibrary.capability()` as single source of truth.
- **Authenticated loopback-only `screen.touch` / `screen.touch.ack` (`tools/ai_sidecar/external_protocol.py`, `tools/ai_sidecar/server.py`, `firmware/screen/src/main.cpp`, `tools/screen_capture.py`)**:
  - Added bounded `320x480` tap and smooth `(x0, y0) -> (x1, y1)` drag injection (`20..1000` ms hold), authorized strictly on HTTP Upgrade for loopback non-browser `client_id == "screen-touch"` peers presenting `AC_COPILOT_SIDECAR_TOKEN`.
  - Physical `jc_touch_read` touches always preempt synthetic input in `lv_indev_read_cb` and emit an error ack.
  - Added `--touch X Y`, `--drag X1 Y1 X2 Y2`, `--hold-ms`, and `--settle-ms` to `python -m tools.screen_capture`.
- **Tests & pre-flash simulator verification (`tests/test_setup_library_summary.py`, `tests/test_screen_capture.py`)**:
  - `make ci-fast` (`5,318 passed`), `make ci-screen` (`127 assertions` on `pc` and Linux CI), and `pio run -d firmware/screen -e jc3248w535_serial` all passed.

## Post-merge classification & deployment boundary

- `scripts/post_merge_classify.py --pr 949`: `No post-merge classification flags for these paths.`
- **Deployment boundary (`pc` + `COM6`):** Pull `185414d` on `pc` (updating `apps\lua\AC_Copilot_Trainer` via junction), flash `COM6` (`pio run -d firmware/screen -e jc3248w535_serial -t upload`), rebuild `dist\AC-Copilot-Game-Point.exe`, and execute the four-leg Spa (`ks_porsche_911_gt3_r_2016`) pit-capture walkthrough directly on `pc`.

## Remaining / Next action

- Execute `pc` + `COM6` deployment and the four-leg Spa pit-capture walkthrough (**Launcher → AC Copilot live hints → Pocket Technician setup load in pits → Setup Exchange browse/download/install → PT load**), inspect PT/SE glyph readability on the physical `COM6` captures, commit durable evidence + `#401`/`Roadmap.md` closure, and close `#86`.
