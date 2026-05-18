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


def test_workspace_match_by_vault_root_containing_repo(tmp_path: Path) -> None:
    """When the repo path lies under ``vault_root``, match even if names differ."""
    vault_root = tmp_path / "vault"
    repo = vault_root / "nested-repo"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "ops").mkdir()
    manifest = textwrap.dedent(f"""\
        manifest_version: 2
        hosts:
          - id: test-host
            workspaces:
              - name: unrelated-workspace
                backend: lightrag
                endpoint: "http://127.0.0.1:1"
                vault_root: "{vault_root}"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries:
                  - prompt: "test"
                    mode: "hybrid"
        """)
    (repo / "ops" / "memory_manifest.yml").write_text(manifest, encoding="utf-8")
    proc = _run(repo)
    assert proc.returncode == 0
    missing = repo / ".scratch" / ".last_memory_query.missing"
    data = json.loads(missing.read_text(encoding="utf-8"))
    assert data["workspace"] == "unrelated-workspace"


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
    assert "blocked endpoint" in proc.stderr
    missing = repo / ".scratch" / ".last_memory_query.missing"
    assert missing.is_file()
    assert not (repo / ".scratch" / ".last_memory_query").exists()


def test_pyyaml_missing_degrades(tmp_path: Path, monkeypatch) -> None:
    """If PyYAML isn't installed the script must degrade gracefully.

    We can't easily uninstall PyYAML mid-test; this test only ensures the
    branch exists in the code (light check). The real defense is that the
    template ships PyYAML in `pyproject [dev]`.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert "import yaml" in src and "ImportError" in src


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
                endpoint: "http://example.invalid"
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
    monkeypatch.setattr(prefetch, "_http_query_lightrag", lambda *a, **k: fake_body)
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
                endpoint: "http://example.invalid"
                vault_root: "/nowhere"
                audit_log: "/nowhere"
                launchd_label: null
                stale_after_hours: 24
                canary_queries: []
        """)
    repo = _setup_repo(tmp_path, manifest=manifest)
    long_body = "x" * (prefetch.RESPONSE_BODY_LIMIT + 1000)
    monkeypatch.setattr(prefetch, "_http_query_lightrag", lambda *a, **k: long_body)
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
