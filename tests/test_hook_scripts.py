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


def _load_detect_git_commit():
    spec = importlib.util.spec_from_file_location(
        "hook_detect_git_commit",
        SCRIPTS / "hook_detect_git_commit.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_hook_detect_git_commit_rejects_relative_env_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = tmp_path / "hub"
    (hub / "hooks").mkdir(parents=True)
    (hub / "hooks" / "hook_protect_main_impl.py").write_text("OK = True\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLEET_GOVERNANCE_ROOT", "hub")

    det = _load_detect_git_commit()
    assert det._canonical_impl_path() is None


def test_hook_detect_git_commit_allows_symlink_inside_hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = tmp_path / "hub"
    real_hooks = hub / "real_hooks"
    real_hooks.mkdir(parents=True)
    target = real_hooks / "hook_protect_main_impl.py"
    target.write_text("OK = True\n", encoding="utf-8")
    (hub / "hooks").symlink_to(real_hooks)
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLEET_GOVERNANCE_ROOT", str(hub))

    det = _load_detect_git_commit()
    assert det._canonical_impl_path() == target.resolve()


def test_hook_detect_git_commit_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = tmp_path / "hub"
    (hub / "hooks").mkdir(parents=True)
    outside = tmp_path / "outside" / "hook_protect_main_impl.py"
    outside.parent.mkdir()
    outside.write_text("OK = True\n", encoding="utf-8")
    (hub / "hooks" / "hook_protect_main_impl.py").symlink_to(outside)
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLEET_GOVERNANCE_ROOT", str(hub))

    det = _load_detect_git_commit()
    assert det._canonical_impl_path() is None


# Not covered here, on purpose: the sensitive-file guard's behavior. It is hub-canonical since
# governance-hub#862 (this repo carries the shim scripts/hook_sensitive_file_guard.py), so its
# tests live in the hub. tests/test_hook_sensitive_file_guard_wiring.py pins the wiring here.


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

            if matcher in ("Edit|Write", "Edit|Write|MultiEdit|NotebookEdit") and (
                "sensitive file" in prompt or "sensitive-file" in prompt
            ):
                offenders.append(
                    "PreToolUse:Edit|Write sensitive-file prompt (replace with command hook)"
                )

    sensitive_cmd = False
    for group in hooks.get("PreToolUse", []) or []:
        if group.get("matcher") not in ("Edit|Write", "Edit|Write|MultiEdit|NotebookEdit"):
            continue
        for h in group.get("hooks", []) or []:
            if h.get("type") != "command":
                continue
            if "hook_sensitive_file_guard.py" in str(h.get("command", "")):
                sensitive_cmd = True
                break
    if not sensitive_cmd:
        offenders.append("PreToolUse:Edit|Write missing command hook hook_sensitive_file_guard.py")

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
