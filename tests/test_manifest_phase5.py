"""Manifest expectations for Phase 5 multi-window layout (issue #57)."""

from __future__ import annotations

from pathlib import Path


def test_manifest_defines_settings_window() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "ac_copilot_trainer" / "manifest.ini").read_text(encoding="utf-8")
    assert "[WINDOW_2]" in text
    assert "NAME=Settings" in text
    assert "FUNCTION_MAIN=windowSettings" in text
