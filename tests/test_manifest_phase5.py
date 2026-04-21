"""Manifest expectations for Phase 5 multi-window layout (issue #57)."""

from __future__ import annotations

from pathlib import Path


def _get_manifest_section(text: str, section_name: str) -> list[str]:
    section_header = f"[{section_name}]"
    in_section = False
    section_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section:
                break
            if stripped == section_header:
                in_section = True
            continue
        if in_section and stripped:
            section_lines.append(stripped)

    return section_lines


def test_manifest_defines_settings_window() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "ac_copilot_trainer" / "manifest.ini").read_text(encoding="utf-8")
    window_2_lines = _get_manifest_section(text, "WINDOW_2")

    assert window_2_lines, "Expected [WINDOW_2] section in manifest.ini"
    assert "NAME=Settings" in window_2_lines
    assert "FUNCTION_MAIN=windowSettings" in window_2_lines
