#!/usr/bin/env python3
"""Generic governance shim — reference, don't vendor.

This file is installed into a spoke repo's ``scripts/<hook_name>.py`` IN PLACE of
the vendored hook logic. It carries NO guard logic itself: it resolves the
canonical implementation in the fleet governance hub (by its own filename) and
delegates, running it with the spoke repo as ``CLAUDE_PROJECT_DIR``. A fix lands
ONCE in the hub and every spoke picks it up; security scanners see one copy.

Resolution order for the hub (TRUSTED, configured locations only):
  1. ``$FLEET_GOVERNANCE_ROOT`` (explicit operator config)
  2. ``~/.fleet-governance`` (host-level canonical clone)

SECURITY (2026-06-03 Cloud Security scan): the previous ``../agent-factory``
sibling-directory fallback was REMOVED. ``runpy``-executing a hook resolved by
directory-layout convention let any code dropped at a sibling path run as the
governance hook on every tool call (untrusted-code execution). The shim now only
executes canonical implementations from a configured, trusted root.

Fail posture (Council 2026-06-03, ADR adr-2026-06-02 + adr-2026-06-03; degraded-mode
hardening Council 2026-06-03 round-3):

  Hub MISSING:
    * HARD gates (``hook_memory_gate.py``, ``hook_protect_main_impl.py``) fail CLOSED — exit 2 —
      EXCEPT a tiny, fixed, anchored RECOVERY allowlist (clone the hub + read-only navigation) so the
      documented one-step recovery is actually reachable on a fresh host. Every recovery hit is
      audited.
    * ADVISORY hooks (prefetch, block-git-stash, …) fail OPEN — exit 0.

  Hub PRESENT but the canonical hook ERRORS at runtime (uncaught exception during delegation):
    * HARD gates fail CLOSED — exit 2 + audit (the security boundary must not silently drop on a bug).
    * ADVISORY hooks fail OPEN — exit 0 + audit (restoring the vendored ``except Exception: exit(0)``
      contract; a bad central advisory hook must never brick benign commands).

Break-glass: ``EMERGENCY_BYPASS_GOVERNANCE=1`` makes EVERY governance hook exit 0 (allow / skip).
Human-only escape for the "global brick" — a bad central hook must never block the humans who need to
fix it. Use is loud (stderr) and auditable.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import runpy
import sys
from pathlib import Path

# Hooks that MUST fail closed (block) when the canonical implementation is absent or errors.
# These are the hard gates; everything else is advisory and fails open.
_FAIL_CLOSED_HOOKS = frozenset(
    {
        "hook_memory_gate.py",
        "hook_protect_main_impl.py",
    }
)

# RECOVERY allowlist for the hub-MISSING hard-gate branch (Council 2026-06-03 round-3). EXACT,
# anchored matches only — NO substring matching, NO shell metacharacters, NO chaining/redirection,
# NO alternate destination or env-controlled URL. The sole purpose is to let an agent/operator
# install the hub (the "bootloader" for governance itself) and look around; everything else still
# fails closed. Every match is audited.
_RECOVERY_PATTERNS: tuple[re.Pattern[str], ...] = (
    # git clone of the EXACT governance-hub URL into the canonical destination.
    re.compile(
        r"^git\s+clone\s+https://github\.com/agorokh/governance-hub(?:\.git)?"
        r"\s+(?:~|\$HOME)/\.fleet-governance/?$"
    ),
    # Read-only navigation / inspection with no metacharacters (no | & ; < > ` $ ( ) newline).
    re.compile(r"^(?:pwd|ls|cd|echo|cat|git status|git --version)(?:[ \t]+[^|&;<>`$()\n]*)?$"),
)


def _canonical(name: str) -> Path | None:
    """Resolve the canonical hook from a TRUSTED, configured location only."""
    here = Path(__file__).resolve()
    bases: list[Path] = []
    env_root = os.environ.get("FLEET_GOVERNANCE_ROOT", "").strip()
    if env_root:
        bases.append(Path(env_root).expanduser())
    bases.append(Path.home() / ".fleet-governance")
    for base in bases:
        for sub in ("hooks", "scripts"):  # hub layout, then legacy layout
            p = base / sub / name
            if p.is_file() and p.resolve() != here:
                return p
    return None


def _audit(event: str, name: str, reason: str) -> None:
    """Best-effort append to the governance audit log + stderr. Self-contained (the hub may be
    absent, which is exactly when this fires), so it cannot import hub modules."""
    sys.stderr.write(f"AUDIT[governance-shim] {event}: {name} — {reason}\n")
    try:
        env = os.environ.get("FLEET_GOVERNANCE_AUDIT_LOG", "").strip()
        if env:
            path = Path(env).expanduser()
        elif sys.platform == "darwin":
            path = (
                Path.home()
                / "Library"
                / "Application Support"
                / "fleet-governance"
                / "overrides.jsonl"
            )
        else:
            xdg = os.environ.get("XDG_STATE_HOME")
            base = Path(xdg) if xdg else Path.home() / ".local" / "state"
            path = base / "fleet-governance" / "overrides.jsonl"
        if str(path) == os.devnull:
            return
        entry = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "guard": "governance-shim",
            "action": event,
            "hook": name,
            "reason": reason,
            "repo": os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
            "session": os.environ.get("CLAUDE_SESSION_ID", ""),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # audit is best-effort; never crash the shim on a write error


def _recovery_command_from_stdin() -> str | None:
    """Return the Bash command from the PreToolUse payload IFF it matches the recovery allowlist.

    Only called in the hub-MISSING hard-gate branch, where there is no delegation — so consuming
    stdin here cannot starve a downstream hook. Returns None when stdin is not a Bash payload, is
    unreadable, or the command is not an exact recovery command."""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return None
    cmd = command.strip()
    for pattern in _RECOVERY_PATTERNS:
        if pattern.match(cmd):
            return cmd
    return None


def _delegate(canonical: Path, name: str) -> None:
    """Run the canonical hook. Propagate its intended exit code (SystemExit). On a NON-SystemExit
    runtime error (hub present but the hook is buggy/incompatible), restore the fail posture:
    HARD gates fail closed (exit 2), ADVISORY hooks fail open (exit 0). Always audited — never a
    silent bypass, never a silent block."""
    try:
        runpy.run_path(str(canonical), run_name="__main__")
    except SystemExit:
        raise  # the hook's own exit code (0 allow / 2 block) is authoritative.
    except Exception as exc:  # noqa: BLE001 — degraded-mode contract below.
        detail = f"{type(exc).__name__}: {exc}"
        if name in _FAIL_CLOSED_HOOKS:
            _audit("hub-runtime-error-failclosed", name, detail)
            sys.stderr.write(
                f"BLOCK: governance-shim — canonical {name} errored at runtime; failing CLOSED "
                "(hard gate). Fix the hub hook or use EMERGENCY_BYPASS_GOVERNANCE=1.\n"
            )
            sys.exit(2)
        _audit("hub-runtime-error-failopen", name, detail)
        sys.stderr.write(
            f"governance-shim: canonical {name} errored at runtime (advisory hook); fail-open.\n"
        )
        sys.exit(0)


def _run() -> None:
    """Delegate to the canonical hook. Guarded by ``__main__`` so IMPORTING this shim
    (e.g. a test that imports the spoke's ``scripts/<hook>.py``) does NOT execute the
    delegation or call ``sys.exit`` — only running it as the hook does."""
    name = Path(__file__).name
    if os.environ.get("EMERGENCY_BYPASS_GOVERNANCE", "").strip() == "1":
        _audit("emergency-bypass", name, "EMERGENCY_BYPASS_GOVERNANCE=1 (human break-glass)")
        sys.exit(0)
    canonical = _canonical(name)
    if canonical is not None:
        _delegate(canonical, name)
        return
    # Hub not found.
    if name in _FAIL_CLOSED_HOOKS:
        recovery = _recovery_command_from_stdin()
        if recovery is not None:
            # The bootloader exception: permit the small, fixed surface needed to INSTALL the hub so
            # the documented recovery is reachable on a fresh host. Audited; everything else blocks.
            _audit("recovery-allowed", name, f"hub missing; recovery command permitted: {recovery}")
            return  # exit 0 (allow the recovery command to run)
        _audit("fail-closed-block", name, "governance hub not found (hard gate)")
        sys.stderr.write(
            f"BLOCK: governance-shim — canonical {name} not found; failing CLOSED (hard gate).\n"
            "  Expected the hub at $FLEET_GOVERNANCE_ROOT or ~/.fleet-governance.\n"
            "  Recover:  git clone https://github.com/agorokh/governance-hub ~/.fleet-governance\n"
            "            (this exact command is allow-listed even while the gate is failing closed)\n"
            "  Break-glass (human only): EMERGENCY_BYPASS_GOVERNANCE=1 <your command>\n"
        )
        sys.exit(2)
    # Advisory hook: fail open so a missing hub never bricks a session.
    sys.stderr.write(
        f"governance-shim: canonical {name} not found (advisory hook); fail-open. "
        "Clone the hub to ~/.fleet-governance to restore it.\n"
    )
    sys.exit(0)


if __name__ == "__main__":
    _run()
