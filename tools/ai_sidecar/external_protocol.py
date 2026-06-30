"""Protocol v1 *external-client* extension (issue #81).

This module is independent of ``protocol.py`` (which carries the legacy
``{"protocol":1,"event":"lap_complete"}`` Lua-↔-Python coaching flow). The
external surface uses the more compact ``{"v":1,"type":"..."}`` envelope so the
ESP32 firmware can encode/decode without tracking two field names.

All frames are JSON objects. Unknown ``type`` values are rejected by
``validate_inbound()`` and produce an ``error`` frame from the sidecar.
"""

from __future__ import annotations

import json
import math
from typing import Any

# Envelope key that identifies a v1 external-client frame.
ENVELOPE_KEY = "v"
ENVELOPE_VERSION = 1
TYPE_KEY = "type"
SERVER_VERSION = "1.0.0"
CLIENT_CLASS_KEY = "client_class"

# Optional client classes advertised in `hello`. Existing clients that omit the
# field keep working as generic external peers.
CLIENT_CLASS_EXTERNAL = "external"
CLIENT_CLASS_LUA = "lua"
CLIENT_CLASS_SCREEN = "screen"
CLIENT_CLASS_HAPTICS = "haptics"
CLIENT_CLASS_PHYSICAL = "physical"
CLIENT_CLASS_BROWSER = "browser"
# Issue #341: a voice-coach client subscribes to `coaching.cue` and speaks the live advisory
# stream (the #340 phrase-bank engine). On the rig the sidecar also drives a VoiceCoach in-process,
# but a separate `voice`-class WS client is a first-class consumer (e.g. a remote speaker / a tap).
CLIENT_CLASS_VOICE = "voice"
KNOWN_CLIENT_CLASSES: frozenset[str] = frozenset(
    {
        CLIENT_CLASS_EXTERNAL,
        CLIENT_CLASS_LUA,
        CLIENT_CLASS_SCREEN,
        CLIENT_CLASS_HAPTICS,
        CLIENT_CLASS_PHYSICAL,
        CLIENT_CLASS_BROWSER,
        CLIENT_CLASS_VOICE,
    }
)
PHYSICAL_CLIENT_CLASSES: frozenset[str] = frozenset(
    {CLIENT_CLASS_SCREEN, CLIENT_CLASS_HAPTICS, CLIENT_CLASS_PHYSICAL}
)
HAPTIC_CLIENT_CLASSES: frozenset[str] = frozenset({CLIENT_CLASS_HAPTICS, CLIENT_CLASS_PHYSICAL})
MAX_SETUP_SNAPSHOT_KEYS = 512
MAX_SETUP_SNAPSHOT_BYTES = 64_000

# Client → server.
TYPE_HELLO = "hello"
TYPE_CONFIG_GET = "config.get"
TYPE_CONFIG_SET = "config.set"
TYPE_ACTION = "action"
TYPE_STATE_SUBSCRIBE = "state.subscribe"
TYPE_STATE_UNSUBSCRIBE = "state.unsubscribe"
# Issue #86 Part D: rig-screen → trainer Lua request types. The sidecar relays
# these to the loopback Lua peer; replies come back as `setup.list.result` /
# `setup.load.ack` (server→client below). Validation is structural only —
# the Lua side enforces the in-pits gate and does the actual ac.loadSetup().
TYPE_SETUP_LIST = "setup.list"
TYPE_SETUP_LOAD = "setup.load"
TYPE_SETUP_SPINNER_LIST = "setup.spinner.list"
TYPE_SETUP_SPINNER_SET = "setup.spinner.set"
TYPE_SETUP_EXPERIMENT_STORE = "setup.experiment.store"
TYPE_SETUP_EXPERIMENT_RECORD = "setup.experiment.record"
TYPE_SETUP_COMPARE = "setup.compare"
TYPE_SETUP_SUGGEST = "setup.suggest"
TYPE_SETUP_ADVICE = "setup.advice"
TYPE_SETUP_DIFF = "setup.diff"
TYPE_SETUP_CLOSED_LOOP = "setup.closed_loop"
TYPE_SETUP_EXCHANGE_SEARCH = "se.search"
TYPE_SETUP_EXCHANGE_DOWNLOAD = "se.download"

# Server → client.
TYPE_HELLO_ACK = "hello_ack"
TYPE_CONFIG_VALUE = "config.value"
TYPE_CONFIG_ACK = "config.ack"
TYPE_ACTION_ACK = "action.ack"
TYPE_STATE_SNAPSHOT = "state.snapshot"
TYPE_ERROR = "error"
# Issue #86 Part D: replies to the screen for setup operations.
TYPE_SETUP_LIST_RESULT = "setup.list.result"
TYPE_SETUP_LOAD_ACK = "setup.load.ack"
TYPE_SETUP_SPINNER_LIST_RESULT = "setup.spinner.list.result"
TYPE_SETUP_SPINNER_SET_ACK = "setup.spinner.set.ack"
TYPE_SETUP_EXPERIMENT_STORE_ACK = "setup.experiment.store.ack"
TYPE_SETUP_EXPERIMENT_RECORD_ACK = "setup.experiment.record.ack"
TYPE_SETUP_COMPARE_RESULT = "setup.compare.result"
TYPE_SETUP_SUGGEST_RESULT = "setup.suggest.result"
TYPE_SETUP_ADVICE_RESULT = "setup.advice.result"
TYPE_SETUP_DIFF_RESULT = "setup.diff.result"
TYPE_SETUP_CLOSED_LOOP_RESULT = "setup.closed_loop.result"
TYPE_SETUP_EXCHANGE_SEARCH_RESULT = "se.search.result"
TYPE_SETUP_EXCHANGE_DOWNLOAD_ACK = "se.download.ack"
# Issue #118: high-rate physical-peripheral frames. `telemetry_tick` is sent
# from the Lua loopback peer to physical clients; the sidecar can derive and
# route `haptic_event` frames to haptic-class clients.
TYPE_TELEMETRY_TICK = "telemetry_tick"
TYPE_HAPTIC_EVENT = "haptic_event"

KNOWN_HAPTIC_EVENTS: frozenset[str] = frozenset(
    {
        "pedal_rumble",
        "slip_buzz",
        "lateral_g",
        "wind",
        "gear_shift",
    }
)
KNOWN_HAPTIC_CHANNELS: frozenset[str] = frozenset(
    {
        "pedal",
        "pedal_left",
        "pedal_right",
        "seat_left",
        "seat_right",
        "fan",
        "shaker",
    }
)

# Capabilities advertised in `hello_ack` so clients can branch on optional
# server features without a v2 bump.
SERVER_CAPABILITIES: tuple[str, ...] = (
    TYPE_CONFIG_GET,
    TYPE_CONFIG_SET,
    TYPE_ACTION,
    TYPE_STATE_SUBSCRIBE,
    TYPE_SETUP_COMPARE,
    TYPE_SETUP_SUGGEST,
    TYPE_SETUP_ADVICE,
    TYPE_SETUP_DIFF,
    TYPE_SETUP_CLOSED_LOOP,
    TYPE_SETUP_EXCHANGE_SEARCH,
    TYPE_SETUP_EXCHANGE_DOWNLOAD,
    TYPE_SETUP_SPINNER_LIST,
    TYPE_SETUP_SPINNER_SET,
    TYPE_TELEMETRY_TICK,
    TYPE_HAPTIC_EVENT,
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
# is the producer; the sidecar fans out snapshots. This allow-list must be the
# single source of truth for EVERY topic the trainer publishes — fan-out itself
# is topic-agnostic (`_broadcast_external`), so an omission here doesn't drop
# frames, it only makes a real topic unsubscribable. `coaching.snapshot` and
# `setup.active` were produced (coaching_publisher.lua / ac_copilot_trainer.lua)
# but missing here, so a client could never legitimately subscribe to them — the
# "produced-but-unsubscribable" sibling of the #170 handshake bug. The
# `test_ws_topic_allowlist` drift-guard asserts every produced topic is listed.
#: Topic the sidecar publishes live coaching cues on (issue #341). Unlike the Lua-produced topics
#: above, `coaching.cue` is **sidecar-originated** (the `RealtimeObserver` advisory stream), so the
#: Lua `publishTopic` drift-guard does not cover it — it is listed here so a `voice`-class client
#: can legitimately subscribe.
TOPIC_COACHING_CUE = "coaching.cue"
# Topics the sidecar produces directly (no loopback Lua relay). Voice/offline clients may
# state.subscribe to these without a Lua peer connected.
SIDECAR_PRODUCED_TOPICS: frozenset[str] = frozenset({TOPIC_COACHING_CUE})
KNOWN_TOPICS: frozenset[str] = frozenset(
    {
        # Declared topics (EPIC #154 Part D wires producers for these).
        "connection",
        "session",
        "lap",
        "delta",
        "tire_temps",
        # Already-produced topics (made subscribable; were missing).
        "coaching.snapshot",
        "setup.active",
        # Sidecar-originated live coaching cues (issue #341).
        TOPIC_COACHING_CUE,
    }
)

# Header used on the WS upgrade for shared-secret auth.
AUTH_HEADER = "X-AC-Copilot-Token"
CLIENT_HEADER = "X-AC-Copilot-Client"


def topics_are_sidecar_only(topics: Any) -> bool:
    """True when every topic in ``topics`` is sidecar-produced (no Lua relay needed)."""
    if not isinstance(topics, list) or not topics:
        return False
    return all(isinstance(t, str) and t in SIDECAR_PRODUCED_TOPICS for t in topics)


def make_hello_ack(server_version: str = SERVER_VERSION) -> dict[str, Any]:
    return {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: TYPE_HELLO_ACK,
        "server_version": server_version,
        "capabilities": list(SERVER_CAPABILITIES),
    }


def make_telemetry_tick(payload: dict[str, Any], *, seq: int | None = None) -> dict[str, Any]:
    """Client->server high-rate telemetry frame (M0, #341).

    The producer side of the live coaching loop. ``_validate_telemetry_tick`` is the single source
    of truth for the payload contract: ``speed_kmh``, ``rpm``, ``throttle``, ``brake``, ``steer``,
    ``gear``, ``lat_g`` and ``long_g`` are all REQUIRED (a payload omitting any is rejected by
    :func:`validate_inbound` and dropped by the server); ``spline`` (0..1) and ``lap`` are OPTIONAL
    (``spline`` is what lets the observer locate corners). Built here so the offline replay source
    and any live shared-memory source emit a byte-identical, validator-accepted contract.
    """
    frame: dict[str, Any] = {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: TYPE_TELEMETRY_TICK,
        "payload": payload,
    }
    if seq is not None:
        frame["seq"] = seq
    return frame


def make_coaching_cue(payload: dict[str, Any], *, ts_sim: float | None = None) -> dict[str, Any]:
    """Build a ``coaching.cue`` topic frame for one live advisory (issue #341).

    Sidecar-originated ``state.snapshot`` envelope on the ``coaching.cue`` topic — the same
    ``{v, type:"state.snapshot", topic, payload}`` shape every topic uses, so a ``voice``-class
    client subscribes to it exactly like ``coaching.snapshot``. ``payload`` carries the advisory's
    machine-readable fields (kind/corner/urgency/message/spline/detail); the renderer (#340's
    resolver) turns it back into speech. ``ts_sim`` is forwarded when the source carried one.
    """
    frame: dict[str, Any] = {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: TYPE_STATE_SNAPSHOT,
        "topic": TOPIC_COACHING_CUE,
        "payload": payload,
        "source": "sidecar.observer",
    }
    if ts_sim is not None:
        frame["ts_sim"] = ts_sim
    return frame


def make_error(message: str, *, ref_type: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: TYPE_ERROR,
        "message": message,
    }
    if ref_type is not None:
        out["ref_type"] = ref_type
    return out


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(float(value))
    )


def _validate_number(
    payload: dict[str, Any],
    key: str,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> str | None:
    value = payload.get(key)
    if not _is_finite_number(value):
        return f"{key} requires a finite number"
    f_value = float(value)
    if min_value is not None and f_value < min_value:
        return f"{key} must be >= {min_value:g}"
    if max_value is not None and f_value > max_value:
        return f"{key} must be <= {max_value:g}"
    return None


def _validate_optional_number(
    payload: dict[str, Any],
    key: str,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> str | None:
    if key not in payload:
        return None
    return _validate_number(payload, key, min_value=min_value, max_value=max_value)


def _validate_optional_string(frame: dict[str, Any], key: str) -> str | None:
    if key in frame and not isinstance(frame.get(key), str):
        return f"{key} must be a string"
    return None


def _validate_optional_object(frame: dict[str, Any], key: str) -> str | None:
    if key in frame and not isinstance(frame.get(key), dict):
        return f"{key} requires an object"
    return None


def _validate_setup_snapshot(
    frame: dict[str, Any],
    key: str,
    *,
    required: bool,
) -> str | None:
    if key not in frame:
        return f"setup.diff requires object '{key}'" if required else None
    value = frame.get(key)
    if not isinstance(value, dict):
        return f"{key} requires an object"
    if len(value) > MAX_SETUP_SNAPSHOT_KEYS:
        return f"{key} must contain <= {MAX_SETUP_SNAPSHOT_KEYS} entries"
    try:
        payload_bytes = len(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError):
        return f"{key} must be JSON-serializable"
    if payload_bytes > MAX_SETUP_SNAPSHOT_BYTES:
        return f"{key} must be <= {MAX_SETUP_SNAPSHOT_BYTES} bytes"
    return None


def _validate_optional_int(
    frame: dict[str, Any],
    key: str,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> str | None:
    if key not in frame:
        return None
    value = frame.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{key} must be an integer"
    if min_value is not None and value < min_value:
        return f"{key} must be >= {min_value}"
    if max_value is not None and value > max_value:
        return f"{key} must be <= {max_value}"
    return None


def _validate_corner_number_map(payload: dict[str, Any], key: str) -> str | None:
    if key not in payload:
        return None
    value = payload[key]
    if not isinstance(value, dict):
        return f"{key} requires an object"
    if not value:
        return f"{key} requires at least one corner"
    known_corners = frozenset({"fl", "fr", "rl", "rr"})
    for corner in value:
        if corner not in known_corners:
            return f"{key}.{corner} is not a known corner"
        if not _is_finite_number(value[corner]):
            return f"{key}.{corner} requires a finite number"
    return None


def _validate_telemetry_tick(frame: dict[str, Any]) -> str | None:
    err = _validate_optional_number(frame, "ts_sim", min_value=0)
    if err is not None:
        return err
    seq = frame.get("seq")
    if seq is not None and (isinstance(seq, bool) or not isinstance(seq, int) or seq < 0):
        return "seq must be a non-negative integer"
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        return "telemetry_tick requires object 'payload'"
    required_ranges = {
        "speed_kmh": (0, None),
        "rpm": (0, None),
        "throttle": (0, 1),
        "brake": (0, 1),
        "steer": (-1, 1),
        "lat_g": (None, None),
        "long_g": (None, None),
    }
    for key, (min_value, max_value) in required_ranges.items():
        err = _validate_number(payload, key, min_value=min_value, max_value=max_value)
        if err is not None:
            return err
    gear = payload.get("gear")
    if isinstance(gear, bool) or not isinstance(gear, int | str):
        return "gear requires an integer or string"
    err = _validate_optional_number(payload, "lap_time_ms", min_value=0)
    if err is not None:
        return err
    err = _validate_optional_number(payload, "slip")
    if err is not None:
        return err
    # M0 (#341): the live RealtimeObserver needs `spline` (0..1) to locate corners + detect lap
    # wraps; the lap counter separates a real start/finish wrap from a pit/teleport. All optional +
    # back-compatible (producers may omit them); when present they must be sane (`spline` 0..1, lap
    # counters non-negative). Both snake_case and camelCase lap spellings are accepted (the Lua
    # producer emits `lap`). #357: consolidated from two duplicate blocks (merge debris).
    err = _validate_optional_number(payload, "spline", min_value=0, max_value=1)
    if err is not None:
        return err
    for lap_key in ("lap", "lap_count", "completed_laps", "lapCount", "completedLaps"):
        err = _validate_optional_number(payload, lap_key, min_value=0)
        if err is not None:
            return err
    for key in (
        "tyre_temps_c",
        "tyre_pressures_psi",
        "tyre_wear_pct",
        "brake_temps_c",
        "brake_wear_pct",
    ):
        err = _validate_corner_number_map(payload, key)
        if err is not None:
            return err
    optional_ranges = {
        "fuel_l": (0, None),
        "fuel_capacity_l": (0, None),
        "fuel_per_lap_l": (0, None),
        "target_laps_remaining": (0, None),
        "laps_to_finish": (0, None),
        "race_laps_remaining": (0, None),
        "race_laps": (0, None),
        "session_laps_total": (0, None),
        "track_grip_level": (0, None),
        "track_temp_c": (None, None),
        "ambient_temp_c": (None, None),
    }
    for key, (min_value, max_value) in optional_ranges.items():
        err = _validate_optional_number(payload, key, min_value=min_value, max_value=max_value)
        if err is not None:
            return err
    for key in ("weather_type", "tyre_compound"):
        if key in payload and not isinstance(payload[key], str):
            return f"{key} must be a string"
    for key in ("abs_active", "brake_lock", "wheel_lock"):
        if key in payload and not isinstance(payload[key], bool):
            return f"{key} must be a boolean"
    return None


def _validate_haptic_event(frame: dict[str, Any]) -> str | None:
    err = _validate_optional_number(frame, "ts_sim", min_value=0)
    if err is not None:
        return err
    event = frame.get("event")
    if not isinstance(event, str) or not event:
        return "haptic_event requires non-empty 'event'"
    if event not in KNOWN_HAPTIC_EVENTS:
        return f"unknown haptic event: {event!r}"
    channel = frame.get("channel")
    if not isinstance(channel, str) or not channel:
        return "haptic_event requires non-empty 'channel'"
    if channel not in KNOWN_HAPTIC_CHANNELS:
        return f"unknown haptic channel: {channel!r}"
    err = _validate_number(frame, "intensity", min_value=0, max_value=1)
    if err is not None:
        return err
    duration_ms = frame.get("duration_ms")
    if (
        isinstance(duration_ms, bool)
        or not isinstance(duration_ms, int)
        or duration_ms < 1
        or duration_ms > 1000
    ):
        return "duration_ms must be an integer between 1 and 1000"
    return None


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
        client_class = frame.get(CLIENT_CLASS_KEY)
        if client_class is not None:
            if not isinstance(client_class, str) or client_class not in KNOWN_CLIENT_CLASSES:
                return f"unknown client_class: {client_class!r}"
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
    if t == TYPE_SETUP_LIST:
        # No required fields — empty payload is valid (lists all setups for
        # the active car). The Lua handler reads ac.getCarID(0) directly.
        return None
    if t == TYPE_SETUP_LOAD:
        name = frame.get("name")
        path = frame.get("path")
        # Either a basename or an absolute path is required. The Lua side
        # prefers `path` when both are present so same-name setups in
        # different track folders disambiguate cleanly.
        name_ok = isinstance(name, str) and name != ""
        path_ok = isinstance(path, str) and path != ""
        if not (name_ok or path_ok):
            return "setup.load requires non-empty 'name' or 'path'"
        return None
    if t == TYPE_SETUP_SPINNER_LIST:
        path = frame.get("path")
        if path is not None and not isinstance(path, str):
            return "setup.spinner.list optional 'path' must be a string"
        return None
    if t == TYPE_SETUP_SPINNER_SET:
        section = frame.get("section")
        name = frame.get("name")
        section_ok = isinstance(section, str) and section != ""
        name_ok = isinstance(name, str) and name != ""
        if not (section_ok or name_ok):
            return "setup.spinner.set requires non-empty 'section' or 'name'"
        path = frame.get("path")
        if path is not None and not isinstance(path, str):
            return "setup.spinner.set optional 'path' must be a string"
        err = _validate_number(frame, "value")
        if err is not None:
            return err
        return None
    if t == TYPE_SETUP_EXPERIMENT_STORE:
        store_path = frame.get("store_path") or frame.get("path")
        if not isinstance(store_path, str) or not store_path:
            return "setup.experiment.store requires non-empty 'store_path'"
        return None
    if t == TYPE_SETUP_EXPERIMENT_RECORD:
        archive_path = frame.get("archive_path") or frame.get("path")
        if not isinstance(archive_path, str) or not archive_path:
            return "setup.experiment.record requires non-empty 'archive_path'"
        return None
    if t == TYPE_SETUP_COMPARE:
        baseline = frame.get("baseline_setup")
        candidate = frame.get("candidate_setup")
        if not isinstance(baseline, str) or not baseline:
            return "setup.compare requires non-empty 'baseline_setup'"
        if not isinstance(candidate, str) or not candidate:
            return "setup.compare requires non-empty 'candidate_setup'"
        return None
    if t == TYPE_SETUP_SUGGEST:
        for key in ("car_id", "track_id"):
            if key in frame and not isinstance(frame.get(key), str):
                return f"setup.suggest optional '{key}' must be a string"
        return None
    if t == TYPE_SETUP_ADVICE:
        complaint = frame.get("complaint")
        if not isinstance(complaint, str) or not complaint.strip():
            return "setup.advice requires non-empty 'complaint'"
        for key in ("car_id", "track_id"):
            err = _validate_optional_string(frame, key)
            if err is not None:
                return err
        return _validate_setup_snapshot(frame, "setup_snapshot", required=False)
    if t == TYPE_SETUP_DIFF:
        for key in ("baseline_snapshot", "candidate_snapshot"):
            err = _validate_setup_snapshot(frame, key, required=True)
            if err is not None:
                return err
        for key in ("car_id", "track_id"):
            err = _validate_optional_string(frame, key)
            if err is not None:
                return err
        return None
    if t == TYPE_SETUP_CLOSED_LOOP:
        param = frame.get("param")
        if not isinstance(param, str) or not param.strip():
            return "setup.closed_loop requires non-empty 'param'"
        for key in ("car_id", "track_id"):
            err = _validate_optional_string(frame, key)
            if err is not None:
                return err
        return None
    if t == TYPE_SETUP_EXCHANGE_SEARCH:
        for key in ("car_id", "track_id", "search", "order_by"):
            err = _validate_optional_string(frame, key)
            if err is not None:
                return err
        err = _validate_optional_int(frame, "limit", min_value=1, max_value=40)
        if err is not None:
            return err
        err = _validate_optional_int(frame, "offset", min_value=0)
        if err is not None:
            return err
        return None
    if t == TYPE_SETUP_EXCHANGE_DOWNLOAD:
        setup_id = frame.get("setup_id")
        setup_id_ok = not isinstance(setup_id, bool) and isinstance(setup_id, int) and setup_id > 0
        if not setup_id_ok:
            return "se.download requires positive integer 'setup_id'"
        car_id = frame.get("car_id")
        if not isinstance(car_id, str) or not car_id:
            return "se.download requires non-empty 'car_id'"
        for key in ("track_id", "name"):
            err = _validate_optional_string(frame, key)
            if err is not None:
                return err
        return None
    if t in (
        TYPE_SETUP_LIST_RESULT,
        TYPE_SETUP_LOAD_ACK,
        TYPE_SETUP_SPINNER_LIST_RESULT,
        TYPE_SETUP_SPINNER_SET_ACK,
    ):
        # Server-to-client replies forwarded from the Lua peer — accept silently.
        return None
    if t in (
        TYPE_SETUP_EXPERIMENT_STORE_ACK,
        TYPE_SETUP_EXPERIMENT_RECORD_ACK,
        TYPE_SETUP_COMPARE_RESULT,
        TYPE_SETUP_SUGGEST_RESULT,
        TYPE_SETUP_ADVICE_RESULT,
        TYPE_SETUP_DIFF_RESULT,
        TYPE_SETUP_CLOSED_LOOP_RESULT,
        TYPE_SETUP_EXCHANGE_SEARCH_RESULT,
        TYPE_SETUP_EXCHANGE_DOWNLOAD_ACK,
    ):
        return None
    if t == TYPE_TELEMETRY_TICK:
        return _validate_telemetry_tick(frame)
    if t == TYPE_HAPTIC_EVENT:
        return _validate_haptic_event(frame)
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
