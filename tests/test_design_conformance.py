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
        stripped = raw.split(";", 1)[0].split("#", 1)[0].strip()
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
    class_decl = re.compile(rf"^---@class\s+{re.escape(class_name)}\b")
    for line in text.splitlines():
        if class_decl.match(line.lstrip()):
            in_class = True
            continue
        if in_class:
            m = re.search(r"---@field\s+(\w+)", line)
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
        assert re.search(r'kind\s*=\s*kind\s*or\s*"general"', src)
        assert re.search(r"text\s*=\s*text", src)

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
        fields = _extract_emmy_class_fields(_lua_text("hud_settings.lua"), "HudSettingsStats")
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
        assert re.search(r"#out\s*>=\s*3", src)

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
        """TY-02: Each ``M.draw*`` function balances fontMod push/pop within its body."""
        src = _lua_text("coaching_overlay.lua")
        draw_funcs = list(re.finditer(r"^function\s+M\.(draw\w*)\s*\(", src, flags=re.MULTILINE))
        assert draw_funcs, "No M.draw* functions found in coaching_overlay.lua"

        total_pushes = 0
        for i, match in enumerate(draw_funcs):
            name = match.group(1)
            start = match.start()
            end_pos = draw_funcs[i + 1].start() if i + 1 < len(draw_funcs) else len(src)
            body = src[start:end_pos]
            # Count both push() and pushNamed() as font pushes
            pushes = len(re.findall(r"fontMod\.push(?:Named)?\(", body))
            pops = len(re.findall(r"fontMod\.pop\(", body))
            total_pushes += pushes
            assert pushes == pops, (
                f"M.{name} font push/pop imbalance: {pushes} pushes vs {pops} pops"
            )
            assert pushes > 0, f"M.{name} must call fontMod.push at least once"

        assert total_pushes >= 3, f"Expected at least 3 font pushes total, got {total_pushes}"


# ---------------------------------------------------------------------------
# TR: Transparency
# ---------------------------------------------------------------------------


class TestTransparency:
    def test_coaching_overlay_bg_transparency(self) -> None:
        """TR-01: Panel fill alphas stay below 1; title uses ``computeAlpha`` (1.0 until fade)."""
        src = _lua_text("coaching_overlay.lua")
        assert re.search(
            r"if\s+rem\s*>=\s*fadeWindow\s+then\s*\n\s*return\s+1\.0",
            src,
        ), "computeAlpha should return 1.0 before fade window"
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
        _, pos_val = pos_line[0].split("=", 1)
        px, py = (float(x.strip()) for x in pos_val.split(",", 1))
        assert px > 0.5 and py < 0.25, (
            f"WINDOW_1 DEFAULT_POSITION should be top-right-ish, got {px},{py}"
        )


# ---------------------------------------------------------------------------
# WL: 3-Window Layout
# ---------------------------------------------------------------------------


class TestThreeWindowLayout:
    def test_manifest_three_windows(self) -> None:
        """WL-01: manifest.ini defines exactly WINDOW_0..WINDOW_2 (no other WINDOW_*)."""
        text = _manifest_text()
        expected_sections = {f"WINDOW_{i}" for i in range(3)}
        actual_sections = {
            m.group(1) for m in re.finditer(r"^\[(WINDOW_\d+)\]\s*$", text, re.MULTILINE)
        }
        assert actual_sections == expected_sections, (
            f"Expected window sections {sorted(expected_sections)}, got {sorted(actual_sections)}"
        )
        for section_name in expected_sections:
            section = _get_manifest_section(text, section_name)
            assert section, f"[{section_name}] section missing or empty"

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


# ---------------------------------------------------------------------------
# Part C: Approach telemetry panel (issue #57)
# ---------------------------------------------------------------------------


class TestApproachPanel:
    """Issue #57 Part C: polished approach telemetry panel in WINDOW_1."""

    def test_draw_approach_panel_exists(self) -> None:
        """PC-01: coaching_overlay exports drawApproachPanel."""
        src = _lua_text("coaching_overlay.lua")
        assert "function M.drawApproachPanel" in src

    def test_approach_panel_speed_color_logic(self) -> None:
        """PC-02: speedColor maps delta > 8 to red, delta <= 0 to green, else white."""
        src = _lua_text("coaching_overlay.lua")
        # Find the full speedColor function (greedy to last 'end')
        m = re.search(
            r"(function\s+speedColor\s*\([^)]*\).*?\nend)",
            src,
            flags=re.DOTALL,
        )
        assert m, "speedColor function must exist in coaching_overlay.lua"
        body = m.group(1)
        assert re.search(r"delta\s*>\s*8", body), "speedColor must use 8 km/h threshold"
        assert "COLOR_RED" in body, "delta > 8 must map to COLOR_RED"
        assert "COLOR_GREEN" in body, "delta <= 0 must map to COLOR_GREEN"
        assert "COLOR_WHITE" in body, "within-band delta must map to COLOR_WHITE"

    def test_approach_panel_progress_bar(self) -> None:
        """PC-03: drawProgressBar renders fill based on pct with clamping."""
        src = _lua_text("coaching_overlay.lua")
        assert re.search(r"function\s+drawProgressBar\s*\(", src), (
            "drawProgressBar function must exist"
        )
        assert "COLOR_BAR_FILL" in src, "Progress bar must use COLOR_BAR_FILL"
        assert "COLOR_BAR_BG" in src, "Progress bar must use COLOR_BAR_BG"
        # pct must scale fill width
        assert re.search(r"pct\).*?\*\s*w", src), "drawProgressBar must scale fill width by pct"
        # pct must be clamped
        assert re.search(r"math\.(?:max|min)\s*\([^)]*pct[^)]*\)", src), (
            "drawProgressBar must clamp pct via math.max/min"
        )

    def test_approach_panel_design_tokens(self) -> None:
        """PC-04: design tokens match Figma brief."""
        src = _lua_text("coaching_overlay.lua")
        assert "COLOR_RED" in src, "Must define COLOR_RED design token"
        assert re.search(r"COLOR_BG\s*=\s*rgbm\([^)]+0\.60\)", src), (
            "COLOR_BG must use 0.60 alpha (Figma: rgba(17,17,17,0.6))"
        )

    def test_approach_panel_font_roles(self) -> None:
        """PC-05: approach panel uses named font roles for numbers and labels."""
        src = _lua_text("coaching_overlay.lua")
        assert 'pushNamed("numbers"' in src, (
            "Approach panel must use 'numbers' font role for speed values"
        )
        assert 'pushNamed("labels"' in src, (
            "Approach panel must use 'labels' font role for section labels"
        )
        assert 'pushNamed("brand"' in src, "Approach panel must use 'brand' font role for footer"

    def test_coaching_font_multi_font_support(self) -> None:
        """PC-06: coaching_font.lua supports named font roles with fallbacks."""
        src = _lua_text("coaching_font.lua")
        assert "function M.namedDescriptor" in src
        assert "function M.pushNamed" in src
        # Primary role fonts
        assert '"Michroma"' in src, "Must try Michroma for numbers font"
        assert '"Montserrat"' in src, "Must try Montserrat for labels font"
        assert '"Syncopate"' in src, "Must try Syncopate for brand font"
        # Windows-safe fallbacks
        assert '"Consolas"' in src, "Must include Windows-safe fallback for numbers"
        assert '"Segoe UI"' in src, "Must include Windows-safe fallback for labels/brand"

    def test_window_coaching_calls_approach_panel(self) -> None:
        """PC-07: windowCoaching in entry script calls drawApproachPanel."""
        src = ENTRY.read_text(encoding="utf-8")
        assert "drawApproachPanel" in src
        assert "approachHudData" in src

    def test_approach_panel_font_push_pop_balance(self) -> None:
        """PC-08: drawApproachPanel balances all font push/pop calls."""
        src = _lua_text("coaching_overlay.lua")
        m = re.search(
            r"function\s+M\.drawApproachPanel\s*\(.*?\)\s*\n(.*?)^end",
            src,
            re.MULTILINE | re.DOTALL,
        )
        assert m, "drawApproachPanel function not found"
        body = m.group(1)
        pushes = len(re.findall(r"fontMod\.push(?:Named)?\(", body))
        pops = len(re.findall(r"fontMod\.pop\(", body))
        assert pushes == pops, (
            f"drawApproachPanel font push/pop imbalance: {pushes} pushes vs {pops} pops"
        )
        assert pushes >= 5, f"drawApproachPanel should push at least 5 font roles, got {pushes}"


# ---------------------------------------------------------------------------
# Part D: Real-time coaching engine (PD-01 through PD-08)
# ---------------------------------------------------------------------------


class TestRealTimeCoachingEngine:
    """PD-01..PD-08: Real-time coaching engine structural conformance."""

    def test_realtime_coaching_module_exists(self) -> None:
        """PD-01: realtime_coaching.lua exists and exports core functions."""
        src = _lua_text("realtime_coaching.lua")
        assert "function M.tick" in src
        assert "function M.reset" in src
        assert "function M.rebuildSegmentIndex" in src

    def test_realtime_coaching_five_phases(self) -> None:
        """PD-02: State machine has all 5 phase string literals."""
        src = _lua_text("realtime_coaching.lua")
        for p in ["straight", "approaching", "braking", "corner", "exiting"]:
            assert (chr(34) + p + chr(34)) in src, f"Phase {p!r} not found in realtime_coaching.lua"

    def test_realtime_coaching_bucket_index(self) -> None:
        """PD-03: O(1) spline lookup via quantized buckets."""
        src = _lua_text("realtime_coaching.lua")
        assert "NUM_BUCKETS" in src, "Bucket constant missing"
        assert "buckets" in src, "Bucket array missing"
        assert re.search(r"math\.floor.*NUM_BUCKETS", src), "Bucket quantization formula missing"

    def test_realtime_coaching_dedup(self) -> None:
        """PD-04: Dedup per corner per lap (key = label_lapCount)."""
        src = _lua_text("realtime_coaching.lua")
        assert "hintShownThisLap" in src, "Dedup map missing"
        assert re.search(r"cornerLabel.*tostring.*lapCount", src), (
            "Dedup key pattern (label + lap) missing"
        )

    def test_coaching_hints_build_realtime(self) -> None:
        """PD-05: coaching_hints.lua exports M.buildRealTime."""
        src = _lua_text("coaching_hints.lua")
        assert "function M.buildRealTime" in src
        assert "cornerLabel" in src
        # Verify it reuses the same comparison thresholds as buildAfterLap
        assert "ENTRY_SPEED_DELTA" in src, (
            "Entry speed threshold constant missing in coaching_hints.lua"
        )

    def test_entry_script_requires_realtime_coaching(self) -> None:
        """PD-06: Entry script requires and wires realtime_coaching."""
        src = ENTRY.read_text(encoding="utf-8")
        assert 'require("realtime_coaching")' in src
        assert "realtimeCoaching.tick" in src
        assert "realtimeCoaching.reset" in src
        assert "realtimeCoaching.rebuildSegmentIndex" in src

    def test_hud_viewmodel_realtime_hint_field(self) -> None:
        """PD-07: HudViewModel has realtimeHint field and hud.lua renders it."""
        hud_src = _lua_text("hud.lua")
        assert "realtimeHint" in hud_src, "realtimeHint field missing from HudViewModel"
        assert "vm.realtimeHint" in hud_src, "hud.lua does not render realtimeHint"

    def test_realtime_coaching_hint_cleared_on_exit(self) -> None:
        """PD-08: activeHint is cleared when phase transitions to straight."""
        src = _lua_text("realtime_coaching.lua")
        # After exiting or braking->straight, activeHint should be set to nil
        assert re.search(r"activeHint\s*=\s*nil", src), "activeHint not cleared on phase transition"


# ---------------------------------------------------------------------------
# Part E: Active suggestion window (PE-01 through PE-06)
# ---------------------------------------------------------------------------


class TestActiveSuggestionWindow:
    """PE-01..PE-06: Active suggestion panel structural conformance."""

    def test_hud_uses_coaching_font(self) -> None:
        """PE-01: hud.lua requires coaching_font for named font roles."""
        src = _lua_text("hud.lua")
        assert 'require("coaching_font")' in src
        assert "fontMod.pushNamed" in src
        assert "fontMod.pop" in src

    def test_active_suggestion_panel_exists(self) -> None:
        """PE-02: drawActiveSuggestion function renders the panel."""
        src = _lua_text("hud.lua")
        assert "drawActiveSuggestion" in src
        assert '"ACTIVE SUGGESTION"' in src

    def test_panel_design_tokens(self) -> None:
        """PE-03: Panel uses design tokens matching Figma spec."""
        src = _lua_text("hud.lua")
        assert re.search(r"COLOR_BG\s*=\s*rgbm\([^)]+0\.60\)", src), (
            "COLOR_BG must use 0.60 alpha (Figma: rgba(17,17,17,0.6))"
        )
        assert "PANEL_ROUNDING" in src
        assert "COLOR_TITLE" in src

    def test_fade_behavior(self) -> None:
        """PE-04: Hint fades smoothly using fadeAlpha and FADE_SPEED."""
        src = _lua_text("hud.lua")
        assert "fadeAlpha" in src, "Fade alpha state missing"
        assert "FADE_SPEED" in src, "Fade speed constant missing"
        assert re.search(r"fadeAlpha.*fadeTarget", src), "Fade interpolation logic missing"

    def test_focus_practice_integration(self) -> None:
        """PE-05: Focus practice indicator integrated in panel."""
        src = _lua_text("hud.lua")
        assert "focusPracticeActive" in src
        assert "focusPracticeLabel" in src
        assert '"Focus: "' in src

    def test_panel_hidden_when_no_hint(self) -> None:
        """PE-06: Panel returns early when fadeAlpha is near zero."""
        src = _lua_text("hud.lua")
        assert re.search(r"fadeAlpha\s*<\s*0\.01", src), (
            "Panel must exit early when fade alpha is near zero"
        )
