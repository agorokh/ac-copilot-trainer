"""Invariant: memory-enforcement hooks must be wired in `.claude/settings.base.json`.

Issue agorokh/agent-factory#169 — this is the test that would have caught the
"dead substrate" condition (hook scripts present but never invoked because
`settings.base.json` did not reference them).

Extracted verbatim from template-repo `tests/test_hook_scripts.py`
(`test_invariant_memory_hooks_wired_in_base` + `_walk_hook_types` helper)
plus a relaxed `*_in_generated_settings` variant that tolerates the optional
`.claude/settings.json` artifact.

The PreToolUse:Bash gate is enforced by chaining `hook_memory_gate.py` INSIDE
`scripts/hook_bash_pre_tool.sh` (single-orchestrator pattern). This file
asserts that chain exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_invariant_memory_hooks_wired_in_base() -> None:
    """The memory-enforcement hooks must be wired in `.claude/settings.base.json`
    so children inheriting the template pick them up via `merge_settings.py`.

    - SessionStart: `hook_session_start_memory_prefetch.py` (direct)
    - SessionStart: `hook_session_start_memory_redirect.py` (direct)
    - PreToolUse Edit|Write|MultiEdit|NotebookEdit: `hook_memory_gate.py` (direct)
    - PreToolUse Bash: chained INSIDE `hook_bash_pre_tool.sh` (single orchestrator).
    """
    base = REPO_ROOT / ".claude" / "settings.base.json"
    assert base.is_file(), f"settings.base.json not found at {base}"
    data = json.loads(base.read_text(encoding="utf-8"))
    commands = [
        (event, matcher, str(h.get("command", "")))
        for event, matcher, h in _walk_hook_types(data)
        if h.get("type") == "command"
    ]
    required = {
        ("SessionStart", "*", "hook_session_start_memory_prefetch.py"),
        ("SessionStart", "*", "hook_session_start_memory_redirect.py"),
        ("PreToolUse", "Edit|Write|MultiEdit|NotebookEdit", "hook_memory_gate.py"),
    }
    saw = {
        (event, matcher, script)
        for event, matcher, cmd in commands
        for (req_event, req_matcher, script) in required
        if event == req_event and matcher == req_matcher and script in cmd
    }
    missing = required - saw
    assert not missing, (
        "Memory-enforcement hooks missing from settings.base.json "
        "(agorokh/agent-factory#169):\n  - "
        + "\n  - ".join(f"{e}[{m}] -> {s}" for e, m, s in sorted(missing))
    )

    # Bash gating happens inside the bash orchestrator. Verify the chain.
    orchestrator = REPO_ROOT / "scripts" / "hook_bash_pre_tool.sh"
    assert orchestrator.is_file(), (
        "scripts/hook_bash_pre_tool.sh missing — required by single-orchestrator "
        "pattern for PreToolUse:Bash memory gating."
    )
    body = orchestrator.read_text(encoding="utf-8")
    assert "hook_memory_gate.py" in body, (
        "hook_bash_pre_tool.sh must chain hook_memory_gate.py. "
        "Adding a parallel Bash hook entry instead would break the "
        "single-orchestrator invariant."
    )


def test_invariant_memory_hooks_wired_in_generated_settings() -> None:
    """If a generated `.claude/settings.json` exists, it must also carry the four
    memory hooks. Skip if absent (it's a regenerated artifact)."""
    p = REPO_ROOT / ".claude" / "settings.json"
    if not p.is_file():
        pytest.skip(".claude/settings.json not present (generated artifact)")
    data = json.loads(p.read_text(encoding="utf-8"))
    commands = [
        str(h.get("command", ""))
        for _event, _matcher, h in _walk_hook_types(data)
        if h.get("type") == "command"
    ]
    blob = "\n".join(commands)
    for needle in (
        "hook_session_start_memory_prefetch.py",
        "hook_session_start_memory_redirect.py",
        "hook_memory_gate.py",
    ):
        assert needle in blob, (
            f"Generated settings.json missing memory hook {needle!r}. "
            "Re-run scripts/merge_settings.py."
        )
