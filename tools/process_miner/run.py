#!/usr/bin/env python3
"""CLI entry point for process miner."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.process_miner.analyze import analyze_prs
from tools.process_miner.collect import collect_pr_data
from tools.process_miner.emit import append_hook_suggestions_to_report, emit_learned_artifacts
from tools.process_miner.github_client import GitHubClient
from tools.process_miner.render import render_report


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Process improvement miner for GitHub PRs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--repo",
        type=str,
        help="Repository in owner/repo format (e.g., agorokh/template-repo)",
        default=os.getenv("REPO"),
    )

    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Number of days to look back (default: 7 or integer DAYS env)",
    )

    parser.add_argument(
        "--since",
        type=str,
        help="Start date in YYYY-MM-DD format (overrides --days)",
    )

    parser.add_argument(
        "--out",
        type=str,
        help="Output directory for reports (default: reports/process_miner/)",
        default="reports/process_miner",
    )

    parser.add_argument(
        "--max-prs",
        type=int,
        default=50,
        help="Maximum number of PRs to analyze (default: 50)",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum GitHub API pages per paginated endpoint (default: 20)",
    )

    parser.add_argument(
        "--emit-learned",
        action="store_true",
        help="Emit .claude/.cursor learned rules and optional AGENTS.md bullets (Tier 1)",
    )

    parser.add_argument(
        "--min-rule-occurrences",
        type=int,
        default=3,
        help="Minimum cluster size to emit a learned rule (default: 3)",
    )

    parser.add_argument(
        "--agents-md",
        type=str,
        default="AGENTS.md",
        help="Path to AGENTS.md for optional Learned Workspace Facts bullets",
    )

    parser.add_argument(
        "--ingest-knowledge",
        action="store_true",
        help="Ingest miner output into SQLite knowledge DB (requires [knowledge] extra)",
    )

    ns = parser.parse_args()
    if ns.days is None:
        raw = os.getenv("DAYS", "7")
        try:
            ns.days = int(raw)
        except ValueError:
            parser.error(f"Invalid DAYS environment variable {raw!r} (expected integer)")
    return ns


def main() -> int:
    """Main entry point."""
    args = parse_args()

    if not args.repo:
        print("Error: --repo required or set REPO environment variable")
        print("Example: --repo owner/repo")
        return 1

    if "/" not in args.repo:
        print("Error: --repo must be in owner/repo format")
        return 1

    owner, repo = args.repo.split("/", 1)

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable required")
        print("Create a Personal Access Token at https://github.com/settings/tokens")
        return 1

    if args.since:
        try:
            since_naive = datetime.fromisoformat(args.since)
            if since_naive.tzinfo is None:
                since = datetime.combine(since_naive.date(), datetime.min.time(), tzinfo=UTC)
            else:
                since = since_naive
        except ValueError:
            print(f"Error: Invalid date format: {args.since}. Use YYYY-MM-DD")
            return 1
        days_span = max((datetime.now(UTC) - since).days, 1)
    else:
        since = datetime.now(UTC) - timedelta(days=args.days)
        days_span = args.days

    cache_dir = Path(".cache/process_miner")
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_filename = f"{since.date()}_last{days_span}days.md"
    report_path = output_dir / report_filename

    print("=" * 60)
    print("Process Improvement Miner")
    print("=" * 60)
    print(f"Repository: {owner}/{repo}")
    print(f"Since: {since.date().isoformat()}")
    print(f"Max PRs: {args.max_prs}")
    print(f"Max pages: {args.max_pages}")
    print(f"Output: {report_path}")
    print("=" * 60)
    print()

    try:
        client = GitHubClient(token=token)
    except Exception as e:
        print(f"Error initializing GitHub client: {e}")
        return 1

    try:
        prs = collect_pr_data(
            client=client,
            owner=owner,
            repo=repo,
            since=since,
            max_prs=args.max_prs,
            cache_dir=cache_dir,
            max_pages=args.max_pages,
        )
    except Exception as e:
        print(f"Error collecting PR data: {e}")
        traceback.print_exc()
        return 1

    if not prs:
        print("No PRs found in the specified time range.")
        return 0

    try:
        result = analyze_prs(prs)
    except Exception as e:
        print(f"Error analyzing PRs: {e}")
        traceback.print_exc()
        return 1

    try:
        until = datetime.now(UTC)
        render_report(
            result,
            args.repo,
            since,
            report_path,
            period_days=days_span,
            until=until,
        )
        append_hook_suggestions_to_report(result, report_path)
    except Exception as e:
        print(f"Error rendering report: {e}")
        traceback.print_exc()
        return 1

    if args.emit_learned:
        repo_root = Path.cwd()
        summary = emit_learned_artifacts(
            result,
            repo=args.repo,
            repo_root=repo_root,
            min_occurrences=args.min_rule_occurrences,
            agents_md_path=Path(args.agents_md),
        )
        print(summary)

    if args.ingest_knowledge:
        try:
            from tools.repo_knowledge.ingest import ingest_analysis

            db_path = Path(".cache/repo_knowledge/knowledge.db")
            ingest_analysis(result, args.repo, db_path, repo_root=Path.cwd())
            print(f"Knowledge DB updated at {db_path}")
        except ImportError as e:
            print(f"ingest-knowledge skipped: install [knowledge] extra ({e})")
            return 1

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"PRs analyzed: {result.stats['pr_count']}")
    print(f"Total comments: {result.stats['total_comments']}")
    print("Top 5 clusters:")
    for i, cluster in enumerate(result.clusters[:5], 1):
        cmt = cluster.count
        sev = cluster.severity
        prev = cluster.preventability
        print(f"  {i}. {cluster.title} ({cmt} comments, {sev}, {prev})")
    print(f"Report saved to: {report_path}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
