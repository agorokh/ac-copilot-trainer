"""Semantic clustering of review comments using sentence-transformer embeddings.

Replaces TF-IDF when ``MINING_SEMANTIC_CLUSTER=1``. Produces clusters based on
*conceptual* similarity (e.g. all "silent exception swallowing" findings cluster
together even when they use different surface words) rather than lexical overlap.

Architecture:
    1. Encode each comment body with ``all-MiniLM-L6-v2`` (384-dim, ~80 MB, CPU-only).
    2. Agglomerative clustering with cosine distance, ``distance_threshold`` controlling
       granularity (default 0.5, aligned with ``cluster_comments(similarity_threshold=0.5)``).
    3. Produce :class:`CommentCluster` objects compatible with the existing analyze pipeline.

Dependencies: ``sentence-transformers`` — install via ``pip install -e ".[mining-semantic]"``.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING

from tools.process_miner.noise_filter import text_for_clustering

if TYPE_CHECKING:
    import numpy as np

    from tools.process_miner.schemas import CommentCluster, ReviewComment

logger = logging.getLogger(__name__)

# Short comments after normalization are often noise; very low values explode
# runtime. Override with MINING_SEMANTIC_MIN_COMMENT_CHARS (default 15).
_raw_min_chars = os.environ.get("MINING_SEMANTIC_MIN_COMMENT_CHARS", "15").strip()
try:
    _cfg_min_chars = int(_raw_min_chars)
except ValueError:
    logger.warning(
        "Ignoring invalid MINING_SEMANTIC_MIN_COMMENT_CHARS=%r; using default 15",
        _raw_min_chars,
    )
    _cfg_min_chars = 15
_MIN_SEMANTIC_COMMENT_CHARS = max(5, _cfg_min_chars)

# Lazy-imported at first use so the module can be imported without
# sentence-transformers installed (e.g. in tests that mock).
_model = None
_MODEL_NAME = "all-MiniLM-L6-v2"


class SemanticClusteringDependencyError(ImportError):
    """Raised when sentence-transformers is not installed."""


def _load_model():  # noqa: ANN202
    """Load sentence-transformer model lazily (first call only)."""
    global _model  # noqa: PLW0603
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise SemanticClusteringDependencyError(
            "Semantic clustering requires sentence-transformers. "
            'Install with: pip install -e ".[mining-semantic]"'
        ) from e
    logger.info("Loading sentence-transformer model %s …", _MODEL_NAME)
    _model = SentenceTransformer(_MODEL_NAME)
    return _model


def encode_comments(
    texts: list[str],
    *,
    batch_size: int = 64,
    show_progress: bool = False,
) -> np.ndarray:
    """Return (N, 384) float32 embedding matrix for *texts*."""
    import numpy as np

    if not texts:
        return np.empty((0, 384), dtype=np.float32)
    model = _load_model()
    return model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
        normalize_embeddings=True,  # cosine → dot product after L2 norm
    )


def cluster_by_embeddings(
    comments: list[ReviewComment],
    *,
    distance_threshold: float = 0.5,
    min_cluster_size: int = 3,
) -> list[CommentCluster]:
    """Cluster *comments* by embedding similarity.

    Parameters
    ----------
    comments:
        Pre-filtered comments (process-chrome already dropped).
    distance_threshold:
        Max cosine distance to merge two comments (lower → tighter clusters).
        Default 0.5 aligns with ``cluster_comments(similarity_threshold=0.5)``
        which passes ``1.0 - similarity_threshold`` as ``distance_threshold``.
    min_cluster_size:
        Clusters smaller than this are discarded.

    Returns
    -------
    list[CommentCluster]
        Sorted by ``count`` descending.
    """
    from tools.process_miner.analyze import (
        _dominant_cluster_author_type,
        _dominant_cluster_bot_name,
        classify_preventability,
        classify_severity,
        normalize_comment_text,
    )

    if len(comments) < min_cluster_size:
        return []

    # Prepare text and filter empties
    raw_texts = [text_for_clustering(c) for c in comments]
    norm_texts = [normalize_comment_text(t) for t in raw_texts]

    filtered_idx: list[int] = []
    filtered_texts: list[str] = []
    for i, t in enumerate(norm_texts):
        if len(t) > _MIN_SEMANTIC_COMMENT_CHARS:
            filtered_idx.append(i)
            filtered_texts.append(t)

    if len(filtered_texts) < min_cluster_size:
        return []

    filtered_comments = [comments[i] for i in filtered_idx]

    # Encode + cluster
    embeddings = encode_comments(filtered_texts)

    try:
        from sklearn.cluster import AgglomerativeClustering
    except ImportError as e:
        raise SemanticClusteringDependencyError(
            "Semantic clustering requires scikit-learn. "
            'Install with: pip install -e ".[mining-semantic]"'
        ) from e

    # distance_threshold on cosine: embeddings are L2-normalized, so
    # cosine_distance = 1 - dot(a, b). AgglomerativeClustering with metric=cosine
    # and linkage=average works well for NLP embeddings.
    # Note: sklearn >=1.4 may deprecate ``metric`` in favor of precomputed distance
    # matrices. If a FutureWarning appears, switch to precomputing cosine distances
    # via ``1 - (embeddings @ embeddings.T)`` and using ``metric="precomputed"``.
    agg = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        compute_full_tree=True,
        metric="cosine",
        linkage="average",
    )
    labels = agg.fit_predict(embeddings)

    # Group by label
    from collections import defaultdict

    groups: dict[int, list[int]] = defaultdict(list)
    for idx, lbl in enumerate(labels):
        groups[lbl].append(idx)

    clusters: list[CommentCluster] = []
    cluster_id = 0
    for _lbl, member_indices in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(member_indices) < min_cluster_size:
            continue
        group_comments = [filtered_comments[i] for i in member_indices]
        group_comments.sort(key=lambda c: (c.id, c.body or ""))
        cluster = _build_cluster(
            cluster_id,
            group_comments,
            member_indices,
            embeddings,
            filtered_comments,
            classify_severity=classify_severity,
            classify_preventability=classify_preventability,
            dominant_author_type=_dominant_cluster_author_type,
            dominant_bot_name=_dominant_cluster_bot_name,
            normalize_comment_text=normalize_comment_text,
        )
        clusters.append(cluster)
        cluster_id += 1

    # Already ordered by descending group size (``sorted(groups...)`` above);
    # ``count`` matches that size, so no second sort/reindex (matches TF-IDF
    # display order without redundant work; Sourcery/Gemini #81).
    return clusters


def _centroid_title(
    embeddings: np.ndarray,
    member_indices: list[int],
    filtered_comments: list[ReviewComment],
    normalize_comment_text: Callable[[str], str],
) -> str:
    """Derive a human-readable title from the centroid-nearest comment."""
    import numpy as np

    centroid = embeddings[member_indices].mean(axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-9
    dots = embeddings[member_indices] @ centroid
    best_local_idx = int(np.argmax(dots))
    best_comment = filtered_comments[member_indices[best_local_idx]]
    title_body = normalize_comment_text(text_for_clustering(best_comment))
    # Prefer sentence boundary at ". " so dotted versions (v1.2.3) are not cut mid-token.
    head = title_body.split(". ", 1)[0].strip() or title_body.strip()
    return head[:80].strip() or "Semantic cluster"


def _representative_examples(group_comments: list[ReviewComment], limit: int = 6) -> list[str]:
    """First *limit* distinct non-empty body snippets."""
    examples: list[str] = []
    for c in group_comments:
        snip = (c.body or "")[:500].strip()
        if snip and snip not in examples:
            examples.append(snip)
        if len(examples) >= limit:
            break
    return examples


def _build_cluster(
    cluster_id: int,
    group_comments: list[ReviewComment],
    member_indices: list[int],
    embeddings: np.ndarray,
    filtered_comments: list[ReviewComment],
    *,
    classify_severity: Callable[[str], str],
    classify_preventability: Callable[[str, str | None], str],
    dominant_author_type: Callable[[list[ReviewComment]], str],
    dominant_bot_name: Callable[[list[ReviewComment]], str | None],
    normalize_comment_text: Callable[[str], str],
) -> CommentCluster:
    """Assemble a :class:`CommentCluster` from one agglomerative group."""
    from tools.process_miner.schemas import CommentCluster

    file_counter: Counter[str] = Counter()
    for c in group_comments:
        if c.path:
            file_counter[c.path] += 1
    top_files = [f for f, _ in file_counter.most_common(5)]

    majority_c = max(group_comments, key=lambda c: len(c.body or ""))
    majority_body = majority_c.body or ""
    severity = classify_severity(majority_body)
    preventability = classify_preventability(majority_body, majority_c.path)

    title = _centroid_title(embeddings, member_indices, filtered_comments, normalize_comment_text)
    dom_author = dominant_author_type(group_comments)  # type: ignore[operator]
    dom_bot = dominant_bot_name(group_comments) if dom_author == "bot" else None  # type: ignore[operator]
    pr_nums = {c.pr_number for c in group_comments if c.pr_number is not None}

    return CommentCluster(
        cluster_id=cluster_id,
        title=title,
        count=len(group_comments),
        comments=group_comments,
        affected_files=top_files,
        severity=severity,
        preventability=preventability,
        representative_examples=_representative_examples(group_comments),
        dominant_author_type=dom_author,
        dominant_bot_name=dom_bot,
        distinct_pr_count=len(pr_nums),
    )
