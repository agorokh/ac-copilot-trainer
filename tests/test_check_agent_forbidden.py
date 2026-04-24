"""Tests for scripts/check_agent_forbidden.py layout allowlist."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def check_agent_mod():
    import importlib.util

    path = REPO_ROOT / "scripts" / "check_agent_forbidden.py"
    spec = importlib.util.spec_from_file_location("check_agent_forbidden_test", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_ls_files(paths: list[str]) -> MagicMock:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = "\n".join(paths) + ("\n" if paths else "")
    proc.stderr = ""
    return proc


def test_reports_top_level_allowed(monkeypatch: pytest.MonkeyPatch, check_agent_mod) -> None:
    monkeypatch.setattr(
        check_agent_mod.subprocess,
        "run",
        lambda *a, **k: _fake_ls_files(["reports/process_miner/out.md", "src/x.py"]),
    )
    assert check_agent_mod.main() == 0


def test_unknown_top_level_rejected(monkeypatch: pytest.MonkeyPatch, check_agent_mod) -> None:
    monkeypatch.setattr(
        check_agent_mod.subprocess,
        "run",
        lambda *a, **k: _fake_ls_files(["vendor/pkg/foo.py"]),
    )
    assert check_agent_mod.main() == 1
