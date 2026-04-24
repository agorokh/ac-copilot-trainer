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
from tools.process_miner.vault_audit import (
    collect_vault_audit,
    render_vault_health_failure,
    render_vault_health_markdown,
)


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
        help="Number of days to look back (default: 30 or integer DAYS env)",
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

    parser.add_argument(
        "--ingest-session-debrief",
        action="store_true",
        help=(
            "Also merge .cache/session_debriefs/*.jsonl into the knowledge DB "
            "(requires --ingest-knowledge; or use scripts/ingest_session_debriefs.py alone)"
        ),
    )

    parser.add_argument(
        "--session-debrief-days",
        type=int,
        default=14,
        help="With --ingest-session-debrief: max age in days for JSONL rows (default: 14)",
    )

    parser.add_argument(
        "--export-multi-bot-jsonl",
        type=str,
        default=None,
        metavar="PATH",
        help="After analysis, write multi-bot training JSONL (PRs with ≥2 bots; issue #56)",
    )

    parser.add_argument(
        "--audit-vault",
        action="store_true",
        help=(
            "Collect vault metadata via GitHub API, score health, SAVE compliance, "
            "and add a Vault Health section to the report (#73)"
        ),
    )

    ns = parser.parse_args()
    if ns.session_debrief_days < 1:
        parser.error("--session-debrief-days must be >= 1")
    if ns.days is None:
        raw = os.getenv("DAYS", "30")
        try:
            ns.days = int(raw)
        except ValueError:
            parser.error(f"Invalid DAYS environment variable {raw!r} (expected integer)")
    return ns


def _append_learned_artifact_output_if_needed(count: int, emit_rules: bool) -> None:
    """Write learned-artifact file count for GitHub Actions when ``--emit-learned`` was set.

    Output key ``learned_artifact_files_count`` counts new ``.md`` + ``.mdc`` files written.
    ``rules_count`` is written with the same value for backwards compatibility.
    """
    path = os.getenv("GITHUB_OUTPUT")
    if not path or not emit_rules:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"learned_artifact_files_count={count}\n")
            f.write(f"rules_count={count}\n")
    except OSError as e:
        print(f"Warning: failed to write GITHUB_OUTPUT ({e})", file=sys.stderr)


def main() -> int:
    """Main entry point."""
    args = parse_args()
    rules_out: list[int] = [0]
    emit_rules = args.emit_learned
    try:
        return _main_run(args, rules_out)
    finally:
        _append_learned_artifact_output_if_needed(rules_out[0], emit_rules)


def _main_run(args: argparse.Namespace, rules_out: list[int]) -> int:
    if args.ingest_session_debrief and not args.ingest_knowledge:
        print(
            "Error: --ingest-session-debrief requires --ingest-knowledge "
            "(or run scripts/ingest_session_debriefs.py without GitHub)"
        )
        return 1

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
        if not args.ingest_knowledge:
            return 0
        print(
            "Continuing with empty PR analysis/report generation and knowledge DB ingestion "
            "(no PR rows in range)."
        )

    try:
        result = analyze_prs(prs)
    except Exception as e:
        print(f"Error analyzing PRs: {e}")
        traceback.print_exc()
        return 1

    vault_lines: list[str] | None = None
    vault_audit = None
    if args.audit_vault:
        try:
            base_branch = client.get_default_branch(owner, repo)
            vault_audit = collect_vault_audit(
                client,
                owner,
                repo,
                branch=base_branch,
                prs=result.prs,
                clusters=result.clusters,
            )
            vault_lines = render_vault_health_markdown(vault_audit)
        except Exception as e:
            print(f"Warning: vault audit failed: {e}", file=sys.stderr)
            if os.getenv("DEBUG", "").strip() or os.getenv("MINING_DEBUG", "").strip():
                traceback.print_exc()
            vault_lines = render_vault_health_failure(e)

    try:
        until = datetime.now(UTC)
        render_report(
            result,
            args.repo,
            since,
            report_path,
            period_days=days_span,
            until=until,
            vault_section_lines=vault_lines,
        )
        append_hook_suggestions_to_report(result, report_path)
    except Exception as e:
        print(f"Error rendering report: {e}")
        traceback.print_exc()
        return 1

    if args.export_multi_bot_jsonl:
        from tools.model_training.data_pipeline import write_multi_bot_miner_training_jsonl

        out_p = Path(args.export_multi_bot_jsonl)
        try:
            n_rows = write_multi_bot_miner_training_jsonl(result.prs, out_p)
        except Exception as e:
            print(f"Error writing multi-bot training JSONL: {e}")
            traceback.print_exc()
            return 1
        print(f"Multi-bot training export: wrote {n_rows} row(s) to {out_p}")

    if args.emit_learned:
        repo_root = Path.cwd()
        summary, n_emitted = emit_learned_artifacts(
            result,
            repo=args.repo,
            repo_root=repo_root,
            min_occurrences=args.min_rule_occurrences,
            agents_md_path=Path(args.agents_md),
        )
        rules_out[0] = n_emitted
        print(summary)

    if args.ingest_knowledge:
        try:
            from tools.repo_knowledge.ingest import ingest_analysis

            db_path = Path(".cache/repo_knowledge/knowledge.db")
            d_applied, d_skipped = ingest_analysis(
                result,
                args.repo,
                db_path,
                repo_root=Path.cwd(),
                ingest_session_debrief=args.ingest_session_debrief,
                debrief_max_age_days=args.session_debrief_days,
                vault_audit=vault_audit,
            )
            print(f"Knowledge DB updated at {db_path}")
            if args.ingest_session_debrief and (d_applied or d_skipped):
                print(
                    f"Session debrief JSONL: {d_applied} applied, {d_skipped} duplicate(s) skipped "
                    "(tools.repo_knowledge.session_debrief_ingest)"
                )
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
