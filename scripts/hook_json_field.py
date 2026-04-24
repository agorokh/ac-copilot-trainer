#!/usr/bin/env python3
"""Read hook JSON from stdin; print a dotted field (e.g. tool_input.command)."""

from __future__ import annotations

import json
import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("hook_json_field: missing dotted path argument", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1].split(".")
    try:
        d = json.load(sys.stdin)
    except Exception:
        print("hook_json_field: stdin is not valid JSON (fail-open)", file=sys.stderr)
        sys.exit(0)
    for key in path:
        if not isinstance(d, dict):
            print("")
            return
        d = d.get(key)
    if d is None:
        print("")
    else:
        print(d)


if __name__ == "__main__":
    main()
