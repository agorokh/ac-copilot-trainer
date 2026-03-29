"""Tests for ``scripts/copier_post_copy.py`` merge helpers."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path


def _load_copier_post_copy() -> types.ModuleType:
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts" / "copier_post_copy.py"
    spec = importlib.util.spec_from_file_location("copier_post_copy", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_relocate_or_merge_moves_when_destination_missing(tmp_path: Path) -> None:
    mod = _load_copier_post_copy()
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "a").mkdir(parents=True)
    (src / "a" / "f.txt").write_text("x", encoding="utf-8")
    mod._relocate_or_merge_tree(active=True, src=src, dst=dst)
    assert not src.exists()
    assert (dst / "a" / "f.txt").read_text(encoding="utf-8") == "x"


def test_merge_missing_files_only_skips_existing(tmp_path: Path) -> None:
    """New files from template are copied; existing destination files are not overwritten."""
    mod = _load_copier_post_copy()
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "nested").mkdir(parents=True)
    (src / "nested" / "new.md").write_text("from-template", encoding="utf-8")
    (dst / "nested").mkdir(parents=True)
    (dst / "nested" / "existing.md").write_text("user-owned", encoding="utf-8")
    mod._merge_missing_files_only(src, dst)
    assert (dst / "nested" / "new.md").read_text(encoding="utf-8") == "from-template"
    assert (dst / "nested" / "existing.md").read_text(encoding="utf-8") == "user-owned"


def _script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "copier_post_copy.py"


def test_script_invalid_yaml_exits_nonzero(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("{broken", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(_script_path())],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1


def test_script_incomplete_answers_exit_code(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text(
        "project_name: foo\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(_script_path())],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "missing" in r.stderr.lower()


def test_script_rejects_unsafe_project_key(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text(
        "project_name: foo\nproject_key: Bad/Key\npackage_name: foo_pkg\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(_script_path())],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
