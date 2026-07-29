---
type: investigation
status: closed
memory_tier: canonical
topic: "SessionStart Tier-3 prefetch worktree markers + failure taxonomy"
source_type: repo
related_issues:
  - https://github.com/agorokh/ac-copilot-trainer/issues/712
  - https://github.com/agorokh/governance-hub/pull/341
related_prs:
  - https://github.com/agorokh/governance-hub/pull/341
last_updated: 2026-07-29
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/tier3-consumer-repoint-drift-2026-07-15.md
---

# Investigation: #712 SessionStart prefetch worktree markers

## Summary

**#712 CLOSED.** Operator re-diagnosis (2026-07-28): resolver `tier3_workspace_id` was **not**
broken — a gitignored `ops/memory_manifest.local.yml` (invisible from linked worktrees) still
named `ac_copilot_trainer` + m2pro, and `AGENTIC_MEMORY_TLS_SERVER_NAME` was unset. Config fixed
on the rig. Remaining **code** work shipped in governance-hub PR [#341](https://github.com/agorokh/governance-hub/pull/341)
MERGED [`3757ec3`](https://github.com/agorokh/governance-hub/commit/3757ec3d37b3b65d765a40906607d3b3b07d970b).

Spoke `scripts/hook_*.py` are shims — no ac-copilot-trainer source change.

## What shipped (hub)

1. **Dual-write stamps** — SessionStart writes `.scratch/.last_memory_query[.missing]` to main
   (authoritative for the gate) **and** the session worktree (visibility). Main write is hard;
   worktree is best-effort. Atomic nofollow writes reject symlink-following attacks.
2. **Failure taxonomy** — collapsed `unreachable or empty` replaced with reason_code phrases
   (transport / empty context / no eligible endpoints / soft-allow vs warn vs block).
3. **Stale-endpoint detector** — non-loopback config hosts that disagree with
   `AGENTIC_MEMORY_BRIDGE_HOST` emit `stale-endpoint-suspect` (ignores injected `env_bridge`,
   uses raw configured URLs so allowlist-filtered hosts still fire, sanitizes diagnostic URLs).
4. **PostToolUse stamp** dual-writes success to the worktree without unlinking harness-authored
   `.missing` (preserves `gate_policy=block` visibility).

## Observed verification (2026-07-29)

Hermetic scenario against merged hub main module: dual-write missing markers share token;
phrases distinct; stale hint fires on pre-migration IP; loopback-only config silent; control
chars stripped. `VERIFIED_OK`.

## Follow-ups

- Hosts must `git pull` / refresh `~/.fleet-governance` to pick up the hook.
- Rig config (overlay → `ac_copilot` + m4max + SNI) already applied 2026-07-28.
