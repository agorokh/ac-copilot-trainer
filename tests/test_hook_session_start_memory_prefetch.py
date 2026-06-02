"""Tests for ``scripts/hook_session_start_memory_prefetch.py``.

The prefetch hook (SessionStart) resolves a workspace from
``ops/memory_manifest.yml`` and stamps the gate lockfile. The script makes a
network call to the workspace's HTTP endpoint, so tests use a controlled
manifest with an unreachable endpoint and validate the **fail-open** path:
the script must still stamp the missing marker (or the lock with empty body)
rather than wedge.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hook_session_start_memory_prefetch.py"


def _run(cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={**os.environ, **(env or {}), "CLAUDE_MEMORY_PREFETCH_TIMEOUT_S": "1"},
        check=False,
        timeout=20,
    )


def _setup_repo(tmp_path: Path, manifest: str | None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git").mkdir()
    (tmp_path / "ops").mkdir()
    if manifest is not None:
        (tmp_path / "ops" / "memory_manifest.yml").write_text(manifest, encoding="utf-8")
    return tmp_path


def test_endpoint_allowed_rejects_remote_https() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("prefetch", SCRIPT)
    prefetch = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(prefetch)
    ok, reason = prefetch._endpoint_allowed("https://example.com/query")
    assert not ok
    assert reason is not None
    ok_local, _ = prefetch._endpoint_allowed("https://127.0.0.1:9621")
    assert ok_local


def test_no_manifest_writes_missing_marker(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    proc = _run(repo)
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["prefetch_ok"] is False
    assert data["workspace"] is None
    assert "WARNING" in proc.stdout


def test_workspace_match_manifest_hyphen_vs_dir_underscore(tmp_path: Path) -> None:
    repo = _setup_repo(
        tmp_path / "my_repo",
        manifest=textwrap.dedent("""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "my-repo"
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries:
                  - prompt: "test"
                    mode: "hybrid"
        """),
    )
    proc = _run(repo)
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == "my-repo"


def test_workspace_match_by_name(tmp_path: Path) -> None:
    # Use a workspace name that matches the tmp_path basename so the
    # name-based fallback fires deterministically.
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries:
                  - prompt: "test"
                    mode: "hybrid"
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    proc = _run(repo)
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    assert not (repo / ".scratch" / ".last_memory_query").exists()
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == ws_name
    assert data["prefetch_ok"] is False
    assert "gate will block code-path edits" in proc.stdout


def _write_local_manifest(repo: Path, body: str) -> None:
    (repo / "ops" / "memory_manifest.local.yml").write_text(body, encoding="utf-8")


def _load_prefetch_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("prefetch", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_prefetch_resolves_via_tier3_workspace_id(tmp_path: Path) -> None:
    """Kimi #180 council: ``repo.tier3_workspace_id`` is THIS repo's canonical
    Tier-3 workspace and wins over basename / vault_root matching.

    Template-repo's manifest declares ``tier3_workspace_id: agent_factory_steward``
    — verified live 2026-06-01 that template-repo memory lives in that
    workspace, not in a (never-provisioned) ``template_repo`` placeholder.
    """
    repo = _setup_repo(tmp_path / "template-repo", manifest=None)
    prefetch = _load_prefetch_module()
    tracked = {
        "repo": {"tier3_workspace_id": "agent_factory_steward"},
        "hosts": [
            {
                "workspaces": [
                    {"name": "agent_factory_steward", "endpoint": "http://x/1"},
                    {"name": "template_repo", "endpoint": "http://x/2"},
                ]
            }
        ],
    }
    ws = prefetch._resolve_workspace(repo, tracked, None)
    assert ws is not None
    assert ws["name"] == "agent_factory_steward"


def test_prefetch_tier3_workspace_id_local_wins(tmp_path: Path) -> None:
    """Local manifest's ``repo.tier3_workspace_id`` wins over tracked, mirroring
    the ``resolution_exceptions`` precedence settled in PR #175 (Qodo review)."""
    repo = _setup_repo(tmp_path / "some-repo", manifest=None)
    prefetch = _load_prefetch_module()
    tracked = {
        "repo": {"tier3_workspace_id": "tracked_ws"},
        "hosts": [
            {
                "workspaces": [
                    {"name": "tracked_ws", "endpoint": "http://x/t"},
                    {"name": "local_ws", "endpoint": "http://x/l"},
                ]
            }
        ],
    }
    local = {"repo": {"tier3_workspace_id": "local_ws"}}
    ws = prefetch._resolve_workspace(repo, tracked, local)
    assert ws is not None
    assert ws["name"] == "local_ws"


def test_prefetch_tier3_workspace_id_unknown_returns_none(tmp_path: Path) -> None:
    """Declared but no matching workspace row → return None so SessionStart
    surfaces the standard 'no workspace registered' warning rather than
    silently falling through to basename match and resolving to a wrong row."""
    repo = _setup_repo(tmp_path / "some-repo", manifest=None)
    prefetch = _load_prefetch_module()
    tracked = {
        "repo": {"tier3_workspace_id": "ghost_not_in_manifest"},
        "hosts": [{"workspaces": [{"name": "some_repo", "endpoint": "http://x/1"}]}],
    }
    ws = prefetch._resolve_workspace(repo, tracked, None)
    assert ws is None


def test_prefetch_missing_backend_defaults_to_lightrag(tmp_path: Path) -> None:
    """Qodo PR #194 / #192 Part 5: per the manifest contract, a workspace row
    that omits ``backend`` MUST be treated as ``lightrag`` (canonical online
    substrate). The prior 'skip prefetch, treat as empty' bricked v1-manifest
    workspaces that didn't yet have the field."""
    manifest = textwrap.dedent("""\
        manifest_version: 1
        hosts:
          - id: test-host
            workspaces:
              - name: "my_repo"
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
        """)
    repo = _setup_repo(tmp_path / "my_repo", manifest=manifest)
    proc = _run(repo)
    assert proc.returncode == 0
    # No 'omits backend' warn on stderr — the default kicks in silently.
    assert "omits backend" not in proc.stderr
    # The workspace IS registered + treated as lightrag → prefetch runs and
    # fails to reach loopback:1 → writes a registered-workspace missing marker
    # (the gate then surfaces the unreachable substrate).
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == "my_repo"


def test_prefetch_unwraps_dict_bridge_provenance_envelope(tmp_path: Path) -> None:
    """Qodo PR #194 / #192 Part 6: when the MCP envelope's ``result`` is a
    decoded dict (not a JSON string), it MUST be unwrapped — otherwise the
    outer envelope leaks through with no ``visible_workspace_ids`` and the
    bridge-mismatch check silently skips, allowing the prefetch to query the
    wrong workspace.
    """
    prefetch = _load_prefetch_module()
    # MCP envelope where `result` is already a dict (newer servers return this).
    envelope = {
        "result": {
            "visible_workspace_ids": ["alpaca_trading"],
            "disabled_workspace_ids": [],
            "registry_path": "/tmp/test-registry.toml",
        }
    }
    prov_file = tmp_path / "prov.json"
    prov_file.write_text(json.dumps(envelope), encoding="utf-8")
    import os as _os

    _os.environ["AGENTIC_MEMORY_BRIDGE_PROVENANCE_FILE"] = str(prov_file)
    try:
        data = prefetch._load_bridge_provenance()
    finally:
        _os.environ.pop("AGENTIC_MEMORY_BRIDGE_PROVENANCE_FILE", None)
    assert data is not None, "dict-form result envelope was not unwrapped"
    assert data.get("visible_workspace_ids") == ["alpaca_trading"]


def test_prefetch_unwraps_string_bridge_provenance_envelope(tmp_path: Path) -> None:
    """Backward-compat: older servers return ``result`` as a JSON string; still
    unwrapped correctly."""
    prefetch = _load_prefetch_module()
    inner = {
        "visible_workspace_ids": ["foo_ws"],
        "disabled_workspace_ids": [],
        "registry_path": "/tmp/x.toml",
    }
    envelope = {"result": json.dumps(inner)}
    prov_file = tmp_path / "prov.json"
    prov_file.write_text(json.dumps(envelope), encoding="utf-8")
    import os as _os

    _os.environ["AGENTIC_MEMORY_BRIDGE_PROVENANCE_FILE"] = str(prov_file)
    try:
        data = prefetch._load_bridge_provenance()
    finally:
        _os.environ.pop("AGENTIC_MEMORY_BRIDGE_PROVENANCE_FILE", None)
    assert data is not None
    assert data.get("visible_workspace_ids") == ["foo_ws"]


def test_prefetch_falls_back_to_name_match_without_tier3_id(tmp_path: Path) -> None:
    """No ``tier3_workspace_id`` → existing basename-match logic fires."""
    repo = _setup_repo(tmp_path / "alpaca_trading", manifest=None)
    prefetch = _load_prefetch_module()
    tracked = {
        "hosts": [
            {
                "workspaces": [
                    {"name": "other_ws", "endpoint": "http://x/o"},
                    {"name": "alpaca_trading", "endpoint": "http://x/a"},
                ]
            }
        ]
    }
    ws = prefetch._resolve_workspace(repo, tracked, None)
    assert ws is not None
    assert ws["name"] == "alpaca_trading"


def test_tracked_workspace_wins_over_local_same_name(tmp_path: Path) -> None:
    # Qodo "Precedence Rules": when tracked and local both define the same
    # workspace name, the tracked row must win (no surprising local override).
    repo = _setup_repo(tmp_path, manifest=None)
    ws_name = repo.name.lower().replace("-", "_")
    _write_local_manifest(
        repo,
        textwrap.dedent(f"""\
        hosts:
          - workspaces:
              - name: "{ws_name}"
                endpoint: "http://127.0.0.1:1/local"
        """),
    )
    prefetch = _load_prefetch_module()
    tracked = {
        "hosts": [{"workspaces": [{"name": ws_name, "endpoint": "http://127.0.0.1:1/tracked"}]}]
    }
    local = prefetch._load_local_manifest(repo)
    ws = prefetch._resolve_workspace(repo, tracked, local)
    assert ws is not None
    assert ws.get("endpoint") == "http://127.0.0.1:1/tracked"


def test_gather_workspaces_ignores_non_list_workspaces() -> None:
    # Gemini Code Assist (PR #175): malformed truthy workspaces values must not
    # raise while flattening manifest host rows.
    prefetch = _load_prefetch_module()
    assert prefetch._gather_workspaces({"hosts": [{"workspaces": True}]}) == []
    assert prefetch._gather_workspaces({"hosts": [{"workspaces": 1}]}) == []


def test_local_exception_wins_over_tracked_different_spelling(tmp_path: Path) -> None:
    # Qodo "Exception precedence order-dependent": local must win even when the
    # tracked manifest spells the same repo with the other separator. A merged
    # dict would keep both keys and return tracked-first; local-precedence must
    # be source-ordered, not iteration-ordered.
    repo = _setup_repo(tmp_path / "repo_with_separator", manifest=None)
    base = repo.name
    hyphen = base.replace("_", "-")
    under = base.replace("-", "_")
    _write_local_manifest(
        repo,
        textwrap.dedent(f"""\
        resolution_exceptions:
          "{under}":
            reason: "from local"
            tracking_issue: "LOCAL"
        """),
    )
    prefetch = _load_prefetch_module()
    tracked = {
        "resolution_exceptions": {hyphen: {"reason": "from tracked", "tracking_issue": "TRACKED"}}
    }
    local = prefetch._load_local_manifest(repo)
    ex = prefetch._resolve_exception(repo, tracked, local)
    assert ex is not None
    assert hyphen != under
    assert ex.get("tracking_issue") == "LOCAL", ex


def test_malformed_tracked_manifest_warns_and_degrades(tmp_path: Path) -> None:
    # Qodo "Silent Failure": a malformed *tracked* manifest must not silently
    # route into the degraded path — it must warn so operator misconfig surfaces.
    repo = _setup_repo(tmp_path, manifest="hosts: [unterminated\n  : : :\n")
    proc = _run(repo)
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] is None
    assert "could not parse" in proc.stderr


def test_local_manifest_workspace_is_merged(tmp_path: Path) -> None:
    # Tracked manifest has no matching workspace; the operator-owned local
    # extension does. The deterministic prefetch must resolve it (previously
    # only the agent-facing ladder consulted the local manifest).
    repo = _setup_repo(tmp_path, manifest="manifest_version: 2\n")
    ws_name = repo.name.lower().replace("-", "_")
    _write_local_manifest(
        repo,
        textwrap.dedent(f"""\
        hosts:
          - id: local-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries:
                  - prompt: "test"
                    mode: "hybrid"
        """),
    )
    proc = _run(repo)
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == ws_name
    assert data["prefetch_ok"] is False
    # Registered (locally) but unreachable → block path, not the no-workspace warning.
    assert "gate will block code-path edits" in proc.stdout


def test_resolution_exception_degrades_quietly(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    basename = repo.name
    tracking = "https://github.com/agorokh/template-repo/issues/167"
    (repo / "ops" / "memory_manifest.yml").write_text(
        textwrap.dedent(f"""\
        manifest_version: 2
        resolution_exceptions:
          "{basename}":
            reason: "Tier-3 workspace not yet provisioned on the fleet substrate"
            tracking_issue: "{tracking}"
        """),
        encoding="utf-8",
    )
    proc = _run(repo)
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["reason"] == "accepted_gap"
    # gate_policy must be the default "allow" (NOT "warn") so the gate's
    # no-workspace branch allows edits unconditionally, independent of any
    # leftover lock (Cursor Bugbot regression, PR #175).
    assert data["gate_policy"] == "allow"
    assert data["workspace"] is None
    assert "accepted Tier-3 gap" in proc.stdout
    assert tracking in proc.stdout
    assert "do NOT file a new" in proc.stdout
    # Must NOT emit the generic "register a workspace" warning for an accepted gap.
    assert "no Tier-3 workspace registered" not in proc.stdout


def test_resolution_exception_from_local_manifest(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest="manifest_version: 2\n")
    basename = repo.name
    _write_local_manifest(
        repo,
        textwrap.dedent(f"""\
        resolution_exceptions:
          "{basename}":
            reason: "known unprovisioned child repo"
            tracking_issue: "https://github.com/agorokh/template-repo/issues/169"
        """),
    )
    proc = _run(repo)
    assert proc.returncode == 0
    data = json.loads(
        (repo / ".scratch" / ".last_memory_query.missing").read_text(encoding="utf-8")
    )
    assert data["reason"] == "accepted_gap"
    assert "accepted Tier-3 gap" in proc.stdout
    assert "issues/169" in proc.stdout


def test_resolved_workspace_wins_over_exception(tmp_path: Path) -> None:
    # A live (registered) workspace must take precedence over a stale exception
    # entry for the same repo basename.
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        resolution_exceptions:
          "{ws_name}":
            reason: "should be ignored — workspace is registered"
            tracking_issue: "https://example.com/stale"
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries:
                  - prompt: "test"
                    mode: "hybrid"
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    proc = _run(repo)
    assert proc.returncode == 0
    data = json.loads(
        (repo / ".scratch" / ".last_memory_query.missing").read_text(encoding="utf-8")
    )
    assert data["workspace"] == ws_name
    assert data.get("reason") != "accepted_gap"
    assert "accepted Tier-3 gap" not in proc.stdout


def test_graphiti_backend_writes_missing_marker(tmp_path: Path) -> None:
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: graphiti
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    proc = _run(repo)
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    assert not (repo / ".scratch" / ".last_memory_query").exists()
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["prefetch_ok"] is False
    assert data["workspace"] == ws_name


def test_unknown_backend_writes_missing_marker(tmp_path: Path) -> None:
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: neo4j_legacy
                endpoint: "http://127.0.0.1:8060"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    proc = _run(repo)
    assert proc.returncode == 0
    assert "unknown backend" in proc.stderr
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file()


def test_missing_backend_defaults_to_lightrag_and_attempts_prefetch(
    tmp_path: Path,
) -> None:
    """Qodo PR #194 / #192 Part 5 — updated from the prior 'skip prefetch +
    warn' behavior. Per the manifest contract, omitted ``backend`` MUST default
    to ``lightrag`` (canonical online substrate); the prefetch then attempts
    the HTTP query like any other lightrag row. The unreachable endpoint here
    fails → stamps the registered-workspace missing marker so the gate
    surfaces the outage."""
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                endpoint: "http://127.0.0.1:8060"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    proc = _run(repo)
    assert proc.returncode == 0
    # Per the new contract: no 'omits backend' warning — default kicks in.
    assert "omits backend" not in proc.stderr
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    assert not (repo / ".scratch" / ".last_memory_query").exists()


def test_disabled_via_env(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    proc = _run(repo, env={"CLAUDE_MEMORY_PREFETCH": "0"})
    assert proc.returncode == 0
    # Kill-switch still stamps the missing marker so the gate degrades warn-only.
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file(), proc.stdout + proc.stderr
    assert not (repo / ".scratch" / ".last_memory_query").exists()
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["prefetch_ok"] is False


def test_load_prompt_override(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    proc = _run(repo, env={"CLAUDE_LOAD_PROMPT": "explicit override prompt"})
    assert proc.returncode == 0
    data = json.loads((repo / ".scratch" / ".last_memory_query.missing").read_text())
    assert data["prompt"] == "explicit override prompt"


def test_blocked_remote_http_endpoint_writes_missing_marker(tmp_path: Path) -> None:
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://evil.example:9999"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    proc = _run(repo)
    assert proc.returncode == 0
    # The untrusted remote HTTP endpoint must never be contacted: the shared
    # resolver's allowlist (non-loopback must be registry-named/Tailscale-shaped
    # AND HTTPS) rejects it, so only the loopback fallback is probed — which is
    # unreachable here — yielding a blocking missing marker and no fresh lock
    # (template-repo#180 replaced the loopback-only _endpoint_allowed guard).
    assert "evil.example" not in proc.stdout and "evil.example" not in proc.stderr
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file()
    assert not (repo / ".scratch" / ".last_memory_query").exists()


def test_bridge_provenance_not_visible_writes_blocking_marker(tmp_path: Path) -> None:
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    provenance = {
        "registry_path": "/tmp/fleet-registry.toml",
        "visible_workspace_ids": ["agent_factory_steward"],
        "disabled_workspace_ids": [],
    }
    proc = _run(repo, env={"AGENTIC_MEMORY_BRIDGE_PROVENANCE_JSON": json.dumps(provenance)})
    assert proc.returncode == 0
    assert "Tier-3 workspace mismatch" in proc.stdout
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == ws_name
    assert data["gate_policy"] == "block"
    assert data["reason"] == "bridge_workspace_not_visible"


def test_bridge_provenance_disabled_writes_blocking_marker(tmp_path: Path) -> None:
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    provenance = {
        "registry_path": "/tmp/fleet-registry.toml",
        "visible_workspace_ids": ["agent_factory_steward"],
        "disabled_workspace_ids": [ws_name],
    }
    proc = _run(repo, env={"AGENTIC_MEMORY_BRIDGE_PROVENANCE_JSON": json.dumps(provenance)})
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["gate_policy"] == "block"
    assert data["reason"] == "bridge_workspace_disabled"


def test_bridge_provenance_ignored_for_graphiti_placeholder(tmp_path: Path) -> None:
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: graphiti
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    provenance = {
        "registry_path": "/tmp/fleet-registry.toml",
        "visible_workspace_ids": ["agent_factory_steward"],
        "disabled_workspace_ids": [ws_name],
    }
    proc = _run(repo, env={"AGENTIC_MEMORY_BRIDGE_PROVENANCE_JSON": json.dumps(provenance)})
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == ws_name
    assert data["gate_policy"] == "allow"
    assert data.get("reason") != "bridge_workspace_disabled"


def test_bridge_provenance_file_size_limit_degrades(tmp_path: Path) -> None:
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    huge = tmp_path / "huge-provenance.json"
    huge.write_text("{" + (" " * 20_000) + "}", encoding="utf-8")
    proc = _run(repo, env={"AGENTIC_MEMORY_BRIDGE_PROVENANCE_FILE": str(huge)})
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == ws_name
    assert data["gate_policy"] == "allow"
    assert data.get("reason") != "bridge_workspace_not_visible"


def test_pyyaml_missing_degrades(tmp_path: Path, monkeypatch) -> None:
    """If PyYAML isn't installed the script must degrade gracefully.

    We can't easily uninstall PyYAML mid-test; this test only ensures the
    branch exists in the code (light check). The real defense is that the
    template ships PyYAML in `pyproject [dev]`.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "import yaml" in src and "ImportError" in src


# -------------------------------------------------------------------------
# Bridge provenance auto-capture (issue #172). The wrapper writes the live
# bridge's visible/disabled set to a well-known file; the prefetch reads it by
# default so _bridge_workspace_problem fires without an env handshake.
# -------------------------------------------------------------------------


def _lightrag_ws_manifest(ws_name: str) -> str:
    return textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)


def _write_default_provenance(cache_home: Path, payload: dict) -> Path:
    """Write a capture at the XDG default path the prefetch reads."""
    prov = cache_home / "agentic-memory" / "bridge_provenance.json"
    prov.parent.mkdir(parents=True, exist_ok=True)
    prov.write_text(json.dumps(payload), encoding="utf-8")
    return prov


def test_bridge_provenance_default_path_blocks(tmp_path: Path) -> None:
    """A not-visible workspace in the default capture file blocks — no env needed."""
    ws_name = tmp_path.name.lower().replace("-", "_")
    repo = _setup_repo(tmp_path, manifest=_lightrag_ws_manifest(ws_name))
    cache_home = tmp_path / "xdgcache"
    _write_default_provenance(
        cache_home,
        {
            "registry_path": "/tmp/fleet-registry.toml",
            "visible_workspace_ids": ["agent_factory_steward"],
            "disabled_workspace_ids": [],
        },
    )
    # Note: only XDG_CACHE_HOME is set — no AGENTIC_MEMORY_BRIDGE_PROVENANCE_* env.
    proc = _run(repo, env={"XDG_CACHE_HOME": str(cache_home)})
    assert proc.returncode == 0
    assert "Tier-3 workspace mismatch" in proc.stdout
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == ws_name
    assert data["gate_policy"] == "block"
    assert data["reason"] == "bridge_workspace_not_visible"


def test_bridge_provenance_default_trusts_old_capture(tmp_path: Path) -> None:
    """Default (no TTL): an old capture is still honoured, so a long-running
    bridge does not silently disable the drift check (cursor-bot #172 review)."""
    ws_name = tmp_path.name.lower().replace("-", "_")
    repo = _setup_repo(tmp_path, manifest=_lightrag_ws_manifest(ws_name))
    cache_home = tmp_path / "xdgcache"
    prov = _write_default_provenance(
        cache_home,
        {
            "registry_path": "/tmp/fleet-registry.toml",
            "visible_workspace_ids": ["agent_factory_steward"],
            "disabled_workspace_ids": [],
        },
    )
    old = time.time() - 30 * 24 * 3600  # 30 days old — no default TTL drops it
    os.utime(prov, (old, old))
    proc = _run(repo, env={"XDG_CACHE_HOME": str(cache_home)})
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["gate_policy"] == "block"
    assert data["reason"] == "bridge_workspace_not_visible"


def test_bridge_provenance_opt_in_staleness_ignores_old(tmp_path: Path) -> None:
    """With a positive MAX_AGE_S backstop, a too-old capture is ignored."""
    ws_name = tmp_path.name.lower().replace("-", "_")
    repo = _setup_repo(tmp_path, manifest=_lightrag_ws_manifest(ws_name))
    cache_home = tmp_path / "xdgcache"
    prov = _write_default_provenance(
        cache_home,
        {
            "registry_path": "/tmp/fleet-registry.toml",
            "visible_workspace_ids": ["agent_factory_steward"],
            "disabled_workspace_ids": [],
        },
    )
    old = time.time() - 48 * 3600
    os.utime(prov, (old, old))
    proc = _run(
        repo,
        env={
            "XDG_CACHE_HOME": str(cache_home),
            "AGENTIC_MEMORY_BRIDGE_PROVENANCE_MAX_AGE_S": "3600",  # 1h backstop
        },
    )
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    # Too-old capture ignored → falls back to the normal unreachable-placeholder path.
    assert data.get("reason") != "bridge_workspace_not_visible"
    assert data["gate_policy"] == "allow"


# -------------------------------------------------------------------------
# Substantive-lockfile coverage (issue #115 council fix, Gemini's pick).
# Verifies the prefetch hook persists the actual MCP response body into
# the lockfile so the gate can check semantic coupling to the file being
# edited. Closes Mistral bypass #3 (query spam) and ChatGPT's "ritual not
# cognition" diagnosis at the producer side.
# -------------------------------------------------------------------------


def _import_prefetch_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("prefetch", SCRIPT)
    assert spec and spec.loader
    prefetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prefetch)
    return prefetch


def _import_hook_repo_root_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_repo_root", REPO_ROOT / "scripts" / "hook_repo_root.py"
    )
    assert spec and spec.loader
    hook_repo_root = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook_repo_root)
    return hook_repo_root


def _patch_git_common_dir(monkeypatch, hook_repo_root, main: Path) -> None:
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if isinstance(cmd, list) and "--git-common-dir" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=str(main / ".git") + "\n", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(hook_repo_root.subprocess, "run", fake_run)


def test_repo_root_normalizes_worktree_to_main(tmp_path: Path, monkeypatch) -> None:
    """In a git worktree, _repo_root resolves to the main repo working dir.

    A worktree's `.git` is a *file* (not a dir), `git rev-parse --show-toplevel`
    returns the worktree path, and its basename is a random slug that never
    matches manifest match_repo_basenames. The fix uses `--git-common-dir` to
    find the shared `.git/`; its parent is the main repo. Without this fix,
    sessions started inside .claude/worktrees/<slug>/ silently degrade the
    Tier-3 memory gate to warn-only.
    """
    hook_repo_root = _import_hook_repo_root_module()
    prefetch = _import_prefetch_module()
    main = tmp_path / "template-repo"
    main.mkdir()
    (main / ".git").mkdir()
    worktree = tmp_path / "wt-random-slug-abc123"
    worktree.mkdir()
    (worktree / ".git").write_text(
        f"gitdir: {main / '.git' / 'worktrees' / 'wt-random-slug-abc123'}\n",
        encoding="utf-8",
    )

    _patch_git_common_dir(monkeypatch, hook_repo_root, main)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(worktree)

    resolved = prefetch._repo_root()
    assert resolved == main.resolve(), f"expected main repo {main} but got {resolved}"


def test_repo_root_normalizes_claude_project_dir_in_worktree(tmp_path: Path, monkeypatch) -> None:
    """CLAUDE_PROJECT_DIR must not bypass worktree normalization."""
    hook_repo_root = _import_hook_repo_root_module()
    prefetch = _import_prefetch_module()
    main = tmp_path / "template-repo"
    main.mkdir()
    (main / ".git").mkdir()
    worktree = tmp_path / "wt-random-slug-abc123"
    worktree.mkdir()
    (worktree / ".git").write_text(
        f"gitdir: {main / '.git' / 'worktrees' / 'wt-random-slug-abc123'}\n",
        encoding="utf-8",
    )

    _patch_git_common_dir(monkeypatch, hook_repo_root, main)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(worktree))
    monkeypatch.chdir(worktree)

    resolved = prefetch._repo_root()
    assert resolved == main.resolve(), f"expected main repo {main} but got {resolved}"


def test_lockfile_carries_response_body(tmp_path: Path, monkeypatch) -> None:
    """The lockfile must persist the actual substrate response body."""
    prefetch = _import_prefetch_module()
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:8020"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries:
                  - prompt: "test"
                    mode: "hybrid"
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    fake_body = (
        "The hook_memory_gate.py enforces session-start prefetch stamps "
        "with response_body content for file relevance checks."
    )
    monkeypatch.setattr(prefetch, "_http_query_lightrag", lambda *a, **k: (fake_body, None))
    monkeypatch.setattr(prefetch, "_endpoint_allowed", lambda e: (True, ""))
    monkeypatch.setattr(prefetch, "_repo_root", lambda: repo)
    monkeypatch.setattr(prefetch, "_derive_prompt", lambda root: "hook memory gate")

    rc = prefetch.main()
    assert rc == 0
    lock_path = repo / ".scratch" / ".last_memory_query"
    assert lock_path.is_file()
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    assert data["prefetch_ok"] is True
    assert data["response_body"] == fake_body
    assert data["response_body_len"] == len(fake_body)


def test_response_body_truncated_to_limit(tmp_path: Path, monkeypatch) -> None:
    """Very long substrate responses are truncated so the lockfile stays small."""
    prefetch = _import_prefetch_module()
    ws_name = tmp_path.name.lower().replace("-", "_")
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: "{ws_name}"
                backend: lightrag
                endpoint: "http://127.0.0.1:8020"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    long_body = "x" * (prefetch.RESPONSE_BODY_LIMIT + 1000)
    monkeypatch.setattr(prefetch, "_http_query_lightrag", lambda *a, **k: (long_body, None))
    monkeypatch.setattr(prefetch, "_endpoint_allowed", lambda e: (True, ""))
    monkeypatch.setattr(prefetch, "_repo_root", lambda: repo)
    monkeypatch.setattr(prefetch, "_derive_prompt", lambda root: "test")

    prefetch.main()
    data = json.loads((repo / ".scratch" / ".last_memory_query").read_text())
    assert "…(truncated)" in data["response_body"]
    assert data["response_body_len"] <= prefetch.RESPONSE_BODY_LIMIT + len("…(truncated)")


# -------------------------------------------------------------------------
# Super-ego feedback (issue #115 post-merge iteration)
# -------------------------------------------------------------------------


def _write_audit(repo: Path, records: list[dict]) -> None:
    scratch = repo / ".scratch"
    scratch.mkdir(exist_ok=True)
    (scratch / "memory_audit.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


def test_super_ego_warns_when_previous_drift_high(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    _write_audit(
        repo,
        [
            {"reason": "no_transcript", "timestamp_utc": "2026-01-01T00:00:00Z"},
            {
                "reason": "scored",
                "drift_score": 0.8,
                "substantive_count": 5,
                "cited_count": 1,
                "timestamp_utc": "2026-01-02T00:00:00Z",
            },
        ],
    )
    proc = _run(repo)
    assert proc.returncode == 0
    assert "WARNING: previous session memory-drift audit" in proc.stdout
    assert "drift_score: 0.80" in proc.stdout


def test_super_ego_silent_when_previous_drift_low(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    _write_audit(
        repo,
        [{"reason": "scored", "drift_score": 0.2, "substantive_count": 4, "cited_count": 3}],
    )
    proc = _run(repo)
    assert proc.returncode == 0
    assert "previous session memory-drift audit" not in proc.stdout


def test_super_ego_silent_when_no_audit_log(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    proc = _run(repo)
    assert proc.returncode == 0
    assert "previous session memory-drift audit" not in proc.stdout


def test_super_ego_uses_most_recent_scored_record(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    _write_audit(
        repo,
        [
            {
                "reason": "scored",
                "drift_score": 0.9,
                "substantive_count": 3,
                "cited_count": 0,
                "timestamp_utc": "old",
            },
            {"reason": "session_too_short", "substantive_count": 0},
            {
                "reason": "scored",
                "drift_score": 0.3,
                "substantive_count": 4,
                "cited_count": 3,
                "timestamp_utc": "new",
            },
        ],
    )
    proc = _run(repo)
    assert proc.returncode == 0
    assert "previous session memory-drift audit" not in proc.stdout


def test_super_ego_respects_drift_audit_kill_switch(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    _write_audit(
        repo,
        [{"reason": "scored", "drift_score": 0.9, "substantive_count": 3, "cited_count": 0}],
    )
    proc = _run(repo, env={"CLAUDE_MEMORY_DRIFT_AUDIT": "0"})
    assert proc.returncode == 0
    assert "previous session memory-drift audit" not in proc.stdout


def test_super_ego_threshold_env_override(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path, manifest=None)
    _write_audit(
        repo,
        [{"reason": "scored", "drift_score": 0.6, "substantive_count": 3, "cited_count": 1}],
    )
    proc = _run(repo, env={"CLAUDE_MEMORY_DRIFT_WARNING_THRESHOLD": "0.7"})
    assert proc.returncode == 0
    assert "previous session memory-drift audit" not in proc.stdout

    proc2 = _run(repo, env={"CLAUDE_MEMORY_DRIFT_WARNING_THRESHOLD": "0.5"})
    assert "WARNING: previous session memory-drift audit" in proc2.stdout
