#!/usr/bin/env python3
"""stdin: hook JSON; exit 0 if tool command includes ``git commit``, else 1."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def _is_relative_to(path: Path, base: Path) -> bool:
    """Python 3.9-compatible containment check."""
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _home_dir() -> Path:
    """Return the hook-visible home directory, honoring test/Unix-style HOME on Windows."""
    raw = os.environ.get("HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home()


def _canonical_impl_path() -> Path | None:
    """Resolve the hub's ``hook_protect_main_impl.py`` from a trusted location.

    Mirrors ``governance_shim._canonical``: ``$FLEET_GOVERNANCE_ROOT`` first, then
    ``~/.fleet-governance``; hub ``hooks/`` layout, then legacy ``scripts/``.
    """
    bases: list[Path] = []
    env_root = os.environ.get("FLEET_GOVERNANCE_ROOT", "").strip()
    if env_root:
        bases.append(Path(env_root).expanduser())
    bases.append(_home_dir() / ".fleet-governance")
    for base in bases:
        if not base.is_absolute():
            continue
        try:
            resolved_base = base.resolve()
        except (OSError, RuntimeError):
            continue
        for sub in ("hooks", "scripts"):
            p = base / sub / "hook_protect_main_impl.py"
            try:
                resolved = p.resolve()
            except (OSError, RuntimeError):
                continue
            if _is_relative_to(resolved, resolved_base) and resolved.is_file():
                return resolved
    return None


def _load_impl():
    """Load ``hook_protect_main_impl``.

    #338 hub-and-spoke: when the local ``hook_protect_main_impl.py`` is a thin governance
    shim it no longer carries ``command_includes_git_commit_intent``; resolve the canonical
    hub impl instead. If the local copy is a shim and the hub is absent, raise a clear error
    rather than fail with an opaque ``AttributeError``.
    """
    here = Path(__file__).resolve().parent
    local = here / "hook_protect_main_impl.py"
    target = local
    if local.is_file() and "governance shim" in local.read_text(encoding="utf-8"):
        canonical = _canonical_impl_path()
        if canonical is None:
            raise RuntimeError(
                "hook_protect_main_impl.py is a governance shim but the fleet-governance hub "
                "is unavailable; clone it to ~/.fleet-governance or set FLEET_GOVERNANCE_ROOT."
            )
        target = canonical
    spec = importlib.util.spec_from_file_location("hook_protect_main_impl", target)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    impl = _load_impl()
    raw = sys.stdin.read()
    try:
        d = json.loads(raw)
    except Exception:
        return 1
    cmd = (d.get("tool_input") or {}).get("command") or ""
    if not cmd:
        return 1
    return 0 if impl.command_includes_git_commit_intent(cmd) else 1


if __name__ == "__main__":
    sys.exit(main())
