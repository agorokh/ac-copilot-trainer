"""Tests for preventability classification heuristics."""

from __future__ import annotations

from tools.process_miner.analyze import classify_preventability


def test_preventability_avoids_substring_false_positives() -> None:
    assert classify_preventability("This is important for reviewers") != "automation"
    assert classify_preventability("See information in the ticket") != "automation"


def test_preventability_still_matches_intended_tokens() -> None:
    assert classify_preventability("Please add an import for logging") == "automation"
    assert classify_preventability("Use consistent code format in this module") == "automation"
