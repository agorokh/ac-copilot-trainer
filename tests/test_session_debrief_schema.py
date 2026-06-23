"""Tests for ``tools.process_miner.session_debrief_schema``."""

from __future__ import annotations

import sys
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


def test_normalize_path_list_rejects_absolute_on_any_platform() -> None:
    """Absolute paths are skipped regardless of host OS flavour.

    Regression: ``WindowsPath('/etc/passwd').is_absolute()`` is ``False`` (no
    drive), so a host-native ``is_absolute()`` check let POSIX-absolute paths
    through the guard on Windows. The guard now tests both pure flavours.
    """
    assert normalize_path_list(["/etc/passwd"]) == []
    assert normalize_path_list(["C:/Windows/System32/config"]) == []
    # A mixed list drops only the absolute entry; the relative one survives.
    assert normalize_path_list(["/etc/passwd", "src/app.py"]) == ["src/app.py"]


def test_normalize_path_list_rejects_unc_path_without_repo_root() -> None:
    """UNC-style absolute paths are skipped when no ``repo_root`` is supplied."""
    assert normalize_path_list([r"\\server\share"]) == []
    assert normalize_path_list([r"\\server\share\secret.txt"]) == []


def test_normalize_path_list_foreign_absolute_with_repo_root_skipped() -> None:
    """A path absolute on the OTHER OS flavour is skipped even *with* ``repo_root``.

    Regression for the gemini-code-assist HIGH finding on PR #304. When
    ``_is_absolute_any_platform`` is true but ``Path(...).is_absolute()`` is
    ``False`` on the host, the path is not host-absolute, so ``resolve()`` anchors
    it to the CWD. If ``repo_root`` is an ancestor of the CWD, the old code's
    ``relative_to(repo_root)`` *succeeded* and admitted a cross-platform absolute
    path as a contained relative path. The guard must skip it instead.
    """
    # Pick a path absolute on the *other* OS flavour than the host.
    foreign = "/etc/passwd" if sys.platform.startswith("win") else "C:/Windows/System32"
    # repo_root = the CWD's anchor — an ancestor of the CWD, the worst case where a
    # pre-fix resolve()+relative_to() would have succeeded and admitted the path.
    anchor = Path(Path.cwd().anchor)
    assert normalize_path_list([foreign], repo_root=anchor) == []
