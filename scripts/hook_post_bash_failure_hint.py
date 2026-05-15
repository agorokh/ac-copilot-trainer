#!/usr/bin/env python3
"""PostToolUse:Bash — one-line transcript hint only when exit_code != 0.

Reads Claude Code hook JSON from stdin. On success (exit code 0) or unknown
payload shape: exit 0 with no stdout (no noise). On non-zero exit: print
exactly one line to stdout (stderr text collapsed to single-line whitespace).

See docs/00_Core/HOOK_DESIGN.md and GitHub issue #95.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _tool_result_dict(data: dict[str, Any]) -> dict[str, Any]:
    tr = data.get("tool_response")
    if isinstance(tr, dict):
        return tr
    tr = data.get("tool_result")
    if isinstance(tr, dict):
        return tr
    return {}


def main() -> None:
    """Always fail open (exit 0); never raise to the hook runner."""
    try:
        if sys.stdin.isatty():
            return
        raw = sys.stdin.read()
        if not raw.strip():
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return

        tr = _tool_result_dict(data)
        code = _as_int(tr.get("exit_code"))
        if code is None:
            code = _as_int(tr.get("exitCode"))
        if code is None:
            return
        if code == 0:
            return

        stderr = tr.get("stderr") or ""
        if not isinstance(stderr, str):
            stderr = str(stderr) if stderr is not None else ""
        # One stdout line: collapse all whitespace (including embedded newlines).
        stderr = " ".join(stderr.split())
        if len(stderr) > 280:
            stderr = stderr[:277].rstrip() + "..."

        line = f"Bash exited with code {code}."
        if stderr:
            line += f" Stderr: {stderr}"
        sys.stdout.write(line + "\n")
    except Exception as exc:
        # Fail open (exit 0) but surface unexpected errors for operators.
        print(f"hook_post_bash_failure_hint: {exc}", file=sys.stderr)
        return


if __name__ == "__main__":
    main()
