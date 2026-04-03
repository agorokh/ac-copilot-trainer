---
date: 2026-04-03
topic: coaching-render-diag
status: approved
---

# Coaching visibility, BMW font, render diagnostics gating, brake wall height

## Problem frame

Drivers see confusing **world-space debug geometry** for the first ~60s of every session (red/green spheres, blue vertical line) from `render_diag.lua`, which reads like a broken “schema” on track. **Coaching hints** are easy to miss: they use default ImGui scale, live primarily in the separate **Coaching** window, and the pre-lap fallback is faint. Brake marker **walls** are acceptable but should be slightly taller.

## Goals

1. **Render diagnostics:** Gate all `render_diag` behavior (tick, Draw3D, UI) behind `config.enableRenderDiagnostics`, default **false**. When true, preserve current troubleshooting behavior (including visual checkpoints).
2. **Coaching UX:** Large, high-contrast text on a dark semi-transparent panel; use **BMW** font from game `content/fonts` when resolvable (parse `bmw.txt` → actual font file; load via CSP font APIs; fallback if missing). **Primary hint** duplicated in **main** app window when coaching is active so users who only open `WINDOW_0` still see coaching; full multi-hint surface remains in Coaching window.
3. **Brake markers:** Increase `WALL_HEIGHT` in `track_markers.lua` modestly (e.g. 0.6 → ~0.85–1.0), tune in-game.

## Non-goals

- Hardcoding absolute Steam paths in repo.
- Changing racing-line or brake-detection algorithms beyond wall height.
- Replacing `render_diag` with a different telemetry system.

## Success criteria (testable)

- Cold session with diagnostics **off**: no red/green/blue debug shapes or `[DIAG]` UI panel for 60s.
- With diagnostics **on**: prior behavior restored (visual + logs).
- After at least one lap with hints: coaching visible with large readable type and dark transparent panel; BMW face when font loads.
- Main window open only: at least **one** prominent coaching line visible when hints active.
- Brake walls visibly taller; existing fade/cull unchanged in spirit.

## Implementation pointers (for planning)

- Files: `ac_copilot_trainer.lua` (config, hooks), `modules/render_diag.lua` (optional: respect external gate), `modules/coaching_overlay.lua`, `modules/hud.lua`, `manifest.ini` (window sizing flags if needed), `modules/track_markers.lua` (`WALL_HEIGHT`).
- Font: resolve via `ac.getFolder` (or equivalent) + relative paths under AC install; never commit proprietary font binaries.

## Related

- GitHub Issue: https://github.com/agorokh/ac-copilot-trainer/issues/41
- Brainstorm approval: user confirmed diagnostic artifact **A** (render_diag), then approved full design 2026-04-03.
