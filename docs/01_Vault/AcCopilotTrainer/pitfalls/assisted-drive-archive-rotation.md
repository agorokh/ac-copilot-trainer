---
type: pitfall
status: active
created: 2026-10-17
updated: 2026-10-17
severity: data-loss
origin: human-curated
domains: [rig, harness, persistence]
scope_paths:
  - tools/ac_harness/auto_drive.py
  - src/ac_copilot_trainer/modules/lap_archive.lua
relates_to:
  - AcCopilotTrainer/pitfalls/_index.md
  - AcCopilotTrainer/03_Investigations/issue-854-remote-inference-2026-10-17.md
---

# Assisted drives evict personal laps through archive rotation

## Pattern

`lap_archive.rotate` runs after **every** completed lap and `os.remove`s the oldest
in-game archives until the journal is under its disk cap (500 MB default). The personal
journal sits at that cap, so any completed lap — including an autonomous/assisted one —
permanently deletes the oldest personal lap (no Recycle Bin). `auto_drive` does not
disable archiving itself; protection depends on the operator's procedure.

Observed 2026-10-17 (#854): an unguarded `auto_drive --wait-lap` acceptance drive saved
one assisted lap and evicted `lap_20261012-185218_…`; it also rewrote the combo history
and CM rewrote `video.ini` bytes at launch. Restored exactly from a preserved copy and
the Part B snapshots; the assisted lap was quarantined.

## Rule

For any assisted drive that is not meant to produce archives:

1. Snapshot the lap manifest (name → SHA-256), combo file and `video.ini`; keep a full
   copy of `journal/laps` when no preserved copy exists.
2. After the trainer peer connects and **before the first lap**, send authenticated
   `config.set lapArchiveEnabled=false` and require `config.get` readback `false`
   (each new game). If it cannot be confirmed, stop the game before a lap completes.
3. Restore `true` with readback before closing; then compare the manifest, quarantine
   anything new, restore anything missing, and restore combo/video bytes.

Do not make archive-off a blanket harness default: the #529 alien pipeline needs
assisted archives for plant refits. The guard belongs to the run's purpose.
Reference implementation: `.scratch/inference854/ab_run.py` on the rig (Part B kit lineage).
