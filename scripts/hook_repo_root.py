# OWNER: @agorokh
"""Shared repo-root resolution for Claude Code memory hooks.

Git worktrees expose `.git` as a file and use a random slug as the worktree
directory name. Hooks that stamp or read ``.scratch/.last_memory_query`` must
normalize to the **main** checkout via ``git rev-parse --git-common-dir`` so
manifest ``match_repo_basenames`` and lockfile paths stay consistent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def session_toplevel_dir() -> Path:
    """Checkout directory for the active session (main clone or worktree).

    Canonical implementation for all memory hooks. SessionStart stamps
    ``.scratch/.last_memory_query`` here; gate/drift/Stop hooks read it from
    the same path (Stop hooks may pass ``argv[1]`` via ``memory_hook_candidates``).
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        p = Path(env_root)
        if p.is_dir():
            return p.resolve()
    here = Path.cwd().resolve()
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here


def memory_hook_candidates() -> list[Path]:
    """Session checkout path(s) before worktree normalization (Stop hooks)."""
    candidates: list[Path] = []
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg:
            candidates.append(Path(arg).expanduser().resolve())
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        candidates.append(Path(env).expanduser().resolve())
    candidates.append(Path.cwd().resolve())
    return candidates


def resolve_memory_roots() -> tuple[Path, Path]:
    """Return ``(main_repo_root, session_toplevel)`` for memory hooks."""
    session = memory_hook_candidates()[0]
    return normalize_to_main_worktree_dir(session), session


def normalize_to_main_worktree_dir(base: Path) -> Path:
    """Return the main repo working directory when *base* is a git worktree."""
    resolved = base.expanduser().resolve()
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(resolved),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=4,
        )
        if out.returncode == 0:
            common = Path(out.stdout.strip())
            if common.is_dir() and common.name == ".git":
                return common.parent.resolve()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return resolved


def worktree_root_for(path: Path) -> Path | None:
    """Nearest ancestor of *path* containing a ``.git`` entry — its OWN worktree root.

    A linked git worktree carries a ``.git`` **file** (a ``gitdir:`` pointer); the
    main repo has a ``.git`` **directory** — either satisfies ``.exists()``.
    Resolving against the file's own worktree means a file inside a **nested**
    worktree (e.g. Claude Code's ``.claude/worktrees/<name>/``) or an **external**
    worktree is classified by its position *within that worktree* (``docs/`` vs
    code), not as ``.claude/worktrees/<name>/...`` relative to the main repo —
    which matched no doc prefix and blocked every worktree edit under a marker
    (agent-factory#308 / template-repo#182).

    Use this for **per-file classifying** hooks (e.g. the stale-main gate's
    docs-vs-code check). For **session/identity** root (memory hooks) use
    ``session_toplevel_dir`` / ``normalize_to_main_worktree_dir`` instead — these
    are the "two distinct needs" reconciled in agent-factory#310.

    Returns ``None`` when no ``.git`` ancestor exists (file outside any repo); the
    caller then falls back to its own ``_REPO_ROOT`` and ultimately fails closed.
    """
    try:
        real = path.resolve()
    except OSError:
        real = path
    base = real if real.is_dir() else real.parent
    for parent in (base, *base.parents):
        if (parent / ".git").exists():
            return parent
    return None
