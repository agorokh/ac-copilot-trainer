"""Stale-reference drift guard (EXTENDED scope) — agent-factory#350 instruction-coherence audit.

Deprecated mechanisms (the removed advisory Stop-hooks `hook_stop_save_reminder` /
`hook_stop_drift_audit`, committed `.governance-vendored-bak`) must NOT be described as CURRENT in
any LIVE agent-facing surface. A fresh autonomous agent reads these as active guidance, so a stale
"verify this hook is wired" line teaches it the deleted system (and it tries to restore it).

This is the EXTENDED guard: the original covered ~6 files (CLAUDE / AGENTS / MEMORY_CONTRACT /
HOOK_DESIGN / SESSION_LIFECYCLE / INVENTORY) and missed MAINTAINING_THE_TEMPLATE.md, vault docs,
`.claude/agents/**`, `.claude/skills/**`, `.claude/rules/**` — which is how the R3 stale verify-
checklist survived. Scope is widened here.

A mention PASSES only if the SAME line carries a removal/superseded marker (or strikethrough), per
the Council ruling that historical records are fine but current-tense instructions are not.
HISTORICAL trees (`01_Decisions/` ADRs, `02_Investigations/`) are excluded — they legitimately
narrate removed mechanisms.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEPRECATED = ("hook_stop_save_reminder", "hook_stop_drift_audit", "governance-vendored-bak")
REMOVAL_MARKER = re.compile(
    r"REMOV|DELET|deleted|removed|slim-down|deprecat|no longer|were\s+removed|SUPERSED|superseded|"
    r"DO NOT RESTORE|~~",
    re.IGNORECASE,
)

# Globs for LIVE agent-facing surfaces. Historical trees are excluded below.
LIVE_GLOBS = (
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "README.md",
    "CONTRIBUTING.md",
    "AGENT_CORE_PRINCIPLES.md",
    "AGENT_PRINCIPLES.md",
    "MEMORY.md",
    "docs/00_Core/*.md",
    "docs/01_Vault/*/00_System/*.md",
    "docs/01_Vault/*/00_System/invariants/*.md",
    "docs/01_Vault/*/pitfalls/*.md",
    ".claude/agents/*.md",
    ".claude/skills/*/SKILL.md",
    ".claude/rules/*.md",
    "scripts/INVENTORY.md",
)
# Substrings that mark a path as HISTORICAL (legitimately narrates removed mechanisms) -> skip.
HISTORICAL = ("/01_Decisions/", "/02_Investigations/", "INSTRUCTION_SURFACE_PRECEDENCE.md")


def _live_files():
    seen = set()
    for g in LIVE_GLOBS:
        for p in REPO_ROOT.glob(g):
            if p.is_file() and not any(h in p.as_posix() for h in HISTORICAL):
                seen.add(p)
    return sorted(seen)


def _scan(text: str) -> list[int]:
    """Return 1-based line numbers describing a deprecated mechanism as CURRENT (no removal marker)."""  # noqa: E501
    bad = []
    for i, line in enumerate(text.splitlines(), 1):
        if any(d in line for d in DEPRECATED) and not REMOVAL_MARKER.search(line):
            bad.append(i)
    return bad


def test_no_deprecated_mechanism_as_current_in_live_surfaces() -> None:
    offenders = []
    for p in _live_files():
        for ln in _scan(p.read_text(encoding="utf-8")):
            rel = p.relative_to(REPO_ROOT)
            offenders.append(f"{rel}:{ln}")
    assert not offenders, (
        "Deprecated mechanisms described as CURRENT in live instruction surfaces (they were REMOVED, "  # noqa: E501
        "issue #205) — a fresh agent would be taught the old system / try to restore it. Add a removal "  # noqa: E501
        "marker (REMOVED/SUPERSEDED/~~strike~~ + 'DO NOT RESTORE') or delete the line:\n  - "
        + "\n  - ".join(offenders)
    )


# --- negative control: prove the scanner FAILS on a stale claim and PASSES when marked superseded ---  # noqa: E501
def test_negative_control_scanner_flags_current_and_allows_superseded() -> None:
    current = "Verification checklist: grep hook_stop_drift_audit.py .claude/settings.base.json returns a hit."  # noqa: E501
    assert _scan(current), "scanner MUST flag a current-tense stale reference"
    superseded = "~~grep hook_stop_drift_audit.py~~ SUPERSEDED by #205 — DO NOT RESTORE."
    assert not _scan(superseded), (
        "scanner MUST allow a superseded/struck reference (no false positive)"
    )
