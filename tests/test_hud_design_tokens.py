"""Conformance: the in-game HUD palette must match the Racing Atelier design colors.css.

Drift guard (fleet pitfall *redundant-code-drift*): the CSP-Lua HUD adapter
``src/ac_copilot_trainer/modules/design_tokens.lua`` mirrors the Racing Atelier palette that the
in-game HUD (`hud.lua`, `coaching_overlay.lua`, `hud_settings.lua`, `racing_line.lua`) renders.
This test parses both that adapter and the canonical ``colors.css`` and asserts every hex
matches, so the HUD palette cannot silently diverge from the design of record — the same
single-source-of-truth check the launcher's ``theme.py`` gets in ``test_rig_launcher_theme.py``.

Issue #673 extends the lock to the Part-A remainder surfaces so inline ``rgbm`` palette
literals cannot reappear without failing CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.lua_text_helpers import strip_lua_comments

_ROOT = Path(__file__).resolve().parents[1]
_MODULES = _ROOT / "src/ac_copilot_trainer/modules"
_COLORS_CSS = _ROOT / "docs/10_Development/design/racing-atelier/project/tokens/colors.css"
_DESIGN_TOKENS_LUA = _MODULES / "design_tokens.lua"

_CSS_HEX = re.compile(r"--([a-zA-Z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})\b")
_LUA_HEX = re.compile(r'(\w+)\s*=\s*["\'](#[0-9A-Fa-f]{6})["\']')
# Numeric component palette literals (rgbm(0.12, ...)). Reconstruction from token
# fields (rgbm(c.r, c.g, c.b, ...)) and availability checks (``if not rgbm``) are OK.
_NUMERIC_RGBM = re.compile(r"\brgbm\s*\(\s*\d")

_ATELIER_SURFACES = (
    "hud.lua",
    "hud_settings.lua",
    "coaching_overlay.lua",
    "racing_line.lua",
)


def _css_tokens() -> dict[str, str]:
    return {n: v.upper() for n, v in _CSS_HEX.findall(_COLORS_CSS.read_text(encoding="utf-8"))}


def _lua_tokens() -> dict[str, str]:
    text = strip_lua_comments(_DESIGN_TOKENS_LUA.read_text(encoding="utf-8"))
    hex_block = re.search(r"M\.HEX\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not hex_block:
        return {}
    return {n: v.upper() for n, v in _LUA_HEX.findall(hex_block.group(1))}


def _surface(name: str) -> str:
    return strip_lua_comments((_MODULES / name).read_text(encoding="utf-8"))


def test_hud_design_tokens_match_colors_css() -> None:
    css = _css_tokens()
    lua = _lua_tokens()
    assert lua, "no hex tokens parsed from design_tokens.lua"
    assert css, "no hex tokens parsed from colors.css"
    for name, value in lua.items():
        assert name in css, f"HUD token {name!r} is not defined in colors.css"
        assert value == css[name], f"{name}: design_tokens.lua={value} but colors.css={css[name]}"


def test_hud_design_tokens_cover_the_signal_palette() -> None:
    lua = _lua_tokens()
    for required in ("carbon", "edge", "chalk", "mute", "brass", "brake", "lift", "clear"):
        assert required in lua, f"HUD palette missing required token {required!r}"


def test_atelier_surfaces_require_design_tokens() -> None:
    """#673: every in-sim Atelier surface derives color from the shared token map."""
    for name in _ATELIER_SURFACES:
        src = _surface(name)
        assert re.search(
            r'^\s*local\s+T\s*=\s*require\(["\']design_tokens["\']\)',
            src,
            re.M,
        ), f"{name} must require design_tokens"


def test_atelier_surfaces_ban_numeric_rgbm_palette_literals() -> None:
    """#673: no surface may reintroduce hand-typed rgbm(0.x, ...) palette literals."""
    for name in _ATELIER_SURFACES:
        src = _surface(name)
        hits = _NUMERIC_RGBM.findall(src)
        assert not hits, f"{name} still has numeric rgbm palette literals: {hits[:5]!r}"


def test_racing_line_speed_gradient_uses_signal_triad() -> None:
    """#673 Part B: racing-line gradient endpoints come from clear/lift/brake tokens."""
    src = _surface("racing_line.lua")
    for token in ("clear", "lift", "brake"):
        assert re.search(
            rf'_hexRgb\(\s*["\']{token}["\']\s*\)',
            src,
        ), f"racing_line speedColor must derive endpoint from token {token!r}"
    assert "speedColorCache" in src, "speedColorCache must remain (built from token refs)"
