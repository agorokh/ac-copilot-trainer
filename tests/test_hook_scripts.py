"""Smoke tests for flow-control hook scripts under `scripts/`.

These are the deterministic backing implementations for the Claude Code
PreToolUse hooks defined in `.claude/settings.base.json`. Each script reads
Claude's hook JSON on stdin and signals allow/block via exit code 0/2.

Catching regressions here prevents the class of bug documented in
template-repo issue #91 (prompt hooks silently stopping agent continuation).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"

_SKIP_NO_BASH = pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="bash not on PATH; hook scripts are bash-only",
)


def _run(script: Path, payload: dict, *, cwd: Path | None = None) -> int:
    """Run a hook script with JSON payload on stdin, return exit code."""
    env = os.environ.copy()
    # Keep output quiet and deterministic regardless of user locale.
    env["LC_ALL"] = "C"
    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
        check=False,
        timeout=15,
    )
    return result.returncode


# ---------------------------------------------------------------------------
# hook_protect_main.sh
# ---------------------------------------------------------------------------

PROTECT_MAIN = SCRIPTS / "hook_protect_main.sh"

# #338 hub-and-spoke: hook_protect_main_impl.py is now a thin governance shim. Its internal API
# (_shell_command_segments, command_includes_git_commit_intent, …) and its calibrated block/allow
# behaviour live in the fleet-governance hub, which owns + re-runs the full protect-main suite for
# every spoke. The tests below assert the spoke's former *vendored* behaviour, which has since been
# revised in the hub (e.g. broad bare-push and aliased-commit handling). Running them against the
# shim exercises a delegator that has no internals (AttributeError) or asserts pre-shim semantics —
# skip when the impl is a shim; coverage migrated to the hub.
_PROTECT_IS_SHIM = (SCRIPTS / "hook_protect_main_impl.py").is_file() and "governance shim" in (
    SCRIPTS / "hook_protect_main_impl.py"
).read_text(encoding="utf-8")
_SKIP_PROTECT_SHIM = pytest.mark.skipif(
    _PROTECT_IS_SHIM,
    reason="protect-main impl is a governance-hub shim; coverage lives in the hub.",
)


def _load_protect_impl():
    spec = importlib.util.spec_from_file_location(
        "hook_protect_main_impl",
        SCRIPTS / "hook_protect_main_impl.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


@_SKIP_PROTECT_SHIM
def test_shell_command_segments_are_independent_lists() -> None:
    """Regression: flush must not append the same list object that is then cleared."""
    impl = _load_protect_impl()
    segs = impl._shell_command_segments(shlex.split("git status && git push origin main"))
    assert len(segs) == 2
    assert segs[0] == ["git", "status"]
    assert segs[1] == ["git", "push", "origin", "main"]
    segs[0].append("x")
    assert "x" not in segs[1]


@_SKIP_PROTECT_SHIM
def test_shell_command_segments_splits_standalone_ampersand() -> None:
    impl = _load_protect_impl()
    segs = impl._shell_command_segments(shlex.split("echo ok & git push origin main"))
    assert segs == [["echo", "ok"], ["git", "push", "origin", "main"]], segs


@_SKIP_PROTECT_SHIM
def test_inspect_allows_echo_with_git_words_not_command() -> None:
    impl = _load_protect_impl()
    assert impl._inspect_command_text("echo git push origin main", depth=0) == 0


@_SKIP_PROTECT_SHIM
def test_expand_glue_before_git_tokens() -> None:
    impl = _load_protect_impl()
    toks = impl._expand_glue_before_git_tokens(shlex.split("echo ok;git push origin main"))
    assert "ok;git" not in toks, toks
    assert impl._inspect_command_text("echo ok;git push origin main", depth=0) == 2
    toks2 = impl._expand_glue_before_git_tokens(shlex.split("echo ok&&git push origin main"))
    assert "ok&&git" not in toks2, toks2
    assert impl._inspect_command_text("echo ok&&git push origin main", depth=0) == 2


@_SKIP_PROTECT_SHIM
def test_logical_shell_lines_keeps_newline_inside_single_quotes() -> None:
    impl = _load_protect_impl()
    text = "bash -c 'line1\nline2'"
    assert impl._logical_shell_lines(text) == [text]


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_compact_chain_and_git(tmp_path: Path) -> None:
    """``ok&&git`` must split so ``git push`` is inspected (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "echo ok&&git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_git_push_in_multiline_quoted_bash_c(tmp_path: Path) -> None:
    """Quoted newline in ``bash -c`` must not skip the embedded ``git push`` (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    cmd = "bash -c 'git push origin main\n'"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
def test_git_commit_intent_false_on_substring_false_positive() -> None:
    impl = _load_protect_impl()
    assert not impl.command_includes_git_commit_intent("echo my_git_commit_helpers")


@_SKIP_PROTECT_SHIM
def test_git_commit_intent_true_for_plain_commit() -> None:
    impl = _load_protect_impl()
    assert impl.command_includes_git_commit_intent("git commit -m msg")


@_SKIP_PROTECT_SHIM
def test_git_commit_intent_true_inside_bash_c() -> None:
    impl = _load_protect_impl()
    assert impl.command_includes_git_commit_intent("bash -c 'git commit -m x'")


@_SKIP_PROTECT_SHIM
def test_hook_detect_git_commit_script() -> None:
    det = SCRIPTS / "hook_detect_git_commit.py"
    payload = json.dumps({"tool_input": {"command": "echo my_git_commit_helpers"}})
    r = subprocess.run(
        [sys.executable, str(det)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 1
    payload2 = json.dumps({"tool_input": {"command": "git commit -m x"}})
    r2 = subprocess.run(
        [sys.executable, str(det)],
        input=payload2,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r2.returncode == 0
    payload3 = json.dumps({"tool_input": {"command": "git -c alias.c=commit c -m x"}})
    r3 = subprocess.run(
        [sys.executable, str(det)],
        input=payload3,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r3.returncode == 0


def _git_init_on(tmp_path: Path, branch: str) -> Path:
    """Create an empty git repo with HEAD on the given branch."""
    subprocess.run(
        ["git", "init", "-q", "-b", branch, str(tmp_path)],
        check=True,
        capture_output=True,
    )
    return tmp_path


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_allows_non_git_command(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "main")
    assert _run(PROTECT_MAIN, {"tool_input": {"command": "ls -la"}}, cwd=tmp_path) == 0


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_commit_on_main(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "main")
    assert _run(PROTECT_MAIN, {"tool_input": {"command": "git commit -m x"}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_on_master(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "master")
    assert (
        _run(PROTECT_MAIN, {"tool_input": {"command": "git push origin master"}}, cwd=tmp_path) == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_allows_commit_on_feature_branch(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert _run(PROTECT_MAIN, {"tool_input": {"command": "git commit -m x"}}, cwd=tmp_path) == 0


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_explicit_refspec_to_main(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    # Feature branch but refspec explicitly targets main on the remote.
    cmd = "git push origin HEAD:main"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_positional_main_without_colon(tmp_path: Path) -> None:
    """Regression: `git push origin main` must not bypass the hook (Bugbot / Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(PROTECT_MAIN, {"tool_input": {"command": "git push origin main"}}, cwd=tmp_path) == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_forced_push_plus_prefix(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(PROTECT_MAIN, {"tool_input": {"command": "git push origin +main"}}, cwd=tmp_path) == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_allows_similar_branch_maintenance(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git push origin HEAD:maintenance"}},
            cwd=tmp_path,
        )
        == 0
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_allows_push_when_remote_named_like_protected_branch(tmp_path: Path) -> None:
    """Remote named ``main``/``master`` is not a refspec; do not false-positive (Bugbot)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git push main feature-branch"}},
            cwd=tmp_path,
        )
        == 0
    )
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git push master release-candidate"}},
            cwd=tmp_path,
        )
        == 0
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_singleton_repo_url_without_refspec(tmp_path: Path) -> None:
    """Lone SCP/HTTPS remote is refspec-less and can update main under matching defaults (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {
                "tool_input": {
                    "command": "git push git@github.com:org/repo.git",
                },
            },
            cwd=tmp_path,
        )
        == 2
    )
    assert (
        _run(
            PROTECT_MAIN,
            {
                "tool_input": {
                    "command": "git push https://github.com/org/repo.git",
                },
            },
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_chained_shell_before_git_push(tmp_path: Path) -> None:
    """Each chained command is inspected; do not stop at the first ``git`` argv (Bugbot)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git status && git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "echo hi; git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_newline_separated_git_push(tmp_path: Path) -> None:
    """Regression: newline must not hide a later ``git push`` (review thread)."""
    _git_init_on(tmp_path, "feat/x")
    cmd = "echo ok\ngit push origin main"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_background_ampersand_git_push(tmp_path: Path) -> None:
    """Regression: single ``&`` must split like ``&&`` without breaking ``2>&1`` tokens."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "echo ok & git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_allows_redirect_2_gt_ampersand(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "echo work 2>&1"}},
            cwd=tmp_path,
        )
        == 0
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_bash_c_git_push(tmp_path: Path) -> None:
    """Regression: ``bash -c 'git push …'`` must not bypass the guard (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "bash -c 'git push origin main'"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_bash_xc_combined_flags(tmp_path: Path) -> None:
    """Regression: ``bash -xc '…'`` bundles ``-x`` and ``-c`` (Bugbot)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "bash -xc 'git push origin main'"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_parenthesized_git_push(tmp_path: Path) -> None:
    """Regression: ``(git push …)`` must not bypass the guard (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "(git push origin main)"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_export_git_dir_before_commit(tmp_path: Path) -> None:
    """``export GIT_DIR=…`` must persist for a later ``git`` on the same line (Codex)."""
    inner = tmp_path / "inner"
    inner.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(inner)],
        check=True,
        capture_output=True,
    )
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "feat/x", str(outer)],
        check=True,
        capture_output=True,
    )
    gd = (inner / ".git").resolve()
    cmd = f"export GIT_DIR={gd}; git commit -m x"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=outer) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_git_inside_dollar_paren_substitution(tmp_path: Path) -> None:
    """Regression: ``echo $(git push …)`` must not bypass the guard (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "echo $(git push origin main)"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_git_inside_backtick_substitution(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "echo `git push origin main`"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_time_wrapped_git_push(tmp_path: Path) -> None:
    """``time`` is not a shell bootstrap; peel it so ``git push`` is inspected (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "time git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_brace_expanded_refspec(tmp_path: Path) -> None:
    """Brace expansion can yield ``main``; fail closed on ``{``/``}`` in refspecs (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git push origin {m,}ain"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_wildcard_refspec(tmp_path: Path) -> None:
    """Wildcard refspecs can update main; fail closed (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git push origin refs/heads/*:refs/heads/*"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_refspec_with_shell_variable(tmp_path: Path) -> None:
    """Shell-expanded ref targets are invisible to shlex; fail closed (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git push origin $branch"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_git_dash_c_value_with_semicolon(tmp_path: Path) -> None:
    """Semicolons inside a single ``-c`` value must not split the argv (Bugbot)."""
    _git_init_on(tmp_path, "feat/x")
    cmd = 'git -c "user.name=A;B" push origin main'
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_compact_semicolon_before_git(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "echo ok;git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_semicolon_before_absolute_git(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "echo ok;/usr/bin/git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_line_continuation_spelling_main(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    cmd = "git push origin ma\\\nin"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_git_after_even_trailing_backslashes(tmp_path: Path) -> None:
    """Even trailing ``\\`` does not join lines; the next ``git push`` is still scanned (Codex)."""
    _git_init_on(tmp_path, "feat/x")
    cmd = "echo ok\\\\\ngit push origin main"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_git_push_via_inline_alias(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git -c alias.p=push p origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_git_push_via_inline_alias_custom_remote(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git -c alias.p=push p fork main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_shell_expanded_git_subcommand(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git $s origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_commit_alias_amend_on_protected_branch(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "main")
    assert (
        _run(
            PROTECT_MAIN,
            {
                "tool_input": {
                    "command": "git -c alias.c=commit c --amend --no-edit",
                }
            },
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_full_path_git_binary(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "/usr/bin/git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_allows_chained_readonly_git_commands(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git status && git rev-parse --short HEAD"}},
            cwd=tmp_path,
        )
        == 0
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_chained_commit_on_main(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "main")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "git status && git commit -m x"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_with_git_cwd_option(tmp_path: Path) -> None:
    repo = _git_init_on(tmp_path, "feat/x")
    cmd = f"git -C {repo} push origin main"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=repo) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_with_git_dash_c_option(tmp_path: Path) -> None:
    repo = _git_init_on(tmp_path, "feat/x")
    cmd = f"git -C {repo} -c user.name=test push origin main"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=repo) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_commit_on_main_with_global_options(tmp_path: Path) -> None:
    repo = _git_init_on(tmp_path, "main")
    cmd = f"git -C {repo} commit -m x"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=repo) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_branch_probe_uses_git_dash_c(tmp_path: Path) -> None:
    """HEAD must be resolved in the repo named by -C, not only the hook cwd."""
    inner = tmp_path / "inner"
    inner.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(inner)],
        check=True,
        capture_output=True,
    )
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "feat/x", str(outer)],
        check=True,
        capture_output=True,
    )
    cmd = f"git -C {inner} commit -m x"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=outer) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_env_prefix_before_git_push(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "env GIT_TRACE=0 git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_env_ignore_environment_git_push(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert (
        _run(
            PROTECT_MAIN,
            {"tool_input": {"command": "env -i git push origin main"}},
            cwd=tmp_path,
        )
        == 2
    )


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_all(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert _run(PROTECT_MAIN, {"tool_input": {"command": "git push --all"}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_mirror(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert _run(PROTECT_MAIN, {"tool_input": {"command": "git push --mirror"}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_push_remote_only(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert _run(PROTECT_MAIN, {"tool_input": {"command": "git push origin"}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_blocks_bare_git_push(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "feat/x")
    assert _run(PROTECT_MAIN, {"tool_input": {"command": "git push"}}, cwd=tmp_path) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_respects_git_dir_env_for_head(tmp_path: Path) -> None:
    inner = tmp_path / "inner"
    inner.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(inner)],
        check=True,
        capture_output=True,
    )
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "feat/x", str(outer)],
        check=True,
        capture_output=True,
    )
    gd = (inner / ".git").resolve()
    cmd = f"GIT_DIR={gd} git commit -m x"
    assert _run(PROTECT_MAIN, {"tool_input": {"command": cmd}}, cwd=outer) == 2


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_handles_empty_command(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "main")
    assert _run(PROTECT_MAIN, {"tool_input": {"command": ""}}, cwd=tmp_path) == 0


@_SKIP_PROTECT_SHIM
@_SKIP_NO_BASH
def test_protect_main_handles_malformed_json(tmp_path: Path) -> None:
    _git_init_on(tmp_path, "main")
    # Write raw bytes that are not JSON; script should fail open (exit 0).
    result = subprocess.run(
        ["bash", str(PROTECT_MAIN)],
        input="not json at all",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        check=False,
        timeout=15,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# hook_sensitive_file_guard.sh
# ---------------------------------------------------------------------------

GUARD = SCRIPTS / "hook_sensitive_file_guard.sh"


@_SKIP_NO_BASH
@pytest.mark.parametrize(
    "file_path",
    [
        "src/foo.py",
        "README.md",
        ".env.example",
        ".env.sample",
        ".env.template",
        "docs/notes.md",
        "scripts/hook_protect_main.sh",
    ],
)
def test_guard_allows_normal_paths(file_path: str) -> None:
    assert _run(GUARD, {"tool_input": {"file_path": file_path}}) == 0


@_SKIP_NO_BASH
def test_guard_allows_ascii_doc_asc_under_docs() -> None:
    """``.asc`` is often AsciiDoc; do not blanket-block outside key paths (Codex)."""
    assert _run(GUARD, {"tool_input": {"file_path": "docs/README.asc"}}) == 0


@_SKIP_NO_BASH
def test_guard_blocks_uppercase_env_filename() -> None:
    assert _run(GUARD, {"tool_input": {"file_path": ".ENV"}}) == 2


@_SKIP_NO_BASH
@pytest.mark.parametrize(
    "file_path",
    [
        ".env",
        ".env.production",
        ".env.local",
        "poetry.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "Cargo.lock",
        "uv.lock",
        "composer.lock",
        "Gemfile.lock",
        "go.sum",
        "npm-shrinkwrap.json",
        "shrinkwrap.yaml",
        "id_rsa",
        "id_ed25519",
        "certs/server.pem",
        "path/to/secret.key",
        "path/to/cert.p12",
        "keys/file.asc",
        "archive/old-config.yaml",
        "secrets/api.json",
        ".secrets/token",
        ".ssh/id_rsa",
        ".gnupg/private.asc",
    ],
)
def test_guard_blocks_sensitive_paths(file_path: str) -> None:
    assert _run(GUARD, {"tool_input": {"file_path": file_path}}) == 2


@_SKIP_NO_BASH
def test_guard_handles_windows_separators() -> None:
    # Backslashes should still match the archive/ pattern.
    assert _run(GUARD, {"tool_input": {"file_path": r"archive\old\file.md"}}) == 2


@_SKIP_NO_BASH
def test_guard_allows_missing_file_path() -> None:
    assert _run(GUARD, {"tool_input": {}}) == 0


@_SKIP_NO_BASH
def test_guard_handles_malformed_json() -> None:
    result = subprocess.run(
        ["bash", str(GUARD)],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# settings.base.json must not contain flow-control prompt hooks
# ---------------------------------------------------------------------------


def test_base_settings_has_no_unsafe_prompt_flow_control() -> None:
    """Flow-control hooks (PreToolUse, PostToolUse:Bash) must be `type: command`.

    Prompt hooks on these matchers depend on the small model emitting an exact
    literal token (PASS/ALLOW/BLOCK). That's fragile across models and wordings;
    one drifted response silently halts continuation. Keep prompt hooks for
    advisory content only (e.g. LOAD nudge, secret-pattern scanner)."""
    base = REPO_ROOT / ".claude" / "settings.base.json"
    data = json.loads(base.read_text(encoding="utf-8"))

    hooks = data.get("hooks", {})
    offenders: list[str] = []

    # The PostToolUse Bash matcher has no safe advisory use today.
    for group in hooks.get("PostToolUse", []) or []:
        if group.get("matcher") == "Bash":
            for h in group.get("hooks", []) or []:
                if h.get("type") == "prompt":
                    offenders.append("PostToolUse:Bash prompt hook (use command or omit)")

    # PreToolUse flow-control checks must NOT use prompts for guards that are
    # supposed to block continuation. Advisory prompts like LOAD reminders are
    # acceptable, but protected-branch and sensitive-file guards must remain
    # deterministic command hooks.
    for group in hooks.get("PreToolUse", []) or []:
        matcher = str(group.get("matcher", ""))
        for h in group.get("hooks", []) or []:
            if h.get("type") != "prompt":
                continue
            prompt = str(h.get("prompt", "")).lower()

            if matcher == "Edit|Write" and (
                "sensitive file" in prompt or "sensitive-file" in prompt
            ):
                offenders.append(
                    "PreToolUse:Edit|Write sensitive-file prompt (replace with command hook)"
                )

    sensitive_cmd = False
    for group in hooks.get("PreToolUse", []) or []:
        if group.get("matcher") != "Edit|Write":
            continue
        for h in group.get("hooks", []) or []:
            if h.get("type") != "command":
                continue
            if "hook_sensitive_file_guard.sh" in str(h.get("command", "")):
                sensitive_cmd = True
                break
    if not sensitive_cmd:
        offenders.append("PreToolUse:Edit|Write missing command hook hook_sensitive_file_guard.sh")

    for group in hooks.get("PreToolUse", []) or []:
        if group.get("matcher") != "Bash":
            continue
        bash_hooks = group.get("hooks", []) or []
        if any(h.get("type") == "prompt" for h in bash_hooks):
            offenders.append("PreToolUse:Bash prompt hook (use command hooks for flow control)")
        cmds = [h for h in bash_hooks if h.get("type") == "command"]
        if len(cmds) != 1:
            offenders.append(
                f"PreToolUse:Bash expected exactly 1 stdin-consuming command hook, got {len(cmds)}"
            )
            continue
        body = str(cmds[0].get("command", ""))
        if "hook_bash_pre_tool.sh" not in body:
            offenders.append("PreToolUse:Bash missing hook_bash_pre_tool.sh orchestrator")
        orc = REPO_ROOT / "scripts" / "hook_bash_pre_tool.sh"
        if orc.is_file():
            ot = orc.read_text(encoding="utf-8")
            if "hook_protect_main.sh" not in ot or "check_vault_follow_up.sh" not in ot:
                offenders.append(
                    "hook_bash_pre_tool.sh must chain hook_protect_main.sh "
                    "and check_vault_follow_up.sh"
                )
            if "hook_detect_git_commit.py" not in ot:
                offenders.append(
                    "hook_bash_pre_tool.sh must call hook_detect_git_commit.py "
                    "before vault follow-up (avoid *git*commit* false positives)"
                )

    assert not offenders, (
        "settings.base.json contains unsafe flow-control prompt hook(s):\n  - "
        + "\n  - ".join(offenders)
        + "\nSee docs/00_Core/HOOK_DESIGN.md for the convention."
    )


def test_hook_scripts_are_executable_bit_or_runnable() -> None:
    """Not all filesystems preserve +x (Windows); functional tests run via `bash script`."""
    impl = SCRIPTS / "hook_protect_main_impl.py"
    orch = SCRIPTS / "hook_bash_pre_tool.sh"
    jf = SCRIPTS / "hook_json_field.py"
    det = SCRIPTS / "hook_detect_git_commit.py"
    for script in (PROTECT_MAIN, impl, orch, jf, det, GUARD):
        assert script.is_file(), f"missing hook script: {script}"


def test_hook_json_field_extracts_tool_input_command() -> None:
    payload = json.dumps({"tool_input": {"command": "git status"}})
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "hook_json_field.py"), "tool_input.command"],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert r.stdout.strip() == "git status"


def test_hook_json_field_malformed_json_exits_zero() -> None:
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "hook_json_field.py"), "tool_input.command"],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "not valid JSON" in r.stderr


# ---------------------------------------------------------------------------
# hook_sql_ddl_guard.py — deterministic replacement for the SQL OPT-IN prompt
# ---------------------------------------------------------------------------

SQL_GUARD = SCRIPTS / "hook_sql_ddl_guard.py"


def _run_sql_guard(payload: dict, *, env_extra: dict[str, str] | None = None) -> tuple[int, str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    # Clean any inherited opt-in so each test asserts its own state.
    env.pop("CLAUDE_SQL_DDL_GUARD", None)
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(
        [sys.executable, str(SQL_GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=15,
    )
    return r.returncode, r.stderr


def test_sql_guard_default_no_op_even_with_ddl() -> None:
    """Template default is opt-in. No env var → always allow, regardless of content."""
    rc, _ = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/src/models.sql",
                "content": "CREATE TABLE users (id INT);",
            }
        }
    )
    assert rc == 0


def test_sql_guard_opt_in_blocks_create_table_in_src() -> None:
    rc, err = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/src/models.sql",
                "content": "CREATE TABLE users (id INT);",
            }
        },
        env_extra={"CLAUDE_SQL_DDL_GUARD": "1"},
    )
    assert rc == 2
    assert "SQL DDL" in err
    assert "CREATE TABLE" in err.upper()


@pytest.mark.parametrize(
    ("snippet", "needle"),
    [
        ("TRUNCATE users;", "TRUNCATE"),
        ("CREATE UNIQUE INDEX idx ON t (a);", "INDEX"),
        ("CREATE DATABASE app;", "DATABASE"),
        ("DROP DATABASE app;", "DATABASE"),
        ("CREATE EXTERNAL TABLE t (a INT);", "EXTERNAL"),
        ("CREATE OR REPLACE TABLE t (a INT);", "REPLACE"),
        ("CREATE VIEW v AS SELECT 1;", "VIEW"),
        ("CREATE OR REPLACE VIEW v AS SELECT 1;", "VIEW"),
        ("DROP VIEW v;", "VIEW"),
    ],
)
def test_sql_guard_opt_in_blocks_extended_ddl_shapes(snippet: str, needle: str) -> None:
    rc, err = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/src/models.sql",
                "content": snippet,
            }
        },
        env_extra={"CLAUDE_SQL_DDL_GUARD": "1"},
    )
    assert rc == 2
    assert "BLOCK: SQL DDL" in err
    assert needle.upper() in err.upper()


def test_sql_guard_opt_in_allows_migrations_dir() -> None:
    rc, _ = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/db/migrations/001_create_users.sql",
                "content": "CREATE TABLE users (id INT);",
            }
        },
        env_extra={"CLAUDE_SQL_DDL_GUARD": "1"},
    )
    assert rc == 0


def test_sql_guard_opt_in_allows_tests_path() -> None:
    rc, _ = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/tests/test_db.py",
                "content": "sql = 'CREATE TABLE t (id INT)'",
            }
        },
        env_extra={"CLAUDE_SQL_DDL_GUARD": "1"},
    )
    assert rc == 0


def test_sql_guard_opt_in_allows_docs_md() -> None:
    rc, _ = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/docs/schema.md",
                "content": "```sql\nCREATE TABLE x (id INT);\n```",
            }
        },
        env_extra={"CLAUDE_SQL_DDL_GUARD": "1"},
    )
    assert rc == 0


def test_sql_guard_opt_in_allows_no_ddl_content() -> None:
    rc, _ = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/src/foo.py",
                "content": "x = 1\n# select * from users\n",
            }
        },
        env_extra={"CLAUDE_SQL_DDL_GUARD": "1"},
    )
    assert rc == 0


def test_sql_guard_opt_in_picks_up_edit_new_string() -> None:
    rc, _ = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/src/dao.py",
                "new_string": "ALTER TABLE accounts ADD COLUMN balance NUMERIC;",
            }
        },
        env_extra={"CLAUDE_SQL_DDL_GUARD": "1"},
    )
    assert rc == 2


def test_sql_guard_opt_in_picks_up_multiedit_edits() -> None:
    rc, _ = _run_sql_guard(
        {
            "tool_input": {
                "file_path": "/repo/src/dao.py",
                "edits": [
                    {"new_string": "# harmless"},
                    {"new_string": "DROP TABLE accounts;"},
                ],
            }
        },
        env_extra={"CLAUDE_SQL_DDL_GUARD": "1"},
    )
    assert rc == 2


def test_sql_guard_malformed_json_fails_open() -> None:
    r = subprocess.run(
        [sys.executable, str(SQL_GUARD)],
        input="not json",
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "CLAUDE_SQL_DDL_GUARD": "1", "LC_ALL": "C"},
        timeout=15,
    )
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# Invariant: no LLM-bearing hook types anywhere in the merged template config
# ---------------------------------------------------------------------------


def _walk_hook_types(settings: dict) -> list[tuple[str, str, dict]]:
    """Return [(event, matcher, hook), ...] for every hook defined in settings."""
    out: list[tuple[str, str, dict]] = []
    for event, groups in (settings.get("hooks") or {}).items():
        for group in groups or []:
            matcher = str(group.get("matcher", "*"))
            for h in group.get("hooks", []) or []:
                if isinstance(h, dict):
                    out.append((event, matcher, h))
    return out


def test_invariant_no_prompt_or_agent_hooks_in_base() -> None:
    """Issue #107: zero `type: "prompt"` and zero `type: "agent"` hooks in the
    canonical template config. Both forms call an LLM in the hot path and have
    been the source of brown-out / stall incidents documented in PR #91,
    PR #95, PR #103, and this PR's changelog entry.

    Children can locally re-enable prompt/agent hooks via `settings.local.json`
    (and own the brown-out risk). The template stays deterministic.
    """
    base = REPO_ROOT / ".claude" / "settings.base.json"
    data = json.loads(base.read_text(encoding="utf-8"))
    offenders = [
        f"{event}[{matcher}] -> {h.get('type')}: {str(h.get('prompt') or h.get('command'))[:80]}"
        for event, matcher, h in _walk_hook_types(data)
        if h.get("type") in ("prompt", "agent")
    ]
    assert not offenders, (
        "settings.base.json contains LLM-bearing hooks; see issue #107.\n  - "
        + "\n  - ".join(offenders)
    )


def test_invariant_no_prompt_or_agent_hooks_in_generated_settings() -> None:
    """The committed `.claude/settings.json` (merge_settings.py output) must
    also be free of LLM-bearing hooks. Belt-and-suspenders for repos that
    inspect only the merged file."""
    p = REPO_ROOT / ".claude" / "settings.json"
    if not p.is_file():
        pytest.skip(".claude/settings.json not present (generated artifact)")
    data = json.loads(p.read_text(encoding="utf-8"))
    offenders = [
        f"{event}[{matcher}] -> {h.get('type')}"
        for event, matcher, h in _walk_hook_types(data)
        if h.get("type") in ("prompt", "agent")
    ]
    assert not offenders, (
        "Generated settings.json contains LLM-bearing hooks. Re-run "
        "`python3 scripts/merge_settings.py --no-local` after fixing base.\n  - "
        + "\n  - ".join(offenders)
    )


def test_invariant_stop_hooks_are_command_only() -> None:
    """Stop hooks specifically must be `type: "command"` (issue #107).

    The 120s `type: "agent"` SAVE hook was an active brown-out source: under
    upstream model outages the sub-agent itself hung, extending the
    user-visible session-stop window (removed in the slim-down ADR)."""
    base = REPO_ROOT / ".claude" / "settings.base.json"
    data = json.loads(base.read_text(encoding="utf-8"))
    offenders = [
        f"Stop[{matcher}] -> {h.get('type')!r}"
        for event, matcher, h in _walk_hook_types(data)
        if event == "Stop" and h.get("type") != "command"
    ]
    assert not offenders, (
        "Stop hooks must be type=command only (issue #107). Saw:\n  - " + "\n  - ".join(offenders)
    )
