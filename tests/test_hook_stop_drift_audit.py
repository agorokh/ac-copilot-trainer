"""Tests for ``scripts/hook_stop_drift_audit.py``.

The Stop hook scores conversational drift post-hoc and logs to
``.scratch/memory_audit.jsonl``. It must always exit 0 (Stop hooks are
command-only per the template invariant) and degrade gracefully when the
transcript, substrate lockfile, or other inputs are missing.

Coverage:
  * No transcript path → "no_transcript" record + exit 0.
  * Transcript file missing → "no_transcript" record + exit 0.
  * No substrate lockfile → "no_substrate" record + exit 0.
  * Session too short (fewer substantive responses than min_sample)
    → "session_too_short" record + exit 0.
  * All substantive responses cite substrate → drift_score = 0.0.
  * No substantive responses cite substrate → drift_score = 1.0.
  * Mixed citation → fractional drift_score.
  * Kill switch ``CLAUDE_MEMORY_DRIFT_AUDIT=0`` → silent exit 0.
  * Substantive threshold tuned via env.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hook_stop_drift_audit.py"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(payload: dict, *, cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        check=False,
        timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr


_DEFAULT_LOCK_BODY = (
    "scripts/hook_memory_gate.py enforces tier-3 substrate at LOAD via mcp tool calls"
)


def _write_lock(tmp_path: Path, *, response_body: str = _DEFAULT_LOCK_BODY) -> None:
    scratch = tmp_path / ".scratch"
    scratch.mkdir(exist_ok=True)
    (scratch / ".last_memory_query").write_text(
        json.dumps(
            {
                "token": "t",
                "timestamp_utc": _now_iso(),
                "workspace": "test_ws",
                "prompt": "test prompt",
                "ttl_seconds": 1800,
                "prefetch_ok": True,
                "response_body": response_body,
                "response_body_len": len(response_body),
            }
        ),
        encoding="utf-8",
    )


def _write_transcript(tmp_path: Path, messages: list[str]) -> Path:
    """Write a JSONL transcript with the given assistant messages."""
    path = tmp_path / "transcript.jsonl"
    lines = []
    for text in messages:
        record = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]},
        }
        lines.append(json.dumps(record))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _read_audit_records(tmp_path: Path) -> list[dict]:
    log = tmp_path / ".scratch" / "memory_audit.jsonl"
    if not log.is_file():
        return []
    out: list[dict] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Fail-open paths (no transcript / no substrate / short session)
# ---------------------------------------------------------------------------


def test_no_transcript_path_logs_skip(fake_repo: Path) -> None:
    rc, stdout, _ = _run({}, cwd=fake_repo)
    assert rc == 0
    assert "no_transcript" not in stdout  # the human-friendly message is different
    assert "transcript_path unavailable" in stdout
    records = _read_audit_records(fake_repo)
    assert records and records[-1]["reason"] == "no_transcript"


def test_missing_transcript_file_logs_skip(fake_repo: Path) -> None:
    rc, stdout, _ = _run(
        {"transcript_path": str(fake_repo / "nonexistent.jsonl")},
        cwd=fake_repo,
    )
    assert rc == 0
    records = _read_audit_records(fake_repo)
    assert records and records[-1]["reason"] == "no_transcript"


def test_no_substrate_lockfile_logs_skip(fake_repo: Path) -> None:
    transcript = _write_transcript(fake_repo, ["a long substantive response " * 10])
    rc, stdout, _ = _run({"transcript_path": str(transcript)}, cwd=fake_repo)
    assert rc == 0
    assert "no Tier-3 substrate context" in stdout
    records = _read_audit_records(fake_repo)
    assert records and records[-1]["reason"] == "no_substrate"


def test_session_too_short_logs_skip(fake_repo: Path) -> None:
    _write_lock(fake_repo)
    transcript = _write_transcript(fake_repo, ["ok", "yes", "done"])
    rc, stdout, _ = _run({"transcript_path": str(transcript)}, cwd=fake_repo)
    assert rc == 0
    assert "session too short" in stdout
    records = _read_audit_records(fake_repo)
    assert records and records[-1]["reason"] == "session_too_short"
    assert records[-1]["substantive_count"] == 0


# ---------------------------------------------------------------------------
# Scoring (all-cited / none-cited / mixed)
# ---------------------------------------------------------------------------


_LONG_GROUNDED = (
    "The memory contract lives in docs/00_Core/MEMORY_CONTRACT.md and the "
    "invariant memory-three-tiers.md describes the three tiers, with "
    "substrate queries via mcp__agentic-memory__query_knowledge_graph. "
    "Agents must cite vault paths and MCP tool names in substantive responses "
    "so the Stop drift audit can measure conversational grounding against the "
    "tier-three semantic substrate loaded at session start."
)
_LONG_UNGROUNDED = (
    "This is a long response that does not reference any project-specific content and "
    "simply rambles about general topics with no connection to the canonical "
    "documentation layout or any curated findings whatsoever long enough to count. "
    "It discusses unrelated hobbies, weather patterns, and fictional narratives "
    "without naming files, automation entrypoints, or governance documents at all."
)


def test_all_substantive_responses_cited_drift_zero(fake_repo: Path) -> None:
    _write_lock(fake_repo)
    transcript = _write_transcript(fake_repo, [_LONG_GROUNDED] * 3)
    rc, stdout, _ = _run({"transcript_path": str(transcript)}, cwd=fake_repo)
    assert rc == 0
    records = _read_audit_records(fake_repo)
    rec = records[-1]
    assert rec["reason"] == "scored"
    assert rec["drift_score"] == 0.0
    assert rec["substantive_count"] == 3
    assert rec["cited_count"] == 3
    assert "drift_score=0.00" in stdout
    assert "LOW" in stdout


def test_no_substantive_responses_cited_drift_one(fake_repo: Path) -> None:
    # Substrate response body picks tokens that DON'T appear in the ungrounded
    # responses. The lockfile uses words like "tier-3 substrate", "memory-gate",
    # which the ungrounded messages avoid.
    _write_lock(
        fake_repo,
        response_body="hook_memory_gate Tier3 substrate kennel zephyr quokka",
    )
    transcript = _write_transcript(
        fake_repo,
        [
            "This response talks about quantum tunneling in cats without any reference "
            "to the architecture we built or any specific file paths or automation tools. "
            "It stays deliberately generic about physics metaphors and household pets only.",
            "Another long response covering galactic civilizations as a metaphor for "
            "something irrelevant to coding agents or repository management practices. "
            "It never names repositories, manifests, or enforcement hooks of any kind.",
            "A third unrelated rambling about historical fiction and the meaning of "
            "various unrelated philosophical concepts that occupy thirty words easily. "
            "The prose avoids tiered knowledge stores and semantic retrieval entirely.",
        ],
    )
    rc, _, _ = _run({"transcript_path": str(transcript)}, cwd=fake_repo)
    assert rc == 0
    rec = _read_audit_records(fake_repo)[-1]
    assert rec["reason"] == "scored"
    assert rec["drift_score"] == 1.0
    assert rec["cited_count"] == 0


def test_mixed_citation_fractional_drift(fake_repo: Path) -> None:
    _write_lock(fake_repo)
    transcript = _write_transcript(
        fake_repo,
        [_LONG_GROUNDED, _LONG_UNGROUNDED, _LONG_GROUNDED, _LONG_UNGROUNDED],
    )
    rc, _, _ = _run({"transcript_path": str(transcript)}, cwd=fake_repo)
    assert rc == 0
    rec = _read_audit_records(fake_repo)[-1]
    assert rec["reason"] == "scored"
    assert rec["substantive_count"] == 4
    # 2 of 4 cited → drift_score = 0.5
    assert rec["cited_count"] == 2
    assert rec["drift_score"] == 0.5


# ---------------------------------------------------------------------------
# Tuning + kill switch
# ---------------------------------------------------------------------------


def test_kill_switch_silent_exit(fake_repo: Path) -> None:
    _write_lock(fake_repo)
    transcript = _write_transcript(fake_repo, [_LONG_GROUNDED] * 3)
    rc, stdout, _ = _run(
        {"transcript_path": str(transcript)},
        cwd=fake_repo,
        env={"CLAUDE_MEMORY_DRIFT_AUDIT": "0"},
    )
    assert rc == 0
    assert stdout == ""  # silent
    # No log entry written either
    assert not _read_audit_records(fake_repo)


def test_min_words_threshold_tuning(fake_repo: Path) -> None:
    """Shorter messages count as substantive when threshold is lowered."""
    _write_lock(fake_repo)
    transcript = _write_transcript(fake_repo, ["short citation MEMORY_CONTRACT.md"] * 4)
    # Default min_words=30 → all filtered as trivial → too_short
    rc, _, _ = _run({"transcript_path": str(transcript)}, cwd=fake_repo)
    assert rc == 0
    assert _read_audit_records(fake_repo)[-1]["reason"] == "session_too_short"

    # Lower threshold to 2 → messages count as substantive → scored
    rc, _, _ = _run(
        {"transcript_path": str(transcript)},
        cwd=fake_repo,
        env={"CLAUDE_MEMORY_DRIFT_AUDIT_MIN_WORDS": "2"},
    )
    assert rc == 0
    rec = _read_audit_records(fake_repo)[-1]
    assert rec["reason"] == "scored"
    assert rec["min_words"] == 2


def test_malformed_transcript_lines_skipped(fake_repo: Path) -> None:
    """Malformed JSONL lines must not crash the audit."""
    _write_lock(fake_repo)
    transcript = fake_repo / "broken.jsonl"
    transcript.write_text(
        "{ this is not JSON\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": _LONG_GROUNDED}]},
            }
        )
        + "\n"
        + "garbage\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": _LONG_GROUNDED}]},
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": _LONG_GROUNDED}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rc, _, _ = _run({"transcript_path": str(transcript)}, cwd=fake_repo)
    assert rc == 0
    rec = _read_audit_records(fake_repo)[-1]
    assert rec["reason"] == "scored"
    assert rec["substantive_count"] == 3  # malformed lines skipped


def test_summary_line_tolerates_malformed_scored_fields() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("drift", SCRIPT)
    assert spec and spec.loader
    drift = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drift)
    line = drift._summary_line(
        {
            "reason": "scored",
            "drift_score": "not-a-float",
            "substantive_count": None,
            "cited_count": "x",
        }
    )
    assert "drift_score=0.00" in line
    assert "LOW" in line


def test_stop_hook_active_skips_without_log(fake_repo: Path) -> None:
    _write_lock(fake_repo)
    transcript = _write_transcript(fake_repo, [_LONG_GROUNDED] * 3)
    rc, stdout, _ = _run(
        {"transcript_path": str(transcript), "stop_hook_active": True},
        cwd=fake_repo,
    )
    assert rc == 0
    assert stdout == ""
    assert not _read_audit_records(fake_repo)


def test_session_can_upgrade_from_too_short_to_scored(fake_repo: Path) -> None:
    _write_lock(fake_repo)
    short = fake_repo / "short.jsonl"
    short.write_text(
        "\n".join(
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}})
            for t in ("ok", "yes", "done")
        )
        + "\n",
        encoding="utf-8",
    )
    long_path = _write_transcript(fake_repo, [_LONG_GROUNDED] * 3)
    sid = "sess-upgrade-1"
    _run({"transcript_path": str(short), "session_id": sid}, cwd=fake_repo)
    assert _read_audit_records(fake_repo)[-1]["reason"] == "session_too_short"
    _run({"transcript_path": str(long_path), "session_id": sid}, cwd=fake_repo)
    assert _read_audit_records(fake_repo)[-1]["reason"] == "scored"


def test_session_dedupe_skips_second_stop_in_same_session(fake_repo: Path) -> None:
    _write_lock(fake_repo)
    transcript = _write_transcript(fake_repo, [_LONG_GROUNDED] * 3)
    payload = {"transcript_path": str(transcript), "session_id": "sess-dedupe-1"}
    rc, _, _ = _run(payload, cwd=fake_repo)
    assert rc == 0
    assert len(_read_audit_records(fake_repo)) == 1
    rc2, stdout2, _ = _run(payload, cwd=fake_repo)
    assert rc2 == 0
    assert stdout2 == ""
    assert len(_read_audit_records(fake_repo)) == 1


def test_string_content_supported(fake_repo: Path) -> None:
    """Some Claude Code transcript formats use string content (not blocks)."""
    _write_lock(fake_repo)
    transcript = fake_repo / "string.jsonl"
    transcript.write_text(
        "\n".join(
            json.dumps({"type": "assistant", "message": {"content": _LONG_GROUNDED}})
            for _ in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    rc, _, _ = _run({"transcript_path": str(transcript)}, cwd=fake_repo)
    assert rc == 0
    rec = _read_audit_records(fake_repo)[-1]
    assert rec["reason"] == "scored"
    assert rec["substantive_count"] == 3
