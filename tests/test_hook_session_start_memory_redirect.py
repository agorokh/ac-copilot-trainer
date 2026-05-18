"""Tests for ``scripts/hook_session_start_memory_redirect.py``.

The redirect hook writes a deprecation README to Claude Code's per-user
auto-memory directory for this project. Tests verify the marker is written
and refreshed, the slug derivation matches Claude Code's convention, and
the kill-switch works.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hook_session_start_memory_redirect.py"


def _run(cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        check=False,
        timeout=10,
    )


def _setup_repo(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git").mkdir(exist_ok=True)
    return tmp_path


def _expected_target(project_root: Path, home: Path) -> Path:
    slug = project_root.resolve().as_posix().replace("/", "-")
    return home / ".claude" / "projects" / slug / "memory"


def test_writes_readme_to_slug_directory(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = _setup_repo(tmp_path / "repo")
    proc = _run(repo, env={"HOME": str(home)})
    assert proc.returncode == 0
    target = _expected_target(repo, home)
    readme = target / "README.md"
    sentinel = target / "DEPRECATED.txt"
    assert readme.is_file(), proc.stdout + proc.stderr
    assert sentinel.is_file()
    body = readme.read_text(encoding="utf-8")
    assert "DEPRECATED" in body
    assert "memory-three-tiers" in body


def test_refreshes_existing_readme(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = _setup_repo(tmp_path / "repo")
    target = _expected_target(repo, home)
    target.mkdir(parents=True)
    (target / "README.md").write_text("old content", encoding="utf-8")
    _run(repo, env={"HOME": str(home)})
    body = (target / "README.md").read_text(encoding="utf-8")
    assert "old content" not in body
    assert "DEPRECATED" in body


def test_kill_switch(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = _setup_repo(tmp_path / "repo")
    proc = _run(repo, env={"HOME": str(home), "CLAUDE_MEMORY_REDIRECT": "0"})
    assert proc.returncode == 0
    target = _expected_target(repo, home)
    assert not target.exists(), "kill switch must skip directory creation"


def test_does_not_delete_existing_files(tmp_path: Path, monkeypatch) -> None:
    """Be conservative: existing auto-memory files might have history to review."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = _setup_repo(tmp_path / "repo")
    target = _expected_target(repo, home)
    target.mkdir(parents=True)
    (target / "feedback_user_role.md").write_text("legacy memory", encoding="utf-8")
    _run(repo, env={"HOME": str(home)})
    legacy = (target / "feedback_user_role.md").read_text(encoding="utf-8")
    assert legacy == "legacy memory"


def test_fail_open_on_oserror(tmp_path: Path, monkeypatch) -> None:
    """Write failures must not wedge the session (cross-platform)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    repo = _setup_repo(tmp_path / "repo")
    original_write = Path.write_text

    def guarded_write(self: Path, data: str, *args, **kwargs) -> int:
        if self.name == "README.md":
            raise OSError("simulated write failure")
        return original_write(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", guarded_write)
    proc = _run(repo, env={"HOME": str(home)})
    assert proc.returncode == 0
