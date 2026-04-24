"""Tests for ``scripts/post_merge_classify`` path classification."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_module() -> ModuleType:
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "post_merge_classify.py"
    spec = importlib.util.spec_from_file_location("_post_merge_classify", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_classify_migration_alembic_versions() -> None:
    m = _load_module()
    lines = m.classify_changed_paths(["src/alembic/versions/0001_initial.py"])
    assert len(lines) == 1
    assert "Migration" in lines[0]


def test_classify_migration_migrations_dir() -> None:
    m = _load_module()
    lines = m.classify_changed_paths(["pkg/migrations/001.sql"])
    assert any("Migration" in ln for ln in lines)


def test_classify_migration_root_migrations_dir() -> None:
    m = _load_module()
    lines = m.classify_changed_paths(["migrations/001.sql"])
    assert any("Migration" in ln for ln in lines)


def test_classify_dedupes_single_category() -> None:
    m = _load_module()
    lines = m.classify_changed_paths(
        ["a/migrations/x.sql", "b/migrations/y.sql"],
    )
    migration_lines = [ln for ln in lines if "Migration" in ln]
    assert len(migration_lines) == 1


def test_classify_env_example_pyproject_scripts_workflows_makefile() -> None:
    m = _load_module()
    paths = [
        ".env.example",
        "pyproject.toml",
        "scripts/foo.sh",
        ".github/workflows/ci.yml",
        "Makefile",
    ]
    lines = m.classify_changed_paths(paths)
    text = "\n".join(lines)
    assert ".env.example" in text or "environment" in text.lower()
    assert "pyproject.toml" in text or "pip install" in text
    assert "scripts/" in text
    assert "workflows" in text.lower()
    assert "Makefile" in text


def test_classify_empty_paths() -> None:
    m = _load_module()
    assert m.classify_changed_paths([]) == []
    assert m.classify_changed_paths(["", "  "]) == []


def test_normalize_paths_strips_and_slashes() -> None:
    m = _load_module()
    assert m.normalize_paths([" a/b ", "x\\y.py"]) == ["a/b", "x/y.py"]


def test_pr_and_file_mutually_exclusive() -> None:
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "post_merge_classify.py"
    r = subprocess.run(
        [
            sys.executable,
            str(script),
            "--pr",
            "1",
            "--file",
            str(root / "pyproject.toml"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    err = (r.stderr + r.stdout).lower()
    assert "not allowed with argument" in err
