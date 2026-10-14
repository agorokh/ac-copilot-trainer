"""governance-hub#814 — post_merge_sync.sh never stashes.

`stash_wip_if_dirty` used to stash on the operator's branch; the script then checked out
main. agent-factory#1778 made the restore refuse a different base, which left the WIP
stranded in a stash every worktree shares (court-fillings-processing#292). The script now
never stashes: a dirty tree stays in place and the hub primitive `sync_fast_forward.py`
fast-forwards main only when the incoming changes cannot touch it.

This file is standalone by design — every copy of post_merge_sync.sh in the fleet has a
different body, so the property is asserted rather than the implementation.
"""

import re
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "post_merge_sync.sh"
_MUTATING_STASH = re.compile(
    r"\bgit\s+stash\s+(push|save|create|store|pop|apply)\b|\bgit\s+stash\s*$"
)


def _script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _executable_lines(script: str) -> list[str]:
    """Lines that run commands: comments and echoed hints are excluded."""
    lines = []
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("echo "):
            continue
        lines.append(line)
    return lines


def test_script_never_creates_or_replays_a_stash() -> None:
    offenders = [ln for ln in _executable_lines(_script()) if _MUTATING_STASH.search(ln)]
    assert offenders == [], f"post_merge_sync.sh must not stash (governance-hub#814): {offenders}"


def test_sync_phase_delegates_to_the_hub_fast_forward_primitive() -> None:
    script = _script()
    assert "sync_fast_forward.py" in script, "sync must call the hub primitive"
    assert '"$SYNC_FF" preflight' in script, "an OPEN PR must be preflighted before the merge"
    assert '"$SYNC_FF" ff' in script, "main must be fast-forwarded by the hub primitive"
