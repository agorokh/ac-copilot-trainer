"""Static check for CSP Lua UI API misuse.

CSP's `ui.textColored(text, color)` is **text-first, color-second** — opposite
of standard ImGui. This script flags any call where the first argument looks
like a color expression and the second looks like text.

Run via `python scripts/check_csp_ui_safety.py` or as part of CI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = REPO_ROOT / "src" / "ac_copilot_trainer"

# Match identifiers that look like a color (rgbm() literal, COLOR_*, names
# starting/ending with col/color, hintCol, brandK, etc).
COLOR_IDENT = (
    r"("
    r"rgbm\("  # inline rgbm() literal
    r"|COLOR_[A-Z_]+"  # COLOR_TITLE etc
    r"|[Cc]ol\b"  # bare col / Col
    r"|[Cc]olor\b"  # bare color / Color
    r"|[Cc]ol[A-Z]\w*"  # colBody, colDet, ColX
    r"|[Cc]olor[A-Z]\w*"  # colorBody, ColorX
    r"|\w+[Cc]ol\b"  # spdCol, hintCol
    r"|\w+[Cc]olor\b"  # hintColor, titleColor
    r")"
)
COLOR_FIRST_PATTERN = re.compile(r"ui\.textColored\(\s*" + COLOR_IDENT)


def strip_lua_comment(line: str) -> str:
    """Strip everything after `--` outside of string literals."""
    out = []
    i = 0
    in_str = False
    str_char = None
    while i < len(line):
        ch = line[i]
        if in_str:
            if ch == "\\" and i + 1 < len(line):
                out.append(ch)
                out.append(line[i + 1])
                i += 2
                continue
            out.append(ch)
            if ch == str_char:
                in_str = False
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = True
            str_char = ch
            out.append(ch)
            i += 1
            continue
        # Single-line comment marker
        if ch == "-" and i + 1 < len(line) and line[i + 1] == "-":
            break
        out.append(ch)
        i += 1
    return "".join(out)


def scan_file(path: Path):
    violations = []
    text = path.read_text(encoding="utf-8")
    # Strip multi-line comments --[[ ... ]]
    text = re.sub(r"--\[\[.*?\]\]", "", text, flags=re.DOTALL)
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_lua_comment(raw_line)
        if "type(ui.textColored)" in line:
            continue
        m = COLOR_FIRST_PATTERN.search(line)
        if m:
            violations.append((lineno, raw_line.strip()))
    return violations


def main():
    files = sorted(LUA_DIR.rglob("*.lua"))
    total = 0
    for f in files:
        for lineno, line in scan_file(f):
            rel = f.relative_to(REPO_ROOT)
            print(f"{rel}:{lineno}: ui.textColored() called with COLOR FIRST")
            print(f"  > {line}")
            print("  > FIX: CSP signature is `ui.textColored(text, color)` -- swap args")
            total += 1
    if total:
        print(f"\nFAIL: {total} ui.textColored signature violation(s)")
        return 1
    print(f"OK: {len(files)} Lua files scanned, 0 textColored signature violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
