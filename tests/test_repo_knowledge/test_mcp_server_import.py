"""Optional MCP server import smoke (requires ``[knowledge]`` extra)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_MCP_NAMESPACE = (REPO_ROOT / "scripts" / "mcp").resolve()


def _fastmcp_available() -> bool:
    spec = importlib.util.find_spec("mcp")
    if spec is None:
        return False
    locations = [Path(p).resolve() for p in spec.submodule_search_locations or []]
    if spec.origin is None and locations and all(p == REPO_MCP_NAMESPACE for p in locations):
        return False
    try:
        return importlib.util.find_spec("mcp.server.fastmcp") is not None
    except ModuleNotFoundError:
        return False


if not _fastmcp_available():
    pytest.skip("requires installed mcp.server.fastmcp from [knowledge]", allow_module_level=True)


def test_mcp_server_module_imports() -> None:
    import tools.repo_knowledge.mcp_server as m

    assert m.mcp is not None
