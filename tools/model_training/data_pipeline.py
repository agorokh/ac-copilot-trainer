"""Export knowledge DB + miner-shaped evidence into training JSONL (Phase 1)."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tools.model_training.format_sft import (
    decision_row_to_sft_record,
    evidence_row_to_sft_record,
    write_jsonl,
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
