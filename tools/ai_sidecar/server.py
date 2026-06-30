"""Async WebSocket server: versioned lap JSON from Lua + optional coaching replies (issue #45).

External clients (issue #81) speak the v1 ``{"v":1,"type":...}`` envelope and
are bridged through the same connection set: the Lua loopback client is the
source of truth for ``config.set`` / ``action`` / ``state.snapshot``; the
sidecar fans those messages between connected peers.

Run: python -m tools.ai_sidecar
Requires optional extra: pip install -e ".[coaching]"
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import ipaddress
import json
import logging
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

from tools.ai_sidecar import observability
from tools.ai_sidecar.coaching.llm_coach import debrief_feature_enabled
from tools.ai_sidecar.external_protocol import (
    AUTH_HEADER,
    CLIENT_CLASS_EXTERNAL,
    CLIENT_CLASS_KEY,
    CLIENT_CLASS_SCREEN,
    CLIENT_HEADER,
    ENVELOPE_KEY,
    ENVELOPE_VERSION,
    HAPTIC_CLIENT_CLASSES,
    PHYSICAL_CLIENT_CLASSES,
    TYPE_ACTION,
    TYPE_ACTION_ACK,
    TYPE_CONFIG_ACK,
    TYPE_CONFIG_GET,
    TYPE_CONFIG_SET,
    TYPE_CONFIG_VALUE,
    TYPE_ERROR,
    TYPE_HAPTIC_EVENT,
    TYPE_HELLO,
    TYPE_HELLO_ACK,
    TYPE_KEY,
    TYPE_SETUP_COMPARE,
    TYPE_SETUP_COMPARE_RESULT,
    TYPE_SETUP_EXCHANGE_DOWNLOAD,
    TYPE_SETUP_EXCHANGE_DOWNLOAD_ACK,
    TYPE_SETUP_EXCHANGE_SEARCH,
    TYPE_SETUP_EXCHANGE_SEARCH_RESULT,
    TYPE_SETUP_EXPERIMENT_RECORD,
    TYPE_SETUP_EXPERIMENT_RECORD_ACK,
    TYPE_SETUP_EXPERIMENT_STORE,
    TYPE_SETUP_EXPERIMENT_STORE_ACK,
    TYPE_SETUP_LIST,
    TYPE_SETUP_LIST_RESULT,
    TYPE_SETUP_LOAD,
    TYPE_SETUP_LOAD_ACK,
    TYPE_SETUP_SPINNER_LIST,
    TYPE_SETUP_SPINNER_LIST_RESULT,
    TYPE_SETUP_SPINNER_SET,
    TYPE_SETUP_SPINNER_SET_ACK,
    TYPE_SETUP_SUGGEST,
    TYPE_SETUP_SUGGEST_RESULT,
    TYPE_STATE_SNAPSHOT,
    TYPE_STATE_SUBSCRIBE,
    TYPE_STATE_UNSUBSCRIBE,
    TYPE_TELEMETRY_TICK,
    make_coaching_cue,
    make_error,
    make_hello_ack,
    topics_are_sidecar_only,
    validate_inbound,
)
from tools.ai_sidecar.protocol import (
    EVENT_ANALYSIS_ERROR,
    EVENT_COACHING_RESPONSE,
    EVENT_CORNER_QUERY,
    PROTOCOL_VERSION,
    build_brain_followup,
    build_ollama_followup,
    prepare_outbound_message,
)
from tools.ai_sidecar.realtime_observer import (
    RealtimeObserver,
)
from tools.ai_sidecar.se_proxy import (
    DEFAULT_SETUP_EXCHANGE_ENDPOINT,
    ENV_SETUP_EXCHANGE_ENDPOINT,
    ENV_USER_SETUPS_DIR,
    SetupExchangeClient,
    SetupExchangeError,
    download_and_install_setup,
    validate_user_setups_root,
)
from tools.ai_sidecar.session import LapComparisonState
from tools.ai_sidecar.setup_optimizer import (
    SetupExperimentError,
    compare_setups,
    is_supported_experiment_store_path,
    load_records,
    rebuild_experiments,
    record_lap_archive,
    suggest_next_setup,
)

logger = logging.getLogger(__name__)

# Strong refs so asyncio.Task objects are not GC'd mid-flight (Python docs).
_background_tasks: set[asyncio.Task[Any]] = set()
_OLLAMA_FOLLOWUP_CONCURRENCY = 4
# Best-effort cap: cancelling a task waiting in asyncio.to_thread can release this
# semaphore before the worker thread finishes (Python limitation).
_ollama_followup_sem: asyncio.Semaphore | None = None

# Connected external-protocol peers (any client that has spoken a `{v,type}`
# frame, including the Lua loopback client). Used for hub-style fan-out.
_external_peers: set[Any] = set()
_setup_experiment_store_path: Path | None = None
_setup_experiment_store_seeded = False
_setup_exchange_endpoint: str | None = None
_setup_exchange_user_setups_root: Path | None = None
_external_peer_classes: dict[Any, str] = {}
# M0 (#341): the live RealtimeObserver built from a FASTER reference lap. Set once at startup
# (--reference-archive / AC_COPILOT_REFERENCE_ARCHIVE); fed each telemetry_tick frame; emits
# advisories on the coaching.cue topic for the voice client. None = no live coaching this run.
_observer: RealtimeObserver | None = None
# The observer holds single-monotonic-stream state (last spline/lap, per-corner passes), so only ONE
# producer may feed it. The first telemetry producer claims the feed; a second concurrent loopback
# producer is still routed to peripherals but NOT into the observer (interleaving would corrupt wrap
# detection and silently mis-grade corners). Released when the owner disconnects.
_observer_feed_peer: Any = None
_observer_feed_warned = False

# Issue #341 — live voice wiring. Both are OPTIONAL and OFF by default: a sidecar with neither set
# behaves byte-identically to before. ``_observer`` turns the live ``telemetry_tick`` stream into
# per-corner advisories (published on ``coaching.cue``); ``_voice_coach`` (the #340 phrase-bank
# engine) speaks them in-process on the rig. The audio deps live only inside the voice package and
# are imported lazily when ``--voice-bank`` is supplied, so the sidecar core stays dep-free.
# (``_observer`` is declared once above with its RealtimeObserver type; not re-declared here.)
_voice_coach: Any | None = None
_voice_runtime_status: dict[str, object] = {
    "configured": False,
    "enabled": False,
    "state": "skipped",
    "disabled_reason": "",
}


@dataclass(frozen=True)
class VoiceRuntimeConfig:
    reference_path: str | None
    bank_dir: str | None
    tts_enabled: bool = False
    tts_rate: int | None = None
    tts_volume: float | None = None
    backend: str | None = None
    device: str | None = None
    host_api: str | None = None
    verbosity: str | None = None


def set_realtime_observer(observer: Any | None) -> None:
    """Install (or clear) the live ``RealtimeObserver`` fed by ``telemetry_tick`` (issue #341)."""
    global _observer
    _observer = observer


def set_voice_coach(coach: Any | None) -> None:
    """Install (or clear) the in-process voice coach that speaks advisories on the rig (#341)."""
    global _voice_coach
    _voice_coach = coach


def set_voice_runtime_status(**updates: object) -> None:
    """Record the voice runtime state reported by ``/health`` and the launcher."""
    _voice_runtime_status.clear()
    _voice_runtime_status.update(
        {
            "configured": False,
            "enabled": False,
            "state": "skipped",
            "disabled_reason": "",
        }
    )
    _voice_runtime_status.update(updates)


def voice_runtime_status() -> dict[str, object]:
    """Return a JSON-safe snapshot of the current voice runtime state."""
    return dict(_voice_runtime_status)


class _Pyttsx3VoiceCoach:
    """Small in-process pyttsx3 adapter for the M0 no-phrase-bank rig path."""

    def __init__(
        self,
        speaker: Callable[[str, str], None],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        from tools.ai_sidecar.voice.cue import CueArbiter

        self._speaker = speaker
        self._clock = clock
        self._arbiter = CueArbiter()

    def subscribe(self, advisory: Any) -> None:
        payload = _advisory_to_payload(advisory)
        if payload is None:
            return
        cue = self._arbiter.select([payload], self._clock())
        if cue is None:
            return
        logger.info("voice: pyttsx3 speaking %r", cue.text)
        self._speaker(cue.text, cue.register)


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("ignoring invalid %s=%r; expected integer", name, raw)
        return default
    return max(min_value, min(max_value, value))


def _env_float(name: str, default: float, *, min_value: float, max_value: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("ignoring invalid %s=%r; expected number", name, raw)
        return default
    return max(min_value, min(max_value, value))


TELEMETRY_TICK_MAX_HZ = 20.0
HAPTIC_EVENT_MAX_HZ = 25.0
LEGACY_SCREEN_CLIENT_PREFIXES = ("ac-copilot-screen",)

# Windows reports a port-in-use bind as WSAEADDRINUSE (10048), which is distinct from the POSIX
# errno.EADDRINUSE value; accept both so the clean-exit path fires on every platform.
_WSAEADDRINUSE = getattr(errno, "WSAEADDRINUSE", 10048)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
CLIENT_TO_SERVER_TYPES = frozenset(
    {
        TYPE_HELLO,
        TYPE_CONFIG_SET,
        TYPE_CONFIG_GET,
        TYPE_ACTION,
        TYPE_STATE_SUBSCRIBE,
        TYPE_STATE_UNSUBSCRIBE,
        # Issue #86 Part D: rig screen requests setup ops via these; relay to
        # the loopback Lua peer which actually scans the filesystem and calls
        # ac.loadSetup(). Without these in the allow-list, validate_inbound
        # rejects the frames with "unknown type" and the screen sits in
        # "Loading…" forever.
        TYPE_SETUP_LIST,
        TYPE_SETUP_LOAD,
        TYPE_SETUP_SPINNER_LIST,
        TYPE_SETUP_SPINNER_SET,
        TYPE_SETUP_EXPERIMENT_STORE,
        TYPE_SETUP_EXPERIMENT_RECORD,
        TYPE_SETUP_COMPARE,
        TYPE_SETUP_SUGGEST,
        TYPE_SETUP_EXCHANGE_SEARCH,
        TYPE_SETUP_EXCHANGE_DOWNLOAD,
    }
)
SERVER_TO_CLIENT_TYPES = frozenset(
    {
        TYPE_HELLO_ACK,
        TYPE_CONFIG_VALUE,
        TYPE_CONFIG_ACK,
        TYPE_ACTION_ACK,
        TYPE_STATE_SNAPSHOT,
        TYPE_ERROR,
        # Issue #118: emitted by the loopback Lua peer / sidecar toward
        # physical peripherals only, never echoed back to Lua.
        TYPE_TELEMETRY_TICK,
        TYPE_HAPTIC_EVENT,
        # Issue #86 Part D: replies the Lua peer sends back to the screen.
        TYPE_SETUP_LIST_RESULT,
        TYPE_SETUP_LOAD_ACK,
        TYPE_SETUP_SPINNER_LIST_RESULT,
        TYPE_SETUP_SPINNER_SET_ACK,
        TYPE_SETUP_EXPERIMENT_STORE_ACK,
        TYPE_SETUP_EXPERIMENT_RECORD_ACK,
        TYPE_SETUP_COMPARE_RESULT,
        TYPE_SETUP_SUGGEST_RESULT,
        TYPE_SETUP_EXCHANGE_SEARCH_RESULT,
        TYPE_SETUP_EXCHANGE_DOWNLOAD_ACK,
    }
)
SIDECAR_LOCAL_TYPES = frozenset(
    {
        TYPE_SETUP_EXPERIMENT_STORE,
        TYPE_SETUP_EXPERIMENT_RECORD,
        TYPE_SETUP_COMPARE,
        TYPE_SETUP_SUGGEST,
        TYPE_SETUP_EXCHANGE_SEARCH,
        TYPE_SETUP_EXCHANGE_DOWNLOAD,
    }
)


class _RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last_sent: dict[tuple[str, ...], float] = {}

    def reset(self) -> None:
        self._last_sent.clear()

    def allow(self, key: tuple[str, ...], max_hz: float) -> bool:
        now = self._clock()
        min_interval = 1.0 / max_hz
        last = self._last_sent.get(key)
        if last is not None and now - last < min_interval:
            return False
        self._last_sent[key] = now
        return True


_peripheral_rate_limiter = _RateLimiter()


def _reset_external_state() -> None:
    global _observer_feed_peer, _observer_feed_warned
    _external_peers.clear()
    _external_peer_classes.clear()
    _peripheral_rate_limiter.reset()
    # The single-producer observer feed is external-peer state: a full reset (server (re)start or
    # teardown) leaves no producer owning the feed, so the next telemetry producer can claim it.
    # Without this, a stale owner persists and the next producer is silently rejected by the guard
    # in _publish_coaching_cues — which also leaked across tests sharing this reset (#354).
    _observer_feed_peer = None
    _observer_feed_warned = False


def _get_ollama_followup_sem() -> asyncio.Semaphore:
    global _ollama_followup_sem
    if _ollama_followup_sem is None:
        _ollama_followup_sem = asyncio.Semaphore(_OLLAMA_FOLLOWUP_CONCURRENCY)
    return _ollama_followup_sem


def _run_compare_laps(last_path: str, ref_path: str) -> None:
    """CLI harness: two lap JSON files → improvement ranking on stdout (issue #49)."""
    try:
        last = json.loads(Path(last_path).read_text(encoding="utf-8"))
        ref = json.loads(Path(ref_path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SystemExit(f"compare-laps: file not found: {e.filename!r}") from e
    except PermissionError as e:
        raise SystemExit(f"compare-laps: cannot read file: {e}") from e
    except json.JSONDecodeError as e:
        raise SystemExit(f"compare-laps: invalid JSON ({e.msg} at char {e.pos})") from e
    from tools.ai_sidecar.features import extract_corner_table
    from tools.ai_sidecar.improvement_ranking import rank_corner_improvements

    ranked = rank_corner_improvements(
        extract_corner_table(last),
        extract_corner_table(ref),
    )
    print(json.dumps(ranked, indent=2))


def _run_setup_record_lap(lap_path: str, store_path: str | None) -> None:
    """CLI harness: one lap archive JSON → upsert one setup experiment row."""
    try:
        out = record_lap_archive(lap_path, store_path=store_path)
    except SetupExperimentError as e:
        raise SystemExit(f"setup-record-lap: {e}") from e
    print(json.dumps(out, indent=2, sort_keys=True))


def _run_setup_rebuild(lap_dir: str, store_path: str | None) -> None:
    """CLI harness: rebuild the setup experiment table from lap archive files."""
    out = rebuild_experiments(lap_dir, store_path=store_path)
    print(json.dumps(out, indent=2, sort_keys=True))


def _run_setup_compare(store_path: str, baseline: str, candidate: str) -> None:
    out = compare_setups(
        load_records(store_path),
        baseline_setup=baseline,
        candidate_setup=candidate,
    )
    print(json.dumps(out, indent=2, sort_keys=True))


def _run_setup_suggest(store_path: str, car_id: str | None, track_id: str | None) -> None:
    out = suggest_next_setup(load_records(store_path), car_id=car_id, track_id=track_id)
    print(json.dumps(out, indent=2, sort_keys=True))


def _setup_store_record_count(store_path: str | Path) -> int:
    return len(load_records(store_path))


def _record_lap_archive_safe(archive_path: str) -> dict[str, Any]:
    return record_lap_archive(archive_path, require_safe_path=True)


def _compare_setup_store(
    store_path: str | Path,
    *,
    baseline_setup: str,
    candidate_setup: str,
) -> dict[str, Any]:
    return compare_setups(
        load_records(store_path),
        baseline_setup=baseline_setup,
        candidate_setup=candidate_setup,
    )


def _suggest_setup_store(
    store_path: str | Path,
    *,
    car_id: str | None,
    track_id: str | None,
) -> dict[str, Any]:
    return suggest_next_setup(load_records(store_path), car_id=car_id, track_id=track_id)


def _user_setups_root_from_config(path: str | None) -> Path | None:
    if not path:
        return None
    try:
        return validate_user_setups_root(path)
    except SetupExchangeError as exc:
        logger.warning("Ignoring invalid user setups root %r: %s", path, exc)
        return None


def _peer_host(connection: Any) -> str | None:
    peer = getattr(connection, "remote_address", None)
    if isinstance(peer, tuple) and peer:
        return str(peer[0])
    if isinstance(peer, str):
        return peer
    return None


def _is_loopback_peer(connection: Any) -> bool:
    host = _peer_host(connection)
    if host is None:
        return False
    return _is_loopback(host)


async def _send_ollama_followup(
    websocket: Any,
    inbound: dict[str, Any],
    improvement_ranking: list[dict[str, Any]],
) -> None:
    """Call Ollama in a background task and send a follow-up coaching_response.

    Runs AFTER the immediate rules-based response has been sent. Uses
    asyncio.to_thread because the llm_coach helpers are sync. Silently
    discards on any error (the socket may have closed in the meantime).
    """
    try:
        async with _get_ollama_followup_sem():
            followup = await asyncio.to_thread(
                build_ollama_followup,
                inbound,
                improvement_ranking,
            )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.info("ollama followup raised: %s", e)
        observability.METRICS.record_ollama_followup_error()
        return
    if followup is None:
        observability.METRICS.record_ollama_followup_error()
        return
    await _safe_send(websocket, followup)


async def _send_brain_followup(websocket: Any, inbound: dict[str, Any]) -> None:
    """Run the setup-vs-technique attribution brain in a background task and send a follow-up.

    Mirrors :func:`_send_ollama_followup`: runs AFTER the immediate rules ack, off the message loop
    (the brain does disk I/O to load the lap archive + pure-Python analysis). Silently discards on
    any error or when no usable trace is available.
    """
    try:
        followup = await asyncio.to_thread(build_brain_followup, inbound)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.info("brain followup raised: %s", e)
        return
    if followup is None:
        return
    await _safe_send(websocket, followup)


async def _safe_send(websocket: Any, payload: dict[str, Any]) -> None:
    try:
        await websocket.send(json.dumps(payload, separators=(",", ":")))
    except Exception:
        logger.exception("websocket send failed")


def make_token_check(token: str | None):
    """Build a websockets ``process_request`` callback for the optional token gate.

    Returns ``None`` when no token is configured (default loopback deployment).
    Otherwise returns a callable that closes the upgrade with HTTP 401 if the
    ``X-AC-Copilot-Token`` header is missing or wrong.
    """
    if not token:
        return None

    def _check(connection: Any, request: Any) -> Any:
        supplied = request.headers.get(AUTH_HEADER)
        client_id = request.headers.get(CLIENT_HEADER) or "<unknown>"
        if _is_loopback_peer(connection):
            logger.info(
                "ws upgrade accepted loopback client=%s peer=%s token=%s",
                client_id,
                getattr(connection, "remote_address", None),
                "set" if supplied else "unset",
            )
            return None
        if supplied is None or not secrets.compare_digest(supplied, token):
            logger.warning(
                "ws upgrade rejected client=%s reason=bad-token peer=%s",
                client_id,
                getattr(connection, "remote_address", None),
            )
            if hasattr(connection, "respond"):
                return connection.respond(
                    HTTPStatus.UNAUTHORIZED,
                    "missing or invalid X-AC-Copilot-Token\n",
                )
            return (
                401,
                [("Content-Type", "text/plain; charset=utf-8")],
                b"missing or invalid X-AC-Copilot-Token\n",
            )
        logger.info(
            "ws upgrade accepted client=%s peer=%s",
            client_id,
            getattr(connection, "remote_address", None),
        )
        return None

    return _check


def _http_response(connection: Any, status: HTTPStatus, body: str, content_type: str) -> Any:
    """Build a plain HTTP response on the WS connection with a SINGLE, correct
    Content-Type.

    ``connection.respond(status, text)`` hardcodes ``Content-Type: text/plain;
    charset=utf-8`` and ``Headers.__setitem__`` APPENDS rather than replaces
    (websockets 16.0, verified), so a naive ``resp.headers["Content-Type"] = …``
    yields TWO Content-Type headers and a strict Prometheus scraper / JSON client
    mis-parses the body. Delete the default header first, then set ours.
    """
    response = connection.respond(status, body)
    try:
        del response.headers["Content-Type"]
    except KeyError:  # pragma: no cover - defensive across websockets versions
        pass
    response.headers["Content-Type"] = content_type
    return response


def make_process_request(token: str | None):
    """Build the websockets ``process_request`` hook.

    Serves ``GET /health`` and ``GET /metrics`` as plain HTTP on the SAME port as
    the WebSocket (short-circuiting the upgrade so they never enter ``_handler``),
    then falls through to the optional token gate (``make_token_check``) for a real
    WS upgrade. Installed UNCONDITIONALLY so the endpoints work even in the default
    no-token loopback deployment. Read-only ``/health`` and ``/metrics`` carry no
    secrets and are intentionally not token-gated; the WS upgrade keeps the gate.
    """
    token_check = make_token_check(token)

    def _process_request(connection: Any, request: Any) -> Any:
        path = (getattr(request, "path", "") or "").split("?", 1)[0]
        if path in ("/health", "/healthz"):
            connected_peers, screen_peers = _peer_counts()
            return _http_response(
                connection,
                HTTPStatus.OK,
                observability.build_health_json(
                    connected_peers,
                    screen_peers=screen_peers,
                    voice=voice_runtime_status(),
                ),
                observability.HEALTH_CONTENT_TYPE,
            )
        if path == "/metrics":
            connected_peers, screen_peers = _peer_counts()
            return _http_response(
                connection,
                HTTPStatus.OK,
                observability.build_metrics_text(connected_peers, screen_peers=screen_peers),
                observability.PROM_CONTENT_TYPE,
            )
        # A rig-screen sighting rides on the WS upgrade (the client header is on
        # the upgrade request), then the token gate applies if one is configured.
        if request.headers.get(CLIENT_HEADER):
            observability.METRICS.note_screen_seen()
        if token_check is not None:
            return token_check(connection, request)
        return None

    return _process_request


async def _broadcast_external(frame: dict[str, Any], *, exclude: Any) -> None:
    """Forward a ``{v,type}`` frame to every external peer except ``exclude``."""
    targets = [p for p in _external_peers if p is not exclude]
    await _broadcast_targets(frame, targets=targets)


def _release_observer_feed(websocket: Any) -> None:
    """Release the observer feed + reset stream state when the owning producer disconnects.

    Lets the next producer claim the feed and start from a clean per-corner/wrap state (the observer
    assumes one monotonic stream). No-op for any peer that did not own the feed.
    """
    global _observer_feed_peer, _observer_feed_warned
    if websocket is _observer_feed_peer:
        _observer_feed_peer = None
        _observer_feed_warned = False
        if _observer is not None:
            _observer.reset()


async def _broadcast_targets(frame: dict[str, Any], *, targets: list[Any]) -> None:
    """Forward a v1 frame to an explicit peer list."""
    if not targets:
        return
    payload = json.dumps(frame, separators=(",", ":"))
    results = await asyncio.gather(*[_safe_send_raw(p, payload) for p in targets])
    for p, err in zip(targets, results, strict=True):
        if err is not None:
            logger.info(
                "broadcast send failed peer=%s err=%s", getattr(p, "remote_address", None), err
            )
            _external_peers.discard(p)
            _external_peer_classes.pop(p, None)


def _has_loopback_target(*, exclude: Any) -> bool:
    for peer in _external_peers:
        if peer is exclude:
            continue
        if _is_loopback_peer(peer):
            return True
    return False


def _peer_class(peer: Any) -> str:
    return _external_peer_classes.get(peer, CLIENT_CLASS_EXTERNAL)


def _peer_counts() -> tuple[int, int]:
    screen_peers = sum(1 for peer in _external_peers if _peer_class(peer) == CLIENT_CLASS_SCREEN)
    return len(_external_peers), screen_peers


def _client_class_from_hello(data: dict[str, Any]) -> str:
    client_class = data.get(CLIENT_CLASS_KEY)
    if isinstance(client_class, str):
        return client_class
    client = data.get("client")
    if isinstance(client, str) and client.startswith(LEGACY_SCREEN_CLIENT_PREFIXES):
        return CLIENT_CLASS_SCREEN
    return CLIENT_CLASS_EXTERNAL


def _targets_for_classes(*, exclude: Any, classes: frozenset[str]) -> list[Any]:
    return [
        peer for peer in _external_peers if peer is not exclude and _peer_class(peer) in classes
    ]


def _clamp_01(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return max(0.0, min(1.0, float(value)))


def _build_haptic_events_from_telemetry(frame: dict[str, Any]) -> list[dict[str, Any]]:
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        return []

    events: list[dict[str, Any]] = []
    ts_sim = frame.get("ts_sim")
    if payload.get("abs_active") or payload.get("brake_lock") or payload.get("wheel_lock"):
        event: dict[str, Any] = {
            "v": 1,
            "type": TYPE_HAPTIC_EVENT,
            "event": "pedal_rumble",
            "channel": "pedal",
            "intensity": max(0.2, _clamp_01(payload.get("brake"))),
            "duration_ms": 80,
            "source": "sidecar.telemetry_tick",
        }
        if ts_sim is not None:
            event["ts_sim"] = ts_sim
        events.append(event)

    slip = payload.get("slip")
    if not isinstance(slip, bool) and isinstance(slip, int | float) and abs(float(slip)) >= 0.2:
        event = {
            "v": 1,
            "type": TYPE_HAPTIC_EVENT,
            "event": "slip_buzz",
            "channel": "pedal",
            "intensity": _clamp_01(abs(float(slip))),
            "duration_ms": 60,
            "source": "sidecar.telemetry_tick",
        }
        if ts_sim is not None:
            event["ts_sim"] = ts_sim
        events.append(event)
    return events


def _advisory_to_payload(advisory: Any) -> dict[str, Any] | None:
    """Flatten a ``RealtimeObserver`` Advisory into the ``coaching.cue`` wire payload (issue #341).

    ``corner`` is kept 0-based (as the observer emits it) so a consumer can reconstruct the Advisory
    faithfully; the human-facing 1-based turn number already lives in ``message`` ("...T4...").

    Returns ``None`` when required fields are missing so consumers never see null
    ``kind``/``urgency``.
    """
    kind = getattr(advisory, "kind", None)
    urgency = getattr(advisory, "urgency", None)
    if not isinstance(kind, str) or not kind or not isinstance(urgency, str) or not urgency:
        logger.warning("voice: dropping advisory with missing kind/urgency: %r", advisory)
        return None
    return {
        "kind": kind,
        "corner": getattr(advisory, "corner", None),
        "urgency": urgency,
        # issue #368: the tone tier + severity travel on the cue so a WS voice client renders the
        # same intensity the in-process coach speaks (additive — older consumers ignore them).
        "register": getattr(advisory, "register", "calm"),
        "intensity": getattr(advisory, "intensity", 0.0),
        "message": getattr(advisory, "message", ""),
        "spline": getattr(advisory, "spline", None),
        "detail": getattr(advisory, "detail", {}),
    }


async def _publish_coaching_cues(frame: dict[str, Any], *, exclude: Any) -> None:
    """Feed one live ``telemetry_tick`` frame to the observer; speak + fan-out its advisories
    (#341).

    No-op unless a ``RealtimeObserver`` is installed (the default). Each advisory is both (a) fed to
    the in-process voice coach so it speaks on the rig, and (b) published as a ``coaching.cue``
    topic
    frame so any ``voice``-class WS client can consume it. The observer/coach never raise into the
    live loop — a fault here must not stall telemetry or haptics.

    Single-producer guarded: only the peer that first fed the observer (``exclude`` is the producer
    websocket) may continue to; a second concurrent producer is ignored here.
    """
    global _observer_feed_peer, _observer_feed_warned
    observer = _observer
    if observer is None:
        return
    if not _peripheral_rate_limiter.allow((TYPE_TELEMETRY_TICK, "observer"), TELEMETRY_TICK_MAX_HZ):
        return
    if _observer_feed_peer is None:
        _observer_feed_peer = exclude
        _observer_feed_warned = False
    elif exclude is not _observer_feed_peer:
        if not _observer_feed_warned:
            logger.warning(
                "ignoring observer feed from a second telemetry producer peer=%s; the live "
                "observer is single-stream and already owned by another producer",
                getattr(exclude, "remote_address", None),
            )
            _observer_feed_warned = True
        return
    try:
        advisories = observer.observe(frame)
    except Exception:
        logger.exception("realtime observer failed on telemetry_tick")
        return
    if not advisories:
        return
    ts_sim = frame.get("ts_sim")
    coach = _voice_coach
    for advisory in advisories:
        if coach is not None:
            try:
                coach.subscribe(advisory)
            except Exception:
                logger.exception("voice coach subscribe failed for advisory")
        try:
            cue_payload = _advisory_to_payload(advisory)
            if cue_payload is None:
                continue
            cue = make_coaching_cue(cue_payload, ts_sim=ts_sim)
            cue_task = asyncio.create_task(_broadcast_external(cue, exclude=exclude))
            _background_tasks.add(cue_task)
            cue_task.add_done_callback(_background_tasks.discard)
        except Exception:
            logger.exception("voice: failed to publish coaching cue for advisory")


async def _route_peripheral_frame(
    frame: dict[str, Any],
    *,
    exclude: Any,
    classes: frozenset[str],
    rate_key: tuple[str, ...],
    max_hz: float,
) -> None:
    targets = _targets_for_classes(exclude=exclude, classes=classes)
    if not targets:
        logger.debug("no peripheral targets for type=%s classes=%s", frame.get(TYPE_KEY), classes)
        return
    if not _peripheral_rate_limiter.allow(rate_key, max_hz):
        logger.debug("peripheral frame rate-limited type=%s key=%s", frame.get(TYPE_KEY), rate_key)
        return
    await _broadcast_targets(frame, targets=targets)


async def _safe_send_raw(websocket: Any, payload: str) -> Exception | None:
    try:
        await websocket.send(payload)
    except Exception as e:
        logger.exception("broadcast websocket send failed")
        return e
    return None


async def _handle_setup_experiment_frame(websocket: Any, data: dict[str, Any]) -> None:
    """Handle setup optimizer frames in the sidecar itself.

    The Lua app sends ``setup.experiment.store`` after the v1 handshake and
    ``setup.experiment.record`` after writing a lap archive. External clients
    can then ask the same sidecar for ``setup.compare`` or ``setup.suggest``
    without inventing another daemon. Arbitrary file reads stay loopback-only:
    only the Lua peer may provide filesystem paths.
    """
    global _setup_experiment_store_path, _setup_experiment_store_seeded

    t = data.get(TYPE_KEY)
    if t == TYPE_SETUP_EXPERIMENT_STORE:
        if not _is_loopback_peer(websocket):
            await _safe_send(
                websocket,
                {
                    ENVELOPE_KEY: ENVELOPE_VERSION,
                    TYPE_KEY: TYPE_SETUP_EXPERIMENT_STORE_ACK,
                    "ok": False,
                    "error": "setup experiment store registration is loopback-only",
                },
            )
            return
        store_path_text = str(data.get("store_path") or data.get("path") or "")
        if not is_supported_experiment_store_path(store_path_text):
            await _safe_send(
                websocket,
                {
                    ENVELOPE_KEY: ENVELOPE_VERSION,
                    TYPE_KEY: TYPE_SETUP_EXPERIMENT_STORE_ACK,
                    "ok": False,
                    "store_path": store_path_text,
                    "error": (
                        "store_path must point to journal/setup_experiments/experiments.jsonl"
                    ),
                },
            )
            return
        candidate_store_path = Path(store_path_text)
        active_store_path = (
            _setup_experiment_store_path
            if _setup_experiment_store_seeded and _setup_experiment_store_path is not None
            else candidate_store_path
        )
        try:
            records_count = await asyncio.to_thread(
                _setup_store_record_count,
                active_store_path,
            )
        except Exception as e:
            logger.info("setup store registration failed store=%s err=%s", active_store_path, e)
            await _safe_send(
                websocket,
                {
                    ENVELOPE_KEY: ENVELOPE_VERSION,
                    TYPE_KEY: TYPE_SETUP_EXPERIMENT_STORE_ACK,
                    "ok": False,
                    "store_path": str(active_store_path),
                    "error": str(e),
                },
            )
            return
        if not _setup_experiment_store_seeded:
            _setup_experiment_store_path = candidate_store_path
        await _safe_send(
            websocket,
            {
                ENVELOPE_KEY: ENVELOPE_VERSION,
                TYPE_KEY: TYPE_SETUP_EXPERIMENT_STORE_ACK,
                "ok": True,
                "store_path": str(_setup_experiment_store_path),
                "requested_store_path": str(candidate_store_path),
                "seeded": _setup_experiment_store_seeded,
                "records": records_count,
            },
        )
        return

    if t == TYPE_SETUP_EXPERIMENT_RECORD:
        if not _is_loopback_peer(websocket):
            await _safe_send(
                websocket,
                {
                    ENVELOPE_KEY: ENVELOPE_VERSION,
                    TYPE_KEY: TYPE_SETUP_EXPERIMENT_RECORD_ACK,
                    "ok": False,
                    "error": "setup experiment recording is loopback-only",
                },
            )
            return
        archive_path = str(data.get("archive_path") or data.get("path") or "")
        try:
            out = await asyncio.to_thread(_record_lap_archive_safe, archive_path)
        except Exception as e:
            logger.info("setup experiment record failed archive=%s err=%s", archive_path, e)
            await _safe_send(
                websocket,
                {
                    ENVELOPE_KEY: ENVELOPE_VERSION,
                    TYPE_KEY: TYPE_SETUP_EXPERIMENT_RECORD_ACK,
                    "ok": False,
                    "archive_path": archive_path,
                    "error": str(e),
                },
            )
            return
        if not _setup_experiment_store_seeded:
            _setup_experiment_store_path = Path(out["store_path"])
        await _safe_send(
            websocket,
            {
                ENVELOPE_KEY: ENVELOPE_VERSION,
                TYPE_KEY: TYPE_SETUP_EXPERIMENT_RECORD_ACK,
                "active_store_path": str(_setup_experiment_store_path)
                if _setup_experiment_store_path is not None
                else None,
                **out,
            },
        )
        return

    store_path = _setup_experiment_store_path
    if store_path is None:
        await _safe_send(
            websocket,
            {
                ENVELOPE_KEY: ENVELOPE_VERSION,
                TYPE_KEY: (
                    TYPE_SETUP_COMPARE_RESULT
                    if t == TYPE_SETUP_COMPARE
                    else TYPE_SETUP_SUGGEST_RESULT
                ),
                "ok": False,
                "error": "no setup experiment store is loaded yet",
            },
        )
        return

    if t == TYPE_SETUP_COMPARE:
        try:
            out = await asyncio.to_thread(
                _compare_setup_store,
                store_path,
                baseline_setup=str(data.get("baseline_setup") or ""),
                candidate_setup=str(data.get("candidate_setup") or ""),
            )
        except Exception as e:
            logger.info("setup compare failed store=%s err=%s", store_path, e)
            out = {"ok": False, "error": str(e)}
        await _safe_send(
            websocket,
            {
                ENVELOPE_KEY: ENVELOPE_VERSION,
                TYPE_KEY: TYPE_SETUP_COMPARE_RESULT,
                "store_path": str(store_path),
                **out,
            },
        )
        return

    if t == TYPE_SETUP_SUGGEST:
        try:
            out = await asyncio.to_thread(
                _suggest_setup_store,
                store_path,
                car_id=data.get("car_id"),
                track_id=data.get("track_id"),
            )
        except Exception as e:
            logger.info("setup suggest failed store=%s err=%s", store_path, e)
            out = {"ok": False, "error": str(e)}
        await _safe_send(
            websocket,
            {
                ENVELOPE_KEY: ENVELOPE_VERSION,
                TYPE_KEY: TYPE_SETUP_SUGGEST_RESULT,
                "store_path": str(store_path),
                **out,
            },
        )
        return


async def _handle_setup_exchange_frame(websocket: Any, data: dict[str, Any]) -> None:
    """Handle Setup Exchange search/download frames in the sidecar (#363)."""

    t = data.get(TYPE_KEY)
    endpoint = _setup_exchange_endpoint or os.environ.get(ENV_SETUP_EXCHANGE_ENDPOINT)
    try:
        client = SetupExchangeClient(endpoint or DEFAULT_SETUP_EXCHANGE_ENDPOINT)
    except SetupExchangeError as e:
        await _safe_send(
            websocket,
            {
                ENVELOPE_KEY: ENVELOPE_VERSION,
                TYPE_KEY: (
                    TYPE_SETUP_EXCHANGE_SEARCH_RESULT
                    if t == TYPE_SETUP_EXCHANGE_SEARCH
                    else TYPE_SETUP_EXCHANGE_DOWNLOAD_ACK
                ),
                "ok": False,
                "error": str(e),
            },
        )
        return
    if t == TYPE_SETUP_EXCHANGE_SEARCH:
        try:
            out = await asyncio.to_thread(
                client.search,
                car_id=data.get("car_id") or None,
                track_id=data.get("track_id") or None,
                search=data.get("search") or None,
                order_by=data.get("order_by") or None,
                offset=data.get("offset"),
                limit=data.get("limit"),
            )
        except SetupExchangeError as e:
            logger.info("setup exchange search failed err=%s", e)
            out = {"ok": False, "error": str(e)}
        await _safe_send(
            websocket,
            {
                ENVELOPE_KEY: ENVELOPE_VERSION,
                TYPE_KEY: TYPE_SETUP_EXCHANGE_SEARCH_RESULT,
                **out,
            },
        )
        return

    if t == TYPE_SETUP_EXCHANGE_DOWNLOAD:
        setup_id = int(data["setup_id"])
        car_id = str(data["car_id"])
        track_id = data.get("track_id") or None
        name = data.get("name") or None
        try:
            out = await asyncio.to_thread(
                download_and_install_setup,
                client=client,
                user_setups_root=_setup_exchange_user_setups_root,
                setup_id=setup_id,
                car_id=car_id,
                track_id=track_id if isinstance(track_id, str) else None,
                name=name if isinstance(name, str) else None,
            )
        except SetupExchangeError as e:
            logger.info("setup exchange download failed setup_id=%s err=%s", setup_id, e)
            out = {
                "ok": False,
                "setup_id": setup_id,
                "car_id": car_id,
                "track_id": track_id,
                "error": str(e),
            }
        except OSError as e:
            logger.info("setup exchange install failed setup_id=%s err=%s", setup_id, e)
            out = {
                "ok": False,
                "setup_id": setup_id,
                "car_id": car_id,
                "track_id": track_id,
                "error": f"failed to install setup: {e}",
            }
        await _safe_send(
            websocket,
            {
                ENVELOPE_KEY: ENVELOPE_VERSION,
                TYPE_KEY: TYPE_SETUP_EXCHANGE_DOWNLOAD_ACK,
                **out,
            },
        )
        return


async def _handle_external_frame(websocket: Any, data: dict[str, Any]) -> None:
    """Process one ``{v,type}`` frame: validate, ack, fan-out as needed."""
    peer = getattr(websocket, "remote_address", None)
    t_in = data.get(TYPE_KEY, "?")
    err = validate_inbound(data)
    if err is not None:
        logger.warning("external frame rejected peer=%s type=%s reason=%s", peer, t_in, err)
        await _safe_send(websocket, make_error(err, ref_type=data.get(TYPE_KEY)))
        return
    t = data[TYPE_KEY]
    if t == TYPE_HELLO:
        # Track this peer for fan-out and acknowledge directly.
        _external_peers.add(websocket)
        client_class = _client_class_from_hello(data)
        _external_peer_classes[websocket] = client_class
        logger.info(
            "external hello accepted peer=%s client=%s class=%s peers=%d",
            peer,
            data.get("client", "?"),
            client_class,
            len(_external_peers),
        )
        await _safe_send(websocket, make_hello_ack())
        return
    if websocket not in _external_peers:
        await _safe_send(
            websocket,
            make_error("peer must send hello before other frame types", ref_type=t),
        )
        return
    if t in (TYPE_SETUP_EXCHANGE_SEARCH, TYPE_SETUP_EXCHANGE_DOWNLOAD):
        await _handle_setup_exchange_frame(websocket, data)
        return
    if t in SIDECAR_LOCAL_TYPES:
        await _handle_setup_experiment_frame(websocket, data)
        return
    if t in SERVER_TO_CLIENT_TYPES and not _is_loopback_peer(websocket):
        await _safe_send(
            websocket,
            make_error(
                f"{t} is server-originated and accepted only from loopback peers",
                ref_type=t,
            ),
        )
        return
    if t not in CLIENT_TO_SERVER_TYPES and t not in SERVER_TO_CLIENT_TYPES:
        await _safe_send(websocket, make_error(f"unsupported type: {t!r}", ref_type=t))
        return
    if t == TYPE_TELEMETRY_TICK:
        await _route_peripheral_frame(
            data,
            exclude=websocket,
            classes=PHYSICAL_CLIENT_CLASSES,
            rate_key=(TYPE_TELEMETRY_TICK,),
            max_hz=TELEMETRY_TICK_MAX_HZ,
        )
        for event in _build_haptic_events_from_telemetry(data):
            event_err = validate_inbound(event)
            if event_err is not None:
                logger.warning("generated haptic_event invalid: %s", event_err)
                continue
            await _route_peripheral_frame(
                event,
                exclude=websocket,
                classes=HAPTIC_CLIENT_CLASSES,
                rate_key=(TYPE_HAPTIC_EVENT, event["event"], event["channel"]),
                max_hz=HAPTIC_EVENT_MAX_HZ,
            )
        # Issue #341: turn the same live frame into spoken coaching cues (no-op unless wired).
        await _publish_coaching_cues(data, exclude=websocket)
        return
    if t == TYPE_HAPTIC_EVENT:
        await _route_peripheral_frame(
            data,
            exclude=websocket,
            classes=HAPTIC_CLIENT_CLASSES,
            rate_key=(TYPE_HAPTIC_EVENT, str(data.get("event")), str(data.get("channel"))),
            max_hz=HAPTIC_EVENT_MAX_HZ,
        )
        return
    if t in (TYPE_STATE_SUBSCRIBE, TYPE_STATE_UNSUBSCRIBE) and topics_are_sidecar_only(
        data.get("topics")
    ):
        logger.info(
            "sidecar-produced %s accepted without loopback peer=%s topics=%s",
            t,
            peer,
            data.get("topics"),
        )
        return
    if (
        t in CLIENT_TO_SERVER_TYPES
        and t != TYPE_HELLO
        and not _has_loopback_target(exclude=websocket)
    ):
        await _safe_send(websocket, make_error("no loopback Lua peer connected", ref_type=t))
        return
    # All other request/response types are forwarded to every other peer.
    # The Lua client receives `config.set` / `action` / `state.subscribe` and
    # responds with `config.value` / `config.ack` / `action.ack` /
    # `state.snapshot`, which are also forwarded back through this same path.
    topic = data.get("topic")
    logger.info(
        "relay peer=%s type=%s%s peers=%d",
        peer,
        t,
        f" topic={topic}" if topic else "",
        len(_external_peers),
    )
    await _broadcast_external(data, exclude=websocket)


async def _handler(websocket: Any, reply_coaching: bool) -> None:
    peer = getattr(websocket, "remote_address", None)
    logger.info(
        "sidecar client connected protocol=%s peer=%s",
        PROTOCOL_VERSION,
        peer,
    )
    lap_state = LapComparisonState()
    prepare_lock = asyncio.Lock()
    pending_followups: set[asyncio.Task[Any]] = set()
    pending_corner_task: asyncio.Task[Any] | None = None
    # Monotonic id so a slow to_thread from a superseded corner_query does not
    # send corner_advice after a newer query has already been issued (Codex).
    corner_job_gen: list[int] = [0]

    def _followup_done(t: asyncio.Task[Any]) -> None:
        _background_tasks.discard(t)
        pending_followups.discard(t)

    try:
        async for message in websocket:
            if not isinstance(message, str):
                logger.warning("non-text frame ignored type=%s", type(message).__name__)
                continue
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning("invalid json (first 200 chars): %s", message[:200])
                if websocket in _external_peers:
                    await _safe_send(websocket, make_error("invalid json"))
                else:
                    await _safe_send(
                        websocket,
                        {
                            "protocol": PROTOCOL_VERSION,
                            "event": EVENT_ANALYSIS_ERROR,
                            "message": "invalid json",
                        },
                    )
                continue
            if not isinstance(data, dict):
                logger.warning("json root must be object, got %s", type(data).__name__)
                if websocket in _external_peers:
                    await _safe_send(websocket, make_error("root must be a JSON object"))
                else:
                    await _safe_send(
                        websocket,
                        {
                            "protocol": PROTOCOL_VERSION,
                            "event": EVENT_ANALYSIS_ERROR,
                            "message": "root must be a JSON object",
                        },
                    )
                continue

            # Route any envelope-like payload through external validation so
            # malformed `{v,type}` frames get explicit protocol errors.
            if ENVELOPE_KEY in data or TYPE_KEY in data:
                observability.METRICS.record_message("type", str(data.get(TYPE_KEY, "?")))
                await _handle_external_frame(websocket, data)
                continue

            event_name = data.get("event")
            if event_name is not None:
                observability.METRICS.record_message("event", str(event_name))

            if data.get("event") == "lap_complete":
                hints = data.get("coachingHints") or []
                logger.info(
                    "lap_complete lap=%s lapTimeMs=%s hints=%s",
                    data.get("lap"),
                    data.get("lapTimeMs"),
                    hints,
                )

            # Archive-backed activation frames are emitted after Lua knows the final archive path.
            # They should only run the brain, not the generic rules ack or Ollama narration.
            if (
                reply_coaching
                and data.get("event") == "lap_complete"
                and data.get("brainOnly") is True
            ):
                brain_task = asyncio.create_task(_send_brain_followup(websocket, data))
                _background_tasks.add(brain_task)
                pending_followups.add(brain_task)
                brain_task.add_done_callback(_followup_done)
                continue

            # corner_query runs compose_corner_hint (blocking HTTP to Ollama). Do not
            # stall the websocket message loop — process it in a background task.
            # corner_query does not read LapComparisonState — keep it out of
            # prepare_lock so lap_complete is not blocked behind Ollama (Copilot).
            if reply_coaching and data.get("event") == EVENT_CORNER_QUERY:

                async def _corner_job(d: dict[str, Any], gen: int) -> None:
                    try:
                        out_c = await asyncio.to_thread(
                            prepare_outbound_message,
                            d,
                            reply_coaching=reply_coaching,
                            lap_state=lap_state,
                        )
                        if gen != corner_job_gen[0]:
                            return
                        if out_c is not None:
                            await _safe_send(websocket, out_c)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("corner_query async handler failed")

                corner_job_gen[0] += 1
                job_gen = corner_job_gen[0]
                if pending_corner_task and not pending_corner_task.done():
                    pending_corner_task.cancel()
                t_c = asyncio.create_task(_corner_job(data, job_gen))
                pending_corner_task = t_c
                _background_tasks.add(t_c)
                pending_followups.add(t_c)
                t_c.add_done_callback(_followup_done)
                continue

            async with prepare_lock:
                out = await asyncio.to_thread(
                    prepare_outbound_message,
                    data,
                    reply_coaching=reply_coaching,
                    lap_state=lap_state,
                )
            if out is not None:
                await _safe_send(websocket, out)

                # Round 8: schedule Ollama follow-up in the background so the
                # immediate response above is not blocked on LLM latency. CSP
                # receives hints+rules_debrief in <100ms, then gets the Ollama
                # debrief as a second message when it's ready (~5-15s later).
                if (
                    debrief_feature_enabled()
                    and reply_coaching
                    and data.get("event") == "lap_complete"
                    and isinstance(out, dict)
                    and out.get("event") == EVENT_COACHING_RESPONSE
                ):
                    # Reuse improvementRanking from the immediate response — calling
                    # improvement_ranking_for again mutates LapComparisonState and
                    # diverges on PB laps (Bugbot).
                    imp_for_bg = out.get("improvementRanking") or []
                    bg_task = asyncio.create_task(
                        _send_ollama_followup(websocket, data, imp_for_bg)
                    )
                    _background_tasks.add(bg_task)
                    pending_followups.add(bg_task)
                    bg_task.add_done_callback(_followup_done)

                    # Also spawn the setup-vs-technique attribution brain (issue #275): a deeper,
                    # archive-grounded follow-up that the rules ack + Ollama narration cannot
                    # produce. Independent task so neither blocks the other.
                    brain_task = asyncio.create_task(_send_brain_followup(websocket, data))
                    _background_tasks.add(brain_task)
                    pending_followups.add(brain_task)
                    brain_task.add_done_callback(_followup_done)
    finally:
        _external_peers.discard(websocket)
        _external_peer_classes.pop(websocket, None)
        _release_observer_feed(websocket)
        for t in list(pending_followups):
            if not t.done():
                t.cancel()
        if pending_followups:
            await asyncio.gather(*pending_followups, return_exceptions=True)


async def _run(
    host: str,
    port: int,
    reply_coaching: bool,
    token: str | None,
    setup_store: str | None = None,
    setup_exchange_endpoint: str | None = None,
    user_setups_root: str | None = None,
) -> None:
    global _setup_exchange_endpoint, _setup_exchange_user_setups_root
    global _setup_experiment_store_path, _setup_experiment_store_seeded
    try:
        import websockets
    except ImportError as e:
        raise SystemExit('websockets is required. Install: pip install -e ".[coaching]"') from e

    process_request = make_process_request(token)
    _reset_external_state()
    _setup_experiment_store_path = Path(setup_store) if setup_store else None
    _setup_experiment_store_seeded = setup_store is not None
    _setup_exchange_endpoint = setup_exchange_endpoint or os.environ.get(
        ENV_SETUP_EXCHANGE_ENDPOINT
    )
    configured_setups_root = user_setups_root or os.environ.get(ENV_USER_SETUPS_DIR)
    _setup_exchange_user_setups_root = _user_setups_root_from_config(configured_setups_root)
    try:
        try:
            async with websockets.serve(
                lambda ws: _handler(ws, reply_coaching),
                host,
                port,
                process_request=process_request,
            ):
                logger.info(
                    "AI sidecar listening host=%s port=%s protocol=%s reply_coaching=%s token=%s",
                    host,
                    port,
                    PROTOCOL_VERSION,
                    reply_coaching,
                    "set" if token else "unset",
                )
                await asyncio.Future()
        except OSError as exc:
            # WinError 10048 / errno EADDRINUSE: another sidecar already owns the port. Exit
            # cleanly with a one-line reason instead of a traceback — a frozen --noconsole build
            # turns an unhandled exception into a scary "Unhandled exception in script" dialog,
            # whereas SystemExit(str) just logs the message and returns a non-zero code.
            if exc.errno in {errno.EADDRINUSE, _WSAEADDRINUSE}:
                raise SystemExit(
                    f"sidecar port {port} on {host} is already in use — another AC Copilot "
                    f"sidecar is probably running. Stop it first, or set "
                    f"AC_COPILOT_SIDECAR_PORT to a free port."
                ) from exc
            raise
    finally:
        _reset_external_state()


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _wire_voice(voice_settings: VoiceRuntimeConfig) -> None:
    """Build the optional live observer + in-process voice coach from CLI paths (issue #341).

    Best-effort by design: a missing/invalid reference or bank disables the feature with a loud log
    rather than aborting the sidecar — telemetry and haptics must keep flowing regardless. Audio
    deps
    are imported lazily here (only when ``--voice-bank`` is supplied), so the sidecar core stays
    dep-free for users who never enable voice.
    """
    reference_path = voice_settings.reference_path
    bank_dir = voice_settings.bank_dir
    bank_backend = (
        voice_settings.backend or os.environ.get("AC_COPILOT_VOICE_BACKEND") or "rtmixer"
        if bank_dir
        else None
    )
    configured = bool(reference_path or bank_dir or voice_settings.tts_enabled)
    set_voice_runtime_status(
        configured=configured,
        enabled=False,
        state="initializing" if configured else "skipped",
        disabled_reason="",
        backend=bank_backend or "",
        bank_configured=bool(bank_dir),
        reference_configured=bool(reference_path),
        tts_enabled=bool(voice_settings.tts_enabled),
    )
    if not configured:
        return
    if bank_dir and not reference_path:
        reason = "voice bank configured without AC_COPILOT_REFERENCE_ARCHIVE"
        logger.error("voice: %s", reason)
        set_voice_runtime_status(
            configured=True,
            enabled=False,
            state="disabled",
            disabled_reason=reason,
            backend=bank_backend or "",
            bank_configured=True,
            reference_configured=False,
            tts_enabled=bool(voice_settings.tts_enabled),
        )
        return

    observer_ready = False
    if reference_path:
        try:
            from tools.ai_sidecar.realtime_observer import build_observer_from_reference

            with open(reference_path, encoding="utf-8") as fh:
                archive = json.load(fh)
            observer = build_observer_from_reference(archive)
            if observer is None:
                reason = f"reference {reference_path} has no usable corners"
                logger.error("voice: %s — observer disabled", reason)
                set_voice_runtime_status(
                    configured=True,
                    enabled=False,
                    state="disabled",
                    disabled_reason=reason,
                    backend=bank_backend or "",
                    bank_configured=bool(bank_dir),
                    reference_configured=True,
                    tts_enabled=bool(voice_settings.tts_enabled),
                )
            else:
                set_realtime_observer(observer)
                observer_ready = True
                set_voice_runtime_status(
                    configured=True,
                    enabled=False,
                    state="observer_only",
                    disabled_reason="",
                    backend=bank_backend or "",
                    bank_configured=bool(bank_dir),
                    reference_configured=True,
                    tts_enabled=bool(voice_settings.tts_enabled),
                )
                logger.info("voice: realtime observer wired from reference %s", reference_path)
        except Exception as exc:  # noqa: BLE001 - malformed archive must not abort the sidecar
            reason = f"failed to load reference {reference_path}: {exc or type(exc).__name__}"
            logger.exception("voice: failed to load reference %s", reference_path)
            set_voice_runtime_status(
                configured=True,
                enabled=False,
                state="disabled",
                disabled_reason=reason,
                backend=bank_backend or "",
                bank_configured=bool(bank_dir),
                reference_configured=True,
                tts_enabled=bool(voice_settings.tts_enabled),
            )
    if (bank_dir or voice_settings.tts_enabled) and not observer_ready:
        return
    if bank_dir:
        try:
            from tools.ai_sidecar.voice.config import VoiceConfig
            from tools.ai_sidecar.voice.engine import VoiceCoach

            backend = bank_backend or "rtmixer"
            config = VoiceConfig(
                device_name=voice_settings.device or os.environ.get("AC_COPILOT_VOICE_DEVICE"),
                host_api=voice_settings.host_api or os.environ.get("AC_COPILOT_VOICE_HOST_API"),
                verbosity=(
                    voice_settings.verbosity
                    or os.environ.get("AC_COPILOT_VOICE_VERBOSITY")
                    or "low"
                ),
            )
            coach = VoiceCoach.from_bank(bank_dir, config, backend=backend)
            if not coach.enabled:
                set_voice_coach(coach)
                set_voice_runtime_status(
                    configured=True,
                    enabled=False,
                    state="disabled",
                    disabled_reason=coach.disabled_reason,
                    backend=backend,
                    bank_configured=True,
                    reference_configured=True,
                    tts_enabled=False,
                )
                logger.error(
                    "voice: bank %s disabled the coach (%s)", bank_dir, coach.disabled_reason
                )
            else:
                coach.start()
                set_voice_coach(coach)
                set_voice_runtime_status(
                    configured=True,
                    enabled=True,
                    state="enabled",
                    disabled_reason="",
                    backend=backend,
                    bank_configured=True,
                    reference_configured=True,
                    tts_enabled=False,
                )
                logger.info(
                    "voice: in-process voice coach wired from bank %s "
                    "backend=%s device=%r host_api=%r verbosity=%s",
                    bank_dir,
                    backend,
                    config.device_name,
                    config.host_api,
                    config.verbosity.name.lower(),
                )
        except Exception as exc:  # noqa: BLE001 - any backend/import fault disables voice, never aborts
            set_voice_runtime_status(
                configured=True,
                enabled=False,
                state="disabled",
                disabled_reason=f"failed to initialize voice coach: {exc or type(exc).__name__}",
                backend=bank_backend or "",
                bank_configured=True,
                reference_configured=True,
                tts_enabled=False,
            )
            logger.exception("voice: failed to initialize voice coach from %s", bank_dir)
    elif voice_settings.tts_enabled:
        try:
            from tools.ai_sidecar.voice.client import (
                DEFAULT_TTS_RATE,
                DEFAULT_TTS_VOLUME,
                _pyttsx3_speaker,
            )

            rate = (
                voice_settings.tts_rate
                if voice_settings.tts_rate is not None
                else _env_int(
                    "AC_COPILOT_VOICE_RATE", DEFAULT_TTS_RATE, min_value=120, max_value=360
                )
            )
            volume = (
                voice_settings.tts_volume
                if voice_settings.tts_volume is not None
                else _env_float(
                    "AC_COPILOT_VOICE_VOLUME",
                    DEFAULT_TTS_VOLUME,
                    min_value=0.0,
                    max_value=1.0,
                )
            )
            set_voice_coach(
                _Pyttsx3VoiceCoach(
                    _pyttsx3_speaker(
                        base_rate=rate,
                        base_volume=volume,
                        require_opt_in=False,
                    )
                )
            )
            set_voice_runtime_status(
                configured=True,
                enabled=True,
                state="tts",
                disabled_reason="",
                backend="pyttsx3",
                bank_configured=False,
                reference_configured=True,
                tts_enabled=True,
            )
            logger.info(
                "voice: in-process pyttsx3 voice coach wired rate=%s volume=%.2f",
                rate,
                volume,
            )
        except Exception as exc:  # noqa: BLE001 - pyttsx3 must never abort the sidecar
            reason = f"failed to initialize pyttsx3 voice coach: {exc or type(exc).__name__}"
            set_voice_runtime_status(
                configured=True,
                enabled=False,
                state="disabled",
                disabled_reason=reason,
                backend="pyttsx3",
                bank_configured=False,
                reference_configured=True,
                tts_enabled=True,
            )
            logger.exception("voice: failed to initialize pyttsx3 voice coach")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="AC Copilot Trainer AI sidecar (WebSocket)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--external-bind",
        default=None,
        help=(
            "Bind a LAN-reachable address for external clients (e.g. 0.0.0.0). "
            "Non-loopback binds require --token. "
            "When unset, the sidecar listens only on --host."
        ),
    )
    p.add_argument(
        "--token",
        default=os.environ.get("AC_COPILOT_SIDECAR_TOKEN"),
        help=(
            "Shared secret enforced on the WS upgrade as X-AC-Copilot-Token. "
            "Required whenever --external-bind is non-loopback. "
            "Defaults to $AC_COPILOT_SIDECAR_TOKEN when set."
        ),
    )
    p.add_argument(
        "--compare-laps",
        nargs=2,
        metavar=("LAST_JSON", "REF_JSON"),
        help=(
            "Print corner improvement ranking JSON from two lap_complete-style fixtures "
            "(telemetry.corners) and exit."
        ),
    )
    p.add_argument(
        "--setup-record-lap",
        metavar="LAP_JSON",
        help="Upsert one setup experiment row from a PR #78 lap archive JSON and exit.",
    )
    p.add_argument(
        "--setup-rebuild-experiments",
        metavar="LAP_DIR",
        help="Rebuild setup experiment JSONL from a journal/laps directory and exit.",
    )
    p.add_argument(
        "--setup-store",
        metavar="EXPERIMENTS_JSONL",
        help=(
            "Experiment JSONL path for setup record/rebuild/compare/suggest commands; "
            "also seeds WS compare/suggest when serving."
        ),
    )
    p.add_argument(
        "--setup-compare",
        nargs=2,
        metavar=("BASELINE_SETUP", "CANDIDATE_SETUP"),
        help="Compare two setup identifiers from --setup-store and exit.",
    )
    p.add_argument(
        "--setup-suggest",
        action="store_true",
        help="Return the next setup candidate from --setup-store and exit.",
    )
    p.add_argument(
        "--setup-car-id", default=None, help="Optional car id filter for --setup-suggest."
    )
    p.add_argument(
        "--setup-track-id",
        default=None,
        help="Optional track id filter for --setup-suggest.",
    )
    p.add_argument(
        "--se-endpoint",
        default=os.environ.get(ENV_SETUP_EXCHANGE_ENDPOINT),
        help=(
            "Authenticated Setup Exchange-compatible proxy endpoint for se.search/se.download. "
            f"Falls back to ${ENV_SETUP_EXCHANGE_ENDPOINT}; direct se.acstuff.club "
            "requires the official signed session handshake and is not used by default."
        ),
    )
    p.add_argument(
        "--user-setups-root",
        default=os.environ.get(ENV_USER_SETUPS_DIR),
        help=(
            "Assetto Corsa user setups directory for se.download installs. "
            f"Falls back to ${ENV_USER_SETUPS_DIR}, then Windows Documents discovery."
        ),
    )
    p.add_argument(
        "--no-reply",
        action="store_true",
        help=(
            "Log lap_complete only; do not send coaching_response. "
            "analysis_error frames may still be sent for invalid JSON or non-object payloads."
        ),
    )
    p.add_argument(
        "--voice-reference",
        default=None,
        help=(
            "Issue #341: path to a faster reference-lap archive JSON. When set, the sidecar feeds "
            "live telemetry_tick frames to a RealtimeObserver built from it and publishes "
            "per-corner advisories on the `coaching.cue` topic. "
            "Falls back to $AC_COPILOT_REFERENCE_ARCHIVE."
        ),
    )
    p.add_argument(
        "--voice-bank",
        default=None,
        help=(
            "Issue #341/#340: path to a baked phrase-bank directory. When set (with "
            "--voice-reference), the sidecar speaks the live cues in-process via the VoiceCoach "
            "engine. Requires the `voice` extra (numpy/sounddevice/rtmixer) + an audio device. "
            "Falls back to $AC_COPILOT_VOICE_BANK."
        ),
    )
    p.add_argument(
        "--voice-backend",
        default=None,
        choices=("rtmixer", "sounddevice"),
        help=(
            "Audio backend for --voice-bank. Falls back to $AC_COPILOT_VOICE_BACKEND then rtmixer."
        ),
    )
    p.add_argument(
        "--voice-device",
        default=None,
        help=(
            "Output device substring for --voice-bank, e.g. 'USB Sound Device'. "
            "Falls back to $AC_COPILOT_VOICE_DEVICE."
        ),
    )
    p.add_argument(
        "--voice-host-api",
        default=None,
        help=(
            "PortAudio host API for --voice-bank, e.g. 'Windows DirectSound' or "
            "'Windows WASAPI'. Falls back to $AC_COPILOT_VOICE_HOST_API."
        ),
    )
    p.add_argument(
        "--voice-verbosity",
        default=None,
        choices=("off", "low", "normal", "high"),
        help="Voice-bank verbosity. Falls back to $AC_COPILOT_VOICE_VERBOSITY.",
    )
    p.add_argument(
        "--voice-tts",
        action="store_true",
        help=(
            "Issue #341: speak coaching.cue advisories in-process via Windows pyttsx3 when no "
            "voice bank is configured. Also enabled by $AC_COPILOT_VOICE_TTS=1."
        ),
    )
    p.add_argument(
        "--voice-rate",
        type=int,
        default=None,
        help="pyttsx3 speaking rate for --voice-tts. Falls back to $AC_COPILOT_VOICE_RATE.",
    )
    p.add_argument(
        "--voice-volume",
        type=float,
        default=None,
        help=(
            "pyttsx3 speaking volume for --voice-tts, 0.0 to 1.0. "
            "Falls back to $AC_COPILOT_VOICE_VOLUME."
        ),
    )
    args = p.parse_args()
    if args.compare_laps:
        _run_compare_laps(args.compare_laps[0], args.compare_laps[1])
        return
    if args.setup_record_lap:
        _run_setup_record_lap(args.setup_record_lap, args.setup_store)
        return
    if args.setup_rebuild_experiments:
        _run_setup_rebuild(args.setup_rebuild_experiments, args.setup_store)
        return
    if args.setup_compare:
        if not args.setup_store:
            raise SystemExit("--setup-compare requires --setup-store")
        _run_setup_compare(args.setup_store, args.setup_compare[0], args.setup_compare[1])
        return
    if args.setup_suggest:
        if not args.setup_store:
            raise SystemExit("--setup-suggest requires --setup-store")
        _run_setup_suggest(args.setup_store, args.setup_car_id, args.setup_track_id)
        return
    reply = not args.no_reply

    if args.external_bind is not None:
        host = args.external_bind
        if not _is_loopback(host) and not args.token:
            raise SystemExit(
                "--external-bind requires --token for non-loopback addresses "
                "(refusing to expose unauthenticated socket)"
            )
    else:
        host = args.host
    if not _is_loopback(host) and not args.token:
        raise SystemExit("--token is required for non-loopback bind addresses")

    ref_path = args.voice_reference or os.environ.get("AC_COPILOT_REFERENCE_ARCHIVE")
    bank_dir = args.voice_bank or os.environ.get("AC_COPILOT_VOICE_BANK")
    _wire_voice(
        VoiceRuntimeConfig(
            reference_path=ref_path,
            bank_dir=bank_dir,
            tts_enabled=args.voice_tts or _env_truthy("AC_COPILOT_VOICE_TTS"),
            tts_rate=args.voice_rate,
            tts_volume=args.voice_volume,
            backend=args.voice_backend,
            device=args.voice_device,
            host_api=args.voice_host_api,
            verbosity=args.voice_verbosity,
        )
    )

    try:
        asyncio.run(
            _run(
                host,
                args.port,
                reply,
                args.token,
                args.setup_store,
                args.se_endpoint,
                args.user_setups_root,
            )
        )
    except KeyboardInterrupt:
        logger.info("sidecar stopped")


if __name__ == "__main__":
    main()
