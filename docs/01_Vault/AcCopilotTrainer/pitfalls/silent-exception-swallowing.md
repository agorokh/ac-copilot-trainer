---
type: pitfall
status: active
created: 2026-04-10
updated: 2026-04-10
severity: bug
scope_paths:
  - "**/*.py"
  - "agent/**"
  - "db/**"
  - "core/**"
  - "**/pipeline/**"
domains: [trading, legal, infra, gaming]
canonical_prs:
  - repo: agorokh/alpaca_trading
    prs: [751, 737]
    note: Kill-switch bypass caused by bare except ValueError hiding DB connection errors
  - repo: agorokh/court-fillings-processing
    prs: [27, 25]
    note: Filing registry enrichment failures silently skipped
  - repo: agorokh/template-repo
    prs: [81]
    note: OpenAI API key silently sent to OpenRouter due to broad error catch
relates_to:
  - AcCopilotTrainer/00_System/invariants/no-secrets.md
  - AcCopilotTrainer/pitfalls/_index.md
---

# Silent exception swallowing

**8 clusters, 109 comments, 3 repos** (court-fillings-processing, alpaca_trading, template-repo).

<!-- GitHub repo slug uses double “l” (court-fillings-processing); see fleet/_index.md -->

## Pattern

Bare `except Exception` or overly-broad catch blocks that hide real failures. The implementing agent adds error handling but catches too broadly, turning hard failures into silent data corruption or feature bypass.

Most common forms:
- `except Exception: pass` or `except Exception: return default`
- `except ValueError` catching unrelated errors from nested calls
- Downgrading all exceptions to `logger.debug()` during "cleanup" refactors

## Preventive rule

Any `except` clause in this area MUST:
1. **Narrow** to the specific exception type expected (e.g., `except KeyError`, not `except Exception`)
2. **Log** with `logger.exception()` (not `logger.debug()`) so the stack trace is preserved
3. **Re-raise or return an explicit error sentinel** -- never silently continue with default data

If the code is in a streaming/async path, the exception MUST propagate to the caller. Silent swallowing in event loops can bypass safety mechanisms (kill switches, circuit breakers).

## Canonical damage

In `alpaca_trading` PR #751, a bare `except ValueError` in the streaming node hid a DB connection error, which prevented the kill switch from activating during a live trading session. The fix was narrowing to `except decimal.InvalidOperation` and re-raising all others.
