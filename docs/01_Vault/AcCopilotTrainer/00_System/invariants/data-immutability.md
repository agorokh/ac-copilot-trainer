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

## Concrete immutable paths (this project)

- `journal/laps/lap_*.json` — per-lap telemetry archives (write-once by the trainer / importers; read-only to analysis).
- `journal/tt/**` — Track Titan personal session lake (issue #353). Raw vulcan/services responses are retained **write-once** keyed by car + track + setup; `tools.tt_ingest` refuses to clobber an existing file (`write_immutable_json(..., overwrite=False)`). Gitignored (personal data). Only the *derived* `journal/tt/index.json` + `journal/tt/sessions_index.json` are regenerated idempotently.

## Enforcement

- Declare forbidden write paths in this vault after specialization.
- **Template default:** only non-blocking PreToolUse prompts in `.claude/settings.json`; add an optional **shell** hook there if paths must be machine-blocked (e.g. disclosures-style `block-data-edits.sh`).
- Human review for any change touching listed paths.
- `tools.tt_ingest` enforces write-once for `journal/tt/**` in code (atomic temp + `os.replace`, existing-file guard).
