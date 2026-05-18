"""Smoke tests for the vault invariants graph.

These tests run cheaply and protect the structural assumptions that other
agents (and ``propagation_health_check.py``) make:

* Every node under ``00_System/invariants/`` is valid YAML frontmatter with
  required schema fields (``type: invariant``, ``status``, ``created``,
  ``updated``, ``part_of``).
* Every invariant is listed in ``invariants/_index.md`` (no orphans).
* The two issue-#115 invariants are present: ``memory-three-tiers.md`` and
  ``secrets-from-doppler.md``.

The vault uses ``ProjectTemplate`` as the placeholder project key; child
repos rename this folder at bootstrap. Tests target the template path
directly — they intentionally do not follow the rename, because the template
repo is the one that ships ``ProjectTemplate``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INVARIANTS_DIR = REPO_ROOT / "docs" / "01_Vault" / "ProjectTemplate" / "00_System" / "invariants"
INDEX = INVARIANTS_DIR / "_index.md"

REQUIRED_INVARIANTS = {
    "entrypoint.md",
    "no-secrets.md",
    "data-immutability.md",
    "persistence.md",
    "memory-three-tiers.md",
    "secrets-from-doppler.md",
}


def _read_frontmatter(path: Path) -> dict[str, str]:
    """Tiny frontmatter parser — no PyYAML dependency in this test."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    block = text[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("-"):
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


def test_invariants_directory_exists() -> None:
    assert INVARIANTS_DIR.is_dir(), f"missing invariants dir: {INVARIANTS_DIR}"
    assert INDEX.is_file(), f"missing invariants index: {INDEX}"


def test_required_invariants_present() -> None:
    on_disk = {p.name for p in INVARIANTS_DIR.glob("*.md") if p.name != "_index.md"}
    missing = REQUIRED_INVARIANTS - on_disk
    assert not missing, f"required invariants missing on disk: {sorted(missing)}"


@pytest.mark.parametrize("name", sorted(REQUIRED_INVARIANTS))
def test_invariant_frontmatter_valid(name: str) -> None:
    fm = _read_frontmatter(INVARIANTS_DIR / name)
    assert fm.get("type") == "invariant", (
        f"{name}: type must be 'invariant', got {fm.get('type')!r}"
    )
    assert fm.get("status") in {"active", "draft", "superseded"}, (
        f"{name}: status must be active|draft|superseded, got {fm.get('status')!r}"
    )
    assert fm.get("created"), f"{name}: missing 'created'"
    assert fm.get("updated"), f"{name}: missing 'updated'"
    assert "part_of" in fm or "relates_to" in (INVARIANTS_DIR / name).read_text(encoding="utf-8"), (
        f"{name}: must declare part_of or relates_to in frontmatter"
    )


def test_index_lists_all_invariants() -> None:
    """No orphan invariant nodes."""
    index_text = INDEX.read_text(encoding="utf-8")
    on_disk = {p.name for p in INVARIANTS_DIR.glob("*.md") if p.name != "_index.md"}
    missing_from_index = [n for n in sorted(on_disk) if n not in index_text]
    assert not missing_from_index, f"invariants not linked from _index.md: {missing_from_index}"


def test_index_relates_to_includes_new_invariants() -> None:
    """Issue #115 invariants must be in the index's relates_to (graph edges)."""
    index_text = INDEX.read_text(encoding="utf-8")
    assert "ProjectTemplate/00_System/invariants/memory-three-tiers.md" in index_text
    assert "ProjectTemplate/00_System/invariants/secrets-from-doppler.md" in index_text


def test_claude_md_carries_auto_memory_override() -> None:
    """CLAUDE.md must explicitly deprecate the auto-memory directory."""
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert (
        "Memory architecture override" in claude_md
        or "Memory architecture (three tiers, no side channels)" in claude_md
    ), "CLAUDE.md must include the auto-memory deprecation block per issue #115"
    assert "deprecated for this project" in claude_md
    assert "memory-three-tiers.md" in claude_md


def test_agent_core_principles_carries_invariant_gap_routing() -> None:
    """AGENT_CORE_PRINCIPLES.md must carry the stop-and-file-upstream rule."""
    text = (REPO_ROOT / "AGENT_CORE_PRINCIPLES.md").read_text(encoding="utf-8")
    assert "Architectural invariant gap" in text
    assert "architectural-invariant-gap" in text
    assert "tactical patch" in text.lower()


def test_issue_template_present() -> None:
    template = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "architectural-invariant-gap.md"
    assert template.is_file(), "missing issue template per issue #115 §F"
    body = template.read_text(encoding="utf-8")
    assert "Architectural invariant gap" in body
    assert "Propagation map" in body
    assert "Validation plan" in body
