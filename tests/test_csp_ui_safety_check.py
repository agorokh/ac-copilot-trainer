"""Unit tests for scripts/check_csp_ui_safety.py — verify the regex catches
all known patterns of reversed ui.textColored calls."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_csp_ui_safety.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_csp_ui_safety", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_csp_ui_safety"] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def test_regex_catches_known_violation_patterns() -> None:
    """The COLOR_FIRST_PATTERN regex must match every known reversed pattern."""
    mod = _load_module()
    pattern = mod.COLOR_FIRST_PATTERN

    must_match = [
        'ui.textColored(rgbm(0.5, 0.5, 0.5, 1), "Hello")',
        'ui.textColored(COLOR_TITLE, "Display")',
        'ui.textColored(COLOR_BG_BORDER, "x")',
        "ui.textColored(colBody, body)",  # col-prefix from PR #67 round 2
        "ui.textColored(colDet, detail)",
        "ui.textColored(col, text)",  # bare col from PR #67 round 3
        "ui.textColored(color, body)",  # bare color
        "ui.textColored(spdCol, curStr)",  # ends in Col
        "ui.textColored(hintColor, hintText)",
        "ui.textColored(titleColor, txt)",
    ]
    for line in must_match:
        assert pattern.search(line), f"regex MISSED: {line}"


def test_regex_does_not_match_correct_patterns() -> None:
    """Correct text-first calls should NOT match the violation pattern."""
    mod = _load_module()
    pattern = mod.COLOR_FIRST_PATTERN

    must_not_match = [
        'ui.textColored("Hello", rgbm(0.5, 0.5, 0.5, 1))',
        'ui.textColored("Display", COLOR_TITLE)',
        'ui.textColored("x", colBody)',
        "ui.textColored(body, col)",
        "ui.textColored(text, color)",
        "ui.textColored(curStr, spdCol)",
        "ui.textColored(lastHintText, hintColor)",
        'ui.textColored(string.format("%.0f", x), COLOR_WHITE)',
    ]
    for line in must_not_match:
        assert not pattern.search(line), f"regex falsely matched: {line}"


def test_strip_lua_comment_removes_inline_comment() -> None:
    mod = _load_module()
    assert (
        mod.strip_lua_comment('ui.textColored("x", col) -- this is a comment')
        == 'ui.textColored("x", col) '
    )


def test_strip_lua_comment_preserves_strings_with_dashes() -> None:
    mod = _load_module()
    # Em dash inside a string should not be treated as a comment
    line = 'ui.textColored("Coasting -- roll to throttle", col)'
    stripped = mod.strip_lua_comment(line)
    assert "Coasting" in stripped
    assert "roll to throttle" in stripped


def test_actual_repo_has_zero_violations() -> None:
    """Smoke: running the checker on the repo finds 0 violations."""
    mod = _load_module()
    files = sorted(mod.LUA_DIR.rglob("*.lua"))
    assert files, f"No Lua files found under {mod.LUA_DIR}"
    total = 0
    for f in files:
        for _ in mod.scan_file(f):
            total += 1
    assert total == 0, f"Found {total} textColored violations in repo"
