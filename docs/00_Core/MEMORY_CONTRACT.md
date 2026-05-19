# Memory contract (mandatory for every agent)

**Status:** Template
**Category:** Core
**Owns:** the LOAD/SAVE protocol across **all three memory tiers** for Claude Code, Cursor, and Task-spawned subagents.
**Loaded by:** `@docs/00_Core/MEMORY_CONTRACT.md` in `CLAUDE.md` (Claude Code auto-inclusion); referenced by `.cursor/rules/memory-contract.mdc` (Cursor auto-apply); embedded in `.claude/agents/*.md` and `AGENTS.md` via marker-delimited sections re-rendered by `scripts/merge_memory_contract.py`.
**Companion invariants:** [`memory-three-tiers.md`](../01_Vault/ProjectTemplate/00_System/invariants/memory-three-tiers.md), [`secrets-from-doppler.md`](../01_Vault/ProjectTemplate/00_System/invariants/secrets-from-doppler.md).
**Originating postmortem:** [issue #115](https://github.com/agorokh/template-repo/issues/115).

---

## The contract in one paragraph

Memory in this project lives in **exactly three tiers** — `AGENTS.md` (Tier 1, short operational facts, auto-loaded), the vault (Tier 2, structured markdown graph), and a per-workspace semantic substrate (Tier 3, LightRAG canonical online — Graphiti retained for offline entity-resolution + bi-temporal metadata only per the [Graphiti sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md) maintained in agent-factory — queryable via `mcp__agentic-memory__*`). Every agent — primary, Task-spawned subagent, Cursor coding agent, CLI invocation — **MUST**:

1. **Read Tier 3 at LOAD** via `mcp__agentic-memory__query_knowledge_graph` for the active workspace before any substantive Edit/Write/Bash on code paths. The substrate is the reason we keep three tiers; skipping the read means re-discovering context every session.
2. **Write to the right tier at SAVE.** Short operational facts → `AGENTS.md`. Structured knowledge (decisions, investigations, invariants, glossary, handoffs) → vault as small linked nodes. **Tier 3 is read-mostly from the agent surface** — it is rebuilt by re-ingesting Tier-2 on cadence; agents do not write to it directly.
3. **Never write outside the three tiers.** The Claude Code per-user auto-memory directory (`~/.claude/projects/.../memory/`) is **deprecated for this project**. Scratch DBs, ad-hoc files, and direct substrate-store writes that bypass the vault → ingest pipeline are all side channels ([invariant](../01_Vault/ProjectTemplate/00_System/invariants/memory-three-tiers.md)).

These rules are enforced by deterministic hooks (`scripts/hook_session_start_memory_prefetch.py`, `scripts/hook_memory_gate.py`, `scripts/hook_stop_save_reminder.py`) — not by trust in the agent's prompt-following. Failure modes are explicit and surfaced to the human.

---

## What "memory" means here (three tiers)

| Tier | Substrate | Agent write path | Agent read path |
|---|---|---|---|
| **1** | `AGENTS.md` bottom section + changelog | Direct `Edit` for short operational facts (commands, ports, learned preferences, policy updates) | Auto-loaded by Claude Code / Cursor at session start |
| **2** | Obsidian vault at `docs/01_Vault/<ProjectKey>/` (markdown graph; `00_Graph_Schema.md`) | Direct `Write` / `Edit` of small linked nodes (decisions, investigations, invariants, glossary, handoffs) | `@`-included by `CLAUDE.md`; indirectly via Tier-3 query (the substrate is built by re-ingesting Tier-2) |
| **3** | Per-workspace semantic substrate declared in [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml). Backend: **`lightrag` (canonical online)** or `graphiti` (offline-only per [sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md); never on the agent read path). | **Indirect.** The substrate ingests Tier-2 vault notes on cadence (`stale_after_hours` per workspace). Agents do **not** write to the substrate directly — no MCP write tools are exposed by design. | For **`lightrag`** workspaces only: `mcp__agentic-memory__query_knowledge_graph(prompt, workspace=…)` + `mcp__agentic-memory__search_*`. Not used for `graphiti` rows (offline-only). **Read at LOAD is mandatory** when a matching LightRAG workspace is live. |

Auto-memory (`~/.claude/projects/.../memory/`) is **not** a tier — it is a side channel actively deprecated for this project. See [`memory-three-tiers.md`](../01_Vault/ProjectTemplate/00_System/invariants/memory-three-tiers.md).

---

## LOAD protocol

At session start, the `SessionStart` command hook (`.claude/settings.base.json`) runs **deterministic** Python subprocesses that:

1. `cat docs/01_Vault/<ProjectKey>/00_System/Next Session Handoff.md` → first turn context.
2. `scripts/knowledge_session_summary.py` → top patterns from the local repo-knowledge SQLite.
3. `scripts/hook_session_start_memory_prefetch.py` → pre-fetches Tier-3 substrate findings for the workspace resolved from `ops/memory_manifest.yml` (matched by repo path), and **stamps `.scratch/.last_memory_query` with `{token, timestamp_utc, workspace, prompt}`**. If no workspace matches, the hook prints a `WARNING: no Tier-3 workspace registered` line and writes `.scratch/.last_memory_query.missing` — the gate hook then **degrades to warn-only** on code paths so the session is not bricked while PR C lands workspace provisioning.
4. `scripts/hook_session_start_memory_redirect.py` → physically marks the auto-memory directory as deprecated (writes a `README.md` that explains the deprecation) so an agent that *tries* to write there sees the warning before silently succeeding.

**Agent obligation:** if you need to do meaningful work, **issue at least one `mcp__agentic-memory__query_knowledge_graph` call early in the session** with a prompt tied to the issue/branch/task. The SessionStart hook does an initial prefetch using branch name + issue title as the query; refine with a task-specific query once you understand scope.

If you are a **Task-spawned subagent**, the orchestrator embeds the SessionStart memory prefetch output as a `## Pre-loaded memory context` block in your prompt. You inherit the same lockfile on disk; further MCP queries supplement context but do not rewrite the gate stamp (only SessionStart prefetch updates `.scratch/.last_memory_query` today).

---

## SAVE protocol

At session end (Stop hook) or before a Phase-C vault commit:

1. **Vault SAVE** — Update `Next Session Handoff.md`. Add or update small linked nodes for any new investigation, decision, or convention per [`00_Graph_Schema.md`](../01_Vault/00_Graph_Schema.md). Prefer **new small files** over appending to monoliths.
2. **Tier-3 substrate write** — *agents never write to the substrate directly.* No MCP write tool is exposed; the substrate is rebuilt by re-ingesting Tier-2 vault notes on cadence. Material findings (architectural decisions, recurring failure patterns, fleet-wide invariant violations) become Tier-3-discoverable by being written as Tier-2 vault nodes (small linked markdown). For `lightrag` workspaces (canonical online), the ingest-audit launchd unit picks up new vault notes within `stale_after_hours`. Operational/audit events that don't merit a knowledge node go to JSONL audit logs alongside the vault (e.g. `docs/01_Vault/<ProjectKey>/_inbox/cycles/steward-events.jsonl`).
3. **Stop audit** — `scripts/hook_stop_save_reminder.py` logs whether (a) the session touched code paths and (b) a vault or Tier-3 write occurred. Mismatches surface to the human as a one-line reminder; they are **not blocking** (template invariant: no LLM in hooks; the audit script is deterministic but advisory).

---

## Runtime gate — what gets blocked

The PreToolUse gate (`scripts/hook_memory_gate.py`) runs on `Edit | Write | Bash` and **blocks** when:

- The tool call would touch a **code path** under `src/`, `scripts/`, `tests/`, `ops/`, `.github/`, `tools/`, or top-level `pyproject.toml` / `Makefile` / `setup.py`.
- AND one of:
  - `.scratch/.last_memory_query` is **missing**, OR
  - the stamp is **stale** (older than `CLAUDE_MEMORY_GATE_TTL_SECONDS` — default 1800s / 30 min), OR
  - **the substrate response in the stamp does not mention any substantive token from the file being edited** (issue #115 council fix — closes the "query spam" bypass where an agent runs `query("x")` to mint a useless stamp). The gate extracts tokens from the path (`scripts/hook_memory_gate.py` → `scripts`, `hook`, `memory`, `gate`) and checks the response body for substring overlap. If your memory query response doesn't mention the file, query again with a prompt that does.

The Bash matcher also blocks **indirect-execution write paths**: `python -c`, `node -e`, `perl -e`, `ruby -e`, `bash -c`, `curl … | bash`, `wget … | sh`, heredoc patterns (`<<EOF`). These are equivalent to `Edit`/`Write` for code mutation purposes and need a fresh + relevant stamp.

The gate **does not block**:

- Touches to `docs/`, `*.md` at root, `.scratch/`, `.claude/agents/`, `.claude/skills/`, `.cursor/`, `.github/ISSUE_TEMPLATE/` — documentation and prompt files are allowed without a fresh memory query.
- Any Bash command that does not parse as a destructive operation (the gate is conservative — it allows `ls`, `cat`, `gh pr view`, `git status`, etc.; it blocks Edit/Write tool calls + Bash commands that look like file edits via `sed -i` / `tee` / `cat >`).
- Any Edit/Write when `CLAUDE_MEMORY_GATE=0` is set in the environment (operator kill-switch, mirrors the `CLAUDE_SQL_DDL_GUARD` opt-in pattern).
- When the SessionStart prefetch failed because no workspace is registered for this repo (degrades to warn-only; see LOAD §3).

When the gate fires, stderr carries:

```
BLOCK: hook_memory_gate.py — no fresh Tier-3 substrate query in this session
  Touched path: <file>
  Required: call mcp__agentic-memory__query_knowledge_graph(prompt="<task-specific>", workspace="<workspace>") first
  Workspace (resolved from ops/memory_manifest.yml): <workspace> at <endpoint>
  Or set CLAUDE_MEMORY_GATE=0 to bypass (rare; surface why in the vault SAVE)
```

---

## Subagent contract

When the orchestrator (`issue-driven-coding-orchestrator`) or any agent invokes `Task(subagent_type=…, prompt=…)`:

- **Embed memory context.** The orchestrator MUST include a `## Pre-loaded memory context` section in the subagent's prompt with the SessionStart prefetch output (verbatim or summarized). Subagents do not auto-load `CLAUDE.md`; this is the explicit propagation channel.
- **Embed the contract pointer.** Include the line `Memory contract: docs/00_Core/MEMORY_CONTRACT.md (loaded contract authoritative).` so the subagent treats memory as required, not optional.
- **Inherit the lockfile.** Subagents in the same session share `.scratch/.last_memory_query`. They may refresh it with their own MCP queries but the parent's stamp counts.

In **Cursor**, where Task only allows `subagent_type` in `{generalPurpose, explore, shell, best-of-n-runner}`, the same contract applies: use `generalPurpose` with the embedded memory context, per `.cursor/rules/cursor-task-delegation.mdc`.

---

## When to write to the vault vs the substrate

| Material | Vault node type | Substrate write |
|---|---|---|
| New architectural decision | `decision` under `01_Decisions/` | yes — picks up at next ingest |
| New investigation / postmortem | `investigation` under `02_Investigations/` | yes — same |
| Recurring pitfall | `pitfall` under `pitfalls/` | yes |
| Entity definition (system, service, person) | `entity` under `glossary/` or `entities/` | yes |
| New invariant | `invariant` under `00_System/invariants/` | yes |
| Session handoff (`Next Session Handoff.md`) | `handoff` | usually no — substrate ingest is too coarse for per-session state |
| Branch / PR ephemeral notes | `.scratch/` (gitignored) | no — promote to vault when stable |

Do **not** write the same fact in both vault and substrate via separate paths. The substrate ingest pipeline reads vault notes on a cadence (`stale_after_hours` per workspace). Write once in the vault, let the ingest propagate.

---

## Conversational drift audit (honest enforcement limit)

The runtime gate enforces memory grounding for **file mutations**. It has **no surface to fire on conversational responses** — when an agent answers a question, plans, or synthesizes findings, no tool call gets gated, so the substrate has no opportunity to compel memory consultation. In 2026 Claude Code architecture, there is no `PreResponse` hook to inject memory or block ungrounded responses.

**This is a known limit.** The substrate covers file-mutation agents (Claude Code coding sessions, Cursor coding agents, Hermes Coder profile) well; it covers conversational/research/planning agents only by encouragement, not by force.

To make the limit **measurable**, `scripts/hook_stop_drift_audit.py` runs as a Stop hook (advisory, never blocking — Stop hooks are command-only per template invariant) and:

1. Reads the session transcript via `transcript_path` from the Stop hook payload.
2. Filters to **substantive** assistant messages (≥ 30 words by default).
3. For each substantive message, checks whether it cites substrate-derived content — vault paths (`docs/01_Vault/`), MCP tool calls (`mcp__agentic-memory__`), and at least two overlapping substantive tokens from the Tier-3 `.scratch/.last_memory_query` **response_body** only (common English stop-words excluded; prompt/workspace excluded to avoid false positives).
4. Computes `drift_score = 1 - (cited / total_substantive)` in `[0.0, 1.0]`.
5. Appends one record per session to `.scratch/memory_audit.jsonl` and emits a one-line operator advisory to stdout.
6. **Log bounds:** SessionStart reads only the last 64 KiB of the audit log; on append, logs above 1 MiB are truncated to the last 512 KiB. Internal hook failures append a non-secret line to `.scratch/memory_drift_audit_errors.jsonl` and emit a one-line stdout advisory (Stop hook still exits 0).

**The "super-ego" feedback loop** — the NEXT session's `hook_session_start_memory_prefetch.py` reads the most recent `"reason": "scored"` record from the audit log. If `drift_score ≥ CLAUDE_MEMORY_DRIFT_WARNING_THRESHOLD` (default `0.5`), it prepends a WARNING block to turn-1 stdout so the agent enters the session aware of the prior drift:

```
WARNING: previous session memory-drift audit:
  drift_score: 0.7 (threshold 0.5) — 1/5 substantive responses cited substrate content
  recorded: <timestamp>
  This session: explicitly cite substrate findings (vault paths,
  mcp__agentic-memory__ tool results, MEMORY_CONTRACT.md) in
  substantive responses so the next audit reflects grounded reasoning.
```

This is the only feedback path that exists in 2026 Claude Code's hook architecture without a PreResponse hook (council reconciliation, 2026-05-17). It does not *force* citation. It *measures* drift and surfaces it to the next session.

Knobs:

- `CLAUDE_MEMORY_DRIFT_AUDIT=0` — disable the audit (silent exit).
- `CLAUDE_MEMORY_DRIFT_AUDIT_MIN_WORDS` — substantive-message threshold (default 30).
- `CLAUDE_MEMORY_DRIFT_AUDIT_MIN_SAMPLE` — minimum substantive count to score (default 3).
- `CLAUDE_MEMORY_DRIFT_WARNING_THRESHOLD` — drift_score above which to warn next session (default 0.5).

Heuristic accuracy: the citation check is substring-match — an agent that happens to mention `MEMORY_CONTRACT.md` in passing scores as "cited" even if the response isn't substantively grounded. Conversely, an agent that paraphrases substrate findings without naming them may score as drift. The audit is **a feedback signal, not a verdict**. Operators should review the `memory_audit.jsonl` records over multiple sessions to decide whether the substrate is working in practice for their fleet.

## What happens when something goes wrong

| Symptom | Cause | Recovery |
|---|---|---|
| Gate blocks every Edit on code paths | No SessionStart prefetch ran (e.g. hook script missing, repo-root mis-detected, or Claude/Cursor host doesn't fire SessionStart) | Run `python3 scripts/hook_session_start_memory_prefetch.py` manually to stamp the lockfile; or set `CLAUDE_MEMORY_GATE=0` and file an `architectural-invariant-gap` issue |
| Gate degrades to warn-only and logs `no Tier-3 workspace registered` | This repo is not in `ops/memory_manifest.yml` | File a tracking issue against template-repo (PR C will provision; for transient sessions set `CLAUDE_MEMORY_GATE=0`) |
| MCP server unreachable | Substrate host down (verify with `mcp__agentic-memory__verify_server_health`) | Vault-only mode: query the vault directly via grep / Read; surface the substrate outage in the session handoff so the next session retries the prefetch |
| Subagent ignores memory contract | Orchestrator did not embed `## Pre-loaded memory context` in the Task prompt | Orchestrator bug — fix in `.claude/agents/issue-driven-coding-orchestrator.md`; the lockfile still gates the subagent's Edit/Write, so blast radius is contained |
| Agent writes to `~/.claude/projects/.../memory/` despite contract | The auto-memory directory marker was not yet written (first run after template upgrade) | The SessionStart redirect hook (PR B) creates the marker on every session start; if the agent still writes there, file an `architectural-invariant-gap` issue (this is a hook regression) |

---

## See also

- [`SESSION_LIFECYCLE.md`](SESSION_LIFECYCLE.md) — LOAD → OPERATE → SAVE that this contract slots into.
- [`MEMORY_SUBSTRATE.md`](MEMORY_SUBSTRATE.md) — Tier-3 substrate detail (LightRAG canonical online; Graphiti offline-only per sunset ADR; workspace schema).
- [`VAULT_TAXONOMY.md`](VAULT_TAXONOMY.md) — `origin` classification (`repo-product` / `repo-embedded` / `human-curated`).
- [`HOOK_DESIGN.md`](HOOK_DESIGN.md) — why hooks are deterministic and never LLM-bearing.
- [`memory-three-tiers.md`](../01_Vault/ProjectTemplate/00_System/invariants/memory-three-tiers.md), [`secrets-from-doppler.md`](../01_Vault/ProjectTemplate/00_System/invariants/secrets-from-doppler.md) — companion invariants.
- [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml) — workspace registry.
- [`ops/propagation_manifest.yml`](../../ops/propagation_manifest.yml) — fleet convergence tracking; PR C adds the `memory-enforcement-v1` invariant.
