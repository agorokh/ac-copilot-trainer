---
type: pitfall
status: active
created: 2026-04-10
updated: 2026-04-10
severity: bug
scope_paths:
  - "agent/**"
  - "core/**"
  - "db/**"
  - "scripts/**"
  - "**/pipeline/**"
domains: [trading, legal, gaming]
canonical_prs:
  - repo: agorokh/alpaca_trading
    prs: [838]
    note: NaN notional bypasses all qty guards, producing invalid orders
  - repo: agorokh/ac-copilot-trainer
    prs: [45, 42]
    note: Shell injection via unsanitized path in ensureDir passes to os.execute
  - repo: agorokh/court-fillings-processing
    prs: [15]
    note: Missing backup pruning on all-copies-failed path
relates_to:
  - AcCopilotTrainer/pitfalls/injection-risks.md
  - AcCopilotTrainer/pitfalls/_index.md
---

# Missing input validation

**9 clusters, 77 comments, 3 repos** (alpaca_trading, ac-copilot-trainer, court-fillings-processing)

## Pattern

Functions accept external input (DB values, config, user params) without validating type, range, or emptiness. The implementing agent assumes inputs are well-formed because the happy path works in tests, but edge cases cause silent corruption downstream.

Most common forms:
- Numeric values from DB/config not checked for NaN, Inf, or negative
- String inputs used in file paths or shell commands without sanitization
- Boolean/enum configs not validated against allowed values
- Missing null/empty checks before dereferencing

## Preventive rule

1. **All numeric inputs from DB or config** MUST be validated for NaN/Inf/negative before arithmetic. Use `math.isfinite(x)` as a guard.
2. **All string inputs used in file paths** MUST be sanitized against path traversal (`..`, null bytes).
3. **Shell execution:** In Python, use `subprocess.run([...])` with list args—never f-string interpolation into a shell. In Lua or other runtimes, do not build shell strings from external input; validate against an allow-list or use APIs that take argv lists (e.g. `luaposix`).
4. **Config values with finite domains** (enums, booleans) MUST be validated at load time, not at use time.

## Canonical damage

In `alpaca_trading` PR #838, a NaN `bot_notional_per_trade` value from the DB bypassed all quantity guards (comparison with NaN is always False), producing an order with invalid quantity that reached the broker API.

<!-- Vault: frontmatter type pitfall matches docs/01_Vault/00_Graph_Schema.md -->
