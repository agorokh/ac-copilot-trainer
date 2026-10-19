"""Invariant: the sensitive-file guard shim is wired for every write tool and for Bash.

The guard is hub-canonical since agorokh/governance-hub#862: the hub owns its behavior and its
tests. This repo carries only the generic shim and must invoke it from both settings surfaces
(Edit|Write|MultiEdit|NotebookEdit) and from the Bash orchestrator, ahead of the memory gate.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SHIM = REPO_ROOT / "scripts" / "hook_sensitive_file_guard.py"
SIBLING_SHIM = REPO_ROOT / "scripts" / "hook_memory_gate.py"
ORCHESTRATOR = REPO_ROOT / "scripts" / "hook_bash_pre_tool.sh"
SETTINGS_FILES = (
    REPO_ROOT / ".claude" / "settings.base.json",
    REPO_ROOT / ".claude" / "settings.json",
)
WRITE_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
CHAIN_LINE = 'printf \'%s\' "$input" | "$PY" "$here/hook_sensitive_file_guard.py" || exit $?'


def _pre_tool_use(settings: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for group in (settings.get("hooks") or {}).get("PreToolUse", []) or []:
        for hook in group.get("hooks", []) or []:
            if isinstance(hook, dict):
                out.append((str(group.get("matcher", "*")), str(hook.get("command", ""))))
    return out


def test_shim_is_byte_identical_to_a_sibling_shim() -> None:
    assert SHIM.read_bytes() == SIBLING_SHIM.read_bytes(), (
        "hook_sensitive_file_guard.py must be the generic governance shim (reference-not-vendor)"
    )


def test_vendored_guard_is_gone() -> None:
    assert not (REPO_ROOT / "scripts" / "hook_sensitive_file_guard.sh").exists()


def test_wired_for_every_write_tool_in_both_settings() -> None:
    for settings_file in SETTINGS_FILES:
        pre = _pre_tool_use(json.loads(settings_file.read_text(encoding="utf-8")))
        wired = [c for m, c in pre if m == WRITE_MATCHER and "hook_sensitive_file_guard.py" in c]
        assert wired, f"{settings_file.name}: guard shim not wired at PreToolUse {WRITE_MATCHER}"
        assert not any("hook_sensitive_file_guard.sh" in c for _, c in pre), settings_file.name


def test_chained_in_bash_orchestrator_before_the_memory_gate() -> None:
    chain = ORCHESTRATOR.read_text(encoding="utf-8")
    assert CHAIN_LINE in chain
    assert chain.index(CHAIN_LINE) < chain.index('hook_memory_gate.py" || exit')
