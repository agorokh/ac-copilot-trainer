#!/usr/bin/env python3
"""Secret scan every tracked path with a Windows-safe Python entrypoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BATCH_SIZE = 100


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


def _batches(items: list[str], size: int = BATCH_SIZE) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


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
