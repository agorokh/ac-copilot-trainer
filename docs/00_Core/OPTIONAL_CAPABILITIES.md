# Optional capabilities (add only what you need)

Keep the template **lean**. Turn these on when the project actually needs them.

## Database (optional)

- **MCP:** e.g. SQLite (`mcp-server-sqlite` pattern), Postgres, or your org’s DB MCP — add to `.mcp.json` and document connection env vars in `.env.example`.
- **CI:** add a service container or mocked DB only when you have real integration tests.

## AWS / cloud deploy (optional)

- Add `ops/`, `infra/`, or IaC when you have a real deployment target; keep **secrets** in CI/org secrets, not in the repo.
- Claude agents/skills for deploy should be **human-gated** (`disable-model-invocation: true` where side effects are dangerous).

## Hugging Face / local models (optional)

- **Hugging Face:** document token in `.env.example`; prefer cache dirs outside the repo or gitignored caches.
- **Ollama / LM Studio:** document base URL and model names in `AGENTS.md` § Local development or `CLAUDE.md`; never commit API keys.

## Self-hosted PR-Agent / Qodo-compatible reviewer (optional)

For epic [#54](https://github.com/agorokh/template-repo/issues/54) Phase 2, run **[PR-Agent](https://github.com/qodo-ai/pr-agent)** (open source) on your infrastructure with a commodity model and repo-specific instructions. This template already carries **hosted** Qodo wiring (`.pr_agent.toml`, [Library Map](../01_Vault/AcCopilotTrainer/00_System/Library%20Map.md)); self-hosted is **operator-maintained** and not part of `make ci-fast`.

- **Docs:** vault ADR [self-hosted-pr-agent-baseline](../01_Vault/AcCopilotTrainer/01_Decisions/self-hosted-pr-agent-baseline.md) — context injection, checklist, non-goals.
- **Secrets:** configure per upstream PR-Agent docs (API keys or local inference URL); keep in `.env` / CI secrets only.

## Browser / E2E (optional)

- **Playwright** or **agent-browser**-style tooling — add when you have a UI worth automating; keep smoke tests fast in CI.

When you add an optional stack, update these vault docs so agents do not guess:

- [00_Graph_Schema.md](../01_Vault/00_Graph_Schema.md) (link new nodes per schema)
- [Architecture Invariants.md](../01_Vault/AcCopilotTrainer/00_System/Architecture%20Invariants.md) / [invariants/_index.md](../01_Vault/AcCopilotTrainer/00_System/invariants/_index.md)
- [Library Map.md](../01_Vault/AcCopilotTrainer/00_System/Library%20Map.md)
