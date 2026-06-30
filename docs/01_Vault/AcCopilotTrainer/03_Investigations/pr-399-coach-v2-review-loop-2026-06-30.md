---
type: investigation
status: active
created: 2026-06-30
updated: 2026-06-30
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/03_Investigations/coach-v2-real-coaching-2026-06-29.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# PR #399 Coach v2 — review resolution loop (2026-06-30)

## Status

PR [#399](https://github.com/agorokh/ac-copilot-trainer/pull/399) is **OPEN, merge-ready** on head
[`2908fc6`](https://github.com/agorokh/ac-copilot-trainer/commit/2908fc61fed5a43f489f422671a9234751d6406b)
(`feat/coach-v2-real-coaching`, closes #396). CI green (`build`, `Canonical docs exist`,
`conformance`; `guard-and-automerge` skipped). GraphQL review threads resolved; resolve-gate clean.

## Resolution work

- Merged `origin/main` — `server.py` conflict: kept Coach v2 wiring + main's `_exception_detail`
  reference-load errors (was `DIRTY`, blocked CI).
- Renamed PR title to `feat(coach): …` (`ci-conventional`).
- Qodo inline #1: linked `coach-v2-real-coaching-2026-06-29.md` in investigations `_index.md`.
- Qodo inline #2 / summary: lap-counter-aware wrap detection (codex #294).
- Qodo summary #3: skip PRIME/accumulate while `_pending_wrap_finals` (teleport/rewind frame).
- Qodo summary #4: `_advance_lap_after_wrap()` — finalize passes before `ledger.begin_lap()`.
- Qodo summary #5: removed `LATE_BRAKE` from `_GRIP_GATED_ROOTS` + regression tests.

## Verification

Local `make ci-fast`: 1961 passed, 75 skipped. Qodo re-review on `8e6135a`: Bugs (0).
