"""Tests for clustering (requires optional ``[mining]`` deps)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tools.process_miner.analyze import cluster_comments
from tools.process_miner.schemas import ReviewComment

pytest.importorskip("sklearn")


def test_cluster_marks_visited_only_after_size_threshold() -> None:
    """Regression: small similarity groups must not consume unrelated comments."""
    bodies = [
        "totally unique alpha bravo charlie delta",
        "totally unique echo foxtrot golf hotel",
        "another unique india juliet kilo lima",
    ]
    comments = [
        ReviewComment(
            id=str(i),
            body=b,
            author="r",
            created_at=datetime.now(UTC),
            path=f"src/f{i}.py",
            is_inline=True,
        )
        for i, b in enumerate(bodies)
    ]
    clusters = cluster_comments(comments, min_cluster_size=3, similarity_threshold=0.99)
    assert clusters == []
