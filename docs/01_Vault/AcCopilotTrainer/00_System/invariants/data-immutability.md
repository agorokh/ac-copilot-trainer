---
type: invariant
status: active
created: 2026-03-27
updated: 2026-03-27
relates_to:
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/invariants/no-secrets.md
part_of: AcCopilotTrainer/00_System/invariants/_index.md
---

# Invariant: data immutability (raw / regulated)

## Rule

**Raw evidence**, **regulated data**, or other immutable corpora paths are **not agent-writable**. List concrete paths after bootstrap; enforce with hooks or CI if needed.

## Rationale

Prevents accidental corruption of evidence chains, PII stores, or golden datasets.

## Enforcement

- Declare forbidden write paths in this vault after specialization.
- **Template default:** only non-blocking PreToolUse prompts in `.claude/settings.json`; add an optional **shell** hook there if paths must be machine-blocked (e.g. disclosures-style `block-data-edits.sh`).
- Human review for any change touching listed paths.
