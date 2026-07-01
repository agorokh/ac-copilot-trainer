"""Conformance + logic tests for the Racing Atelier launcher theme (epic #432).

The palette test is the drift guard: it parses the design package's canonical
``colors.css`` and asserts every hex token the launcher uses matches it, so the
Python adapter can never silently diverge from the design of record (fleet
pitfall: *redundant-code-drift*). The tone/font tests cover the presentation
logic without needing a Tk display, so they run in headless CI.
"""

from __future__ import annotations

import re
from pathlib import Path

from tools.rig_launcher import theme

_COLORS_CSS = (
    Path(__file__).resolve().parents[1]
    / "docs/10_Development/design/racing-atelier/project/tokens/colors.css"
)
_HEX_TOKEN = re.compile(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})\b")


def _css_hex_tokens() -> dict[str, str]:
    text = _COLORS_CSS.read_text(encoding="utf-8")
    return {name: value.upper() for name, value in _HEX_TOKEN.findall(text)}


def test_palette_matches_design_tokens_single_source_of_truth() -> None:
    css = _css_hex_tokens()
    assert css, "no hex tokens parsed from colors.css — path or format drift"
    for name, value in theme.TOKENS.items():
        assert name in css, f"token {name!r} is not defined in colors.css"
        assert value.upper() == css[name], f"{name}: theme={value} but css={css[name]}"


def test_tone_for_maps_states_to_signals() -> None:
    assert theme.tone_for(True, "healthy") == "clear"
    assert theme.tone_for(True, "connected") == "clear"
    assert theme.tone_for(True, "enabled") == "clear"
    # a healthy hotspot "on" is lit green, not amber (matches the design mock)
    assert theme.tone_for(True, "on") == "clear"
    # present-but-quiescent rows are demoted, not lit green
    assert theme.tone_for(True, "absent") == "idle"
    assert theme.tone_for(True, "skipped") == "idle"
    assert theme.tone_for(True, "loopback") == "idle"
    # failures are red unless they are a known in-progress state
    assert theme.tone_for(False, "DISABLED") == "brake"
    assert theme.tone_for(False, "unreachable") == "brake"
    assert theme.tone_for(False, "waiting") == "lift"
    assert theme.tone_for(True, "starting") == "lift"


def test_color_for_tone_uses_signal_hex() -> None:
    assert theme.color_for_tone("clear") == theme.CLEAR
    assert theme.color_for_tone("lift") == theme.LIFT
    assert theme.color_for_tone("brake") == theme.BRAKE
    assert theme.color_for_tone("idle") == theme.DIM
    assert theme.color_for_tone("nonsense") == theme.DIM


def test_resolve_font_prefers_available_family() -> None:
    assert (
        theme.resolve_font(("Saira", "Segoe UI", "Helvetica"), {"Segoe UI", "Arial"}) == "Segoe UI"
    )
    # none installed -> last (generic) fallback so the caller always gets a family
    assert theme.resolve_font(("Saira", "Helvetica"), {"Arial"}) == "Helvetica"
    # match is case-insensitive
    assert theme.resolve_font(("saira semi condensed",), {"Saira Semi Condensed"}) == (
        "saira semi condensed"
    )
