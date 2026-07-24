---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-23
updated: 2026-07-23
issue: https://github.com/agorokh/ac-copilot-trainer/issues/668
relates_to:
  - AcCopilotTrainer/03_Investigations/stable-windows-soak-2026-07-23.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #668: graceful battery + CM probe — launches arm the accumulator; mitigation shipped

## Results (2026-07-23 evening, one boot, stable 26200, 9.43–10.24 h)

- **Graceful battery (16 launches, WM_CLOSE teardown):** 1–13 stable (all graceful),
  **14–15 froze**, 16 stable but WM_CLOSE hung → forced fallback.
- **CM-restart probe (fresh CM, 6 launches):** **1–2 froze through a brand-new CM**, 3–6 stable.

## Settled

- **Hard kills NOT necessary** — onset after 13 pure-graceful cycles. Launch cycles arm it.
- **Kills accelerate onset** (n=1/arm): ~3–5 (kill-heavy) → 8 (hard teardown) → 14 (graceful).
- **Post-onset burst rate teardown-independent** (~44% both arms).
- **CM process state REFUTED** as the container (fresh CM froze twice). Only the
  freezes-through-fresh-CM carry inference — burst decay confounds the stables after.
- Any "kill X then probe" design is burst-decay-confounded → remaining suspects need
  **boot-scoped arms** (stop suspect from boot, measure onset): NVIDIA session state,
  session-wide kernel objects, external `acpmf_*` holders (SimHub/MOZA).

## Shipped

**PR [#669](https://github.com/agorokh/ac-copilot-trainer/pull/669) MERGED** `28107b688`,
#668 CLOSED: `graceful_grace` phase in `terminate_process_tree_confirmed_absent` +
verdict-gated wiring (`DEFAULT_GRACEFUL_EXIT_GRACE` 20 s, STABLE-only — wedges keep the
immediate forced kill). Roughly doubles the clean-launch budget per boot.

Data: `.scratch/freeze-forensics/graceful-battery-20260723.json`, `cm-restart-probe-20260723.json`.
Full analysis: [#668 results comment](https://github.com/agorokh/ac-copilot-trainer/issues/668#issuecomment-5065689952).
