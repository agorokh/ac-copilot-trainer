"""Optional MCP server import smoke (requires ``[knowledge]`` extra)."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")


def test_mcp_server_module_imports() -> None:
    import tools.repo_knowledge.mcp_server as m

    assert m.mcp is not None
