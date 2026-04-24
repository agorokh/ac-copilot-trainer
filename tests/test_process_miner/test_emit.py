"""Tests for deterministic rule emission."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.process_miner.emit import (
    _merge_agents_learned_paths,
    _paths_to_globs,
    _rule_fingerprint,
    emit_learned_artifacts,
)
from tools.process_miner.schemas import AnalysisResult, CommentCluster, ReviewComment


def _cluster(count: int = 3) -> CommentCluster:
    comments = [
        ReviewComment(
            id=str(i),
            body="Please add type hints to this public API surface for clarity.",
            author="reviewer",
            created_at=datetime.now(UTC),
            path="src/ac_copilot_trainer/__init__.py",
            line=10 + i,
            pr_number=100 + i,
            is_inline=True,
        )
        for i in range(count)
    ]
    return CommentCluster(
        cluster_id=0,
        title="type / hints / annotation",
        count=count,
        comments=comments,
        affected_files=["src/ac_copilot_trainer/__init__.py"],
        severity="maintainability",
        preventability="typecheck",
        representative_examples=[c.body for c in comments[:3]],
        distinct_pr_count=len({c.pr_number for c in comments if c.pr_number is not None}),
    )


def test_paths_to_globs_posix_and_segments() -> None:
    assert _paths_to_globs(["Makefile"]) == ["**/Makefile"]
    assert _paths_to_globs(["src/pkg/mod.py"]) == ["src/**/*"]
    assert _paths_to_globs(["src/a.py", "Makefile"]) == ["src/**/*", "**/Makefile"]


def test_rule_fingerprint_stable() -> None:
    c1 = _cluster()
    c2 = _cluster()
    assert _rule_fingerprint(c1) == _rule_fingerprint(c2)


def test_emit_writes_and_skips_duplicates(tmp_path: Path) -> None:
    result = AnalysisResult(
        prs=[],
        clusters=[_cluster(3)],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 0},
    )

    summary, n_written = emit_learned_artifacts(
        result,
        repo="o/r",
        repo_root=tmp_path,
        min_occurrences=3,
        agents_md_path=None,
    )
    assert "wrote 2 learned artifact file(s) across 1 cluster(s)" in summary
    assert n_written == 2

    mdc_files = list((tmp_path / ".cursor/rules/learned").rglob("*.mdc"))
    assert len(mdc_files) == 1
    mdc = mdc_files[0]
    mdc_fm = mdc.read_text(encoding="utf-8").split("---", 2)[1]
    assert "globs:" in mdc_fm
    assert "paths:" not in mdc_fm

    md_files = list((tmp_path / ".claude/rules/learned").rglob("*.md"))
    assert len(md_files) == 1
    md = md_files[0]
    md_fm = md.read_text(encoding="utf-8").split("---", 2)[1]
    assert "paths:" in md_fm
    assert "globs:" not in md_fm
    assert "scope: S3" in md_fm

    summary2, n2 = emit_learned_artifacts(
        result,
        repo="o/r",
        repo_root=tmp_path,
        min_occurrences=3,
        agents_md_path=None,
    )
    assert "skipped" in summary2
    assert "duplicates" in summary2
    assert n2 == 0


def test_emit_skips_when_distinct_pr_count_too_low(tmp_path: Path) -> None:
    comments = [
        ReviewComment(
            id=str(i),
            body="Please add type hints to this public API surface for clarity.",
            author="reviewer",
            created_at=datetime.now(UTC),
            path="src/ac_copilot_trainer/__init__.py",
            line=10 + i,
            pr_number=100,
            is_inline=True,
        )
        for i in range(3)
    ]
    cluster = CommentCluster(
        cluster_id=0,
        title="type / hints / annotation",
        count=3,
        comments=comments,
        affected_files=["src/ac_copilot_trainer/__init__.py"],
        severity="maintainability",
        preventability="typecheck",
        representative_examples=[c.body for c in comments[:3]],
        distinct_pr_count=1,
    )
    result = AnalysisResult(
        prs=[],
        clusters=[cluster],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 0},
    )
    summary, n = emit_learned_artifacts(
        result,
        repo="o/r",
        repo_root=tmp_path,
        min_occurrences=3,
        min_distinct_prs=2,
        agents_md_path=None,
    )
    assert n == 0
    assert "few-PR" in summary


def test_emit_cross_repo_skips_local_volume_gates(tmp_path: Path) -> None:
    """S0/S2 pass ``cross_repo_title_repo_count`` so one repo's small cluster can still emit."""
    rc = ReviewComment(
        id="1",
        body="Prefer explicit return types on public helpers in this module.",
        author="r",
        created_at=datetime.now(UTC),
        path="src/x.py",
        line=1,
        pr_number=1,
        is_inline=True,
    )
    cluster = CommentCluster(
        cluster_id=0,
        title="return / types / hints",
        count=1,
        comments=[rc],
        affected_files=["src/x.py"],
        severity="maintainability",
        preventability="typecheck",
        representative_examples=[rc.body],
        distinct_pr_count=1,
    )
    result = AnalysisResult(
        prs=[],
        clusters=[cluster],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 0},
    )
    summary, n = emit_learned_artifacts(
        result,
        repo="o/r",
        repo_root=tmp_path,
        min_occurrences=3,
        min_distinct_prs=2,
        agents_md_path=None,
        cross_repo_title_repo_count=2,
    )
    assert n == 2
    assert "wrote 2" in summary

    summary_local, n_local = emit_learned_artifacts(
        result,
        repo="o/r",
        repo_root=tmp_path,
        min_occurrences=3,
        min_distinct_prs=2,
        agents_md_path=None,
    )
    assert n_local == 0
    assert "below threshold" in summary_local


def test_emit_s2_raises_when_domain_unresolved(tmp_path: Path) -> None:
    """S2 with unknown repo must raise instead of failing inside _scope_subdir."""
    result = AnalysisResult(
        prs=[],
        clusters=[_cluster(3)],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 0},
    )
    with pytest.raises(ValueError, match="scope='S2'"):
        emit_learned_artifacts(
            result,
            repo="unknown/orphan-repo",
            repo_root=tmp_path,
            min_occurrences=3,
            agents_md_path=None,
            scope="S2",
            domain_tag=None,
        )


def test_merge_agents_learned_paths_replaces_prior_process_miner_line(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "# Title\n"
        "<!-- process-miner:learned:start -->\n"
        "- (process-miner) New learned rule file(s): stale.md\n"
        "<!-- process-miner:learned:end -->\n",
        encoding="utf-8",
    )
    _merge_agents_learned_paths(tmp_path, Path("AGENTS.md"), ["fresh.md"])
    text = agents.read_text(encoding="utf-8")
    assert text.count("(process-miner) New learned rule file(s):") == 1
    assert "fresh.md" in text
    assert "stale.md" not in text


def test_merge_agents_learned_paths_appends_inside_block(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "# Title\n"
        "<!-- process-miner:learned:start -->\n"
        "- keep this line\n"
        "<!-- process-miner:learned:end -->\n",
        encoding="utf-8",
    )
    _merge_agents_learned_paths(tmp_path, Path("AGENTS.md"), [".claude/rules/learned/local/x.md"])
    text = agents.read_text(encoding="utf-8")
    assert "keep this line" in text
    assert "New learned rule file(s)" in text
    assert text.index("keep this line") < text.index("New learned rule file(s)")


def test_emit_skips_nit_below_threshold(tmp_path: Path) -> None:
    comments = [
        ReviewComment(
            id=str(i),
            body="nit: spacing",
            author="reviewer",
            created_at=datetime.now(UTC),
            path="src/a.py",
            line=i,
            pr_number=200 + i,
            is_inline=True,
        )
        for i in range(5)
    ]
    cluster = CommentCluster(
        cluster_id=0,
        title="spacing / nit",
        count=5,
        comments=comments,
        affected_files=["src/a.py"],
        severity="nit",
        preventability="guideline",
        representative_examples=[c.body for c in comments[:3]],
        distinct_pr_count=2,
    )
    result = AnalysisResult(
        prs=[],
        clusters=[cluster],
        ci_failures=[],
        churned_files=[],
        stats={"pr_count": 0},
    )
    summary, n = emit_learned_artifacts(
        result,
        repo="o/r",
        repo_root=tmp_path,
        min_occurrences=3,
        agents_md_path=None,
    )
    assert n == 0
    assert "nit-bar" in summary
