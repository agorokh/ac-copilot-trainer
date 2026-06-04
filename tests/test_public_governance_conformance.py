"""Self-contained PUBLIC governance conformance (agent-factory#350, Council-decided).

This is a PUBLIC repo: it cannot consume the PRIVATE governance-hub composite action the 14
private governed repos use. This checker proves the two things that matter for first-try
correctness, with NO private-hub dependency and NO vendored hub logic:

  1. SHIM INTEGRITY — every governed hook shim that is PRESENT is byte-identical to the pinned
     canonical shim hash below (absent = ok; a repo need not carry all 7). A tampered/neutered
     shim (e.g. `exit 0`) fails the pin. Pinning a KNOWN-GOOD hash (not "identical to each other")
     is deliberate: byte-identical-to-each-other would pass even if all shims were corrupted in
     lockstep; the pin catches that.
  2. HARNESS WIRING — each tracked harness config (.claude / .cursor / .codex) wires the
     deterministic memory gate on PreToolUse, so a FRESH CLONE in that harness loads the gate
     BEFORE the agent edits.

It does NOT execute the gate (that needs the private hub at runtime) — config + cryptographic
identity is the Council-ratified sufficient floor for a public repo.

PIN MAINTENANCE: update CANONICAL_SHIM_SHA256 only when the hub `wrappers/governance_shim.py`
legitimately changes (the 14 private repos are byte-identity-gated against the same shim by the
hub action). The value is a PUBLIC file hash, not a credential.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_SHIM_SHA256 = (
    "d28fab569a94f943c5c0c49178d9fd4cadcfa37550222cabf7cc2fa40f92d71c"  # pragma: allowlist secret
)
GOVERNED_SHIMS = (
    "hook_session_start_memory_prefetch.py",
    "hook_memory_gate.py",
    "hook_protect_main_impl.py",
    "hook_block_git_stash.py",
    "hook_memory_query_stamp.py",
    "hook_stale_main_gate.py",
    "hook_session_start_post_merge_steward.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_present_governed_shims_match_pinned_hash() -> None:
    """Any governed shim present must equal the pinned canonical shim hash (absent = ok)."""
    pin = CANONICAL_SHIM_SHA256[:16]
    drift = []
    for name in GOVERNED_SHIMS:
        f = REPO_ROOT / "scripts" / name
        if f.is_file() and _sha256(f) != CANONICAL_SHIM_SHA256:
            drift.append(f"{name}: {_sha256(f)[:16]} != pinned {pin} (tampered)")
    assert not drift, "governed shim drift from pinned canonical shim:\n  - " + "\n  - ".join(drift)


def _wires_gate(path: Path) -> bool:
    return path.is_file() and "hook_memory_gate" in path.read_text(encoding="utf-8")


def test_claude_settings_wire_memory_gate() -> None:
    p = REPO_ROOT / ".claude" / "settings.json"
    assert p.is_file(), "missing .claude/settings.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    blob = json.dumps(data.get("hooks", {}).get("PreToolUse", []))
    assert "hook_memory_gate" in blob, "PreToolUse must wire hook_memory_gate (first-try gate)"


def test_tracked_harness_configs_present_and_wire_gate() -> None:
    """Required harness configs must be TRACKED (present) AND wire the memory gate, so a fresh clone
    in that harness gets the first-try gate. Asserting presence (not `if present`) means DELETING a
    harness config is caught — not just mutation (agent-factory#350 falsification: closes the
    deletion blind spot)."""
    for rel in (".cursor/hooks.json", ".codex/hooks.json"):
        p = REPO_ROOT / rel
        assert p.is_file(), (
            f"{rel} missing — fresh-clone agents in that harness would build blind (first-try gap)"
        )
        assert _wires_gate(p), f"{rel} present but does not wire hook_memory_gate"
