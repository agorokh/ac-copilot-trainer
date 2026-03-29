"""Emit deterministic learned rules (Claude + Cursor) from miner clusters."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.schemas import AnalysisResult, CommentCluster

CLAUDE_LEARNED = Path(".claude/rules/learned")
CURSOR_LEARNED = Path(".cursor/rules/learned")


def _slugify(title: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (s[:max_len] or "pattern").rstrip("-")


def _paths_to_globs(paths: list[str], max_globs: int = 6) -> list[str]:
    """Build forward-slash globs for Claude/Cursor rule frontmatter.

    Paths are normalized with ``Path.as_posix()`` so emitted strings never contain OS-specific
    separators. Multi-segment paths scope to the top-level directory (``dir/**/*``); a single
    segment is treated as a root-level basename (``**/name``), not ``name/**/*``.
    """
    globs: list[str] = []
    for p in paths[:max_globs]:
        posix = Path(p).as_posix()
        parts = posix.split("/")
        if len(parts) >= 2:
            globs.append(f"{parts[0]}/**/*")
        elif parts:
            # Root-level file (e.g. Makefile): match by basename, not as a directory.
            globs.append(f"**/{parts[0]}")
    seen: set[str] = set()
    out: list[str] = []
    for g in globs:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out or ["**/*"]


def _rule_fingerprint(cluster: CommentCluster) -> str:
    files = ",".join(sorted(cluster.affected_files))
    payload = f"{cluster.title}|{cluster.severity}|{cluster.preventability}|{files}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _parse_existing_fingerprints(learned_dir: Path) -> set[str]:
    found: set[str] = set()
    if not learned_dir.exists():
        return found
    for f in learned_dir.glob("*"):
        if f.suffix not in {".md", ".mdc"}:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^rule_fingerprint:\s*(\S+)\s*$", text, re.MULTILINE)
        if m:
            found.add(m.group(1))
    return found


def _build_rule_markdown(
    cluster: CommentCluster,
    repo: str,
    *,
    fingerprint: str,
    mined_at: str,
    path_scope_key: str = "paths",
) -> tuple[str, str]:
    """Return (title_human, markdown_body_including_frontmatter).

    ``path_scope_key`` is ``paths`` for Claude ``.md`` rules and ``globs`` for Cursor ``.mdc``.
    """
    title_human = cluster.title.replace(" / ", " ").title()[:80]
    if not title_human.strip():
        title_human = f"Pattern {fingerprint}"

    pr_nums = sorted({c.pr_number for c in cluster.comments if c.pr_number})
    pr_part = f"{len(pr_nums)} PRs" if pr_nums else "unknown PRs"
    globs = _paths_to_globs(cluster.affected_files)

    lines: list[str] = [
        "---",
        'description: "Learned via process-miner — verify before relying on it."',
        f"{path_scope_key}:",
    ]
    for g in globs:
        lines.append(f'  - "{g}"')
    lines.extend(
        [
            "source: process-miner",
            f"rule_fingerprint: {fingerprint}",
            f"mined_from: {cluster.count} review comments across {pr_part}",
            f"last_updated: {mined_at}",
            f"repository: {repo}",
            f"severity: {cluster.severity}",
            f"preventability: {cluster.preventability}",
            "---",
            "",
            f"# {title_human} (learned)",
            "",
            "Reviewers repeatedly raised similar feedback in this area. "
            "Treat as a heuristic, not a hard rule.",
            "",
            "## Representative themes",
            "",
        ]
    )
    for ex in cluster.representative_examples[:4]:
        lines.append(f"- {ex[:400]}{'...' if len(ex) > 400 else ''}")
    lines.extend(["", "## Suggested enforcement", ""])

    if cluster.preventability == "automation":
        lines.append(
            "- Prefer lint/format or CI checks over manual review for this class of issue."
        )
    elif cluster.preventability == "typecheck":
        lines.append("- Strengthen typing (mypy/pyright) or narrow APIs to catch this earlier.")
    else:
        lines.append("- Document the preferred pattern in AGENTS.md or a scoped rule.")

    body = "\n".join(lines) + "\n"
    return title_human, body


def emit_learned_artifacts(
    result: AnalysisResult,
    *,
    repo: str,
    repo_root: Path,
    min_occurrences: int = 3,
    agents_md_path: Path | None = None,
) -> str:
    """Write learned rules under ``.claude/rules/learned`` and ``.cursor/rules/learned``.

    Skips clusters below ``min_occurrences`` or whose fingerprint already exists on disk.
    Optionally appends bullets to **Learned Workspace Facts** in ``AGENTS.md``.
    """
    mined_at = datetime.now(UTC).date().isoformat()
    claude_dir = repo_root / CLAUDE_LEARNED
    cursor_dir = repo_root / CURSOR_LEARNED
    claude_dir.mkdir(parents=True, exist_ok=True)
    cursor_dir.mkdir(parents=True, exist_ok=True)

    claude_existing = _parse_existing_fingerprints(claude_dir)
    cursor_existing = _parse_existing_fingerprints(cursor_dir)

    written: list[str] = []
    skipped_dup = 0
    skipped_small = 0

    for cluster in result.clusters:
        if cluster.count < min_occurrences:
            skipped_small += 1
            continue
        fp = _rule_fingerprint(cluster)
        have_claude = fp in claude_existing
        have_cursor = fp in cursor_existing
        if have_claude and have_cursor:
            skipped_dup += 1
            continue

        _, body_claude = _build_rule_markdown(
            cluster, repo, fingerprint=fp, mined_at=mined_at, path_scope_key="paths"
        )
        _, body_cursor = _build_rule_markdown(
            cluster, repo, fingerprint=fp, mined_at=mined_at, path_scope_key="globs"
        )
        slug = _slugify(cluster.title)
        fname = f"{slug}-{fp[:8]}.md"

        wrote = False
        if not have_claude:
            (claude_dir / fname).write_text(body_claude, encoding="utf-8")
            claude_existing.add(fp)
            wrote = True
        if not have_cursor:
            (cursor_dir / (Path(fname).stem + ".mdc")).write_text(body_cursor, encoding="utf-8")
            cursor_existing.add(fp)
            wrote = True
        if wrote:
            written.append(fname)

    agents_note = ""
    if agents_md_path and written:
        agents_file = repo_root / agents_md_path
        if agents_file.is_file():
            block = (
                "\n<!-- process-miner:learned:start -->\n"
                + f"- (process-miner) New learned rule file(s): {', '.join(written)}"
                + "\n<!-- process-miner:learned:end -->\n"
            )
            text = agents_file.read_text(encoding="utf-8")
            if "process-miner:learned:start" in text:
                pattern = re.compile(
                    r"<!-- process-miner:learned:start -->.*?<!-- process-miner:learned:end -->",
                    re.DOTALL,
                )
                text = pattern.sub(block.strip(), text)
            else:
                marker = "## Learned Workspace Facts"
                if marker in text:
                    text = text.replace(marker, marker + block, 1)
                else:
                    text = text.rstrip() + "\n" + block
            agents_file.write_text(text, encoding="utf-8")
            agents_note = f"; updated {agents_file}"

    return (
        f"emit: wrote {len(written)} rule pair(s){agents_note}; "
        f"skipped {skipped_small} below threshold; skipped {skipped_dup} duplicates"
    )


def append_hook_suggestions_to_report(
    result: AnalysisResult,
    report_path: Path,
) -> None:
    """Append diff-style hook suggestions for automation-tagged clusters (not auto-applied)."""
    automation = [c for c in result.clusters if c.preventability == "automation" and c.count >= 2]
    if not automation:
        return
    lines = [
        "",
        "## Hook suggestions (not applied)",
        "",
        "The following are **suggested** `settings.json` hook snippets for "
        "`preventability: automation` patterns.",
        "Review and merge manually if appropriate.",
        "",
    ]
    for c in automation[:10]:
        lines.append(f"### {c.title}")
        lines.append("```diff")
        lines.append("+ // Suggested: add PreToolUse guard for format/lint class feedback")
        lines.append(f"+ // Pattern: {c.title} ({c.count} occurrences)")
        lines.append("```")
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


# re-export for tests
__all__ = [
    "append_hook_suggestions_to_report",
    "emit_learned_artifacts",
    "_paths_to_globs",
    "_rule_fingerprint",
]
