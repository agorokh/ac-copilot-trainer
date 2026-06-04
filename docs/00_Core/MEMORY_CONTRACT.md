# Memory contract (mandatory for every agent)

**Status:** Template
**Category:** Core
**Owns:** the LOAD/SAVE protocol across **all three memory tiers** for Claude Code, Cursor, and Task-spawned subagents.
**Loaded by:** `@docs/00_Core/MEMORY_CONTRACT.md` in `CLAUDE.md` (Claude Code auto-inclusion); referenced by `.cursor/rules/memory-contract.mdc` (Cursor auto-apply); embedded in `.claude/agents/*.md` and `AGENTS.md` via marker-delimited sections re-rendered by `scripts/merge_memory_contract.py`.
**Companion invariants:** [`memory-three-tiers.md`](../01_Vault/AcCopilotTrainer/00_System/invariants/memory-three-tiers.md), [`secrets-from-doppler.md`](../01_Vault/AcCopilotTrainer/00_System/invariants/secrets-from-doppler.md).
**Originating postmortem:** [issue #115](https://github.com/agorokh/template-repo/issues/115).

---

## The contract in one paragraph

Memory in this project lives in **exactly three tiers** — `AGENTS.md` (Tier 1, short operational facts, auto-loaded), the vault (Tier 2, structured markdown graph), and a per-workspace semantic substrate (Tier 3, LightRAG canonical online — Graphiti retained for offline entity-resolution + bi-temporal metadata only per the [Graphiti sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md) maintained in agent-factory — queryable via `mcp__agentic-memory__*`). Every agent — primary, Task-spawned subagent, Cursor coding agent, CLI invocation — **MUST**:

1. **Read Tier 3 at LOAD** via `mcp__agentic-memory__query_knowledge_graph` for the active workspace before any substantive Edit/Write/Bash on code paths. The substrate is the reason we keep three tiers; skipping the read means re-discovering context every session.
2. **Write to the right tier at SAVE.** Short operational facts → `AGENTS.md`. Structured knowledge (decisions, investigations, invariants, glossary, handoffs) → vault as small linked nodes. **Tier 3 is read-mostly from the agent surface** — it is rebuilt by re-ingesting Tier-2 on cadence; agents do not write to it directly.
3. **Never write outside the three tiers.** The Claude Code per-user auto-memory directory (`~/.claude/projects/.../memory/`) is **deprecated for this project**. Scratch DBs, ad-hoc files, and direct substrate-store writes that bypass the vault → ingest pipeline are all side channels ([invariant](../01_Vault/AcCopilotTrainer/00_System/invariants/memory-three-tiers.md)).

These rules are enforced by the deterministic PreToolUse gate (`scripts/hook_memory_gate.py`) — the only mechanism with measurable adherence (slim-down ADR, issue #205). Failure modes are explicit and surfaced to the operator at the tool-call boundary, not via Stop-hook reminders that agents learn to ignore.

Simplicity policy (2026-05-24): prefer deterministic, in-band controls that directly affect execution behavior; avoid adding template-core report-only health-check layers that are frequently skipped by non-agent and human paths.

---

## What "memory" means here (three tiers)

| Tier | Substrate | Agent write path | Agent read path |
|---|---|---|---|
| **1** | `AGENTS.md` bottom section + changelog | Direct `Edit` for short operational facts (commands, ports, learned preferences, policy updates) | Auto-loaded by Claude Code / Cursor at session start |
| **2** | Obsidian vault at `docs/01_Vault/<ProjectKey>/` (markdown graph; `00_Graph_Schema.md`) | Direct `Write` / `Edit` of small linked nodes (decisions, investigations, invariants, glossary, handoffs) | `@`-included by `CLAUDE.md`; indirectly via Tier-3 query (the substrate is built by re-ingesting Tier-2) |
| **3** | Per-workspace semantic substrate declared in [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml). Backend: **`lightrag` (canonical online)** or `graphiti` (offline-only per [sunset ADR](https://github.com/agorokh/agent-factory/blob/main/docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-17-graphiti-sunset.md); never on the agent read path). | **Indirect.** The substrate ingests Tier-2 vault notes on cadence (`stale_after_hours` per workspace). Agents do **not** write to the substrate directly — no MCP write tools are exposed by design. | For **`lightrag`** workspaces only: `mcp__agentic-memory__query_knowledge_graph(prompt, workspace=…)` + `mcp__agentic-memory__search_*`. Not used for `graphiti` rows (offline-only). **Read at LOAD is mandatory** when a matching LightRAG workspace is live. |

Auto-memory (`~/.claude/projects/.../memory/`) is **not** a tier — it is a side channel actively deprecated for this project. See [`memory-three-tiers.md`](../01_Vault/AcCopilotTrainer/00_System/invariants/memory-three-tiers.md).

---

## LOAD protocol

At session start, the `SessionStart` command hook (`.claude/settings.base.json`) runs **deterministic** Python subprocesses that:

1. `cat docs/01_Vault/<ProjectKey>/00_System/Next Session Handoff.md` → first turn context.
2. `scripts/knowledge_session_summary.py` → top patterns from the local repo-knowledge SQLite.
3. `scripts/hook_session_start_memory_prefetch.py` → pre-fetches Tier-3 substrate findings for the workspace resolved from `ops/memory_manifest.yml` (matched by repo path), and **stamps `.scratch/.last_memory_query` with `{token, timestamp_utc, workspace, prompt}`**. If no workspace matches, the hook prints a `WARNING: no Tier-3 workspace registered` line and writes `.scratch/.last_memory_query.missing` — the gate hook then **degrades to warn-only** on code paths so the session is not bricked while PR C lands workspace provisioning. If sanitized bridge provenance is available and says the resolved live LightRAG workspace is disabled or not visible, the hook writes a **blocking** missing marker instead; the gate then fails fast so the agent cannot silently query another workspace universe. **This provenance is supplied automatically:** `scripts/mcp/agentic-memory.sh` runs `scripts/mcp/capture_bridge_provenance.py` before launching the MCP server, writing the live bridge's visible/disabled workspace set to `${XDG_CACHE_HOME:-$HOME/.cache}/agentic-memory/bridge_provenance.json` (rewritten every launch; the capture removes the file when it cannot refresh, so no mtime TTL is needed — an optional backstop is available via `AGENTIC_MEMORY_BRIDGE_PROVENANCE_MAX_AGE_S`; path override via `AGENTIC_MEMORY_BRIDGE_PROVENANCE_FILE`). So a manifest-declared workspace the bridge omits is surfaced at SessionStart rather than as `workspace_unknown` mid-session ([#172](https://github.com/agorokh/template-repo/issues/172)).
4. `scripts/hook_session_start_memory_redirect.py` → physically marks the auto-memory directory as deprecated (writes a `README.md` that explains the deprecation) so an agent that *tries* to write there sees the warning before silently succeeding.
5. `scripts/hook_session_start_post_merge_steward.py` → if local `main` is behind `origin/main`, prints a `POST-MERGE STEWARD NEEDED` routing block and writes `.scratch/post-merge-steward-needed.json`. This does not merge or pull by itself; it makes the agent-facing next action explicit before new implementation work starts.

**Agent obligation:** if you need to do meaningful work, **issue at least one `mcp__agentic-memory__query_knowledge_graph` call early in the session** with a prompt tied to the issue/branch/task. The SessionStart hook does an initial prefetch using branch name + issue title as the query; refine with a task-specific query once you understand scope.

If you are a **Task-spawned subagent**, the orchestrator embeds the SessionStart memory prefetch output as a `## Pre-loaded memory context` block in your prompt. You inherit the same lockfile on disk; further MCP queries supplement context but do not rewrite the gate stamp (only SessionStart prefetch updates `.scratch/.last_memory_query` today).

---

## SAVE protocol

At session end (Stop hook) or before a Phase-C vault commit:

1. **Vault SAVE** — Update `Next Session Handoff.md`. Add or update small linked nodes for any new investigation, decision, or convention per [`00_Graph_Schema.md`](../01_Vault/00_Graph_Schema.md). Prefer **new small files** over appending to monoliths.
2. **Tier-3 substrate write** — *agents never write to the substrate directly.* No MCP write tool is exposed; the substrate is rebuilt by re-ingesting Tier-2 vault notes on cadence. Material findings (architectural decisions, recurring failure patterns, fleet-wide invariant violations) become Tier-3-discoverable by being written as Tier-2 vault nodes (small linked markdown). For `lightrag` workspaces (canonical online), the ingest-audit launchd unit picks up new vault notes within `stale_after_hours`. Operational/audit events that don't merit a knowledge node go to JSONL audit logs alongside the vault (e.g. `docs/01_Vault/<ProjectKey>/_inbox/cycles/steward-events.jsonl`).
3. **Stop audit** — REMOVED 2026-05-20 (issue #205). Stop-hook advisory reminders cannot block per Anthropic spec, and the 2026 research in the slim-down ADR found prose-equivalent hooks emit text the agent learns to ignore. The PreToolUse gate is now the only enforcement point; LOAD-side discipline is mandatory, SAVE-side is honor-system.

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

## Conversational drift audit (removed 2026-05-20, issue #205)

The Stop drift-audit hook (`scripts/hook_stop_drift_audit.py`) was DELETED in the slim-down sweep. Prose-equivalent hooks that emit advisory text and exit 0 do not measurably change agent behavior — they generate alarm fatigue and a "super-ego" warning the next session ignores at the same rate (slim-down ADR, issue #205).

The enforcement that survives is the **PreToolUse memory gate** (`scripts/hook_memory_gate.py`) — the only deterministic block in the chain. Honest limit (unchanged): 2026 Claude Code has no `PreResponse` hook, so purely conversational drift on file-mutation-free sessions cannot be gated. We accept that limit rather than fake it with a Stop-hook advisory.
## Workspace lifecycle: declared ≠ registered ≠ provisioned

A Tier-3 workspace moves through **three distinct states**. Conflating them is
the root cause of [issue #169](https://github.com/agorokh/template-repo/issues/169):
a freshly bootstrapped repo *names* a workspace in `AGENTS.md` / vault state and
then an agent treats that name as if the substrate were live, hits the
resolution ladder cold, and burns a session on a spurious "architectural gap."

| State | What it means | How an agent detects it | Gate behavior (deterministic) | Correct agent action |
|---|---|---|---|---|
| **Declared** | The workspace *name* appears in `AGENTS.md` / vault, but there is **no manifest row and no live bridge entry**. Declaration is aspirational — it does **not** register or provision anything. | Resolution ladder steps 1–3 all miss (no `ops/memory_manifest.yml` row, no `…local.yml` row, name absent from `list_workspaces`). | **Warn-only** (bootstrap mode): SessionStart writes a no-workspace missing marker; `hook_memory_gate.py` allows code-path edits. | This is an **expected transient**, *not* a gap. Operate vault-only (Tier-2 grep/Read) for grounding; track substrate provisioning against the owning infra repo (workstation-ops). Do **not** file a fresh `architectural-invariant-gap` issue per session, and do **not** set `CLAUDE_MEMORY_GATE=0` — the gate already allows edits. |
| **Registered** | A manifest row exists (`ops/memory_manifest.yml` or `…local.yml`) but the substrate server isn't live yet — e.g. the `template_repo` placeholder row (`health_probe: false`, closed-loopback `http://127.0.0.1:1`), or any row whose workspace is **absent from the live bridge** `visible_workspace_ids`. | Ladder step 1/2 hits, but the prefetch query fails: unreachable endpoint, or `bridge_workspace_not_visible` / `bridge_workspace_disabled`. | **Hard block** (by #115 design): a *registered* workspace must be reachable before code edits. Unreachable/not-visible → blocking missing marker. | Provision the substrate (see below) **or** fix the bridge registry/allowlist so the workspace is visible. Only if neither is possible this session: set `CLAUDE_MEMORY_GATE=0`, **say why in the vault SAVE**, and ensure a provisioning issue is tracked against workstation-ops. Adding a placeholder row to "satisfy the ladder" makes the gate *stricter*, not looser — register a workspace only when you intend to provision it. |
| **Provisioned & visible** | Substrate server is live and the workspace appears in the bridge `visible_workspace_ids`. | `query_knowledge_graph(workspace=…)` returns content; `list_workspaces` lists it. | Normal: a fresh, file-relevant query stamps the lock and edits proceed. | Query early with a task-specific prompt; refine per file touched. |

**Rule of thumb for bootstrap:** declaring a workspace name is free and harmless
(warn-only), but **registering** a manifest row is a commitment to provision it —
until the server is live, a registered-but-unreachable workspace blocks edits on
purpose. Don't register ahead of provisioning unless you accept the block.

### Decision tree (authoritative — the skills link here)

Resolve the workspace via the ladder (`ops/memory_manifest.yml` → `…local.yml` →
`list_workspaces`), then **anchor every decision on the observable gate state**, not
on intent or how a doc "feels":

1. **Gate is warn-only** (no manifest row resolved → bootstrap mode) → **proceed.** Ground on vault Tier-2. **No** `architectural-invariant-gap` issue, **no** `CLAUDE_MEMORY_GATE=0`.
2. **Gate is blocking** (`bridge_workspace_not_visible` / `bridge_workspace_disabled` / unreachable on a *registered* row) → **fix first:** provision the substrate or correct the bridge registry/allowlist so the workspace is visible. Only if neither is possible this session, `CLAUDE_MEMORY_GATE=0` is a **last resort** — record the reason in the vault SAVE and confirm a workstation-ops provisioning issue exists.
3. **File an `architectural-invariant-gap` issue** *only* when an observable condition holds: (a) `AGENTS.md` / vault **asserts the workspace is already provisioned/queryable** yet the ladder finds nothing (a doc/state lie), or (b) provisioning is **observably overdue** — verifiable via `gh issue view` on the workstation-ops provisioning issue (missing, closed without the workspace going live, or past its recorded due-date/milestone).

Never file a per-session gap issue, and never normalize `CLAUDE_MEMORY_GATE=0`, for the expected *declared* transient (rule 1).

## What happens when something goes wrong

| Symptom | Cause | Recovery |
|---|---|---|
| Gate blocks every Edit on code paths | No SessionStart prefetch ran (e.g. hook script missing, repo-root mis-detected, or Claude/Cursor host doesn't fire SessionStart) | Run `python3 scripts/hook_session_start_memory_prefetch.py` manually to stamp the lockfile; or set `CLAUDE_MEMORY_GATE=0` and file an `architectural-invariant-gap` issue |
| Workspace named in `AGENTS.md` / vault but ladder finds no match (freshly bootstrapped repo) | Workspace is **declared, not registered** — see lifecycle table above | **Not a gap.** The gate is already warn-only (bootstrap mode); operate vault-only and track substrate provisioning against workstation-ops. Do not file a per-session `architectural-invariant-gap` issue and do not set `CLAUDE_MEMORY_GATE=0` for this state. File a gap issue only if the declaration claims the workspace is already live (a doc/state lie) or provisioning is **observably overdue** (the workstation-ops provisioning issue is missing, closed without the workspace going live, or past its recorded due-date/milestone). |
| Gate degrades to warn-only and logs `no Tier-3 workspace registered` | This repo is not in `ops/memory_manifest.yml` | Walk the workspace-resolution ladder before bypassing: (1) check `ops/memory_manifest.local.yml` (operator-owned, gitignored — schema in `ops/memory_manifest.local.example.yml`); (2) call `mcp__agentic-memory__list_workspaces` and if the repo basename appears in `visible_workspace_ids` (and not in `disabled_workspace_ids`), pass it explicitly to `mcp__agentic-memory__query_knowledge_graph(..., workspace=…)`; (3) if the gap is known and accepted, record the repo under a top-level `resolution_exceptions` block in `ops/memory_manifest.local.yml` (`reason` + `tracking_issue`) — SessionStart then degrades **quietly** (prints `accepted Tier-3 gap (tracked: …)`) and the ladder stops re-filing. **In this warn-only state the gate already permits code-path edits**, so `CLAUDE_MEMORY_GATE=0` is unnecessary and a per-session `architectural-invariant-gap` issue is wrong for a merely *declared* (not yet registered/provisioned) workspace — see the lifecycle table above. (4) For a genuine gap, first read `docs/01_Vault/AcCopilotTrainer/pitfalls/_index.md` and `.claude/pitfalls-hub.json`, then **dedup in the same tracker where the issue would be filed**: `gh issue list --repo <template-owner>/template-repo --state open --search "<repo-basename> Tier-3 workspace"` (and scan the `architectural-invariant-gap` label). Comment on a matching open issue instead of opening a duplicate; file against `<template-owner>/template-repo` only when the declaration claims the workspace is already live (a doc/state lie) or provisioning is observably overdue (the workstation-ops provisioning issue is missing, closed without the workspace going live, or past its recorded due-date/milestone). Canonical procedure: [`.claude/skills/resolve-pr/SKILL.md`](../../.claude/skills/resolve-pr/SKILL.md) § Workspace resolution. |
| Gate blocks with `bridge_workspace_not_visible` or `bridge_workspace_disabled` | Manifest workspace and active agentic-memory bridge registry disagree (now auto-detected: the wrapper captures live provenance to `…/agentic-memory/bridge_provenance.json` so the prefetch fires this check at SessionStart — [#172](https://github.com/agorokh/template-repo/issues/172)) | Run `mcp__agentic-memory__get_bridge_provenance` (and `list_workspaces` where available), inspect `registry_path`, `visible_workspace_ids`, and `disabled_workspace_ids`, then fix the bridge registry/allowlist. Do not proceed by querying an unrelated workspace. |
| MCP server unreachable | Substrate host down (verify with `mcp__agentic-memory__verify_server_health`) | Vault-only mode: query the vault directly via grep / Read; surface the substrate outage in the session handoff so the next session retries the prefetch |
| Subagent ignores memory contract | Orchestrator did not embed `## Pre-loaded memory context` in the Task prompt | Orchestrator bug — fix in `.claude/agents/issue-driven-coding-orchestrator.md`; the lockfile still gates the subagent's Edit/Write, so blast radius is contained |
| Agent writes to `~/.claude/projects/.../memory/` despite contract | The auto-memory directory marker was not yet written (first run after template upgrade) | The SessionStart redirect hook (PR B) creates the marker on every session start; if the agent still writes there, file an `architectural-invariant-gap` issue (this is a hook regression) |

---

## See also

- [`SESSION_LIFECYCLE.md`](SESSION_LIFECYCLE.md) — LOAD → OPERATE → SAVE that this contract slots into.
- [`MEMORY_SUBSTRATE.md`](MEMORY_SUBSTRATE.md) — Tier-3 substrate detail (LightRAG canonical online; Graphiti offline-only per sunset ADR; workspace schema).
- [`VAULT_TAXONOMY.md`](VAULT_TAXONOMY.md) — `origin` classification (`repo-product` / `repo-embedded` / `human-curated`).
- [`HOOK_DESIGN.md`](HOOK_DESIGN.md) — why hooks are deterministic and never LLM-bearing.
- [`memory-three-tiers.md`](../01_Vault/AcCopilotTrainer/00_System/invariants/memory-three-tiers.md), [`secrets-from-doppler.md`](../01_Vault/AcCopilotTrainer/00_System/invariants/secrets-from-doppler.md) — companion invariants.
- [`ops/memory_manifest.yml`](../../ops/memory_manifest.yml) — workspace registry.
