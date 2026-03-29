"""Build Supervised Fine-Tuning (SFT) records from repo knowledge SQLite rows."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, TextIO

SYSTEM_REVIEWER = (
    "You are a repository-specific code reviewer. Given file and PR context "
    "(placeholders until diff hunks are wired in Tier 2), produce concise review feedback."
)


def user_content_for_evidence(
    *,
    pr_number: int | None,
    file_path: str | None,
    line_number: int | None,
    pattern_text: str,
) -> str:
    """Synthetic \"diff\" placeholder: real hunks replace this in a later phase."""
    pr_s = f"#{pr_number}" if pr_number is not None else "(unknown)"
    path_s = file_path or "(unknown)"
    line_s = str(line_number) if line_number is not None else "(n/a)"
    return (
        "Repository review context (placeholder; PR diff hunks not yet embedded):\n"
        f"- PR: {pr_s}\n"
        f"- File: {path_s}\n"
        f"- Line: {line_s}\n"
        f"- Related pattern theme: {pattern_text}\n"
    )


def evidence_row_to_sft_record(row: dict[str, Any]) -> dict[str, Any]:
    """One training example from ``pattern_evidence`` joined with ``patterns``."""
    body = (row.get("comment_body") or "").strip()
    user = user_content_for_evidence(
        pr_number=row.get("pr_number"),
        file_path=row.get("file_path"),
        line_number=row.get("line_number"),
        pattern_text=str(row.get("pattern_text") or ""),
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_REVIEWER},
            {"role": "user", "content": user},
            {"role": "assistant", "content": body},
        ],
        "metadata": {
            "source": "pattern_evidence",
            "pattern_id": row.get("pattern_id"),
            "evidence_id": row.get("id"),
            "pr_number": row.get("pr_number"),
        },
    }


def decision_row_to_sft_record(row: dict[str, Any]) -> dict[str, Any]:
    """Optional SFT line from vault-backed ``decisions`` rows."""
    vault_path = row.get("vault_path") or ""
    area = row.get("affected_paths") or ""
    title = (row.get("decision_text") or "").strip()
    user = (
        "Summarize this architecture decision for someone implementing a change:\n"
        f"- Vault path: {vault_path}\n"
        f"- Area tag: {area}\n"
    )
    return {
        "messages": [
            {
                "role": "system",
                "content": "You explain recorded architecture decisions clearly and briefly.",
            },
            {"role": "user", "content": user},
            {"role": "assistant", "content": title},
        ],
        "metadata": {"source": "decisions", "vault_path": vault_path},
    }


def write_jsonl(records: Iterable[dict[str, Any]], fh: TextIO) -> int:
    """Write one JSON object per line; returns number of records written."""
    n = 0
    for rec in records:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n += 1
    return n
