#!/usr/bin/env python3
"""Generic governance shim — reference, don't vendor.

This file is installed into a spoke repo's ``scripts/<hook_name>.py`` IN PLACE of
the vendored hook logic. It carries NO guard logic itself: it resolves the
canonical implementation in the fleet governance hub (by its own filename) and
delegates. Before any non-break-glass audit or ``runpy`` delegation it establishes
``CLAUDE_PROJECT_DIR`` as the spoke repository root derived from *this* installed
shim path, unless a trusted harness already supplied a non-empty
``CLAUDE_PROJECT_DIR`` (sandbox / worktree) — that explicit value remains
authoritative (#268). Break-glass attempts the same binding on a best-effort basis,
but an attribution failure cannot block the human escape. A fix lands ONCE in the
hub and every spoke picks it up; security scanners see one copy.

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

# Hooks whose fail posture is CONDITIONAL on an armed env toggle (gov-hub#418, agent-factory#1736
# round-1 Codex P1): the write-lock gate is advisory while report-only, but once the operator arms
# WRITE_LOCK_ENFORCE the staged enforcement must not silently vanish on hub drift or a runtime
# error — an armed gate that fails open is the exact "enforcement theater" failure mode.
# Entries: hook name -> (enforce env key, accepted armed values, disable env key). The posture is
# EFFECTIVE arming, not mere presence (round-5 Codex P2): `WRITE_LOCK_ENFORCE=0`/`off`/a typo does
# not arm the hook, so it must not fail closed either, and the hook's advertised operator bypass
# (`WRITE_LOCK_DISABLE`, any non-empty value) disarms the posture entirely.
_ENV_CONDITIONAL_FAIL_CLOSED = {
    "hook_write_lock.py": ("WRITE_LOCK_ENFORCE", ("issue", "repo"), "WRITE_LOCK_DISABLE"),
}


def _argv_declared_event() -> str:
    """The hook event declared on argv (``--event <name>`` / ``--event=<name>``), or ""."""
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--event" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--event="):
            return arg.split("=", 1)[1]
    return ""


def _conditional_armed(name: str) -> bool:
    """Whether this hook's env-conditional posture is EFFECTIVELY armed (event-agnostic)."""
    entry = _ENV_CONDITIONAL_FAIL_CLOSED.get(name)
    if not entry:
        return False
    enforce_key, armed_values, disable_key = entry
    if os.environ.get(disable_key, "") != "":
        return False
    return os.environ.get(enforce_key, "").strip().lower() in armed_values


def _fails_closed(name: str, payload_event: str = "") -> bool:
    """Posture for the runtime-error and hub-missing branches. A declared non-write event
    (SessionStart report, etc.) inspects no mutation and stays advisory even while armed
    (gov-hub#419 rounds 15-16): the event comes from argv when declared, else from the payload
    when the caller could safely read it (hub-missing branch only — no delegation follows)."""
    if name in _FAIL_CLOSED_HOOKS:
        return True
    if not _conditional_armed(name):
        return False
    event = _argv_declared_event() or payload_event
    return event in ("", "PreToolUse")


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
        try:
            bases.append(Path(env_root).expanduser())
        except RuntimeError:
            # expanduser() raises RuntimeError when env_root begins with ``~`` and no home
            # directory is resolvable (minimal containers / some CI runners) — the SAME failure
            # the Path.home() call below guards; this env-root branch was the asymmetric gap
            # (governance-hub#213, same class as the #208 WI-shim fix). Fall back to the literal
            # path: an unexpandable ``~`` prefix simply fails the ``.is_absolute()`` probe below
            # (candidate skipped, then fail-closed/open per posture), while an absolute env_root —
            # which never raises — is preserved unchanged.
            bases.append(Path(env_root))
    try:
        bases.append(Path.home() / ".fleet-governance")
    except RuntimeError:
        # Path.home() raises when no home directory is resolvable (minimal containers / some CI
        # runners). The env-root candidate (if any) still applies; otherwise the caller sees no
        # hub and applies the fail posture (hard gate => fail-closed, advisory => fail-open).
        pass
    for base in bases:
        if not base.is_absolute():
            continue
        try:
            resolved_base = base.resolve()
        except (OSError, RuntimeError):
            continue
        for sub in ("hooks", "scripts"):  # hub layout, then legacy layout
            p = base / sub / name
            try:
                resolved = p.resolve()
            except (OSError, RuntimeError):
                continue
            if (
                resolved.is_relative_to(resolved_base)
                and resolved.is_file()
                and resolved != here
            ):
                return resolved
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
    except (OSError, RuntimeError):
        # audit is best-effort; never crash the shim on a write error (OSError) OR on an
        # unresolvable home (RuntimeError from Path.home()/expanduser() in the darwin/XDG path
        # branches above — same failure guarded in _canonical(), governance-hub#213). A shim that
        # cannot even log must still return its verdict rather than die mid-gate.
        pass


_SHIM_MAX_STDIN_BYTES = 4 * 1024 * 1024
_SHIM_STDIN_DEADLINE_S = 5.0


def _read_stdin_bounded_shim() -> str | None:
    """Byte-capped, deadline-bounded stdin read without locking buffered stdin at exit."""
    import io
    import threading

    try:
        stdin_fd = sys.stdin.fileno()
    except (OSError, ValueError, AttributeError):
        stdin_fd = None
    if stdin_fd is None:
        # The only supported descriptor-less inputs are bounded in-memory streams used when
        # this shim re-feeds an already captured payload. An arbitrary stream with no fileno()
        # cannot be deadline-bounded or cancelled safely in CPython, so fail safe instead of
        # starting another buffered daemon that could recreate the shutdown abort below.
        try:
            if isinstance(sys.stdin, io.StringIO):
                return sys.stdin.read(_SHIM_MAX_STDIN_BYTES)
            buffer = getattr(sys.stdin, "buffer", None)
            if isinstance(buffer, io.BytesIO):
                return buffer.read(_SHIM_MAX_STDIN_BYTES).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — unreadable in-memory stdin is no payload
            return None
        return None

    chunks: list[bytes] = []
    done = threading.Event()

    def _reader() -> None:
        try:
            while sum(len(c) for c in chunks) < _SHIM_MAX_STDIN_BYTES:
                remaining = _SHIM_MAX_STDIN_BYTES - sum(len(c) for c in chunks)
                # Read the descriptor directly. A host may keep the pipe open after one complete
                # JSON object; leaving a daemon blocked in BufferedReader.read1() then aborts
                # CPython during finalization because it owns the stdin buffer lock. os.read()
                # holds no Python buffered-I/O lock, so the daemon can be abandoned safely once
                # the main thread recognizes complete JSON.
                chunk = os.read(stdin_fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
        except Exception:  # noqa: BLE001 — whatever arrived is the payload
            pass
        finally:
            done.set()

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    import time as _time

    deadline = _time.monotonic() + _SHIM_STDIN_DEADLINE_S
    validated_snapshot: bytes | None = None
    while not done.wait(0.05) and _time.monotonic() < deadline:
        snapshot = b"".join(chunks)
        if snapshot:
            try:
                json.loads(snapshot.decode("utf-8", "replace"))
            except ValueError:
                continue
            validated_snapshot = snapshot
            break  # complete JSON payload: stop waiting for EOF (gov-hub#419 round-34)
    result = validated_snapshot if validated_snapshot is not None else b"".join(chunks)
    return result.decode("utf-8", "replace")


def _normalise_recovery_field(value: object) -> str | None:
    """Turn a ``command``/``cmd`` payload value into the string the allowlist matches.

    List values are accepted only as bare-word argv (plain-space join, NOT shlex.quote:
    quoting ``~/.fleet-governance`` would make the documented payload fail to match). A
    list that cannot be joined unambiguously — empty element, whitespace, or a shell
    metacharacter in any element — is None, as is any non-string non-list value.
    """
    if isinstance(value, list) and all(isinstance(t, str) for t in value):
        if any((not t) or any(c.isspace() or c in "\"'`$\\|&;<>()" for c in t) for t in value):
            return None
        value = " ".join(value)
    if not isinstance(value, str):
        return None
    return value.strip()


def _recovery_command_from_stdin(raw: str | None = None) -> str | None:
    """Return the recovery command from the PreToolUse payload IFF it matches the allowlist.

    Called from two fail-closed branches in ``_run()``:
      * hub-MISSING (after ``_canonical(name)`` returns None)
      * attribution-failure (the ``except Exception`` around ``_ensure_project_dir()``, #500)

    Returns None when stdin is not a usable payload, the surviving command is not an exact
    recovery command, or ``command`` and ``cmd`` are both present and are not string-equal
    after argv normalisation. Residual: a harness that forwards both keys with equivalent
    values is treated as one command (the executed and allowlisted strings are the same). A
    harness that forwards both keys with disagreeing values is refused — the shim never
    allowlists a field the host will not execute. The parser does not read ``tool_name``.

    Codex's ``exec_command`` supplies the command as ``cmd`` (gov-hub#419 round-68). A
    single-key payload on either ``command`` or ``cmd`` still matches; do not select the
    field from ``tool_name`` (that would invert the round-68 pin that ``exec_command`` +
    ``command`` must still match).

    BOUNDED (gov-hub#419 round-13): a host that writes the payload but keeps the pipe open must
    not hang the fail-closed verdict, and an oversized payload must not exhaust memory — the read
    runs in a daemon thread with a hard deadline and a byte cap."""
    if raw is None:
        raw = _read_stdin_bounded_shim()
    if raw is None:
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return None
    has_command = "command" in tool_input
    has_cmd = "cmd" in tool_input
    if not has_command and not has_cmd:
        return None
    command_n = _normalise_recovery_field(tool_input.get("command")) if has_command else None
    cmd_n = _normalise_recovery_field(tool_input.get("cmd")) if has_cmd else None
    if has_command and has_cmd:
        if command_n is None or cmd_n is None or command_n != cmd_n:
            return None
        command = command_n
    else:
        command = command_n if has_command else cmd_n
    if not command:
        return None
    for pattern in _RECOVERY_PATTERNS:
        if pattern.match(command):
            return command
    return None


def _spoke_project_root() -> Path:
    """Spoke repository root derived from the *installed* shim path.

    Install layout (``install.sh shim``): ``<spoke>/scripts/<hook_name>.py`` is a byte-copy of
    this file. Root selection must NOT use ambient cwd (foreign launches) or the canonical hub
    hook path (``runpy`` would otherwise make hub hooks audit ``~/.fleet-governance`` — #268).

    Derived from the *logical* installed path (``os.path.abspath``: absolutize + normalize ``..``
    LEXICALLY), never ``Path.resolve()`` — resolving FOLLOWS SYMLINKS, and an unsupported
    symlinked install (``<spoke>/scripts/<hook>.py -> <hub>/scripts/<hook>.py``) would then land on
    the hub's own ``scripts/`` dir and hand back the HUB root as the spoke — reintroducing the exact
    mis-binding #268 exists to prevent (governance-hub#281). ``install.sh``/``install.ps1`` refuse
    to write through a symlinked hook path, so this layout is not installable; the shim
    nonetheless fails SAFE (spoke, not hub) if one ever appears by hand.
    """
    here = Path(os.path.abspath(__file__))
    if here.parent.name == "scripts":
        return here.parent.parent
    # Defensive fallback for non-standard placements (unit fixtures that drop the shim flat).
    for parent in (here.parent, *here.parent.parents):
        if (parent / ".git").exists():
            return parent
    return here.parent


def _ensure_project_dir() -> None:
    """Establish ``CLAUDE_PROJECT_DIR`` before canonical-hook delegation (#268).

    Contract (must match the module docstring):
      * Trusted harness / host-supplied ``CLAUDE_PROJECT_DIR`` (sandbox, worktree) remains
        authoritative when set to a non-empty value.
      * Otherwise set it to the spoke root derived from the installed shim path so hub hooks
        that fall back to ``__file__`` (or honor the env) read/write spoke state, not the hub.
    """
    if os.environ.get("CLAUDE_PROJECT_DIR", "").strip():
        return
    os.environ["CLAUDE_PROJECT_DIR"] = str(_spoke_project_root())


def _delegate(canonical: Path, name: str) -> None:
    """Run the canonical hook. Propagate its intended exit code (SystemExit). On a NON-SystemExit
    runtime error (hub present but the hook is buggy/incompatible), restore the fail posture:
    HARD gates fail closed (exit 2), ADVISORY hooks fail open (exit 0). Always audited — never a
    silent bypass, never a silent block.

    Sets ``CLAUDE_PROJECT_DIR`` to the spoke root when absent so the delegated hook operates on
    the spoke, not the hub install path (#268)."""
    _ensure_project_dir()
    payload_event = ""
    if name in _ENV_CONDITIONAL_FAIL_CLOSED and _conditional_armed(name) and not _argv_declared_event():
        # Event-aware runtime-error posture (gov-hub#419 round-17): capture the payload BEFORE
        # delegation and re-feed it through a StringIO stdin so the canonical hook still reads
        # it. Scoped to armed conditional hooks only — every other hook keeps the untouched
        # stdin passthrough.
        try:
            import io

            raw = _read_stdin_bounded_shim() or ""
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    evt = data.get("hook_event_name") or data.get("hookEventName")
                    payload_event = evt if isinstance(evt, str) else ""
            except (ValueError, TypeError):
                payload_event = ""
            sys.stdin = io.StringIO(raw)
        except Exception:  # noqa: BLE001 — capture failure: fall back to the blind posture
            payload_event = ""
    try:
        runpy.run_path(str(canonical), run_name="__main__")
    except SystemExit:
        raise  # the hook's own exit code (0 allow / 2 block) is authoritative.
    except Exception as exc:  # noqa: BLE001 — degraded-mode contract below.
        detail = f"{type(exc).__name__}: {exc}"
        if _fails_closed(name, payload_event):
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
        try:
            _ensure_project_dir()
        except Exception:  # noqa: BLE001; attribution cannot make break-glass unreachable.
            pass
        _audit("emergency-bypass", name, "EMERGENCY_BYPASS_GOVERNANCE=1 (human break-glass)")
        sys.exit(0)
    try:
        _ensure_project_dir()
    except Exception as exc:  # noqa: BLE001; preserve the named hook's degraded-mode posture.
        detail = f"{type(exc).__name__}: {exc}"
        payload_event = ""
        raw_payload: str | None = None
        if (
            name in _ENV_CONDITIONAL_FAIL_CLOSED
            and _conditional_armed(name)
            and not _argv_declared_event()
        ):
            raw_payload = _read_stdin_bounded_shim()
            try:
                data = json.loads(raw_payload or "")
                if isinstance(data, dict):
                    evt = data.get("hook_event_name") or data.get("hookEventName")
                    payload_event = evt if isinstance(evt, str) else ""
            except (ValueError, TypeError):
                payload_event = ""
        if _fails_closed(name, payload_event):
            recovery = _recovery_command_from_stdin(raw_payload)
            if recovery is not None:
                _audit(
                    "recovery-allowed",
                    name,
                    f"project attribution failed; recovery command permitted: {recovery}",
                )
                return
            _audit("project-dir-init-error-failclosed", name, detail)
            sys.stderr.write(
                f"BLOCK: governance-shim - {name} could not initialize project attribution; "
                "failing CLOSED (hard gate). Use EMERGENCY_BYPASS_GOVERNANCE=1 for human "
                "recovery.\n"
            )
            sys.exit(2)
        _audit("project-dir-init-error-failopen", name, detail)
        sys.stderr.write(
            f"governance-shim: {name} could not initialize project attribution; "
            "advisory hook fails open.\n"
        )
        sys.exit(0)
    canonical = _canonical(name)
    if canonical is not None:
        _delegate(canonical, name)
        return
    # Hub not found.
    payload_event = ""
    raw_payload: str | None = None
    if name not in _FAIL_CLOSED_HOOKS and _conditional_armed(name) and not _argv_declared_event():
        # No delegation follows in this branch, so consuming stdin is safe: resolve the event
        # from the payload so a payload-only SessionStart stays advisory (round-16 daemon HIGH).
        raw_payload = _read_stdin_bounded_shim()
        try:
            data = json.loads(raw_payload or "")
            if isinstance(data, dict):
                evt = data.get("hook_event_name") or data.get("hookEventName")
                payload_event = evt if isinstance(evt, str) else ""
        except (ValueError, TypeError):
            payload_event = ""
    if _fails_closed(name, payload_event):
        recovery = _recovery_command_from_stdin(raw_payload)
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
