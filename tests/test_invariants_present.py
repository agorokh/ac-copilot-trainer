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
repos rename this folder at bootstrap (e.g. ``AgentFactory``, ``ExampleSandbox``).
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
    assert "part_of" in fm or "relates_to" in fm, (
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
    # ExampleSandbox, ...) pass without per-child patches.
    assert f"{PROJECT_KEY}/00_System/invariants/memory-three-tiers.md" in index_text
    assert f"{PROJECT_KEY}/00_System/invariants/secrets-from-doppler.md" in index_text


def test_claude_md_carries_auto_memory_override() -> None:
    """CLAUDE.md must explicitly deprecate the auto-memory directory."""
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert (
        "Memory architecture override" in claude_md
        or "Memory architecture (three tiers, no side channels)" in claude_md
        or "Persistent memory (three tiers, no side channels)" in claude_md
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


# --- Required body-section contract (fleet-propagated template-repo#308 / #309) ---
# A propagated invariant clause (e.g. secrets-from-doppler.md's "## Scope
# (cross-repo boundary)") can be silently dropped by a later edit. template-repo#309
# added this guard canonically, but by its charter it checks only the template's own
# vault; test_invariants_present.py is template-propagated, so each repo must carry the
# guard to catch drift in ITS OWN vault. This is the fleet-propagated, structure-agnostic
# form: it self-locates the single invariants dir under docs/01_Vault/*/00_System/invariants
# (works in the template and every renamed child) and asserts the named sections are present
# and non-empty. It reads ONLY this repo's own vault and knows nothing of other repos.
_DG309_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "secrets-from-doppler.md": ("## Rule", "## Scope"),
}


def _dg309_invariants_dir() -> Path:
    """Resolve the single ``<ProjectKey>/00_System/invariants`` dir under the vault by
    globbing, so this same block runs in the template and every renamed child."""
    vault_root = Path(__file__).resolve().parents[1] / "docs" / "01_Vault"
    cands = sorted(p for p in vault_root.glob("*/00_System/invariants") if p.is_dir())
    assert len(cands) == 1, (
        f"expected exactly one vault project under {vault_root}, found "
        f"{[str(p.relative_to(vault_root)) for p in cands]}"
    )
    return cands[0]


def _dg309_heading_satisfies(heading: str, required: str) -> bool:
    """Exact match or the required token followed by a space (allowing a trailing
    parenthetical) — so ``## Scope (cross-repo boundary)`` counts for ``## Scope`` while
    pluralised near-misses like ``## Scopes`` / ``## Rules`` do not."""
    return heading == required or heading.startswith(required + " ")


def _dg309_h2_section_bodies(text: str) -> list[tuple[str, str]]:
    """Return ``[(heading_line, body_text), ...]`` for each ``## `` (H2) section. Lines
    inside fenced code blocks (``` or ~~~) are body, never headings, so a ``## `` inside a
    fence cannot cause a false section split."""
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    fence_marker = ""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, ""
            if sections:
                sections[-1][1].append(line)
            continue
        if not in_fence and line.startswith("## "):
            sections.append((line.rstrip(), []))
        elif sections:
            sections[-1][1].append(line)
    return [(heading, "\n".join(body).strip()) for heading, body in sections]


@pytest.mark.parametrize("name", sorted(_DG309_REQUIRED_SECTIONS))
def test_required_invariant_sections_present(name: str) -> None:
    """Each named invariant carries its required ``## `` sections with a non-empty body
    (fleet-propagated template-repo#308 / #309 drift-guard). Guards against the silent
    loss of a propagated clause such as secrets-from-doppler.md's ``## Scope`` cross-repo
    boundary; present-but-empty also fails (an empty section is a silent-drift false-pass)."""
    path = _dg309_invariants_dir() / name
    assert path.is_file(), f"{name}: not found under {path.parent} (#308 guard)"
    sections = _dg309_h2_section_bodies(path.read_text(encoding="utf-8"))
    for required in _DG309_REQUIRED_SECTIONS[name]:
        match = next(((h, b) for h, b in sections if _dg309_heading_satisfies(h, required)), None)
        assert match is not None, (
            f"{name}: required section {required!r} is missing "
            "(template-repo#308 — do not drop propagated invariant sections)"
        )
        assert match[1], (
            f"{name}: required section {required!r} is present but its body is empty "
            "(an empty section is a silent-drift false-pass; #308)"
        )


def test_dg309_section_matcher_is_precise_and_fence_aware() -> None:
    """The matcher rejects pluralised prefix near-misses; the parser ignores ``## `` lines
    inside fenced code blocks (mirrors template-repo#309's own hardening test)."""
    assert _dg309_heading_satisfies("## Scope (cross-repo boundary)", "## Scope")
    assert _dg309_heading_satisfies("## Rule", "## Rule")
    assert not _dg309_heading_satisfies("## Scopes", "## Scope")
    assert not _dg309_heading_satisfies("## Rules", "## Rule")
    doc = (
        "# Invariant: x\n\n## Rule\n\nreal body\n\n"
        "```sh\n## not a heading inside a fence\n```\n\nstill rule body\n"
    )
    secs = _dg309_h2_section_bodies(doc)
    assert [h for h, _ in secs] == ["## Rule"], secs


# --- All-invariant frontmatter coverage (template-repo#311) ---------------------
# The module docstring claims every node under 00_System/invariants/ is frontmatter-
# validated, but the legacy parametrized check only covers a fixed REQUIRED_INVARIANTS
# set — extra on-disk nodes (e.g. session-boundary-hygiene.md) were never schema-checked.
# This self-contained, structure-agnostic check closes that gap: it globs every *.md node
# under the vault's invariants dir (except _index.md) and validates the frontmatter schema.
# Self-locating + Path-only so the same block runs in the template and every renamed child;
# graph-edge and ISO-date checks read PARSED frontmatter (not body substrings).
def _dg311_all_invariant_nodes() -> list[Path]:
    """Every on-disk invariant node across the (single) vault project. Globbed at
    collection time WITHOUT asserting, so a malformed/absent vault layout degrades to an
    empty parametrization rather than erroring the whole module at collection — the
    directory's existence is already asserted by the sibling structural tests."""
    vault_root = Path(__file__).resolve().parents[1] / "docs" / "01_Vault"
    return sorted(
        p for p in vault_root.glob("*/00_System/invariants/*.md") if p.name != "_index.md"
    )


def _dg311_read_frontmatter(path: Path) -> dict[str, str]:
    """Tiny top-level YAML frontmatter parser — no PyYAML dependency. Block-list keys
    (e.g. ``relates_to:`` followed by ``  - ...`` items) are captured as the key with an
    empty value, so ``"relates_to" in fm`` correctly detects the frontmatter key."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    out: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith((" ", "-")):
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"')
    return out


def _dg311_is_iso_date(value: str) -> bool:
    """True for a ``YYYY-MM-DD`` date (optionally with a trailing time component)."""
    parts = value.split("-")
    return (
        len(parts) == 3
        and len(parts[0]) == 4
        and parts[0].isdigit()
        and len(parts[1]) == 2
        and parts[1].isdigit()
        and len(parts[2]) >= 2
        and parts[2][:2].isdigit()
    )


@pytest.mark.parametrize("node", _dg311_all_invariant_nodes(), ids=lambda p: p.name)
def test_all_invariant_nodes_frontmatter_valid(node: Path) -> None:
    """EVERY on-disk invariant node (not only REQUIRED_INVARIANTS) carries valid frontmatter
    (template-repo#311): type, status, ISO created/updated, and a graph edge (part_of or
    relates_to) declared in PARSED FRONTMATTER — not merely mentioned in the body. Makes the
    module docstring's "every node" claim true and catches a malformed extra invariant."""
    fm = _dg311_read_frontmatter(node)
    assert fm.get("type") == "invariant", (
        f"{node.name}: type must be 'invariant', got {fm.get('type')!r}"
    )
    assert fm.get("status") in {"active", "draft", "superseded"}, (
        f"{node.name}: status must be active|draft|superseded, got {fm.get('status')!r}"
    )
    for field in ("created", "updated"):
        val = fm.get(field, "")
        assert val, f"{node.name}: missing {field!r}"
        assert _dg311_is_iso_date(val), (
            f"{node.name}: {field} must be an ISO date (YYYY-MM-DD), got {val!r}"
        )
    assert "part_of" in fm or "relates_to" in fm, (
        f"{node.name}: must declare part_of or relates_to in frontmatter (not just body text)"
    )
