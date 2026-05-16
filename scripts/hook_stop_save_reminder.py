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
  * Otherwise → print the lightweight SAVE reminder (no marker = nothing
    obviously dirty, but the contract still asks the agent to SAVE).
  * Always exits 0. Stop hooks must never wedge the session.

Why stdout, not stderr:
  Claude Code surfaces Stop-hook stdout back into the next session preamble
  (per ``docs/00_Core/SESSION_LIFECYCLE.md``). Stderr is for blocking
  ``exit 2`` reasons, which Stop hooks must not produce.
"""

from __future__ import annotations

import os
import sys
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
    "`docs/01_Vault/AcCopilotTrainer/00_System/Next Session Handoff.md` "
    "(resume / shipped / remains / blockers) before closing. "
    "See `docs/00_Core/SESSION_LIFECYCLE.md` for the full SAVE checklist."
)

_PLAIN_REMINDER = (
    "SAVE reminder: see `docs/00_Core/SESSION_LIFECYCLE.md` — handoff, "
    "small vault linked nodes with relates_to, Current Focus if branch/PR "
    "changed, failure notes on abort. No vault-dirty marker so nothing is "
    "obviously stale; SAVE on real work only."
)


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

    if marker.exists():
        sys.stdout.write(_VAULT_DIRTY_REMINDER + "\n")
        # Clear the marker now that we have surfaced the reminder.
        try:
            marker.unlink()
        except OSError:
            pass
        return 0

    sys.stdout.write(_PLAIN_REMINDER + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — Stop hooks must never block
        sys.exit(0)
