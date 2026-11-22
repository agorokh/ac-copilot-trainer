---
type: entity
status: active
created: 2026-03-27
updated: 2026-03-28
relates_to:
  - AcCopilotTrainer/00_System/Workflow OS.md
part_of: AcCopilotTrainer/00_System/glossary/_index.md
---

# ci-fast

**Definition:** The aggregate local check invoked as **`make ci-fast`**: format (`ci-format`), lint (`ci-lint`), tests with coverage floor (`ci-test`, `pytest-cov` on `src` with `--cov-fail-under=80`), security static analysis (`ci-security`, `bandit` on `src`), policy docs (`ci-policy`), and agent root-file allowlist checks (`ci-agent-proof`, stderr warnings via `scripts/check_agent_forbidden.py`). Aim for parity with required GitHub Actions where practical.

**See also:** [Workflow OS.md](../Workflow%20OS.md).
