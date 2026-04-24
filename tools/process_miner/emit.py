"""Emit deterministic learned rules (Claude + Cursor) from miner clusters."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path

from tools.process_miner.aggregate import AggregateResult, emit_prefilter_skip_reason
from tools.process_miner.fleet import domain_for_repo
from tools.process_miner.schemas import AnalysisResult, CommentCluster

CLAUDE_LEARNED = Path(".claude/rules/learned")
CURSOR_LEARNED = Path(".cursor/rules/learned")

_SEMANTIC_DEDUP_THRESHOLD = 0.7


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


def _scope_subdir(scope: str, domain_tag: str | None) -> Path:
    if scope == "S0":
        return Path("universal")
    if scope == "S2":
        if not domain_tag:
            raise ValueError("S2 requires a non-empty domain_tag")
        return Path("domain") / domain_tag
    if scope == "S3":
        return Path("local")
    raise ValueError(f"unsupported scope: {scope!r}")


def _parse_existing_fingerprints(learned_dir: Path) -> set[str]:
    found: set[str] = set()
    if not learned_dir.exists():
        return found
    for f in learned_dir.rglob("*"):
        if f.suffix not in {".md", ".mdc"} or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^rule_fingerprint:\s*(\S+)\s*$", text, re.MULTILINE)
        if m:
            found.add(m.group(1))
    return found


def _word_set(s: str) -> set[str]:
    return set(re.findall(r"\b\w{4,}\b", s.lower()))


def _cosine_word_sets(a: str, b: str) -> float:
    """Cosine similarity on binary word-presence vectors (sqrt-normalized overlap).

    This is **not** Jaccard: for the same token sets, cosine is typically higher than Jaccard.
    The ``_SEMANTIC_DEDUP_THRESHOLD`` is tuned for this cosine, not for Jaccard-equivalence.
    """
    A, B = _word_set(a), _word_set(b)
    if not A or not B:
        return 0.0
    inter = len(A & B)
    return inter / (math.sqrt(len(A)) * math.sqrt(len(B)))


def _cluster_signature_text(cluster: CommentCluster) -> str:
    parts = [cluster.title, cluster.severity, cluster.preventability]
    parts.extend(cluster.representative_examples[:3])
    return "\n".join(parts)


def _max_similarity_to_existing(signature: str, bodies: list[str]) -> float:
    return max((_cosine_word_sets(signature, b) for b in bodies), default=0.0)


def _extract_themes_section(markdown: str) -> str:
    """Body slice used for semantic dedup (avoids shared boilerplate in every rule file)."""
    m = re.search(
        r"^## Representative themes\s*\n\n(.*?)(?=^## |\Z)",
        markdown,
        re.MULTILINE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def _collect_existing_dedup_texts(claude_root: Path) -> list[str]:
    if not claude_root.exists():
        return []
    out: list[str] = []
    for f in claude_root.rglob("*.md"):
        body = f.read_text(encoding="utf-8", errors="replace")
        themes = _extract_themes_section(body)
        out.append(themes if themes else body)
    return out


def _build_rule_markdown(
    cluster: CommentCluster,
    repo: str,
    *,
    fingerprint: str,
    mined_at: str,
    path_scope_key: str,
    scope: str,
    domain_yaml: str,
    frequency_across_repos: int,
    source_repos: list[str],
) -> tuple[str, str]:
    """Return (title_human, markdown_body_including_frontmatter).

    Caller supplies resolved ``domain_yaml``, ``frequency_across_repos``, and ``source_repos``.
    """
    title_human = cluster.title.replace(" / ", " ").title()[:80]
    if not title_human.strip():
        title_human = f"Pattern {fingerprint}"

    pr_nums = sorted(
        {c.pr_number for c in cluster.comments if c.pr_number is not None},
    )
    n_pr = len(pr_nums)
    if n_pr == 0:
        pr_part = "unknown PRs"
    elif n_pr == 1:
        pr_part = "1 PR"
    else:
        pr_part = f"{n_pr} PRs"

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
            f"scope: {scope}",
            f'domain_tag: "{domain_yaml}"',
            f"frequency_across_repos: {frequency_across_repos}",
            "source_repos:",
        ]
    )
    for s in sorted(source_repos):
        lines.append(f'  - "{s}"')
    lines.extend(
        [
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


_PM_LEARNED_LINE = re.compile(
    r"^-\s*\(process-miner\)\s+New learned rule file\(s\):\s*.*$",
)


def _merge_agents_learned_paths(repo_root: Path, agents_md_path: Path, written: list[str]) -> str:
    """Append a line inside the process-miner learned block (preserve existing block content)."""
    if not written:
        return ""
    agents_file = repo_root / agents_md_path
    if not agents_file.is_file():
        return ""
    new_line = "- (process-miner) New learned rule file(s): " + ", ".join(sorted(set(written)))
    start_marker = "<!-- process-miner:learned:start -->"
    end_marker = "<!-- process-miner:learned:end -->"
    text = agents_file.read_text(encoding="utf-8")
    if start_marker in text and end_marker in text:
        si = text.index(start_marker) + len(start_marker)
        ei = text.index(end_marker)
        inner = text[si:ei]
        kept: list[str] = []
        for ln in inner.splitlines():
            if _PM_LEARNED_LINE.match(ln.strip()):
                continue
            kept.append(ln)
        body_inner = "\n".join(kept).rstrip("\n")
        chunk = f"\n{body_inner}\n{new_line}\n" if body_inner else f"\n{new_line}\n"
        text = text[:si] + chunk + text[ei:]
    else:
        block = f"\n{start_marker}\n{new_line}\n{end_marker}\n"
        marker = "## Learned Workspace Facts"
        if marker in text:
            text = text.replace(marker, marker + block, 1)
        else:
            text = text.rstrip() + "\n" + block
    agents_file.write_text(text, encoding="utf-8")
    return f"updated {agents_file}"


def emit_learned_artifacts(
    result: AnalysisResult,
    *,
    repo: str,
    repo_root: Path,
    min_occurrences: int = 3,
    min_distinct_prs: int = 2,
    agents_md_path: Path | None = None,
    scope: str = "S3",
    domain_tag: str | None = None,
    frequency_across_repos: int | None = None,
    source_repos: list[str] | None = None,
    written_paths_out: list[str] | None = None,
    cross_repo_title_repo_count: int | None = None,
) -> tuple[str, int]:
    """Write learned rules under scoped subdirectories (#70).

    Skips boilerplate clusters, enforces distinct PR counts, stricter nit thresholds,
    fingerprint dedup, and semantic dedup (cosine on word-presence vs existing rules).

    When ``cross_repo_title_repo_count >= 2``, per-cluster ``min_occurrences`` and
    ``min_distinct_prs`` gates are skipped — the title already met fleet breadth in
    aggregate (S0/S2). Boilerplate, nit-bar, and semantic dedup still apply.
    """
    mined_at = datetime.now(UTC).date().isoformat()
    if scope == "S0":
        dom = ""
    elif domain_tag is not None:
        dom = domain_tag
    else:
        dom = domain_for_repo(repo) or ""
    if scope == "S2" and not dom.strip():
        raise ValueError(
            "scope='S2' requires a non-empty domain_tag or a repo slug resolvable via "
            "domain_for_repo()"
        )
    freq = frequency_across_repos if frequency_across_repos is not None else 1
    src = list(source_repos) if source_repos is not None else [repo]

    sub = _scope_subdir(scope, dom if scope == "S2" else None)
    claude_dir = repo_root / CLAUDE_LEARNED / sub
    cursor_dir = repo_root / CURSOR_LEARNED / sub
    claude_dir.mkdir(parents=True, exist_ok=True)
    cursor_dir.mkdir(parents=True, exist_ok=True)

    claude_root = repo_root / CLAUDE_LEARNED
    existing_texts = _collect_existing_dedup_texts(claude_root)

    claude_existing = _parse_existing_fingerprints(claude_root)
    cursor_existing = _parse_existing_fingerprints(repo_root / CURSOR_LEARNED)

    written: list[str] = []
    clusters_written = 0
    new_file_count = 0
    skipped_dup = 0
    skipped_small = 0
    skipped_pr = 0
    skipped_nit = 0
    skipped_boiler = 0
    skipped_semantic = 0

    cross_volume_ok = cross_repo_title_repo_count is not None and cross_repo_title_repo_count >= 2

    for cluster in result.clusters:
        skip = emit_prefilter_skip_reason(
            cluster,
            cross_volume_ok=cross_volume_ok,
            min_occurrences=min_occurrences,
            min_distinct_prs=min_distinct_prs,
        )
        if skip == "small":
            skipped_small += 1
            continue
        if skip == "pr":
            skipped_pr += 1
            continue
        if skip == "nit":
            skipped_nit += 1
            continue
        if skip == "boiler":
            skipped_boiler += 1
            continue

        sig = _cluster_signature_text(cluster)
        if _max_similarity_to_existing(sig, existing_texts) >= _SEMANTIC_DEDUP_THRESHOLD:
            skipped_semantic += 1
            continue

        fp = _rule_fingerprint(cluster)
        have_claude = fp in claude_existing
        have_cursor = fp in cursor_existing
        if have_claude and have_cursor:
            skipped_dup += 1
            continue

        _, body_claude = _build_rule_markdown(
            cluster,
            repo,
            fingerprint=fp,
            mined_at=mined_at,
            path_scope_key="paths",
            scope=scope,
            domain_yaml=dom,
            frequency_across_repos=freq,
            source_repos=list(src),
        )
        _, body_cursor = _build_rule_markdown(
            cluster,
            repo,
            fingerprint=fp,
            mined_at=mined_at,
            path_scope_key="globs",
            scope=scope,
            domain_yaml=dom,
            frequency_across_repos=freq,
            source_repos=list(src),
        )
        slug = _slugify(cluster.title)
        fname = f"{slug}-{fp[:8]}.md"
        stem = Path(fname).stem
        rel_claude = (CLAUDE_LEARNED / sub / fname).as_posix()
        rel_cursor = (CURSOR_LEARNED / sub / f"{stem}.mdc").as_posix()

        wrote = False
        if not have_claude:
            (claude_dir / fname).write_text(body_claude, encoding="utf-8")
            claude_existing.add(fp)
            existing_texts.append(
                _extract_themes_section(body_claude) or body_claude,
            )
            new_file_count += 1
            wrote = True
        if not have_cursor:
            (cursor_dir / f"{stem}.mdc").write_text(body_cursor, encoding="utf-8")
            cursor_existing.add(fp)
            new_file_count += 1
            wrote = True
        if wrote:
            clusters_written += 1
            if not have_claude:
                written.append(rel_claude)
                if written_paths_out is not None:
                    written_paths_out.append(rel_claude)
            if not have_cursor:
                written.append(rel_cursor)
                if written_paths_out is not None:
                    written_paths_out.append(rel_cursor)

    merge_msg = (
        _merge_agents_learned_paths(repo_root, agents_md_path, written)
        if agents_md_path and written
        else ""
    )
    agents_note = f"; {merge_msg}" if merge_msg else ""

    summary = (
        f"emit: wrote {new_file_count} learned artifact file(s) across {clusters_written} "
        f"cluster(s){agents_note}; "
        f"skipped {skipped_small} below threshold; {skipped_pr} few-PR; {skipped_nit} nit-bar; "
        f"{skipped_boiler} boilerplate; {skipped_semantic} semantic-dedup; "
        f"{skipped_dup} duplicates (fingerprint)"
    )
    return summary, new_file_count


def emit_cross_repo_learned(
    agg: AggregateResult,
    repo_root: Path,
    *,
    agents_md_path: Path | None = None,
) -> tuple[str, int]:
    """Emit S0 universal and S2 domain rules from a fleet aggregate (#70)."""
    from tools.process_miner.aggregate import (
        best_emittable_cluster_for_title,
        cluster_title_to_repos,
        find_domain_scope_titles,
        find_universal_scope_titles,
    )

    if not isinstance(agg, AggregateResult):
        raise TypeError("agg must be AggregateResult")

    per_repo = agg.per_repo
    title_repos = cluster_title_to_repos(per_repo)
    slug_domain = {s: domain_for_repo(s) for s in per_repo}
    universal = find_universal_scope_titles(title_repos, slug_domain)
    domain_map = find_domain_scope_titles(title_repos, slug_domain, universal, min_repos=2)

    total_written = 0
    parts: list[str] = []
    acc_paths: list[str] = []

    for title_key in sorted(universal):
        repos = sorted(title_repos.get(title_key, ()))
        picked = best_emittable_cluster_for_title(
            per_repo,
            title_key,
            cross_volume_ok=len(repos) >= 2,
            min_occurrences=3,
            min_distinct_prs=2,
        )
        if picked is None:
            continue
        src_slug, cluster = picked
        summary, n = emit_learned_artifacts(
            AnalysisResult(
                prs=[],
                clusters=[cluster],
                ci_failures=[],
                churned_files=[],
                stats={"pr_count": 0},
            ),
            repo=src_slug,
            repo_root=repo_root,
            min_occurrences=3,
            min_distinct_prs=2,
            agents_md_path=None,
            scope="S0",
            domain_tag=None,
            frequency_across_repos=len(repos),
            source_repos=repos,
            written_paths_out=acc_paths,
            cross_repo_title_repo_count=len(repos),
        )
        parts.append(summary)
        total_written += n

    for title_key in sorted(domain_map):
        dom = domain_map[title_key]
        repos = sorted(title_repos.get(title_key, ()))
        picked = best_emittable_cluster_for_title(
            per_repo,
            title_key,
            cross_volume_ok=len(repos) >= 2,
            min_occurrences=3,
            min_distinct_prs=2,
        )
        if picked is None:
            continue
        src_slug, cluster = picked
        summary, n = emit_learned_artifacts(
            AnalysisResult(
                prs=[],
                clusters=[cluster],
                ci_failures=[],
                churned_files=[],
                stats={"pr_count": 0},
            ),
            repo=src_slug,
            repo_root=repo_root,
            min_occurrences=3,
            min_distinct_prs=2,
            agents_md_path=None,
            scope="S2",
            domain_tag=dom,
            frequency_across_repos=len(repos),
            source_repos=repos,
            written_paths_out=acc_paths,
            cross_repo_title_repo_count=len(repos),
        )
        parts.append(summary)
        total_written += n

    merge_msg = (
        _merge_agents_learned_paths(repo_root, agents_md_path, acc_paths)
        if agents_md_path and acc_paths
        else ""
    )
    agents_note = f"; {merge_msg}" if merge_msg else ""

    merged = (
        " | ".join(parts) if parts else "emit_cross_repo: no qualifying clusters"
    ) + agents_note
    return merged, total_written


def append_hook_suggestions_to_report(
    result: AnalysisResult,
    report_path: Path,
) -> None:
    """Append diff-style hook suggestions for automation-tagged clusters (not auto-applied)."""
    automation = [
        c
        for c in result.clusters
        if c.preventability == "automation" and c.count >= 3 and c.distinct_pr_count >= 2
    ]
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
    "emit_cross_repo_learned",
    "emit_learned_artifacts",
    "_paths_to_globs",
    "_rule_fingerprint",
]
