"""Drift-guard: deprecated Stop-hooks must not be described as CURRENT enforcement in any LIVE
agent-facing instruction surface (agent-factory#350 falsification audit, Council-decided).

The advisory Stop-hooks hook_stop_save_reminder.py / hook_stop_drift_audit.py were REMOVED in the
slim-down sweep (issue #205). A fresh agent reads these files as current operating guidance, so a
stale 'enforced by ... hook_stop_save_reminder.py' line teaches it the deleted system. This test
FAILS if a deprecated hook name appears in a live surface WITHOUT an adjacent removal marker.

Vault ADRs / postmortems (docs/01_Vault/**) are HISTORICAL records and are intentionally NOT
scanned — they correctly describe the old hooks as history.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEPRECATED = ("hook_stop_save_reminder", "hook_stop_drift_audit")
# A mention is OK only if the same line marks it as removed/historical.
REMOVAL_MARKER = re.compile(
    r"REMOVED|DELETED|deleted|removed|slim-down|deprecated|no longer|were\s+removed", re.IGNORECASE
)

LIVE_SURFACES = [
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "README.md",
    "CONTRIBUTING.md",
    "docs/00_Core/MEMORY_CONTRACT.md",
    "docs/00_Core/HOOK_DESIGN.md",
    "docs/00_Core/SESSION_LIFECYCLE.md",
    "scripts/INVENTORY.md",
]


def test_no_deprecated_stophook_as_current_in_live_surfaces() -> None:
    offenders: list[str] = []
    for rel in LIVE_SURFACES:
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if any(dep in line for dep in DEPRECATED) and not REMOVAL_MARKER.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:120]}")
    assert not offenders, (
        "Deprecated Stop-hooks described as CURRENT in live instruction surfaces "
        "(they were REMOVED, issue #205) — a fresh agent would be taught the old system:\n  - "
        + "\n  - ".join(offenders)
    )
