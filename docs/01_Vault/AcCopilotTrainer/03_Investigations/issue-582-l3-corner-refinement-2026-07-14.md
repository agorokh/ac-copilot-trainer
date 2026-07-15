---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-14
updated: 2026-07-14
issue: https://github.com/agorokh/ac-copilot-trainer/issues/582
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-577-alien-selfplay-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-572-alien-pipeline-2026-07-14.md
  - AcCopilotTrainer/03_Investigations/issue-543-uncertainty-aware-plant-id-2026-07-13.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #582 — L3 corridor-constrained per-corner refinement (PR #583, EPIC #529 Layer 3)

**Merged:** squash [`b2ef740`](https://github.com/agorokh/ac-copilot-trainer/commit/b2ef740)
(2026-07-15T00:07Z), PR [#583](https://github.com/agorokh/ac-copilot-trainer/pull/583); **#582
CLOSED**. The #577 item-3 follow-up the previous handoff prescribed.

## What shipped

`tools/ac_harness/corner_refine.py` (new): the QSS profile drives the 1.96-z safe LCB everywhere,
which #577 proved binds the floor. L3 relaxes **measured, low-relative-variance** bins toward the
posterior mean (hard stability floor `Z_STABILITY_FLOOR = 1.0`, a module constant persisted params
cannot lower), segments padded/merged cyclic corner windows, re-solves each interior between
QSS-pinned entry/exit speeds (the ellipse-coupled backward branch is the trail-brake shape), and
accepts a z-ladder candidate only when pointwise ≥ QSS AND inside the barrier AND strictly faster.
Every corner is reported `refined` (z, relaxed bins, gain) or `reverted` (named reason) — never
silent. `alien_line.py`: refined profile rides the same artifact with `v_target_qss_mps` fallback;
L3-typing keys on `params.l3` identity; verify re-derives the barrier from the CURRENT plant and
tamper-rejects laxer params, sub-QSS refined profiles, NaN inputs. `auto_drive --l3` (opt-in);
`auto_alien` passes `--l3` by default (`--no-l3` opt-out) and surfaces per-stage summaries.

## Review (4 rounds, all fixed forward)

Codex P2 ×5 — **`run.alien_line` report shape** (the l3 summary would have been silently absent on
real stage outcomes), drive-bin provenance, refined≥QSS cache contract, artifact vs driven
utilisation reporting, **ggv_scale-aware driven utilisation** (an overspeed step must never read
within-barrier). Qodo ×3 — exactly-touching padded windows merge, L3 params-identity typing, NaN
under-report in `profile_utilisation`. Final: Qodo Bugs (0), 0 unresolved threads, resolve-gate
ledger clean, daemon vacuous (App not installed).

## Live rig proof (merged main, hands-off)

`auto_alien --car ks_porsche_911_gt3_r_2016 --track magione --laps 3 --iterations 2` →
**`auto-alien: OK`**, ladder `completed`, best flying lap **96.621 s**, monotonic
107.005 → 101.651 → 96.621, every stage PASS/VALID. Observed live: L3 **reverted all 7 corners
with named per-corner reasons** (`no measured low-variance lateral bin in 51–114 km/h ranges`) —
the evidence gate refusing prior-dominated posteriors, by design; the iter-2 refit raised 1
lateral bin → plant fit hash changed → **line rebuilt** (provenance gate live); run evidence
recorded `ggv_scale` + `driven_max_ay_utilisation_vs_barrier` (0.9025 @0.95, 1.0 @1.0). Evidence:
issue #582 comment + `.scratch/harness-evidence/alien-582-l3-911-magione/`.

## Honest limitation / where the gain unlocks

Live refinement gain is currently **0 on this combo**: no corner-speed lateral bin is yet
`measured` with rel-std ≤ 0.25. The self-play ladder is the mechanism that flips them (each
overspeed batch adds supra-LCB lateral evidence). Once corner-speed bins qualify, L3 lifts the
interior toward `mean − z·std` under the barrier — until then it is exactly safe-QSS plus an
audit trail. NOT a wall and NOT a defect; do not "fix" by weakening the gate.

## Ops notes

- COM6 (rig screen serial) was held by another process → sidecar retried forever, flooding
  stdout every 2 s; first monitored run was killed and restarted with a quiet filter. Harmless to
  the drive, but long unattended runs should filter or free COM6.
- Rig left clean: acs + Content Manager stopped after the run; plant artifact carries the iter-2
  refit (fit `de4e96e825d0`, keep-last-valid ladder VALID throughout).
