"""Optional MCP v2 server smoke (requires the ``[knowledge]`` extra)."""

from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version

import pytest

try:
    version("mcp")
except PackageNotFoundError:
    pytest.skip("requires MCP SDK v2 from [knowledge]", allow_module_level=True)

# Once an MCP distribution is installed, incompatible/missing v2 exports are a real failure. Do
# not turn an installed v1 SDK into an optional-dependency skip (#764).
from mcp import Client
from mcp.server import MCPServer

EXPECTED_TOOLS = {
    "query_ci_failures",
    "query_decisions",
    "query_file_patterns",
    "query_review_history",
    "query_similar_issues",
}


def test_mcp_server_exposes_repo_knowledge_tools_over_v2_protocol() -> None:
    import tools.repo_knowledge.mcp_server as module

    assert isinstance(module.mcp, MCPServer)

    async def inspect_server() -> tuple[str, set[str]]:
        async with Client(module.mcp, raise_exceptions=True) as client:
            assert client.server_info is not None
            result = await client.list_tools()
            return client.server_info.name, {tool.name for tool in result.tools}

    name, tools = asyncio.run(inspect_server())
    assert name == "repo-knowledge"
    assert tools == EXPECTED_TOOLS
