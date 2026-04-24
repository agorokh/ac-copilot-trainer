"""Multi-bot miner training export (#56)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tools.model_training.data_pipeline import (
    iter_multi_bot_miner_training_records,
    write_multi_bot_miner_training_jsonl,
)
from tools.process_miner.schemas import PRData, ReviewComment


def test_iter_multi_bot_skips_single_bot_pr() -> None:
    pr = PRData(
        number=1,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="x",
                author="coderabbitai",
                author_type="bot",
                bot_name="coderabbit",
                path="f.py",
                line=1,
                is_inline=True,
            )
        ],
        issue_comments=[],
    )
    assert list(iter_multi_bot_miner_training_records([pr])) == []


def test_iter_multi_bot_same_line_two_bots() -> None:
    pr = PRData(
        number=2,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="from a",
                author="coderabbitai",
                author_type="bot",
                bot_name="coderabbit",
                path="f.py",
                line=10,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="from b",
                author="gemini-code-assist",
                author_type="bot",
                bot_name="gemini",
                path="f.py",
                line=10,
                is_inline=True,
            ),
        ],
        issue_comments=[
            ReviewComment(
                id="3",
                body="lgtm",
                author="human",
                author_type="human",
                pr_number=2,
                is_inline=False,
            )
        ],
    )
    rows = list(iter_multi_bot_miner_training_records([pr]))
    assert len(rows) == 1
    assert rows[0]["pr_number"] == 2
    assert rows[0]["row_kind"] == "inline_multi_bot"
    assert rows[0]["file_path"] == "f.py"
    assert rows[0]["line"] == 10
    assert len(rows[0]["bot_comments"]) == 2
    assert rows[0]["human_resolution"] == ["lgtm"]
    assert "diff hunk not embedded" in str(rows[0]["diff_hunk"])


def test_write_multi_bot_jsonl(tmp_path: Path) -> None:
    pr = PRData(
        number=3,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="a",
                author="b1",
                author_type="bot",
                bot_name="u",
                path="x.py",
                line=1,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="b",
                author="b2",
                author_type="bot",
                bot_name="v",
                path="x.py",
                line=1,
                is_inline=True,
            ),
        ],
        issue_comments=[],
    )
    out = tmp_path / "m.jsonl"
    n = write_multi_bot_miner_training_jsonl([pr], out)
    assert n == 1
    text = out.read_text(encoding="utf-8").strip()
    assert "miner_multi_bot_sft_v1" in text
    assert "inline_multi_bot" in text


def test_iter_multi_bot_two_distinct_files_pr_level_row() -> None:
    """≥2 bots on different files (and lines) → single PR-level aggregate row."""
    pr = PRData(
        number=41,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="a",
                author="b1",
                author_type="bot",
                bot_name="u",
                path="f.py",
                line=1,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="b",
                author="b2",
                author_type="bot",
                bot_name="v",
                path="g.py",
                line=2,
                is_inline=True,
            ),
        ],
        issue_comments=[],
    )
    rows = list(iter_multi_bot_miner_training_records([pr]))
    assert len(rows) == 1
    assert rows[0]["row_kind"] == "pr_all_bots"
    assert rows[0]["file_path"] is None
    assert rows[0]["line"] is None
    assert len(rows[0]["bot_comments"]) == 2


def test_iter_multi_bot_different_lines_emits_pr_level_row() -> None:
    """No single (path,line) has ≥2 bots → one pr_all_bots row."""
    pr = PRData(
        number=4,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="a",
                author="b1",
                author_type="bot",
                bot_name="u",
                path="f.py",
                line=1,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="b",
                author="b2",
                author_type="bot",
                bot_name="v",
                path="f.py",
                line=2,
                is_inline=True,
            ),
        ],
        issue_comments=[],
    )
    rows = list(iter_multi_bot_miner_training_records([pr]))
    assert len(rows) == 1
    assert rows[0]["row_kind"] == "pr_all_bots"
    assert rows[0]["file_path"] is None
    assert len(rows[0]["bot_comments"]) == 2


def test_iter_multi_bot_file_level_same_path_no_line_two_bots() -> None:
    """≥2 bots on the same file without inline line → file_level_multi_bot row."""
    pr = PRData(
        number=50,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="file a",
                author="b1",
                author_type="bot",
                bot_name="u",
                path="f.py",
                line=None,
                is_inline=False,
            ),
            ReviewComment(
                id="2",
                body="file b",
                author="b2",
                author_type="bot",
                bot_name="v",
                path="f.py",
                line=None,
                is_inline=False,
            ),
        ],
        issue_comments=[],
    )
    rows = list(iter_multi_bot_miner_training_records([pr]))
    assert len(rows) == 1
    assert rows[0]["row_kind"] == "file_level_multi_bot"
    assert rows[0]["file_path"] == "f.py"
    assert rows[0]["line"] is None
    assert len(rows[0]["bot_comments"]) == 2


def test_iter_multi_bot_inline_plus_file_level_rows() -> None:
    """Inline multi-bot row plus path-only overlap on another file → two location rows."""
    pr = PRData(
        number=51,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="inline a",
                author="b1",
                author_type="bot",
                bot_name="u",
                path="a.py",
                line=1,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="inline b",
                author="b2",
                author_type="bot",
                bot_name="v",
                path="a.py",
                line=1,
                is_inline=True,
            ),
            ReviewComment(
                id="3",
                body="file c",
                author="b3",
                author_type="bot",
                bot_name="w",
                path="b.py",
                line=None,
                is_inline=False,
            ),
            ReviewComment(
                id="4",
                body="file d",
                author="b4",
                author_type="bot",
                bot_name="x",
                path="b.py",
                line=None,
                is_inline=False,
            ),
        ],
        issue_comments=[],
    )
    rows = list(iter_multi_bot_miner_training_records([pr]))
    kinds = [r["row_kind"] for r in rows]
    assert kinds == ["inline_multi_bot", "file_level_multi_bot"]
    assert rows[0]["file_path"] == "a.py" and rows[0]["line"] == 1
    assert rows[1]["file_path"] == "b.py" and rows[1]["line"] is None


def test_iter_multi_bot_remaining_thread_comments() -> None:
    """Inline row consumes some bots; issue-thread bots still form a ≥2-bot remainder."""
    pr = PRData(
        number=5,
        title="t",
        author="a",
        created_at=datetime.now(UTC),
        merged_at=datetime.now(UTC),
        body="",
        review_comments=[
            ReviewComment(
                id="1",
                body="inline a",
                author="b1",
                author_type="bot",
                bot_name="u",
                path="f.py",
                line=10,
                is_inline=True,
            ),
            ReviewComment(
                id="2",
                body="inline b",
                author="b2",
                author_type="bot",
                bot_name="v",
                path="f.py",
                line=10,
                is_inline=True,
            ),
        ],
        issue_comments=[
            ReviewComment(
                id="3",
                body="thread c",
                author="b3",
                author_type="bot",
                bot_name="w",
                pr_number=5,
                is_inline=False,
            ),
            ReviewComment(
                id="4",
                body="thread d",
                author="b4",
                author_type="bot",
                bot_name="x",
                pr_number=5,
                is_inline=False,
            ),
        ],
    )
    rows = list(iter_multi_bot_miner_training_records([pr]))
    kinds = [r["row_kind"] for r in rows]
    assert kinds == ["inline_multi_bot", "remaining_multi_bot"]
    assert len(rows[1]["bot_comments"]) == 2
    bots = {c["bot"] for c in rows[1]["bot_comments"]}
    assert bots == {"w", "x"}
