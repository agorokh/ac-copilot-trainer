---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-13
updated: 2026-07-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/558
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-532-partb-friction-id-2026-07-13.md
---

# #558 — CM launch reliability: a stale Content Manager needs a RESTART, not a URL re-issue

**PR [#559](https://github.com/agorokh/ac-copilot-trainer/pull/559) MERGED** (squash `2cfd662`, 2026-07-13). The recovery half of #537 (which shipped detection + bounded relaunch only).

## Symptom (the "flaky rig")

During #532 Part B live verification, ~8 consecutive launch cycles degraded into: CM serving a cached **Spa** session instead of the requested Magione (#537), `hijack probe … no Car0` pre-drive overlay stalls (#466), and intermittent `acs.exe` `sim_dead` crashes. Every relaunch failed. I first mislabeled this **"rig degraded, needs a reboot"** and handed off — **that was wrong**. The operator restarted **Content Manager** and the very next launch hijacked on probe 1 and drove a clean lap. Root cause = **a stale long-lived CM instance**; recovery = a **CM restart**.

## Root cause

`auto_drive.rig_launch` launches via `ContentManagerActuator`, which hands the `acmanager://race/quick?presetFile=…` URL to the **already-running** CM through single-instance IPC. When that CM instance goes stale it stops honoring the `presetFile` and re-runs its cached last session — and a plain `relaunch()` (which only kills `acs.exe`) re-issues the URL to the **same stale CM**, so it never recovers. NOT an elevation problem: both agent shells verified non-elevated on AG_PC (`IsInRole(Administrator)=False`; CM/Steam run as `arsen`).

## Fix (#559)

- `entry_launcher`: `ContentManagerActuator.restart_content_manager()` kills the CM process tree (`taskkill /IM "Content Manager.exe" /F /T`; `/T` also drops its `acs.exe` child) so the next `launch()` cold-starts a **fresh** CM that honors the preset.
- `auto_drive`: injectable `restart_launcher` seam (`rig_restart_launcher` on the rig). `run_auto_drive` cold-starts a fresh CM before a relaunch when EITHER the previous attempt hit a cached-session mismatch (`restart_cm_next` — restart immediately) OR plain relaunches already failed twice (`attempt_idx >= 2` — persistent overlay-stall degradation). A transient overlay race still gets one plain relaunch first. Bounded by `max_launches`; a restart-seam failure is swallowed (best-effort).

## Verification

- Off-sim: cached-session mismatch restarts CM once before the recovery relaunch; a persistent hijack stall (stall, stall, land) restarts once before the 3rd attempt; a raising restart seam still recovers. `make ci-fast` OK.
- Live (AG_PC, fresh CM): **5 consecutive clean launches** on probe 1 after the operator's CM restart. The closed-loop #532 Part B A/B ran (generic 108.447 s vs identified 107.781 s, no regression). Transient overlay stalls self-recovered via plain relaunch (2 relaunches, no CM restart) — confirming the restart is reserved for persistent/cached staleness. (The auto-restart trigger only fires on a *stale* CM, which cannot be forced deterministically on a healthy one; it is covered off-sim + the recovery action is the operator's proven manual restart.)
- Review: cursor daemon MEDIUM ("launch_mode guard") is a false-positive — `auto_drive` has no `launch_mode`/`acs` path; `rig_launch` is unconditionally CM, so `rig_restart_launcher`'s CM target is correct.

## Lesson

"Rig degraded / needs reboot" was a symptom label, not a diagnosis. The launch path (CM single-instance IPC) had a real, fixable recovery gap. Own the failure → find the mechanism → fix it. The harness IS the deliverable: it must launch reliably, not just when CM happens to be fresh.
