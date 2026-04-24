"""Merge session debrief JSONL into the repo knowledge SQLite DB (best-effort)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tools.process_miner.session_debrief_schema import (
    normalize_path_list,
    normalize_pattern_list,
)
from tools.repo_knowledge.schema import apply_schema

_PATTERN_CI = "Session debrief: self-reported CI note"
_PATTERN_MISTAKES = "Session debrief: self-reported mistakes"
_PATTERN_PREFIX = "session_debrief:pattern:"
_PATTERN_BODY_MAX = 2000 - len(_PATTERN_PREFIX)


def utc_now_iso_z() -> str:
    """UTC instant as second-precision ISO-8601 with ``Z`` (matches debrief JSONL ``ts``)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fingerprint_for_line(line: str) -> str:
    return hashlib.sha256(line.strip().encode("utf-8", errors="replace")).hexdigest()


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _canonical_ts_iso(raw: object, fallback: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return fallback
    dt = _parse_ts(raw)
    if dt is None:
        return fallback
    au = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return au.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def list_debrief_jsonl_paths(debrief_dir: Path) -> list[Path]:
    if not debrief_dir.is_dir():
        return []
    return sorted(debrief_dir.glob("debrief-*.jsonl"))


def load_debrief_records(
    debrief_dir: Path,
    *,
    max_age_days: int,
    now: datetime | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Return ``(source_path_str, record)`` for JSON objects with a parseable ``ts`` in range."""
    base = now if now is not None else datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    now_utc = base.astimezone(UTC)
    if max_age_days < 1:
        raise ValueError("max_age_days must be >= 1")
    cutoff = now_utc - timedelta(days=max_age_days)
    out: list[tuple[str, dict[str, Any]]] = []
    for path in list_debrief_jsonl_paths(debrief_dir):
        try:
            with path.open(encoding="utf-8", errors="replace") as debrief_f:
                for raw_line in debrief_f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    ts = _parse_ts(obj.get("ts"))
                    if ts is None:
                        continue
                    au = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
                    au = au.astimezone(UTC)
                    if au < cutoff:
                        continue
                    out.append((path.as_posix(), obj))
        except OSError:
            continue
    return out


def _ensure_pattern(
    conn: sqlite3.Connection,
    pattern_text: str,
    *,
    now: str,
) -> int:
    pkey = pattern_text[:2000]
    conn.execute(
        """
        INSERT INTO patterns (
            pattern_text, severity, preventability, frequency, first_seen, last_seen
        )
        VALUES (?, 'maintainability', 'session_debrief', 1, ?, ?)
        ON CONFLICT(pattern_text) DO UPDATE SET
            frequency = patterns.frequency + 1,
            last_seen = excluded.last_seen
        """,
        (pkey, now, now),
    )
    row = conn.execute("SELECT id FROM patterns WHERE pattern_text = ?", (pkey,)).fetchone()
    if row is None or row[0] is None:
        err = "pattern upsert did not yield a row id"
        raise RuntimeError(err)
    return int(row[0])


def _insert_evidence(
    conn: sqlite3.Connection,
    pattern_id: int,
    *,
    body: str,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO pattern_evidence (
            pattern_id, pr_number, comment_author, comment_body, file_path, line_number, created_at
        )
        VALUES (?, NULL, 'session_debrief', ?, NULL, NULL, ?)
        """,
        (pattern_id, body[:8000], created_at),
    )


def ingest_session_debrief_records(
    conn: sqlite3.Connection,
    repo_root: Path,
    records: list[tuple[str, dict[str, Any]]],
    *,
    now_iso: str,
) -> tuple[int, int]:
    """Apply debrief rows to ``conn``. Returns ``(records_applied, records_skipped_duplicate)``.

    Each row reserves its fingerprint with ``INSERT`` under a ``SAVEPOINT`` first so concurrent
    writers see ``IntegrityError`` / skip instead of partial apply then duplicate PK failure.
    """
    applied = 0
    skipped = 0
    for _src, rec in records:
        line_fp = _fingerprint_for_line(
            json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        )
        conn.execute("SAVEPOINT session_debrief_row")
        try:
            try:
                conn.execute(
                    "INSERT INTO session_debrief_ingest (fingerprint, ingested_at) VALUES (?, ?)",
                    (line_fp, now_iso),
                )
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK TO SAVEPOINT session_debrief_row")
                conn.execute("RELEASE SAVEPOINT session_debrief_row")
                skipped += 1
                continue

            ts_fallback = now_iso
            created_at = _canonical_ts_iso(rec.get("ts"), ts_fallback)

            paths = normalize_path_list(rec.get("session_debrief_files"), repo_root=repo_root)
            for fp in paths:
                conn.execute(
                    """
                    INSERT INTO files (
                        path, review_comment_count, ci_failure_count, session_touch_count
                    )
                    VALUES (?, 0, 0, 1)
                    ON CONFLICT(path) DO UPDATE SET
                        session_touch_count = files.session_touch_count + 1
                    """,
                    (fp,),
                )

            for pat in normalize_pattern_list(rec.get("session_debrief_patterns")):
                tail = pat if len(pat) <= _PATTERN_BODY_MAX else pat[:_PATTERN_BODY_MAX]
                ptext = f"{_PATTERN_PREFIX}{tail}"
                pid = _ensure_pattern(conn, ptext, now=now_iso)
                _insert_evidence(conn, pid, body=pat, created_at=created_at)

            ci_note = rec.get("session_debrief_ci")
            if isinstance(ci_note, str) and ci_note.strip():
                pid = _ensure_pattern(conn, _PATTERN_CI, now=now_iso)
                _insert_evidence(conn, pid, body=ci_note.strip(), created_at=created_at)

            ms = rec.get("session_debrief_mistakes")
            if isinstance(ms, str) and ms.strip():
                pid = _ensure_pattern(conn, _PATTERN_MISTAKES, now=now_iso)
                _insert_evidence(conn, pid, body=ms.strip(), created_at=created_at)

            conn.execute("RELEASE SAVEPOINT session_debrief_row")
            applied += 1
        except Exception:
            conn.execute("ROLLBACK TO SAVEPOINT session_debrief_row")
            conn.execute("RELEASE SAVEPOINT session_debrief_row")
            raise

    return applied, skipped


def ingest_session_debriefs_from_disk(
    db_path: Path,
    repo_root: Path,
    *,
    max_age_days: int = 14,
) -> tuple[int, int]:
    """Open DB, load recent JSONL under ``repo_root/.cache/session_debriefs``, merge, commit."""
    if max_age_days < 1:
        raise ValueError("max_age_days must be >= 1")
    debrief_dir = repo_root / ".cache" / "session_debriefs"
    records = load_debrief_records(debrief_dir, max_age_days=max_age_days)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        apply_schema(conn)
        now = utc_now_iso_z()
        applied, skipped = ingest_session_debrief_records(conn, repo_root, records, now_iso=now)
        conn.commit()
        return applied, skipped
    finally:
        conn.close()
