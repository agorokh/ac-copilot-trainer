"""The urgency scheduler — decides *which* cue speaks, *when*, and what it interrupts.

Kept strictly separate from the renderer (:mod:`resolver`) and the audio backend (:mod:`playback`)
so a future free-form/TTS path can never stall a critical ``act`` cue (issue #340). The telemetry/WS
thread only calls :meth:`Scheduler.submit`; all arbitration happens here, off that thread.

Decision policy (per the issue's acceptance criteria):

* **Urgency wins** — ``act`` > ``prepare`` > ``info``. Among everything pending, the highest-urgency
  cue is the one considered.
* **Barge-in** — an ``act`` cue arriving while a *strictly lower* urgency clip is playing cancels
  that clip and speaks immediately. A lower/equal cue never interrupts what is playing (it would be
  stale by the time the current clip ended), so it is dropped rather than queued.
* **Dedup** — the same ``(kind, corner)`` within one corner pass collapses to a single utterance.
The
  dedup window is shorter than a lap, so the *next* pass is never suppressed.
* **TTL / staleness** — an advisory older than ``ttl_s`` (the car is already past the point) is
  dropped before it can speak.
* **Cooldown** — a minimum gap between two cues of the same *kind*. ``act`` is **exempt**: a fresh
  ``act`` cue is never delayed or dropped by cooldown/TTL/dedup machinery.
* **Verbosity** — cues below the configured verbosity floor are suppressed.

The arbitration in :meth:`process_pending` is a pure function of the injected ``clock`` and the
injected :class:`~tools.ai_sidecar.voice.playback.Playback`, so it is fully unit-testable with a
fake
clock + fake playback and no audio hardware. :meth:`start`/:meth:`stop` add the production worker
thread; tests drive :meth:`submit` + :meth:`process_pending` directly.

Pure stdlib (``threading`` + ``time``; ``time`` only as the default clock, always injectable).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from tools.ai_sidecar.voice.config import Verbosity, VoiceConfig
from tools.ai_sidecar.voice.playback import Playback
from tools.ai_sidecar.voice.resolver import Resolver
from tools.ai_sidecar.voice.utterance import URGENCY_RANK, Utterance
from tools.ai_sidecar.voice.vocabulary import REGISTER_RANK

_log = logging.getLogger("ai_sidecar.voice.scheduler")

_ACT_RANK = URGENCY_RANK["act"]
#: tone-register ordering (low -> high) — used only to break a same-urgency barge-in tie so a
#: critical escalation can interrupt a still-playing urgent clip (issue #381).
_REGISTER_RANK = REGISTER_RANK


@dataclass
class _Pending:
    """An advisory awaiting arbitration, stamped with the clock time it was submitted."""

    advisory: object
    enqueued_at: float


class Scheduler:
    """Arbitrates resolved utterances onto a single playback channel."""

    def __init__(
        self,
        resolver: Resolver,
        playback: Playback,
        config: VoiceConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._resolver = resolver
        self._playback = playback
        self._config = config
        self._clock = clock

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._pending: list[_Pending] = []
        self._deferred: list[tuple[Utterance, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        # last time (clock) a given dedup_key actually spoke — drives the dedup window.
        self._last_spoke_key: dict[str, float] = {}
        # last time (clock) a given kind actually spoke — drives the per-kind cooldown.
        self._last_spoke_kind: dict[str, float] = {}

    # ---- submission (any thread) -------------------------------------------------------------

    def submit(self, advisory: object) -> None:
        """Enqueue one advisory for arbitration. Non-blocking; safe from the telemetry thread."""
        now = self._clock()
        with self._cond:
            self._pending.append(_Pending(advisory=advisory, enqueued_at=now))
            self._cond.notify()

    # ---- arbitration (pure; testable) --------------------------------------------------------

    def process_pending(self, now: float | None = None) -> Utterance | None:
        """Arbitrate everything pending and dispatch at most one cue. Returns the cue spoken (or
        None).

        Drains the pending queue, filters by verbosity / TTL / dedup / cooldown, picks the highest
        urgency survivor, and dispatches it to playback with barge-in. Idempotent w.r.t. an empty
        queue. ``now`` defaults to the injected clock.
        """
        if now is None:
            now = self._clock()
        deferred: tuple[Utterance, float] | None = None
        with self._lock:
            if not self._pending and self._deferred and self._playback.current is None:
                deferred = self._deferred.pop(0)
            batch = self._pending
            self._pending = []
        if deferred is not None:
            winner, enqueued_at = deferred
            return self._dispatch(winner, now, enqueued_at=enqueued_at)

        candidates: list[tuple[Utterance, float, int]] = []
        for batch_index, item in enumerate(batch):
            utt = self._consider(item, now)
            if utt is not None:
                candidates.append((utt, item.enqueued_at, batch_index))
        if not candidates:
            return None

        # Highest urgency wins; ties break toward the cue considered last (freshest in this batch).
        # When enqueued_at collides (constant/coarse clock), batch_index preserves submission order.
        winner, enqueued_at, _batch_index = max(
            candidates, key=lambda pair: (pair[0].rank, pair[1], pair[2])
        )
        return self._dispatch(winner, now, enqueued_at=enqueued_at)

    def _consider(self, item: _Pending, now: float) -> Utterance | None:
        """Resolve + filter one pending advisory; return a playable utterance or ``None``."""
        utt = self._resolver.resolve(item.advisory)  # type: ignore[arg-type]
        if utt is None:
            return None
        if self._config.verbosity == Verbosity.OFF:
            return None
        if not self._config.urgency_allowed(utt.urgency):
            return None

        is_act = utt.rank >= _ACT_RANK
        # TTL: a stale advisory (car already past the point) is dropped. A *fresh* act has tiny age,
        # so this never delays a fresh act — it only discards old ones.
        if (now - item.enqueued_at) > self._config.ttl_s:
            _log.debug("voice: dropping stale %s (age=%.3fs)", utt.clip_id, now - item.enqueued_at)
            return None
        # Dedup: same (kind, corner) within the pass collapses to one utterance. Fresh act cues are
        # exempt so a same-corner escalation from "brake soon" to "brake now" is never silenced.
        if not is_act:
            last_key = self._last_spoke_key.get(utt.dedup_key)
            if last_key is not None and (now - last_key) < self._config.dedup_window_s:
                _log.debug("voice: dedup-suppress %s (key=%s)", utt.clip_id, utt.dedup_key)
                return None
        # Cooldown: minimum gap between same-kind cues. ACT is exempt (never delayed/dropped).
        if not is_act:
            last_kind = self._last_spoke_kind.get(utt.kind)
            cooldown = self._config.cooldown_for(utt.kind)
            if last_kind is not None and (now - last_kind) < cooldown:
                _log.debug("voice: cooldown-suppress %s (kind=%s)", utt.clip_id, utt.kind)
                return None
        return utt

    def _dispatch(
        self, winner: Utterance, now: float, *, enqueued_at: float | None = None
    ) -> Utterance | None:
        """Play ``winner`` with barge-in semantics, or drop it if the channel is busy with >=
        cue."""
        current = self._playback.current
        if current is not None:
            higher_urgency = winner.rank > current.rank
            # A hotter escalation over a still-playing act clip shares the `act` urgency rank, so
            # break the tie on the tone register — the more intense alarm must be heard. Same
            # urgency + same/lower register never interrupts (it would be stale).
            louder_same_urgency = winner.rank == current.rank and _REGISTER_RANK.get(
                winner.register, 0
            ) > _REGISTER_RANK.get(current.register, 0)
            if winner.rank >= _ACT_RANK and (higher_urgency or louder_same_urgency):
                # Barge-in: an act cue interrupts a strictly-lower clip — or a higher-intensity
                # register at the same urgency — mid-word.
                _log.info("voice: barge-in %s over %s", winner.clip_id, current.clip_id)
                self._playback.cancel()
            elif (
                winner.rank >= _ACT_RANK
                and winner.kind == "brake_release"
                and current.kind == "late_brake"
            ):
                # A release correction that follows a brake alarm is still fresh and materially
                # different. Defer it until the brake alarm finishes instead of dropping it as an
                # equal/lower act cue.
                with self._lock:
                    self._deferred.append((winner, enqueued_at if enqueued_at is not None else now))
                _log.debug("voice: defer %s until %s finishes", winner.clip_id, current.clip_id)
                return None
            else:
                # Channel busy with an equal/higher cue; the moment for this one has passed — drop
                # it
                # rather than queue a backlog that would speak late.
                _log.debug("voice: channel busy (%s); dropping %s", current.clip_id, winner.clip_id)
                return None
        try:
            self._playback.play(winner)
        except Exception:  # noqa: BLE001 — never let a backend fault crash the scheduler thread
            _log.exception("voice: playback.play failed for %s — staying silent", winner.clip_id)
            return None
        _log.info("voice: dispatched %s urgency=%s", winner.clip_id, winner.urgency)
        if winner.rank >= _ACT_RANK and enqueued_at is not None:
            latency_ms = (now - enqueued_at) * 1000.0
            if latency_ms > 150.0:
                _log.warning(
                    "voice: act cue %s advisory→dispatch latency %.1f ms exceeds 150 ms budget",
                    winner.clip_id,
                    latency_ms,
                )
            else:
                _log.debug(
                    "voice: act cue %s advisory→dispatch latency %.1f ms",
                    winner.clip_id,
                    latency_ms,
                )
        self._last_spoke_key[winner.dedup_key] = now
        self._last_spoke_kind[winner.kind] = now
        return winner

    # ---- production worker thread ------------------------------------------------------------

    def start(self) -> None:
        """Start the dedicated arbitration thread (no-op if already running)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="voice-scheduler", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 2.0) -> None:
        """Signal the worker thread to exit and join it."""
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._cond:
                # Wake on a new submission; also wake periodically so a clip that finished frees the
                # channel for the next submission's arbitration without an unbounded wait.
                while (
                    not self._pending
                    and not self._stop.is_set()
                    and (not self._deferred or self._playback.current is not None)
                ):
                    self._cond.wait(timeout=0.05)
            if self._stop.is_set():
                break
            try:
                self.process_pending(self._clock())
            except Exception:  # noqa: BLE001 — keep the coach alive across any single-cycle fault
                _log.exception("voice: scheduler cycle failed")
