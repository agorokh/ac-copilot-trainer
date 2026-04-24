"""Analysis pipeline with comment clustering and classification."""

from __future__ import annotations

import logging
import os
import re
from collections import Counter, defaultdict

from tools.process_miner.bot_authorship import bot_agreement_location_key
from tools.process_miner.noise_filter import (
    drop_process_chrome_comments,
    post_cluster_cleanup,
    text_for_clustering,
)
from tools.process_miner.schemas import (
    AnalysisResult,
    CommentCluster,
    PRData,
    ReviewComment,
)

logger = logging.getLogger(__name__)


def _use_semantic_cluster() -> bool:
    """Check at call time so tests and late env changes are respected (Bugbot #81)."""
    return os.environ.get("MINING_SEMANTIC_CLUSTER", "").strip().lower() in ("1", "true", "yes")


class MiningClusteringDependencyError(ImportError):
    """Raised when optional sklearn dependencies for TF-IDF clustering are missing."""


def normalize_comment_text(text: str) -> str:
    """Normalize comment text for clustering."""
    text = re.sub(r"```[\s\S]*?```", "[CODE_BLOCK]", text)
    text = re.sub(r"`[^`]+`", "[CODE]", text)

    lines = text.split("\n")
    filtered_lines: list[str] = []
    skip_next = False
    for line in lines:
        if line.strip().startswith("Traceback"):
            skip_next = True
        elif skip_next and (line.strip().startswith("File") or line.startswith("  ")):
            continue
        else:
            skip_next = False
            filtered_lines.append(line)
    text = "\n".join(filtered_lines)

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"https?://\S+", "[URL]", text)

    return text.strip().lower()


def _keyword_hit(text_lower: str, keywords: tuple[str, ...]) -> bool:
    """Match single-token keywords as whole words; multi-token phrases as substrings."""
    for phrase in keywords:
        p = phrase.lower()
        if re.fullmatch(r"\w+", p):
            if re.search(rf"\b{re.escape(p)}\b", text_lower):
                return True
        elif p in text_lower:
            return True
    return False


def classify_severity(text: str) -> str:
    """Classify comment severity based on keywords."""
    text_lower = text.lower()

    if _keyword_hit(
        text_lower,
        ("security", "vulnerability", "exploit", "injection", "xss", "csrf"),
    ):
        return "security"

    if _keyword_hit(
        text_lower,
        ("bug", "crash", "error", "exception", "fails", "broken", "wrong"),
    ):
        return "bug"

    if _keyword_hit(
        text_lower,
        ("race", "deadlock", "timeout", "leak", "memory", "concurrent", "thread"),
    ):
        return "reliability"

    if _keyword_hit(
        text_lower,
        ("slow", "performance", "optimize", "bottleneck", "latency", "n+1"),
    ):
        return "perf"

    if _keyword_hit(
        text_lower,
        ("validation", "check", "verify", "test", "refactor", "cleanup"),
    ):
        return "maintainability"

    return "nit"


# Most severe first; must stay aligned with :func:`classify_severity` return labels.
SEVERITY_ORDER: tuple[str, ...] = (
    "security",
    "bug",
    "reliability",
    "perf",
    "maintainability",
    "nit",
)


def _prefer_by_ordered_rank(a: str, b: str, order: tuple[str, ...]) -> str:
    """Pick ``a`` or ``b`` by earliest index in ``order`` (unknown labels sort last)."""

    def rank(s: str) -> int:
        try:
            return order.index(s)
        except ValueError:
            return len(order)

    return a if rank(a) <= rank(b) else b


def more_severe_severity(a: str, b: str) -> str:
    """Return the more severe of two :func:`classify_severity` labels."""
    return _prefer_by_ordered_rank(a, b, SEVERITY_ORDER)


# Higher-stake prevention gaps first; must cover all :func:`classify_preventability` labels.
PREVENTABILITY_ORDER: tuple[str, ...] = (
    "architecture",
    "test",
    "typecheck",
    "guideline",
    "automation",
)


def more_consequential_preventability(a: str, b: str) -> str:
    """Return the more consequential of two :func:`classify_preventability` labels."""
    return _prefer_by_ordered_rank(a, b, PREVENTABILITY_ORDER)


def classify_preventability(text: str, _file_path: str | None = None) -> str:
    """Classify how this could have been prevented."""
    text_lower = text.lower()

    if _keyword_hit(
        text_lower,
        ("format", "import", "unused import", "whitespace", "trailing"),
    ):
        return "automation"

    if _keyword_hit(
        text_lower,
        ("type", "typing", "none", "optional", "type hint", "annotation"),
    ):
        return "typecheck"

    if _keyword_hit(
        text_lower,
        ("error handling", "exception", "try/except", "catch", "retry"),
    ):
        return "guideline"

    if _keyword_hit(
        text_lower,
        (
            "architecture",
            "pattern",
            "design",
            "should use",
            "instead of",
            "anti-pattern",
        ),
    ):
        return "architecture"

    if _keyword_hit(text_lower, ("test", "test case", "coverage", "missing test")):
        return "test"

    return "guideline"


def _dominant_cluster_author_type(comments: list[ReviewComment]) -> str:
    """Classify cluster by bot vs human (``unknown`` does not vote with either side)."""
    if not comments:
        return "mixed"
    ctr = Counter(c.author_type for c in comments)
    bots = ctr.get("bot", 0)
    humans = ctr.get("human", 0)
    if bots > humans:
        return "bot"
    if humans > bots:
        return "human"
    if bots == 0 and humans == 0:
        return "unknown"
    return "mixed"


def _dominant_cluster_bot_name(comments: list[ReviewComment]) -> str | None:
    """Majority short name among comments with ``bot_name``.

    Only used when the cluster is bot-dominated (``dominant_author_type == \"bot\"``).
    """
    bot_only = [c for c in comments if c.bot_name]
    if not bot_only:
        return None
    top, n = Counter(c.bot_name for c in bot_only).most_common(1)[0]
    if n > len(bot_only) / 2:
        return top
    return None


def author_type_breakdown(comments: list[ReviewComment]) -> dict[str, int]:
    """Count comments by ``author_type``."""
    return dict(Counter(c.author_type for c in comments))


def per_bot_severity_counts(comments: list[ReviewComment]) -> dict[str, dict[str, int]]:
    """For each ``bot_name``, count comments by ``classify_severity`` bucket."""
    out: dict[str, dict[str, int]] = {}
    for c in comments:
        if c.author_type != "bot" or not c.bot_name:
            continue
        sev = classify_severity(c.body)
        out.setdefault(c.bot_name, {})
        out[c.bot_name][sev] = out[c.bot_name].get(sev, 0) + 1
    return out


def bot_agreement_summary_for_pr(pr: PRData) -> dict[str, object] | None:
    """Overlap stats when ≥2 distinct bots commented on a PR."""
    all_c = [
        c for c in pr.review_comments + pr.issue_comments if c.author_type == "bot" and c.bot_name
    ]
    bots = {c.bot_name for c in all_c}
    if len(bots) < 2:
        return None
    loc_to_bots: dict[str, set[str]] = defaultdict(set)
    for c in all_c:
        key = bot_agreement_location_key(path=c.path, line=c.line, comment_id=c.id)
        loc_to_bots[key].add(c.bot_name)
    multi = sum(1 for s in loc_to_bots.values() if len(s) >= 2)
    pair_counts: dict[str, int] = defaultdict(int)
    for names in loc_to_bots.values():
        sl = sorted(names)
        if len(sl) < 2:
            continue
        for i in range(len(sl)):
            for j in range(i + 1, len(sl)):
                pair_counts[f"{sl[i]}|{sl[j]}"] += 1
    top_pairs = dict(
        sorted(pair_counts.items(), key=lambda x: (-x[1], x[0]))[:20],
    )
    return {
        "pr_number": pr.number,
        "distinct_bots": sorted(bots),
        "inline_or_thread_locations": len(loc_to_bots),
        "locations_with_multiple_bots": multi,
        "bot_pair_co_occurrence": top_pairs,
    }


def _collect_bot_agreement_rows(prs: list[PRData]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for pr in prs:
        row = bot_agreement_summary_for_pr(pr)
        if row is not None:
            rows.append(row)
    return rows


def cluster_comments(
    comments: list[ReviewComment],
    min_cluster_size: int = 3,
    similarity_threshold: float = 0.5,
) -> list[CommentCluster]:
    """Cluster similar comments.

    Dispatches to either semantic (sentence-transformer) or TF-IDF clustering based on
    the ``MINING_SEMANTIC_CLUSTER`` env flag. Pre-cluster gate: pure process-chrome
    comments are dropped before any vectorization. See ``noise_filter.is_process_chrome_only``.
    """
    if len(comments) < min_cluster_size:
        return []

    comments, dropped_chrome = drop_process_chrome_comments(comments)
    if dropped_chrome:
        logger.debug("Dropped %s process-chrome comments before clustering.", dropped_chrome)
    if len(comments) < min_cluster_size:
        return []

    # --- Semantic clustering path (opt-in) ---
    if _use_semantic_cluster():
        from tools.process_miner.semantic_cluster import (
            SemanticClusteringDependencyError,
            cluster_by_embeddings,
        )

        try:
            return cluster_by_embeddings(
                comments,
                distance_threshold=1.0 - similarity_threshold,
                min_cluster_size=min_cluster_size,
            )
        except SemanticClusteringDependencyError as e:
            raise MiningClusteringDependencyError(
                "Semantic clustering requires optional dependencies. "
                'Install with: pip install -e ".[mining-semantic]"'
            ) from e

    # --- TF-IDF path (default) ---
    clustering_plain = [text_for_clustering(c) for c in comments]
    normalized_texts = [normalize_comment_text(t) for t in clustering_plain]

    filtered_comments: list[ReviewComment] = []
    filtered_texts: list[str] = []
    for c, text in zip(comments, normalized_texts, strict=True):
        if len(text) > 20:
            filtered_comments.append(c)
            filtered_texts.append(text)

    if len(filtered_comments) < min_cluster_size:
        return []

    norm_by_id = {c.id: t for c, t in zip(filtered_comments, filtered_texts, strict=True)}

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as e:
        raise MiningClusteringDependencyError(
            'Clustering requires optional dependencies. Install with: pip install -e ".[mining]"'
        ) from e

    vectorizer = TfidfVectorizer(
        max_features=1000,
        min_df=1,
        stop_words="english",
        ngram_range=(1, 2),
    )

    try:
        tfidf_matrix = vectorizer.fit_transform(filtered_texts)
    except ValueError:
        return []

    similarity_matrix = cosine_similarity(tfidf_matrix)

    threshold = similarity_threshold
    visited: set[int] = set()
    clusters: list[CommentCluster] = []
    cluster_id = 0

    for i in range(len(filtered_comments)):
        if i in visited:
            continue

        similar_indices = [i]
        for j in range(i + 1, len(filtered_comments)):
            if j not in visited and similarity_matrix[i][j] >= threshold:
                similar_indices.append(j)

        if len(similar_indices) >= min_cluster_size:
            for idx in similar_indices:
                visited.add(idx)

            group_comments = [filtered_comments[idx] for idx in similar_indices]
            ordered = sorted(group_comments, key=lambda c: (c.id, c.body))

            file_counter: Counter[str] = Counter()
            for c in ordered:
                if c.path:
                    file_counter[c.path] += 1

            affected_files = [path for path, _ in file_counter.most_common(5)]

            # Reuse normalized clustering text (same as TF-IDF inputs) — do not re-run clustering.
            filtered_bodies = [norm_by_id[c.id] for c in ordered]
            all_text = " ".join(filtered_bodies)
            words = re.findall(r"\b\w{4,}\b", all_text)
            word_counter = Counter(words)
            top_words = [w for w, _ in word_counter.most_common(3)]
            title = " / ".join(top_words) if top_words else f"Cluster {cluster_id}"

            sample_text = filtered_bodies[0] if filtered_bodies else ""
            severity = classify_severity(sample_text)
            preventability = classify_preventability(sample_text, ordered[0].path)

            examples = [c.body[:200] + "..." if len(c.body) > 200 else c.body for c in ordered[:6]]

            dom_author = _dominant_cluster_author_type(ordered)
            dom_bot = _dominant_cluster_bot_name(ordered) if dom_author == "bot" else None
            pr_nums = {c.pr_number for c in ordered if c.pr_number is not None}
            distinct_pr = len(pr_nums)

            cluster = CommentCluster(
                cluster_id=cluster_id,
                title=title,
                count=len(group_comments),
                comments=group_comments,
                affected_files=affected_files,
                severity=severity,
                preventability=preventability,
                representative_examples=examples,
                dominant_author_type=dom_author,
                dominant_bot_name=dom_bot,
                distinct_pr_count=distinct_pr,
            )
            clusters.append(cluster)
            cluster_id += 1

    clusters.sort(key=lambda c: c.count, reverse=True)
    for i, cl in enumerate(clusters):
        cl.cluster_id = i

    return clusters


def analyze_prs(prs: list[PRData]) -> AnalysisResult:
    """Analyze PRs and generate clusters."""
    print(f"Analyzing {len(prs)} PRs...")

    all_comments: list[ReviewComment] = []
    for pr in prs:
        all_comments.extend(pr.review_comments)
        all_comments.extend(pr.issue_comments)

    print(f"Found {len(all_comments)} total comments")

    print("Clustering comments...")
    # Defaults (min size 3, similarity 0.5): see test_analyze_prs_default_clustering_forms_cluster.
    clusters = cluster_comments(all_comments)
    clusters, noise_post_audit = post_cluster_cleanup(clusters)
    print(f"Found {len(clusters)} clusters (after post-cluster dedupe / title chrome filter)")

    ci_failures: list[dict[str, object]] = []
    for pr in prs:
        if pr.ci_status and pr.ci_status.conclusion == "failure":
            failed_jobs = [j for j in pr.ci_status.jobs if j.get("conclusion") == "failure"]
            ci_failures.append(
                {
                    "pr_number": pr.number,
                    "pr_title": pr.title,
                    "failed_jobs": [j.get("name") for j in failed_jobs],
                }
            )

    file_comment_count: defaultdict[str, int] = defaultdict(int)
    for pr in prs:
        for comment in pr.review_comments:
            if comment.path:
                file_comment_count[comment.path] += 1

    churned_files = [
        {"path": path, "comment_count": count}
        for path, count in sorted(file_comment_count.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    total_comments = len(all_comments)
    total_files = sum(len(pr.files) for pr in prs)
    total_additions = sum(sum(f.additions for f in pr.files) for pr in prs)
    total_deletions = sum(sum(f.deletions for f in pr.files) for pr in prs)

    bot_agreement_by_pr = _collect_bot_agreement_rows(prs)
    stats: dict[str, object] = {
        "pr_count": len(prs),
        "noise_filter_post_cluster_audit": noise_post_audit,
        "total_comments": total_comments,
        "total_files": total_files,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "avg_comments_per_pr": total_comments / len(prs) if prs else 0,
        "ci_failure_count": len(ci_failures),
        "comment_author_type_breakdown": author_type_breakdown(all_comments),
        "per_bot_severity_counts": per_bot_severity_counts(all_comments),
        "multi_bot_pr_count": len(bot_agreement_by_pr),
        "bot_agreement_by_pr": bot_agreement_by_pr,
    }

    return AnalysisResult(
        prs=prs,
        clusters=clusters,
        ci_failures=ci_failures,
        churned_files=churned_files,
        stats=stats,
    )
