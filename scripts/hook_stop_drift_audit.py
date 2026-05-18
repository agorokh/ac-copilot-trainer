#!/usr/bin/env python3
"""Stop hook: deterministic memory-drift audit (advisory).

Closes the conversational-agent gap in the issue-#115 memory-enforcement
substrate. The PreToolUse gate (``hook_memory_gate.py``) enforces memory
grounding for **file mutations**. It has no surface to fire on conversational
responses (research, planning, synthesis) — the agent generates prose,
returns, and the gate never sees it.

Council consensus (Mistral + Gemini, 2026-05-17 post-#116 review):
  * Mistral: log compliance feedback loop. The substrate enforces tools, not
    reasoning. The honest extension is a measurable audit of conversational
    grounding so operators can see drift before they trust the substrate to
    cover their fleet.
  * Gemini: Stop hook citation audit with "super-ego" feedback into the next
    session's prefetch. The NEXT SessionStart reads the previous drift_score
    and warns the agent in turn-1 stdout.

This script implements that pattern. **It is advisory, not blocking.** Stop
hooks blocking is too high-risk for false positives on legitimate short or
docs-only sessions; the template invariant
(``tests/test_hook_scripts.py::test_invariant_stop_hooks_are_command_only``)
asserts Stop hooks are command-only and they must always exit 0.

Behavior:
  * Reads ``transcript_path`` from the Stop hook JSON payload on stdin
    (Claude Code 2026 hook contract).
  * Parses the transcript JSONL — extracts assistant messages.
  * Filters to **substantive** messages (>=30 words). Trivial responses ("ok",
    "yes", "done") are skipped — they don't need memory citation.
  * For each substantive message, computes whether it cites substrate-derived
    content based on:
      - Presence of substrate-derived tokens (from
        ``.scratch/.last_memory_query`` response_body).
      - Mentions of vault paths (``docs/01_Vault/``).
      - Mentions of substrate MCP tool calls
        (``mcp__agentic-memory__query_knowledge_graph``).
  * Aggregates to a **drift_score** in ``[0.0, 1.0]`` -- higher is worse.
    ``drift_score = 1 - (cited_substantive / total_substantive)``.
  * Appends one record per session to ``.scratch/memory_audit.jsonl``.
  * Stdout: one advisory line surfaced to the operator at session-end.

The NEXT session's ``hook_session_start_memory_prefetch.py`` reads the tail
of the audit log; when prior drift_score exceeds the warning threshold, it
prepends a WARNING line to turn-1 stdout. That is the only feedback loop
that exists in 2026 Claude Code architecture without a PreResponse hook.

Fail-open contract:
  * Missing / malformed transcript_path -> log "no_transcript" record and
    exit 0.
  * <3 substantive responses -> too short to score meaningfully -> log
    "session_too_short" with details and exit 0.
  * No ``.last_memory_query`` lockfile -> no substrate context to score
    against -> log "no_substrate" and exit 0.
  * Any unexpected exception -> exit 0 (Stop hooks must never block).

Environment:
  * ``CLAUDE_MEMORY_DRIFT_AUDIT=0`` -- skip audit (kill switch).
  * ``CLAUDE_MEMORY_DRIFT_AUDIT_MIN_WORDS`` -- substantive-message threshold
    (default 30).
  * ``CLAUDE_MEMORY_DRIFT_AUDIT_MIN_SAMPLE`` -- minimum substantive count
    required to score (default 3).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Tunable knobs (env-overridable).
_DEFAULT_MIN_WORDS = 30
_DEFAULT_MIN_SAMPLE = 3
_TOKEN_MIN_LEN = 4  # longer than the gate's 3 -- conversation needs more substance.
_TOKEN_OVERLAP_MIN = 2  # require multiple token hits to reduce stop-word false positives
_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "have",
        "they",
        "been",
        "were",
        "when",
        "your",
        "more",
        "some",
        "what",
        "there",
        "their",
        "about",
        "which",
        "would",
        "could",
        "should",
        "will",
        "than",
        "then",
        "them",
        "these",
        "also",
        "only",
        "into",
        "such",
        "even",
        "most",
        "many",
        "each",
        "both",
        "other",
        "where",
        "while",
    }
)

# Citation signal patterns. Any of these in a substantive message counts as
# "this message cited substrate-derived content" (boolean per-message; we
# don't try to weight them).
_CITATION_HEURISTICS = (
    "docs/01_Vault/",
    "docs/00_Core/",
    "mcp__agentic-memory__",
    ".scratch/.last_memory_query",
    "ops/memory_manifest.yml",
    "MEMORY_CONTRACT.md",
    "memory-three-tiers.md",
)


def _enabled() -> bool:
    val = os.environ.get("CLAUDE_MEMORY_DRIFT_AUDIT")
    if val is None:
        return True
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    try:
        v = int(raw)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _repo_root() -> Path:
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if arg:
            return Path(arg).expanduser().resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_payload() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_lock(root: Path) -> dict | None:
    """Return ``.scratch/.last_memory_query`` payload, or None."""
    path = root / ".scratch" / ".last_memory_query"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _substrate_tokens(lock: dict) -> set[str]:
    """Extract substantive tokens from Tier-3 ``response_body`` only.

    Prompt and workspace names are excluded so generic turn text (branch names,
    issue numbers) does not inflate cited counts (Codex review feedback).
    """
    out: set[str] = set()
    v = lock.get("response_body")
    if isinstance(v, str):
        for tok in _TOKEN_SPLIT_RE.split(v):
            tok = tok.lower()
            if len(tok) >= _TOKEN_MIN_LEN and tok not in _STOP_WORDS:
                out.add(tok)
    return out


def _extract_assistant_text(message: dict) -> str:
    """Pull plain text from an assistant transcript message.

    Claude Code transcripts (2026) are JSONL where each line is a record.
    Assistant messages have ``type: "assistant"`` and a ``message`` dict whose
    ``content`` can be a string or a list of content blocks (text + tool_use).
    """
    if message.get("type") != "assistant":
        return ""
    msg = message.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            txt = block.get("text")
            if isinstance(txt, str):
                parts.append(txt)
    return "\n".join(parts)


def _is_substantive(text: str, min_words: int) -> bool:
    if not text:
        return False
    word_count = sum(1 for _ in re.finditer(r"\b\w+\b", text))
    return word_count >= min_words


def _is_cited(text: str, substrate_tokens: set[str]) -> bool:
    """True if the response shows any substrate citation signal."""
    if not text:
        return False
    lower = text.lower()
    if any(needle.lower() in lower for needle in _CITATION_HEURISTICS):
        return True
    if substrate_tokens:
        msg_tokens = {
            tok
            for tok in _TOKEN_SPLIT_RE.split(lower)
            if len(tok) >= _TOKEN_MIN_LEN and tok not in _STOP_WORDS
        }
        if len(substrate_tokens & msg_tokens) >= _TOKEN_OVERLAP_MIN:
            return True
    return False


def _parse_transcript(path: Path) -> list[str]:
    """Return assistant message texts from the transcript JSONL.

    Each line is parsed independently; malformed lines are skipped. We do not
    require a specific schema beyond ``type: assistant`` and a ``content``
    list of text blocks -- Claude Code may evolve the format.
    """
    out: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(record, dict):
                    text = _extract_assistant_text(record)
                    if text:
                        out.append(text)
    except OSError:
        return []
    return out


def _audit_record(reason: str, *, session_id: str = "", **extra: object) -> dict:
    rec: dict = {
        "timestamp_utc": _now_iso(),
        "reason": reason,
    }
    if session_id:
        rec["session_id"] = session_id
    rec.update(extra)
    return rec


_AUDIT_MAX_BYTES = 1_048_576  # 1 MiB soft cap; retain tail on append
_AUDIT_RETAIN_BYTES = 524_288
_AUDIT_TAIL_BYTES = 65_536


def _append_audit(root: Path, record: dict) -> None:
    scratch = root / ".scratch"
    try:
        scratch.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    path = scratch / "memory_audit.jsonl"
    try:
        if path.is_file() and path.stat().st_size > _AUDIT_MAX_BYTES:
            with path.open("rb") as f:
                f.seek(-_AUDIT_RETAIN_BYTES, os.SEEK_END)
                f.readline()  # align to JSONL line boundary
                tail = f.read()
            tmp_path = path.with_suffix(".jsonl.tmp")
            tmp_path.write_bytes(tail)
            os.replace(tmp_path, path)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _read_audit_tail_text(path: Path) -> str:
    """Read the tail of the audit log without loading unbounded history."""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > _AUDIT_TAIL_BYTES:
                f.seek(-_AUDIT_TAIL_BYTES, os.SEEK_END)
                f.readline()
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _session_already_scored(root: Path, session_id: str) -> bool:
    """True if this session already has a final ``scored`` row.

    Stop runs every turn; early turns may log ``session_too_short`` before the
    transcript is long enough to score. Only dedupe after a successful score.
    """
    path = root / ".scratch" / "memory_audit.jsonl"
    if not session_id or not path.is_file():
        return False
    for line in reversed(_read_audit_tail_text(path).splitlines()):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if (
            isinstance(record, dict)
            and record.get("session_id") == session_id
            and record.get("reason") == "scored"
        ):
            return True
    return False


def _append_hook_error(root: Path, detail: str) -> None:
    """Non-blocking error note for operator forensics (Qodo silent-failure feedback)."""
    scratch = root / ".scratch"
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        err = {
            "timestamp_utc": _now_iso(),
            "hook": "hook_stop_drift_audit.py",
            "detail": detail[:500],
        }
        with (scratch / "memory_drift_audit_errors.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(err) + "\n")
    except OSError:
        pass


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _summary_line(record: dict) -> str:
    """One-line operator advisory; surfaced as Stop-hook stdout."""
    reason = record.get("reason", "")
    if reason == "scored":
        ds = _safe_float(record.get("drift_score"), 0.0)
        sub = _safe_int(record.get("substantive_count"), 0)
        cited = _safe_int(record.get("cited_count"), 0)
        if ds >= 0.7:
            severity = "HIGH"
        elif ds >= 0.5:
            severity = "MEDIUM"
        else:
            severity = "LOW"
        return (
            f"memory-drift audit: drift_score={ds:.2f} ({cited}/{sub} "
            f"substantive responses cited substrate content) -- {severity}. "
            "Next session's prefetch will surface this signal."
        )
    if reason == "session_too_short":
        return (
            "memory-drift audit: session too short to score "
            f"(substantive={record.get('substantive_count', 0)}; min="
            f"{record.get('min_sample', _DEFAULT_MIN_SAMPLE)}). No signal."
        )
    if reason == "no_substrate":
        return (
            "memory-drift audit: no Tier-3 substrate context for this repo -- "
            "skipped (warn-only mode; register workspace in ops/memory_manifest.yml)."
        )
    if reason == "no_transcript":
        return (
            "memory-drift audit: transcript_path unavailable from hook payload -- "
            "skipped. (Claude Code may not have surfaced it for this session.)"
        )
    if reason == "disabled":
        return "memory-drift audit: disabled via CLAUDE_MEMORY_DRIFT_AUDIT=0."
    return f"memory-drift audit: {reason}."


def main() -> int:
    if not _enabled():
        return 0  # Silent disable -- no stdout, no log.

    root = _repo_root()
    payload = _read_payload()

    if payload.get("stop_hook_active") is True:
        return 0

    session_id_raw = payload.get("session_id") or payload.get("sessionId")
    session_id = session_id_raw if isinstance(session_id_raw, str) else ""
    if session_id and _session_already_scored(root, session_id):
        return 0

    transcript_path_raw = payload.get("transcript_path")
    if not isinstance(transcript_path_raw, str) or not transcript_path_raw:
        record = _audit_record("no_transcript", session_id=session_id)
        _append_audit(root, record)
        sys.stdout.write(_summary_line(record) + "\n")
        return 0

    transcript_path = Path(os.path.expanduser(transcript_path_raw))
    if not transcript_path.is_file():
        record = _audit_record("no_transcript", session_id=session_id, path=str(transcript_path))
        _append_audit(root, record)
        sys.stdout.write(_summary_line(record) + "\n")
        return 0

    lock = _read_lock(root)
    if not lock:
        record = _audit_record(
            "no_substrate",
            session_id=session_id,
            transcript_path=str(transcript_path),
        )
        _append_audit(root, record)
        sys.stdout.write(_summary_line(record) + "\n")
        return 0

    substrate_tokens = _substrate_tokens(lock)
    min_words = _int_env("CLAUDE_MEMORY_DRIFT_AUDIT_MIN_WORDS", _DEFAULT_MIN_WORDS)
    min_sample = _int_env("CLAUDE_MEMORY_DRIFT_AUDIT_MIN_SAMPLE", _DEFAULT_MIN_SAMPLE)

    messages = _parse_transcript(transcript_path)
    substantive = [m for m in messages if _is_substantive(m, min_words)]

    if len(substantive) < min_sample:
        record = _audit_record(
            "session_too_short",
            session_id=session_id,
            substantive_count=len(substantive),
            min_sample=min_sample,
            min_words=min_words,
            total_assistant_messages=len(messages),
        )
        _append_audit(root, record)
        sys.stdout.write(_summary_line(record) + "\n")
        return 0

    cited = sum(1 for m in substantive if _is_cited(m, substrate_tokens))
    drift_score = 1.0 - (cited / len(substantive))

    record = _audit_record(
        "scored",
        session_id=session_id,
        drift_score=round(drift_score, 3),
        substantive_count=len(substantive),
        cited_count=cited,
        total_assistant_messages=len(messages),
        substrate_tokens_count=len(substrate_tokens),
        workspace=lock.get("workspace"),
        min_words=min_words,
        min_sample=min_sample,
    )
    _append_audit(root, record)
    sys.stdout.write(_summary_line(record) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 -- Stop hooks must never block
        try:
            root = _repo_root()
            _append_hook_error(root, f"{type(exc).__name__}: {exc}")
            sys.stdout.write(
                "memory-drift audit: internal error (logged to "
                ".scratch/memory_drift_audit_errors.jsonl). No score.\n"
            )
        except Exception:  # noqa: BLE001
            pass
        sys.exit(0)
