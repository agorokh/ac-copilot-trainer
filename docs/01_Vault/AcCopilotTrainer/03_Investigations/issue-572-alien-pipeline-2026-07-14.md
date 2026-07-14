---
type: investigation
status: resolved
memory_tier: canonical
created: 2026-07-14
updated: 2026-07-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/572
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/issue-543-uncertainty-aware-plant-id-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/issue-532-partb-friction-id-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/frontier-controller-ggv-2026-06-19.md
---

# #572 — one-button alien pipeline (EPIC #529 P2)

**Issue [#572](https://github.com/agorokh/ac-copilot-trainer/issues/572) CLOSED by PR
[#573](https://github.com/agorokh/ac-copilot-trainer/pull/573)** (squash
[`dfd4b7e`](https://github.com/agorokh/ac-copilot-trainer/commit/dfd4b7e), 2026-07-14).

## Shipped contract

- `python -m tools.ac_harness.auto_alien --car <car> --track <track>` is the one-button path:
  ensures the combo's identified plant (runs the #532/#543 handshake+ID session when the shared
  readiness gate fails), lets the sidecar port settle between stages, then drives the optimized
  line via `auto_drive --driver alien`; composed `alien_report.json` names each stage's verdict.
- `tools/ac_harness/alien_line.py` owns the per-combo optimized-line artifact: min-curvature QP
  bounded by the validated `fast_lane.ai` corridor + QSS profile against the identified
  uncertainty-aware GGVModel; persisted under `Documents/Assetto Corsa/alien_line/` keyed by the
  plant identity stem + plant-fit and fast_lane content hashes; hash-matched caches are
  content-revalidated (corridor bounds + plant envelope) before being driven.
- `plant_id.plant_ready_for_full_consumption(artifact, require_friction_fit=…)` is the single
  readiness gate shared by the alien resolution, the alien preflight, and
  `auto_alien.needs_identification` (daemon HIGH: the three sites must never drift).
- All plant/line resolution runs AFTER preflight + the machine-global rig lock (peer-worktree
  re-identification is picked up from on-disk state); `--ggv-scale` outside (0,1] is rejected on
  the alien path (a >1 scale would bypass the build-time envelope verification).

## Live proof (rig, 2026-07-14)

One command through the unmodified path: identification correctly skipped (plant present), line
served from cache with fit provenance `0e16c52b5b5a`, `auto-drive: PASS (stage=done)` — drove
lap 1 `is_valid=True` (159.108 s standing start), 200.2 km/h, 6th gear, **zero recoveries**,
HUD rendering, 1111 coaching snapshots. Evidence: `.scratch/harness-evidence/alien-572-live/` +
[#572 evidence comment](https://github.com/agorokh/ac-copilot-trainer/issues/572#issuecomment-4966787520).
Line-stage reconciliation vs the same plant: stock 93.15 s QSS → optimized 91.39 s (−1.76 s,
max offset 0.24 m) — Magione's stock line is near-optimal (consistent with PR #259).

## Review (4 rounds, 12 findings, all fixed)

Codex P2 ×7 (scale gate, post-lock resolution, preflight ordering + false-greens, sidecar settle,
degenerate v_top, corridor pinch/margin, cache revalidation), daemon HIGH+MEDIUM (shared readiness
gate), Qodo testability (preflight checks unit-tested off-rig). 226 focused tests green;
`make ci-fast` green; resolve-gate ledger clean; daemon posted no review on the final SHA after a
completed cooldown (vacuous per anti-hang; its prior-SHA findings fixed + fix-noted on the PR).

## Durable lesson

Cache identity hashes gate the *inputs*; they say nothing about the cached *content*. Anything
that drives the car re-verifies content (corridor bounds, plant envelope) at consumption time.
And one readiness predicate, shared by every consumer, is the only way "skip the expensive stage"
logic stays consistent with what the consuming stage actually requires.

## Remaining on EPIC #529

G1 evidence on **unseen combos** (this PR proved the button on the already-identified Magione
combo; the epic gate wants 3 unseen), then P3 (corner BVP + stint layer, attack the 82.7 s floor),
P4 (LLM scientist), P5 (coachable frontier).
