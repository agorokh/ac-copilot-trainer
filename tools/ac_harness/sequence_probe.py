"""L1.5 in-sim WS-sequence probe (EPIC #154 Part E, issue #190).

The L1.5 layer asserts on the **message sequence** the trainer emits during a drive — not pixels.
It consumes the trainer's published WS frames (live tap via `ai_sidecar.harness_client`, or a
recorded JSONL file) and checks the declared-topic contract:

  * the CONTINUOUS streams (connection / tire_temps / coaching.snapshot) are present — the
    "pipeline is alive" check, required in any driving window; and
  * the lifecycle ordering invariant holds: the first ``session`` precedes the first ``lap``
    (the #182 contract — no ``lap`` frame may precede a ``session``), asserted whenever a
    ``session`` is observed.

CONDITIONAL topics (``session`` / ``lap`` / ``delta``) are only present under specific
circumstances — ``session`` is an event that fires at session start (a mid-session tap misses it),
``lap`` needs a lap boundary in the window, and ``delta`` needs a reference lap + an s/f-aligned
clock. By default these are reported as informational notes, NOT failures, so an ad-hoc mid-session
tap doesn't spuriously fail. Pass ``strict_lifecycle=True`` for the controlled L1.5 run that taps
from session start, where their presence + strict session→lap ordering ARE required.

Published topic frames are shaped ``{v, type="state.snapshot", topic, payload}`` (see
`ws_bridge.publishTopic`), so frames are filtered by their top-level ``topic`` key.

`evaluate_sequence()` is a **pure function**, unit-tested off-sim with synthetic frame streams.
The live tap (`tap_frames` / ``__main__``) is **gated**: it needs AC running and a car on track,
so it is exercised in-sim on a real (operator-launched) drive, not in CI.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

# Topics that stream CONTINUOUSLY whenever a car is on track — required presence in any driving
# window (the "pipeline alive" check).
DEFAULT_CONTINUOUS_TOPICS: tuple[str, ...] = (
    "connection",  # ~1 Hz heartbeat
    "tire_temps",  # ~5 Hz per-wheel temps
    "coaching.snapshot",  # continuous coaching stream
)

# CONDITIONAL topics — present only under specific circumstances, so a short or mid-session tap may
# legitimately miss them (NOT a producer fault): `session` is an EVENT (session start / track-car
# change / reconnect — a tap connecting mid-session misses it); `lap` needs a lap boundary in the
# window; `delta` needs a reference lap to exist AND an s/f-aligned clock (see deltaRefStale).
# Reported as informational notes by default; promoted to required checks under strict_lifecycle.
LIFECYCLE_TOPICS: tuple[str, ...] = ("session", "lap", "delta")

# `setup.active` is event-driven (only on a setup change) and never required for a baseline lap.
# Everything the live tap subscribes to:
ALL_TAP_TOPICS: tuple[str, ...] = DEFAULT_CONTINUOUS_TOPICS + LIFECYCLE_TOPICS


@dataclass
class Check:
    """One assertion in the sequence contract."""

    name: str
    ok: bool
    detail: str


@dataclass
class SequenceResult:
    """Outcome of evaluating a frame stream against the L1.5 contract."""

    ok: bool
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        head = "PASS" if self.ok else "FAIL"
        lines = [f"{head}: L1.5 sequence probe ({len(self.checks)} checks)"]
        for c in self.checks:
            lines.append(f"  [{'ok' if c.ok else 'XX'}] {c.name} — {c.detail}")
        for n in self.notes:
            lines.append(f"  (i) {n}")
        return "\n".join(lines)


def _ordered_topics(frames: list[dict]) -> list[tuple[int, str]]:
    """Return ``(index, topic)`` for each frame with a string ``topic`` key, in arrival order."""
    out: list[tuple[int, str]] = []
    for i, f in enumerate(frames):
        if not isinstance(f, dict):
            continue
        topic = f.get("topic")
        if isinstance(topic, str):
            out.append((i, topic))
    return out


def evaluate_sequence(
    frames: list[dict],
    *,
    continuous_topics: tuple[str, ...] = DEFAULT_CONTINUOUS_TOPICS,
    strict_lifecycle: bool = False,
) -> SequenceResult:
    """Evaluate a frame stream against the L1.5 contract (pure).

    Default "window" mode: require the continuous streams, and assert session-before-lap only
    when a ``session`` is observed. Lifecycle topics are reported as notes — a mid-session tap
    legitimately misses the ``session`` event, a lap boundary, or a reference lap for ``delta``.

    ``strict_lifecycle=True`` (controlled tap from session start): also require ``session``,
    ``lap``, ``delta`` present and strictly enforce session-before-lap.
    """
    ordered = _ordered_topics(frames)
    first_index: dict[str, int] = {}
    counts: dict[str, int] = {}
    for i, topic in ordered:
        counts[topic] = counts.get(topic, 0) + 1
        first_index.setdefault(topic, i)

    checks: list[Check] = []
    notes: list[str] = []

    def _presence(topic: str) -> Check:
        present = topic in first_index
        return Check(
            f"present:{topic}",
            present,
            f"count={counts.get(topic, 0)}" if present else "never seen",
        )

    # 1) continuous streams must be present (pipeline alive).
    for topic in continuous_topics:
        checks.append(_presence(topic))

    # 2) lifecycle topics: required only under strict_lifecycle; otherwise informational.
    for topic in LIFECYCLE_TOPICS:
        if strict_lifecycle:
            checks.append(_presence(topic))
        elif topic in first_index:
            notes.append(f"{topic}: count={counts[topic]}")
        else:
            notes.append(f"{topic}: not in window (conditional: event / boundary / reference-lap)")

    # 3) ordering: the first `session` precedes the first `lap` (#182 lifecycle contract).
    if "session" in first_index and "lap" in first_index:
        ok = first_index["session"] < first_index["lap"]
        checks.append(
            Check(
                "order:session-before-lap",
                ok,
                f"session@{first_index['session']} lap@{first_index['lap']}",
            )
        )
    elif "lap" in first_index and "session" not in first_index:
        # A lap with no session in the window is almost always a mid-session tap (the session event
        # fired before we connected), NOT a contract violation — so it fails only in strict mode.
        if strict_lifecycle:
            checks.append(Check("order:session-before-lap", False, "lap emitted with no session"))
        else:
            notes.append(
                "lap seen without session — tap likely started mid-session (session is an "
                "event that fired before connect); use strict_lifecycle from session start to "
                "assert session→lap ordering"
            )

    return SequenceResult(ok=all(c.ok for c in checks), checks=checks, notes=notes, counts=counts)


def frames_from_jsonl(path: str) -> list[dict]:
    """Load a recorded frame stream (one JSON object per line). Blank/invalid lines are skipped."""
    frames: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                frames.append(obj)
    return frames


async def tap_frames(url: str = "ws://127.0.0.1:8765", *, seconds: float = 20.0) -> list[dict]:
    """Tap the sidecar for ``seconds`` and return the frames received (live; needs AC driving).

    Imported lazily so the pure evaluator has no hard dependency on the sidecar client.
    """
    from tools.ai_sidecar.harness_client import HarnessClient

    hc = HarnessClient(url)
    await hc.connect(retries=40, retry_delay=0.25)
    await hc.hello(timeout=10)
    await hc.subscribe(list(ALL_TAP_TOPICS))
    # Frames accumulate in hc.frames via the client's background recv task; wait the window out.
    await asyncio.sleep(seconds)
    frames = list(hc.frames)
    await hc.close()
    return frames


async def _main() -> int:
    frames = await tap_frames(seconds=20.0)
    result = evaluate_sequence(frames)
    print(result.summary())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
