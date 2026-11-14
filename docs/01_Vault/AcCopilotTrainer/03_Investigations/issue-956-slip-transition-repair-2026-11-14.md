---
type: investigation
status: active
created: 2026-11-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/956
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-956-slip-feedback-pilot-2026-11-13.md
  - AcCopilotTrainer/03_Investigations/issue-956-autonomous-acceptance-proposal-2026-11-12.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Native pilot stop and startup projection correction

PR980 passed exact-head independent review and all four canonical merge gates;
merge35004ded660b8677df06b61beef4b20c39d8122f was built and verified against its
actual packaged code. EXE SHA256
ac5926823cfbb04b030cac3b206c73ac58f16e0e1cf04f69a639c4f9f81132d5 was deployed
under the owned lease. Firmware and all seven protected guard modules stayed
unchanged. The bound registration was published before native capture:
https://github.com/agorokh/ac-copilot-trainer/issues/956#issuecomment-6871304829.

Run2d25b588b6d34e428c11e0a79a31851a staged the fixed G1 conditions and passed
Car0 on its first probe. Actual command/physics observations then showed repeated
throttle release/reapplication around18kmh and0completed native laps. The pilot
was stopped through normal Escape pause, without tuning, retry or replacement.
The resulting stale-physics exception was the intentional stop mechanism.
The report's default `drive did not run` stats lost the interrupted drive stats;
independent read-only receipts retain proof of its actual movement and commands.
No raw lap was exported, case enrolled, candidate revealed/ARM requested, or
actor timer started. T3 and all scored/safety cases were not run: INCONCLUSIVE,0/12.

## Demonstrated software defect

The governor masked slip to0 below5m/s, then differentiated a real moving sample
against that synthetic zero. At native control cadence the invented derivative
could consume the entire bounded projection and collapse the pedal ceiling.
An identical off-rig stream at4.99/5.01m/s,5ms intervals and constant actual2%
slip gives last100 mean pedal1.0 at constant speed but0.00375 with crossings.
The defect is present at PR980 entry95ca495, reviewed headb4e2a6a and merged
candidate35004de; the pre-feature base's ordinary GGV output does not collapse.

Discard derivative history while startup masking is active. The first moving
sample establishes history and still receives the direct measured-slip clamp;
subsequent valid moving samples retain bounded prediction. Every numeric onset,
recovery, ramp, freshness and projection limit stays unchanged. New regressions
first fail on both gas/brake crossings, then pass after correction, while real
high slip is still cut on the first moving sample. This proves the software
counterexample is repaired; it does not prove native driving or acceptance.

Council advice was2/6 answered,4provider errors, quorum2/3 unmet. Adopt its
boundary/re-entry checks; the suggestion that the demonstrated counterexample
cannot be corrected by discarding masked history is refuted by the identical
before/after stream. Do not infer that all real high-slip oscillations disappear.
Do not smooth away the direct clamp or change thresholds. Automatic exact-head
PR review and CI remain required independently of this advisory panel.

## Measured stop, preservation and budget

Outcome: https://github.com/agorokh/ac-copilot-trainer/issues/956#issuecomment-6871550584.
Native post-stop attempts/writes/setup_load/ini_write/csp_setter were all0;
all four cold pressures stayed26psi. Restoration verified202 originals and
matching durable hashes, unchanged attribution prefix, exact CSP/race/assists,
unchanged settings/selected setup, restored archive capacity, removed unchanged
owned setup copies, absent permit and released owner. Actual normal health was
disabled/unconfigured; the native screen showed pressure experiment inactive,
abstention/no setup change and disabled Accept/Reject. Owned apps/children exited
and8765 was exclusively rebound. Receipts are under the original9e9f checkout's
`.scratch/issue956/operator-acceptance/20261114T035521Z-approved-ai-bench/`.

This epoch consumed1072.2103145s; cumulative12287.7834329s of14400, leaving
2112.2165671s before any later deployment lease. Another genuine unit requires
1380+370+860.227089=2610.227089s before startup, so it cannot fit. No new pilot
registration, native retry, guard exception or cap reset follows this correction.
Normal experiment remains disabled and956 OPEN. Human UX and lap benefit remain
unmeasured. Further real acceptance remains incomplete under the current cap.
