"""Analysis pipeline with comment clustering and classification."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from tools.process_miner.schemas import (
    AnalysisResult,
    CommentCluster,
    PRData,
    ReviewComment,
)


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


def cluster_comments(
    comments: list[ReviewComment],
    min_cluster_size: int = 2,
    similarity_threshold: float = 0.3,
) -> list[CommentCluster]:
    """Cluster similar comments using TF-IDF and cosine similarity."""
    if len(comments) < min_cluster_size:
        return []

    normalized_texts = [normalize_comment_text(c.body) for c in comments]

    filtered_comments: list[ReviewComment] = []
    filtered_texts: list[str] = []
    for c, text in zip(comments, normalized_texts, strict=True):
        if len(text) > 20:
            filtered_comments.append(c)
            filtered_texts.append(text)

    if len(filtered_comments) < min_cluster_size:
        return []

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

            all_text = " ".join([normalize_comment_text(c.body) for c in ordered])
            words = re.findall(r"\b\w{4,}\b", all_text)
            word_counter = Counter(words)
            top_words = [w for w, _ in word_counter.most_common(3)]
            title = " / ".join(top_words) if top_words else f"Cluster {cluster_id}"

            sample_text = ordered[0].body
            severity = classify_severity(sample_text)
            preventability = classify_preventability(sample_text, ordered[0].path)

            examples = [c.body[:200] + "..." if len(c.body) > 200 else c.body for c in ordered[:6]]

            cluster = CommentCluster(
                cluster_id=cluster_id,
                title=title,
                count=len(group_comments),
                comments=group_comments,
                affected_files=affected_files,
                severity=severity,
                preventability=preventability,
                representative_examples=examples,
            )
            clusters.append(cluster)
            cluster_id += 1

    clusters.sort(key=lambda c: c.count, reverse=True)

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
    clusters = cluster_comments(all_comments, min_cluster_size=2)
    print(f"Found {len(clusters)} clusters")

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

    stats: dict[str, object] = {
        "pr_count": len(prs),
        "total_comments": total_comments,
        "total_files": total_files,
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "avg_comments_per_pr": total_comments / len(prs) if prs else 0,
        "ci_failure_count": len(ci_failures),
    }

    return AnalysisResult(
        prs=prs,
        clusters=clusters,
        ci_failures=ci_failures,
        churned_files=churned_files,
        stats=stats,
    )
