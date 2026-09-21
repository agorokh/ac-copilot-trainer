# OWNER: @agorokh
"""Shared repo-root resolution and host identity for Claude Code memory hooks.

Git worktrees expose `.git` as a file and use a random slug as the worktree
directory name. Hooks that stamp or read ``.scratch/.last_memory_query`` must
normalize to the **main** checkout via ``git rev-parse --git-common-dir`` so
manifest ``match_repo_basenames`` and lockfile paths stay consistent.
"""

from __future__ import annotations

import os
import re
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
            encoding="utf-8",
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


def boot_identity() -> str | None:
    """This machine's EXACT boot identifier, or None when it cannot be determined.

    Shared by the prefetch (which STAMPS it into the lock/marker) and the gate (which
    COMPARES the stamps). Both sides must agree byte-for-byte or the comparison silently
    stops matching, so the extraction is deliberate: two copies of this drifted apart the
    moment either gained a platform (advisory MEDIUM, PR #544).

    Returning None is safe -- the consumer treats an absent identity as "not comparable"
    and falls through to wall clock, then mtime, then CLOSED.
    """
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
        if boot_id:
            return f"linux:{boot_id}"
    except OSError:
        pass
    try:
        proc = subprocess.run(
            ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True,
            encoding="utf-8", timeout=5, check=False,
        )
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and out:
            return _darwin_boot_identity(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


#: ``kern.boottime`` renders as ``{ sec = 1788715075, usec = 877413 } Sun Sep  6 10:17:55 2026``.
#: Only the struct fields are stable; the trailing ctime is formatted in the CALLER's
#: timezone and locale.
_DARWIN_BOOTTIME_RE = re.compile(r"sec\s*=\s*(\d+).*?usec\s*=\s*(\d+)", re.DOTALL)
_DARWIN_NORMALIZED_RE = re.compile(r"darwin:(\d+)\.(\d+)\Z")


def _darwin_boot_identity(raw: str) -> str:
    """Boot identity from ``kern.boottime`` output, keyed on the stable fields only.

    The whole stdout is NOT usable as the key. ``sec``/``usec`` are invariant for a
    given boot, but the ctime suffix is rendered in the caller's timezone, so the same
    boot yields different strings to processes with different ``TZ``::

        $ TZ=UTC        sysctl -n kern.boottime
        { sec = 1788715075, usec = 877413 } Sun Sep  6 17:17:55 2026
        $ TZ=Asia/Tokyo sysctl -n kern.boottime
        { sec = 1788715075, usec = 877413 } Mon Sep  7 02:17:55 2026

    A launchd-run producer and an interactive-shell consumer need not share ``TZ``, so
    embedding the suffix made one boot compare as two -- and this function's contract is
    that both sides "agree byte-for-byte or the comparison silently stops matching".
    The consumer then falls off the boot-identity path to wall clock, then mtime.

    Falls back to the raw string when the fields cannot be parsed: an unrecognised
    format is better keyed imperfectly than treated as "no identity at all".
    """
    match = _DARWIN_BOOTTIME_RE.search(raw)
    if match:
        return f"darwin:{match.group(1)}.{match.group(2)}"
    return f"darwin:{raw}"


def normalized_boot_identity(identity: str) -> str:
    """Canonicalize current and legacy Darwin boot ids for persisted-record reads."""
    value = identity.strip()
    normalized = _DARWIN_NORMALIZED_RE.fullmatch(value)
    if normalized:
        return f"darwin:{normalized.group(1)}.{normalized.group(2)}"
    if value.startswith("darwin:"):
        legacy = _DARWIN_BOOTTIME_RE.search(value.removeprefix("darwin:"))
        if legacy:
            return f"darwin:{legacy.group(1)}.{legacy.group(2)}"
    return value


def boot_identities_match(first: str, second: str) -> bool:
    """Compare boot ids while dual-reading pre-#646 Darwin persisted records."""
    return normalized_boot_identity(first) == normalized_boot_identity(second)
