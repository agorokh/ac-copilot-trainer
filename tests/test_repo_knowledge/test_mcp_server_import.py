"""Optional MCP server import smoke (requires ``[knowledge]`` extra)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_MCP_NAMESPACE = (REPO_ROOT / "scripts" / "mcp").resolve()


def _installed_mcp_available() -> bool:
    spec = importlib.util.find_spec("mcp")
    if spec is None:
        return False
    locations = [Path(p).resolve() for p in spec.submodule_search_locations or []]
    if spec.origin is None and locations and all(p == REPO_MCP_NAMESPACE for p in locations):
        return False
    return True


if not _installed_mcp_available():
    pytest.skip("requires installed mcp package from [knowledge]", allow_module_level=True)


def test_mcp_server_module_imports() -> None:
    import tools.repo_knowledge.mcp_server as m

    assert m.mcp is not None
