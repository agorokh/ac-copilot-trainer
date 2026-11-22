---
type: handoff
status: active
created: 2026-11-22
updated: 2026-11-22
issue: https://github.com/agorokh/ac-copilot-trainer/issues/957
relates_to:
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-21-195910Z-issue988-offline-corpus-ac8e7e.md
---

# #957 condition-matched progression audit

The November 21 operator instruction removed the hold on implementing the
offline audit. The issue title and body now reflect that instruction. The audit
and optional session-review JSON path are in [PR #1017](https://github.com/agorokh/ac-copilot-trainer/pull/1017).

| Retained clause | Observed result |
|---|---|
| Audit the qualified corpus, missing confounders and per-stratum support | The CLI and session-review fixtures produced the same result from the same eight fabricated sessions. The rig audit read 202 files with zero unreadable. |
| Abstain with a specific reason when matching or independent session support fails | Tested split-crossing sessions, identity collisions, unknown and occupied traffic, missing assists and temperatures, and repeated laps from two later sessions. The rig audit returned `cannot_identify` with `no_complete_human_qualified_traffic_clean_sessions`. |
| Run the frozen 1,000-trial null, nuisance and 200–500 ms shift calibrations | Supported fixtures exercised both calibration outcomes and published the 200 ms estimate only after the successful run. The actual rig corpus produced `calibration.status = inconclusive` before estimation. |

The documented rig SSH path ran the audit CLI from stdin
over the existing Assetto Corsa journal. The smoke comparison used Porsche
911 GT3 R 2016 at Magione and a November 15 UTC split. It excluded 11 sessions
and retained zero. All 23 archives for the combo lacked positive traffic
clearance, complete thermal conditions and an assists configuration. Four
lacked a setup hash. An
independent corpus inventory using `ArchiveQualificationSnapshot` counted
142 shared, 33 AI and 27 legacy-unknown archive decisions, with zero
human-qualified, traffic-clear sessions across combos. The aggregate audit
receipt is `.scratch/issue957-rig-audit-summary.json`. No simulator or
attestation settings changed.

The audit requires the recorded assists configuration. The current native
archive producer has no complete assists block. Captures missing it cannot
qualify for a matched estimate. Review and merge remain under PR #1017.
Real-data calibration can run when an existing combo has complete qualifying
captures in at least one stratum with three independent sessions in each period.
No adjacent issue or agent was created.
