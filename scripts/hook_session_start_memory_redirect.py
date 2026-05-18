#!/usr/bin/env python3
"""SessionStart command hook — auto-memory directory deprecation marker.

Backs the ``memory-three-tiers`` invariant under ``docs/01_Vault/<ProjectKey>/``.

On every SessionStart, this script writes a deprecation README inside Claude
Code's per-user auto-memory directory for this project so an agent that
**tries** to write there sees an explicit "this is the wrong place" notice
before silently succeeding.

The script is **non-destructive**: it does not delete existing auto-memory
files (those may contain history that should be reviewed manually before
removal). It only writes / refreshes a ``README.md`` and a
``DEPRECATED.txt`` sentinel.

Path resolution:
  * Claude Code's per-user auto-memory directory follows the pattern
    ``~/.claude/projects/<slugified-project-path>/memory/``. The slug is
    derived from the project's absolute path by replacing ``/`` with ``-``.
  * If the directory does not exist, the script creates it (so the warning
    is present *before* an agent tries to write there for the first time).

Fail-open contract: any error → exit 0 (this hook is advisory, not load-
bearing). Set ``CLAUDE_MEMORY_REDIRECT=0`` to skip entirely.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from memory_vault_paths import vault_relpath

MARKER_README = (
    "# DEPRECATED — Auto-memory is not used in this project\n"
    "\n"
    "This directory (`~/.claude/projects/.../memory/`) is **deprecated** for\n"
    "this project. Anything written here is invisible to:\n"
    "\n"
    "- Other agents in the same session (Task-spawned subagents inherit no per-user state).\n"
    "- Other sessions on the same machine.\n"
    "- Teammates and other machines.\n"
    "- The Tier-3 ingest pipelines (LightRAG, Graphiti) that consume vault content.\n"
    "\n"
    "## Where to write instead\n"
    "\n"
    "1. **Vault** — `docs/01_Vault/<ProjectKey>/` (Obsidian markdown graph).\n"
    "   See `docs/01_Vault/00_Graph_Schema.md` for node types and frontmatter.\n"
    "2. **Tier-3 substrate** — declared in `ops/memory_manifest.yml`; written\n"
    "   indirectly by promoting stable findings into the vault, which is then\n"
    "   re-ingested by the substrate.\n"
    "\n"
    "## Canonical contract\n"
    "\n"
    "- Invariant: `{invariant_path}`\n"
    "- Contract:  `docs/00_Core/MEMORY_CONTRACT.md`\n"
    "- Postmortem driving this rule: https://github.com/agorokh/template-repo/issues/115\n"
    "\n"
    "If you (an agent) are reading this README in your context, it means a hook\n"
    "tried to redirect a write that would have ended up here. Migrate the\n"
    "content to the vault and file an `architectural-invariant-gap` issue against\n"
    "`template-repo` so the structural fix lands upstream.\n"
)

MARKER_SENTINEL = "deprecated\n"


def _enabled() -> bool:
    val = os.environ.get("CLAUDE_MEMORY_REDIRECT")
    if val is None:
        return True
    return val.strip().lower() in ("1", "true", "yes", "on")


def _project_root() -> Path:
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


def _slugify(path: Path) -> str:
    """Match Claude Code's auto-memory directory naming convention."""
    # Normalize to POSIX separators before slugging (Windows uses ``\``).
    abs_str = path.resolve().as_posix()
    return abs_str.replace("/", "-")


def _auto_memory_dir(project_root: Path) -> Path:
    slug = _slugify(project_root)
    return Path.home() / ".claude" / "projects" / slug / "memory"


def _marker_readme(project_root: Path) -> str:
    invariant_path = vault_relpath(project_root, "00_System", "invariants", "memory-three-tiers.md")
    return MARKER_README.format(invariant_path=invariant_path)


def main() -> int:
    if not _enabled():
        return 0
    project_root = _project_root()
    target = _auto_memory_dir(project_root)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        # No permission to create — degrade silently.
        return 0
    try:
        readme = target / "README.md"
        # Always refresh content so a template update lands without manual ops.
        readme.write_text(_marker_readme(project_root), encoding="utf-8")
        sentinel = target / "DEPRECATED.txt"
        sentinel.write_text(MARKER_SENTINEL, encoding="utf-8")
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — fail-open
        sys.exit(0)
