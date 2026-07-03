---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-03
updated: 2026-07-03
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/pr-444-atelier-main-dashboard-2026-07-01.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/432
---

# #432 Racing Atelier — independent in-sim re-verification (2026-07-03)

Autonomous `/autonomous-deliver 432` on `AG_PC`. #432 was already code-complete
(all 5 PRs merged: #437/#444 Part A, #434/#445 Part B, #446 Part C via #86); this
session **re-verified the outcome against live `main` (`9e88794`)** with own tools —
a verification-close, not new implementation.

## Observed evidence (not inherited from pre-merge captures)

- **Part A HUD — VERIFIED live in-sim.** `tools.ac_harness.auto_drive --car
  ks_porsche_911_gt3_r_2016 --track spa` (ggv + racing). `report.json`: `ok:true,
  stage:done`, launched+hijacked, `coaching.snapshot=299–301`, `hud.rendering:true`.
  Inspected frames: **ON PACE** (green clear) full card — `[T3] SPA` brass badge,
  GEAR 6/160, RPM·3635 shift strip, BRAKE POINT 1203 m, 12-cell segment bar → red
  BRAKE ZONE, ENTRY Δ row, brass corner brackets, carbon palette; and **READY @
  brake point 5 m** into La Source — red `IN BRAKE ZONE` cells + amber `TOO SLOW`
  delta. Matches `ingame_hud.png` composition. The 4 post-#444 defects are absent.
- **Single-source-of-truth.** `pytest tests/test_hud_atelier_card.py
  tests/test_rig_screen_racing_atelier.py` → **23 passed**. `git grep FFD700` over
  firmware/lua/launcher → **0** (`UI_ACCENT_GOLD` is now a legacy alias → `UI_BRASS`).
- **Part C data path live.** Game Point sidecar `/health` → `"screen_peers":1`
  (COM6 held) — the rig screen received live Spa coaching during the drives.

## Reusable findings

- **The giant red `BRAKE / TOO HOT — LIFT` verb is a *reference-delta* state.** With
  no reference lap loaded the run reports `delta: not in window`, and the
  reference-independent verb ladder correctly shows ON PACE → SHIFT UP → READY
  (brake-point-driven). To freeze the render-target's dramatic BRAKE verb you must
  load a reference lap so the delta system is active and can call "too hot". The
  brake-state *styling* (red) is still proven by the live brake-zone cells + the
  conformance test.
- **Cold-launch hijack flake ≈ 50 %.** carcsw hijack failed 2/4 cold launches
  (`FAIL stage=hijack: CSP did not accept the carcsw hijack`); ggv + racing both
  drove cleanly when it took (no ~500 m stall this session; 625–931 m, recoveries=0).
  Consistent with the prior "hijack absent on some cold launches" note — no per-run
  hijack-retry flag exists in `auto_drive`; just re-invoke.

## Remaining (single, operator/camera-gated)

On-glass photo of the flashed rig screen vs `esp32_rig.png` — cannot self-verify
(no camera; COM6 render is not echoed over serial). Also #86 acceptance. Everything
else on #432 is observed. Recommend closing #432 after an eyes-on-glass glance.

Evidence bundles: `.scratch/harness-evidence/issue432-hud-verify*/`. Verification
comment: [#432 comment](https://github.com/agorokh/ac-copilot-trainer/issues/432#issuecomment-4874464533).
