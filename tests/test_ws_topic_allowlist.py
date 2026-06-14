"""WS topic allow-list integrity (EPIC #154 Part D, step 1).

`external_protocol.KNOWN_TOPICS` is the allow-list `validate_inbound` consults for
`state.subscribe`. Fan-out itself is topic-agnostic (`_broadcast_external`), so an
omission here does NOT drop frames — it just makes a real, produced topic
*unsubscribable*. That is the "produced-but-unsubscribable" sibling of the #170
handshake bug: `coaching.snapshot` and `setup.active` were emitted by the trainer
yet a client could never legitimately subscribe to them.

These tests keep the allow-list honest:
1. `validate_inbound` accepts a subscribe to every `KNOWN_TOPICS` entry and rejects
   an unknown one.
2. **Drift-guard** — every topic the Lua side actually publishes (via
   `publishTopic`, whether an inline string literal or a `local TOPIC = "..."`
   constant) MUST be in `KNOWN_TOPICS`. This fails CI the moment a new producer is
   wired without its allow-list entry — the structural fix for the recurring
   "forgot the allow-list" pitfall.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from tools.ai_sidecar.external_protocol import (
    ENVELOPE_KEY,
    ENVELOPE_VERSION,
    KNOWN_TOPICS,
    TYPE_KEY,
    validate_inbound,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
LUA_SRC = REPO / "src" / "ac_copilot_trainer"

# A call site: `<recv>.publishTopic(<first-arg>` — the leading dot excludes the
# `function M.publishTopic(topic, payload)` definition (no dot) and the
# `type(wsBridge.publishTopic)` guard (no `(` after the name).
_CALL_RE = re.compile(r"\.publishTopic\s*\(\s*([^\s,)]+)")


def _produced_topics() -> tuple[dict[str, str], list[str]]:
    """Return ({topic: 'file'} , [unresolved-call descriptions]).

    Resolves the first argument of each `.publishTopic(` CALL to a string literal:
    direct ('"coaching.snapshot"') or via a `local NAME = "..."` / `NAME = "..."`
    assignment in the same file (covers coaching_publisher's `TOPIC` constant).
    A first-arg that cannot be resolved to a literal is reported as unresolved so
    the guard fails loud rather than silently passing a producer it can't verify.
    """
    topics: dict[str, str] = {}
    unresolved: list[str] = []
    for f in sorted(LUA_SRC.rglob("*.lua")):
        text = f.read_text(encoding="utf-8")
        for m in _CALL_RE.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.start())
            line = text[line_start : line_end if line_end != -1 else len(text)]
            if "function" in line:  # the definition, not a call
                continue
            if "--" in line[: m.start() - line_start]:  # commented-out call (Lua --)
                continue
            arg = m.group(1)
            if arg[:1] in ("'", '"'):
                topics[arg.strip("'\"")] = f.name
                continue
            vm = re.search(rf"\b{re.escape(arg)}\s*=\s*['\"]([^'\"]+)['\"]", text)
            if vm:
                topics[vm.group(1)] = f.name
            else:
                unresolved.append(
                    f"{f.name}: publishTopic({arg}) — first arg not a resolvable string literal"
                )
    return topics, unresolved


@pytest.mark.parametrize("topic", sorted(KNOWN_TOPICS))
def test_subscribe_accepts_every_known_topic(topic: str):
    frame = {ENVELOPE_KEY: ENVELOPE_VERSION, TYPE_KEY: "state.subscribe", "topics": [topic]}
    assert validate_inbound(frame) is None


def test_subscribe_rejects_unknown_topic():
    frame = {
        ENVELOPE_KEY: ENVELOPE_VERSION,
        TYPE_KEY: "state.subscribe",
        "topics": ["definitely_not_a_real_topic"],
    }
    err = validate_inbound(frame)
    assert err is not None and "unknown topic" in err


def test_formerly_unsubscribable_produced_topics_are_now_allowed():
    # The two topics the trainer already produced but a client could not subscribe to.
    assert "coaching.snapshot" in KNOWN_TOPICS
    assert "setup.active" in KNOWN_TOPICS


def test_every_produced_topic_is_in_known_topics():
    """Drift-guard: no producer may publish a topic that isn't subscribable."""
    produced, unresolved = _produced_topics()
    assert not unresolved, (
        "publishTopic call(s) whose topic could not be statically resolved — "
        f"extend the guard or use a literal/const: {unresolved}"
    )
    assert produced, "expected to find at least one publishTopic producer in the Lua sources"
    missing = sorted(t for t in produced if t not in KNOWN_TOPICS)
    assert not missing, (
        "topic(s) produced by Lua but absent from KNOWN_TOPICS (forgot the allow-list — "
        f"add to external_protocol.KNOWN_TOPICS): {missing} "
        f"(produced set: {sorted(produced)})"
    )
