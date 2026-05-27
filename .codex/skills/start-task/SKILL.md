---
name: start-task
description: Initialize ANY non-trivial work session that is NOT a code change — deck, report, paper, diagram, explanation, ADR draft, research synthesis, written critique, slide narrative, vault note refactor — with the full discipline stack. Forces Tier-3 memory query, vault subgraph LOAD, sibling-skill selection, council deliberation when warranted, and an explicit artifact-handoff plan BEFORE any substantive output. Use this when /orchestrate (issue → branch → code) does not fit. If you are asked to "write", "draft", "explain", "summarize", "compare", "design a deck", "produce a report", "review an artifact", or "propose an approach" — invoke this first.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent
---

# /start-task — discipline gate for non-code work

## Why this exists

When Claude Code, Codex, or Cursor is used for a non-code task (deck, report, paper, explanation), the deterministic PreToolUse memory gate does **not** fire — `docs/**`, `.scratch/**`, root `*.md` are exempt by design ([`MEMORY_CONTRACT.md`](../../../docs/00_Core/MEMORY_CONTRACT.md) § Runtime gate). The agent then defaults to: produce the artifact directly, skip the substrate, skip the vault, skip the council. The 2026 Anthropic research surveyed in [`adr-2026-05-20-slim-down-discipline-mechanism.md`](../../../docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-20-slim-down-discipline-mechanism.md) is explicit that advisory prose alone does not change this — agents learn to ignore it.

This skill is the honest answer: a **front-loaded, contractual checklist** that must be discharged before *any* substantive output, with a `.scratch/.last_start_task.json` stamp that the operator and follow-up hooks can audit. The skill body is itself the highest-signal place to push the agent away from its default — every rule below is something that would otherwise be skipped.

## Canonical source and mirrors

**Canonical:** `.claude/skills/start-task/SKILL.md`. Host mirrors under `.cursor/skills/`, `.codex/skills/`, and `.agents/skills/` are verbatim copies for surface parity per [orchestration.md](../../../.claude/rules/orchestration.md). When you change this skill, edit the canonical file first, then copy to all mirrors in the same commit. A future `make skills-mirror` extension may automate workflow-skill sync; until then, manual copy is the fleet pattern for `/orchestrate`, `/resolve-pr`, and siblings.

## First-reply contract (NON-NEGOTIABLE)

Your **first substantive reply** to the operator MUST contain — verbatim, in this order, under explicit headings:

1. **`## Task classification`** — one of: `deck` / `report` / `paper` / `diagram` / `explanation` / `adr-draft` / `research-synthesis` / `artifact-review` / `vault-note` / `other:<short noun>`. State the **target audience** in one phrase (`operator`, `EPAM internal`, `external readers`, `court`, etc.).
2. **`## Pre-loaded substrate context`** — the verbatim or summarized response from `mcp__agentic-memory__query_knowledge_graph` for the resolved workspace. If you skipped this and have a justification, write the justification here instead — but be honest: "I skipped Tier-3" is a contract violation unless the substrate is provably down.
3. **`## Vault subgraph loaded`** — the paths you opened from `docs/01_Vault/<ProjectKey>/` (handoff → `relates_to` subgraph → glossary terms you needed). Empty list is acceptable for one-shot artifacts that have no vault precedent — say so explicitly.
4. **`## Sibling skills selected`** — bulleted list of the named skills you will defer to for the actual artifact (see § **Sibling-skill selection** below). Empty list means you are intentionally not deferring — justify in one line.
5. **`## Council decision`** — one of: `not-required` (with reason) / `required:gemini` / `required:mistral` / `required:both`. See § **Council routing** below. If council is required, surface the council outputs **before** you write the artifact.
6. **`## Artifact handoff plan`** — where the deliverable lands: vault path under `docs/01_Vault/<ProjectKey>/`, an outputs directory, `.scratch/` (for ephemeral), or "operator inbox / chat only" (for transient explanations). If the artifact will be published externally (Slack, Medium, Confluence, Notion, GitHub Pages, an EPAM client), say so — this triggers mandatory council.

You then write `.scratch/.last_start_task.json` (schema in § **Stamp file**) and only THEN proceed to the actual work.

## Procedure (numbered, mandatory)

### 1. Classify the task — pick ONE primary type

| Primary type | Trigger | Typical sibling skill(s) |
|---|---|---|
| `deck` | "make a deck / slides / pitch / pptx" | `anthropic-skills:epam-pptx`, `anthropic-skills:pptx`, `anthropic-skills:epam-html-deck` |
| `report` | "report / write-up / executive summary" | `anthropic-skills:docx`, `epam-research-narrative`, `data-storytelling` |
| `paper` | "paper / publishable narrative / Medium post" | `epam-research-narrative` (mandatory for EPAM/external), `code-review` (if it cites code) |
| `diagram` | "diagram / architecture sketch / flowchart" | `anthropic-skills:canvas-design`, `anthropic-skills:algorithmic-art`, `anthropic-skills:epam-html-deck` (for tier-grid) |
| `explanation` | "explain / how does X work / walk me through" | `claude-code-guide` (for Claude tooling), `project-conventions` (for repo norms), substrate query only |
| `adr-draft` | "draft an ADR / write a decision" | `vault-memory` (mandatory — ADRs are vault nodes), `code-review` if irreversible |
| `research-synthesis` | "synthesize this corpus / what do these say" | `epam-research-narrative` if external, `vault-memory` for SAVE |
| `artifact-review` | "review this PDF / deck / draft" | `comprehensive-review:full-review`, `code-review`, `epam-research-narrative` if EPAM-bound |
| `vault-note` | "add to the vault / log this decision" | `vault-memory` (mandatory) |
| `other:<noun>` | none of the above | document why you picked `other` |

If the task is "implement a feature / fix a bug / land a PR" — **STOP and invoke `/orchestrate` instead**. This skill is for non-code work.

### 2. Tier-3 substrate query (mandatory)

**Shared contract:** workspace resolution, query discipline, and degraded-mode bypass follow [`MEMORY_CONTRACT.md`](../../../docs/00_Core/MEMORY_CONTRACT.md) § Tier-3 Substrate Query (same baseline as `/orchestrate`, `/resolve-pr`, and sibling workflow skills). This section adds only start-task-specific prompt nouns.

Resolve the workspace from `ops/memory_manifest.yml` by repo basename (e.g. `agent_factory_steward` for `agent-factory/`, `dial_sandbox_mnemos` for `dial-sandbox/`). Then call:

```
mcp__agentic-memory__query_knowledge_graph(
    prompt="<task type> | <key nouns from operator's ask> | <expected sibling-skill names> | <prior related decisions if known>",
    workspace="<resolved>",
    limit=80,
)
```

**Refine** with a follow-up query naming the specific concepts the first response surfaces. The stamp is invalidated if your query doesn't mention the topic — the gate's relevance check rejects "query spam" (issue #115 fix in [`hook_memory_gate.py`](../../../scripts/hook_memory_gate.py)).

**Substrate unreachable?** Write a one-line rationale to `.scratch/.memory_bypass_rationale` (auditable bypass — see [`MEMORY_CONTRACT.md`](../../../docs/00_Core/MEMORY_CONTRACT.md) § Degraded mode). Do not silently proceed — that is the failure mode the contract exists to prevent.

### 3. Vault subgraph LOAD

Per [`SESSION_LIFECYCLE.md`](../../../docs/00_Core/SESSION_LIFECYCLE.md) §LOAD: open `Next Session Handoff.md` first, follow its `relates_to` to the small subgraph the task touches, then `Current Focus.md` if branch context matters. Glossary nodes only when terminology is ambiguous. Do **not** load the entire vault — load only what the task names.

### 4. Sibling-skill selection

Use the routing table in § **1. Classify the task** above. **Defer the actual artifact production to the sibling skill** — `/start-task` is the discipline gate, not the producer. If you write a deck without invoking `epam-pptx` / `epam-html-deck` / `pptx`, that is a contract violation; if you produce a CA family-law document without `anthropic-skills:ca-pleading-paper`, same.

Surface the sibling-skill names in your first reply (contract bullet #4). When `Skill` is available, invoke them directly. When not, embed their relevant checklist verbatim from the corresponding `SKILL.md`.

### 5. Council routing

| Trigger | Council required | Why |
|---|---|---|
| External publication (Medium, Confluence, EPAM client, Slack to anyone outside `#me`) | **both** (`gemini_second_opinion` + `mistral_second_opinion`) | Adversarial review on factual claims and framing before the artifact escapes the local context |
| Irreversible / fleet-wide decision (ADR, propagation plan, dependency choice that affects N≥3 repos) | **both** | Mistral does adversarial; Gemini stress-tests design |
| Cross-domain claim (mixes legal + technical, finance + engineering, etc.) | **mistral** at minimum | Adversarial framing surfaces over-claims |
| Factual claim about people, markets, EPAM offerings, or external entities | **gemini** at minimum | Second eye on facts |
| Pure format conversion (CSV → table, JSON → markdown), glossary lookup, internal walkthrough that names no facts | not-required | Council adds cost without signal |
| Operator explicitly asked for council, deliberation, or "second opinion" | **both** | Honor the explicit request |

If the council disagrees with each other, surface that disagreement in the first reply under `## Council decision` — do not silently average them.

### 6. Stamp file

Machine-checked contract: [`ops/schemas/last_start_task.schema.json`](../../../ops/schemas/last_start_task.schema.json) (JSON Schema draft 2020-12). Hooks and tests should validate stamps against that file rather than re-deriving rules from prose.

Write (or update) `.scratch/.last_start_task.json` with at least (use **one** `council_decision` enum value from the schema — not a pipe-separated list):

```json
{
  "timestamp_utc": "<ISO-8601>",
  "task_type": "<one of the classifications>",
  "audience": "<one phrase>",
  "workspace": "<resolved Tier-3 workspace>",
  "substrate_query_token": "<short hash or first 80 chars of the response>",
  "vault_paths_loaded": ["..."],
  "sibling_skills_selected": ["..."],
  "council_decision": "not-required",
  "artifact_handoff": "<vault path | outputs dir | .scratch/<file> | operator-inbox>",
  "operator_brief_oneline": "<paraphrase of the operator's ask in <=120 chars>",
  "closed_at": null,
  "outcome": null
}
```

`closed_at` and `outcome` stay `null` at open; set them only at close-out (`shipped` / `paused` / `dropped`) per § **SAVE contract** below.

This stamp is the **honest audit trail**. The follow-up gate (see § **Future: deterministic teeth** below) checks it before allowing publication-surface writes. For V1, you write it manually and it serves as your own commitment device.

### 7. Artifact handoff

Produce the artifact in the location named in `artifact_handoff`. After the artifact is final, run the SAVE side per [`SESSION_LIFECYCLE.md`](../../../docs/00_Core/SESSION_LIFECYCLE.md):

* Add/update a small linked vault node — typically `investigation` or `insight` type — under the appropriate `docs/01_Vault/<ProjectKey>/` folder, with `relates_to` pointing back to the artifact and any council inputs.
* Update `Next Session Handoff.md` with what shipped, what's pending.
* For external publications, capture the council outputs verbatim in `.scratch/` and reference them from the vault node — they are evidence the discipline was followed.

## Anti-patterns (council-defined, verbatim from review)

| Anti-pattern | Symptom | Mitigation |
|---|---|---|
| **Ghost writing** | Drafting the deliverable before the stamp file exists | The stamp file is step 6 for a reason — discharge the contract first |
| **Simulated consensus** | "The council would say X" / "Per best practices…" without actually invoking the council | Council MCP calls are concrete tool calls — execute them, capture verbatim outputs |
| **Premature exemption exploitation** | Writing to `docs/**` or external surfaces because the PreToolUse gate doesn't fire there | Treat `start-task` invocation as your gate; write to `.scratch/` first, promote only after the handoff plan resolves |
| **Sibling-skill bypass** | Producing a deck/paper/CA-court-doc directly instead of routing through `epam-pptx` / `epam-research-narrative` / `ca-pleading-paper` | The routing table is mandatory, not advisory |
| **Substrate spam** | Querying with generic strings (`"agent factory main"`) to mint a stamp without relevance | The Tier-3 query must mention the task's nouns; the gate's relevance check rejects spam |
| **Audience drift** | Operator says "internal" but the artifact reads like an external publication, or vice versa | Lock the audience phrase in step 1 and reference it when the council reviews tone |
| **Vault-only theatre** | Updating the vault but never naming sibling skills or council inputs | The vault node should cite both — that's how future sessions trace the discipline |

## Sibling-skill discoverability

If the operator's request is ambiguous, the order to **discover** sibling skills (cheapest first):

1. The routing table in § **1. Classify the task**.
2. The `Skill` tool listing (each entry has a one-line description and trigger phrases).
3. `.claude/skills/*/SKILL.md` frontmatter (`description` field) — `grep -l "^name: " .claude/skills/*/SKILL.md`.
4. `.claude/rules/orchestration.md` for any role-table additions since this skill last shipped.

Do **not** invent a sibling skill that doesn't exist. If the right skill is missing, surface the gap in your first reply and propose creating it via `propose-new-skill` — never simulate one inline.

## Future: deterministic teeth

V1 of this skill relies on the operator-visible stamp file + honor-system contract. The follow-up extension (tracked separately) is a PreToolUse matcher that:

1. Detects Bash/Write/Edit touching a **publication surface** outside `.scratch/` and not under `docs/01_Vault/<ProjectKey>/_inbox/` (the curated holding area).
2. Requires `.scratch/.last_start_task.json` to exist, be <2h fresh, and name the touched path under `artifact_handoff`.
3. Blocks otherwise with a message pointing back to this skill.

That extension belongs in [`scripts/hook_memory_gate.py`](../../../scripts/hook_memory_gate.py) (or a sibling `hook_publication_gate.py`) so the enforcement is deterministic, not prose-equivalent. Validation should call the same [`ops/schemas/last_start_task.schema.json`](../../../ops/schemas/last_start_task.schema.json) used at write time. It is **not** in V1 because shipping the gate without operator buy-in repeats the alarm-fatigue failure mode the slim-down ADR prohibits.

## SAVE contract

When the task closes (delivered, abandoned, or paused):

1. **Update the stamp** — set `closed_at` (ISO-8601) and `outcome` to one of `shipped` / `paused` / `dropped` on `.scratch/.last_start_task.json` (replacing the `null` placeholders from § **Stamp file**).
2. **Vault node** — add or extend a small linked node (`investigation`, `insight`, `decision`, `attachment` per `00_Graph_Schema.md`). Link it to the artifact, the council inputs (if any), and the substrate response.
3. **Handoff** — append a one-line note to `Next Session Handoff.md` so the next session knows the artifact exists and where it lives.

## See also

* [`docs/00_Core/MEMORY_CONTRACT.md`](../../../docs/00_Core/MEMORY_CONTRACT.md) — three-tier memory architecture (this skill is the LOAD-side discipline for non-code work).
* [`docs/00_Core/SESSION_LIFECYCLE.md`](../../../docs/00_Core/SESSION_LIFECYCLE.md) — LOAD → OPERATE → SAVE.
* [`docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-20-slim-down-discipline-mechanism.md`](../../../docs/01_Vault/AgentFactory/01_Decisions/adr-2026-05-20-slim-down-discipline-mechanism.md) — why prose alone fails; why this skill is contractual, not advisory.
* `/orchestrate` — sibling skill for code work (issue → branch → PR).
* `/vault-memory` — sibling skill for vault LOAD / SAVE primitives.
