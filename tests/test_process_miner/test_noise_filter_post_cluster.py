"""Post-cluster dedupe and title chrome (#78)."""

from __future__ import annotations

from tools.process_miner.noise_filter import (
    cluster_title_is_bot_chrome,
    normalize_cluster_title_dedup_key,
    post_cluster_cleanup,
)
from tools.process_miner.schemas import CommentCluster, ReviewComment


def test_normalize_title_dedup_key_order_independent() -> None:
    a = normalize_cluster_title_dedup_key("foo / bar / baz")
    b = normalize_cluster_title_dedup_key("baz / foo / bar")
    assert a == b
    assert a == "bar baz foo"


def test_normalize_title_dedup_key_keeps_short_tokens_when_needed() -> None:
    a = normalize_cluster_title_dedup_key("go / api / gateway")
    b = normalize_cluster_title_dedup_key("rust / api / timeout")
    assert a != b


def test_cluster_title_bot_chrome_detects_product_stack() -> None:
    assert cluster_title_is_bot_chrome("cursor / bugbot / github")
    assert cluster_title_is_bot_chrome("coderabbit review noise")


def test_cluster_title_substantive_not_bot_chrome() -> None:
    assert not cluster_title_is_bot_chrome("cache invalidation and migration risk")
    assert not cluster_title_is_bot_chrome("nullable foreign key data integrity")
    assert not cluster_title_is_bot_chrome("cursor migration risk")


def test_post_cluster_merges_permuted_titles() -> None:
    body = "substantive comment about return codes " * 3

    def mk(tid: str, title: str) -> CommentCluster:
        return CommentCluster(
            cluster_id=0,
            title=title,
            count=3,
            comments=[
                ReviewComment(
                    id=f"{tid}-{i}",
                    body=body,
                    author="b",
                    author_type="bot",
                    bot_name="x",
                    pr_number=1,
                )
                for i in range(3)
            ],
            affected_files=["a.py"],
            severity="nit",
            preventability="guideline",
            distinct_pr_count=1,
        )

    c1 = mk("a", "alpha / beta / gamma")
    c2 = mk("b", "gamma / alpha / beta")
    kept, audit = post_cluster_cleanup([c1, c2])
    assert len(audit["near_duplicate_merges"]) == 1
    assert len(kept) == 1
    assert kept[0].count == 6


def test_cluster_fallback_titles_do_not_merge() -> None:
    """``Cluster 0`` / ``Cluster 1`` TF-IDF fallbacks must keep distinct dedup keys."""
    assert normalize_cluster_title_dedup_key("Cluster 0") != normalize_cluster_title_dedup_key(
        "Cluster 1"
    )


def test_post_cluster_cluster_ids_follow_count_order() -> None:
    """After cleanup, ``cluster_id`` matches sort order by ``count`` (descending)."""
    body = "substantive comment about return codes " * 3

    def mk(cid: int, n: int, title: str) -> CommentCluster:
        return CommentCluster(
            cluster_id=cid,
            title=title,
            count=n,
            comments=[
                ReviewComment(
                    id=f"{cid}-{i}",
                    body=body,
                    author="b",
                    author_type="bot",
                    bot_name="x",
                    pr_number=i,
                )
                for i in range(n)
            ],
            affected_files=["a.py"],
            severity="nit",
            preventability="guideline",
            distinct_pr_count=1,
        )

    small = mk(0, 2, "alpha only token here")
    big = mk(1, 5, "beta gamma delta")
    kept, _audit = post_cluster_cleanup([small, big])
    assert len(kept) == 2
    assert kept[0].count >= kept[1].count
    assert kept[0].cluster_id == 0
    assert kept[1].cluster_id == 1


def test_post_cluster_drops_chrome_after_merge() -> None:
    chrome = CommentCluster(
        cluster_id=0,
        title="cursor / bugbot / copilot",
        count=3,
        comments=[
            ReviewComment(
                id=str(i),
                body=("real finding " * 20),
                author="b",
                author_type="bot",
                bot_name="x",
                pr_number=i,
            )
            for i in range(3)
        ],
        affected_files=[],
        severity="nit",
        preventability="guideline",
        distinct_pr_count=3,
    )
    kept, audit = post_cluster_cleanup([chrome])
    assert kept == []
    assert len(audit["dropped_title_bot_chrome"]) == 1
