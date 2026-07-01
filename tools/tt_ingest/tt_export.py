"""Immutable retention of raw Track Titan responses to the lake (issue #353, M-TT0).

Raw vulcan/services JSON is **write-once**: keyed by car + track + setup under
``journal/tt/{game}/{car}/{track}/{sessionKey}/{endpoint}.json`` and never edited in
place (data-immutability invariant). A content-addressed index (``index.json`` at the
lake root) records each retained file with its sha256 + byte size so silent
corruption is *detected*, never assumed away.

Path building, sanitization, hashing, and index assembly are pure and unit-tested.
The only side effect is the atomic write in :func:`write_immutable_json`, which is
exercised against ``tmp_path`` in tests (no network, no real lake).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LAKE_SUBDIR = "tt"
INDEX_FILENAME = "index.json"
INDEX_SCHEMA_VERSION = 1
LAST_SESSION_ENDPOINT_PREFIX = "last_session_lap"
LAST_SESSION_WINDOW_MARKER = "_window_"
COACHING_ENDPOINT_PREFIX = "coaching_lap"
CURRICULUM_ENDPOINT_PREFIX = "curriculum_lap"

#: Characters allowed in a single lake path segment; everything else collapses to ``_``.
_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


class TTExportError(RuntimeError):
    """A retention write would violate immutability or escape the lake root."""


def sanitize_segment(value: Any, *, fallback: str = "unknown") -> str:
    """Make ``value`` a safe single path segment (no separators, no traversal)."""
    text = str(value).strip() if value not in (None, "") else ""
    text = _SAFE_SEGMENT_RE.sub("_", text).strip("._")
    if not text or text in {".", ".."}:
        return fallback
    return text[:128]


def lake_root(base: Path | str | None = None) -> Path:
    """Resolve the Track Titan lake root (``<base>/journal/tt``; default ``base``: cwd).

    Retention ALWAYS nests under ``journal/tt`` of the given base, matching the
    coaching-lake convention that application writes stay inside ``journal/``. There is
    deliberately no env override that could redirect the write root to an arbitrary
    filesystem location — the operator chooses the base explicitly via ``--lake-base``.
    """
    root = Path(base) if base is not None else Path.cwd()
    return root / "journal" / LAKE_SUBDIR


def session_lake_dir(root: Path, *, game: Any, car: Any, track: Any, session_key: Any) -> Path:
    """Directory for one session's retained endpoints, with sanitized segments."""
    return (
        root
        / sanitize_segment(game, fallback="unknown_game")
        / sanitize_segment(car, fallback="unknown_car")
        / sanitize_segment(track, fallback="unknown_track")
        / sanitize_segment(session_key, fallback="unknown_session")
    )


def endpoint_file(session_dir: Path, endpoint: str) -> Path:
    """Path to one endpoint's retained JSON within a session dir."""
    return session_dir / f"{sanitize_segment(endpoint, fallback='endpoint')}.json"


def _serialize(payload: Any, *, allow_nan: bool = False) -> bytes:
    return (
        json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=allow_nan) + "\n"
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Hex sha256 of bytes."""
    return hashlib.sha256(data).hexdigest()


def stable_fingerprint(payload: Any, *, length: int = 12) -> str:
    """A short, deterministic content fingerprint of ``payload`` (sha256 of canonical JSON).

    Used to key retention for sessions that lack a usable id, so two *distinct* id-less
    payloads never collapse onto one lake path (which would silently drop the second).
    """
    return sha256_hex(_serialize(payload, allow_nan=True))[:length]


@dataclass(frozen=True)
class WriteResult:
    """Outcome of an immutable write."""

    path: Path
    written: bool
    sha256: str
    bytes: int


def write_immutable_json(
    path: Path, payload: Any, *, overwrite: bool = False, allow_nan: bool = False
) -> WriteResult:
    """Atomically write ``payload`` as JSON, refusing to clobber an existing file.

    Write-once is the default: if ``path`` already exists and ``overwrite`` is False,
    nothing is written and ``WriteResult.written`` is False (with the *existing* file's
    hash, so the caller can still index it). Uses a temp file + ``os.replace`` so a
    crash never leaves a half-written record on disk.

    ``allow_nan`` controls non-finite float handling: ``False`` (default) keeps derived
    indexes as strict, portable JSON; raw retention passes ``True`` so a session carrying
    a ``NaN``/``Infinity`` telemetry float is retained *losslessly* (it round-trips through
    our own ``json.loads``) instead of raising and aborting the batch.
    """
    data = _serialize(payload, allow_nan=allow_nan)
    digest = sha256_hex(data)
    if path.exists():
        if not overwrite:
            existing = path.read_bytes()
            return WriteResult(
                path=path, written=False, sha256=sha256_hex(existing), bytes=len(existing)
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        # Clean up the temp file on any failure so the lake never accrues litter.
        try:
            os.unlink(tmp_name)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
        raise
    return WriteResult(path=path, written=True, sha256=digest, bytes=len(data))


@dataclass(frozen=True)
class RetainedFile:
    """One retained endpoint file, as recorded in the lake index."""

    session_key: str
    endpoint: str
    relative_path: str
    sha256: str
    bytes: int
    written: bool


def relative_to_lake(path: Path, root: Path) -> str:
    """POSIX-style path of ``path`` relative to the lake ``root`` (index portability)."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise TTExportError(f"retained file {path} is outside lake root {root}") from exc
    return rel.as_posix()


def build_index(records: list[RetainedFile], *, generated_at: str) -> dict[str, Any]:
    """Assemble the content-addressed lake index document from retained-file records."""
    return {
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": generated_at,
        "file_count": len(records),
        "files": [
            {
                "session_key": r.session_key,
                "endpoint": r.endpoint,
                "path": r.relative_path,
                "sha256": r.sha256,
                "bytes": r.bytes,
            }
            for r in records
        ],
    }
