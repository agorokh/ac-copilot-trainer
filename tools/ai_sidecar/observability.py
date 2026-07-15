"""Prometheus ``/metrics`` + ``/health`` text builders for the AI sidecar (issue #167).

Stdlib-only emitter — the metric set is small and fixed-cardinality, so a full
``prometheus_client`` dependency is unwarranted (keeps the ``[coaching]`` extra
to ``websockets`` + the ML libs). The endpoints are served over the websockets
``process_request`` hook on the same ``:8765`` port (see
``server.make_process_request``), so a plain HTTP ``GET /health`` or ``/metrics``
short-circuits the WS upgrade and never enters the coaching handler.

Thread-safety: counters are mutated from the asyncio event-loop thread (the
process_request hook + frame dispatch) and from ``asyncio.to_thread`` worker
threads (the Ollama follow-up error path), so increments take a module lock.
``build_metrics_text`` snapshots the counters under the lock and formats the
exposition text OUTSIDE the lock, so rendering ``/metrics`` cannot stall a
concurrent WS upgrade.

Cross-repo: fleet registration of this surface as a session-scoped service lands
in ``agorokh/workstation-ops`` (#517).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from tools.ai_sidecar.external_protocol import SERVER_VERSION
from tools.ai_sidecar.protocol import PROTOCOL_VERSION

# Prometheus text exposition content type (version 0.0.4).
PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
HEALTH_CONTENT_TYPE = "application/json"
# A screen counts as "connected" if its client header was seen this recently.
SCREEN_RECENCY_SECONDS = 120.0

_lock = threading.Lock()
_build_commit_cache: str | None = None
_build_time_cache: str | None = None

# Baked into the frozen EXE at package time by the PyInstaller runtime hook that
# ``tools.rig_launcher.build_info`` generates (issue #569). Keep the names in lockstep.
BUILD_COMMIT_ENV = "AC_COPILOT_BUILD_COMMIT"
BUILD_TIME_ENV = "AC_COPILOT_BUILD_TIME"


def _git_output(args: list[str]) -> str:
    """Best-effort ``git`` stdout for the dev/source path. ``""`` on any failure."""
    try:
        completed = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            # Anchor to THIS module's source tree so a sidecar launched from elsewhere (a desktop
            # shortcut, or a frozen EXE that happens to sit inside an unrelated git repo) can't
            # report a foreign commit (#568 self-hosted reviewer).
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def build_commit() -> str:
    """Short commit hash of the running build.

    Resolution order (issue #567): ``AC_COPILOT_BUILD_COMMIT`` (baked at package
    time — a frozen PyInstaller EXE has no ``.git``), then a best-effort
    ``git rev-parse --short HEAD`` for dev checkouts, then ``"unknown"``. The
    result is immutable for a process, so it is cached after the first call — the
    at-most-once ``git`` subprocess never repeats on the ``/health`` hot path.
    """
    global _build_commit_cache
    if _build_commit_cache is not None:
        return _build_commit_cache
    baked = os.environ.get(BUILD_COMMIT_ENV, "").strip()
    if baked:
        _build_commit_cache = baked
        return baked
    _build_commit_cache = _git_output(["rev-parse", "--short", "HEAD"]) or "unknown"
    return _build_commit_cache


def build_time() -> str:
    """ISO-8601 UTC timestamp of the running build.

    Resolution order (issue #569): ``AC_COPILOT_BUILD_TIME`` (baked at package time,
    where it is when the EXE was *packaged*), then the ``HEAD`` commit date for dev
    checkouts — a source run has no packaging event, so the commit date is the closest
    honest answer — then ``"unknown"``. Cached like ``build_commit``.
    """
    global _build_time_cache
    if _build_time_cache is not None:
        return _build_time_cache
    baked = os.environ.get(BUILD_TIME_ENV, "").strip()
    if baked:
        _build_time_cache = baked
        return baked
    _build_time_cache = _git_output(["log", "-1", "--format=%cI"]) or "unknown"
    return _build_time_cache


@dataclass
class SidecarMetrics:
    """Process-global counters/gauges for the sidecar (singleton ``METRICS``)."""

    # (label_key, label_value) -> count, e.g. ("event", "lap_complete") or ("type", "hello").
    messages: dict[tuple[str, str], int] = field(default_factory=dict)
    ollama_followup_errors: int = 0
    last_message_ts: float = 0.0  # unix seconds of the last dispatched message
    screen_last_seen_monotonic: float = 0.0  # time.monotonic() of the last screen client header

    def record_message(self, label_key: str, label_value: str) -> None:
        with _lock:
            key = (label_key, label_value)
            self.messages[key] = self.messages.get(key, 0) + 1
            self.last_message_ts = time.time()

    def record_ollama_followup_error(self) -> None:
        with _lock:
            self.ollama_followup_errors += 1

    def note_screen_seen(self) -> None:
        with _lock:
            self.screen_last_seen_monotonic = time.monotonic()


METRICS = SidecarMetrics()


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(pairs: dict[str, str]) -> str:
    if not pairs:
        return ""
    inner = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(pairs.items()))
    return "{" + inner + "}"


def build_health_json(
    connected_peers: int,
    *,
    screen_peers: int = 0,
    browser_peers: int = 0,
    endpoints: Sequence[str] = (),
    voice: Mapping[str, object] | None = None,
) -> str:
    """Instant health body: the endpoint answering IS liveness.

    Carries ``build_commit`` + ``build_time`` + the served ``endpoints`` set
    (issues #567/#569) so a stale packaged binary is identifiable from the
    payload — and, for a frozen EXE, says *which* build it is — and ``browser_peers``
    so the launcher can tell a tablet dashboard is actually connected (not just
    that the tunnel is up). ``endpoints`` is the **caller's** canonical route
    list — the single source of truth lives next to the handlers in
    ``server.make_process_request`` (``server.SERVED_ENDPOINTS``), not here — so a
    new route can't be served yet silently omitted from ``/health`` (#568 review).
    """
    payload: dict[str, object] = {
        "status": "ok",
        "connected_peers": connected_peers,
        "screen_peers": screen_peers,
        "browser_peers": browser_peers,
        "build_commit": build_commit(),
        "build_time": build_time(),
        "endpoints": list(endpoints),
    }
    if voice is not None:
        payload["voice"] = dict(voice)
    return json.dumps(payload, separators=(",", ":"))


def build_metrics_text(connected_peers: int, *, screen_peers: int = 0) -> str:
    """Prometheus exposition text for the sidecar's fixed metric set.

    Snapshots the shared counters under the lock, then formats outside it.
    """
    with _lock:
        messages = dict(METRICS.messages)  # snapshot under lock; format below outside it
        ollama_errors = METRICS.ollama_followup_errors
        last_message_ts = METRICS.last_message_ts
        screen_last_seen = METRICS.screen_last_seen_monotonic

    now_mono = time.monotonic()
    screen_recent = (
        1 if screen_last_seen > 0 and (now_mono - screen_last_seen) < SCREEN_RECENCY_SECONDS else 0
    )
    screen_connected = 1 if screen_peers > 0 or screen_recent else 0

    lines: list[str] = []

    def emit(
        name: str, help_text: str, metric_type: str, samples: list[tuple[dict[str, str], object]]
    ) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {metric_type}")
        for label_pairs, value in samples:
            lines.append(f"{name}{_labels(label_pairs)} {value}")

    emit("ac_sidecar_up", "Sidecar HTTP endpoint is answering.", "gauge", [({}, 1)])
    emit(
        "ac_sidecar_build_info",
        "Sidecar build/version info.",
        "gauge",
        [({"protocol_version": str(PROTOCOL_VERSION), "server_version": SERVER_VERSION}, 1)],
    )
    emit(
        "ac_sidecar_connected_peers",
        "External v1 peers currently connected.",
        "gauge",
        [({}, connected_peers)],
    )
    emit(
        "ac_sidecar_screen_peers",
        "ESP32 rig-screen peers currently connected.",
        "gauge",
        [({}, screen_peers)],
    )
    emit(
        "ac_sidecar_messages_total",
        "Messages dispatched, by envelope label (event= legacy, type= v1).",
        "counter",
        [
            ({label_key: label_value}, count)
            for (label_key, label_value), count in sorted(messages.items())
        ],
    )
    emit(
        "ac_sidecar_ollama_followup_errors_total",
        "Ollama coaching follow-ups that failed or did not deliver.",
        "counter",
        [({}, ollama_errors)],
    )
    emit(
        "ac_sidecar_screen_connected",
        "1 if an ESP32 rig-screen client was seen within the recency window.",
        "gauge",
        [({}, screen_connected)],
    )
    emit(
        "ac_sidecar_last_message_timestamp",
        "Unix timestamp of the last dispatched message (0 if none yet).",
        "gauge",
        [({}, f"{last_message_ts:.0f}")],
    )
    return "\n".join(lines) + "\n"
