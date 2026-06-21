# OWNER: @agorokh
"""Fleet inference-egress client: the ONE canonical resolver for provider
``base_url`` / API key / auth header / ``X-App-Label``. The third governed asset class
(after hooks and skills) per ADR ``adr-2026-06-19-inference-egress-client-canonical-home``
(governance-hub#67).

Reference-not-vendor: spokes IMPORT this from ``$FLEET_GOVERNANCE_ROOT/runtime``, they do
not copy it (conformance forbids a re-vendored copy). Extracted close to verbatim from the
fleet's de-facto shared client (agent-factory ``tools/process_miner/distill.py``); the logic
is proven in production, so this is an extraction, not a rewrite.

Provider-auth authority: this module is the runtime embodiment of
``adr-2026-05-19-subscription-routing-contract`` (the authority for ALL provider auth on this
fleet). DIAL uses ``Api-Key``; OpenAI / OpenRouter / generic OpenAI-compatible
endpoints use ``Authorization: Bearer``. ``DIAL_API_KEY_PROJECT`` is preferred for ingestion
workloads. The opt-in ``X-App-Label`` header carries per-consumer attribution to the
inference-governance gateway (dial-sandbox#506); set it so a consumer's egress is governable.

Pure stdlib, no network in this module (callers own the HTTP). Env-var NAMES are parameters
with distill-compatible defaults, so the process-miner and the bespoke consumers
(alpaca / disclosures / stock_hero) share one implementation.
"""

from __future__ import annotations

import functools
import os
import urllib.parse
from pathlib import Path

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _deployment_default_dial_host() -> str:
    """The deployment default DIAL proxy host, read from the sibling ``dial_host.txt`` file.

    The internal infra hostname lives in ``dial_host.txt`` (PRIVATE hub only), NOT in this module,
    because this module is byte-vendored into PUBLIC spokes (governance-hub#75) and must carry no
    internal hostname. The sidecar is co-located in ``$FLEET_GOVERNANCE_ROOT/runtime`` (which every
    spoke already imports), so runtime DIAL detection is unchanged fleet-wide with no env rollout.
    Read by path off ``__file__`` so it resolves whether this file is imported as part of the
    ``inference_egress`` package or loaded standalone. Absent in a public vendored copy (which
    excludes ``dial_host.txt``) -> empty, and callers fall back to ``$DIAL_PROXY_HOST``.
    """
    try:
        text = (Path(__file__).resolve().parent / "dial_host.txt").read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped.lower()
    return ""


# Deployment default DIAL proxy host (empty in a public vendored copy that excludes the sidecar).
DIAL_PROXY_HOST_MARKER = _deployment_default_dial_host()


@functools.lru_cache(maxsize=32)
def _extra_host_markers(raw: str) -> tuple[str, ...]:
    """Lowercase markers from a comma-separated env value; cached by raw string so an
    edit invalidates cheaply. Tests that change the env must call ``cache_clear()``."""
    raw = (raw or "").strip()
    if not raw:
        return ()
    return tuple(dict.fromkeys(m.strip().lower() for m in raw.split(",") if m.strip()))


def safe_url_hostname(url: str) -> str:
    """Lowercase hostname for ``url``, or empty if missing or ``urlparse`` raises."""
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def host_matches_marker(host: str, marker: str) -> bool:
    """Whether ``host`` matches ``marker`` (exact hostname or a registrable subdomain).

    Registrable-boundary match (``host == m`` or ``host endswith '.' + m``) so that
    ``api.openai.com`` matches ``openai.com`` but ``evilopenai.com`` does not.
    """
    h = (host or "").lower()
    m = (marker or "").lower()
    return bool(h) and bool(m) and (h == m or h.endswith("." + m))


def is_dial_host(
    host: str, *, host_env: str = "DIAL_PROXY_HOST", extra_hosts_env: str = "DIAL_EXTRA_HOSTS"
) -> bool:
    """Whether ``host`` is the DIAL proxy (registrable-boundary match).

    The primary marker is ``$DIAL_PROXY_HOST`` when set, else the deployment default
    ``DIAL_PROXY_HOST_MARKER`` (provided out of band — see ``_deployment_default_dial_host``).
    Honors ``$DIAL_EXTRA_HOSTS`` (comma-separated) for reverse-proxy / tailnet-served DIAL
    relay hosts.
    """
    primary = os.environ.get(host_env, "").strip() or DIAL_PROXY_HOST_MARKER
    extras = _extra_host_markers(os.environ.get(extra_hosts_env, ""))
    return host_matches_marker(host, primary) or any(
        host_matches_marker(host, marker) for marker in extras
    )


def normalized_base_url(explicit: str | None = None, *, base_url_env: str = "DISTILL_BASE_URL") -> str:
    """Strip and default the base URL; prepend ``https://`` when the scheme is omitted."""
    raw = (explicit if explicit is not None else os.environ.get(base_url_env)) or DEFAULT_BASE_URL
    raw = raw.strip()
    if not raw:
        return DEFAULT_BASE_URL
    if "://" not in raw:
        raw = "https://" + raw
    return raw


def resolve_api_key(
    url: str,
    *,
    global_key_env: str = "DISTILL_API_KEY",
    openrouter_env: str = "OPENROUTER_API_KEY",
    openai_env: str = "OPENAI_API_KEY",
    dial_project_env: str = "DIAL_API_KEY_PROJECT",
    dial_env: str = "DIAL_API_KEY",
) -> str | None:
    """Resolve the API key for the host in ``url`` (per-request URL).

    A global override (``$DISTILL_API_KEY`` by default) wins. Otherwise the hostname of
    ``url`` selects the provider key, so a per-call ``base_url`` override cannot attach the
    wrong credential. DIAL prefers ``$DIAL_API_KEY_PROJECT`` (higher rate limit for
    ingestion) then falls back to ``$DIAL_API_KEY``.
    """
    override = os.environ.get(global_key_env, "").strip()
    if override:
        return override
    host = safe_url_hostname(url)
    if host == "openrouter.ai" or host.endswith(".openrouter.ai"):
        return os.environ.get(openrouter_env, "").strip() or None
    if host == "api.openai.com" or host.endswith(".openai.com"):
        return os.environ.get(openai_env, "").strip() or None
    if is_dial_host(host):
        project_key = os.environ.get(dial_project_env, "").strip()
        if project_key:
            return project_key
        return os.environ.get(dial_env, "").strip() or None
    return None


def auth_headers(url: str, api_key: str) -> dict[str, str]:
    """Build the auth header dict for ``url``.

    DIAL expects ``Api-Key: <key>``; OpenAI / OpenRouter / generic
    OpenAI-compatible endpoints expect ``Authorization: Bearer <key>``.
    """
    if is_dial_host(safe_url_hostname(url)):
        return {"Api-Key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def app_label_headers(*, label_env: str = "DISTILL_APP_LABEL") -> dict[str, str]:
    """Opt-in ``X-App-Label`` header for per-consumer gateway attribution.

    The inference-governance gateway (dial-sandbox#506) keys cost attribution off
    ``X-App-Label``. The header is inert metadata to endpoints that do not consume it, so it
    is sent regardless of host. Off by default (empty env, zero behaviour change); set
    ``$DISTILL_APP_LABEL`` (or pass ``label_env``) to enable.
    """
    label = os.environ.get(label_env, "").strip()
    return {"X-App-Label": label} if label else {}


def request_headers(
    url: str,
    api_key: str,
    *,
    label_env: str = "DISTILL_APP_LABEL",
    content_type: str = "application/json",
) -> dict[str, str]:
    """The full header dict for one request: content-type, auth, and the opt-in app label."""
    return {
        "Content-Type": content_type,
        **auth_headers(url, api_key),
        **app_label_headers(label_env=label_env),
    }
