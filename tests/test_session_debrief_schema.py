"""Tests for ``tools.process_miner.session_debrief_schema``."""

from __future__ import annotations

from pathlib import Path

from tools.process_miner.session_debrief_schema import (
    normalize_path_list,
    normalize_pattern_list,
)


def test_normalize_path_list_preserves_dot_prefixed_segments() -> None:
    paths = normalize_path_list([".github/workflows/ci.yml", "./src/foo.py"])
    assert ".github/workflows/ci.yml" in paths
    assert "src/foo.py" in paths


def test_normalize_path_list_skips_parent_traversal() -> None:
    assert normalize_path_list(["../secret"]) == []


def test_normalize_path_list_absolute_without_repo_root_skipped() -> None:
    assert normalize_path_list(["/etc/passwd"]) == []


def test_normalize_path_list_absolute_relative_to_repo_root(tmp_path: Path) -> None:
    child = tmp_path / "a" / "b.txt"
    child.parent.mkdir(parents=True)
    child.touch()
    out = normalize_path_list([str(child.resolve())], repo_root=tmp_path)
    assert out == ["a/b.txt"]


def test_normalize_pattern_list_only_strings_from_list() -> None:
    assert normalize_pattern_list(["x", None, 3, " y "]) == ["x", "y"]


def test_normalize_pattern_list_strips_standalone_string() -> None:
    assert normalize_pattern_list("  forgot tests  ") == ["forgot tests"]


def test_normalize_path_list_dedupes_equivalent_paths() -> None:
    paths = normalize_path_list(["src/foo.py", "./src/foo.py"])
    assert paths == ["src/foo.py"]


def test_normalize_path_list_normalizes_backslashes() -> None:
    paths = normalize_path_list([r"src\bar\baz.py"])
    assert paths == ["src/bar/baz.py"]
