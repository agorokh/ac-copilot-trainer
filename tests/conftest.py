"""Shared pytest fixtures for the AC Copilot Trainer test suite (issue #154 Part C)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_script_module(module_name: str, path: Path) -> ModuleType:
    """Load a repo script by file path without putting ``scripts/`` on ``sys.path``."""
    cached = sys.modules.get(module_name)
    if isinstance(cached, ModuleType):
        return cached
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {module_name} at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


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
