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
repos rename this folder at bootstrap (e.g. ``AgentFactory``, ``DialSandbox``).
This test resolves the invariants directory by globbing
``docs/01_Vault/*/00_System/invariants/`` so the same test file remains
runnable in both the template repo and its renamed children — see
[agorokh/agent-factory#169](https://github.com/agorokh/agent-factory/issues/169)
for the fleet-rollout context that surfaced the hard-coded path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VAULT_ROOT = REPO_ROOT / "docs" / "01_Vault"


def _resolve_invariants_dir() -> Path:
    """Find the single ``<ProjectKey>/00_System/invariants/`` under the vault.

    Globs ``docs/01_Vault/*/00_System/invariants/`` and returns the unique
    match. Fails loudly if zero or multiple matches — children should rename
    ``ProjectTemplate`` to a single project key at bootstrap, never fan out.
    """
    candidates = sorted(VAULT_ROOT.glob("*/00_System/invariants"))
    candidates = [p for p in candidates if p.is_dir()]
    if not candidates:
        # Fall back to the template default so the failure message points at
        # the expected path rather than an opaque "list is empty".
        return VAULT_ROOT / "ProjectTemplate" / "00_System" / "invariants"
    if len(candidates) > 1:
        raise AssertionError(
            f"expected one vault project under {VAULT_ROOT}, found "
            f"{[p.relative_to(VAULT_ROOT) for p in candidates]}"
        )
    return candidates[0]


INVARIANTS_DIR = _resolve_invariants_dir()
INDEX = INVARIANTS_DIR / "_index.md"
PROJECT_KEY = INVARIANTS_DIR.relative_to(VAULT_ROOT).parts[0]

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
    # Use the resolved project key so renamed children (AgentFactory,
    # DialSandbox, ...) pass without per-child patches.
    assert f"{PROJECT_KEY}/00_System/invariants/memory-three-tiers.md" in index_text
    assert f"{PROJECT_KEY}/00_System/invariants/secrets-from-doppler.md" in index_text


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
