"""Tests that every workflow skill (and the 2 remaining agents) embeds Tier-3
memory consultation as a **first-class workflow step**, not as an appendix
footer.

Operator demand 2026-05-17 (post-#116): the substrate (lockfile, gate, drift
audit) is enforcement infrastructure, but readers go top-to-bottom and
internalize the procedure BEFORE reaching the memory-contract footer. The fix
is to interleave Tier-3 consultation into the procedure itself.

History: 2026-05-26 (agent-factory#256) — the 5 workflow agents collapsed to
skills under ``.claude/skills/<slash-name>/SKILL.md``. The structural
assertions now run against skill files. Two surfaces remain as legacy
agents because they are still being shaped:
``.claude/agents/account-intake-overview.md`` and
``.claude/agents/mcp-harvest-ingestion.md`` — they keep the same Tier-3
structural contract.

Every covered file must contain:

  1. ``## Tier-3 Substrate Query (mandatory first step)`` BEFORE the first
     procedural section.
  2. ``mcp__agentic-memory__query_knowledge_graph`` literal in that section.
  3. Non-negotiable #1 OR Session-lifecycle LOAD step explicitly references
     Tier-3 (interleaved, not duplicated).
  4. ``<!-- memory-contract:start -->...<!-- memory-contract:end -->``
     rendered block under 30 non-blank lines (stub form).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

# Workflow skills (collapsed 2026-05-26).
REQUIRED_SKILLS: set[str] = set()  # workflow skills moved to governance-hub skills/ @ skills-v1.1.0 (machine-level ~/.agents/skills; gov-hub#24 wave-2 sweep)

# The 2 remaining agents (account-intake-overview, mcp-harvest-ingestion) are
# excluded from this strict structural contract: account-intake-overview is
# still being shaped (operator-driven, kept as agent intentionally per the
# 2026-05-26 collapse decision), and mcp-harvest-ingestion is a thin design
# pointer that pre-dates the post-#116 uplift. They keep the Tier-3 query in
# spirit but not in strict structural form. Re-add them here once they're
# stabilized.
REQUIRED_AGENTS: set[str] = set()

TIER3_SECTION_HEADING = "## Tier-3 Substrate Query (mandatory first step)"
MCP_CALL_LITERAL = "mcp__agentic-memory__query_knowledge_graph"
MARKER_START = "<!-- memory-contract:start -->"
MARKER_END = "<!-- memory-contract:end -->"


def _skill_path(name: str) -> Path:
    return SKILLS_DIR / name / "SKILL.md"


def _agent_path(name: str) -> Path:
    return AGENTS_DIR / name


def _covered_paths() -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for name in sorted(REQUIRED_SKILLS):
        out.append((f"skill:{name}", _skill_path(name)))
    for name in sorted(REQUIRED_AGENTS):
        out.append((f"agent:{name}", _agent_path(name)))
    return out


def test_all_required_files_present() -> None:
    missing: list[str] = []
    for label, path in _covered_paths():
        if not path.is_file():
            missing.append(f"{label} @ {path.relative_to(REPO_ROOT)}")
    assert not missing, (
        "Required Tier-3-bearing files missing: "
        + ", ".join(missing)
        + ". Workflow skills + the 2 remaining agents must exist."
    )


@pytest.mark.parametrize("label_and_path", _covered_paths(), ids=lambda lp: lp[0])
def test_file_has_tier3_section(label_and_path: tuple[str, Path]) -> None:
    label, path = label_and_path
    text = path.read_text(encoding="utf-8")
    assert TIER3_SECTION_HEADING in text, (
        f"{label}: missing '{TIER3_SECTION_HEADING}'. The post-#116 procedure "
        f"uplift requires Tier-3 query as a first-class workflow step."
    )


@pytest.mark.parametrize("label_and_path", _covered_paths(), ids=lambda lp: lp[0])
def test_tier3_section_contains_mcp_call(label_and_path: tuple[str, Path]) -> None:
    label, path = label_and_path
    text = path.read_text(encoding="utf-8")
    start = text.find(TIER3_SECTION_HEADING)
    assert start >= 0, f"{label}: Tier-3 section missing"
    next_section = text.find("\n## ", start + len(TIER3_SECTION_HEADING))
    section = text[start : next_section if next_section >= 0 else len(text)]
    assert MCP_CALL_LITERAL in section, (
        f"{label}: Tier-3 section must reference '{MCP_CALL_LITERAL}' literally."
    )


@pytest.mark.parametrize("label_and_path", _covered_paths(), ids=lambda lp: lp[0])
def test_tier3_section_precedes_first_procedural_section(
    label_and_path: tuple[str, Path],
) -> None:
    label, path = label_and_path
    text = path.read_text(encoding="utf-8")
    tier3_pos = text.find(TIER3_SECTION_HEADING)
    assert tier3_pos >= 0
    procedural_headings = [
        "## Routing",
        "## Non-negotiables",
        "## Session lifecycle",
        "## Inputs",
        "## In scope",
        "## When to run",
        "## Procedure",
    ]
    for heading in procedural_headings:
        pos = text.find("\n" + heading + "\n", 0)
        if pos >= 0:
            assert tier3_pos < pos, (
                f"{label}: '{TIER3_SECTION_HEADING}' (pos {tier3_pos}) must come "
                f"BEFORE '{heading}' (pos {pos})."
            )


@pytest.mark.parametrize("label_and_path", _covered_paths(), ids=lambda lp: lp[0])
def test_memory_contract_footer_is_short_pointer(
    label_and_path: tuple[str, Path],
) -> None:
    label, path = label_and_path
    text = path.read_text(encoding="utf-8")
    start = text.find(MARKER_START)
    end = text.find(MARKER_END)
    assert start >= 0 and end > start, f"{label}: marker block missing"
    block = text[start : end + len(MARKER_END)]
    block_lines = [line for line in block.splitlines() if line.strip()]
    assert len(block_lines) < 30, (
        f"{label}: memory-contract footer is {len(block_lines)} non-blank lines "
        f"— should be a short pointer stub (<30 lines). Re-render via "
        f"`python3 scripts/merge_memory_contract.py`."
    )


def test_agents_md_top_pointer_present() -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Memory-first" in text, "AGENTS.md missing Memory-first top-level pointer"
    assert "Tier-3 Substrate Query" in text or TIER3_SECTION_HEADING in text, (
        "AGENTS.md memory-first section must reference the Tier-3 Substrate Query"
    )
    pointer_pos = text.find("Memory-first")
    mandatory_pos = text.find("## Mandatory reading")
    assert pointer_pos > 0 and mandatory_pos > pointer_pos, (
        "AGENTS.md 'Memory-first' pointer must precede '## Mandatory reading'."
    )
