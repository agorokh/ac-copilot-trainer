---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-22
updated: 2026-07-22
issue: https://github.com/agorokh/ac-copilot-trainer/issues/627
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-630-parts-cde-2026-07-22.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #627 wedge: live forensics — the freeze is back, and §6.1 has an answer

## Summary (2026-07-22, uptime 9.3–9.7 h, same boot)

- **Rate:** 6 froze / 10 launches at 9.3–9.5 h uptime (`--trials`, shipped tool, PR #646) vs
  0/29 below 7.2 h. §6.2 settled: **the reinstall did not fix it**. Uptime-vs-kill-count still
  unseparated (§6.5 caveat stands).
- **3 wedges caught in 3 launches** (catch driver: launch → §2 signature → attach the promoted
  instrument in place). Records: `.scratch/freeze-forensics/wedge-2026072*.json`.
- **Wedge #3 (decisive):** hottest thread WAS the render-stack thread — sustained 2.87–2.88e9
  cycles/s across two S1 windows; 8 RIP samples: **6 in the CSP dll formatting region
  RVA `0x14E0464`–`0x14E7169`, 3 INSIDE the `imul 0x147B` RUNTIME_FUNCTION
  (`0x14e6db0`–`0x14e7355`)**, 2 excursions into an unidentified module `~0x7ff910…`; gfx
  pinned at 45 throughout, physics advancing, process alive. Companion thread 13516 at 2.15e9
  spinning through `RtlQueryPerformanceCounter`/`NtDelayExecution` (`acs+0x238a48`).
- **Wedge #2:** render thread burst-then-parked (one identical wait RIP over 20 s) while another
  thread burned; gfx briefly RESUMED (3097→3307) mid-capture — the wedge can stutter.
- **Wedge #1:** honest refusal (liveness gap) — apparent silent acs exit mid-capture, no WER.

**Reading:** recurrent full-core loop spanning ~27 KB of `accRenderingAdv.dll`'s Dragon4-style
float→decimal region + a second module; not a <4 KiB single-site spin, not a converging
computation. The historical dump is now corroborated live and repeatedly.

## Evidence trail

- [#627 rate comment](https://github.com/agorokh/ac-copilot-trainer/issues/627#issuecomment-5042398361)
- [#627 §6.1 synthesis](https://github.com/agorokh/ac-copilot-trainer/issues/627#issuecomment-5042547613)

## Next steps

- **Upstream CSP report FILED** (operator-authorized 2026-07-22):
  [acc-extension-config#622](https://github.com/ac-custom-shaders-patch/acc-extension-config/issues/622)
  — module identity (0.2.11.0 / `accRenderingAdv.dll` / SHA256 `6546FDF7…`), dual-pass RIP
  evidence, ÷100-reciprocal analysis, rate data, Insider caveat. Watch it for maintainer
  questions; raw records + the 4.8 GB dump were offered.
- Next-boot experiment separating uptime from kill-count (few kills before first measurement).
- Next capture round: persist the cdb `lm` module map in the record to name `0x7ff910…`.

## Instrument learnings (encoded into PR #647 during the night)

Stale-S1 burn conviction (observed live on wedge #2 → end-of-capture resample), pid-bound
liveness with post-read re-check, multi-acs refusal, `--tid` second pass, `.scratch`-scoped
`--json` roots. `find_cdb` needs the Store WinDbg app-execution alias on this rig.
