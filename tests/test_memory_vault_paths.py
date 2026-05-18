"""Tests for ``scripts/memory_vault_paths.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "memory_vault_paths.py"


def _load():
    spec = importlib.util.spec_from_file_location("memory_vault_paths", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_discover_vault_key_in_repo() -> None:
    mod = _load()
    assert mod.discover_vault_key(REPO_ROOT) == "AcCopilotTrainer"


def test_vault_relpath_uses_discovered_key(tmp_path: Path) -> None:
    mod = _load()
    vault = tmp_path / "docs" / "01_Vault" / "MyProject" / "00_System" / "invariants"
    vault.mkdir(parents=True)
    (vault / "memory-three-tiers.md").write_text("---\n", encoding="utf-8")
    rel = mod.vault_relpath(tmp_path, "00_System", "Next Session Handoff.md")
    assert rel == "docs/01_Vault/MyProject/00_System/Next Session Handoff.md"
