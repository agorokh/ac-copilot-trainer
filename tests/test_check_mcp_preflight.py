"""Tests for scripts/check_mcp_preflight.py MCP launch preconditions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def preflight_mod():
    import importlib.util

    path = REPO_ROOT / "scripts" / "check_mcp_preflight.py"
    spec = importlib.util.spec_from_file_location("check_mcp_preflight_test", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_mcp_json(root: Path, servers: dict) -> None:
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def _wrapper_server() -> dict:
    return {
        "command": "bash",
        "args": ["scripts/mcp/repo-knowledge.sh"],
        "env": {"REPO_KNOWLEDGE_DB": ".cache/repo_knowledge/knowledge.db"},
    }


def test_no_mcp_json_passes(tmp_path: Path, preflight_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight_mod, "_repo_root", lambda: tmp_path)
    assert preflight_mod.main() == 0


def test_no_wrapper_server_passes(
    tmp_path: Path, preflight_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_mcp_json(
        tmp_path, {"agentic-memory": {"command": "bash", "args": ["scripts/mcp/agentic-memory.sh"]}}
    )
    monkeypatch.setattr(preflight_mod, "_repo_root", lambda: tmp_path)
    assert preflight_mod.main() == 0


def test_wrapper_with_importable_mcp_passes(
    tmp_path: Path, preflight_mod, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_mcp_json(tmp_path, {"repo-knowledge": _wrapper_server()})
    monkeypatch.setattr(preflight_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(preflight_mod, "_resolve_wrapper_python", lambda root, env: "/fake/python")
    monkeypatch.setattr(preflight_mod, "_can_import", lambda py, mod: True)
    assert preflight_mod.main() == 0


def test_wrapper_with_missing_mcp_fails(
    tmp_path: Path, preflight_mod, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _write_mcp_json(tmp_path, {"repo-knowledge": _wrapper_server()})
    monkeypatch.setattr(preflight_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(preflight_mod, "_resolve_wrapper_python", lambda root, env: "/fake/python")
    monkeypatch.setattr(preflight_mod, "_can_import", lambda py, mod: False)
    assert preflight_mod.main() == 1
    assert "pip install -e '.[knowledge]'" in capsys.readouterr().err


def test_resolve_prefers_venv_python(tmp_path: Path, preflight_mod) -> None:
    venv_py = tmp_path / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.touch()
    venv_py.chmod(0o755)
    assert preflight_mod._resolve_wrapper_python(tmp_path, {}) == str(venv_py)


def test_resolve_honors_override(tmp_path: Path, preflight_mod) -> None:
    custom = tmp_path / "custom" / "python"
    custom.parent.mkdir()
    custom.touch()
    custom.chmod(0o755)
    env = {"REPO_KNOWLEDGE_PYTHON": str(custom)}
    assert preflight_mod._resolve_wrapper_python(tmp_path, env) == str(custom)


def test_can_import_uses_returncode(preflight_mod, monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.returncode = 1
    monkeypatch.setattr(preflight_mod.subprocess, "run", lambda *a, **k: proc)
    assert preflight_mod._can_import("/fake/python", "mcp") is False
