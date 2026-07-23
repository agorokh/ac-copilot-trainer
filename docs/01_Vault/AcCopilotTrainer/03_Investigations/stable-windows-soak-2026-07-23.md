---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-23
updated: 2026-07-23
issue: https://github.com/agorokh/ac-copilot-trainer/issues/627
relates_to:
  - AcCopilotTrainer/03_Investigations/wedge-live-forensics-2026-07-22.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #627: stable-Windows night — §6.3 killed; the accumulator is launch-cycle count, not uptime

## Result (2026-07-23, single boot, build 26200.8894 stable 25H2)

Zero-kill soak to 9.3 h, then 20 launches: **launches 1–7 clean; freezes at 8, 11, 14, 16
(each exactly 15.4 s, fast init shape); launches 17–20 clean** (5-min holds, no catch).
Records: `.scratch/freeze-forensics/trials-zerokill-26200-20260723.json`, `trials-battery2-*`.

## Settled

- **§6.3 DEAD** — 4 freezes on stable Windows; not Insider-specific. Upstream
  [#622 updated](https://github.com/ac-custom-shaders-patch/acc-extension-config/issues/622#issuecomment-5059324698).
- **Uptime alone is not the driver** — last boot froze by launch ~3–5 @9.37 h; this boot's
  launch 1 @9.33 h (0 prior kills) clean through launch 7 @9.61 h. §3.4's uptime correlation
  is really **accumulated launch/kill cycles**.
- **Accumulation is not monotonic** — 17–20 clean right after the freeze cluster; those were
  5-min holds vs 165 s trials (bursty propensity vs hold-duration drain: undecided).
- Accumulator is NOT on disk in the AC install (nothing persisted across 16 kills; no
  `extension/state` here); only per-cycle writer found: CM's `Values.data` (CM = one
  long-lived process per boot).

## Next experiments (order of leverage) — see [#627 synthesis](https://github.com/agorokh/ac-copilot-trainer/issues/627#issuecomment-5059322044)

1. **CM-restart reset test** when freezes recur (accumulator in CM process state?).
2. **Hold-duration test** (165 s vs 300 s holds — does session lifetime drain it?).
3. **Graceful-exit test** (ESC-quit battery — if clean exits don't accumulate, launcher
   teardown change becomes the operational fix).

Rig left clean. Freeze-instrument records are `freeze-forensics-capture/v1.1` (module map)
as of PR #663 — next caught wedge names the `0x7ff910…` module automatically.
