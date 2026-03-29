"""Markdown report renderer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.schemas import AnalysisResult


def _executive_summary_lines(result: AnalysisResult) -> list[str]:
    """Build executive summary bullets with defensive ``stats`` lookups."""
    st = result.stats
    pr_count = int(st.get("pr_count", 0))
    total_comments = int(st.get("total_comments", 0))
    avg = float(st.get("avg_comments_per_pr", 0.0))
    total_files = int(st.get("total_files", 0))
    total_additions = int(st.get("total_additions", 0))
    total_deletions = int(st.get("total_deletions", 0))
    ci_failures = int(st.get("ci_failure_count", 0))
    lines = [
        "## Executive Summary",
        "",
        f"- **PRs Analyzed:** {pr_count}",
        f"- **Total Comments:** {total_comments}",
        f"- **Average Comments per PR:** {avg:.1f}",
        f"- **Total Files Changed:** {total_files}",
        f"- **Total Additions:** {total_additions:,}",
        f"- **Total Deletions:** {total_deletions:,}",
        f"- **CI Failures:** {ci_failures}",
        f"- **Comment Clusters Found:** {len(result.clusters)}",
        "",
        "---",
        "",
    ]
    return lines


def render_report(
    result: AnalysisResult,
    repo: str,
    since: datetime,
    output_path: Path,
    *,
    period_days: int | None = None,
    until: datetime | None = None,
) -> None:
    """Render analysis result as markdown report.

    ``period_days`` and ``until`` describe the analysis window for the header
    (fixes hardcoded \"Last 7 days\" when callers use other ranges).
    """
    lines: list[str] = []
    until_utc = until if until is not None else datetime.now(UTC)
    if until_utc.tzinfo is None:
        until_utc = until_utc.replace(tzinfo=UTC)

    if period_days is not None:
        period_label = f"last {period_days} day(s)"
    else:
        period_label = f"since {since.date().isoformat()}"

    lines.append("# Process Improvement Miner Report")
    lines.append("")
    lines.append(f"**Repository:** {repo}")
    lines.append(
        f"**Analysis period:** {period_label} "
        f"(since {since.date().isoformat()} UTC, through {until_utc.date().isoformat()} UTC)"
    )
    lines.append(f"**Generated:** {until_utc.isoformat()}")
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.extend(_executive_summary_lines(result))

    lines.append("## Analyzed PRs")
    lines.append("")
    for pr in result.prs:
        merged_date = pr.merged_at.date().isoformat() if pr.merged_at else "N/A"
        lines.append(
            f"- **PR #{pr.number}:** [{pr.title}](https://github.com/{repo}/pull/{pr.number})"
        )
        lines.append(f"  - Author: {pr.author}")
        lines.append(f"  - Merged: {merged_date}")
        lines.append(f"  - Comments: {len(pr.review_comments) + len(pr.issue_comments)}")
        lines.append(f"  - Files: {len(pr.files)}")
        if pr.ci_status:
            lines.append(f"  - CI: {pr.ci_status.conclusion}")
        lines.append("")
    lines.append("---")
    lines.append("")

    lines.append("## Top Recurring Comment Clusters")
    lines.append("")
    lines.append("These clusters represent patterns of repeated feedback across PRs.")
    lines.append("")

    top_clusters = result.clusters[:20]
    for i, cluster in enumerate(top_clusters, 1):
        lines.append(f"### {i}. {cluster.title}")
        lines.append("")
        lines.append(f"- **Count:** {cluster.count} comments")
        lines.append(f"- **Severity:** {cluster.severity}")
        lines.append(f"- **Preventability:** {cluster.preventability}")
        if cluster.affected_files:
            lines.append(f"- **Affected Files:** {', '.join(cluster.affected_files[:3])}")
        lines.append("")
        lines.append("**Representative Examples:**")
        lines.append("")
        for j, example in enumerate(cluster.representative_examples[:3], 1):
            lines.append(f"{j}. {example[:300]}{'...' if len(example) > 300 else ''}")
            lines.append("")
        lines.append("---")
        lines.append("")

    if result.ci_failures:
        lines.append("## Recurring CI Failures")
        lines.append("")
        for failure in result.ci_failures:
            pr_n = int(failure.get("pr_number", 0))
            pr_t = str(failure.get("pr_title", ""))
            lines.append(f"- **PR #{pr_n}:** [{pr_t}](https://github.com/{repo}/pull/{pr_n})")
            if failure.get("failed_jobs"):
                jobs = failure["failed_jobs"]
                if isinstance(jobs, list):
                    names = [str(j) for j in jobs[:5]]
                    lines.append(f"  - Failed jobs: {', '.join(names)}")
            lines.append("")
        lines.append("---")
        lines.append("")

    if result.churned_files:
        lines.append("## Most Churned Files")
        lines.append("")
        lines.append("Files with the most review comments:")
        lines.append("")
        for file_info in result.churned_files[:10]:
            lines.append(f"- `{file_info['path']}`: {file_info['comment_count']} comments")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Suggested Next Actions")
    lines.append("")
    lines.append("### Proposed Cursor Rule Updates")
    lines.append("")

    automation_clusters = [c for c in result.clusters if c.preventability == "automation"]
    guideline_clusters = [c for c in result.clusters if c.preventability == "guideline"]
    architecture_clusters = [c for c in result.clusters if c.preventability == "architecture"]
    typecheck_clusters = [c for c in result.clusters if c.preventability == "typecheck"]

    if automation_clusters:
        lines.append("**Automation Gates (lint/format/pre-commit):**")
        lines.append("")
        for cluster in automation_clusters[:5]:
            lines.append(f"- Add check for: {cluster.title.lower()}")
        lines.append("")

    if typecheck_clusters:
        lines.append("**Type Checking:**")
        lines.append("")
        for cluster in typecheck_clusters[:5]:
            lines.append(f"- Add type check for: {cluster.title.lower()}")
        lines.append("")

    if guideline_clusters:
        lines.append("**Repository Guidelines:**")
        lines.append("")
        for cluster in guideline_clusters[:5]:
            lines.append(f"- Document pattern: {cluster.title.lower()}")
        lines.append("")

    if architecture_clusters:
        lines.append("**Architecture/Agent Rules:**")
        lines.append("")
        for cluster in architecture_clusters[:5]:
            lines.append(f"- Add agent rule: {cluster.title.lower()}")
        lines.append("")

    lines.append("### Proposed CI/Pre-commit Changes")
    lines.append("")
    if automation_clusters or typecheck_clusters:
        lines.append("- Add automated checks for common formatting/import issues")
        lines.append("- Add type checking to CI pipeline")
        lines.append("- Add pre-commit hooks for common issues")
        lines.append("")

    lines.append("### Proposed Documentation Updates")
    lines.append("")
    if guideline_clusters:
        lines.append("- Update AGENTS.md with common patterns")
        lines.append("- Add examples to documentation")
        lines.append("- Create troubleshooting guide")
        lines.append("")

    lines.append("---")
    lines.append("")

    lines.append("## Appendix: All Comment Clusters")
    lines.append("")
    for cluster in result.clusters:
        lines.append(f"### Cluster {cluster.cluster_id}: {cluster.title}")
        lines.append("")
        lines.append(f"- Count: {cluster.count}")
        lines.append(f"- Severity: {cluster.severity}")
        lines.append(f"- Preventability: {cluster.preventability}")
        affected = ", ".join(cluster.affected_files) if cluster.affected_files else "N/A"
        lines.append(f"- Affected Files: {affected}")
        lines.append("")
        lines.append("**All Examples:**")
        lines.append("")
        for example in cluster.representative_examples:
            lines.append("```")
            lines.append(example)
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report written to {output_path}")
