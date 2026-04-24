---
type: index
status: active
created: 2026-04-10
updated: 2026-04-10
relates_to:
  - AcCopilotTrainer/01_Decisions/_index.md
  - AcCopilotTrainer/00_System/invariants/_index.md
---

# Investigations (index)

Deep-dive analyses that inform decisions and architecture. Each node captures findings, data, and conclusions from a bounded investigation.

| Node | Summary |
|------|---------|
| [process-miner-corpus-analysis-2026-04.md](process-miner-corpus-analysis-2026-04.md) | Fleet-wide miner run: 10k comments, zero human signal, TF-IDF finds only bot chrome, real patterns require semantic clustering. |
| [bot-reviewer-fleet-analysis-2026-04.md](bot-reviewer-fleet-analysis-2026-04.md) | 7-bot reviewer fleet composition, Qodo SaaS cap issue, stale re-posting noise, Doppler centralization status. |
| [post-merge-determinism-overhaul-2026-04.md](post-merge-determinism-overhaul-2026-04.md) | Two-phase post-merge steward, exit-code contract, vault SAVE via labeled PR + auto-merge workflow (no more agent push to main). |
| [pr-pain-detection-workflow-2026-04.md](pr-pain-detection-workflow-2026-04.md) | Linear pain score over merged PRs → process-learning issue in template-repo, fingerprint-deduped across child repos, allowlist-gated. |
