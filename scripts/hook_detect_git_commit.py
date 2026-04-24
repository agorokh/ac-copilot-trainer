#!/usr/bin/env python3
"""stdin: hook JSON; exit 0 if tool command includes ``git commit``, else 1."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_impl():
    here = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "hook_protect_main_impl",
        here / "hook_protect_main_impl.py",
    )
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
