#!/usr/bin/env python3
"""Classify changed paths from a merged PR for post-merge follow-ups."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def classify_changed_paths(paths: list[str]) -> list[str]:
    norm = [p.strip().replace("\\", "/").removeprefix("./") for p in paths if p.strip()]
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
    dependency_files = (
        "pyproject.toml",
        "poetry.lock",
        "pdm.lock",
        "requirements.txt",
        "environment.yml",
        "uv.lock",
        "Pipfile",
        "Pipfile.lock",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "Cargo.toml",
        "Cargo.lock",
        "go.mod",
        "go.sum",
        "platformio.ini",
    )
    dependency_suffixes = tuple(f"/{name}" for name in dependency_files)
    if any(p in dependency_files or p.endswith(dependency_suffixes) for p in norm):
        add("deps", "Dependency files changed: refresh local dependencies if needed.")
    if any(Path(p).parts and Path(p).parts[0] == "scripts" for p in norm):
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

    repo = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],  # noqa: S603,S607
        capture_output=True,
        text=True,
        check=False,
    )
    if repo.returncode != 0:
        print(repo.stderr.strip() or "gh repo view failed", file=sys.stderr)
        sys.exit(repo.returncode or 1)
    owner_repo = repo.stdout.strip()
    if not owner_repo or "/" not in owner_repo:
        print("could not determine owner/repo from gh repo view", file=sys.stderr)
        sys.exit(1)

    files_json = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", f"repos/{owner_repo}/pulls/{args.pr}/files"],  # noqa: S603,S607
        capture_output=True,
        text=True,
        check=False,
    )
    if files_json.returncode != 0:
        print(files_json.stderr.strip() or "gh api pulls/files failed", file=sys.stderr)
        sys.exit(files_json.returncode or 1)
    try:
        files = json.loads(files_json.stdout)
    except json.JSONDecodeError as exc:
        print(f"failed to parse changed file list JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    file_items: list[dict[str, object]] = []
    if isinstance(files, list):
        for page in files:
            if isinstance(page, list):
                file_items.extend(item for item in page if isinstance(item, dict))
    paths = [str(item.get("filename", "")) for item in file_items]

    lines = classify_changed_paths(paths)
    if not lines:
        print("No post-merge classification flags for these paths.")
        return

    body = "## Post-merge follow-ups\n\n" + "\n".join(f"- {line}" for line in lines)
    print("\n".join(lines))
    if args.github_comment:
        try:
            subprocess.run(
                ["gh", "pr", "comment", str(args.pr), "--body-file", "-"],
                input=body,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            print(
                f"warning: failed to post GitHub PR comment via `gh pr comment` "
                f"(exit code {exc.returncode}); continuing",
                file=sys.stderr,
            )


if __name__ == "__main__":
    main()
