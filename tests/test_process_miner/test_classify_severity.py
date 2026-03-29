"""Tests for severity classification heuristics."""

from __future__ import annotations

from tools.process_miner.analyze import classify_severity


def test_severity_avoids_substring_false_positives() -> None:
    assert classify_severity("Add debug logging here") != "bug"
    assert classify_severity("Fix the checkout session token") != "maintainability"


def test_severity_still_matches_intent() -> None:
    assert classify_severity("This is a bug in production") == "bug"
    assert classify_severity("Add a unit test for this path") == "maintainability"
