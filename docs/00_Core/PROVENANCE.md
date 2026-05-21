# Provenance

This template generalizes practices observed across:

| Repository | Notable patterns absorbed |
|------------|---------------------------|
| `your-org/example-trading-repo` | `.claude/settings.json` hook style, policy CI for canonical docs, `AGENTS.md` / `CLAUDE.md` depth, mirrored `.cursor` skills, Bugbot injection, Dependabot + security workflows, vault path layout |
| `your-org/example-doc-pipeline` | `make ci-fast` parity, doc hygiene and agent-proofing **scripts** as CI gates, layered `docs/10_Development` protocol, issue/PR templates |
| `your-org/example-legal-repo-b` | `check_policy_docs.sh`, SQLite MCP example, `block-data-edits`-style path protection (adapt per project), `policy.yml` split from main CI |
| `your-org/example-text-analysis` | `CLAUDE.md` session tail + `AGENTS.md` durable changelog blocks, long-form operator guide (now consolidated into `AGENTS.md`) |

Domain-specific content (trading runtime, OCR pipelines, legal-discovery DB schemas, text-analysis ML) was **not** copied. Replace `AcCopilotTrainer` vault folder names and edit invariants before serious use.

**Evolving the template:** [MAINTAINING_THE_TEMPLATE.md](MAINTAINING_THE_TEMPLATE.md), [TOOLCHAIN.md](TOOLCHAIN.md), [GITHUB_SETUP.md](GITHUB_SETUP.md).
