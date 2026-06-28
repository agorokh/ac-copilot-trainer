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
import ipaddress
import json
import logging
import secrets
import time
from collections.abc import Callable
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
    TYPE_SETUP_EXPERIMENT_RECORD,
    TYPE_SETUP_EXPERIMENT_RECORD_ACK,
    TYPE_SETUP_EXPERIMENT_STORE,
    TYPE_SETUP_EXPERIMENT_STORE_ACK,
    TYPE_SETUP_LIST,
    TYPE_SETUP_LIST_RESULT,
    TYPE_SETUP_LOAD,
    TYPE_SETUP_LOAD_ACK,
    TYPE_SETUP_SUGGEST,
    TYPE_SETUP_SUGGEST_RESULT,
    TYPE_STATE_SNAPSHOT,
    TYPE_STATE_SUBSCRIBE,
    TYPE_STATE_UNSUBSCRIBE,
    TYPE_TELEMETRY_TICK,
    make_coaching_cue,
    make_error,
    make_hello_ack,
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
_external_peer_classes: dict[Any, str] = {}

# Issue #341 — live voice wiring. Both are OPTIONAL and OFF by default: a sidecar with neither set
# behaves byte-identically to before. ``_observer`` turns the live ``telemetry_tick`` stream into
# per-corner advisories (published on ``coaching.cue``); ``_voice_coach`` (the #340 phrase-bank
# engine) speaks them in-process on the rig. The audio deps live only inside the voice package and
# are imported lazily when ``--voice-bank`` is supplied, so the sidecar core stays dep-free.
_observer: Any | None = None
_voice_coach: Any | None = None


def set_realtime_observer(observer: Any | None) -> None:
    """Install (or clear) the live ``RealtimeObserver`` fed by ``telemetry_tick`` (issue #341)."""
    global _observer
    _observer = observer


def set_voice_coach(coach: Any | None) -> None:
    """Install (or clear) the in-process voice coach that speaks advisories on the rig (#341)."""
    global _voice_coach
    _voice_coach = coach


TELEMETRY_TICK_MAX_HZ = 20.0
HAPTIC_EVENT_MAX_HZ = 25.0
LEGACY_SCREEN_CLIENT_PREFIXES = ("ac-copilot-screen",)

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
        TYPE_SETUP_EXPERIMENT_STORE,
        TYPE_SETUP_EXPERIMENT_RECORD,
        TYPE_SETUP_COMPARE,
        TYPE_SETUP_SUGGEST,
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
        TYPE_SETUP_EXPERIMENT_STORE_ACK,
        TYPE_SETUP_EXPERIMENT_RECORD_ACK,
        TYPE_SETUP_COMPARE_RESULT,
        TYPE_SETUP_SUGGEST_RESULT,
    }
)
SIDECAR_LOCAL_TYPES = frozenset(
    {
        TYPE_SETUP_EXPERIMENT_STORE,
        TYPE_SETUP_EXPERIMENT_RECORD,
        TYPE_SETUP_COMPARE,
        TYPE_SETUP_SUGGEST,
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
    _external_peers.clear()
    _external_peer_classes.clear()
    _peripheral_rate_limiter.reset()


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
            return _http_response(
                connection,
                HTTPStatus.OK,
                observability.build_health_json(len(_external_peers)),
                observability.HEALTH_CONTENT_TYPE,
            )
        if path == "/metrics":
            return _http_response(
                connection,
                HTTPStatus.OK,
                observability.build_metrics_text(len(_external_peers)),
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


def _advisory_to_payload(advisory: Any) -> dict[str, Any]:
    """Flatten a ``RealtimeObserver`` Advisory into the ``coaching.cue`` wire payload (issue #341).

    ``corner`` is kept 0-based (as the observer emits it) so a consumer can reconstruct the Advisory
    faithfully; the human-facing 1-based turn number already lives in ``message`` ("...T4...").
    """
    return {
        "kind": getattr(advisory, "kind", None),
        "corner": getattr(advisory, "corner", None),
        "urgency": getattr(advisory, "urgency", None),
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
    """
    observer = _observer
    if observer is None:
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
        cue = make_coaching_cue(_advisory_to_payload(advisory), ts_sim=ts_sim)
        await _broadcast_external(cue, exclude=exclude)


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
) -> None:
    global _setup_experiment_store_path, _setup_experiment_store_seeded
    try:
        import websockets
    except ImportError as e:
        raise SystemExit('websockets is required. Install: pip install -e ".[coaching]"') from e

    process_request = make_process_request(token)
    _reset_external_state()
    _setup_experiment_store_path = Path(setup_store) if setup_store else None
    _setup_experiment_store_seeded = setup_store is not None
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
    finally:
        _reset_external_state()


def _is_loopback(host: str) -> bool:
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _wire_voice(reference_path: str | None, bank_dir: str | None) -> None:
    """Build the optional live observer + in-process voice coach from CLI paths (issue #341).

    Best-effort by design: a missing/invalid reference or bank disables the feature with a loud log
    rather than aborting the sidecar — telemetry and haptics must keep flowing regardless. Audio
    deps
    are imported lazily here (only when ``--voice-bank`` is supplied), so the sidecar core stays
    dep-free for users who never enable voice.
    """
    if reference_path:
        try:
            from tools.ai_sidecar.realtime_observer import build_observer_from_reference

            with open(reference_path, encoding="utf-8") as fh:
                archive = json.load(fh)
            observer = build_observer_from_reference(archive)
            if observer is None:
                logger.error(
                    "voice: reference %s has no usable corners — observer disabled", reference_path
                )
            else:
                set_realtime_observer(observer)
                logger.info("voice: realtime observer wired from reference %s", reference_path)
        except (OSError, ValueError) as exc:
            logger.error("voice: failed to load reference %s: %s", reference_path, exc)
    if bank_dir:
        try:
            from tools.ai_sidecar.voice.engine import VoiceCoach

            coach = VoiceCoach.from_bank(bank_dir)
            if not coach.enabled:
                logger.error(
                    "voice: bank %s disabled the coach (%s)", bank_dir, coach.disabled_reason
                )
            else:
                coach.start()
                set_voice_coach(coach)
                logger.info("voice: in-process voice coach wired from bank %s", bank_dir)
        except Exception:  # noqa: BLE001 - any backend/import fault disables voice, never aborts
            logger.exception("voice: failed to initialize voice coach from %s", bank_dir)


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
        default=None,
        help=(
            "Shared secret enforced on the WS upgrade as X-AC-Copilot-Token. "
            "Required whenever --external-bind is non-loopback."
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
            "per-corner advisories on the `coaching.cue` topic."
        ),
    )
    p.add_argument(
        "--voice-bank",
        default=None,
        help=(
            "Issue #341/#340: path to a baked phrase-bank directory. When set (with "
            "--voice-reference), the sidecar speaks the live cues in-process via the VoiceCoach "
            "engine. Requires the `voice` extra (numpy/sounddevice/rtmixer) + an audio device."
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

    _wire_voice(args.voice_reference, args.voice_bank)

    try:
        asyncio.run(_run(host, args.port, reply, args.token, args.setup_store))
    except KeyboardInterrupt:
        logger.info("sidecar stopped")


if __name__ == "__main__":
    main()
