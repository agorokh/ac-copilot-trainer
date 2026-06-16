"""L1.5 in-sim WS-sequence probe (EPIC #154 Part E — verifies the #180 producer pipeline).

The L1.5 layer asserts on the **message sequence** the trainer emits during a drive — not pixels.
It consumes the trainer's published WS frames (live tap via `ai_sidecar.harness_client`, or a
recorded JSONL file) and checks the declared-topic contract:

  * the CONTINUOUS streams (connection / tire_temps / coaching.snapshot) are present — the
    "pipeline alive" check, required in any driving window; and
  * the lifecycle ordering invariant holds: the first ``session`` precedes the first ``lap``
    (the #182 contract — no ``lap`` frame may precede a ``session``), asserted whenever a
    ``session`` is observed.

Only ``type == "state.snapshot"`` frames (the `ws_bridge.publishTopic` envelope) are counted, so a
diagnostic/client frame that merely carries a ``topic`` key cannot satisfy the contract.

CONDITIONAL topics are present only under specific circumstances, so a short or mid-session tap may
legitimately miss them — this is NOT a producer fault:
  * ``session`` — an EVENT (session start / track-car change / reconnect). A tap that connects
    mid-session misses it: sidecar fan-out is topic-agnostic and `publishSessionIfChanged`
    suppresses the same key until a reconnect/change, so subscribing does not replay it. To assert
    ``session`` / session-before-lap, tap from session start (``--strict --wait-lap``) or, as a
    future enhancement, have the trainer re-emit ``session`` to late-attaching subscribers.
  * ``lap``   — needs a lap boundary in the window (use ``--wait-lap``).
  * ``delta`` — needs a reference lap (``state.bestSortedTrace``) AND an s/f-aligned clock, so it is
    ALWAYS reported as a note (never required) — requiring it would false-fail a healthy
    no-reference session.

By default session/lap are informational notes; ``strict_lifecycle=True`` (the controlled tap from
session start) requires session + lap present and strictly enforces session-before-lap.

`evaluate_sequence()` is a **pure function**, unit-tested off-sim with synthetic frame streams.
The live tap (`tap_frames` / ``__main__``) is **gated**: it needs AC running and a car on track,
so it is exercised in-sim on a real (operator-launched) drive, not in CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field

# Producer-snapshot envelope type (ws_bridge.publishTopic). Only these frames count.
STATE_SNAPSHOT_TYPE = "state.snapshot"

# Topics that stream CONTINUOUSLY whenever a car is on track — required presence in any driving
# window (the "pipeline alive" check).
DEFAULT_CONTINUOUS_TOPICS: tuple[str, ...] = (
    "connection",  # ~1 Hz heartbeat
    "tire_temps",  # ~5 Hz per-wheel temps
    "coaching.snapshot",  # continuous coaching stream
)

# Lifecycle topics carrying the ordering contract — informational notes by default, required under
# strict_lifecycle. `delta` is deliberately EXCLUDED: it needs a reference lap + an s/f-aligned
# clock, so it is always a note (requiring it would false-fail a healthy no-reference session).
STRICT_LIFECYCLE_TOPICS: tuple[str, ...] = ("session", "lap")

# Everything the live tap subscribes to (`setup.active` is event-driven and never required).
ALL_TAP_TOPICS: tuple[str, ...] = (
    "connection",
    "session",
    "lap",
    "delta",
    "tire_temps",
    "coaching.snapshot",
)

_CONTINUOUS_SET = frozenset(DEFAULT_CONTINUOUS_TOPICS)


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
    """Return ``(index, topic)`` for each ``state.snapshot`` frame with a string ``topic`` key."""
    out: list[tuple[int, str]] = []
    for i, f in enumerate(frames):
        if not isinstance(f, dict) or f.get("type") != STATE_SNAPSHOT_TYPE:
            continue
        topic = f.get("topic")
        if isinstance(topic, str):
            out.append((i, topic))
    return out


def _conditional_note(topic: str, first_index: dict[str, int], counts: dict[str, int]) -> str:
    if topic in first_index:
        return f"{topic}: count={counts[topic]}"
    return f"{topic}: not in window (conditional: event / boundary / reference-lap)"


def evaluate_sequence(
    frames: list[dict],
    *,
    continuous_topics: tuple[str, ...] = DEFAULT_CONTINUOUS_TOPICS,
    strict_lifecycle: bool = False,
) -> SequenceResult:
    """Evaluate a frame stream against the L1.5 contract (pure).

    Default "window" mode: require the continuous streams, and assert session-before-lap only
    when a ``session`` is observed. session/lap/delta are reported as notes — a mid-session tap
    legitimately misses the ``session`` event, a lap boundary, or a reference lap for ``delta``.

    ``strict_lifecycle=True`` (controlled tap from session start): also require ``session`` and
    ``lap`` present and strictly enforce session-before-lap. ``delta`` stays a note in both modes.
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

    # 2) session / lap: required under strict_lifecycle; otherwise informational notes.
    for topic in STRICT_LIFECYCLE_TOPICS:
        if strict_lifecycle:
            checks.append(_presence(topic))
        else:
            notes.append(_conditional_note(topic, first_index, counts))

    # 3) delta: always a note (needs a reference lap + an s/f-aligned clock) — never required.
    notes.append(_conditional_note("delta", first_index, counts))

    # 4) ordering: the first `session` precedes the first `lap` (#182 lifecycle contract).
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
                "event that fired before connect); use --strict --wait-lap from session start to "
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


def _is_snapshot(frame: dict, topic: str) -> bool:
    return (
        isinstance(frame, dict)
        and frame.get("type") == STATE_SNAPSHOT_TYPE
        and frame.get("topic") == topic
    )


async def tap_frames(
    url: str = "ws://127.0.0.1:8765",
    *,
    seconds: float = 20.0,
    wait_for_lap: bool = False,
    settle_timeout: float = 120.0,
    lap_timeout: float = 180.0,
) -> list[dict]:
    """Tap the sidecar and return the frames received (live; needs AC driving).

    Default: a fixed ``seconds`` window. With ``wait_for_lap=True`` the tap first waits (up to
    ``settle_timeout``) for the car to be on track, then waits (up to ``lap_timeout``) for a ``lap``
    frame — so a slow real lap is captured rather than false-failing a fixed 20 s window.

    Always closes the client (try/finally) and fails fast on a missing hello handshake. Imported
    lazily so the pure evaluator has no hard dependency on the sidecar client.
    """
    from tools.ai_sidecar.harness_client import HarnessClient

    hc = HarnessClient(url)
    try:
        await hc.connect(retries=40, retry_delay=0.25)
        if await hc.hello(timeout=10) is None:
            raise RuntimeError("sidecar hello handshake timed out (no hello_ack)")
        await hc.subscribe(list(ALL_TAP_TOPICS))
        if wait_for_lap:
            # Wait for the car to be on track (any continuous topic), then for a lap boundary.
            # `wait_for` consumes from a separate queue; `hc.frames` still accrues the full stream.
            await hc.wait_for(
                lambda f: any(_is_snapshot(f, t) for t in _CONTINUOUS_SET),
                timeout=settle_timeout,
            )
            await hc.wait_for(lambda f: _is_snapshot(f, "lap"), timeout=lap_timeout)
        else:
            await asyncio.sleep(seconds)
        return list(hc.frames)
    finally:
        await hc.close()


async def _amain(args: argparse.Namespace) -> int:
    frames = await tap_frames(seconds=args.seconds, wait_for_lap=args.wait_lap)
    result = evaluate_sequence(frames, strict_lifecycle=args.strict)
    print(result.summary())
    return 0 if result.ok else 1


def _main() -> int:
    parser = argparse.ArgumentParser(description="L1.5 in-sim WS-sequence probe")
    parser.add_argument(
        "--seconds", type=float, default=20.0, help="fixed tap window (window mode)"
    )
    parser.add_argument(
        "--wait-lap",
        action="store_true",
        help="wait for the car on track, then for a lap boundary (slow laps), not a fixed window",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="require session + lap and enforce session→lap ordering (tap from session start)",
    )
    return asyncio.run(_amain(parser.parse_args()))


if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Direct invocation (`python tools/ac_harness/sequence_probe.py`) puts tools/ac_harness on
    # sys.path, not the repo root — so the lazy `from tools...` import would fail on a fresh clone.
    # Put the repo root first so both `python <file>` and `python -m ...` work.
    _repo_root = str(Path(__file__).resolve().parents[2])
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    raise SystemExit(_main())
