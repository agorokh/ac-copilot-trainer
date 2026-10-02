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


# Read-only worktree fallback (ported from workstation-ops#2097; fleet rollout
# Atelier-AppliedAI/workstation-ops#3548). The wrapper serves the main checkout's DB with
# REPO_KNOWLEDGE_READONLY=1; the server must refuse to start on a missing or schema-less
# read-only DB instead of serving a zombie whose every query errors.


def test_mcp_server_readonly_missing_db_exits_instead_of_zombie(tmp_path, monkeypatch) -> None:
    import tools.repo_knowledge.mcp_server as m

    monkeypatch.setenv("REPO_KNOWLEDGE_DB", str(tmp_path / "missing.db"))
    monkeypatch.setenv("REPO_KNOWLEDGE_READONLY", "1")
    ran = []
    monkeypatch.setattr(m.mcp, "run", lambda **_: ran.append(True))

    with pytest.raises(SystemExit) as excinfo:
        m.main()

    assert excinfo.value.code == 1
    assert ran == []  # never reaches mcp.run


def test_mcp_server_readonly_existing_db_serves(tmp_path, monkeypatch) -> None:
    import tools.repo_knowledge.mcp_server as m
    from tools.repo_knowledge.query import connect

    db = tmp_path / "present.db"
    connect(db).close()  # seed a valid DB (write mode outside the ro serve path)
    monkeypatch.setenv("REPO_KNOWLEDGE_DB", str(db))
    monkeypatch.setenv("REPO_KNOWLEDGE_READONLY", "1")
    ran = []
    monkeypatch.setattr(m.mcp, "run", lambda **_: ran.append(True))

    m.main()

    assert ran == [True]


def test_mcp_server_readonly_schemaless_db_exits(tmp_path, monkeypatch) -> None:
    import tools.repo_knowledge.mcp_server as m

    db = tmp_path / "empty.db"
    db.write_bytes(b"")
    monkeypatch.setenv("REPO_KNOWLEDGE_DB", str(db))
    monkeypatch.setenv("REPO_KNOWLEDGE_READONLY", "1")
    ran = []
    monkeypatch.setattr(m.mcp, "run", lambda **_: ran.append(True))

    with pytest.raises(SystemExit) as excinfo:
        m.main()

    assert excinfo.value.code == 1
    assert ran == []
