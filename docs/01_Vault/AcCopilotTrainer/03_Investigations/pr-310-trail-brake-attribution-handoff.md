---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-23
updated: 2026-06-23
issue: https://github.com/agorokh/ac-copilot-trainer/issues/301
relates_to:
  - AcCopilotTrainer/01_Decisions/realtime-coaching-architecture-2026-06-22.md
  - AcCopilotTrainer/03_Investigations/pr-75-ollama-corner-coaching-protocol.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# PR #310 — trail-braking surfaced in coach-handoff + folded into attribution (#301)

**Delivered** (squash-merged `2755eb7`, 2026-06-23): the two optional follow-ups from issue #301,
both on the AC sidecar coaching brain. Closes the frontier coaching program's trail-braking reach
(analyzer built in #296, surfaced in debrief/live response in #299/#300).

## What shipped

- **Part 1 — `tools/ai_sidecar/coach_handoff.py`.** `build_coach_handoff` now joins the structured
  debrief's separate `trail_braking` block (keyed by 0-based corner index) onto each handoff corner
  as a compact `trail_brake` field (`classification`/`trail_overlap`/`brake_off_rel`/
  `release_abruptness`/`coaching`), `None` when the corner had no braking-into-entry phase. Additive
  — `COACH_HANDOFF_VERSION` unchanged.
- **Part 2 — `tools/ai_sidecar/corner_attribution.py`.** Trail-braking now participates in the
  attribution layer: `coach_lap` computes `analyze_trail_braking` over the **same** segmentation as
  the signatures and injects the per-corner read into `CornerContext.extra["trail_brake"]`; a new
  `DiagnosticRule(key="trail_brake")` turns a deficit classification into a **technique** attribution
  (`cause_class "technique"`, no suggested setup delta).

## Key design decision — "never displaces"

The `trail_brake` rule confidence is deliberately low (`0.26–0.29`) — **below every existing rule's
firing floor** (turn_in_lag 0.35, exit_traction ≥0.5, braking_phase_loss 0.4/0.7, entry_speed_left
≥0.5, grip_limited 0.6/1.0) yet above `min_confidence` (0.25). So trail-brake rides along as a
supporting technique cue and becomes a corner's **primary** cause only when no other rule fires
(e.g. a clean lap with no reference). Existing corners' `cause_class` / `suggested_setup_delta` /
`_headline` are unchanged, and `attribute_corner()` still no-ops for trail-brake when called directly
without `coach_lap` injection. The strict `coaching_response` golden (`test_harness_client.py`) is
unchanged.

## Verification (operator-grade)

End-to-end on the real pipeline (pre- and post-merge on `main`): the `trail_brake` attribution
(`cause_class='technique'`) appears in `cornerAnalysis`; the handoff corner carries the joined
`trail_brake` field; and the live `coaching_response` wire path (`build_brain_followup`, feature
flag `AC_COPILOT_OLLAMA_ENABLE=1`) surfaces both the `trailBraking` block and the attribution.
`make ci-fast` OK (full suite 1337 passed). An adversarial multi-lens review (correctness /
regression / back-compat / test-adequacy, self-verifying) raised 3 findings, **0 confirmed**.
Qodo's reviewer-guide validated the low-confidence trade-off explicitly; its two defensive-coding
"focus areas" (key-type join, `.get()` forwarding) were answered on the PR as non-defects (keys are
ints produced together by `build_structured_debrief`; `.get()` matches the module idiom).

## Session note — Tier-3 grounding

Substrate `ac_copilot` endpoint was **down (HTTP 502, verified)** this session, so grounding was
vault-only per the MEMORY_CONTRACT recovery table. The worktree memory-gate false-block (committed
manifest placeholder not propagating into linked worktrees) is already tracked as **issue #308**; a
concurrent session's `ops/memory_manifest.local.yml` registers the real `ac_copilot` workspace, so
the gate sat in its sanctioned substrate-outage soft-allow.
