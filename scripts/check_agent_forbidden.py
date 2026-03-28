#!/usr/bin/env python3
"""
Agent-proofing: fail CI if tracked files violate repository layout rules.

Customize ALLOWED_TOPLEVEL_DIRS to match docs/10_Development/11_Repository_Structure.md
for your specialized project.

Root-level *files* outside ROOT_FILE_ALLOWLIST emit warnings only (stderr); CI still passes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ALLOWED_TOPLEVEL_DIRS = {
    ".cursor",
    ".github",
    "docs",
    "scripts",
    "src",
    "tests",
    ".claude",
    # Common additions when you specialize (uncomment as needed):
    # "apps",
    # "ops",
    # "archive",
}

# Tracked files at repository root (single path segment). Warnings only if not listed.
ROOT_FILE_ALLOWLIST = frozenset(
    {
        # Config / build
        "pyproject.toml",
        "Makefile",
        ".gitignore",
        ".pre-commit-config.yaml",
        # Governance / docs at root
        "AGENTS.md",
        "CLAUDE.md",
        "CODEX.md",
        "WARP.md",
        "AGENT_CORE_PRINCIPLES.md",
        ".cursorrules",
        "README.md",
        "LICENSE",
        # Editor / local toolchain (optional files)
        ".editorconfig",
        ".python-version",
        # Common template / integration root files
        ".mcp.json",
        ".env.example",
        ".markdownlint.json",
    }
)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    errors: list[str] = []
    root_warnings: list[str] = []

    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fresh clone without git metadata in some sandboxes — skip softly
        return 0

    tracked = out.stdout.strip().splitlines() if out.stdout else []
    seen: set[str] = set()
    for path in tracked:
        path = path.strip('"')
        parts = path.split("/")
        if len(parts) == 1 and parts[0]:
            name = parts[0]
            if name not in ROOT_FILE_ALLOWLIST:
                root_warnings.append(
                    f"Unexpected root-level file (allowlist warning only): {name}. "
                    "If intentional, add it to ROOT_FILE_ALLOWLIST in "
                    "scripts/check_agent_forbidden.py and document it in "
                    "docs/10_Development/11_Repository_Structure.md."
                )
            continue
        if len(parts) >= 2:
            top = parts[0]
            if top not in ALLOWED_TOPLEVEL_DIRS:
                seen.add(top)

    for d in sorted(seen):
        errors.append(
            f"Forbidden top-level path segment (not in allowlist): {d}. "
            "Update ALLOWED_TOPLEVEL_DIRS in scripts/check_agent_forbidden.py "
            "and docs/10_Development/11_Repository_Structure.md together."
        )

    for w in sorted(set(root_warnings)):
        print(w, file=sys.stderr)

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
