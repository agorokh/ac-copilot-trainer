---
type: investigation
status: active
created: 2026-04-10
updated: 2026-04-10
memory_tier: canonical
issue: https://github.com/agorokh/template-repo/pull/81
relates_to:
  - AcCopilotTrainer/01_Decisions/self-hosted-pr-agent-baseline.md
  - AcCopilotTrainer/01_Decisions/local-reviewer-model.md
  - AcCopilotTrainer/00_System/invariants/_index.md
---

# Process miner corpus analysis (April 2026)

## Context

Fleet-wide aggregate run on 2026-04-09: 13 repos, 232 PRs, 10,025 comments, 120-day window. PR #81 implements semantic clustering + frontier distillation to address findings below.

## Finding 1: The corpus has zero human signal

**All 10,025 comments are agent-authored.** There are no human reviewers.

| Author | Role | Count |
|--------|------|-------|
| `coderabbit[bot]` | External review bot | ~3,200 |
| `copilot` | External review bot | ~2,100 |
| `cursor[bot]` (Bugbot) | External review bot | ~2,000 |
| `sourcery-ai[bot]` | External review bot | ~800 |
| `chatgpt-codex-connector[bot]` | External review bot | ~400 |
| `gemini-code-assist[bot]` | External review bot | ~300 |
| `agorokh` | Agent-as-user (Claude Code, Cursor acting under user PAT) | ~1,200 |

Comments under `agorokh` are NOT human — they are agents (Claude Code, Cursor) that inherit the user's GitHub identity because they use his PAT. The user never manually writes PR review comments.

**Implication:** Mining PR comments for "human engineering wisdom" is fundamentally impossible with this corpus. The miner was built to extract patterns from experienced engineers; what it actually sees is agents-reviewing-agents in a recursive loop.

## Finding 2: TF-IDF clustering finds only bot process chrome

The Apr 9 aggregate produced **9 universal (S0) clusters**, all bot chrome:

- `code / lgtm / with` — auto-generated review summaries
- `code / check / passed` / `code / passed / check` — status notifications
- `your / limits / have` — Codex usage limit alerts
- `code / added / tests` — generic test coverage mentions
- `code / code_block / ensure` / `code / code_block / script` / `code / code_block / with` — vague code-block references

Zero of these carry engineering signal. TF-IDF clusters by surface-word overlap, so conceptually related findings (e.g. "silent exception swallowing" across 8 PRs with different vocabulary) scatter into separate clusters and never reach universal rank.

## Finding 3: Real recurring patterns exist but are invisible to TF-IDF

Manual audit of `alpaca_trading` cache (50 PRs, 1,916 comments) found concrete, recurring implementation mistakes:

### Pattern A: Silent exception swallowing (8 PRs, 18 findings)

The same conceptual mistake applied to different contexts over 3+ months:

| PR | File | Mistake |
|----|------|---------|
| #842 | `agent/streaming/alpaca_stream_listener.py` | Async reconnect wraps sync DB I/O in bare except, drops metrics silently |
| #818 | `core/errors/error_handler.py` | `LogAndReRaiseStrategy` named to re-raise but `handle()` silently returns None |
| #792 | `agent/streaming/nodes/gate_factory.py` | `fail_open=True` returns `{result_key: True}` on ANY exception |
| #758 | `agent/streaming/service.py` | try/except around import that always fails → fallback permanently active |
| #756 | `analytics_ui/views/bot_management.py` | `except Exception: pass` around `inject_live_banner()` |
| #751 | `core/services/circuit_breaker_service.py` | **Kill switch disabled:** `ValueError` → allocation=0.0 → daily loss breaker never triggers |
| #751 | `agent/streaming/nodes/receive_event.py` | Bare `except Exception` around `resolve_from_row()`, no logging |
| #739 | `analytics_ui/utils/live_config.py` | Probe failure swallowed, live DB outage invisible |

**Severity:** PR #751's pattern disabled the kill switch — a complete safety invariant failure.

### Pattern B: Secret/credential exposure (5 PRs)

| PR | File | Mistake |
|----|------|---------|
| #776 | `docs/40_Infrastructure/72_Deployment_Verification_Workflow.md` | Docs teach passing creds on CLI — leaks via `ps` + shell history |
| #768 | `docs/10_Development/20_Analytics_UI_Design_System.md` | Raw Figma share key committed, Gitleaks fired |
| #744 | `scripts/deploy_aws_paper.sh` | `2>/dev/null` hides stack traces and secret-related errors |
| #736 | `scripts/provision_live_db.sh` | `LIVE_DB` interpolated into `CREATE DATABASE` — SQL injection |
| #745 | `.cursor/rules/pr-resolution-and-deploy.mdc` | `$TAG` unquoted over SSH — injection before validation |

### Pattern C: Shell/SQL injection (2 PRs)

Same root cause as Pattern B but specifically in provisioning/deploy scripts.

## Finding 4: Distillation quality depends on model, not pipeline

| Run | Model | Result |
|-----|-------|--------|
| Apr 5 (v1) | `gpt-4o-mini` | Noise detection correct (4/9 noise). Signal "lessons" worthless: "Consider addressing potential security issues" — fortune cookie advice. |
| Apr 9 (v1) | `claude-sonnet-4.5` | Noise detection sharper (4 noise @ 0.95+ confidence). Signal lessons better but still generic: "Actionable technical feedback including error handling gaps." |

The v1 prompt asks "signal vs noise." That's the wrong question. V2 prompt (PR #81) asks: "What is the conceptual mistake? What rule prevents it? Which PRs are canonical examples?" — structured output the issue writer can consume.

## Finding 5: The arXiv correlated-error problem is recursive here

arXiv 2603.25773 showed that when AI generates code AND AI reviews it, errors correlate — the reviewer misses what the generator missed. In this fleet:

1. Agent (Cursor Auto) implements from issue spec
2. Agent army (CodeRabbit, Copilot, Bugbot, Sourcery, Gemini, Codex) reviews
3. Agent (Claude Code / Cursor) fixes review findings
4. Loop repeats 8-20 times per PR

The miner then mines the review loop output to "learn." But since every layer is agent-generated, the mined "patterns" are agents-distilling-agents-distilling-agents. The only human signal in the entire pipeline is:

- **Issue bodies** the user writes (intent, constraints)
- **Chat messages** directing agent work (corrections, priorities)
- **Merge decisions** (accept vs iterate vs kill)
- **Vault nodes** the user promotes from `.scratch/`

## Conclusions

1. **Mining PR comments is necessary but insufficient.** It finds recurring mistakes (Pattern A/B/C) but cannot extract engineering wisdom because there are no human engineers in the loop.
2. **The shift-left fix is the only viable path.** Better issues (with mined pitfall guidance) → fewer recurring mistakes → fewer iteration cycles. Mining feeds the issue writer, not a standalone learning system.
3. **Semantic clustering (sentence-transformers) is required** to find conceptual patterns. TF-IDF is structurally incapable because the patterns share meaning, not vocabulary.
4. **Frontier model distillation produces actionable output** only when asked the right question (v2: conceptual mistake + preventive rule + citations) with a capable model (Sonnet 4.5+, not gpt-4o-mini).
5. **Local model training (#26) is premature.** Training on this corpus would teach a model to emit bot chrome. Wait until the shift-left loop produces cleaner data.

## Ship log

- **2026-04-10:** [PR #81](https://github.com/agorokh/template-repo/pull/81) merged to `main` (squash merge `9f88af95aa3a0de1f7de6dfb13f157d9bb46db90`). Template now ships semantic clustering, distill v2, and pre-cluster chrome filtering described in this note.
