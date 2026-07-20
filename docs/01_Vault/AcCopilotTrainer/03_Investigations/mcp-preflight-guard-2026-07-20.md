---
type: investigation
status: complete
created: 2026-07-20
updated: 2026-07-20
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/02_Investigations/_index.md
  - AcCopilotTrainer/03_Investigations/tier3-consumer-repoint-drift-2026-07-15.md
---

# MCP preflight guard — repo-knowledge silent-fail root cause + fleet pattern

## Summary

Kimi (and every other agent host) launched sessions here with only
`mcp__agentic-memory__*` tools — `repo-knowledge` was silently absent. Root
cause: the local `.venv` was created without the `.[knowledge]` extra, so
`scripts/mcp/repo-knowledge.sh` correctly failed closed (`cannot import 'mcp'`)
and the host surfaced it only as a missing tool surface. The identical failure
had just been repaired by hand in the workstation-ops checkout — an
environment-level fix with no committed guard, so it recurred here on the next
repo. This note records the durable fix.

## Root cause chain

1. `.mcp.json` declares `repo-knowledge` via `scripts/mcp/repo-knowledge.sh`.
2. The wrapper prefers `.venv/bin/python` and requires `import mcp`
   (pyproject `knowledge` extra: `mcp>=1.27.0`).
3. Local `.venv` had only the base editable install — README documents
   `pip install -e ".[dev]"`, CI installs `.[dev,mining,knowledge,analytics]`,
   so the gap exists **only on local dev venvs** and is invisible to CI.
4. Agent hosts mark the server failed at launch; the session proceeds with a
   silently reduced tool surface.

## Fix (this repo)

1. `.venv/bin/python -m pip install -e '.[knowledge]'` — immediate repair;
   `tools/list` handshake smoke-verified against the wrapper.
2. `scripts/check_mcp_preflight.py` (new) — parses `.mcp.json`, and when the
   repo-knowledge wrapper is declared, resolves the interpreter with the
   wrapper's own precedence (`REPO_KNOWLEDGE_PYTHON` → `.venv/Scripts/python.exe`
   → `.venv/bin/python` → system `python3`/`python`) and fails
   `make ci-policy` (thus `ci-fast`) with the exact remediation when
   `import mcp` fails. Negative path verified against a real interpreter
   without `mcp` (`REPO_KNOWLEDGE_PYTHON=/usr/bin/python3` → exit 1,
   actionable stderr).
3. `tests/test_check_mcp_preflight.py` — 7 tests, monkeypatched in the
   `test_check_agent_forbidden.py` style.

## Fleet pattern (why this recurs)

Any template child repo can hit this: the wrapper fix propagated (PR #611
here), but the **environment precondition** it depends on was never guarded.
The workstation-ops repair was uncommitted venv state — invisible to the next
repo. `check_mcp_preflight.py` is domain-agnostic (reads only `.mcp.json` +
the wrapper contract) and is a candidate for upstream propagation to
template-repo / the governance hub so every child repo inherits the guard
instead of rediscovering the failure per-host.

## Verification

- `pytest tests/test_check_mcp_preflight.py` — 7 passed.
- `make ci-policy` green; `ruff format --check` / `ruff check` clean on both
  new files.
- Live handshake: `initialize` + `tools/list` against
  `bash scripts/mcp/repo-knowledge.sh` returns the repo-knowledge tool set.
