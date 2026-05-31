"""Regression: post_merge_sync.sh must clear the stale-main marker (issue #246).

Propagated from template-repo PR #164. The script had no marker-handling code,
so after a successful sync .scratch/session_stale.marker persisted and the
stale-main PreToolUse gate kept blocking Edit/Write. The sync now re-runs the
deterministic steward residue detector, which clears the marker only when no
residue remains.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNC = REPO_ROOT / "scripts" / "post_merge_sync.sh"


def test_sync_reruns_steward_to_clear_marker():
    text = SYNC.read_text(encoding="utf-8")
    assert "hook_session_start_post_merge_steward.py" in text
    assert "session_stale.marker" in text
