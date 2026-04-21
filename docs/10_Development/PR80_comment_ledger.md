# PR #80 — zero-sampling comment ledger

Full inventory via `gh api repos/agorokh/ac-copilot-trainer/pulls/80/comments` (paginated) and the same for `issues/80/comments` and `pulls/80/reviews`. Every inline thread ID is listed below as **RESOLVED** where the branch already addresses the feedback or the thread is bot/meta-only.

## Checks (required + bots)

| Check | Outcome |
|-------|---------|
| build | pass |
| Canonical docs exist | pass |
| Sourcery review | pass |
| CodeRabbit | pass |
| guard-and-automerge | skipping |

## Inline review threads (`pulls/80/comments`)

| Comment ID | Author | RESOLVED |
|-------------|--------|----------|
| 3120465737 | gemini-code-assist[bot] | yes |
| 3120465755 | gemini-code-assist[bot] | yes |
| 3120465762 | gemini-code-assist[bot] | yes |
| 3120470916 | Copilot | yes |
| 3120470933 | Copilot | yes |
| 3120477722 | chatgpt-codex-connector[bot] | yes |
| 3120477724 | chatgpt-codex-connector[bot] | yes |
| 3120489380 | gemini-code-assist[bot] | yes |
| 3120489388 | gemini-code-assist[bot] | yes |
| 3120489394 | gemini-code-assist[bot] | yes |
| 3120489524 | sourcery-ai[bot] | yes |
| 3120496168 | Copilot | yes |
| 3120496191 | Copilot | yes |
| 3120496210 | Copilot | yes |
| 3120496224 | Copilot | yes |
| 3120500159 | chatgpt-codex-connector[bot] | yes |
| 3120533715 | cursor[bot] | yes |
| 3120541508 | sourcery-ai[bot] | yes |
| 3120546730 | gemini-code-assist[bot] | yes |
| 3120546737 | gemini-code-assist[bot] | yes |
| 3120551276 | Copilot | yes |
| 3120551296 | Copilot | yes |
| 3120551301 | Copilot | yes |
| 3120551325 | Copilot | yes |
| 3120551337 | Copilot | yes |
| 3120557745 | chatgpt-codex-connector[bot] | yes |
| 3120571395 | cursor[bot] | yes |
| 3120583790 | sourcery-ai[bot] | yes |
| 3120583794 | sourcery-ai[bot] | yes |
| 3120593940 | chatgpt-codex-connector[bot] | yes |
| 3120595054 | Copilot | yes |
| 3120595070 | Copilot | yes |
| 3120595079 | Copilot | yes |
| 3120595085 | Copilot | yes |
| 3120619906 | cursor[bot] | yes |
| 3120619909 | cursor[bot] | yes |
| 3120627985 | sourcery-ai[bot] | yes |
| 3120629903 | SourceryAI | yes |
| 3120629906 | SourceryAI | yes |
| 3120639775 | chatgpt-codex-connector[bot] | yes |
| 3120639803 | Copilot | yes |
| 3120657164 | cursor[bot] | yes |
| 3120676506 | chatgpt-codex-connector[bot] | yes |
| 3120676509 | chatgpt-codex-connector[bot] | yes |
| 3120679453 | Copilot | yes |
| 3120679475 | Copilot | yes |
| 3120705956 | cursor[bot] | yes |
| 3120748665 | Copilot | yes |
| 3120748687 | Copilot | yes |
| 3120748698 | Copilot | yes |
| 3120749468 | coderabbitai[bot] | yes |
| 3120749476 | coderabbitai[bot] | yes |
| 3120749478 | coderabbitai[bot] | yes |
| 3120749483 | coderabbitai[bot] | yes |
| 3120749489 | coderabbitai[bot] | yes |
| 3120749492 | coderabbitai[bot] | yes |
| 3120749501 | coderabbitai[bot] | yes |

## Issue comments (`issues/80/comments`): 38

PR conversation; bot guides and usage-limit notices are typically **N/A**. Re-open any `agorokh` item that requests a concrete change and add a ledger subsection + code fix.

## PR reviews (`pulls/80/reviews`): 29

Automated summaries; actionable items should map to inline rows above.

## Local verification

Same as `Makefile`: `python -m pytest -q --cov=ac_copilot_trainer --cov=tools --cov-fail-under=80`, `python -m ruff format --check src tests tools scripts`, `python -m ruff check src tests tools scripts`.
