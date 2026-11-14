---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-23
updated: 2026-06-23
issue: https://github.com/agorokh/ac-copilot-trainer/issues/305
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/pr-78-sidecar-autolaunch-lap-archive.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# PR #309 — last lap's trace lost on session end (issue #305)

**Merged:** squash [`86c5f60`](https://github.com/agorokh/ac-copilot-trainer/commit/86c5f60) (2026-06-23), PR #309. **Issue #305 stays OPEN** pending live rig confirmation.

## Symptom

A clean flying lap that is **not followed by another completed lap** (driver does a hot lap then
pits/stops, or an automated capture run ends) leaves only a ~923-byte / 0 KB stub archive — the trace
rows never persist. The HUD times the lap correctly (e.g. `Best/Last 1:22.55`), and the *outlap*
(followed by the flying lap) always writes a full ~655 KB trace. Reproduced twice on the rig
(2026-06-22) from a fresh `acmanager://` launch.

## Root cause (capture/flush, not analysis)

The per-lap archive job is queued at the S/F crossing that **completes** a lap
(`queueLapArchiveJob`, `ac_copilot_trainer.lua`) and pumped a few rows per frame by
`pumpLapArchiveJobs()` (`LAP_ARCHIVE_ROWS_PER_FRAME = 64`, ~32 frames for a 2000-sample trace). When
the session ends, `script.update()` enters the `if sim.isInMainMenu then` branch and **`return`s
before ever reaching the per-frame pump** — so the *last* lap's queued job is abandoned mid-stream as a
partial `.tmp` (never renamed to `.json`). The outlap survived only because ~82 s of flying-lap frames
pumped it to completion. `resetRuntimeAfterLeavingTrack` never drains or clears the queue, so once in
the menu the job is stranded.

The job streams to a `.tmp` and renames on `_finish` only; a `samplesCount==0` job would instead
finish immediately as a complete envelope-only `.json` stub — the second, defensive variant.

## Fix

1. **`flushPendingLapArchiveJobs(reason)`** (`ac_copilot_trainer.lua`) — synchronously force-completes
   every pending job (`pumpLapArchiveJobs` gained an optional row budget; the flush passes
   `LAP_ARCHIVE_FLUSH_ROWS = 1_000_000`, so one step finishes a job; a 4096-iteration cap +
   `before == after` fallback make a spin impossible). Wired into the session-end branch, gated on
   `state.wasDriving` (a job can only be queued while driving) so it runs once on the driving→menu
   transition, before `resetRuntimeAfterLeavingTrack`.
2. **Stub guard** (`lap_archive.lua`) — `createWriteJob` returns `(nil, reason)` when
   `samplesCount <= 0`, so a traceless archive is never staged.

## Verification

- **Offline only** (macOS; rig is AG_PC/Windows): full suite **1334 passed**, `make ci-fast` green
  (ruff, bandit, CSP-API, CSP-UI-safety, policy, secrets, conventional). lupa behavioral tests cover
  empty-trace refusal, one-step full drain, and multi-job flush orchestration; a lupa-independent
  source-structure guard pins the session-end wiring. Proved the stub-guard test **fails on pre-fix
  `origin/main`**. A 5-lens adversarial-review workflow (19 raw → 3 confirmed, all test-hygiene) was
  addressed; no correctness/Lua/regression finding survived skeptic verification.
- **REMAINING (rig-gated):** drive ≥1 flying lap, return to the menu / end the session without
  another lap, confirm a **full-trace** `lap_*.json` for that lap under `journal/laps/`. Same class as
  the #277 live-activation step.

## Notes / follow-ups

- The per-frame deferred pump (#246/#249) was intentional to avoid render-thread flushing; the
  synchronous drain only runs at session end (one frame, leaving the track), preserving that intent.
- **Out of scope (filed as a spawn-task chip):** `ops/memory_manifest.yml` still has the template
  placeholder workspace `example_kb_workspace`, so the Tier-3 prefetch errors every SessionStart and
  never stamps the memory gate. Real workspace is `ac_copilot`.
