---
type: pitfall
status: active
created: 2026-04-10
updated: 2026-04-10
severity: security
scope_paths:
  - "scripts/**"
  - ".github/workflows/**"
  - "tools/**"
  - "**/*config*"
  - "**/*deploy*"
  - "**/.env*"
domains: [trading, infra, legal]
canonical_prs:
  - repo: agorokh/template-repo
    prs: [81]
    note: API key resolution not endpoint-aware -- OpenAI key silently sent to OpenRouter
  - repo: agorokh/dial-sandbox
    prs: [12]
    note: GHCR token passed on kubectl command line, visible in process listings
  - repo: agorokh/alpaca_trading
    prs: [756]
    note: Agent instructions contradict AGENTS.md deployment policy on credential handling
relates_to:
  - AcCopilotTrainer/00_System/invariants/no-secrets.md
  - AcCopilotTrainer/pitfalls/injection-risks.md
  - AcCopilotTrainer/pitfalls/_index.md
---

# Secret and credential handling

**4 clusters, 41 comments, 3 repos**

## Pattern

API keys passed via command-line arguments (visible in process listings), credentials sent to wrong endpoints due to missing provider validation, or hardcoded sandbox keys confused with production credentials.

Most common forms:
- `kubectl create secret --docker-password="$token"` exposes token in `ps aux`
- API key env var resolved without checking which endpoint it's for (OpenAI key sent to OpenRouter)
- `.env.example` contains real-looking placeholder values that are committed
- Agent docs reference credential patterns that contradict the project's AGENTS.md policy

## Preventive rule

1. **Never pass secrets via command-line arguments.** Use environment variables, mounted files, or stdin piping.
2. **Validate API key matches endpoint** before making requests. If `DISTILL_BASE_URL` points to OpenRouter, only `OPENROUTER_API_KEY` should be used.
3. **Use Doppler** (or your project's secret manager) for all secrets. Never read from `.env` directly in production paths.
4. **Placeholder values in `.env.example`** must be obviously fake (`sk-REPLACE-ME`, not `sk-abc123...`). Values that are committed must never resemble real credentials.

## Canonical damage

In `template-repo` PR #81, the distillation module resolved `OPENAI_API_KEY` regardless of which provider's `DISTILL_BASE_URL` was configured. This sent an OpenAI API key to the OpenRouter endpoint, which could have leaked the key to a third-party provider. Fixed by making key resolution endpoint-aware.
