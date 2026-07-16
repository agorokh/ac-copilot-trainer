"""Sidecar-computed race status for the ``race.status`` topic (#531 Part D remainder).

The tablet dashboard's "fuel as a decision" and predicted-lap slots need clean first-class
fields; before this module they lived only inside a race-management cue ``detail`` (fuel) or
client-side (burn from lap boundaries). The tracker fuses the three streams the sidecar already
sees — ``telemetry_tick`` (fuel level, via :meth:`RaceManagementObserver.fuel_status`), the Lua
``delta`` topic (gap to reference), and the Lua ``lap`` topic (stint best) — into one low-rate
payload:

``{fuel_l, fuel_per_lap_l, laps_remaining, fuel_per_lap_source, samples,
   target_laps_remaining?, lap?, best_lap_ms?, last_lap_ms?, delta_s?, predicted_lap_ms?}``

Honesty rules (the #531 sentinel discipline): a field is present only when measured this
session; ``predicted_lap_ms`` (= stint best + current delta) requires BOTH a stint best and a
FRESH delta — a stale delta drops the prediction rather than freezing it. Pure stdlib.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: A delta older than this cannot anchor a predicted lap (the 10 Hz producer paused/stopped).
DELTA_FRESH_S = 5.0


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


@dataclass
class RaceStatusTracker:
    """Accumulates the latest fuel/lap/delta state and serializes ``race.status`` payloads."""

    clock: Callable[[], float] = time.monotonic
    _fuel: dict[str, Any] | None = None
    _delta_s: float | None = None
    _delta_at: float = field(default=float("-inf"))
    _reference_lap_ms: float | None = None
    _best_lap_ms: float | None = None
    _last_lap_ms: float | None = None
    _lap: int | None = None
    _session_key: tuple[str, str, str] | None = None
    _last_published: tuple[Any, ...] | None = None

    def reset(self) -> None:
        self._fuel = None
        self._delta_s = None
        self._delta_at = float("-inf")
        self._reference_lap_ms = None
        self._best_lap_ms = None
        self._last_lap_ms = None
        self._lap = None
        self._last_published = None

    def note_fuel(self, status: dict[str, Any] | None, *, channel_live: bool = False) -> None:
        """Latest clean fuel fields (from ``RaceManagementObserver.fuel_status``).

        ``None`` with ``channel_live=False`` keeps the previous measurement (the frame simply
        lacked the fuel channel — unknown, not empty). ``None`` with ``channel_live=True``
        means the channel IS reporting but the burn state reset (lap rollback / refuel), so the
        previous stint's numbers are stale and must be dropped, not frozen (Codex on PR #615).
        """
        if isinstance(status, dict) and status:
            self._fuel = dict(status)
        elif status is None and channel_live:
            self._fuel = None

    def note_delta(self, payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            return
        delta = _num(payload.get("delta_s"))
        if delta is not None:
            self._delta_s = delta
            self._delta_at = self.clock()
            # The delta's OWN baseline (the active reference trace's lap time), when the
            # producer carries it. Stored with the delta — the two are meaningless apart.
            self._reference_lap_ms = _num(payload.get("reference_lap_ms"))

    def note_session(self, payload: dict[str, Any] | None) -> None:
        """Reset the fusion only on a REAL identity change. The Lua bridge re-emits the
        current ``session`` snapshot to late subscribers, so a frame alone is not a change
        (Codex on PR #615) — compare car/track/session before dropping state."""
        if not isinstance(payload, dict):
            return
        key = (
            str(payload.get("car_id") or ""),
            str(payload.get("track_id") or ""),
            str(payload.get("session_index") if payload.get("session_index") is not None else ""),
        )
        if self._session_key is not None and key != self._session_key:
            self.reset()
        self._session_key = key

    def note_lap(self, payload: dict[str, Any] | None) -> None:
        if not isinstance(payload, dict):
            return
        best = _num(payload.get("best_lap_ms"))
        if best is not None and best > 0:
            self._best_lap_ms = best
        last = _num(payload.get("last_lap_ms"))
        if last is not None and last > 0:
            self._last_lap_ms = last
        lap = _num(payload.get("lap"))
        if lap is not None and lap >= 0:
            self._lap = int(lap)

    def snapshot(self, now: float | None = None) -> dict[str, Any] | None:
        """The current ``race.status`` payload, or ``None`` when nothing is measured yet."""
        if now is None:
            now = self.clock()
        out: dict[str, Any] = {}
        if self._fuel:
            out.update(self._fuel)
        if self._lap is not None:
            out["lap"] = self._lap
        if self._best_lap_ms is not None:
            out["best_lap_ms"] = self._best_lap_ms
        if self._last_lap_ms is not None:
            out["last_lap_ms"] = self._last_lap_ms
        delta_fresh = self._delta_s is not None and (now - self._delta_at) <= DELTA_FRESH_S
        if delta_fresh:
            out["delta_s"] = self._delta_s
            if self._reference_lap_ms is not None and self._reference_lap_ms > 0:
                # Predicted lap = the delta's OWN reference lap time + the live gap. The stint
                # best is the WRONG baseline when an imported/faster reference drives the delta
                # (Codex on PR #615) — so the prediction exists only when the producer carries
                # `reference_lap_ms` with the delta. Suppressed (never guessed) otherwise.
                predicted = self._reference_lap_ms + self._delta_s * 1000.0
                if predicted > 0:
                    out["predicted_lap_ms"] = round(predicted)
        return out or None

    def snapshot_if_changed(self, now: float | None = None) -> dict[str, Any] | None:
        """Like :meth:`snapshot`, but ``None`` when the payload is identical to the last one this
        method returned — the publish path stays quiet while nothing moves (pit box, menu)."""
        snap = self.snapshot(now)
        if snap is None:
            return None
        key = tuple(sorted(snap.items()))
        if key == self._last_published:
            return None
        self._last_published = key
        return snap
