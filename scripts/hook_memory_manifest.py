#!/usr/bin/env python3
# OWNER: @agorokh
# ALLOWLIST: #320 | imported helper, not hook entrypoint | @agorokh | 2026-07-01
"""Shared manifest loading for deterministic memory hook scripts.

Owns the canonical default code-dir allowlist (``DEFAULT_CODE_PATH_PREFIXES`` /
``DEFAULT_CODE_PATH_TOP_LEVEL`` / ``DEFAULT_CODE_DIR_TOP_LEVEL``) so the gate and
the prefetch can't drift on what counts as a code path, and exposes
``repo_code_path_prefixes`` / ``repo_code_path_top_level`` /
``repo_code_dir_top_level`` / ``repo_tier3_workspace_id`` for the per-repo
``repo:`` block in ``ops/memory_manifest.yml``. Council #180 fix: hardcoding the
allowlist in the gate let propagation copy template's defaults over each child's
project-specific code dirs (regression — child production edits bypassed the
gate). Per-repo manifest data is gated by being under ``ops/``, so editing it
still requires a fresh substrate stamp (closes Mistral's "shrink the allowlist"
bypass).
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Canonical default code-path classification — single source of truth.
# Both the gate and the contract docs reference these. Children override via
# the per-repo ``repo:`` block in ``ops/memory_manifest.yml``.
# ---------------------------------------------------------------------------
DEFAULT_CODE_PATH_PREFIXES: tuple[str, ...] = (
    "src/",
    "scripts/",
    "tests/",
    "ops/",
    ".github/workflows/",
    ".github/actions/",
    "tools/",
)
DEFAULT_CODE_PATH_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "Makefile",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "requirements-dev.txt",
        ".pre-commit-config.yaml",
    }
)
DEFAULT_CODE_DIR_TOP_LEVEL: frozenset[str] = frozenset(
    {"src", "scripts", "tests", "ops", "tools", ".github"}
)


def _yaml_scalar(value: str) -> str:
    cleaned = value.split("#", 1)[0].strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        return cleaned[1:-1]
    return cleaned


def _apply_field(row: dict[str, Any], text: str) -> str | None:
    match = re.match(r"([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", text)
    if not match:
        return None
    key = match.group(1)
    if key not in {
        "name",
        "workspace",
        "id",
        "backend",
        "endpoint",
        "vault_root",
        "match_repo_basenames",
    }:
        return None
    raw_value = match.group(2)
    if key == "match_repo_basenames" and not raw_value.strip():
        row[key] = []
    else:
        row[key] = _yaml_scalar(raw_value)
    return key


def _fallback_manifest_from_text(text: str) -> dict[str, Any]:
    """Parse the manifest subset needed by hooks when PyYAML is unavailable.

    Covers:
    * ``hosts: [- workspaces: [- name/backend/endpoint/vault_root/match_repo_basenames]]``
    * Top-level ``repo:`` block with ``code_dirs`` / ``code_top_level`` lists
      and ``tier3_workspace_id`` scalar (Qodo PR #194 HIGH: without this, the
      per-repo override silently drops in PyYAML-missing hook runtimes and the
      gate falls back to template defaults — re-introducing the wave-introduced
      clobber regression for repos relying on the override).
    """
    hosts: list[dict[str, Any]] = []
    repo_block: dict[str, Any] = {}
    in_hosts = False
    hosts_indent = -1
    in_repo = False
    repo_indent = -1
    repo_list_key: str | None = None
    repo_list_indent = -1
    current_host: dict[str, Any] | None = None
    host_indent: int | None = None
    in_workspaces = False
    workspaces_indent = -1
    row_indent: int | None = None
    current: dict[str, Any] | None = None
    current_list_key: str | None = None

    def finish_current() -> None:
        nonlocal current, current_list_key
        if current and current_host is not None:
            current_host.setdefault("workspaces", []).append(current)
        current = None
        current_list_key = None

    def exit_repo() -> None:
        nonlocal in_repo, repo_indent, repo_list_key, repo_list_indent
        in_repo = False
        repo_indent = -1
        repo_list_key = None
        repo_list_indent = -1

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        stripped = raw_line.strip()

        # Exit repo: block when we hit another top-level (indent <= repo_indent).
        if in_repo and indent <= repo_indent:
            exit_repo()

        # Top-level `repo:` block.
        if re.match(r"repo:\s*(?:#.*)?$", stripped):
            finish_current()
            in_hosts = False
            in_workspaces = False
            in_repo = True
            repo_indent = indent
            repo_list_key = None
            continue

        if in_repo and indent > repo_indent:
            # A scalar key or the start of a list (`code_dirs:`, `code_top_level:`,
            # `tier3_workspace_id: "..."`).
            scalar_m = re.match(r"(code_dirs|code_top_level|tier3_workspace_id):\s*(.*)$", stripped)
            if scalar_m:
                key = scalar_m.group(1)
                raw_value = scalar_m.group(2).strip()
                if not raw_value or raw_value.startswith("#"):
                    # Block scalar with list to follow.
                    repo_block[key] = []
                    repo_list_key = key
                    repo_list_indent = indent
                elif raw_value.startswith("["):
                    # SECURITY (#10, 2026-06-03 scan): a FLOW sequence (`code_dirs: [a, b]`) is
                    # valid YAML but used to land here as an opaque scalar string, silently
                    # dropping the repo's code-dir allowlist so the gate reverted to defaults and
                    # stopped gating custom dirs. Parse it as a list.
                    inner = raw_value[1 : raw_value.rfind("]")] if "]" in raw_value else raw_value[1:]
                    repo_block[key] = [
                        _yaml_scalar(item.strip()) for item in inner.split(",") if item.strip()
                    ]
                    repo_list_key = None
                else:
                    repo_block[key] = _yaml_scalar(raw_value)
                    repo_list_key = None
                continue
            # SECURITY (#10): accept block-sequence items indented at the SAME column as the key
            # (`>=`), not only strictly deeper (`>`). Same-indent `-` items are valid YAML and
            # were previously dropped, reverting the code-dir allowlist to permissive defaults.
            if repo_list_key and stripped.startswith("- ") and indent >= repo_list_indent:
                repo_block.setdefault(repo_list_key, []).append(_yaml_scalar(stripped[2:].strip()))
                continue
            # Unrecognized line inside repo: — ignore (forward-compat with new keys).
            continue

        if re.match(r"hosts:\s*(?:#.*)?$", stripped):
            finish_current()
            in_hosts = True
            hosts_indent = indent
            current_host = None
            host_indent = None
            in_workspaces = False
            row_indent = None
            continue

        if in_workspaces and indent <= workspaces_indent:
            finish_current()
            in_workspaces = False
            row_indent = None

        if (
            in_hosts
            and not in_workspaces
            and stripped.startswith("- ")
            and indent > hosts_indent
            and (host_indent is None or indent <= host_indent)
        ):
            current_host = {"workspaces": []}
            hosts.append(current_host)
            host_indent = indent
            _apply_field(current_host, stripped[2:].strip())
            continue

        if re.match(r"workspaces:\s*(?:#.*)?$", stripped):
            finish_current()
            if current_host is None:
                current_host = {"workspaces": []}
                hosts.append(current_host)
            in_workspaces = True
            workspaces_indent = indent
            row_indent = None
            continue

        if not in_workspaces:
            if current_host is not None and host_indent is not None and indent > host_indent:
                _apply_field(current_host, stripped)
            continue

        if stripped.startswith("- ") and (row_indent is None or indent == row_indent):
            finish_current()
            row_indent = indent
            current = {}
            current_list_key = _apply_field(current, stripped[2:].strip())
            continue

        if current is not None and row_indent is not None and indent > row_indent:
            if (
                current_list_key == "match_repo_basenames"
                and isinstance(current.get(current_list_key), list)
                and stripped.startswith("- ")
            ):
                current[current_list_key].append(_yaml_scalar(stripped[2:].strip()))
                continue
            current_list_key = _apply_field(current, stripped)

    finish_current()
    out: dict[str, Any] = {"hosts": hosts}
    if repo_block:
        out["repo"] = repo_block
    return out


def load_manifest(root: Path, *, warn_missing_pyyaml: bool = False) -> dict[str, Any] | None:
    path = root / "ops" / "memory_manifest.yml"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        if warn_missing_pyyaml:
            print(
                "WARNING: hook_session_start_memory_prefetch.py needs PyYAML; "
                "using limited manifest parser fallback. Run `pip install -e '.[dev]'` "
                "or use the repo .venv python in SessionStart hooks "
                "(see .claude/settings.base.json).",
                file=sys.stderr,
            )
        return _fallback_manifest_from_text(text)
    try:
        payload = yaml.safe_load(text)
    except Exception:  # noqa: BLE001
        return _fallback_manifest_from_text(text)
    return payload if isinstance(payload, dict) else _fallback_manifest_from_text(text)


def name_match_keys(name: str) -> set[str]:
    lowered = name.lower()
    return {lowered, lowered.replace("-", "_"), lowered.replace("_", "-")}


def resolve_vault_root(vault_root: str, root: Path) -> Path:
    expanded = Path(os.path.expanduser(vault_root))
    if expanded.is_absolute():
        return expanded.resolve()
    return (root / expanded).resolve()


def workspace_name(workspace: dict[str, Any]) -> str:
    name = workspace.get("name", workspace.get("workspace", workspace.get("id", "")))
    return name.strip() if isinstance(name, str) else ""


def workspace_backend(workspace: dict[str, Any]) -> str:
    backend = workspace.get("backend", "lightrag")
    if backend is None:
        return "lightrag"
    if isinstance(backend, str):
        return backend.strip().lower() or "lightrag"
    return "lightrag"


def workspace_match_repo_basenames(workspace: dict[str, Any]) -> set[str]:
    raw = workspace.get("match_repo_basenames") or []
    if not isinstance(raw, list):
        return set()
    names: set[str] = set()
    for item in raw:
        if isinstance(item, str) and item.strip():
            names.update(name_match_keys(item.strip()))
    return names


def _gather_workspace_rows(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten ``hosts[].workspaces`` rows from one manifest dict."""
    if not isinstance(manifest, dict):
        return []
    hosts = manifest.get("hosts") or []
    if not isinstance(hosts, list):
        return []
    candidates: list[dict[str, Any]] = []
    for host in hosts:
        if not isinstance(host, dict):
            continue
        rows = host.get("workspaces") or []
        if not isinstance(rows, list):
            continue
        candidates.extend(row for row in rows if isinstance(row, dict))
    return candidates


def resolve_workspace(
    root: Path,
    manifest: dict[str, Any] | None,
    local_manifest: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """THE workspace resolver — the single implementation both the gate and the
    SessionStart prefetch use (governance-hub#28 finding 1: the prefetch carried
    its own copy whose basename-vs-vault_root rung order disagreed with this
    one, so the stamp and the gate could resolve different workspaces on repos
    without an explicit ``tier3_workspace_id``).

    ``local_manifest`` is the operator-owned ``ops/memory_manifest.local.yml``
    extension: its workspace rows are appended as candidates and its
    ``repo.tier3_workspace_id`` overrides the tracked one (PR #175 precedence).
    Rows keyed ``id:`` / ``workspace:`` instead of ``name:`` resolve too —
    matching goes through ``workspace_name()``.
    """
    candidates = _gather_workspace_rows(manifest) + _gather_workspace_rows(local_manifest)
    if not candidates:
        return None

    # Kimi #180 council: workspace resolution is template-relative — must live
    # in per-repo data, not copied logic. If the manifest declares
    # `repo.tier3_workspace_id`, that's THIS repo's canonical workspace name
    # (e.g. template-repo → "agent_factory_steward", verified live via
    # mcp__agentic-memory 2026-06-01). Wins over name/vault_root/basename match.
    # A local-manifest value overrides the tracked one when both are set.
    tier3_id: str | None = None
    for man in (local_manifest, manifest):  # local wins
        if not isinstance(man, dict):
            continue
        repo_block = man.get("repo")
        if isinstance(repo_block, dict):
            val = repo_block.get("tier3_workspace_id")
            if isinstance(val, str) and val.strip():
                tier3_id = val.strip()
                break
    if tier3_id:
        id_keys = name_match_keys(tier3_id)
        for workspace in candidates:
            name = workspace_name(workspace)
            if name and name_match_keys(name) & id_keys:
                return workspace
        # tier3_id declared but no matching workspace row → return None and let
        # SessionStart surface the standard "no workspace registered" warning
        # rather than silently degrade to a wrong workspace.
        return None

    # Name/alias matching comes BEFORE the vault_root fallback — this is the
    # documented contract ("match the workspace whose name matches this repo's
    # basename", MEMORY_CONTRACT + the skills ladder) and the high-traffic
    # SessionStart order. The old gate-side vault_root-first order was the
    # outlier the unification removes (PR #33 review, codex P2): the template
    # ships a generic tracked row with a RELATIVE vault_root that resolves
    # inside EVERY child checkout, so vault_root-first would steal resolution
    # from an operator's local basename row.
    basename_keys = name_match_keys(root.name)
    for workspace in candidates:
        name = workspace_name(workspace)
        if name and name_match_keys(name) & basename_keys:
            return workspace
    for workspace in candidates:
        if workspace_match_repo_basenames(workspace) & basename_keys:
            return workspace

    vault_matches: list[dict[str, Any]] = []
    for workspace in candidates:
        vault_root = workspace.get("vault_root")
        if not isinstance(vault_root, str):
            continue
        try:
            if resolve_vault_root(vault_root, root).is_relative_to(root):
                vault_matches.append(workspace)
        except (OSError, ValueError):
            pass
    if len(vault_matches) == 1:
        return vault_matches[0]
    return None


def active_workspace_backend(root: Path, workspace: str) -> str | None:
    manifest = load_manifest(root)
    active = resolve_workspace(root, manifest)
    if not active:
        return None
    active_name = workspace_name(active)
    if active_name != workspace and not (name_match_keys(active_name) & name_match_keys(workspace)):
        return None
    return workspace_backend(active)


def online_workspace_name_for_failure(root: Path) -> str | None:
    manifest = load_manifest(root)
    workspace = resolve_workspace(root, manifest)
    if not workspace or workspace_backend(workspace) == "graphiti":
        return None
    return workspace_name(workspace) or None


# ---------------------------------------------------------------------------
# Per-repo classification & workspace-resolution data (council #180 fix).
#
# A top-level ``repo:`` block in ``ops/memory_manifest.yml`` holds per-repo
# configuration the gate consumes. Schema:
#
#     repo:
#       # Optional. Overrides DEFAULT_CODE_PATH_PREFIXES — when present,
#       # REPLACES the defaults (each entry normalized to trailing "/").
#       code_dirs:
#         - "src"
#         - "scripts"
#         - "agent"         # child override: this repo's runtime code lives here
#         - "core"
#
#       # Optional. Overrides DEFAULT_CODE_PATH_TOP_LEVEL (exact filenames).
#       code_top_level:
#         - "pyproject.toml"
#         - "Justfile"      # child override
#
#       # Optional. The Tier-3 workspace this repo's memory canonically lives in,
#       # when it differs from the repo basename. E.g. template-repo's memory
#       # lives in "agent_factory_steward" (fleet/template governance workspace).
#       tier3_workspace_id: "agent_factory_steward"
#
# Why: hardcoding these in scripts/ meant the propagation wave copied template's
# code_dirs onto every child and clobbered each child's project-specific dirs —
# child production code then bypassed the gate (the regression we shipped).
# Putting them in per-repo manifest data means propagation updates LOGIC
# (scripts/hook_memory_gate.py) but never the per-repo classification surface.
# Mistral's adversarial review: editing this config to shrink the allowlist
# would re-introduce the bypass — but ``ops/`` is itself a code path, so
# editing ``ops/memory_manifest.yml`` requires a fresh substrate stamp
# (verified in tests/test_hook_memory_gate.py).
# ---------------------------------------------------------------------------


def load_repo_section(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Return the top-level ``repo:`` block, or an empty dict."""
    if not isinstance(manifest, dict):
        return {}
    repo = manifest.get("repo")
    return repo if isinstance(repo, dict) else {}


def repo_code_path_prefixes(manifest: dict[str, Any] | None) -> tuple[str, ...]:
    """Per-repo code-dir prefixes; absent block/key → ``DEFAULT_CODE_PATH_PREFIXES``.

    Each entry is normalized to a trailing-slash POSIX prefix
    (``"agent"`` → ``"agent/"``).
    """
    repo = load_repo_section(manifest)
    raw = repo.get("code_dirs")
    if not isinstance(raw, list) or not raw:
        return DEFAULT_CODE_PATH_PREFIXES
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip().replace("\\", "/").lstrip("/")
        if not s:
            continue
        if not s.endswith("/"):
            s = s + "/"
        out.append(s)
    return tuple(out) if out else DEFAULT_CODE_PATH_PREFIXES


def repo_code_path_top_level(manifest: dict[str, Any] | None) -> frozenset[str]:
    """Per-repo top-level code filenames; absent → ``DEFAULT_CODE_PATH_TOP_LEVEL``."""
    repo = load_repo_section(manifest)
    raw = repo.get("code_top_level")
    if not isinstance(raw, list) or not raw:
        return DEFAULT_CODE_PATH_TOP_LEVEL
    out = {s.strip() for s in raw if isinstance(s, str) and s.strip()}
    return frozenset(out) if out else DEFAULT_CODE_PATH_TOP_LEVEL


def repo_code_dir_top_level(manifest: dict[str, Any] | None) -> frozenset[str]:
    """Per-repo top-level code DIR names; derived from ``code_dirs`` first segments.

    Absent → ``DEFAULT_CODE_DIR_TOP_LEVEL``. Used to classify bare top-level
    references like ``Edit("scripts")`` (the directory itself) as code.
    """
    repo = load_repo_section(manifest)
    raw = repo.get("code_dirs")
    if isinstance(raw, list) and raw:
        out: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            first = item.strip().replace("\\", "/").lstrip("/").split("/", 1)[0]
            if first:
                out.add(first)
        if out:
            return frozenset(out)
    return DEFAULT_CODE_DIR_TOP_LEVEL


def repo_tier3_workspace_id(manifest: dict[str, Any] | None) -> str | None:
    """The Tier-3 workspace this repo's memory canonically lives in (per-repo data).

    Returns ``None`` when the ``repo:`` block omits ``tier3_workspace_id`` — in
    that case the prefetch's existing name/vault-root resolver fires. Set this
    when the canonical workspace name differs from the repo basename — e.g.
    template-repo's memory lives in ``agent_factory_steward`` (the fleet
    governance workspace, verified live via mcp__agentic-memory queries
    2026-06-01); the bare ``template_repo`` workspace row is a dead placeholder.
    """
    repo = load_repo_section(manifest)
    val = repo.get("tier3_workspace_id")
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


# ---------------------------------------------------------------------------
# Oracle / consumer-contract checker (Kimi #180 council — walk-back loop cure)
#
# Asserts that the gate's CLASSIFIER (the proposed code change) is consistent
# with the manifest's DECLARED code_dirs/code_top_level (the per-repo data).
# Catches: a propagation that changes gate logic in a way that breaks a
# child's declared dirs — surfaced at CI/merge, not by human review after.
# ---------------------------------------------------------------------------


def oracle_classification_failures(
    manifest: dict[str, Any] | None,
    # callable signature:
    #   (path, *, root, code_prefixes, code_top_level, code_dir_top_level) -> str
    classify_fn: Any,
    root: Path | None = None,
) -> list[str]:
    """Run the consumer-contract oracle for the manifest+classifier pair.

    For every declared ``code_dir`` and ``code_top_level``, synthesize a sample
    path and assert ``classify_fn(sample) == "code"``. Returns a list of
    failure strings (empty list == oracle PASS). Callers should assert
    ``len(failures) == 0`` and surface failures in the assertion message so
    the operator sees exactly which declaration the gate broke.

    Intra-repo use: load this repo's manifest, pass the gate's ``_classify``,
    fail at pytest time if classification drifts from declaration.

    Cross-repo (CI) use: a workflow can fetch each child's manifest, run this
    against the proposed gate code, fail the wave PR if any child's
    declarations are no longer honored — this is the walk-back loop cure
    (Kimi #180: catch the regression at CI/merge, not in human review).
    """
    prefixes = repo_code_path_prefixes(manifest)
    top_level = repo_code_path_top_level(manifest)
    dir_top = repo_code_dir_top_level(manifest)

    def _check(path: str) -> str:
        return classify_fn(
            path,
            root=root,
            code_prefixes=prefixes,
            code_top_level=top_level,
            code_dir_top_level=dir_top,
        )

    failures: list[str] = []
    for prefix in prefixes:
        sample = prefix + "oracle_sample_file.py"
        kind = _check(sample)
        if kind != "code":
            failures.append(
                f"code_dir '{prefix}' declared in ops/memory_manifest.yml "
                f"but '{sample}' classifies as '{kind}' (expected 'code')"
            )
    for top in sorted(top_level):
        kind = _check(top)
        if kind != "code":
            failures.append(
                f"code_top_level '{top}' declared in ops/memory_manifest.yml "
                f"but classifies as '{kind}' (expected 'code')"
            )
    return failures


# ---------------------------------------------------------------------------
# Shared substrate endpoint resolution (template-repo#180 / workstation-ops#170)
#
# Single source of truth for "how do I reach workspace X from THIS host",
# imported by BOTH the SessionStart prefetch hook and the memory gate so they
# cannot drift to different endpoint logic again. The prior bug: the prefetch
# hard-coded ``http://localhost:8020`` + a loopback-only SSRF guard, so it could
# never reach the substrate from a remote tailnet host even though the MCP read
# path (consumer fleet registry + Tailscale Serve) could. Result: the gate
# hard-blocked all code edits on every non-central host.
#
# This resolver is PURE (no network I/O — callers probe the returned
# candidates). Precedence: env bridge override -> consumer registry -> legacy
# registry -> manifest endpoint -> loopback. Security (council-reconciled,
# Mistral + Perplexity): the non-loopback allowlist is the set of hosts the
# trusted registries name, plus an explicitly-configured bridge host that is
# itself Tailscale-shaped (``*.ts.net`` or the 100.64.0.0/10 CGNAT range) — NOT
# a blanket wildcard. Non-loopback endpoints must be HTTPS: Tailscale Serve
# terminates TLS with a real ``*.ts.net`` cert, so callers connect via the
# ts.net hostname for SNI; raw-IP-over-HTTP across the tailnet is rejected.
# ---------------------------------------------------------------------------

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_REGISTRY_ENV_VARS = (
    "AGENTIC_MEMORY_REGISTRY_PATH",
    "AGENTIC_MEMORY_CONSUMER_REGISTRY_PATH",
    "LIGHTRAG_FLEET_REGISTRY",
)
# (dir, glob, source-label) — consumer registries first (host-local tailnet
# view), then the legacy registry. Mirrors the exporter/drift-probe precedence
# documented in docs/grafana.md.
_DEFAULT_REGISTRY_DIRS = (
    ("~/.config/mcp-servers", "*fleet-registry.toml", "consumer_registry"),
    ("~/.config/agentic-memory", "fleet_registry.toml", "legacy_registry"),
)
_DEFAULT_SUBSTRATE_PORT = 8020
# Closed-loopback placeholder ports (e.g. http://127.0.0.1:1 used by
# not-yet-provisioned manifest rows): never reachable, never a probe target.
_PLACEHOLDER_PORTS = frozenset({0, 1})


@dataclass(frozen=True)
class EndpointCandidate:
    """One ordered, allowlist-validated way to reach a workspace substrate."""

    url: str
    scheme: str
    host: str
    port: int
    source: str  # env_bridge|consumer_registry|legacy_registry|env_registry|manifest|loopback
    priority: int


def _is_loopback_host(host: str) -> bool:
    return host.strip("[]").strip().lower() in _LOOPBACK_HOSTS


def _is_tailnet_shaped(host: str) -> bool:
    """True for a ``*.ts.net`` hostname or an IP in Tailscale's 100.64.0.0/10."""
    import ipaddress

    cleaned = host.strip("[]").strip().lower()
    if not cleaned:
        return False
    if cleaned.endswith(".ts.net"):
        return True
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        return False
    return addr in ipaddress.ip_network("100.64.0.0/10")


def _split_endpoint(endpoint: str) -> tuple[str, str, int] | None:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(endpoint.strip())
    except (ValueError, AttributeError):
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None
    return parsed.scheme, parsed.hostname.lower(), int(port)


def _registry_sources(env: dict[str, str]) -> list[tuple[Path, str]]:
    """Ordered (path, source-label) registry files to consult.

    Honors the explicit override env vars in precedence order; otherwise globs
    the default consumer registry dir first, then the legacy registry.
    """
    explicit: list[tuple[Path, str]] = []
    for var in _REGISTRY_ENV_VARS:
        raw = (env.get(var) or "").strip()
        if not raw:
            continue
        candidate = Path(os.path.expanduser(raw))
        # Drift runtime ignores non-absolute override paths; match it so the
        # resolver can't follow a cwd-relative file the MCP layer won't load.
        if candidate.is_absolute():
            explicit.append((candidate, "env_registry"))
    if explicit:
        return explicit
    out: list[tuple[Path, str]] = []
    for dir_str, pattern, label in _DEFAULT_REGISTRY_DIRS:
        base = Path(os.path.expanduser(dir_str))
        if not base.is_dir():
            continue
        for path in sorted(base.glob(pattern)):
            out.append((path, label))
    return out


def _parse_registry(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return ``(rows, default_enabled)`` for a registry TOML file.

    ``default_enabled`` comes from a ``[defaults] enabled`` key when present
    (legacy registry shape); rows without their own ``enabled`` inherit it.
    """
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python < 3.11
        return [], True
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return [], True
    defaults_raw = data.get("defaults", {})
    if "defaults" in data and not isinstance(defaults_raw, dict):
        # Drift runtime discards the whole file when [defaults] is malformed.
        return [], {}
    defaults: dict[str, Any] = defaults_raw if isinstance(defaults_raw, dict) else {}
    # Match the drift runtime: only the `vaults` array defines substrate rows.
    value = data.get("vaults")
    rows = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    return rows, defaults


def _row_workspace_id(row: dict[str, Any]) -> str | None:
    # Precedence matches the fleet registry loaders (exporter / drift runtime):
    # canonical `id`, then `workspace`, then human-facing `name` last.
    for key in ("id", "workspace", "name"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _row_enabled(row: dict[str, Any], defaults: dict[str, Any]) -> bool:
    value = row.get("enabled", defaults.get("enabled", True))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _row_backend(row: dict[str, Any], defaults: dict[str, Any]) -> str:
    # Per-row backend wins; otherwise inherit the file-level [defaults].backend
    # (drift-runtime semantics); absent everywhere → LightRAG (consumer shape).
    backend = row.get("backend", defaults.get("backend"))
    if isinstance(backend, str) and backend.strip():
        return backend.strip().lower()
    return "lightrag"


def _row_is_lightrag(row: dict[str, Any], defaults: dict[str, Any]) -> bool:
    # Offline/graphiti rows are never on the agent read path.
    return _row_backend(row, defaults) == "lightrag"


def _row_endpoint(row: dict[str, Any], defaults: dict[str, Any]) -> str | None:
    # Consumer registries use `endpoint`; the legacy/source shape uses `api_url`,
    # and may carry a file-level [defaults] URL that per-row entries inherit.
    for source in (row, defaults):
        for key in ("endpoint", "api_url"):
            val = source.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return None


def resolve_memory_endpoints(
    workspace: str,
    manifest_workspace: dict[str, Any] | None = None,
    *,
    env: dict[str, str] | None = None,
    registry_sources: list[tuple[Path, str]] | None = None,
) -> list[EndpointCandidate]:
    """Resolve ordered, allowlist-validated substrate endpoints for THIS host.

    Shared by the SessionStart prefetch hook and the memory gate so the two
    cannot drift. Pure: no network I/O. Returns candidates ordered by priority
    (lower first); callers probe in order and use the first that answers.
    """
    env = dict(os.environ) if env is None else env
    keys = name_match_keys(workspace) if workspace else set()
    # (priority, source, scheme, host, port)
    raw: list[tuple[int, str, str, str, int]] = []
    registry_hosts: set[str] = set()

    sources = _registry_sources(env) if registry_sources is None else registry_sources
    for index, (path, label) in enumerate(sources):
        if not path.is_file():
            continue
        rows, defaults = _parse_registry(path)
        for row in rows:
            if not _row_enabled(row, defaults):
                continue  # a disabled vault is not a reachable probe target
            if not _row_is_lightrag(row, defaults):
                continue  # offline/graphiti rows are never on the agent read path
            rid = _row_workspace_id(row)
            if not rid:
                continue
            # An empty workspace must not match every registry row.
            if not keys or not (name_match_keys(rid) & keys):
                continue
            endpoint = _row_endpoint(row, defaults)
            if endpoint is None:
                continue
            parsed = _split_endpoint(endpoint)
            if parsed and parsed[2] not in _PLACEHOLDER_PORTS:
                # Collect from ALL sources; precedence is enforced by the
                # priority ordering (consumer registries rank above legacy),
                # and callers probe in order. We intentionally do NOT stop at
                # the first matching source: if a higher-precedence row is later
                # rejected by the allowlist (e.g. plain-HTTP to a tailnet IP), a
                # valid HTTPS endpoint from a lower-precedence registry must
                # still survive as a fallback.
                raw.append((20 + index, label, *parsed))
                if not _is_loopback_host(parsed[1]):
                    registry_hosts.add(parsed[1])

    if isinstance(manifest_workspace, dict):
        # Only attach the manifest endpoint when the row is actually THIS
        # workspace and is an online (lightrag) substrate — never a mismatched
        # snippet, an offline graphiti row, or (with an empty workspace arg) any
        # manifest row at all.
        mf_name = workspace_name(manifest_workspace)
        mf_matches = bool(mf_name) and bool(keys) and bool(name_match_keys(mf_name) & keys)
        endpoint = manifest_workspace.get("endpoint")
        if (
            mf_matches
            and workspace_backend(manifest_workspace) == "lightrag"
            and isinstance(endpoint, str)
        ):
            parsed = _split_endpoint(endpoint)
            # Skip closed-loopback placeholder rows (e.g. http://127.0.0.1:1):
            # they are never reachable and must not seed base_port or candidates.
            if parsed and parsed[2] not in _PLACEHOLDER_PORTS:
                mf_scheme, mf_host, mf_port = parsed
                if _is_loopback_host(mf_host):
                    # SECURITY (#7 SSRF, 2026-06-03 scan): the manifest ``endpoint`` is read
                    # from the OPERATED repo's tree (attacker-controllable). A loopback host
                    # otherwise short-circuits the allowlist, so a repo could point the
                    # SessionStart prefetch at ``http://127.0.0.1:<any-port>`` to probe local
                    # services and reflect responses into the agent context. Trust a
                    # manifest-named loopback endpoint ONLY on a registry-known loopback port
                    # (from trusted ~/.config registries, collected above) or the default
                    # substrate port — never an arbitrary port the repo names.
                    allowed_loopback_ports = {
                        port for (_pri, _lbl, _sch, _h, port) in raw if _is_loopback_host(_h)
                    } | {_DEFAULT_SUBSTRATE_PORT}
                    if mf_port in allowed_loopback_ports:
                        raw.append((40, "manifest", *parsed))
                    else:
                        sys.stderr.write(
                            "WARN  hook_memory_manifest: ignoring manifest loopback endpoint on "
                            f"untrusted port {mf_port} (not registry-known); SSRF guard (#7)\n"
                        )
                else:
                    # Non-loopback: validated later by the registry/bridge allowlist + HTTPS.
                    raw.append((40, "manifest", *parsed))

    bridge = (env.get("AGENTIC_MEMORY_BRIDGE_HOST") or "").strip().lower()
    bridge_allowed = (
        bool(bridge)
        and not _is_loopback_host(bridge)
        and (bridge in registry_hosts or _is_tailnet_shaped(bridge))
    )
    # Non-loopback allowlist: registry-named hosts + an explicitly-configured,
    # Tailscale-shaped bridge host. A manifest/registry host that merely *looks*
    # Tailscale-shaped but is neither registry-named nor the configured bridge is
    # NOT trusted (a repo-controlled manifest must not inject probe targets).
    allowed_nonloop = set(registry_hosts)
    if bridge_allowed:
        allowed_nonloop.add(bridge)

    def _accepted(scheme: str, host: str) -> bool:
        if _is_loopback_host(host):
            return True
        return host in allowed_nonloop and scheme == "https"

    # base_port and the "is there a real substrate?" decision come ONLY from
    # endpoints that survive the allowlist — a to-be-rejected host's port must
    # never set the loopback/bridge fallback port. Ignore placeholder ports and
    # the bare HTTPS-443 default (Serve fronts 443; the substrate listens on 8020+).
    # base_port: lowest-priority accepted port, excluding the bare HTTPS-443
    # default (Serve fronts 443; the substrate listens on 8020+). A 443-only
    # endpoint still counts as a real substrate (below) — it just doesn't set the
    # loopback port.
    port_seeds = sorted(
        (pri, port)
        for (pri, _src, scheme, host, port) in raw
        if _accepted(scheme, host) and port not in _PLACEHOLDER_PORTS and port != 443
    )
    base_port = port_seeds[0][1] if port_seeds else _DEFAULT_SUBSTRATE_PORT
    # A "real substrate" is any accepted, non-placeholder endpoint (443 included).
    have_real_substrate = any(
        _accepted(scheme, host) and port not in _PLACEHOLDER_PORTS
        for (_pri, _src, scheme, host, port) in raw
    )
    # A loopback fallback is only meaningful when the workspace config actually
    # points at loopback (central host). Synthesizing 127.0.0.1:<port> for a
    # remote-only substrate can hit an unrelated local service reusing the port
    # and stamp success for the wrong workspace (#187 review, Codex P2).
    have_loopback_signal = any(
        _is_loopback_host(host) and port not in _PLACEHOLDER_PORTS
        for (_pri, _src, _scheme, host, port) in raw
    )

    # The bridge reaches a real substrate — never synthesize it for a
    # placeholder/unprovisioned workspace that has no real endpoint of its own
    # (a global AGENTIC_MEMORY_BRIDGE_HOST must not fabricate a probe target for
    # an unprovisioned workspace; #187 review, Codex P1).
    if bridge_allowed and have_real_substrate:
        raw.append((10, "env_bridge", "https", bridge, base_port))

    # Loopback fallback only when the config actually points at loopback.
    if have_loopback_signal:
        raw.append((90, "loopback", "http", "127.0.0.1", base_port))

    seen: set[str] = set()
    out: list[EndpointCandidate] = []
    for priority, source, scheme, host, port in sorted(raw, key=lambda item: item[0]):
        if not _is_loopback_host(host):
            if host not in allowed_nonloop:
                continue  # not registry-named or the configured bridge
            if scheme != "https":
                continue  # non-loopback substrate must use Tailscale Serve TLS
        url = f"{scheme}://{host}:{port}"
        if url in seen:
            continue
        seen.add(url)
        out.append(EndpointCandidate(url, scheme, host, port, source, priority))
    return out
