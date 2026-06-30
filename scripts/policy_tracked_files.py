#!/usr/bin/env python3
"""Secret scan every tracked path with a Windows-safe Python entrypoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

POSIX_BATCH_SIZE = 100
POSIX_MAX_ARG_CHARS = 24_000
WINDOWS_BATCH_SIZE = 25
WINDOWS_MAX_ARG_CHARS = 4_000


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=True,
        text=True,
    )
    return Path(result.stdout.strip())


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    raw = result.stdout.split(b"\0")
    return [
        path for chunk in raw if (path := chunk.decode("utf-8")) and path != ".secrets.baseline"
    ]


def _batches(
    items: list[str],
    size: int | None = None,
    max_chars: int | None = None,
) -> list[list[str]]:
    if size is None:
        size = WINDOWS_BATCH_SIZE if sys.platform == "win32" else POSIX_BATCH_SIZE
    if max_chars is None:
        max_chars = WINDOWS_MAX_ARG_CHARS if sys.platform == "win32" else POSIX_MAX_ARG_CHARS
    batches: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for item in items:
        item_chars = len(item) + 1
        if current and (len(current) >= size or current_chars + item_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        batches.append(current)
    return batches


def main() -> int:
    root = _repo_root()
    files = _tracked_files(root)
    baseline = root / ".secrets.baseline"
    if not files:
        return 0
    for batch in _batches(files):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "detect_secrets.pre_commit_hook",
                "--baseline",
                str(baseline),
                *batch,
            ],
            cwd=root,
        )
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
