"""Tests for the shared substrate endpoint resolver.

Covers the council-reconciled design for template-repo#180 / workstation-ops#170:
one resolver shared by the SessionStart prefetch hook and the memory gate, so a
remote tailnet host resolves the same reachable endpoint the MCP read path uses
instead of dead loopback. Security: non-loopback endpoints must be HTTPS and
within the Tailscale trust boundary (registry-named host or ``*.ts.net`` /
100.64.0.0/10), never an arbitrary external host.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from hook_memory_manifest import (  # noqa: E402
    EndpointCandidate,
    _is_tailnet_shaped,
    _split_endpoint,
    resolve_memory_endpoints,
)

WORKSPACE = "agent_factory_steward"
TSNET_HOST = "m2pro.tail31ce1b.ts.net"
TAILNET_IP = "100.71.123.90"


def _write_registry(
    tmp_path: Path, name: str, endpoint: str, *, workspace: str = WORKSPACE
) -> Path:
    path = tmp_path / name
    path.write_text(
        f'[[vaults]]\nid = "{workspace}"\nendpoint = "{endpoint}"\n',
        encoding="utf-8",
    )
    return path


def _urls(candidates: list[EndpointCandidate]) -> list[str]:
    return [c.url for c in candidates]


def test_tailnet_shaped_helper() -> None:
    assert _is_tailnet_shaped(TSNET_HOST)
    assert _is_tailnet_shaped(TAILNET_IP)  # 100.64.0.0/10
    assert _is_tailnet_shaped("100.127.255.255")
    assert not _is_tailnet_shaped("example.com")
    assert not _is_tailnet_shaped("8.8.8.8")
    assert not _is_tailnet_shaped("100.128.0.1")  # just outside CGNAT range
    assert not _is_tailnet_shaped("")


def test_split_endpoint() -> None:
    assert _split_endpoint("https://m2pro.tail31ce1b.ts.net:8020") == ("https", TSNET_HOST, 8020)
    assert _split_endpoint("http://localhost:8020") == ("http", "localhost", 8020)
    assert _split_endpoint("https://host.ts.net") == ("https", "host.ts.net", 443)
    assert _split_endpoint("ftp://x:1") is None
    assert _split_endpoint("not a url") is None


def test_remote_consumer_registry_https_resolves_before_loopback(tmp_path: Path) -> None:
    reg = _write_registry(tmp_path, "m5-fleet-registry.toml", f"https://{TAILNET_IP}:8020")
    manifest_ws = {"name": WORKSPACE, "endpoint": "http://localhost:8020"}
    out = resolve_memory_endpoints(
        WORKSPACE,
        manifest_ws,
        env={},
        registry_sources=[(reg, "consumer_registry")],
    )
    urls = _urls(out)
    assert f"https://{TAILNET_IP}:8020" in urls
    # registry endpoint (priority 20) must come before the loopback fallback (90)
    assert urls.index(f"https://{TAILNET_IP}:8020") < urls.index("http://127.0.0.1:8020")
    assert out[0].source == "consumer_registry"


def test_env_bridge_tsnet_takes_top_priority(tmp_path: Path) -> None:
    # Only a loopback manifest is known (the exact remote-host bug); the bridge
    # env var must still yield a reachable HTTPS ts.net candidate, ranked first.
    manifest_ws = {"name": WORKSPACE, "endpoint": "http://localhost:8020"}
    out = resolve_memory_endpoints(
        WORKSPACE,
        manifest_ws,
        env={"AGENTIC_MEMORY_BRIDGE_HOST": TSNET_HOST},
        registry_sources=[],
    )
    assert out[0].source == "env_bridge"
    assert out[0].url == f"https://{TSNET_HOST}:8020"
    assert out[0].scheme == "https"


def test_non_loopback_http_is_rejected(tmp_path: Path) -> None:
    # A non-loopback endpoint over plain HTTP must be dropped (Tailscale Serve TLS).
    reg = _write_registry(tmp_path, "m5-fleet-registry.toml", f"http://{TAILNET_IP}:8020")
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "consumer_registry")]
    )
    assert all(not c.url.startswith(f"http://{TAILNET_IP}") for c in out)
    # the rejected plain-HTTP endpoint was the only signal → no real substrate
    assert _urls(out) == []  # no real substrate → no default-loopback probe (#180 P1/B)


def test_poisoned_manifest_external_host_rejected() -> None:
    manifest_ws = {"name": WORKSPACE, "endpoint": "https://evil.example.com:8020"}
    out = resolve_memory_endpoints(WORKSPACE, manifest_ws, env={}, registry_sources=[])
    assert all("evil.example.com" not in c.url for c in out)
    assert _urls(out) == []  # no real substrate → no default-loopback probe (#180 P1/B)


def test_bridge_external_host_rejected() -> None:
    manifest_ws = {"name": WORKSPACE, "endpoint": "http://localhost:8020"}
    out = resolve_memory_endpoints(
        WORKSPACE,
        manifest_ws,
        env={"AGENTIC_MEMORY_BRIDGE_HOST": "evil.example.com"},
        registry_sources=[],
    )
    assert all(c.source != "env_bridge" for c in out)
    assert all("evil.example.com" not in c.url for c in out)


def test_loopback_manifest_is_kept() -> None:
    manifest_ws = {"name": WORKSPACE, "endpoint": "http://localhost:8020"}
    out = resolve_memory_endpoints(WORKSPACE, manifest_ws, env={}, registry_sources=[])
    assert "http://localhost:8020" in _urls(out)
    assert "http://127.0.0.1:8020" in _urls(out)


def test_workspace_id_mismatch_excluded(tmp_path: Path) -> None:
    reg = _write_registry(
        tmp_path, "m5-fleet-registry.toml", f"https://{TAILNET_IP}:8040", workspace="epam_dialx"
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "consumer_registry")]
    )
    # the epam_dialx row must not leak into agent_factory_steward resolution
    assert all(":8040" not in c.url for c in out)


def test_dedup_across_sources(tmp_path: Path) -> None:
    reg1 = _write_registry(tmp_path, "m5-fleet-registry.toml", f"https://{TAILNET_IP}:8020")
    reg2 = _write_registry(tmp_path, "other-fleet-registry.toml", f"https://{TAILNET_IP}:8020")
    out = resolve_memory_endpoints(
        WORKSPACE,
        None,
        env={},
        registry_sources=[(reg1, "consumer_registry"), (reg2, "consumer_registry")],
    )
    assert _urls(out).count(f"https://{TAILNET_IP}:8020") == 1


def test_candidates_ordered_by_priority(tmp_path: Path) -> None:
    reg = _write_registry(tmp_path, "m5-fleet-registry.toml", f"https://{TAILNET_IP}:8020")
    manifest_ws = {"name": WORKSPACE, "endpoint": "http://localhost:8020"}
    out = resolve_memory_endpoints(
        WORKSPACE,
        manifest_ws,
        env={"AGENTIC_MEMORY_BRIDGE_HOST": TSNET_HOST},
        registry_sources=[(reg, "consumer_registry")],
    )
    priorities = [c.priority for c in out]
    assert priorities == sorted(priorities)
    assert out[0].source == "env_bridge"  # ts.net hostname (SNI/cert) tried first


def test_disabled_registry_row_is_skipped(tmp_path: Path) -> None:
    # enabled = false rows exist in the live consumer registry and must NOT
    # become probe targets (workstation-ops#171 Cursor finding).
    reg = tmp_path / "m5-fleet-registry.toml"
    reg.write_text(
        f'[[vaults]]\nid = "{WORKSPACE}"\n'
        f'endpoint = "https://{TAILNET_IP}:8020"\nenabled = false\n',
        encoding="utf-8",
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "consumer_registry")]
    )
    assert all(":8020" not in c.url or c.source == "loopback" for c in out)
    assert _urls(out) == []  # no real substrate → no default-loopback probe (#180 P1/B)


def test_defaults_disabled_inherited_when_row_silent(tmp_path: Path) -> None:
    reg = tmp_path / "m5-fleet-registry.toml"
    reg.write_text(
        f'[defaults]\nenabled = false\n\n[[vaults]]\nid = "{WORKSPACE}"\n'
        f'endpoint = "https://{TAILNET_IP}:8020"\n',
        encoding="utf-8",
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "consumer_registry")]
    )
    assert all(c.source != "consumer_registry" for c in out)


def test_non_lightrag_registry_row_is_skipped(tmp_path: Path) -> None:
    reg = tmp_path / "fleet_registry.toml"
    reg.write_text(
        f'[[vaults]]\nworkspace = "{WORKSPACE}"\napi_url = "https://{TAILNET_IP}:8020"\n'
        'backend = "graphiti"\n',
        encoding="utf-8",
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "legacy_registry")]
    )
    assert _urls(out) == []  # no real substrate → no default-loopback probe (#180 P1/B)


def test_api_url_fallback_and_workspace_id(tmp_path: Path) -> None:
    # Legacy/source registry shape: `workspace` id + `api_url` endpoint.
    reg = tmp_path / "fleet_registry.toml"
    reg.write_text(
        f'[[vaults]]\nworkspace = "{WORKSPACE}"\napi_url = "https://{TAILNET_IP}:8020"\n',
        encoding="utf-8",
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "legacy_registry")]
    )
    assert f"https://{TAILNET_IP}:8020" in _urls(out)


def test_placeholder_loopback_endpoint_is_skipped() -> None:
    # The not-yet-provisioned manifest placeholder must not seed a port-1
    # candidate or set base_port to 1.
    manifest_ws = {"name": WORKSPACE, "endpoint": "http://127.0.0.1:1"}
    out = resolve_memory_endpoints(WORKSPACE, manifest_ws, env={}, registry_sources=[])
    assert all(":1" not in c.url for c in out)
    # placeholder is unprovisioned → no real substrate → no default-loopback probe
    assert _urls(out) == []


def test_remote_https_443_endpoint_does_not_synthesize_loopback(tmp_path: Path) -> None:
    # A portless HTTPS registry endpoint defaults to 443. It is a valid remote
    # candidate, but since the config has no loopback signal NO loopback fallback
    # is synthesized — and 443 must never leak into a loopback port.
    reg = tmp_path / "m5-fleet-registry.toml"
    reg.write_text(
        f'[[vaults]]\nid = "{WORKSPACE}"\nendpoint = "https://{TSNET_HOST}"\n',
        encoding="utf-8",
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "consumer_registry")]
    )
    assert f"https://{TSNET_HOST}:443" in _urls(out)
    assert not any(c.url.startswith("http://127.0.0.1") for c in out)


def test_empty_workspace_does_not_match_all_rows(tmp_path: Path) -> None:
    reg = _write_registry(
        tmp_path, "m5-fleet-registry.toml", f"https://{TAILNET_IP}:8040", workspace="epam_dialx"
    )
    out = resolve_memory_endpoints("", None, env={}, registry_sources=[(reg, "consumer_registry")])
    assert all(":8040" not in c.url for c in out)


def test_higher_precedence_registry_ranks_first_but_fallback_kept(tmp_path: Path) -> None:
    # Precedence is by ordering, not by dropping: the consumer registry endpoint
    # ranks before the legacy one, but the legacy endpoint survives as a fallback
    # (so a rejected higher-precedence endpoint never strands the resolver).
    reg1 = _write_registry(tmp_path, "m5-fleet-registry.toml", f"https://{TAILNET_IP}:8020")
    reg2 = _write_registry(tmp_path, "legacy.toml", f"https://{TAILNET_IP}:9999")
    out = resolve_memory_endpoints(
        WORKSPACE,
        None,
        env={},
        registry_sources=[(reg1, "consumer_registry"), (reg2, "legacy_registry")],
    )
    urls = _urls(out)
    assert f"https://{TAILNET_IP}:8020" in urls and f"https://{TAILNET_IP}:9999" in urls
    assert urls.index(f"https://{TAILNET_IP}:8020") < urls.index(f"https://{TAILNET_IP}:9999")


def test_break_does_not_strand_when_top_endpoint_rejected(tmp_path: Path) -> None:
    # Higher-precedence row matches but its endpoint is plain-HTTP to a tailnet IP
    # (rejected by the allowlist); the lower-precedence HTTPS endpoint must remain.
    reg1 = _write_registry(tmp_path, "m5-fleet-registry.toml", f"http://{TAILNET_IP}:8020")
    reg2 = _write_registry(tmp_path, "legacy.toml", f"https://{TAILNET_IP}:8040")
    out = resolve_memory_endpoints(
        WORKSPACE,
        None,
        env={},
        registry_sources=[(reg1, "consumer_registry"), (reg2, "legacy_registry")],
    )
    assert f"https://{TAILNET_IP}:8040" in _urls(out)


def test_defaults_backend_graphiti_skips_row(tmp_path: Path) -> None:
    reg = tmp_path / "fleet_registry.toml"
    reg.write_text(
        f'[defaults]\nbackend = "graphiti"\n\n[[vaults]]\nworkspace = "{WORKSPACE}"\n'
        f'api_url = "https://{TAILNET_IP}:8020"\n',
        encoding="utf-8",
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "legacy_registry")]
    )
    assert _urls(out) == []  # no real substrate → no default-loopback probe (#180 P1/B)


def test_defaults_api_url_inherited(tmp_path: Path) -> None:
    reg = tmp_path / "fleet_registry.toml"
    reg.write_text(
        f'[defaults]\napi_url = "https://{TAILNET_IP}:8020"\n\n'
        f'[[vaults]]\nworkspace = "{WORKSPACE}"\n',
        encoding="utf-8",
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "legacy_registry")]
    )
    assert f"https://{TAILNET_IP}:8020" in _urls(out)


def test_manifest_endpoint_workspace_mismatch_rejected() -> None:
    # A manifest snippet for a DIFFERENT workspace must not attach its URL.
    manifest_ws = {"name": "some_other_ws", "endpoint": f"https://{TAILNET_IP}:8020"}
    out = resolve_memory_endpoints(WORKSPACE, manifest_ws, env={}, registry_sources=[])
    assert all(c.source != "manifest" for c in out)


def test_manifest_graphiti_row_skipped() -> None:
    manifest_ws = {
        "name": WORKSPACE,
        "backend": "graphiti",
        "endpoint": f"https://{TAILNET_IP}:8020",
    }
    out = resolve_memory_endpoints(WORKSPACE, manifest_ws, env={}, registry_sources=[])
    assert all(c.source != "manifest" for c in out)


def test_invalid_defaults_table_discards_file(tmp_path: Path) -> None:
    reg = tmp_path / "m5-fleet-registry.toml"
    reg.write_text(
        f'defaults = "oops"\n[[vaults]]\nid = "{WORKSPACE}"\n'
        f'endpoint = "https://{TAILNET_IP}:8020"\n',
        encoding="utf-8",
    )
    out = resolve_memory_endpoints(
        WORKSPACE, None, env={}, registry_sources=[(reg, "consumer_registry")]
    )
    assert all(c.source != "consumer_registry" for c in out)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
