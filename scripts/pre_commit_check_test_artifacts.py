#!/usr/bin/env python3
"""Pre-commit: block obvious test-only markers and data fixtures under production trees.

Scans **staged** paths passed by pre-commit. Checks:

- ``.json`` / ``.csv`` under ``src/`` (belong in ``tests/fixtures/`` or outside ``src/``).
- Substrings ``TEST-``, ``test_fixture_``, ``MOCK_`` in ``src/**/*.py`` and ``tools/**/*.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARKERS = ("TEST-", "test_fixture_", "MOCK_")
DATA_SUFFIXES = {".json", ".csv"}


def _rel_under_repo(path: Path, repo_root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None


def check_file(path: Path, repo_root: Path) -> list[str]:
    rel = _rel_under_repo(path, repo_root)
    if rel is None:
        return []
    key = rel.as_posix()
    errors: list[str] = []

    if key.startswith("src/") and path.suffix.lower() in DATA_SUFFIXES:
        errors.append(f"{key}: move data fixtures out of src/ (e.g. tests/fixtures/)")
        return errors

    if not key.endswith(".py"):
        return errors
    if not (key.startswith("src/") or key.startswith("tools/")):
        return errors

    text = path.read_text(encoding="utf-8", errors="replace")
    for marker in MARKERS:
        if marker in text:
            errors.append(f"{key}: disallowed test marker {marker!r} in production path")
            break
    return errors


def main() -> int:
    repo_root = Path.cwd()
    problems: list[str] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if not p.is_file():
            continue
        problems.extend(check_file(p, repo_root))
    if problems:
        print("pre_commit_check_test_artifacts failed:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
