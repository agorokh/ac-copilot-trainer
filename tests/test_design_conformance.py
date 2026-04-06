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
        """PE-01: hud.lua requires coaching_font with balanced push/pop."""
        src = _lua_text("hud.lua")
        assert 'require("coaching_font")' in src
        assert "fontMod.pushNamed" in src
        assert "fontMod.pop" in src
        # Verify pushNamed return value is captured (not discarded)
        assert re.search(r"local\s+\w+K?\s*=\s*fontMod\.pushNamed", src), (
            "pushNamed return value must be captured for pop(kind)"
        )
        # Verify pop receives an argument (not bare pop())
        assert re.search(r"fontMod\.pop\(\w+", src), (
            "fontMod.pop must receive kind argument from pushNamed"
        )

    def test_active_suggestion_panel_exists(self) -> None:
        """PE-02: drawActiveSuggestion function renders the panel."""
        src = _lua_text("hud.lua")
        assert "drawActiveSuggestion" in src
        assert '"ACTIVE SUGGESTION"' in src

    def test_panel_design_tokens(self) -> None:
        """PE-03: Panel uses design tokens matching Figma spec; text 100% opaque."""
        src = _lua_text("hud.lua")
        assert re.search(r"COLOR_BG\s*=\s*rgbm\([^)]+0\.60\)", src), (
            "COLOR_BG must use 0.60 alpha (Figma: rgba(17,17,17,0.6))"
        )
        assert "PANEL_ROUNDING" in src
        assert "COLOR_TITLE" in src
        # Text must be 100% opaque (only background fades)
        assert re.search(r"textAlpha\s*=\s*1\.0", src), (
            "textAlpha must be 1.0 (text 100% opaque per design brief)"
        )

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

    def test_debrief_text_field_wired(self) -> None:
        """PE-07 (issue #69): HudViewModel.debriefText is declared and referenced.

        Per issue #69 user feedback, the debrief paragraph must NOT be rendered
        inside WINDOW_0 (it was stomping on the Active Suggestion panel). The
        field stays in the viewmodel contract and is read (so the entry script
        can continue passing it) but rendering happens in the coaching window
        sidecar instead (see `coachingOverlay.drawSidecarDebrief`).
        """
        src = _lua_text("hud.lua")
        fields = _extract_emmy_class_fields(src, "HudViewModel")
        assert "debriefText" in fields, "debriefText field missing from HudViewModel"
        # Field is still referenced so the entry-script handoff stays valid
        assert "vm.debriefText" in src, "vm.debriefText not consumed in hud.lua"


# ---------------------------------------------------------------------------
# Issue #69: visual design match (PE-08..PE-11, PC-09..PC-13)
# ---------------------------------------------------------------------------


class TestIssue69VisualDesignMatch:
    """Pin the Figma visual spec that the in-game screenshots violated.

    User feedback that drove these tests:
      - TARGET ENTRY and CURRENT must share a single box (not two columns)
      - Active Suggestion must own WINDOW_0 (no delta bar / lap summary / coaching strip pile-up)
      - Progress bar must be visible (taller, red fill against dark bg)
      - Post-lap coaching strip must not cover the Active Suggestion panel
      - Panel must use Syncopate/Michroma/Montserrat + AG PORSCHE ACADEMY footer
    """

    # ------- Top tile (hud.lua Active Suggestion) --------------------------

    def test_pe08_top_tile_full_window_panel(self) -> None:
        """PE-08: Top tile draws across the full window (not cramped mid-column)."""
        src = _lua_text("hud.lua")
        # Panel fills the full window: drawRectFilled(vec2(0, 0), vec2(w, h), ...)
        assert re.search(
            r"drawRectFilled\(\s*vec2\(0,\s*0\),\s*vec2\(w,\s*h\)",
            src,
        ), "top tile must fill the entire window"

    def test_pe09_top_tile_no_legacy_stackup(self) -> None:
        """PE-09: Top tile must not render legacy delta bar / post-lap strip / coaching."""
        src = _lua_text("hud.lua")
        # The stacked blocks from pre-#69 must be gone:
        assert "drawDeltaBar" not in src, "legacy delta bar must be removed from WINDOW_0"
        assert "drawMainWindowStrip" not in src, (
            "legacy coaching strip must NOT be called from hud.lua (belongs in WINDOW_1)"
        )
        assert "vm.postLapLines" not in src, (
            "post-lap lines must not be rendered in WINDOW_0 (they stomp on Active Suggestion)"
        )
        assert "vm.setupChangeMsg" not in src, "setup change msg removed from WINDOW_0"
        assert "vm.tireLockupFlash" not in src, "tire lockup flash removed from WINDOW_0"
        assert "vm.autoSetupLine" not in src, "auto setup line removed from WINDOW_0"

    def test_pe10_top_tile_uses_shared_tokens(self) -> None:
        """PE-10: Top tile imports shared design tokens from coaching_overlay."""
        src = _lua_text("hud.lua")
        assert re.search(r"coachingOverlay\.tokens", src), (
            "hud.lua must consume coachingOverlay.tokens for shared design tokens"
        )

    def test_pe11_top_tile_red_title_and_amber_secondary(self) -> None:
        """PE-11: Title is red (#EF4444) and the amber token is defined for secondary hints."""
        src = _lua_text("hud.lua")
        # Red title: rgbm matching #EF4444 (0.937, 0.267, 0.267)
        assert re.search(
            r"COLOR_RED\s*=\s*rgbm\(0\.93[0-9]*,\s*0\.26[0-9]*,\s*0\.26[0-9]*",
            src,
        ), "COLOR_RED must be #EF4444"
        assert re.search(
            r"COLOR_AMBER\s*=\s*rgbm\(1\.00[0-9]*,\s*0\.76[0-9]*",
            src,
        ), "COLOR_AMBER must be #FFC43D"

    # ------- Bottom tile (coaching_overlay.drawApproachPanel) --------------

    def test_pc09_bottom_tile_status_gate(self) -> None:
        """PC-09: Bottom tile only renders when approachData.status == 'approaching'."""
        src = _lua_text("coaching_overlay.lua")
        assert re.search(
            r'status\s+or\s+""\)\s*~=\s*"approaching"',
            src,
        ), "drawApproachPanel must gate on status == 'approaching'"

    def test_pc10_bottom_tile_shared_target_current_box(self) -> None:
        """PC-10: TARGET ENTRY and CURRENT share a single visual box (per user feedback)."""
        src = _lua_text("coaching_overlay.lua")
        # Find the drawApproachPanel body
        m = re.search(
            r"function M\.drawApproachPanel.*?return true",
            src,
            flags=re.DOTALL,
        )
        assert m, "drawApproachPanel body not found"
        body = m.group(0)
        # Must have a rightBoxX / rightBoxW / rightBoxH frame
        assert "rightBoxX" in body and "rightBoxW" in body and "rightBoxH" in body, (
            "shared right-hand box must be explicitly framed"
        )
        # Both TARGET ENTRY and CURRENT must be positioned INSIDE that box
        assert re.search(r'"TARGET ENTRY"', body) and re.search(r'"CURRENT"', body)
        # A vertical divider between the two sub-columns
        assert re.search(
            r"rightBoxX\s*\+\s*subColW",
            body,
        ), "vertical divider between TARGET ENTRY and CURRENT must exist"

    def test_pc11_bottom_tile_red_progress_bar(self) -> None:
        """PC-11: Progress bar fill is red #EF4444, not cyan."""
        src = _lua_text("coaching_overlay.lua")
        assert re.search(
            r"COLOR_BAR_FILL\s*=\s*rgbm\(0\.93[0-9]*,\s*0\.26[0-9]*,\s*0\.26[0-9]*",
            src,
        ), "COLOR_BAR_FILL must be red (#EF4444)"

    def test_pc12_bottom_tile_tall_progress_bar(self) -> None:
        """PC-12: Progress bar is at least 12 px tall (was 8 px, invisible)."""
        src = _lua_text("coaching_overlay.lua")
        m = re.search(r"function M\.drawApproachPanel.*?return true", src, flags=re.DOTALL)
        assert m
        body = m.group(0)
        bar_h_match = re.search(r"local\s+barH\s*=\s*(\d+)", body)
        assert bar_h_match, "barH not assigned in drawApproachPanel"
        assert int(bar_h_match.group(1)) >= 12, (
            f"progress bar must be >= 12 px tall, got {bar_h_match.group(1)}"
        )

    def test_pc13_bottom_tile_footer_text(self) -> None:
        """PC-13: Footer reads 'AG PORSCHE ACADEMY' (not 'AC COPILOT TRAINER')."""
        src = _lua_text("coaching_overlay.lua")
        m = re.search(r"function M\.drawApproachPanel.*?return true", src, flags=re.DOTALL)
        assert m
        body = m.group(0)
        assert '"AG PORSCHE ACADEMY"' in body, "footer must read AG PORSCHE ACADEMY"
        assert '"AC COPILOT TRAINER"' not in body, "legacy 'AC COPILOT TRAINER' footer must be gone"

    def test_pc14_bottom_tile_tokens_exported(self) -> None:
        """PC-14: coaching_overlay exports M.tokens table for shared consumption."""
        src = _lua_text("coaching_overlay.lua")
        assert re.search(
            r"M\.tokens\s*=\s*\{",
            src,
        ), "coaching_overlay must export M.tokens table"
        # Must include the keys that hud.lua consumes
        for key in ("COLOR_BG", "COLOR_RED", "COLOR_AMBER", "COLOR_LABEL_GREY", "PANEL_ROUNDING"):
            assert re.search(
                rf"{key}\s*=\s*{key}",
                src,
            ), f"M.tokens missing key {key}"


# ---------------------------------------------------------------------------
# Issue #69: manifest window flags
# ---------------------------------------------------------------------------


class TestIssue69ManifestFlags:
    """WINDOW_0 must be transparent and WINDOW_1 must NOT auto-resize."""

    def test_mf01_window0_no_background(self) -> None:
        """MF-01: WINDOW_0 has NO_BACKGROUND so custom panel owns the chrome."""
        lines = _get_manifest_section(_manifest_text(), "WINDOW_0")
        flags_line = [ln for ln in lines if ln.startswith("FLAGS=")]
        assert flags_line, "WINDOW_0 missing FLAGS"
        assert "NO_BACKGROUND" in flags_line[0], (
            "WINDOW_0 must use NO_BACKGROUND so custom panel is not double-tinted"
        )

    def test_mf02_window1_no_auto_resize(self) -> None:
        """MF-02: WINDOW_1 must NOT use AUTO_RESIZE (caused the cramped panel)."""
        lines = _get_manifest_section(_manifest_text(), "WINDOW_1")
        flags_line = [ln for ln in lines if ln.startswith("FLAGS=")]
        assert flags_line, "WINDOW_1 missing FLAGS"
        assert "AUTO_RESIZE" not in flags_line[0], (
            "WINDOW_1 must NOT use AUTO_RESIZE (it squeezed the panel into a tiny box)"
        )
        assert "NO_BACKGROUND" in flags_line[0], "WINDOW_1 must use NO_BACKGROUND"

    def test_mf03_window_sizes_match_spec(self) -> None:
        """MF-03: Main + coaching window sizes match Figma layout (issue #69)."""
        text = _manifest_text()
        w0 = _get_manifest_section(text, "WINDOW_0")
        w1 = _get_manifest_section(text, "WINDOW_1")
        size0 = next(ln for ln in w0 if ln.startswith("SIZE="))
        size1 = next(ln for ln in w1 if ln.startswith("SIZE="))
        assert size0 == "SIZE=480,180", f"WINDOW_0 SIZE expected 480,180, got {size0!r}"
        assert size1 == "SIZE=520,280", f"WINDOW_1 SIZE expected 520,280, got {size1!r}"
