---
type: handoff
status: active
memory_tier: canonical
created: 2026-08-29
updated: 2026-08-29
last_updated: 2026-08-29T19:06:23Z
pr: https://github.com/agorokh/ac-copilot-trainer/pull/770
issue: https://github.com/agorokh/ac-copilot-trainer/issues/749
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/handoffs/2026-08-29-152241Z-c1-pr766-post-merge-gated-6ed54b.md
  - AcCopilotTrainer/01_Decisions/cold-side-temperature-tagged-friction-refit-2026-08-28.md
  - AcCopilotTrainer/03_Investigations/issue-746-749-repeatability-and-thermal-gate-2026-08-10.md
---

# Post-merge PR #770: C1 pressure cohort from usable-grip rows

## Resume here

1. Keep #749, #750, #751, and #764 open together. Do not mint a new issue or split.
2. Off-rig correctness from #766's reproduced P1 is on `main` at merge `b636830`
   (`_finite_friction_channels` in `ggv_profile.py`).
3. When the Windows rig `100.75.251.87` is online, run the retained #749 second-session
   plant-adoption proof and the #750 three-lap scientist verdict, then close the block.
4. Phase A stash `stash@{0}` (`post-merge-pr770-wip`) is a superseded mid-session handoff
   draft taken on the deleted feature branch. Safe to drop after this node ships.

## Shipped

- PR #770 squash-merged at exact vetted head `7fd1e71`; merge commit `b636830`.
- Local `make ci-fast PYTHON=.venv/bin/python`: 4,103 passed, 75 skipped.
- Inverse-validity test failed on unfixed `main` and passes on `b636830`.
- Independent recompute: thermal-only medians 25/25 psi; friction-valid 20/30 psi.
- Classification: no migrations, env, deps, or workflow flags.
- Advisory antigravity HIGH rebutted on the PR: 80 unique collected tests, 0 shadowed names.

## Still gated

Live #749/#750 acceptance. Rig ping remains 100% loss. Phase B follow-ups: none.
