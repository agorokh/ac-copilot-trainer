"""L1.5 in-sim WS-sequence probe (EPIC #154 Part E, issue #190).

The L1.5 layer asserts on the **message sequence** the trainer emits during a drive — not pixels.
It consumes the trainer's published WS frames (live tap via `ai_sidecar.harness_client`, or a
recorded JSONL file) and checks the declared-topic contract:

  * every declared producer topic appears at least once during the drive, and
  * the lifecycle ordering invariant holds: the first ``session`` precedes the first ``lap``
    (the #182 contract — no ``lap`` frame may precede a ``session``).

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

# The declared producer topics whose presence we assert during a drive. `setup.active` is
# event-driven (only on a setup change) so it is NOT required for a baseline lap; the other six
# should all appear on any normal driving session.
DEFAULT_REQUIRED_TOPICS: tuple[str, ...] = (
    "connection",
    "session",
    "lap",
    "delta",
    "tire_temps",
    "coaching.snapshot",
)


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
    counts: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        head = "PASS" if self.ok else "FAIL"
        lines = [f"{head}: L1.5 sequence probe ({len(self.checks)} checks)"]
        for c in self.checks:
            lines.append(f"  [{'ok' if c.ok else 'XX'}] {c.name} — {c.detail}")
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
    required_topics: tuple[str, ...] = DEFAULT_REQUIRED_TOPICS,
) -> SequenceResult:
    """Evaluate a frame stream against the L1.5 declared-topic + ordering contract (pure)."""
    ordered = _ordered_topics(frames)
    first_index: dict[str, int] = {}
    counts: dict[str, int] = {}
    for i, topic in ordered:
        counts[topic] = counts.get(topic, 0) + 1
        first_index.setdefault(topic, i)

    checks: list[Check] = []

    # 1) presence: each required producer topic appears at least once.
    for topic in required_topics:
        present = topic in first_index
        checks.append(
            Check(
                f"present:{topic}",
                present,
                f"count={counts.get(topic, 0)}" if present else "never seen",
            )
        )

    # 2) ordering: the first `session` precedes the first `lap` (no lap without a preceding
    #    session — the #182 lifecycle contract). Only assertable when a `lap` was emitted; absence
    #    of `lap` is already flagged by the presence check above.
    if "lap" in first_index:
        if "session" not in first_index:
            checks.append(Check("order:session-before-lap", False, "lap emitted with no session"))
        else:
            ok = first_index["session"] < first_index["lap"]
            checks.append(
                Check(
                    "order:session-before-lap",
                    ok,
                    f"session@{first_index['session']} lap@{first_index['lap']}",
                )
            )

    return SequenceResult(ok=all(c.ok for c in checks), checks=checks, counts=counts)


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
    await hc.subscribe(list(DEFAULT_REQUIRED_TOPICS))
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
