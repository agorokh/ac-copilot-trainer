#!/usr/bin/env python3
"""Enforce branch naming and PR title conventions (CI + local).

Reads ``GITHUB_EVENT_PATH`` / ``GITHUB_EVENT_NAME`` in GitHub Actions.
Locally, uses the current git branch when no event file is present.
Skips policy when: push to ``main``, or Dependabot head branch.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

CONVENTIONAL_TYPES: tuple[str, ...] = (
    "feat",
    "fix",
    "chore",
    "docs",
    "refactor",
    "test",
    "ci",
    "build",
    "perf",
    "style",
)

ALLOWED_BRANCH_PREFIXES: tuple[str, ...] = (
    *(f"{t}/" for t in CONVENTIONAL_TYPES),
    "dependabot/",
    "cursor/",
    "renovate/",
)

# Conventional commit style for PR titles (type, optional scope, optional !, colon, message).
_TITLE_RE = re.compile(
    rf"^({'|'.join(CONVENTIONAL_TYPES)})"
    r"(\([a-zA-Z0-9._/-]+\))?!?:\s+\S.*$"
)


def validate_branch(branch: str) -> None:
    if not branch:
        raise ValueError("Branch name must not be empty.")
    if branch == "main":
        raise ValueError(
            "Branch name must not be 'main' for this check; open a feature branch instead."
        )
    if any(branch.startswith(prefix) for prefix in ALLOWED_BRANCH_PREFIXES):
        return
    allowed = ", ".join(sorted(ALLOWED_BRANCH_PREFIXES))
    raise ValueError(f"Branch {branch!r} must start with one of: {allowed}")


def validate_pr_title(title: str) -> None:
    title = title.strip()
    if not title:
        raise ValueError("PR title must not be empty.")
    if not _TITLE_RE.match(title):
        raise ValueError(
            "PR title must follow conventional commits, e.g. "
            "'feat: add parser', 'fix(scope): handle edge case', 'chore: bump deps'."
        )


def _current_git_branch() -> str:
    git = shutil.which("git")
    if not git:
        raise OSError("git executable not found on PATH")
    out = subprocess.run(
        [git, "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def _parse_github_event_file(path: str) -> tuple[dict[str, Any] | None, int]:
    p = Path(path)
    if not p.is_file():
        print(
            f"ci_policy: GITHUB_EVENT_PATH is set but does not point to a readable file: {p}",
            file=sys.stderr,
        )
        return None, 1
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        print(f"ci_policy: cannot read GITHUB_EVENT_PATH: {e}", file=sys.stderr)
        return None, 1
    try:
        return json.loads(raw), 0
    except json.JSONDecodeError as e:
        print(f"ci_policy: invalid JSON in GITHUB_EVENT_PATH: {e}", file=sys.stderr)
        return None, 1


def _handle_github_event(path: str, event_name: str) -> int:
    event, code = _parse_github_event_file(path)
    if code != 0:
        return code
    assert event is not None

    if event_name == "push":
        ref = str(event.get("ref", ""))
        if ref == "refs/heads/main":
            return 0
        if not ref.startswith("refs/heads/"):
            print(
                f"ci_policy: skipping branch checks for non-branch push ref {ref!r}",
                file=sys.stderr,
            )
            return 0
        branch = ref.removeprefix("refs/heads/")
        try:
            validate_branch(branch)
        except ValueError as e:
            print(f"ci_policy: {e}", file=sys.stderr)
            return 1
        return 0
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        head = pr.get("head") or {}
        head_ref = str(head.get("ref", ""))
        if head_ref.startswith("dependabot/"):
            return 0
        try:
            validate_branch(head_ref)
            validate_pr_title(str(pr.get("title", "")))
        except ValueError as e:
            print(f"ci_policy: {e}", file=sys.stderr)
            return 1
        return 0

    print(
        f"ci_policy: skipping branch/title checks for GitHub event {event_name!r}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    if path:
        return _handle_github_event(path, os.environ.get("GITHUB_EVENT_NAME", ""))

    try:
        branch = _current_git_branch()
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"ci_policy: cannot read git branch: {e}", file=sys.stderr)
        return 1
    if branch == "main":
        return 0
    try:
        validate_branch(branch)
    except ValueError as e:
        print(f"ci_policy: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
