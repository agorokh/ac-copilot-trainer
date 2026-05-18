"""Tests for the portable agentic-memory MCP wrapper.

The wrapper at ``scripts/mcp/agentic-memory.sh`` launches the agentic-memory
MCP server (from agorokh/mcp-servers) using fleet registry data (from
agorokh/agent-factory) without requiring the child repo to vendor either.

Contract under test:
1. The script exists and is executable.
2. Its header documents the env-var defaults (sibling-clone assumption).
3. With both sibling roots missing, it exits non-zero and writes a clear
   diagnostic to stderr — the fail-safe behavior so Claude MCP startup does
   not crash if siblings are not on disk.
4. With a missing fleet_registry.toml, it exits non-zero with a diagnostic.
5. If ``.mcp.json`` is present at the repo root and registers an
   ``agentic-memory`` server, the command must reference this wrapper.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "scripts" / "mcp" / "agentic-memory.sh"
MCP_JSON = REPO_ROOT / ".mcp.json"

_SKIP_NO_BASH = pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="bash not on PATH; wrapper is bash-only",
)


def test_wrapper_exists_and_executable() -> None:
    """Wrapper file is present and has the executable bit set."""
    assert WRAPPER.is_file(), f"missing wrapper: {WRAPPER}"
    assert os.access(WRAPPER, os.X_OK), f"wrapper not executable: {WRAPPER}"


def test_wrapper_header_documents_env_vars() -> None:
    """Wrapper header documents the two sibling-clone env vars + defaults."""
    text = WRAPPER.read_text(encoding="utf-8")
    head = "\n".join(text.splitlines()[:80])
    assert "AGENTIC_MEMORY_MCP_SERVERS_ROOT" in head, (
        "wrapper header must document AGENTIC_MEMORY_MCP_SERVERS_ROOT"
    )
    assert "AGENTIC_MEMORY_AGENT_FACTORY_ROOT" in head, (
        "wrapper header must document AGENTIC_MEMORY_AGENT_FACTORY_ROOT"
    )
    assert "../mcp-servers" in head, "wrapper header must show default ../mcp-servers"
    assert "../agent-factory" in head, "wrapper header must show default ../agent-factory"


@_SKIP_NO_BASH
def test_wrapper_fails_gracefully_when_mcp_servers_root_missing(tmp_path: Path) -> None:
    """With AGENTIC_MEMORY_MCP_SERVERS_ROOT pointing nowhere, exit non-zero + clear stderr."""
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["AGENTIC_MEMORY_MCP_SERVERS_ROOT"] = str(tmp_path / "missing-mcp-servers")
    env["AGENTIC_MEMORY_AGENT_FACTORY_ROOT"] = str(tmp_path / "missing-agent-factory")
    result = subprocess.run(
        ["bash", str(WRAPPER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0, "wrapper must exit non-zero when siblings missing"
    combined = result.stderr + result.stdout
    assert "AGENTIC_MEMORY_MCP_SERVERS_ROOT" in combined, (
        f"stderr must name the missing env var; got: {combined!r}"
    )


@_SKIP_NO_BASH
def test_wrapper_fails_gracefully_when_agent_factory_root_missing(tmp_path: Path) -> None:
    """With AGENTIC_MEMORY_AGENT_FACTORY_ROOT missing but mcp-servers stub present."""
    fake_mcp = tmp_path / "mcp-servers"
    (fake_mcp / "servers" / "agentic-memory" / "src").mkdir(parents=True)
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["AGENTIC_MEMORY_MCP_SERVERS_ROOT"] = str(fake_mcp)
    env["AGENTIC_MEMORY_AGENT_FACTORY_ROOT"] = str(tmp_path / "missing-agent-factory")
    result = subprocess.run(
        ["bash", str(WRAPPER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0, "wrapper must exit non-zero when agent-factory missing"
    combined = result.stderr + result.stdout
    assert "AGENTIC_MEMORY_AGENT_FACTORY_ROOT" in combined, (
        f"stderr must name the missing env var; got: {combined!r}"
    )


@_SKIP_NO_BASH
def test_wrapper_fails_gracefully_when_fleet_registry_missing(tmp_path: Path) -> None:
    """With both sibling dirs present but fleet_registry.toml missing, exit non-zero."""
    fake_mcp = tmp_path / "mcp-servers"
    (fake_mcp / "servers" / "agentic-memory" / "src").mkdir(parents=True)
    fake_af = tmp_path / "agent-factory"
    (fake_af / "tools" / "hermes_adapter").mkdir(parents=True)
    # Note: NO fleet_registry.toml is created.
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["AGENTIC_MEMORY_MCP_SERVERS_ROOT"] = str(fake_mcp)
    env["AGENTIC_MEMORY_AGENT_FACTORY_ROOT"] = str(fake_af)
    result = subprocess.run(
        ["bash", str(WRAPPER)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0, "wrapper must exit non-zero when fleet_registry.toml missing"
    combined = result.stderr + result.stdout
    assert "fleet_registry.toml" in combined, (
        f"stderr must name the missing file; got: {combined!r}"
    )


def test_mcp_json_agentic_memory_references_wrapper() -> None:
    """If .mcp.json registers agentic-memory, the entry must use this wrapper."""
    if not MCP_JSON.is_file():
        pytest.skip(".mcp.json not present in this repo")
    data = json.loads(MCP_JSON.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {})
    if "agentic-memory" not in servers:
        pytest.skip(".mcp.json does not register agentic-memory")
    entry = servers["agentic-memory"]
    command = entry.get("command", "")
    args = entry.get("args", [])
    joined = " ".join([command, *args])
    assert "scripts/mcp/agentic-memory.sh" in joined, (
        f"agentic-memory entry must call scripts/mcp/agentic-memory.sh; got: {entry!r}"
    )
