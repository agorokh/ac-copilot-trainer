#!/usr/bin/env python3
"""Classify changed paths from a merged PR for post-merge follow-ups."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def classify_changed_paths(paths: list[str]) -> list[str]:
    norm = [p.strip().replace("\\", "/") for p in paths if p.strip()]
    if not norm:
        return []
    messages: list[str] = []
    seen: set[str] = set()

    def add(key: str, text: str) -> None:
        if key not in seen:
            seen.add(key)
            messages.append(text)

    if any("/migrations/" in p or p.startswith(("migrations/", "db/migrations/")) for p in norm):
        add("migration", "Migration paths touched: run your project's migrate command.")
    if any(p == ".env.example" or p.endswith("/.env.example") for p in norm):
        add("env", "`.env.example` changed: review for new required environment variables.")
    if any(p == "pyproject.toml" or p.endswith("/pyproject.toml") for p in norm):
        add("deps", "`pyproject.toml` changed: refresh local dependencies if needed.")
    if any(p.startswith("scripts/") for p in norm):
        add("scripts", "`scripts/` changed: review new or updated setup/utility scripts.")
    if any(p.startswith(".github/workflows/") for p in norm):
        add(
            "workflows",
            "`.github/workflows/` changed: review triggers, permissions, and secrets usage.",
        )
    if any(Path(p).name == "Makefile" for p in norm):
        add("makefile", "`Makefile` changed: check for new targets and document if needed.")
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--github-comment", action="store_true")
    args = parser.parse_args()

    if shutil.which("gh") is None:
        print("error: gh CLI not found", file=sys.stderr)
        sys.exit(1)

    r = subprocess.run(
        ["gh", "pr", "diff", str(args.pr), "--name-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        print(r.stderr.strip() or "gh pr diff failed", file=sys.stderr)
        sys.exit(r.returncode or 1)

    lines = classify_changed_paths(r.stdout.splitlines())
    if not lines:
        print("No post-merge classification flags for these paths.")
        return

    body = "## Post-merge follow-ups\n\n" + "\n".join(f"- {line}" for line in lines)
    print("\n".join(lines))
    if args.github_comment:
        subprocess.run(
            ["gh", "pr", "comment", str(args.pr), "--body-file", "-"],
            input=body,
            text=True,
            check=True,
        )


if __name__ == "__main__":
    main()
