"""Tests that every `.claude/agents/*.md` agent procedure embeds Tier-3 memory
consultation as a **first-class workflow step**, not as an appendix footer.

Operator demand 2026-05-17 (post-#116): the substrate (lockfile, gate, drift
audit) is enforcement infrastructure, but agents reading the .md files
top-to-bottom internalize the procedure BEFORE reaching the memory-contract
footer. The fix is to interleave Tier-3 consultation into the procedure itself
— specifically, every agent file must contain:

  1. A top-level ``## Tier-3 Substrate Query (mandatory first step)`` section
     placed BEFORE the first procedural section (Routing, Non-negotiables,
     Session lifecycle, Inputs, etc.).
  2. The literal MCP tool name ``mcp__agentic-memory__query_knowledge_graph``
     in that section, so the agent has a concrete call template, not an
     abstract instruction.
  3. The Non-negotiable #1 OR Session-lifecycle LOAD step explicitly
     references the Tier-3 section above (interleaved, not duplicated).
  4. The marker-delimited memory-contract footer is **short** (stub form;
     full rules live in-procedure now) — empirically the rendered block
     should be under 30 lines.

These tests run cheaply and protect the structural assumption above. They
will fail loudly if an agent file regresses to the old "appendix only"
shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

REQUIRED_AGENTS = {
    "issue-driven-coding-orchestrator.md",
    "pr-resolution-follow-up.md",
    "post-merge-steward.md",
    "dependency-review.md",
    "learner.md",
}

TIER3_SECTION_HEADING = "## Tier-3 Substrate Query (mandatory first step)"
MCP_CALL_LITERAL = "mcp__agentic-memory__query_knowledge_graph"
MARKER_START = "<!-- memory-contract:start -->"
MARKER_END = "<!-- memory-contract:end -->"


def test_all_required_agent_files_present() -> None:
    on_disk = {p.name for p in AGENTS_DIR.glob("*.md")}
    missing = REQUIRED_AGENTS - on_disk
    assert not missing, (
        f"required agent .md files missing: {sorted(missing)}. "
        f"Agent procedure uplift (post-#116) requires all 5 named agents."
    )


@pytest.mark.parametrize("name", sorted(REQUIRED_AGENTS))
def test_agent_has_tier3_section(name: str) -> None:
    """Every agent .md must open with the Tier-3 Substrate Query section."""
    text = (AGENTS_DIR / name).read_text(encoding="utf-8")
    assert TIER3_SECTION_HEADING in text, (
        f"{name}: missing '{TIER3_SECTION_HEADING}' section. "
        f"The post-#116 procedure uplift requires Tier-3 query as a "
        f"first-class workflow step, not as an appendix footer."
    )


@pytest.mark.parametrize("name", sorted(REQUIRED_AGENTS))
def test_tier3_section_contains_mcp_call(name: str) -> None:
    """The Tier-3 section must name the literal MCP tool — concrete call
    template, not abstract instruction."""
    text = (AGENTS_DIR / name).read_text(encoding="utf-8")
    start = text.find(TIER3_SECTION_HEADING)
    assert start >= 0, f"{name}: Tier-3 section missing"
    next_section = text.find("\n## ", start + len(TIER3_SECTION_HEADING))
    section = text[start : next_section if next_section >= 0 else len(text)]
    assert MCP_CALL_LITERAL in section, (
        f"{name}: Tier-3 section must reference '{MCP_CALL_LITERAL}' literally "
        f"so the agent has a concrete call template."
    )


@pytest.mark.parametrize("name", sorted(REQUIRED_AGENTS))
def test_tier3_section_precedes_first_procedural_section(name: str) -> None:
    """The Tier-3 section must come BEFORE the first procedural section."""
    text = (AGENTS_DIR / name).read_text(encoding="utf-8")
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
                f"{name}: '{TIER3_SECTION_HEADING}' (pos {tier3_pos}) must come "
                f"BEFORE '{heading}' (pos {pos}). Otherwise the agent reads the "
                f"procedure first and the Tier-3 step is an afterthought."
            )


@pytest.mark.parametrize("name", sorted(REQUIRED_AGENTS))
def test_memory_contract_footer_is_short_pointer(name: str) -> None:
    """The marker-delimited footer block must be a SHORT pointer (under 30
    non-blank lines), not the full duplicated tier table."""
    text = (AGENTS_DIR / name).read_text(encoding="utf-8")
    start = text.find(MARKER_START)
    end = text.find(MARKER_END)
    assert start >= 0 and end > start, f"{name}: marker block missing"
    block = text[start : end + len(MARKER_END)]
    block_lines = [line for line in block.splitlines() if line.strip()]
    assert len(block_lines) < 30, (
        f"{name}: memory-contract footer is {len(block_lines)} non-blank "
        f"lines — should be a short pointer stub (<30 lines). Re-render via "
        f"`python3 scripts/merge_memory_contract.py`."
    )


def test_agents_md_top_pointer_present() -> None:
    """AGENTS.md top must summarize the memory-first principle."""
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
