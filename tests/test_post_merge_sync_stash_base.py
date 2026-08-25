"""agent-factory#1778 — a stash must never be popped onto a base it was not taken on.

`stash_wip_if_dirty` stashes on the operator's branch; the script then checks out main
(and in some repos a vault branch). Popping there replays a diff computed against a
different tree and writes conflict markers into the operator's own source files.

The contract: record the base at stash time, and REFUSE rather than pop when HEAD does
not match. This file is standalone by design — every copy of post_merge_sync.sh in the
fleet has a different body (5 distinct `restore_stash_best_effort` variants across 15
repos), so the property is asserted rather than the implementation.
"""

import re
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "post_merge_sync.sh"


def _script() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_stash_base_is_recorded_at_stash_time() -> None:
    script = _script()
    assert "STASH_BASE_BRANCH" in script, "the stash's base branch must be recorded"
    assert 'STASH_BASE_OID="$(git rev-parse --verify HEAD' in script, (
        "the stash's base commit must be captured at stash time"
    )


def test_stash_restore_refuses_a_different_base() -> None:
    script = _script()
    restore = re.search(
        r"^(restore_stash_best_effort|restore_saved_stash_or_exit)\(\) \{\n(.*?)^\}",
        script,
        re.S | re.M,
    )
    assert restore, "no stash-restore function found in post_merge_sync.sh"
    body = restore.group(2)

    assert '"$_head_now" != "$STASH_BASE_OID"' in body, (
        "the restore path must compare HEAD against the recorded stash base"
    )

    guard_at = body.index("_head_now")
    # a pop is REAL only if `echo` does not precede it ON THE SAME LINE — the refusal
    # branch prints a `git stash pop ...` hint two lines above the real one, and a
    # character-window lookback wrongly swallows it.
    pops = []
    for m in re.finditer(r"git stash pop", body):
        line_start = body.rfind("\n", 0, m.start()) + 1
        if "echo" not in body[line_start : m.start()]:
            pops.append(m.start())
    assert pops, "no actual `git stash pop` found in the restore function"
    assert guard_at < min(pops), "the base check must run BEFORE the pop, not after it"
