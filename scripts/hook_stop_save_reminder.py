#!/usr/bin/env python3
"""Stop hook: deterministic SAVE reminder. Replaces the ``type: "agent"`` SAVE hook.

Issue #107 traced cloud-session stalls to two LLM-bearing hooks:
  * ``type: "prompt"`` flow-control guards (brown-out loops when the small-model
    classifier flaked — already addressed in PRs #91, #95, #103).
  * ``type: "agent"`` Stop hook that spawned a 120-second sub-agent on every
    session end. Under upstream brownouts the sub-agent itself hung,
    extending the user-visible "Claude is stopping…" window indefinitely.

This script is the deterministic replacement. It runs in well under a second,
inspects local repo signals only, and emits stdout text Claude Code surfaces
to the user. There is no model call.

Behavior:
  * Reads optional hook JSON on stdin (currently unused; future-proofed).
  * Repo root: optional ``argv[1]`` (the Stop hook shell passes ``$root``),
    else ``CLAUDE_PROJECT_DIR``, else ``cwd``.
  * If ``CLAUDE_DISABLE_STOP_SAVE_REMINDER`` is truthy → silent exit 0 after
    clearing ``.scratch/vault-dirty`` if present (matches the old unconditional
    ``rm`` hook; no stdout reminder when disabled).
  * If ``.scratch/vault-dirty`` exists in the repo root → print the
    vault-dirty reminder (handoff first, then full SAVE) and clear the marker.
  * **Memory contract SAVE audit (PR #115/B):** when ``.scratch/vault-dirty``
    is set and the SessionStart stamp is older than ~25 minutes (no query-time
    refresh yet — see issue #115 follow-up), print a one-line advisory and
    append to ``.scratch/memory_audit.jsonl``. **Advisory only** — Stop hooks
    must never block.
  * Otherwise → print the lightweight SAVE reminder (no marker = nothing
    obviously dirty, but the contract still asks the agent to SAVE).
  * Always exits 0. Stop hooks must never wedge the session.

Why stdout, not stderr:
  Claude Code surfaces Stop-hook stdout back into the next session preamble
  (per ``docs/00_Core/SESSION_LIFECYCLE.md``). Stderr is for blocking
  ``exit 2`` reasons, which Stop hooks must not produce.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path


def _repo_root() -> Path:
    """Resolve repo root: optional ``argv[1]`` from the hook wrapper, else env, else cwd."""
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg:
            return Path(arg).expanduser().resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _disabled() -> bool:
    val = os.environ.get("CLAUDE_DISABLE_STOP_SAVE_REMINDER", "").strip().lower()
    return val in ("1", "true", "yes", "on")


_VAULT_DIRTY_REMINDER = (
    "SAVE reminder: `.scratch/vault-dirty` is set — at minimum update "
    "`docs/01_Vault/ProjectTemplate/00_System/Next Session Handoff.md` "
    "(resume / shipped / remains / blockers) before closing. "
    "See `docs/00_Core/SESSION_LIFECYCLE.md` for the full SAVE checklist."
)

_PLAIN_REMINDER = (
    "SAVE reminder: see `docs/00_Core/SESSION_LIFECYCLE.md` — handoff, "
    "small vault linked nodes with relates_to, Current Focus if branch/PR "
    "changed, failure notes on abort. No vault-dirty marker so nothing is "
    "obviously stale; SAVE on real work only."
)


def _memory_audit(root: Path) -> str | None:
    """Return a one-line advisory when vault work is dirty but the Tier-3
    stamp was not refreshed (proxy until query-time refresh lands)."""
    scratch = root / ".scratch"
    lock_path = scratch / ".last_memory_query"
    if not lock_path.is_file():
        # No stamp → SessionStart prefetch did not run or this repo is
        # un-provisioned (gate already degrades to warn-only). Nothing to audit.
        return None
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    stamp_ts = data.get("timestamp_utc")
    if not isinstance(stamp_ts, str):
        return None
    try:
        when = datetime.fromisoformat(stamp_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.now(UTC)
    age_s = (now - when).total_seconds()
    # If the stamp is younger than ~5 min, treat it as "the session started
    # and immediately stopped" → nothing meaningful to audit.
    if age_s < 300:
        return None
    # Until query-time stamp refresh exists, only nudge when vault-dirty is set
    # (real SAVE obligation) and the session ran long enough to matter.
    if not (scratch / "vault-dirty").is_file() or age_s < 1500:
        return None
    workspace = data.get("workspace") or "(unknown)"
    return (
        "memory-audit advisory: `.scratch/vault-dirty` is set but the Tier-3 "
        f"stamp was not refreshed this session (last stamp {int(age_s)}s ago, "
        f"workspace={workspace}). Complete SAVE + substrate handoff per "
        "`docs/00_Core/MEMORY_CONTRACT.md`."
    )


def _append_audit_record(root: Path, advisory: str | None) -> None:
    """Best-effort append to ``.scratch/memory_audit.jsonl`` for later mining."""
    scratch = root / ".scratch"
    try:
        scratch.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    record = {
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "advisory": advisory,
        "vault_dirty": (scratch / "vault-dirty").exists(),
    }
    try:
        with (scratch / "memory_audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        return


def main() -> int:
    # Drain stdin defensively so we don't leave the parent shell wedged on a
    # blocked pipe — including when the kill-switch skips all output below.
    # Payload is currently unused.
    try:
        sys.stdin.read()
    except Exception:  # noqa: BLE001
        pass

    root = _repo_root()
    marker = root / ".scratch" / "vault-dirty"

    if _disabled():
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                pass
        return 0

    advisory = _memory_audit(root)
    _append_audit_record(root, advisory)

    if marker.exists():
        sys.stdout.write(_VAULT_DIRTY_REMINDER + "\n")
        if advisory:
            sys.stdout.write(advisory + "\n")
        # Clear the marker now that we have surfaced the reminder.
        try:
            marker.unlink()
        except OSError:
            pass
        return 0

    sys.stdout.write(_PLAIN_REMINDER + "\n")
    if advisory:
        sys.stdout.write(advisory + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — Stop hooks must never block
        sys.exit(0)
