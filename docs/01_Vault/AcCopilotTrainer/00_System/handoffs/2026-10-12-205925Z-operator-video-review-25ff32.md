---
type: handoff
status: draft
memory_tier: canonical
created: 2026-10-12
updated: 2026-10-12
last_updated: 2026-10-12T20:59:25Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/804
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-804-operator-video-review-2026-10-12.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-12-181458Z-operator-driven-rigcheck-f3b1cc.md
---

# Phone video reviewed; physical dynamic telemetry proven, defects remain

User provided C:/Users/arsen/Downloads/IMG_8761.MOV after the initial reply lacked
an attachment. Independently reviewed all 149.19 seconds, local ASR and exact
frames. Main findings and evidence are in the linked investigation and
.scratch/rig-restore/operator-video-review/report.md.

ESP32 dynamic speed/corner/distance/progress is now proven on glass. Remaining
repairs: stale setup bias and misleading pits-only controls; line-category
commands incorrectly becoming LIFT; distance digits wrapping; min/next-corner
target semantics. Do not mark full rig readiness from successful transport.

This was analysis only. No changes deployed, no AC relaunch or driving input,
no new issue or external comments. C1 remains paused, #804 remains open and
Stable AC automatic Drive remains unresolved. Raw media remains local.
These two vault notes are uncommitted local drafts pending the normal review
and SAVE PR flow; prior deployed builds and earlier merged SAVEs are unchanged.
