---
type: investigation
status: resolved
memory_tier: archive
topic: "Issue #596 autonomous-drive reliability"
related_issues: [596]
related_prs: [598, 600]
last_updated: 2026-07-15
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-596-partc-actionable-reason-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/issue-528-pit-start-stall-recovery-2026-07-12.md
  - AcCopilotTrainer/03_Investigations/issue-555-cross-worktree-rig-ownership-2026-07-13.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Issue #596: high-gear stall and bounded sim-death recovery

## Outcome

Issue [#596](https://github.com/agorokh/ac-copilot-trainer/issues/596) is **CLOSED**. PR
[#600](https://github.com/agorokh/ac-copilot-trainer/pull/600) merged to `main` as
[`613fae2`](https://github.com/agorokh/ac-copilot-trainer/commit/613fae2ef4fe7ec3489800b13751f199185de7ce)
at 2026-07-15T17:24:57Z. Part C shipped earlier through PR #598.

## Root cause and fix

The 450–580 m stall was a gear/speed feedback latch, not a recovery-cap defect. At low RPM in AC
gear 4/5, `RacingDriver._gear_pulse` required `speed_kmh > 5` before requesting a downshift. A car
that had over-slowed to 0 km/h in that gear could not accelerate past 5 km/h and therefore could
never request the downshift needed to move. Downshifts now gate on low RPM plus the existing pulse
cooldown; `gear > 2` still stops at first gear and never selects neutral/reverse. A mutation-first
test reproduced the old stationary-high-gear failure before the one-line behavioral fix.

`auto_drive` also gained a bounded 2 Hz control trace (state, commands, phase, recovery events) and
one full launch→hijack→drive→tap retry after a pure `acs.exe` death. The machine-global rig lock is
held across attempts. Each full attempt remains in `report.json`; a recovered crash is measurable,
not laundered into an unexplained PASS. Session replacement, recovery cap, `--skip-launch`, and
raised pipeline errors remain terminal.

## Live rig proof

- The issue's 6-run sample plus 7 new natural PR-branch drive runs gives a **13-run measured
  history**. Raw `acs.exe` deaths were **2/13**, both in the original sample; the new natural sample
  was **0/7**.
- Post-fix practice starts passed on BMW M3 GT2 at Magione and Imola and Ferrari 458 GT2 at
  Magione. Completed distances were 724–3,093 m with zero recovery caps.
- No trace contained a stopped-high-gear sample after 100 m. Representative crossings of the
  original stall region: M3/Magione 454.3 m at 92.4 km/h in 4th; Ferrari/Magione 461.7 m at
  79.6 km/h in 2nd; M3/Imola 454.1 m at 200.6 km/h.
- Controlled death proof: live PID 18868 was killed after 284 m. Attempt 1 recorded
  `acpmf_physics packet_id stagnant (acs.exe died)` and 36 trace samples; the bounded retry launched
  PID 936 and passed at 2,295 m with 178 samples. One evidence bundle retained both attempts.
- Every completed run's HUD capture reported rendering and was visually inspected.

## Verification and review

Focused harness/driver suite: **211 passed**. Full `make ci-fast`: **2,963 passed, 113 skipped,
87.61% coverage**, with Ruff, Bandit, and policy checks clean. GitHub required checks passed;
GraphQL had zero review threads; the resolve-gate ledger was clean; the current-SHA self-hosted
review reported no medium-or-higher findings after the required 10-minute cooldown.

## Merged-main rig reconciliation

After PR #600 and the vault SAVE merged, `main` at `acefe87f299ce5ac0902a5bac632499487605e7e`
was exercised again on the real rig. BMW M3 GT2 / Magione / GGV passed a 120-second drive window
at 2,875.7 m and 210.7 km/h with one completed lap, zero recoveries, no recovery cap, no sim death,
one attempt, 217 bounded control-trace samples, a rendering HUD, and a healthy telemetry/coaching
pipeline.

A preceding 70-second probe crossed the original 450 m band, then entered pit-box geometry near
513 m and invoked three recoveries before its timer expired. That short-run PASS was treated as a
warning rather than proof; the extended fresh launch above completed the lap without a recovery.
The final evidence was also attached to issue #596.

## Separable rig findings

- Porsche `ks_porsche_911_gt3_r_2016` launch trials were excluded before the drive denominator.
  CSP crash reports state the local car is damaged and its LODs list is missing; the install also
  lacks `data.acd`. Follow-up: [#603](https://github.com/agorokh/ac-copilot-trainer/issues/603).
- The configured realtime voice bank could not initialize `rtmixer` (`Invalid number of channels`),
  so those harness sidecars continued with voice disabled. This did not affect drive/pipeline
  verdicts. Follow-up: [#602](https://github.com/agorokh/ac-copilot-trainer/issues/602).
- Post-merge worktree cleanup remains blocked by a Windows bug in the hub remover: it rejects
  `C:/Users/...` as "not absolute". The merged worktree was clean; it was deliberately preserved.
  Follow-up: [template-repo#515](https://github.com/agorokh/template-repo/issues/515).
