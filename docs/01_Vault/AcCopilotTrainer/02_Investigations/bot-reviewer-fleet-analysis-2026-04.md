---
type: investigation
status: active
created: 2026-04-10
updated: 2026-04-10
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/02_Investigations/process-miner-corpus-analysis-2026-04.md
  - AcCopilotTrainer/01_Decisions/self-hosted-pr-agent-baseline.md
---

# Bot reviewer fleet analysis (April 2026)

## Fleet composition

7 bots review PRs across the 13-repo fleet. Each has distinct strengths.

| Bot | Trigger | Focus | Value |
|-----|---------|-------|-------|
| **CodeRabbit** | Every push (GitHub App) | Security, architecture, code quality | Highest volume (~32% of comments). Deep analysis chains with web queries. |
| **Copilot** | Every push (GitHub native) | Bugs, logic errors, consistency | Good at spotting functional issues. Concise. |
| **Cursor Bugbot** | Every push (GitHub App) | Bugs with code-level citations | Specific file:line anchored findings. Autofix links. |
| **Sourcery** | Every push (GitHub App) | Code quality, testing gaps, refactoring | Structured guide + sequence diagrams. |
| **Gemini** | Every push (GitHub App) | Maintainability, style consistency | Medium priority, sometimes flags real issues (bot name lists). |
| **Codex (ChatGPT)** | Every push (GitHub App) | Priority-badged findings (P1/P2) | Lower volume but occasionally catches what others miss. |
| **Qodo** | PR publish only (SaaS, 30/month free cap) | Bugs, rule violations, requirement gaps | Best structured format. Limited by free tier. |

## Qodo SaaS issue (discovered April 2026)

Qodo stopped reviewing after PR #77 (April 5, 2026). Investigation found:

1. **Free tier cap:** 30 PR reviews/month across all repos. With 13 repos, exhausted quickly.
2. **No push trigger by default:** Dashboard only offers "Published PRs" or "Manual." The `.pr_agent.toml` setting `[github_app] handle_push_trigger = true` enables push reviews but each burns 1 credit.
3. **Fix applied:** `handle_push_trigger = true` + `push_commands = ["/review"]` added. Strategic usage guidelines in TOML header for agents.
4. **Self-hosted workflow:** `.github/workflows/qodo-review.yml` created but disabled (`workflow_dispatch` only). Ready for future local LLM (Qwen3.5 5-8B on dedicated Mac).

### Strategic Qodo usage (for agents)

- **USE /review when:** PR has 3+ changed files, touches security/auth/financial paths, refactors a module boundary, or other bots disagree on severity
- **SKIP when:** docs-only, vault-only, dependency bumps, or other bots already surfaced the same findings
- **Budget:** 30 credits/month, each push = 1 credit

## Bot noise problem

~60% of total comment volume is process chrome (status notifications, rate limits, trial promos, review summaries). PR #81 adds pre-cluster filtering to drop these before clustering.

After chrome removal, remaining comments are predominantly:
- Inline code findings (the actual signal)
- PR summary comments (useful for context, not for mining)
- Duplicate/stale re-posts of already-fixed findings (bots don't diff against their own prior feedback — every push re-posts the same comment if the code location still exists)

## Key insight: stale re-posting

Bots re-post the SAME finding on every push even after it's been fixed. This is the #1 source of "recursive comments" the user observed (50-250 comments per PR). The comments aren't new issues — they're stale echoes.

**Implication for miner:** deduplication by (file, line, finding-hash) across commits within a PR is essential to count true recurrences vs stale re-posts. Currently not implemented.

## Doppler centralization (in progress)

All API keys for the fleet should live in Doppler (`ag-dev-ecosystem` project):
- `OPENROUTER_API_KEY` — confirmed in `dev_personal` config
- `MISTRAL_API_KEY` — confirmed
- GitHub PAT — not yet in Doppler (using `gh auth token` locally)
- Bot-specific keys — managed by each SaaS provider, not in Doppler

For GitHub Actions secrets, Doppler's GitHub integration (`doppler/cli-action`) should replace per-repo secret management. Not yet implemented.
