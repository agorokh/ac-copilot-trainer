---
type: decision
status: draft
created: 2026-03-28
updated: 2026-03-29
id: ADR-T3-REVIEWER
area: ml-training
relates_to:
  - AcCopilotTrainer/01_Decisions/_index.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Local fine-tuned reviewer model (Tier 3)

## Context

Epic #26 tracks a small, repo-specific reviewer model. Tier 1+2 (#21) supply structured SQLite + miner-shaped evidence; Tier 3 adds formatting, training, and optional integration.

## Decision (Phase 1 shipped)

- **Phase 1** keeps the training **data exporter** in `tools/model_training/` **stdlib-only** so `make ci-fast` stays free of torch/Unsloth.
- **SFT JSONL** uses a `messages` array (system / user / assistant), where the user message includes placeholder review context until real diff hunks are wired in; records are sourced from `pattern_evidence` and optional `decisions` rows.
- **Artifacts**: default export paths under `.cache/training_data/` (already covered by root `.gitignore` for `.cache/`); **model weights** under `/models/` (gitignored at repo root only).

## Deferred

- **DPO / CPT** formatters are stubs until labels and corpus policy exist.
- **Training loop, Ollama, CI GPU** — later phases; see issue #26 body.

Phase 1 implementation PR: https://github.com/agorokh/template-repo/pull/31

## Consequences

- Consumers install optional extras only when implementing Phase 2+ training locally.
- Placeholder user prompts document where PR diff hunks must be injected in a future milestone.
