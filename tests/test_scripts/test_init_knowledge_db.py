"""Tests for ``scripts/init_knowledge_db.py``."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType


def _load_init_knowledge_db() -> ModuleType:
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "init_knowledge_db.py"
    spec = importlib.util.spec_from_file_location("init_knowledge_db", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_main_creates_db_with_expected_tables(tmp_path: Path) -> None:
    mod = _load_init_knowledge_db()
    assert mod.main(root=tmp_path) == 0
    assert mod.main(root=tmp_path) == 0
    db_path = tmp_path / ".cache" / "repo_knowledge" / "knowledge.db"
    assert db_path.is_file()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r[0] for r in rows}
        expected = {
            "ci_failures",
            "decisions",
            "file_patterns",
            "files",
            "ingest_meta",
            "pattern_evidence",
            "patterns",
        }
        assert expected <= names
    finally:
        conn.close()
