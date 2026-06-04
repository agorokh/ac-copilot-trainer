# Instruction-surface precedence (for autonomous agents)

**Status:** Template
**Category:** Core
**Why:** Council-required (2026-06-04 instruction-coherence audit). When two agent-facing
surfaces disagree, an autonomous agent with no declared precedence resolves the conflict by
context-recency or salience — i.e. non-deterministically. This file is the deterministic
tie-breaker. Enforced by `tests/test_instruction_coherence.py`.

---

## Enforcement polarity (the one that must never invert)

**Local deterministic hooks are the PRIMARY first-try correctness layer wherever they can fire.
Server-side rulesets are the BACKSTOP, not the replacement.** No surface may state or imply that
client/local hooks are "advisory", "optional", or "UX", or that the server side is the "real"
or "primary" enforcement. A guard that must *also* hold under headless modes (where local hooks
do not fire) — e.g. `protect-main` — is coarse for that reason; that does not demote the local
layer for the flows where it *does* fire.

Headless `codex exec` / `agy --print` / Antigravity user-level modes fire no per-repo hooks. That
is **accepted, registered debt** (`GOVERNANCE-GAPS.md` GAP-1) backstopped by the server belt — it
must **never** be described as proven local-hook enforcement.

---

## Reading order (first-match-wins for the SAME topic)

Resolve instruction conflicts in this order. A **higher** item never overrides a **lower** one
for the same topic; a lower item only adds detail that does not contradict a higher one.

1. **Active handoff** — `docs/01_Vault/<ProjectKey>/00_System/Next Session Handoff.md` (task-specific, current).
2. **Active ADR / gaps registry** — `docs/01_Vault/.../01_Decisions/*` marked `status: active`; `docs/00_Core/GOVERNANCE-GAPS.md`.
3. **Repo `AGENTS.md` / `CLAUDE.md`** — repo-specific persistent guidance.
4. **Canonical contracts** — `MEMORY_CONTRACT.md`, `HOOK_DESIGN.md`, `SESSION_LIFECYCLE.md`, the invariants under `00_System/invariants/`.
5. **Workflow skills** — `.claude/skills/*/SKILL.md` and `.claude/rules/*`.
6. **Executable hooks/config** — `.claude/settings*.json`, `.cursor/hooks.json`, `.codex/hooks.json`, hub `wrappers/`. (Executable behavior must not contradict 1–4; if it does, that is a bug in the config, not new policy.)
7. **Vault / historical material** — investigations, superseded ADRs, changelogs.

**Hub vs repo:** `governance-hub` is the source for **cross-repo / fleet policy and canonical hook
logic** only. Repo-local surfaces govern repo-specific execution where they do not contradict a
hub contract. A hub doc never overrides a repo's active handoff for that repo's task state.

---

## Historical ≠ active

Changelogs, superseded ADRs, and investigation notes legitimately record removed mechanisms. They
are **not active instruction** unless explicitly marked CURRENT. Any mention of a removed mechanism
(e.g. the deleted `hook_stop_save_reminder` / `hook_stop_drift_audit` Stop hooks) in a live surface
must carry a removal marker (`REMOVED` / `DELETED` / `SUPERSEDED` / strikethrough + `DO NOT
RESTORE`). Current-tense verification checklists for removed mechanisms are forbidden — an agent
reads them as active work and tries to restore deleted code.

---

## See also
- [`MEMORY_CONTRACT.md`](MEMORY_CONTRACT.md), [`HOOK_DESIGN.md`](HOOK_DESIGN.md), [`GOVERNANCE-GAPS.md`](GOVERNANCE-GAPS.md)
- [`ANTI_PATTERNS.md`](ANTI_PATTERNS.md), the cross-repo change gate invariant.
- Guard: `tests/test_instruction_coherence.py`; stale-reference guard: `tests/test_no_stale_hook_refs.py`.

## Workspace-provisioning honesty (do NOT manufacture a stamp)

When the manifest resolves a Tier-3 workspace the live substrate does not expose (`workspace_unknown`),
you MUST NOT query a *neighboring* workspace to mint a stamp — even if the content visibly lives there
(e.g. querying `divorce_proceedings` to satisfy a `court_fillings_processing` resolution). Ground in
the Tier-2 vault per the fallback rule, surface the provisioning gap explicitly (link the tracking
issue), and proceed from vault + live evidence — or stop. Faking provenance from an adjacent workspace
is a contract violation, not a workaround. (Canonical: `MEMORY_CONTRACT.md`.)
