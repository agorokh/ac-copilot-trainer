#!/usr/bin/env python3
"""Scan every tracked file with detect-secrets' pre-commit hook."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

_MAX_COMMAND_CHARS = 24_000


def _tracked_paths(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )
    return [
        raw.decode("utf-8", errors="surrogateescape") for raw in proc.stdout.split(b"\0") if raw
    ]


def _chunks(paths: Iterable[str]) -> Iterator[list[str]]:
    batch: list[str] = []
    size = 0
    for path in paths:
        added = len(path) + 1
        if batch and size + added > _MAX_COMMAND_CHARS:
            yield batch
            batch = []
            size = 0
        batch.append(path)
        size += added
    if batch:
        yield batch


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    paths = _tracked_paths(repo_root)
    if not paths:
        return 0
    base_cmd = [
        sys.executable,
        "-m",
        "detect_secrets.pre_commit_hook",
        "--baseline",
        ".secrets.baseline",
    ]
    for batch in _chunks(paths):
        proc = subprocess.run([*base_cmd, *batch], cwd=repo_root)
        if proc.returncode != 0:
            return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
