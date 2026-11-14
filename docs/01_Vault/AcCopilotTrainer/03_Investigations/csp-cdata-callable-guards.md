---
type: investigation
status: active
created: 2026-04-07
updated: 2026-04-08
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# CSP cdata-callable guards

## Finding

In CSP/LuaJIT, `vec2`, `rgbm`, and many `ui.*` rendering primitives (e.g. `ui.windowSize`) are FFI cdata callables. `type(fn)` returns `"cdata"`, NOT `"function"`.

Guards like `if type(vec2) ~= "function" then return end` silently reject real, working APIs and cause both HUD windows to render nothing.

## Evidence

```
[COPILOT][HUD-DIAG] win0 vec2=cdata rgbm=cdata drawRectFilled=function windowSize=cdata
[COPILOT][OV-DIAG] win1 GUARD-RETURN ui=table vec2=cdata
```

Some `ui.*` methods ARE regular functions (e.g. `ui.drawRectFilled`, `ui.checkbox`). Others are cdata (e.g. `ui.windowSize`). No shipped CSP app uses `type()` checks for these.

## Fix

Replace `type(X) ~= "function"` with `X == nil` for all CSP-provided constructors and API functions. Zero shipped CSP apps use `web.socket` or `type(vec2)` checks — we are the pioneer.

## Scope

Affected files: `hud.lua`, `coaching_overlay.lua`, `coaching_font.lua`, `render_diag.lua`.
