"""Conformance: the in-game HUD palette must match the Racing Atelier design colors.css.

Drift guard (fleet pitfall *redundant-code-drift*): the CSP-Lua HUD adapter
``src/ac_copilot_trainer/modules/design_tokens.lua`` mirrors the Racing Atelier palette that the
in-game HUD (`hud.lua`, `coaching_overlay.lua`) renders. This test parses both that adapter and
the canonical ``colors.css`` and asserts every hex matches, so the HUD palette cannot silently
diverge from the design of record — the same single-source-of-truth check the launcher's
``theme.py`` gets in ``test_rig_launcher_theme.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COLORS_CSS = _ROOT / "docs/10_Development/design/racing-atelier/project/tokens/colors.css"
_DESIGN_TOKENS_LUA = _ROOT / "src/ac_copilot_trainer/modules/design_tokens.lua"

_CSS_HEX = re.compile(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\b")
_LUA_HEX = re.compile(r'(\w+)\s*=\s*"(#[0-9A-Fa-f]{6})"')


def _css_tokens() -> dict[str, str]:
    return {n: v.upper() for n, v in _CSS_HEX.findall(_COLORS_CSS.read_text(encoding="utf-8"))}


def _lua_tokens() -> dict[str, str]:
    return {
        n: v.upper() for n, v in _LUA_HEX.findall(_DESIGN_TOKENS_LUA.read_text(encoding="utf-8"))
    }


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
