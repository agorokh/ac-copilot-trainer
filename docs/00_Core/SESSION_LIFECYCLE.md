# Session lifecycle (LOAD → OPERATE → SAVE)

**Status:** Template  
**Category:** Core

All agents working in this repository should treat a session as three explicit phases. This integrates with the **vault knowledge graph** ([`docs/01_Vault/00_Graph_Schema.md`](../01_Vault/00_Graph_Schema.md)) and `.claude/skills/vault-memory/SKILL.md`.

## LOAD

1. Read **`Next Session Handoff.md`** under `docs/01_Vault/<ProjectKey>/00_System/` (template: `AcCopilotTrainer`).
2. Follow **`relates_to` links** in frontmatter to load a **small subgraph** (indexes + relevant invariant or glossary nodes) — do not load the entire vault.
3. Read **`Current Focus.md`** for branch, PR, and active intent.
4. For work that touches architecture or security, read linked **invariant** nodes (e.g. `00_System/invariants/no-secrets.md`) via `invariants/_index.md`.

## OPERATE

- Execute the task (Issue, PR, docs, refactor) per `AGENTS.md` and `10_Agent_Protocol.md`.
- **Capture insights** first as **draft notes** under **`.scratch/`** (gitignored), then promote into the vault as small linked nodes when stable.

## SAVE

Always run SAVE before ending a session or abandoning a thread — including after **failure**.

1. Update **`Next Session Handoff.md`**: resume pointer, what shipped, what remains, blockers.
2. **Create or update** vault nodes with valid frontmatter and **`relates_to`** (see graph schema). Prefer **new small files** over appending long sections to existing monoliths.
3. Update **`Current Focus.md`** if the active branch, PR, or focus changed.

### Vault-only updates (labeled PR + auto-merge)

**Default flow as of `template-2026.04`:** Post-merge vault handoff (and similar meta-docs under `docs/01_Vault/`) ships via a **`vault/post-merge-pr<N>`** branch labeled **`vault-only`**. The `.github/workflows/vault-automerge.yml` workflow validates that the PR's diff is strictly under `docs/01_Vault/**` and enables GitHub auto-merge. The agent **never** pushes to `main` directly. See `.claude/agents/post-merge-steward.md` for the full procedure and exit-code contract.

If branch protection blocks the bot from auto-merging, the workflow comments on the PR and a human with merge rights lands it. Do not stack additional vault-only PRs for the same handoff while one is open — fix the existing PR.

**One-time per repo:** create the label with `gh label create vault-only --description "post-merge handoff PR; auto-merged by bot"`. Until the label exists, the workflow does nothing and a human merges manually.

For **routine** session SAVE that only touched vault files (not steward-driven), the same labeled-PR + auto-merge flow is the safest path; ad-hoc commits to `main` are discouraged.

### Failure protocol

If the session ends in error or timeout:

- Record **what was attempted**, **what failed** (command, check name, or symptom), and **links** to relevant issues, PRs, or vault nodes.
- Do not leave the handoff empty — the next agent depends on it.

## Platform grounding (Claude Code and similar hosts)

- **Project instructions:** Many hosts auto-load the **first ~200 lines** of project memory files (e.g. root **`CLAUDE.md`**, sometimes **`MEMORY.md`**). Keep high-signal, stable guidance there; put depth in the vault graph.
- **Subagent / memory scopes:** When tools distinguish **`user`**, **`project`**, and **`local`** memory, treat **project** + vault as shared team truth; **local** as disposable session scratch unless promoted to the vault.

## See also

- [BOOTSTRAP_NEW_PROJECT.md](BOOTSTRAP_NEW_PROJECT.md)
- [TOOLCHAIN.md](TOOLCHAIN.md)
