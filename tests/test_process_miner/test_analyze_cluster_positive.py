"""Positive clustering coverage (requires ``[mining]``)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tools.process_miner.analyze import cluster_comments
from tools.process_miner.schemas import ReviewComment

pytest.importorskip("sklearn")


def test_cluster_forms_for_similar_comments() -> None:
    body = (
        "Please ensure every public function in this module has explicit type annotations "
        "so consumers can rely on static analysis."
    )
    comments = [
        ReviewComment(
            id=str(i),
            body=body,
            author="r",
            created_at=datetime.now(UTC),
            path="src/x.py",
            is_inline=True,
        )
        for i in range(4)
    ]
    clusters = cluster_comments(comments, min_cluster_size=2, similarity_threshold=0.25)
    assert clusters
    assert max(c.count for c in clusters) >= 2
