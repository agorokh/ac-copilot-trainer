---
type: investigation
status: complete
memory_tier: canonical
created: 2026-07-16
updated: 2026-07-16
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-603-car-content-preflight-2026-07-15.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# Rig maintenance — restored `ks_porsche_911_gt3_r_2016/data.acd` (2026-07-16)

## Symptom

Operator report: tablet dash "not working at all" and the primary test Porsche fails to launch.
Content Manager dialog: *car "ks_porsche_911_gt3_r_2016" is damaged, LODs list is missing* —
suspected as a code regression from the 2026-07-15 merges.

## Root cause (rig content, NOT a code regression)

`%AC_ROOT%\content\cars\ks_porsche_911_gt3_r_2016\` had **no `data.acd` and no unpacked `data/`**
— only `data.acd~cm_bak_ep` (241,806 B). The `~cm_bak_ep` suffix is Content Manager's backup made
when its **extended-physics data patch** rewrites car data: CM renamed the original away and the
patched replacement never landed (folder mtime 2026-07-14 23:47). With zero data sources, AC cannot
read `lods.ini` → the "LODs list is missing" dialog. This is the same damage the #596 rig session
observed on 2026-07-15 and #603 turned into a launch preflight (PR #607). The 07-15 merges only
*detect* the condition; they did not cause it.

The tablet dash was collateral: sidecar healthy (`/health` ok, `/tablet/dash` → 200, screen peer
connected) but no race ever launched, so it had no telemetry to render.

## Fix

- Verified `data.acd~cm_bak_ep` decodes as a valid packed ACD via `tools.ac_content.unpack_acd`
  (70 members, `lods.ini` with LOD_0..3, all referenced `.kn5` present on disk).
- **Copied** it back to `data.acd` (backup file preserved, byte-identical).
- `python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016 --track magione
  --preflight-only` → `preflight ok`, app provenance `match`.

## Prevention

Before launching this car from CM, leave "extended physics (experimental)" **unchecked** for car
data — the CM patch path is what renamed `data.acd` away. If the patch is ever wanted, confirm
`data.acd` (or a complete unpacked `data/`) exists afterwards, or run the #603
`--preflight-only` gate before driving.
