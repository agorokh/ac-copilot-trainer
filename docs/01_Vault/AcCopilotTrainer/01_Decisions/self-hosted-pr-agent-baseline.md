---
type: decision
status: draft
created: 2026-04-04
updated: 2026-04-04
id: ADR-PR-AGENT-BASELINE
area: code-review
memory_tier: canonical
issue: https://github.com/agorokh/template-repo/issues/54
relates_to:
  - AcCopilotTrainer/01_Decisions/_index.md
  - AcCopilotTrainer/01_Decisions/local-reviewer-model.md
  - AcCopilotTrainer/00_System/Library Map.md
---

# Self-hosted PR-Agent baseline (epic #54 Phase 2)

## Context

[Issue #54](https://github.com/agorokh/template-repo/issues/54) tracks a self-hosted reviewer using **PR-Agent**-compatible open-source tooling plus a future fine-tuned model (extends [#26](https://github.com/agorokh/template-repo/issues/26)). Phase 1 data collection is unblocked: [#56](https://github.com/agorokh/template-repo/issues/56) (miner bot metadata) and [#26](https://github.com/agorokh/template-repo/issues/26) Phase 1 (training export scaffold, [PR #31](https://github.com/agorokh/template-repo/pull/31)) are done.

Hosted **Qodo** in this repo uses PR-Agent-style config at `.pr_agent.toml` (see [Library Map](../00_System/Library%20Map.md)). Phase 2 adds a **self-hosted** runner so reviews can use vault context and stay on your network boundary.

## Decision (Phase 2 — baseline, not production cutover)

1. **Upstream:** Follow the **Qodo / PR-Agent** open-source install and runtime docs ([`qodo-ai/pr-agent`](https://github.com/qodo-ai/pr-agent)). **Reproducibility:** record the **release tag or container digest** you run in operator notes and bump intentionally when comparing Phase 2 metrics; do not fork behavior in this template until a project-specific need appears.
2. **Model:**
   - For **metrics that inform Phase 4** (#54 catch-rate goals), prefer a **hosted commercial API** (OpenAI, Anthropic, Gemini, etc.)—PR-Agent upstream docs recommend commercial models for production-style structured review.
   - Many open-source/local models are fine for **experimentation and wiring** but often underperform on full review workflows.
   - **Ollama / LM Studio** remains valid for bring-up per [OPTIONAL_CAPABILITIES.md](../../../00_Core/OPTIONAL_CAPABILITIES.md); treat OSS-only catch-rate numbers as **non-representative** unless/until Phase 3 fine-tuning or a stronger endpoint.
   - **Egress / residency:** Hosted commercial APIs send review context (diffs, excerpts) to the vendor. If policy requires **no third-party code egress**, use **local inference** only. Otherwise, use **org-approved** providers with **secret/PII minimization** (never paste credentials; align with repo secret hygiene) and **security/legal** approval where your org mandates it.
   - No custom weights in Phase 2.
3. **Context injection:** Mount or copy **read-only** pointers for the same governance layers human agents use:
   - Repo root: [AGENTS.md](../../../../AGENTS.md), [AGENT_CORE_PRINCIPLES.md](../../../../AGENT_CORE_PRINCIPLES.md), [CLAUDE.md](../../../../CLAUDE.md)
   - Vault: [Architecture Invariants](../00_System/Architecture%20Invariants.md), [invariants index](../00_System/invariants/_index.md). Paths use the template folder name `AcCopilotTrainer`; after bootstrap, substitute `docs/01_Vault/<ProjectKey>/...` per [00_Graph_Schema.md](../../00_Graph_Schema.md)—**relative links from this ADR stay the same** once the vault folder is renamed.

   Exact mechanism (Docker volume, CI artifact, or CLI flag) is left to the operator; secrets stay in `.env` / CI secrets only.
4. **Comparison:** Run self-hosted reviews **alongside** existing bots until catch-rate / false-positive metrics justify Phase 4 cutover (#54).

## Non-goals (this phase)

- Replacing hosted Qodo/CodeRabbit/Gemini in CI by default.
- Training or serving the fine-tuned model (Phase 3).

## Consequences

- Operators maintain PR-Agent version + model endpoint outside `make ci-fast`.
- Future Phase 3 ties miner export + SFT records from `tools/model_training/` into review prompts or adapters.

## Checklist (operator)

- [ ] PR-Agent installed per upstream (container or CLI).
- [ ] Model provider configured (API key or local base URL); never committed.
- [ ] Repo rules + vault invariant excerpts available to the review prompt or config.
- [ ] At least one trial PR reviewed; notes captured for #54 metrics.
