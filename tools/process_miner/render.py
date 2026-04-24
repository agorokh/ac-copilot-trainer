"""Markdown report renderer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.schemas import AnalysisResult


def _bot_review_sections(result: AnalysisResult) -> list[str]:
    """Bot vs human breakdown, per-bot severity, and multi-bot agreement (issue #56)."""
    st = result.stats
    breakdown = st.get("comment_author_type_breakdown")
    if not breakdown:
        return []
    lines: list[str] = [
        "## Bot vs human review comments",
        "",
        "Counts are over review and issue thread comments for this run (excludes the PR body).",
        "",
    ]
    for k in sorted(breakdown.keys()):
        lines.append(f"- **{k}:** {breakdown[k]}")
    lines.extend(["", "---", ""])

    per_bot = st.get("per_bot_severity_counts") or {}
    if isinstance(per_bot, dict) and per_bot:
        lines.append("## Per-bot comment severity (heuristic)")
        lines.append("")
        for bot in sorted(per_bot.keys()):
            sev_map = per_bot[bot]
            if not isinstance(sev_map, dict):
                continue
            parts = [f"{s}={sev_map[s]}" for s in sorted(sev_map.keys())]
            lines.append(f"- **{bot}:** {', '.join(parts)}")
        lines.extend(["", "---", ""])

    mbc = st.get("multi_bot_pr_count", 0)
    lines.append("## Multi-bot agreement (PRs with ≥2 distinct bots)")
    lines.append("")
    lines.append(f"- **PRs in window with ≥2 bots:** {mbc}")
    lines.append("")

    bag = st.get("bot_agreement_by_pr") or []
    if isinstance(bag, list) and bag:
        lines.append(
            "Per-PR summaries (pair co-occurrence counts use agreement locations: "
            "file+line when present, else path+comment id, else comment id):"
        )
        lines.append("")
        for row in bag[:25]:
            if not isinstance(row, dict):
                continue
            pr_n = row.get("pr_number", 0)
            dbs = row.get("distinct_bots") or []
            multi_loc = row.get("locations_with_multiple_bots", 0)
            lines.append(
                f"- **PR #{pr_n}** — bots: {', '.join(str(x) for x in dbs)}; "
                f"locations with multiple bots: {multi_loc}"
            )
            pairs = row.get("bot_pair_co_occurrence") or {}
            if isinstance(pairs, dict) and pairs:
                top = sorted(pairs.items(), key=lambda x: (-int(x[1]), str(x[0])))[:6]
                lines.append(f"  top pairs: {', '.join(f'{a}={b}' for a, b in top)}")
            lines.append("")
    lines.append("---")
    lines.append("")
    return lines


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
    vault_section_lines: list[str] | None = None,
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

    lines.extend(_bot_review_sections(result))

    if vault_section_lines:
        lines.extend(vault_section_lines)

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
        if cluster.dominant_author_type:
            lines.append(f"- **Dominant author type:** {cluster.dominant_author_type}")
        if cluster.dominant_bot_name:
            lines.append(f"- **Dominant bot:** {cluster.dominant_bot_name}")
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
        if cluster.dominant_author_type:
            lines.append(f"- Dominant author type: {cluster.dominant_author_type}")
        if cluster.dominant_bot_name:
            lines.append(f"- Dominant bot: {cluster.dominant_bot_name}")
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
