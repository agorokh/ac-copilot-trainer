---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-13
updated: 2026-07-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/537
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-555-cross-worktree-rig-ownership-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-537-cm-cached-track-relaunch-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-528-pit-start-stall-recovery-2026-07-12.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #537 AC#1 rig verification — two-track live proof PASS; cross-worktree rig collision found (#555)

## Summary

**#537 CLOSED** (2026-07-13). AC#1's live two-track proof ran **on the rig itself** (`AG_PC` —
the session executed there, dissolving the prior macOS→rig SSH blocker without touching keys).
Clean consecutive hands-off pair, `ks_porsche_911_gt3_r_2016`, merged #544 code (`41f4d53` via
worktree at `6731713`):

| Leg | Track | Window | Result | Evidence |
|---|---|---|---|---|
| 1 | magione | 02:37:06–02:39:5x | PASS (2 overlay stalls absorbed by #544 relaunch) | `.scratch/harness-evidence/20260713T093706Z_..._magione/` |
| 2 | spa | 02:40:23–02:43:0x | PASS (1 stall absorbed) | `.scratch/harness-evidence/20260713T094023Z_..._spa/` |

`acpmf_static.track` matched per leg by construction (#535 post-hijack guard passed → drive ran);
HUD captures inspected: trainer tile reads **MAGIONE** / **SPA** respectively, car live on track.
Evidence comment: [#537#issuecomment-4956636834](https://github.com/agorokh/ac-copilot-trainer/issues/537#issuecomment-4956636834).

## Found en route → [#555](https://github.com/agorokh/ac-copilot-trainer/issues/555), now corrected and closed

The original session interpretation—Content Manager spontaneously respawned `acs.exe` after a
harness kill—was disproved by CM's own log. Both apparent respawns were explicit
`acmanager://race/quick` requests from a concurrent #532 worktree. The real defect was missing
machine-global ownership across worktrees. PR #563 (`a195b38`) ships the shared OS rig lock and
structured PID-replacement attribution. R8 content failure was refuted by 3/3 pre-merge and 1/1
merged-main R8/Magione passes. Durable correction:
[[issue-555-cross-worktree-rig-ownership-2026-07-13]].

## Rig ops notes (this session)

- The rig **rebooted at 00:28** mid-session (first magione attempt was pre-reboot; its
  overlay-stall exhaustion at `stage=hijack` is confounded by that).
- A harness-auto-started sidecar orphaned by a failed run can linger, get adopted by the next
  run ("already listening"), then die mid-run → `ConnectionRefusedError` at the WS tap. A
  dedicated long-lived `tools.ai_sidecar` on :8765 avoided it.
- `pyserial` is missing from the repo `.venv` (`No module named 'serial'` — sidecar serial
  transport to COM6/rig-screen retries forever). Surfaced to operator via handoff; not filed.
- The R8 handoff suggestion ("non-extended car per #277") was swapped for the rig-proven 911.
  #555 later proved the R8 was not the cause: cross-worktree session replacement was.
