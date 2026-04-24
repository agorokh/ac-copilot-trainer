---
type: pitfall
status: active
created: 2026-04-10
updated: 2026-04-10
severity: maintainability
scope_paths:
  - "**/*.py"
  - "**/*.lua"
  - "**/pipeline/**"
  - "**/vault/**"
domains: [legal, trading, infra]
canonical_prs:
  - repo: agorokh/court-fillings-processing
    prs: [22, 18]
    note: Duplicated wikilink-building logic across two modules drifts out of sync
  - repo: agorokh/alpaca_trading
    prs: [759]
    note: Non-atomic append-then-read after module split introduces race condition
relates_to:
  - AcCopilotTrainer/pitfalls/_index.md
---

# Redundant code drift

**4 clusters, 36 comments, 3 repos**

## Pattern

Logic is duplicated across modules (often from copy-paste during refactors), then the copies drift out of sync as each is modified independently. Also: splitting a module into two files can break atomicity guarantees that the original monolith provided.

Most common forms:
- Two modules build wikilinks with slightly different normalization rules
- Validation logic copy-pasted into three handlers instead of shared
- Module split breaks "read-after-write" atomicity when the lock scope changes
- Duplicate ID handling with inconsistent dedup strategies

## Preventive rule

1. **Before creating a new helper**, grep for existing implementations of the same logic. If found, refactor to share rather than duplicate.
2. **When splitting a module**, verify all state access remains atomic. If the original had a lock around read+write, the split must preserve that scope.
3. **After refactoring**, search for string literals and function names from the old code to find remaining callers that need updating.

## Canonical damage

In `alpaca_trading` PR #759, the price history cache was split from `update_state.py` into its own module. The split changed the lock scope: bar append and price history read became two separate lock acquisitions instead of one, introducing a race condition where reads could see partially-updated data.
