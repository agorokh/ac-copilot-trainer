"""Shared manifest loading for deterministic memory hook scripts."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    """Parse the manifest subset needed by hooks when PyYAML is unavailable."""

    hosts: list[dict[str, Any]] = []
    in_hosts = False
    hosts_indent = -1
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

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        stripped = raw_line.strip()

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
    return {"hosts": hosts}


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


def resolve_workspace(root: Path, manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(manifest, dict):
        return None
    hosts = manifest.get("hosts") or []
    if not isinstance(hosts, list):
        return None
    candidates: list[dict[str, Any]] = []
    for host in hosts:
        if not isinstance(host, dict):
            continue
        rows = host.get("workspaces") or []
        if not isinstance(rows, list):
            continue
        candidates.extend(row for row in rows if isinstance(row, dict))
    if not candidates:
        return None

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

    basename_keys = name_match_keys(root.name)
    for workspace in candidates:
        name = workspace_name(workspace)
        if name and name_match_keys(name) & basename_keys:
            return workspace
    for workspace in candidates:
        if workspace_match_repo_basenames(workspace) & basename_keys:
            return workspace
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
