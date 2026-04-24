#!/usr/bin/env python3
"""Seed repo knowledge SQLite from canonical markdown (idempotent).

Loads:
- ``AGENTS.md`` — Learned User Preferences + Learned Workspace Facts bullets
- ``AGENT_CORE_PRINCIPLES.md`` — numbered principle lines
- Vault ``invariants/*.md`` under ``AcCopilotTrainer/00_System/invariants/`` (not ``_index.md``)

Pattern rows use ``INSERT … ON CONFLICT(pattern_text) DO NOTHING`` so re-runs are idempotent.
Bootstrap-tagged evidence and decisions are replaced on each run.
"""

from __future__ import annotations

import re
import sqlite3
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.process_miner.simple_frontmatter import parse_simple_frontmatter  # noqa: E402

_BOOTSTRAP_AUTHOR = "bootstrap_knowledge"
_BOOTSTRAP_RATIONALE = "bootstrap_knowledge"

_PROCESS_MINER_LEARNED_BLOCK = re.compile(
    r"<!-- process-miner:learned:start -->.*?<!-- process-miner:learned:end -->",
    re.DOTALL,
)


def _strip_frontmatter(text: str) -> str:
    """Drop leading YAML-ish frontmatter (line-delimited close ``---``, same as repo ingest)."""
    _, body = parse_simple_frontmatter(text)
    return body


def _section_after_heading(md: str, heading_line: str) -> str:
    """Return body after ``heading_line`` (including ``##``) until the next H2 or EOF."""
    idx = md.find(heading_line)
    if idx < 0:
        return ""
    start = idx + len(heading_line)
    if not heading_line.endswith("\n"):
        start = md.find("\n", idx)
        if start < 0:
            return ""
        start += 1
    rest = md[start:]
    m = re.search(r"^## [^\n]+\s*$", rest, re.MULTILINE)
    if m:
        return rest[: m.start()]
    return rest


def _bullets_from_chunk(chunk: str) -> list[str]:
    out: list[str] = []
    for line in chunk.splitlines():
        raw = line.strip()
        if not raw.startswith("- "):
            continue
        body = raw[2:].strip()
        if not body or body.startswith("<!--"):
            continue
        # Strip bold lead before dash/colon variants (Unicode dashes intentional).
        body = re.sub(r"^\*\*[^*]+\*\*\s*[—:–-]\s*", "", body)  # noqa: RUF001
        body = body.strip()
        if body:
            out.append(body)
    return out


def _agents_learned_patterns(agents_path: Path) -> list[str]:
    if not agents_path.is_file():
        return []
    text = agents_path.read_text(encoding="utf-8")
    prefs = _section_after_heading(text, "## Learned User Preferences")
    facts = _section_after_heading(text, "## Learned Workspace Facts")
    facts = _PROCESS_MINER_LEARNED_BLOCK.sub("", facts)
    return _bullets_from_chunk(prefs) + _bullets_from_chunk(facts)


def _core_principles_patterns(core_path: Path) -> list[str]:
    if not core_path.is_file():
        return []
    text = core_path.read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\d+\.\s+(.+)$", line.strip())
        if m:
            out.append(m.group(1).strip())
    return out


def _subsection(body: str, title: str) -> str:
    m = re.search(
        rf"^## {re.escape(title)}\s*\n(.*?)(?=^## |\Z)",
        body,
        re.MULTILINE | re.DOTALL,
    )
    if not m:
        return ""
    return m.group(1).strip()


def _invariant_docs(root: Path) -> list[tuple[str, str, str]]:
    """List of (vault_path_posix, pattern_text, decision_text)."""
    inv_dir = root / "docs" / "01_Vault" / "AcCopilotTrainer" / "00_System" / "invariants"
    if not inv_dir.is_dir():
        return []
    rows: list[tuple[str, str, str]] = []
    for path in sorted(inv_dir.glob("*.md")):
        if path.name == "_index.md":
            continue
        raw = path.read_text(encoding="utf-8")
        body = _strip_frontmatter(raw)
        m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = m.group(1).strip() if m else path.stem
        # H1 is usually "Invariant: …" — avoid "Invariant: Invariant: …" in pattern_text.
        if title.lower().startswith("invariant:"):
            pattern_text = title
        else:
            pattern_text = f"Invariant: {title}"
        rel = path.relative_to(root).as_posix()
        rule = _subsection(body, "Rule")
        rationale = _subsection(body, "Rationale")
        if not rule:
            if not rationale:
                warnings.warn(
                    f"bootstrap_knowledge: {rel} has no Rule or Rationale; using title as decision",
                    stacklevel=1,
                )
            rule = rationale or title
        rows.append((rel, pattern_text, rule))
    return rows


def _ensure_pattern(conn: sqlite3.Connection, text: str, now: str) -> int:
    conn.execute(
        """
        INSERT INTO patterns (
            pattern_text, severity, preventability, frequency, first_seen, last_seen
        )
        VALUES (?, NULL, NULL, 1, ?, ?)
        ON CONFLICT(pattern_text) DO NOTHING
        """,
        (text, now, now),
    )
    row = conn.execute("SELECT id FROM patterns WHERE pattern_text = ?", (text,)).fetchone()
    assert row is not None
    return int(row[0])


def _reset_bootstrap_rows(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM pattern_evidence WHERE comment_author = ?", (_BOOTSTRAP_AUTHOR,))
    conn.execute("DELETE FROM decisions WHERE rationale = ?", (_BOOTSTRAP_RATIONALE,))


def bootstrap(*, root: Path | None = None) -> int:
    repo = root if root is not None else _REPO_ROOT
    db_path = repo / ".cache" / "repo_knowledge" / "knowledge.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from tools.repo_knowledge.schema import apply_schema

    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    conn = sqlite3.connect(db_path)
    try:
        apply_schema(conn)
        _reset_bootstrap_rows(conn)

        agents = repo / "AGENTS.md"
        core = repo / "AGENT_CORE_PRINCIPLES.md"

        for label, text in (("AGENTS.md", p) for p in _agents_learned_patterns(agents)):
            pid = _ensure_pattern(conn, text, now)
            conn.execute(
                """
                INSERT INTO pattern_evidence (
                    pattern_id, pr_number, comment_author, comment_body,
                    file_path, line_number, created_at
                )
                VALUES (?, NULL, ?, ?, ?, NULL, ?)
                """,
                (pid, _BOOTSTRAP_AUTHOR, f"[bootstrap] {label}: {text[:500]}", label, now),
            )

        for text in _core_principles_patterns(core):
            pid = _ensure_pattern(conn, text, now)
            conn.execute(
                """
                INSERT INTO pattern_evidence (
                    pattern_id, pr_number, comment_author, comment_body,
                    file_path, line_number, created_at
                )
                VALUES (?, NULL, ?, ?, ?, NULL, ?)
                """,
                (
                    pid,
                    _BOOTSTRAP_AUTHOR,
                    f"[bootstrap] AGENT_CORE_PRINCIPLES.md: {text[:500]}",
                    "AGENT_CORE_PRINCIPLES.md",
                    now,
                ),
            )

        for vault_path, pattern_text, decision_text in _invariant_docs(repo):
            pid = _ensure_pattern(conn, pattern_text, now)
            conn.execute(
                """
                INSERT INTO pattern_evidence (
                    pattern_id, pr_number, comment_author, comment_body,
                    file_path, line_number, created_at
                )
                VALUES (?, NULL, ?, ?, ?, NULL, ?)
                """,
                (
                    pid,
                    _BOOTSTRAP_AUTHOR,
                    f"[bootstrap] invariant {vault_path}",
                    vault_path,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO decisions (
                    vault_path, decision_text, rationale, affected_paths, created_at
                )
                VALUES (?, ?, ?, NULL, ?)
                """,
                (vault_path, decision_text, _BOOTSTRAP_RATIONALE, now),
            )

        conn.execute(
            """
            INSERT INTO ingest_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            ("bootstrap_knowledge_last_run", now),
        )
        conn.commit()
    finally:
        conn.close()
    return 0


def main() -> int:
    return bootstrap()


if __name__ == "__main__":
    raise SystemExit(main())
