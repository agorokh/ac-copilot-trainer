"""Vault path helpers for memory-enforcement hooks (child-repo aware).

Children rename ``docs/01_Vault/ProjectTemplate`` to a project key on bootstrap.
Hooks discover the active vault folder by locating the memory-three-tiers invariant
rather than hardcoding template placeholders.
"""

from __future__ import annotations

from pathlib import Path

MEMORY_THREE_TIERS_INVARIANT = "memory-three-tiers.md"


def discover_vault_key(root: Path) -> str | None:
    """Return the ``docs/01_Vault/<key>`` folder name for this repo, if any."""
    vault_dir = root / "docs" / "01_Vault"
    if not vault_dir.is_dir():
        return None
    for child in sorted(vault_dir.iterdir()):
        if not child.is_dir():
            continue
        inv = child / "00_System" / "invariants" / MEMORY_THREE_TIERS_INVARIANT
        if inv.is_file():
            return child.name
    return None


def vault_relpath(root: Path, *parts: str) -> str:
    """POSIX path under ``docs/01_Vault/<key>/`` (placeholder when unknown)."""
    key = discover_vault_key(root) or "<ProjectKey>"
    suffix = "/".join(parts)
    return f"docs/01_Vault/{key}/{suffix}" if suffix else f"docs/01_Vault/{key}"
