"""Weekly process-miner PRs stay inside the zero-human merge contract.

Spoke-adapted from template-repo tests/test_process_miner/test_workflow_pr_scope.py.
The vendored miner no longer accepts an AGENTS.md output path (gov-hub#290), while
glob add-only staging and the fail-closed scope guard remain defense in depth.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _REPO_ROOT / ".github/workflows/process-miner.yml"
_SCOPE_GUARD = _REPO_ROOT / "scripts/process_miner_pr_scope.sh"


def _bash_executable() -> str | None:
    """Locate a bash interpreter, or ``None`` when the host has none.

    ``bash`` is not guaranteed on ``PATH`` in a native Windows shell: Git for Windows commonly
    exposes ``git.exe`` through its ``cmd`` directory while leaving ``bash.exe`` off ``PATH``. So
    fall back to deriving it from git's own install root rather than assuming the bare name
    resolves.
    """
    found = shutil.which("bash")
    if found:
        return found
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent
        for candidate in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
            if candidate.is_file():
                return str(candidate)
    return None


def _run_scope_guard(repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the shell scope guard through bash rather than exec'ing the ``.sh`` directly.

    Windows cannot execute a shell script as a process image — a direct
    ``subprocess.run([str(_SCOPE_GUARD)])`` raises ``OSError: [WinError 193] %1 is not a valid
    Win32 application`` — so these tests passed in Linux CI but failed deterministically on the
    Windows rig, where they blocked ``make ci-fast``. Naming the interpreter explicitly is correct
    on every platform (it is a bash script either way) and keeps the guard's behavior identical.
    """
    bash = _bash_executable()
    if bash is None:
        pytest.skip("no bash interpreter available to run the shell scope guard")
    return subprocess.run(
        [bash, str(_SCOPE_GUARD)],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "miner-test@example.invalid")
    _git(repo, "config", "user.name", "Miner Test")
    (repo / "AGENTS.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "AGENTS.md")
    _git(repo, "commit", "-m", "baseline")


def test_weekly_miner_workflow_invokes_runtime_scope_guard() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")

    assert "':(glob).claude/rules/learned/**/*.md'" in text
    assert "':(glob).cursor/rules/learned/**/*.mdc'" in text
    assert "scripts/process_miner_pr_scope.sh" in text
    assert "git add -- ':(glob).claude/rules/learned/**/*.md' || true" in text
    assert "git add -- ':(glob).cursor/rules/learned/**/*.mdc' || true" in text
    assert (
        "git add .claude/rules/learned .cursor/rules/learned reports/process_miner AGENTS.md"
        not in text
    )


def test_weekly_miner_stages_missing_rule_sides_independently() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    claude_stage = "git add -- ':(glob).claude/rules/learned/**/*.md' || true"
    cursor_stage = "git add -- ':(glob).cursor/rules/learned/**/*.mdc' || true"

    assert text.count(claude_stage) == 1
    assert text.count(cursor_stage) == 1
    assert text.index(claude_stage) < text.index(cursor_stage)


def test_runtime_scope_guard_accepts_only_added_rule_pairs(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    claude_rule = tmp_path / ".claude/rules/learned/local/rule.md"
    cursor_rule = tmp_path / ".cursor/rules/learned/local/rule.mdc"
    report = tmp_path / "reports/process_miner/latest.md"
    for path in (claude_rule, cursor_rule, report):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("dirty but deliberately unstaged\n", encoding="utf-8")

    _git(
        tmp_path,
        "add",
        "--",
        ":(glob).claude/rules/learned/**/*.md",
        ":(glob).cursor/rules/learned/**/*.mdc",
    )
    result = _run_scope_guard(tmp_path)

    assert result.returncode == 0
    assert _git(tmp_path, "diff", "--cached", "--name-status").stdout.splitlines() == [
        "A\t.claude/rules/learned/local/rule.md",
        "A\t.cursor/rules/learned/local/rule.mdc",
    ]


def test_runtime_scope_guard_accepts_modified_rule_and_rejects_non_rule(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    existing = tmp_path / ".claude/rules/learned/local/existing.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("baseline rule\n", encoding="utf-8")
    _git(tmp_path, "add", str(existing.relative_to(tmp_path)))
    _git(tmp_path, "commit", "-m", "existing rule")

    existing.write_text("modified rule\n", encoding="utf-8")
    _git(tmp_path, "add", str(existing.relative_to(tmp_path)))
    modified = _run_scope_guard(tmp_path)
    assert modified.returncode == 0

    _git(tmp_path, "reset", "--hard", "HEAD")
    (tmp_path / "AGENTS.md").write_text("unsafe index update\n", encoding="utf-8")
    _git(tmp_path, "add", "AGENTS.md")
    non_rule = _run_scope_guard(tmp_path)
    assert non_rule.returncode == 1
    assert "AGENTS.md" in non_rule.stderr


def test_weekly_miner_report_is_an_audit_artifact_not_pr_content() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")

    assert "name: Upload process-miner audit sidecar" in text
    assert "uses: actions/upload-artifact@v7" in text
    assert "path: reports/process_miner" in text
