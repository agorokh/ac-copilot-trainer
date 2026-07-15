---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-15
updated: 2026-07-15
relates_to:
  - AcCopilotTrainer/00_System/invariants/memory-three-tiers.md
  - AcCopilotTrainer/03_Investigations/issue-596-partc-actionable-reason-2026-07-15.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# AG_PC Tier-3 consumer repoint drift

## Observed state

The mandatory PR #598 task query resolved the registered `ac_copilot_trainer` workspace but returned
HTTP 502 and an empty context payload. Startup probes showed the bridge routing the memory fleet to
`https://100.71.123.90:*`; every probed workspace on that endpoint was unreachable. The session used
the contract's Tier-2 vault fallback and did not bypass the memory gate.

An existing local investigation maps `100.71.123.90` to the retired m2pro consumer path while the
canonical Tier-3 fleet has moved to m4max-studio. The generated local registry and persisted
`AGENTIC_MEMORY_BRIDGE_HOST` still pin the old endpoint; this is the AG_PC consumer-repoint leg of
open workstation-ops issue #1551, not a new per-session gap.

## Constraints and next action

No machine-global environment variable or registry was changed from this repo session. The owning
workstation-ops workflow should repoint the AG_PC consumer and verify:

- the canonical tailnet hostname is used so TLS SNI is valid;
- `ac_copilot_trainer` returns real context, not only a healthy status;
- the session-start prefetch stamps the primary checkout successfully;
- a normal Codex session no longer falls back to Tier-2-only grounding.

Until then, PR-resolution sessions should issue the required task query, surface the 502, ground on
the relevant vault subgraph, and record the outage in SAVE.
