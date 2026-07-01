"""Shared Lua source-text helpers for static conformance tests."""

from __future__ import annotations


def strip_lua_comments(text: str) -> str:
    """Drop Lua ``--`` line comments, honoring string literals (PR #173 pattern).

    A ``--`` inside a string is not a comment, and an escaped quote does not end
    one. Block comments (``--[[ ]]``) are out of scope — no producer wraps live
    code in one.
    """
    out: list[str] = []
    for line in text.splitlines():
        i, in_str, cut = 0, None, None
        while i < len(line):
            c = line[i]
            if in_str is not None:
                if c == "\\":
                    i += 1
                elif c == in_str:
                    in_str = None
            elif c in ("'", '"'):
                in_str = c
            elif c == "-" and line[i + 1 : i + 2] == "-":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)
