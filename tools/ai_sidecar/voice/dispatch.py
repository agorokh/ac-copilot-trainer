"""Dispatch tap — observe what the scheduler ACTUALLY plays, without touching arbitration.

Issue #511 Part D: a remote audio endpoint (the tablet page) must mirror exactly what the
in-process coach speaks. Re-implementing the scheduler's cooldown/dedup/barge-in in a second
place would drift, so instead the real :class:`~tools.ai_sidecar.voice.playback.Playback` is
wrapped in :class:`DispatchTapPlayback`: every successful ``play`` builds a
:class:`VoiceDispatch` record (seq + wall/monotonic timestamps + clip identity) and hands it
to a listener. The sidecar's listener broadcasts it as a ``coaching.voice`` frame; the
audible-latency harness (issue #381 verification) anchors its end-to-end measurement on the
``t_wall_ms`` stamped here.

The tap is strictly pass-through for scheduling semantics: ``current``/``cancel``/``close``
forward untouched, a listener fault never breaks audio, and when no listener is installed the
engine does not wrap at all — zero behavior change for existing deployments.

Pure stdlib.
"""

from __future__ import annotations

import itertools
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from tools.ai_sidecar.voice.playback import Playback
from tools.ai_sidecar.voice.utterance import Utterance

_log = logging.getLogger("ai_sidecar.voice.dispatch")


@dataclass(frozen=True)
class VoiceDispatch:
    """One clip the scheduler dispatched to playback, stamped at dispatch time.

    ``t_wall_ms`` is Unix-epoch milliseconds (``time.time()``) — the cross-host anchor the
    audible-latency harness compares acoustic onsets against. ``t_mono_ms`` is the server's
    monotonic clock in milliseconds — immune to wall-clock steps, used for intra-server
    interval math. ``duration_ms`` is the pre-decoded clip length when known (``None`` when
    the playback was injected without a bank, e.g. in tests).
    """

    seq: int
    clip_id: str
    kind: str
    urgency: str
    register: str
    corner: int | None
    text: str
    duration_ms: float | None
    t_wall_ms: float
    t_mono_ms: float

    def to_payload(self) -> dict[str, object]:
        """The ``coaching.voice`` wire payload (plain JSON-safe dict)."""
        return asdict(self)


class DispatchTapPlayback:
    """A :class:`Playback` wrapper that notifies a listener on every successful ``play``.

    The listener runs on the scheduler worker thread and MUST be cheap/non-blocking (the
    sidecar's listener only appends to a deque and schedules an async broadcast). Any
    listener exception is swallowed and logged — the audio path always wins.
    """

    def __init__(
        self,
        inner: Playback,
        listener: Callable[[VoiceDispatch], None],
        *,
        duration_lookup: Callable[[str], float | None] | None = None,
        wall_clock: Callable[[], float] = time.time,
        mono_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._listener = listener
        self._duration_lookup = duration_lookup
        self._wall_clock = wall_clock
        self._mono_clock = mono_clock
        self._seq = itertools.count(1)

    @property
    def current(self) -> Utterance | None:
        return self._inner.current

    def play(self, utterance: Utterance) -> None:
        # Play FIRST: if the backend raises, no dispatch happened and no event is emitted.
        self._inner.play(utterance)
        duration_ms = self._duration(utterance.clip_id)
        if self._duration_lookup is not None and duration_ms is None:
            # The bank-backed backends degrade per-clip: a missing/sha-bad/undecodable clip
            # is SKIPPED by play() (logged no-op), and the same bank drives this duration
            # lookup — so no duration means no audio actually sounded. Never broadcast a
            # dispatch for silence (PR #519 review): the tablet would speak a clip the
            # in-ear coach never played.
            _log.warning(
                "voice: suppressing dispatch event for %s — clip absent from the loaded bank",
                utterance.clip_id,
            )
            return
        dispatch = VoiceDispatch(
            seq=next(self._seq),
            clip_id=utterance.clip_id,
            kind=utterance.kind,
            urgency=utterance.urgency,
            register=utterance.register,
            corner=utterance.corner,
            text=utterance.text,
            duration_ms=duration_ms,
            t_wall_ms=self._wall_clock() * 1000.0,
            t_mono_ms=self._mono_clock() * 1000.0,
        )
        try:
            self._listener(dispatch)
        except Exception:  # noqa: BLE001 — the tap must never break the audio path
            _log.exception("voice: dispatch listener failed for %s", utterance.clip_id)

    def cancel(self) -> None:
        self._inner.cancel()

    def close(self) -> None:
        self._inner.close()

    def _duration(self, clip_id: str) -> float | None:
        if self._duration_lookup is None:
            return None
        try:
            return self._duration_lookup(clip_id)
        except Exception:  # noqa: BLE001 — duration is advisory metadata only
            _log.exception("voice: duration lookup failed for %s", clip_id)
            return None
