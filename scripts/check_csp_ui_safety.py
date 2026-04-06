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

COLOR_FIRST_PATTERN = re.compile(
    r"ui\.textColored\(\s*("
    r"rgbm\b"
    r"|COLOR_[A-Z_]+"
    r"|[a-z][a-zA-Z]*[Cc]ol\b"
    r"|[a-z][a-zA-Z]*[Cc]olor\b"
    r")"
)


def scan_file(path: Path):
    violations = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if "type(ui.textColored)" in line:
            continue
        m = COLOR_FIRST_PATTERN.search(line)
        if m:
            violations.append((lineno, line.strip()))
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
