"""CLI smoke + worktree-root regression matrix for ``scripts/hook_repo_root.py``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import load_script_module

REPO_ROOT = Path(__file__).resolve().parent.parent

_hook_repo_root = load_script_module(
    "_test_hook_repo_root", REPO_ROOT / "scripts" / "hook_repo_root.py"
)
worktree_root_for = _hook_repo_root.worktree_root_for


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "docs").mkdir(exist_ok=True)
    (path / "README.md").write_text("x", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")


def test_hook_repo_root_importable_via_python() -> None:
    script = REPO_ROOT / "scripts" / "hook_repo_root.py"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util, pathlib, sys; "
            f"p=pathlib.Path({str(script)!r}); "
            "spec=importlib.util.spec_from_file_location('hook_repo_root', p); "
            "m=importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(m); "
            "assert callable(m.session_toplevel_dir)",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_worktree_root_for_main_repo(tmp_path: Path) -> None:
    repo = tmp_path / "main"
    _init_repo(repo)
    doc = repo / "docs" / "a.md"
    doc.write_text("x", encoding="utf-8")
    assert worktree_root_for(doc) == repo.resolve()
    # directory argument resolves to itself
    assert worktree_root_for(repo / "docs") == repo.resolve()


def test_worktree_root_for_nested_worktree(tmp_path: Path) -> None:
    # A nested worktree (Claude Code's .claude/worktrees/<name>/) must classify
    # by its OWN root, not the main repo — the agent-factory#308 bug.
    repo = tmp_path / "main"
    _init_repo(repo)
    wt = repo / ".claude" / "worktrees" / "slug"
    _git(repo, "worktree", "add", "-q", str(wt))
    (wt / "docs").mkdir(parents=True, exist_ok=True)
    doc = wt / "docs" / "b.md"
    doc.write_text("x", encoding="utf-8")
    assert worktree_root_for(doc) == wt.resolve()


def test_worktree_root_for_external_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "main"
    _init_repo(repo)
    wt = tmp_path / "external-wt"
    _git(repo, "worktree", "add", "-q", str(wt))
    doc = wt / "docs"
    doc.mkdir(parents=True, exist_ok=True)
    f = doc / "c.md"
    f.write_text("x", encoding="utf-8")
    assert worktree_root_for(f) == wt.resolve()


def test_worktree_root_for_outside_any_repo(tmp_path: Path) -> None:
    loose = tmp_path / "loose" / "file.md"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text("x", encoding="utf-8")
    assert worktree_root_for(loose) is None
