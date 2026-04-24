"""Vault content mining via GitHub API, health scoring, and SAVE compliance (#73)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from tools.process_miner.simple_frontmatter import extract_relates_to, parse_simple_frontmatter

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from tools.process_miner.github_client import GitHubClient
    from tools.process_miner.schemas import PRData


class VaultAuditError(RuntimeError):
    """Vault tree or content collection failed (API, auth, network, or permission)."""


VAULT_PREFIX = "docs/01_Vault/"
SESSION_MARKERS = ("Next Session Handoff.md", "Current Focus.md")
SECURITY_MARKERS = ("security", "invariant", "investigation", "threat", "cve")


@dataclass
class VaultNode:
    """One markdown vault file discovered via GitHub API."""

    path: str
    node_type: str | None
    status: str | None
    last_updated: datetime | None
    relates_to: list[str] = field(default_factory=list)
    frontmatter_ok: bool = False


@dataclass
class VaultAuditResult:
    """Structured vault audit + scores for reporting and SQLite."""

    repo: str
    vault_exists: bool
    tree_truncated: bool
    nodes: list[VaultNode]
    health_score: int
    freshness_score: float
    depth_score: float
    frontmatter_score: float
    connectivity_score: float
    coverage_score: float
    coverage_gaps: list[str]
    broken_links: list[str]
    broken_links_total: int
    save_compliant_prs: int
    save_total_prs: int
    save_rate: float
    handoff_last_updated: datetime | None
    last_pr_merged_at: datetime | None

    def to_stats_dict(self) -> dict[str, Any]:
        return {
            "vault_exists": self.vault_exists,
            "tree_truncated": self.tree_truncated,
            "node_count": len(self.nodes),
            "health_score": self.health_score,
            "freshness": round(self.freshness_score, 3),
            "depth": round(self.depth_score, 3),
            "frontmatter": round(self.frontmatter_score, 3),
            "connectivity": round(self.connectivity_score, 3),
            "coverage": round(self.coverage_score, 3),
            "save_compliant_prs": self.save_compliant_prs,
            "save_total_prs": self.save_total_prs,
            "save_rate": round(self.save_rate, 3),
            "coverage_gaps": list(self.coverage_gaps),
            "broken_links_count": self.broken_links_total,
            "handoff_last_updated": self.handoff_last_updated.isoformat()
            if self.handoff_last_updated
            else None,
            "last_pr_merged_at": self.last_pr_merged_at.isoformat()
            if self.last_pr_merged_at
            else None,
        }


def _session_path_hit(path: str) -> bool:
    pl = path.replace("\\", "/").lower()
    return any(m.lower() in pl for m in SESSION_MARKERS)


def _merged_pr_save_compliant(
    client: GitHubClient,
    owner: str,
    repo: str,
    ref: str,
    p: PRData,
    session_paths: list[str],
) -> bool:
    """SAVE: PR touches session files in its diff, or a commit within 24h after merge does."""
    if any(_session_path_hit(f.path) for f in p.files):
        return True
    if not p.merged_at or not session_paths:
        return False
    merge = p.merged_at
    if merge.tzinfo is None:
        merge = merge.replace(tzinfo=UTC)
    window_end = merge + timedelta(hours=24)
    for sp in session_paths:
        try:
            commits = client.list_commits_for_path(
                owner,
                repo,
                sp,
                sha=ref,
                since=merge,
                until=window_end,
                per_page=20,
            )
        except Exception:
            logger.warning(
                "vault audit: SAVE 24h commit query failed for %s/%s path=%s",
                owner,
                repo,
                sp,
                exc_info=True,
            )
            continue
        for c in commits:
            d_raw = (c.get("commit") or {}).get("committer", {}).get("date")
            if not d_raw:
                continue
            d = datetime.fromisoformat(str(d_raw).replace("Z", "+00:00"))
            if merge <= d <= window_end:
                return True
    return False


def _vault_text_blob_paths(entries: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for e in entries:
        if e.get("type") != "blob":
            continue
        p = str(e.get("path", ""))
        if p.startswith(VAULT_PREFIX) and p.endswith(".md"):
            paths.append(p)
    return sorted(paths)


def _security_cluster_titles(clusters: list[Any]) -> list[str]:
    out: list[str] = []
    for c in clusters:
        sev = getattr(c, "severity", "") or ""
        if str(sev).lower() == "security":
            out.append(getattr(c, "title", "") or "")
    return out


def _vault_covers_security(nodes: list[VaultNode], body_lower: dict[str, str]) -> bool:
    for n in nodes:
        pl = n.path.lower()
        if any(m in pl for m in SECURITY_MARKERS):
            return True
        blob = body_lower.get(n.path, "")
        if any(m in blob for m in SECURITY_MARKERS):
            return True
        nt = (n.node_type or "").lower()
        if "security" in nt or "invariant" in nt:
            return True
    return False


def collect_vault_audit(
    client: GitHubClient,
    owner: str,
    repo: str,
    *,
    branch: str,
    prs: list[PRData],
    clusters: list[Any],
    max_md_files: int = 200,
) -> VaultAuditResult:
    """Fetch vault tree + markdown bodies, compute subscores and SAVE compliance."""
    slug = f"{owner}/{repo}"
    nodes: list[VaultNode] = []
    tree_truncated = False
    vault_exists = False
    body_by_path: dict[str, str] = {}
    body_lower: dict[str, str] = {}

    try:
        tip_sha, tree_sha = client.get_branch_tip(owner, repo, branch)
        entries, tree_truncated = client.get_recursive_tree(owner, repo, tree_sha)
    except Exception as e:
        logger.warning(
            "vault audit: failed to load tree for %s/%s@%s: %s",
            owner,
            repo,
            branch,
            e,
        )
        raise VaultAuditError(f"vault tree load failed for {owner}/{repo}: {e}") from e

    md_all = _vault_text_blob_paths(entries)
    vault_exists = bool(md_all)
    marker_set = {p for p in md_all if _session_path_hit(p)}
    marker_paths = sorted(marker_set)
    rest = [p for p in md_all if p not in marker_set]
    ordered = marker_paths + rest
    if len(ordered) > max_md_files:
        md_paths = ordered[:max_md_files]
    else:
        md_paths = ordered
    for path in md_paths:
        try:
            text = client.get_contents_text(owner, repo, path, ref=tip_sha)
        except Exception as e:
            logger.warning(
                "vault audit: skip content fetch %s/%s:%s: %s",
                owner,
                repo,
                path,
                e,
            )
            continue
        if text is None:
            continue
        body_by_path[path] = text
        body_lower[path] = text.lower()
        meta, _ = parse_simple_frontmatter(text)
        relates = extract_relates_to(text[:120_000]) if text.startswith("---") else []
        ntype = meta.get("type")
        st = meta.get("status")
        fm_ok = bool(ntype and st)
        lu: datetime | None = None
        if "next session handoff.md" in path.replace("\\", "/").lower():
            c = client.get_latest_commit_for_path(owner, repo, path, ref=tip_sha)
            if c and c.get("commit", {}).get("committer", {}).get("date"):
                lu = datetime.fromisoformat(
                    str(c["commit"]["committer"]["date"]).replace("Z", "+00:00")
                )
        nodes.append(
            VaultNode(
                path=path,
                node_type=ntype,
                status=st,
                last_updated=lu,
                relates_to=relates,
                frontmatter_ok=fm_ok,
            )
        )

    vault_tree_md_set = set(md_all)
    broken: list[str] = []
    internal_relates_checked = 0
    for n in nodes:
        for target in n.relates_to:
            t = target.strip()
            if not t or t.startswith("http"):
                continue
            internal_relates_checked += 1
            cand1 = f"{VAULT_PREFIX}{t}.md" if not t.endswith(".md") else f"{VAULT_PREFIX}{t}"
            cand2 = f"{VAULT_PREFIX}{t}"
            if t.startswith("AcCopilotTrainer/"):
                cand1 = f"{VAULT_PREFIX}{t}"
                cand2 = cand1 + ("" if cand1.endswith(".md") else ".md")
            if cand1 not in vault_tree_md_set and cand2 not in vault_tree_md_set:
                resolved = False
                if "/" in t:
                    alt = f"{VAULT_PREFIX}{t.lstrip('/')}"
                    resolved = alt in vault_tree_md_set or alt + ".md" in vault_tree_md_set
                if not resolved:
                    broken.append(f"{n.path} -> {t}")

    merged = [p for p in prs if p.merged_at]
    last_pr_merged = max((p.merged_at for p in merged if p.merged_at), default=None)

    handoff_lu: datetime | None = None
    for n in nodes:
        if "next session handoff.md" not in n.path.replace("\\", "/").lower():
            continue
        if n.last_updated and (handoff_lu is None or n.last_updated > handoff_lu):
            handoff_lu = n.last_updated

    # Freshness: handoff age vs last merge
    freshness = 0.0
    if not vault_exists:
        freshness = 0.0
    elif handoff_lu and last_pr_merged:
        delta_days = (last_pr_merged - handoff_lu).total_seconds() / 86400.0
        if delta_days <= 1:
            freshness = 1.0
        elif delta_days <= 7:
            freshness = 0.85
        elif delta_days <= 14:
            freshness = 0.6
        elif delta_days <= 30:
            freshness = 0.35
        else:
            freshness = 0.15
    elif handoff_lu:
        freshness = 0.7
    else:
        freshness = 0.2

    pr_n = max(len(merged), 1)
    expected_nodes = max(8, min(80, pr_n * 3))
    depth = min(1.0, len(nodes) / expected_nodes) if vault_exists else 0.0

    if nodes:
        fm_ok_n = sum(1 for n in nodes if n.frontmatter_ok)
        frontmatter = fm_ok_n / len(nodes)
    else:
        frontmatter = 0.0

    if internal_relates_checked == 0:
        connectivity = 0.4 if vault_exists else 0.0
    else:
        connectivity = max(0.0, 1.0 - (len(broken) / internal_relates_checked))

    sec_titles = _security_cluster_titles(clusters)
    coverage_gaps: list[str] = []
    if sec_titles and not _vault_covers_security(nodes, body_lower):
        coverage_gaps.append(
            "Miner reported security-severity clusters but no security/invariant vault nodes"
        )
    maintainability_clusters = [
        c for c in clusters if getattr(c, "severity", "") == "maintainability"
    ]
    if len(maintainability_clusters) >= 3 and not any(
        "decision" in (n.node_type or "").lower() for n in nodes
    ):
        coverage_gaps.append(
            "Many maintainability clusters; vault has few or no typed decision nodes"
        )
    coverage = 1.0 if not coverage_gaps else max(0.25, 1.0 - 0.35 * len(coverage_gaps))

    health = round(
        100
        * (
            0.25 * freshness
            + 0.20 * depth
            + 0.20 * frontmatter
            + 0.15 * connectivity
            + 0.20 * coverage
        )
    )
    health = max(0, min(100, health))

    session_paths = sorted({vp for vp in body_by_path if _session_path_hit(vp)})

    compliant = 0
    total_save = 0
    for p in merged:
        total_save += 1
        if _merged_pr_save_compliant(client, owner, repo, tip_sha, p, session_paths):
            compliant += 1

    save_rate = (compliant / total_save) if total_save else 0.0

    return VaultAuditResult(
        repo=slug,
        vault_exists=vault_exists,
        tree_truncated=tree_truncated,
        nodes=nodes,
        health_score=health,
        freshness_score=freshness,
        depth_score=depth,
        frontmatter_score=frontmatter,
        connectivity_score=connectivity,
        coverage_score=coverage,
        coverage_gaps=coverage_gaps,
        broken_links=broken[:50],
        broken_links_total=len(broken),
        save_compliant_prs=compliant,
        save_total_prs=total_save,
        save_rate=save_rate,
        handoff_last_updated=handoff_lu,
        last_pr_merged_at=last_pr_merged,
    )


def render_vault_health_markdown(audit: VaultAuditResult) -> list[str]:
    """Markdown section for the process miner report."""
    lines = [
        "## Vault Health Assessment",
        "",
        f"- **Repository:** `{audit.repo}`",
        f"- **Vault present:** {audit.vault_exists}",
        f"- **Tree truncated (GitHub API):** {audit.tree_truncated}",
        f"- **Markdown nodes scanned:** {len(audit.nodes)}",
        f"- **Composite health score:** {audit.health_score}/100",
        "",
        "### Subscores (weights: freshness 25%, depth 20%, frontmatter 20%, "
        "connectivity 15%, coverage 20%)",
        "",
        f"- **Freshness:** {audit.freshness_score:.2f} (handoff vs last merged PR in window)",
        f"- **Depth:** {audit.depth_score:.2f}",
        f"- **Frontmatter validity:** {audit.frontmatter_score:.2f}",
        f"- **Connectivity:** {audit.connectivity_score:.2f}",
        f"- **Coverage (vs miner clusters):** {audit.coverage_score:.2f}",
        "",
        "### Session lifecycle (SAVE)",
        "",
        f"- **SAVE compliance:** {audit.save_compliant_prs}/{audit.save_total_prs} "
        "merged PRs: session paths in the **PR file list**, or any **commit within 24h after "
        "merge** touching handoff/current-focus paths (GitHub commits API per path).",
        f"- **Rate:** {audit.save_rate:.0%}",
        "",
    ]
    if audit.handoff_last_updated:
        h = audit.handoff_last_updated.isoformat()
        lines.append(f"- **Handoff last commit (default branch):** {h}")
    if audit.last_pr_merged_at:
        lines.append(f"- **Newest merged PR in window:** {audit.last_pr_merged_at.isoformat()}")
    lines.append("")
    if audit.coverage_gaps:
        lines.append("### Coverage gaps")
        lines.append("")
        lines.extend(f"- {g}" for g in audit.coverage_gaps)
        lines.append("")
    if audit.broken_links:
        lines.append("### Suspected broken `relates_to` targets (sample)")
        lines.append("")
        lines.extend(f"- `{b}`" for b in audit.broken_links[:15])
        lines.append("")
    lines.append("---")
    lines.append("")
    return lines


def vault_audit_json_for_aggregate(audit: VaultAuditResult | None) -> dict[str, Any] | None:
    if audit is None:
        return None
    return {
        "health_score": audit.health_score,
        "node_count": len(audit.nodes),
        "save_rate": round(audit.save_rate, 3),
        "coverage_gaps": audit.coverage_gaps,
    }


def render_vault_health_failure(exc: BaseException) -> list[str]:
    """Minimal Vault Health section when auditing raises (report still documents the failure)."""
    msg = str(exc).replace("\n", " ")[:500]
    return [
        "## Vault Health Assessment",
        "",
        f"- **Status:** audit failed — `{exc.__class__.__name__}`: {msg}",
        "- **Action:** Check `GITHUB_TOKEN` scopes, rate limits, and repository access; retry with "
        "`--audit-vault` after fixing the underlying error.",
        "",
        "---",
        "",
    ]
