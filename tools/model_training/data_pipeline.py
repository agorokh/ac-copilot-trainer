"""Export knowledge DB + miner-shaped evidence into training JSONL (Phase 1)."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tools.model_training.format_sft import (
    decision_row_to_sft_record,
    evidence_row_to_sft_record,
    write_jsonl,
)
from tools.process_miner.analyze import classify_severity
from tools.process_miner.bot_authorship import (
    BOT_REVIEW_TEXT_CLIP_CHARS,
    distinct_bot_names_for_pr,
)
from tools.process_miner.schemas import PRData, ReviewComment

# Tier 1 export: no unified diff text in PR snapshots; non-empty placeholder documents intent (#56).
MULTI_BOT_DIFF_HUNK_PLACEHOLDER = (
    "(diff hunk not embedded in miner export v1; use bot comment bodies)"
)


def _open_source_readonly(source_db: Path) -> sqlite3.Connection:
    """Open SQLite read-only — export must not mutate or re-apply schema on the source DB."""
    uri = source_db.expanduser().resolve().as_uri()
    conn = sqlite3.connect(f"{uri}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _iter_evidence_rows(conn: sqlite3.Connection) -> Iterator[dict[str, object]]:
    """Stream joined evidence+pattern rows as dicts (ordered by evidence id)."""
    cur = conn.execute(
        """
        SELECT
            pe.id AS id,
            pe.pattern_id AS pattern_id,
            pe.pr_number AS pr_number,
            pe.comment_author AS comment_author,
            pe.comment_body AS comment_body,
            pe.file_path AS file_path,
            pe.line_number AS line_number,
            pe.created_at AS created_at,
            p.pattern_text AS pattern_text,
            p.severity AS severity,
            p.preventability AS preventability
        FROM pattern_evidence pe
        JOIN patterns p ON p.id = pe.pattern_id
        ORDER BY pe.id
        """
    )
    yield from (dict(r) for r in cur)


def _iter_decision_rows(conn: sqlite3.Connection) -> Iterator[dict[str, object]]:
    """Stream ``decisions`` table rows as dicts (ordered by id)."""
    cur = conn.execute(
        """
        SELECT vault_path, decision_text, rationale, affected_paths, created_at
        FROM decisions
        ORDER BY id
        """
    )
    yield from (dict(r) for r in cur)


def _multi_bot_record(
    *,
    pr_number: int,
    file_path: str | None,
    line: int | None,
    row_kind: str,
    bot_group: list[ReviewComment],
    human_bodies: list[str],
) -> dict[str, Any]:
    return {
        "schema": "miner_multi_bot_sft_v1",
        "row_kind": row_kind,
        "pr_number": pr_number,
        "file_path": file_path,
        "line": line,
        "diff_hunk": MULTI_BOT_DIFF_HUNK_PLACEHOLDER,
        "bot_comments": [
            {
                "bot": x.bot_name,
                "body": x.body[:BOT_REVIEW_TEXT_CLIP_CHARS],
                "severity": classify_severity(x.body),
                "review_structure": x.review_structure,
            }
            for x in sorted(bot_group, key=lambda z: (z.bot_name or "", z.id))
        ],
        "human_resolution": human_bodies[:20],
    }


def iter_multi_bot_miner_training_records(prs: list[PRData]) -> Iterator[dict[str, Any]]:
    """Yield SFT-oriented rows for PRs with ≥2 distinct review bots (issue #56 / #54).

    Emits one row per (file, line) where ≥2 bots commented (same bucket as
    ``bot_agreement_location_key`` inline keys), then rows for the same file with ``line``
    unset when ≥2 distinct bots left comments there (path-level overlap). Optional
    ``remaining`` rows cover other bot comments that still span ≥2 bots. If no qualifying
    location row exists, emits a single PR-level row with all bot comments.
    ``diff_hunk`` is a documented placeholder until a later tier supplies real hunks.
    """
    for pr in prs:
        all_c = pr.review_comments + pr.issue_comments
        if len(distinct_bot_names_for_pr(pr)) < 2:
            continue
        bot_comments = [c for c in all_c if c.author_type == "bot" and c.bot_name]
        # Human context uses a shorter clip than bot bodies (``BOT_REVIEW_TEXT_CLIP_CHARS``).
        human_bodies = [c.body[:2000] for c in all_c if c.author_type == "human"]
        loc: defaultdict[tuple[str, int], list[ReviewComment]] = defaultdict(list)
        for c in bot_comments:
            if c.path and c.line is not None:
                loc[(c.path, c.line)].append(c)
        emitted_ids: set[str] = set()
        emitted_any = False
        for (path, line), group in sorted(loc.items()):
            if len({x.bot_name for x in group}) < 2:
                continue
            emitted_any = True
            emitted_ids.update(x.id for x in group)
            yield _multi_bot_record(
                pr_number=pr.number,
                file_path=path,
                line=line,
                row_kind="inline_multi_bot",
                bot_group=group,
                human_bodies=human_bodies,
            )
        file_noline: defaultdict[str, list[ReviewComment]] = defaultdict(list)
        for c in bot_comments:
            if c.path and c.line is None and c.id not in emitted_ids:
                file_noline[c.path].append(c)
        for path in sorted(file_noline.keys()):
            group = file_noline[path]
            if len({x.bot_name for x in group}) < 2:
                continue
            emitted_any = True
            emitted_ids.update(x.id for x in group)
            yield _multi_bot_record(
                pr_number=pr.number,
                file_path=path,
                line=None,
                row_kind="file_level_multi_bot",
                bot_group=group,
                human_bodies=human_bodies,
            )
        if not emitted_any:
            yield _multi_bot_record(
                pr_number=pr.number,
                file_path=None,
                line=None,
                row_kind="pr_all_bots",
                bot_group=bot_comments,
                human_bodies=human_bodies,
            )
            continue
        remaining = [c for c in bot_comments if c.id not in emitted_ids]
        if len({c.bot_name for c in remaining}) >= 2:
            yield _multi_bot_record(
                pr_number=pr.number,
                file_path=None,
                line=None,
                row_kind="remaining_multi_bot",
                bot_group=remaining,
                human_bodies=human_bodies,
            )


def write_multi_bot_miner_training_jsonl(prs: list[PRData], out_path: Path) -> int:
    """Write ``iter_multi_bot_miner_training_records`` to JSONL; returns row count."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            n = write_jsonl(iter_multi_bot_miner_training_records(prs), fh)
        os.replace(tmp, out_path)
        return n
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def run_pipeline(source_db: Path, output_dir: Path) -> tuple[Path, Path]:
    """Write ``sft_pairs.jsonl`` (evidence) and ``sft_decisions.jsonl`` (vault decisions).

    Returns paths ``(sft_pairs, sft_decisions)``.
    """
    if not source_db.is_file():
        raise FileNotFoundError(f"Source database not found (expected a file): {source_db}")

    output_dir.mkdir(parents=True, exist_ok=True)
    sft_pairs_path = output_dir / "sft_pairs.jsonl"
    sft_decisions_path = output_dir / "sft_decisions.jsonl"

    conn = _open_source_readonly(source_db)
    try:

        def iter_evidence_sft() -> Iterator[dict[str, Any]]:
            """Yield SFT dicts for evidence rows that have non-empty comment bodies."""
            for row in _iter_evidence_rows(conn):
                if (str(row.get("comment_body") or "")).strip():
                    yield evidence_row_to_sft_record(row)

        def iter_decision_sft() -> Iterator[dict[str, Any]]:
            """Yield SFT dicts for decision rows that have non-empty decision text."""
            for row in _iter_decision_rows(conn):
                if (str(row.get("decision_text") or "")).strip():
                    yield decision_row_to_sft_record(row)

        pairs_tmp = output_dir / (sft_pairs_path.name + ".tmp")
        dec_tmp = output_dir / (sft_decisions_path.name + ".tmp")
        try:
            with pairs_tmp.open("w", encoding="utf-8") as fh:
                write_jsonl(iter_evidence_sft(), fh)
            with dec_tmp.open("w", encoding="utf-8") as fh:
                write_jsonl(iter_decision_sft(), fh)
            os.replace(pairs_tmp, sft_pairs_path)
            os.replace(dec_tmp, sft_decisions_path)
        finally:
            for tmp in (pairs_tmp, dec_tmp):
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
    finally:
        conn.close()

    return sft_pairs_path, sft_decisions_path


def main(argv: list[str] | None = None) -> int:
    """Parse CLI args and export ``--source`` knowledge DB to JSONL under ``--output``."""
    p = argparse.ArgumentParser(
        description="Export repo knowledge SQLite to SFT JSONL placeholders (issue #26 Phase 1)."
    )
    p.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Path to knowledge.db (e.g. .cache/repo_knowledge/knowledge.db)",
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory (e.g. .cache/training_data/)",
    )
    args = p.parse_args(argv)
    try:
        pairs, decisions = run_pipeline(args.source, args.output)
    except FileNotFoundError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    print(f"Wrote {pairs} and {decisions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
