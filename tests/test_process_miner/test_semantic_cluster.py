"""Tests for semantic clustering module (sentence-transformer path).

All mock-based tests use fake embeddings so they run without sentence-transformers
installed. The sklearn dependency is guarded at module level via ``importorskip``
so the entire file is skipped gracefully when sklearn is absent (Copilot #81).
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

# Guard: skip the whole module if scikit-learn is not installed, since
# cluster_by_embeddings imports sklearn unconditionally.
pytest.importorskip("sklearn", reason="scikit-learn not installed")  # noqa: E402

from tools.process_miner.schemas import ReviewComment  # noqa: E402


def _mk(body: str, cid: str, pr: int = 1, path: str = "a.py") -> ReviewComment:
    return ReviewComment(
        id=cid,
        body=body,
        author="coderabbit[bot]",
        author_type="bot",
        bot_name="coderabbit",
        pr_number=pr,
        path=path,
    )


# 6 comments in 2 conceptual groups:
# Group A (3): silent exception swallowing variants
# Group B (3): SQL injection variants
_COMMENTS = [
    _mk("bare except clause swallows all errors silently", "a1", pr=1, path="service.py"),
    _mk("exception handler drops errors with pass statement", "a2", pr=2, path="gate.py"),
    _mk("silent exception swallowing hides failures in metrics", "a3", pr=3, path="metrics.py"),
    _mk("SQL injection via unvalidated env var in CREATE DATABASE", "b1", pr=4, path="setup.sh"),
    _mk("shell injection through unquoted variable expansion", "b2", pr=5, path="deploy.sh"),
    _mk("SQL injection risk in database provisioning script", "b3", pr=6, path="init.sh"),
]

# Fake embeddings: Group A vectors near [1,0,0], Group B near [0,1,0]
_FAKE_EMBEDDINGS = np.array(
    [
        [0.95, 0.05, 0.0],  # a1
        [0.90, 0.10, 0.0],  # a2
        [0.92, 0.08, 0.0],  # a3
        [0.05, 0.95, 0.0],  # b1
        [0.10, 0.90, 0.0],  # b2
        [0.08, 0.92, 0.0],  # b3
    ],
    dtype=np.float32,
)
# L2-normalize rows (encode_comments does this in real path)
_FAKE_EMBEDDINGS = _FAKE_EMBEDDINGS / np.linalg.norm(_FAKE_EMBEDDINGS, axis=1, keepdims=True)


@patch("tools.process_miner.semantic_cluster.encode_comments", return_value=_FAKE_EMBEDDINGS)
def test_two_conceptual_groups_found(_mock_encode: object) -> None:
    from tools.process_miner.semantic_cluster import cluster_by_embeddings

    clusters = cluster_by_embeddings(_COMMENTS, min_cluster_size=3, distance_threshold=0.5)
    assert len(clusters) == 2
    counts = sorted(cl.count for cl in clusters)
    assert counts == [3, 3]


@patch("tools.process_miner.semantic_cluster.encode_comments", return_value=_FAKE_EMBEDDINGS)
def test_distinct_pr_count_tracks_unique_prs(_mock_encode: object) -> None:
    from tools.process_miner.semantic_cluster import cluster_by_embeddings

    clusters = cluster_by_embeddings(_COMMENTS, min_cluster_size=3, distance_threshold=0.5)
    for cl in clusters:
        assert cl.distinct_pr_count == 3  # each group has PRs 1,2,3 or 4,5,6


@patch("tools.process_miner.semantic_cluster.encode_comments", return_value=_FAKE_EMBEDDINGS)
def test_affected_files_populated(_mock_encode: object) -> None:
    from tools.process_miner.semantic_cluster import cluster_by_embeddings

    clusters = cluster_by_embeddings(_COMMENTS, min_cluster_size=3, distance_threshold=0.5)
    for cl in clusters:
        assert len(cl.affected_files) >= 1


@patch("tools.process_miner.semantic_cluster.encode_comments", return_value=_FAKE_EMBEDDINGS)
def test_small_input_returns_empty(_mock_encode: object) -> None:
    from tools.process_miner.semantic_cluster import cluster_by_embeddings

    clusters = cluster_by_embeddings(_COMMENTS[:2], min_cluster_size=3)
    assert clusters == []


@patch("tools.process_miner.semantic_cluster.encode_comments", return_value=_FAKE_EMBEDDINGS[:3])
def test_single_cluster_when_all_similar(_mock_encode: object) -> None:
    from tools.process_miner.semantic_cluster import cluster_by_embeddings

    # Only feed Group A comments (3 items)
    clusters = cluster_by_embeddings(_COMMENTS[:3], min_cluster_size=3, distance_threshold=0.5)
    assert len(clusters) == 1
    assert clusters[0].count == 3


def test_encode_comments_returns_correct_shape() -> None:
    """Integration test: only runs if sentence-transformers is installed."""
    st = pytest.importorskip("sentence_transformers", reason="sentence-transformers not installed")
    assert st  # make linter happy

    from tools.process_miner.semantic_cluster import encode_comments

    texts = ["hello world", "testing embeddings"]
    result = encode_comments(texts)
    assert result.shape == (2, 384)
    assert result.dtype == np.float32
