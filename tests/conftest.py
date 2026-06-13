"""Shared pytest fixtures for the AC Copilot Trainer test suite (issue #154 Part C)."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "llm_live: exercises a live Ollama endpoint (nondeterministic); deselected by default.",
    )


@pytest.fixture
def disable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the deterministic coaching path: no Ollama ``debrief`` on coaching_response.

    The sidecar attaches a ``debrief`` field only when ``AC_COPILOT_OLLAMA_ENABLE`` is
    truthy (``tools/ai_sidecar/coaching/llm_coach.py:debrief_feature_enabled``). Golden
    coaching_response tests must run with it unset so the wire payload is deterministic.
    """
    monkeypatch.delenv("AC_COPILOT_OLLAMA_ENABLE", raising=False)
