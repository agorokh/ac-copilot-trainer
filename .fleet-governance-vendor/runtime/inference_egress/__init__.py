# OWNER: @agorokh
"""Fleet inference-egress client package (the third governed asset class, governance-hub#67).

Reference-not-vendor: import from ``$FLEET_GOVERNANCE_ROOT/runtime``
(``from inference_egress import resolve_api_key, auth_headers, ...``); do not copy this
package into a spoke (conformance forbids a re-vendored drifted copy). ADR
``adr-2026-06-19-inference-egress-client-canonical-home``.
"""

from __future__ import annotations

from .client import (
    DEFAULT_BASE_URL,
    DIAL_PROXY_HOST_MARKER,
    app_label_headers,
    auth_headers,
    host_matches_marker,
    is_dial_host,
    normalized_base_url,
    request_headers,
    resolve_api_key,
    safe_url_hostname,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DIAL_PROXY_HOST_MARKER",
    "app_label_headers",
    "auth_headers",
    "host_matches_marker",
    "is_dial_host",
    "normalized_base_url",
    "request_headers",
    "resolve_api_key",
    "safe_url_hostname",
]
