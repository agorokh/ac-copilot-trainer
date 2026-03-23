#!/usr/bin/env python3
"""
Agent-proofing: fail CI if tracked files violate repository layout rules.

Customize ALLOWED_TOPLEVEL_DIRS to match docs/10_Development/11_Repository_Structure.md
for your specialized project.
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


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    errors: list[str] = []

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

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
