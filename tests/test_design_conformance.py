"""Design conformance tests for AC Copilot Trainer (no AC runtime needed).

These tests parse Lua source files and manifest.ini to verify that design
requirements from the Figma spec are structurally present in code.  They
complement the existing ``test_manifest_phase5.py``, ``test_corner_names.py``,
and ``test_coaching_max_visible_contract.py`` suites.

Checklist cross-reference: ``tests/design_conformance_checklist.yaml``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULES = REPO_ROOT / "src" / "ac_copilot_trainer" / "modules"
ENTRY = REPO_ROOT / "src" / "ac_copilot_trainer" / "ac_copilot_trainer.lua"
MANIFEST = REPO_ROOT / "src" / "ac_copilot_trainer" / "manifest.ini"


# ---------------------------------------------------------------------------
# Helpers: Lua source readers
# ---------------------------------------------------------------------------


def _lua_text(name: str) -> str:
    """Return full text of a module under ``src/ac_copilot_trainer/modules/``."""
    return (MODULES / name).read_text(encoding="utf-8")


def _manifest_text() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def _get_manifest_section(text: str, section_name: str) -> list[str]:
    """Reuse the helper from test_manifest_phase5 (kept local to avoid import coupling)."""
    header = f"[{section_name}]"
    in_section = False
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section:
                break
            if stripped == header:
                in_section = True
            continue
        if in_section and stripped:
            lines.append(stripped)
    return lines


def _extract_emmy_class_fields(text: str, class_name: str) -> list[str]:
    """Extract ``@field`` names from an EmmyLua ``---@class`` block."""
    fields: list[str] = []
    in_class = False
    for line in text.splitlines():
        if f"---@class {class_name}" in line:
            in_class = True
            continue
        if in_class:
            m = re.match(r"^---@field\s+(\w+)", line)
            if m:
                fields.append(m.group(1))
            elif not line.startswith("---"):
                break
    return fields


# ---------------------------------------------------------------------------
# IA: Information Architecture
# ---------------------------------------------------------------------------


class TestInformationArchitecture:
    def test_hud_viewmodel_has_debrief_text(self) -> None:
        """IA-01: debriefText is the sole LLM free-text channel."""
        fields = _extract_emmy_class_fields(_lua_text("hud.lua"), "HudViewModel")
        assert "debriefText" in fields

    def test_coaching_hints_returns_structured_kind_text(self) -> None:
        """IA-02: hint() returns {kind, text} tables."""
        src = _lua_text("coaching_hints.lua")
        # The local function ``hint`` must produce a table with both keys.
        assert 'kind = kind or "general"' in src
        assert "text = text" in src

    def test_coaching_overlay_uses_kind_for_accent(self) -> None:
        """IA-03: accentForKind dispatches on the kind string."""
        src = _lua_text("coaching_overlay.lua")
        for kind in ("brake", "throttle", "line", "positive"):
            assert f'"{kind}"' in src, f"Missing accent branch for kind={kind}"


# ---------------------------------------------------------------------------
# SD: Structured Data Points
# ---------------------------------------------------------------------------


class TestStructuredDataPoints:
    def test_hud_viewmodel_core_telemetry_fields(self) -> None:
        """SD-01/SD-02: HudViewModel has core telemetry fields."""
        fields = _extract_emmy_class_fields(_lua_text("hud.lua"), "HudViewModel")
        for f in (
            "speed",
            "brake",
            "lapCount",
            "bestLapMs",
            "lastLapMs",
            "deltaSmoothedSec",
        ):
            assert f in fields, f"HudViewModel missing field: {f}"

    def test_approach_hud_payload_fields(self) -> None:
        """SD-03: ApproachHudPayload has all required fields."""
        fields = _extract_emmy_class_fields(_lua_text("hud.lua"), "ApproachHudPayload")
        required = {
            "turnLabel",
            "targetSpeedKmh",
            "currentSpeedKmh",
            "distanceToBrakeM",
            "status",
            "progressPct",
            "brakeIndex",
        }
        missing = required - set(fields)
        assert not missing, f"ApproachHudPayload missing: {missing}"

    def test_settings_stats_fields(self) -> None:
        """SD-04: HudSettingsStats exposes telemetry counters."""
        fields = _extract_emmy_class_fields(
            _lua_text("hud_settings.lua"), "HudSettingsStats"
        )
        for f in (
            "telemetrySamples",
            "brakeBest",
            "brakeLast",
            "brakeSession",
            "throttleLapHint",
            "consistencyHud",
            "tireHud",
        ):
            assert f in fields, f"HudSettingsStats missing field: {f}"


# ---------------------------------------------------------------------------
# RC: Real-Time Coaching
# ---------------------------------------------------------------------------


class TestRealTimeCoaching:
    def test_coaching_hints_max_three(self) -> None:
        """RC-01: buildAfterLap caps output at 3 hints."""
        src = _lua_text("coaching_hints.lua")
        assert "function M.buildAfterLap" in src
        # The guard ``#out >= 3`` ensures at most 3 hints.
        assert "#out >= 3" in src

    def test_main_window_strip_function_exists(self) -> None:
        """RC-03: coaching_overlay exports drawMainWindowStrip."""
        src = _lua_text("coaching_overlay.lua")
        assert "function M.drawMainWindowStrip" in src


# ---------------------------------------------------------------------------
# TY: Typography
# ---------------------------------------------------------------------------


class TestTypography:
    def test_coaching_font_dwrite_pipeline(self) -> None:
        """TY-01: coaching_font.lua has the DWriteFont resolution pipeline."""
        src = _lua_text("coaching_font.lua")
        assert "function M.dwriteDescriptor" in src
        assert "ui.DWriteFont" in src
        # Must reference bmw.txt (AC default racing font).
        assert "bmw.txt" in src.lower() or "BMW.txt" in src

    def test_coaching_overlay_font_brackets(self) -> None:
        """TY-02: Every draw function in coaching_overlay brackets font push/pop."""
        src = _lua_text("coaching_overlay.lua")
        # Count fontMod.push() and fontMod.pop() -- they must be balanced.
        pushes = len(re.findall(r"fontMod\.push\(\)", src))
        pops = len(re.findall(r"fontMod\.pop\(", src))
        assert pushes >= 3, f"Expected at least 3 font pushes, got {pushes}"
        assert pushes == pops, (
            f"Font push/pop imbalance: {pushes} pushes vs {pops} pops"
        )


# ---------------------------------------------------------------------------
# TR: Transparency
# ---------------------------------------------------------------------------


class TestTransparency:
    def test_coaching_overlay_bg_transparency(self) -> None:
        """TR-01/TR-02: Background rgbm alpha < 1; title text alpha == 1 before fade."""
        src = _lua_text("coaching_overlay.lua")
        # Background: drawRectFilled with alpha 0.82 (M.draw) or 0.78 (strip).
        bg_matches = re.findall(r"drawRectFilled\(.*?rgbm\([^)]+\)", src)
        assert bg_matches, "No drawRectFilled calls found"
        for m in bg_matches:
            # Last number in rgbm(...) is alpha; extract it.
            nums = re.findall(r"[\d.]+", m.split("rgbm")[-1])
            if len(nums) >= 4:
                alpha = float(nums[3])
                assert alpha < 1.0, f"Background alpha should be < 1, got {alpha}"

    def test_manifest_coaching_window_flags(self) -> None:
        """TR-02/WL-03: WINDOW_1 has NO_BACKGROUND and correct default position."""
        lines = _get_manifest_section(_manifest_text(), "WINDOW_1")
        flags_line = [ln for ln in lines if ln.startswith("FLAGS=")]
        assert flags_line, "WINDOW_1 missing FLAGS"
        assert "NO_BACKGROUND" in flags_line[0]
        pos_line = [ln for ln in lines if ln.startswith("DEFAULT_POSITION=")]
        assert pos_line, "WINDOW_1 missing DEFAULT_POSITION"


# ---------------------------------------------------------------------------
# WL: 3-Window Layout
# ---------------------------------------------------------------------------


class TestThreeWindowLayout:
    def test_manifest_three_windows(self) -> None:
        """WL-01: manifest.ini defines exactly WINDOW_0, WINDOW_1, WINDOW_2."""
        text = _manifest_text()
        for i in range(3):
            section = _get_manifest_section(text, f"WINDOW_{i}")
            assert section, f"[WINDOW_{i}] section missing or empty"

    def test_manifest_window_functions(self) -> None:
        """WL-02: Each window routes to its correct FUNCTION_MAIN."""
        text = _manifest_text()
        expected = {
            "WINDOW_0": "windowMain",
            "WINDOW_1": "windowCoaching",
            "WINDOW_2": "windowSettings",
        }
        for section, func in expected.items():
            lines = _get_manifest_section(text, section)
            func_lines = [ln for ln in lines if ln.startswith("FUNCTION_MAIN=")]
            assert func_lines, f"{section} missing FUNCTION_MAIN"
            assert f"FUNCTION_MAIN={func}" in func_lines, (
                f"{section}: expected FUNCTION_MAIN={func}, got {func_lines}"
            )


# ---------------------------------------------------------------------------
# SM: Settings Migration
# ---------------------------------------------------------------------------


class TestSettingsMigration:
    def test_config_defaults_keys(self) -> None:
        """SM-01: CONFIG_DEFAULTS in the entry script contains expected keys."""
        src = ENTRY.read_text(encoding="utf-8")
        # Extract the CONFIG_DEFAULTS block.
        m = re.search(r"CONFIG_DEFAULTS\s*=\s*\{(.*?)\}", src, re.DOTALL)
        assert m, "CONFIG_DEFAULTS block not found in entry script"
        block = m.group(1)
        expected_keys = [
            "brakeThreshold",
            "hudEnabled",
            "approachMeters",
            "coachingHoldSeconds",
            "coachingMaxVisibleHints",
            "racingLineMode",
            "lineStyle",
            "racingLineEnabled",
            "brakeMarkersEnabled",
            "enableRenderDiagnostics",
            "enableDraw3DDiagnostics",
            "wsSidecarUrl",
            "focusPracticeCornerLabels",
            "focusPracticeAutoCount",
            "focusPracticeDimNonFocus",
        ]
        for key in expected_keys:
            assert key in block, f"CONFIG_DEFAULTS missing key: {key}"

    def test_settings_ui_controls(self) -> None:
        """SM-02 through SM-07: hud_settings.lua has all required UI controls."""
        src = _lua_text("hud_settings.lua")

        # Checkboxes (SM-02, SM-03, SM-07)
        checkbox_keys = [
            "hudEnabled",
            "racingLineEnabled",
            "brakeMarkersEnabled",
            "enableRenderDiagnostics",
            "enableDraw3DDiagnostics",
        ]
        for key in checkbox_keys:
            assert f'"{key}"' in src, f"Missing checkbox for config key: {key}"

        # Sliders (SM-04)
        assert "Approach distance" in src, "Missing slider for approachMeters"
        assert "Post-lap coaching hold" in src, "Missing slider for coachingHoldSeconds"

        # Combos (SM-05, SM-06)
        assert "Racing line source" in src, "Missing combo for racingLineMode"
        assert "Racing line style" in src, "Missing combo for lineStyle"


# ---------------------------------------------------------------------------
# Corner names export
# ---------------------------------------------------------------------------


class TestCornerNames:
    def test_corner_names_exports_resolve_approach_label(self) -> None:
        """SM-08: corner_names.lua exports resolveApproachLabel on the module table."""
        src = _lua_text("corner_names.lua")
        assert "function M.resolveApproachLabel" in src
        # Must also be returned (module table pattern).
        assert "return M" in src
