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
from tools.rig_launcher.supervisor import GamePointStatus, ProbeResult

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
    # present-but-quiescent rows are demoted, not lit green
    assert theme.tone_for(True, "absent") == "idle"
    assert theme.tone_for(True, "skipped") == "idle"
    assert theme.tone_for(True, "loopback") == "idle"
    # failures are red unless they are a known in-progress state
    assert theme.tone_for(False, "DISABLED") == "brake"
    assert theme.tone_for(False, "unreachable") == "brake"
    # a missing screen peer is a failure to fix, not progress — the render
    # shows SCREEN WAITING in brake red (issue #432 photo parity)
    assert theme.tone_for(False, "waiting") == "brake"
    # genuinely in-progress states stay amber
    assert theme.tone_for(True, "starting") == "lift"
    assert theme.tone_for(False, "initializing") == "lift"


def test_color_for_tone_uses_signal_hex() -> None:
    assert theme.color_for_tone("clear") == theme.CLEAR
    assert theme.color_for_tone("lift") == theme.LIFT
    assert theme.color_for_tone("brake") == theme.BRAKE
    assert theme.color_for_tone("idle") == theme.DIM
    assert theme.color_for_tone("nonsense") == theme.DIM


def test_field_ink_matches_status_field_component() -> None:
    # StatusField 'go' ink from the design bundle; 'stop' ink is chalk-on-brake.
    assert theme.FIELD_INK["clear"] == "#06140C"
    assert theme.FIELD_INK["brake"] == theme.CHALK


def _status(**overrides: ProbeResult) -> GamePointStatus:
    rows: dict[str, ProbeResult] = {
        "sidecar": ProbeResult("sidecar", True, "healthy", "peers=1 screen_peers=1"),
        "screen": ProbeResult("screen", True, "connected", "screen_peers=1"),
        "voice": ProbeResult("voice", True, "enabled", "backend=sounddevice"),
        "simhub": ProbeResult("simhub", True, "absent", "executable not found"),
    }
    rows.update(overrides)
    return GamePointStatus(
        generated_at=0.0,
        log_path="sidecar.log",
        status_path="status.json",
        **rows,
    )


def test_summary_for_ready_state() -> None:
    assert theme.summary_for(_status()) == (
        "READY TO DRIVE",
        "clear",
        "sidecar · screen live",
    )


def test_summary_for_stopped_sidecar_names_the_port() -> None:
    status = _status(
        sidecar=ProbeResult("sidecar", False, "stopped", "—"),
        screen=ProbeResult("screen", False, "waiting", "no screen peer"),
    )
    assert theme.summary_for(status, port=9876) == (
        "PRESS START",
        "brake",
        "nothing on port 9876 yet",
    )


def test_summary_for_unreachable_sidecar_names_the_default_port() -> None:
    status = _status(sidecar=ProbeResult("sidecar", False, "unreachable", "connection refused"))
    assert theme.summary_for(status) == ("PRESS START", "brake", "nothing on port 8765 yet")


def test_summary_for_other_failure_uses_first_failing_detail() -> None:
    status = _status(
        screen=ProbeResult("screen", False, "waiting", "no ESP32 screen peer connected")
    )
    assert theme.summary_for(status) == (
        "PRESS START",
        "brake",
        "no ESP32 screen peer connected",
    )


def test_summary_for_blocking_preflight_outranks_port_copy() -> None:
    """A failing preflight check must surface before the port-down copy —
    pressing Start cannot succeed until the blocker clears (PR #445 review)."""
    status = _status(sidecar=ProbeResult("sidecar", False, "stopped", "—"))
    status = GamePointStatus(
        generated_at=status.generated_at,
        sidecar=status.sidecar,
        screen=status.screen,
        voice=status.voice,
        simhub=status.simhub,
        log_path=status.log_path,
        status_path=status.status_path,
        checks=(ProbeResult("acroot", False, "missing", "AC install not found"),),
    )
    assert theme.summary_for(status) == (
        "PRESS START",
        "brake",
        "AC install not found",
    )


def test_summary_for_falls_back_to_state_word_without_detail() -> None:
    status = _status(voice=ProbeResult("voice", False, "DISABLED", ""))
    assert theme.summary_for(status) == ("PRESS START", "brake", "DISABLED")


def test_launcher_buttons_are_uppercase_with_start_emphasis() -> None:
    from tools.rig_launcher import view

    labels = [label for label, _key, _primary in view._BUTTONS]
    assert labels == ["▶ START", "STABLE AC", "REFRESH", "LOGS", "SETTINGS", "SETUP DIFF"]
    assert [primary for _label, _key, primary in view._BUTTONS] == [
        True,
        False,
        False,
        False,
        False,
        False,
    ]
    # Start is 1.5x each secondary action (1.5fr vs 1fr in the design grid).
    assert view._BUTTON_WEIGHTS == (3, 2, 2, 2, 2, 2)


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


def test_display_ladder_prefers_bundled_semicondensed_family() -> None:
    # The FR_PRIVATE statics expose the name-table family "Saira SemiCondensed"
    # (no space); the Google system-install name has the space. Both precede
    # the Windows fallbacks.
    assert theme.FONT_DISPLAY[:2] == ("Saira SemiCondensed", "Saira Semi Condensed")
    assert "Bahnschrift" in theme.FONT_DISPLAY
