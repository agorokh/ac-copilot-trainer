"""Protocol v1 *external-client* extension (issue #81).

This module is independent of ``protocol.py`` (which carries the legacy
``{"protocol":1,"event":"lap_complete"}`` Lua-↔-Python coaching flow). The
external surface uses the more compact ``{"v":1,"type":"..."}`` envelope so the
ESP32 firmware can encode/decode without tracking two field names.

All frames are JSON objects. Unknown ``type`` values are rejected by
``validate_inbound()`` and produce an ``error`` frame from the sidecar.
"""

from __future__ import annotations

from typing import Any

# Envelope key that identifies a v1 external-client frame.
ENVELOPE_KEY = "v"
ENVELOPE_VERSION = 1
TYPE_KEY = "type"
SERVER_VERSION = "1.0.0"

# Client → server.
TYPE_HELLO = "hello"
TYPE_CONFIG_GET = "config.get"
TYPE_CONFIG_SET = "config.set"
TYPE_ACTION = "action"
TYPE_STATE_SUBSCRIBE = "state.subscribe"
TYPE_STATE_UNSUBSCRIBE = "state.unsubscribe"

# Server → client.
TYPE_HELLO_ACK = "hello_ack"
TYPE_CONFIG_VALUE = "config.value"
TYPE_CONFIG_ACK = "config.ack"
TYPE_ACTION_ACK = "action.ack"
TYPE_STATE_SNAPSHOT = "state.snapshot"
TYPE_ERROR = "error"

# Capabilities advertised in `hello_ack` so clients can branch on optional
# server features without a v2 bump.
SERVER_CAPABILITIES: tuple[str, ...] = (
    TYPE_CONFIG_GET,
    TYPE_CONFIG_SET,
    TYPE_ACTION,
    TYPE_STATE_SUBSCRIBE,
)

# Names a client may invoke via `action`. Mirrors the Lua dispatcher in
# ``modules/ws_bridge.lua``; the sidecar only validates that the name is
# in this whitelist, the Lua side actually performs the action.
KNOWN_ACTIONS: frozenset[str] = frozenset(
    {
        "toggleFocusPractice",
        "cycleRacingLine",
        "tareDelta",
        "reloadSetup",
        "applySetupFromPath",
    }
)

# Topics a client may `state.subscribe` to. Same rule as actions: the Lua side
# is the producer; the sidecar fans out snapshots.
KNOWN_TOPICS: frozenset[str] = frozenset(
    {
        "connection",
        "session",
        "lap",
        "delta",
        "tire_temps",
    }
)

# Header used on the WS upgrade for shared-secret auth.
AUTH_HEADER = "X-AC-Copilot-Token"
CLIENT_HEADER = "X-AC-Copilot-Client"


def make_hello_ack(server_version: str = SERVER_VERSION) -> dict[str, Any]:
    return {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: TYPE_HELLO_ACK,
        "server_version": server_version,
        "capabilities": list(SERVER_CAPABILITIES),
    }


def make_error(message: str, *, ref_type: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: TYPE_ERROR,
        "message": message,
    }
    if ref_type is not None:
        out["ref_type"] = ref_type
    return out


def validate_inbound(frame: dict[str, Any]) -> str | None:
    """Return ``None`` if ``frame`` is structurally valid, else an error string."""
    version = frame.get(ENVELOPE_KEY)
    if isinstance(version, bool) or version != ENVELOPE_VERSION:
        return f"unsupported envelope version: {frame.get(ENVELOPE_KEY)!r}"
    t = frame.get(TYPE_KEY)
    if not isinstance(t, str) or not t:
        return "frame requires non-empty string 'type'"
    if t == TYPE_HELLO:
        if not isinstance(frame.get("client"), str) or not frame["client"]:
            return "hello requires non-empty 'client'"
        return None
    if t == TYPE_CONFIG_GET:
        if not isinstance(frame.get("key"), str) or not frame["key"]:
            return "config.get requires non-empty 'key'"
        return None
    if t == TYPE_CONFIG_SET:
        if not isinstance(frame.get("key"), str) or not frame["key"]:
            return "config.set requires non-empty 'key'"
        if "value" not in frame:
            return "config.set requires 'value'"
        return None
    if t == TYPE_ACTION:
        name = frame.get("name")
        if not isinstance(name, str) or not name:
            return "action requires non-empty 'name'"
        if name not in KNOWN_ACTIONS:
            return f"unknown action: {name!r}"
        return None
    if t in (TYPE_STATE_SUBSCRIBE, TYPE_STATE_UNSUBSCRIBE):
        topics = frame.get("topics")
        if not isinstance(topics, list) or not topics:
            return f"{t} requires non-empty 'topics' list"
        for topic in topics:
            if not isinstance(topic, str) or not topic:
                return f"{t} 'topics' entries must be non-empty strings"
            if topic not in KNOWN_TOPICS:
                return f"unknown topic: {topic!r}"
        return None
    # Server→client types may legitimately appear when the Lua client forwards
    # a reply for the sidecar to fan out — accept silently.
    if t in (
        TYPE_HELLO_ACK,
        TYPE_CONFIG_VALUE,
        TYPE_CONFIG_ACK,
        TYPE_ACTION_ACK,
        TYPE_STATE_SNAPSHOT,
        TYPE_ERROR,
    ):
        return None
    return f"unknown type: {t!r}"
