#!/usr/bin/env python3
"""Fail if canonical agent policy docs are missing."""

from __future__ import annotations

from pathlib import Path

REQUIRED = (
    "AGENTS.md",
    "AGENT_CORE_PRINCIPLES.md",
    "CLAUDE.md",
    ".cursorrules",
    "docs/00_Core/SESSION_LIFECYCLE.md",
    "docs/01_Vault/00_Graph_Schema.md",
)


def main(root: Path | None = None) -> int:
    repo_root = root or Path(__file__).resolve().parents[1]
    missing = [path for path in REQUIRED if not (repo_root / path).is_file()]
    for path in missing:
        print(f"Policy check failed: {path} not found")
    if missing:
        return 1
    print("Policy docs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
