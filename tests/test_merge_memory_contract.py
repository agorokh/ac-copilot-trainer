"""Tests for ``scripts/merge_memory_contract.py``.

The merge script renders a marker-delimited "memory contract" block into
``AGENTS.md`` and ``.claude/agents/*.md`` (and any custom targets), preserving
all content outside the markers. Critical property: **idempotent**. Running
it twice on the same file must produce no diff.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "merge_memory_contract.py"

MARKER_START = "<!-- memory-contract:start -->"
MARKER_END = "<!-- memory-contract:end -->"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
        cwd=str(REPO_ROOT),
    )


def _setup_target(tmp_path: Path, body: str, *, name: str = "AGENTS.md") -> Path:
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return target


def test_appends_when_markers_missing(tmp_path: Path) -> None:
    target = _setup_target(tmp_path, "# AGENTS\n\nsome custom content here\n")
    proc = _run(["--root", str(tmp_path), "--target", "AGENTS.md"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = target.read_text(encoding="utf-8")
    assert "some custom content here" in text, "custom content must be preserved"
    assert MARKER_START in text and MARKER_END in text
    # Post-#117 pointer stub: heading is now "Memory contract (pointer)" and
    # the substantive rules live in-procedure in each agent's Tier-3 section.
    assert "Memory contract (pointer)" in text


def test_idempotent(tmp_path: Path) -> None:
    target = _setup_target(tmp_path, "# AGENTS\n\nsome custom content here\n")
    p1 = _run(["--root", str(tmp_path), "--target", "AGENTS.md"])
    assert p1.returncode == 0
    after_first = target.read_text(encoding="utf-8")
    p2 = _run(["--root", str(tmp_path), "--target", "AGENTS.md"])
    assert p2.returncode == 0
    after_second = target.read_text(encoding="utf-8")
    assert after_first == after_second, "second render must produce identical output"


def test_replaces_existing_block(tmp_path: Path) -> None:
    body = (
        "# AGENTS\n\nold content above\n\n"
        f"{MARKER_START}\nold contract block\n{MARKER_END}\n\nfooter below\n"
    )
    target = _setup_target(tmp_path, body)
    proc = _run(["--root", str(tmp_path), "--target", "AGENTS.md"])
    assert proc.returncode == 0
    text = target.read_text(encoding="utf-8")
    assert "old content above" in text
    assert "footer below" in text
    assert "old contract block" not in text
    # Post-#117 pointer stub: heading is now "Memory contract (pointer)" and
    # the substantive rules live in-procedure in each agent's Tier-3 section.
    assert "Memory contract (pointer)" in text


def test_diff_mode_does_not_modify(tmp_path: Path) -> None:
    original = "# AGENTS\nno markers yet\n"
    target = _setup_target(tmp_path, original)
    proc = _run(["--root", str(tmp_path), "--target", "AGENTS.md", "--diff"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert target.read_text(encoding="utf-8") == original
    assert "WOULD CHANGE" in proc.stdout or "rendered" in proc.stdout


def test_check_mode_exits_1_on_drift(tmp_path: Path) -> None:
    """--check must exit 1 when targets are out of sync (without modifying)."""
    target = _setup_target(tmp_path, "# AGENTS\nno markers yet\n")
    proc = _run(["--root", str(tmp_path), "--target", "AGENTS.md", "--check"])
    assert proc.returncode == 1
    # Must not have modified the file
    assert target.read_text(encoding="utf-8") == "# AGENTS\nno markers yet\n"


def test_check_mode_exits_0_when_in_sync(tmp_path: Path) -> None:
    _setup_target(tmp_path, "# AGENTS\n")
    # First render to bring in sync
    _run(["--root", str(tmp_path), "--target", "AGENTS.md"])
    proc = _run(["--root", str(tmp_path), "--target", "AGENTS.md", "--check"])
    assert proc.returncode == 0


def test_skip_missing_target(tmp_path: Path) -> None:
    """Missing targets don't fail the run (e.g. example-sandbox has no learner.md)."""
    proc = _run(["--root", str(tmp_path), "--target", "AGENTS.md"])
    # Should print a skip line and exit 0 (no target to render).
    assert proc.returncode == 0
    assert "skip (missing)" in proc.stdout


def test_preserves_per_repo_customization(tmp_path: Path) -> None:
    """Per-repo content outside the markers must survive a re-render."""
    custom_body = (
        "# AGENTS\n\n"
        "## Project-specific rules\n\n"
        "- Custom rule A unique to this child repo\n"
        "- Custom rule B with [a link](https://example.com)\n\n"
        "## Local development\n\n"
        "Use `make custom-target`.\n"
    )
    target = _setup_target(tmp_path, custom_body)
    _run(["--root", str(tmp_path), "--target", "AGENTS.md"])
    text = target.read_text(encoding="utf-8")
    # Every line of custom_body must survive.
    for needle in (
        "Custom rule A unique to this child repo",
        "Custom rule B with [a link](https://example.com)",
        "Local development",
        "Use `make custom-target`.",
    ):
        assert needle in text, f"customization lost: {needle!r}"


def test_agent_targets_use_parent_relative_links(tmp_path: Path) -> None:
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    target = agents / "learner.md"
    target.write_text("# Agent\n", encoding="utf-8")
    proc = _run(["--root", str(tmp_path), "--target", ".claude/agents/learner.md"])
    assert proc.returncode == 0
    text = target.read_text(encoding="utf-8")
    # Post-#117 pointer stub still references MEMORY_CONTRACT.md (canonical
    # contract pointer) with the correct ../../ parent-relative prefix when
    # rendered into .claude/agents/<name>.md. ops/memory_manifest.yml link
    # was removed from the stub (substantive rules now in-procedure), so
    # that assertion is dropped — verify the canonical contract link only.
    assert "](../../docs/00_Core/MEMORY_CONTRACT.md)" in text


def test_real_repo_is_in_sync() -> None:
    """The template-repo's own targets must be in sync with the script (CI invariant)."""
    proc = _run(["--check"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
