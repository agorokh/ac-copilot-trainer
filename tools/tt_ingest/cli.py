"""CLI + orchestration for ``python -m tools.tt_ingest`` (issue #353, M-TT0).

The local retention pipeline (:func:`retain_sessions`) is pure-of-network and fully
unit-tested against ``tmp_path``: given already-fetched raw sessions it normalizes,
immutably retains, and indexes them. The network entrypoints (token mint + page
fetch) are thin and ``# pragma: no cover`` — they are proven live, not in CI.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.tt_ingest.tt_auth import (
    TTAuthError,
    TTConfig,
    is_token_expired,
    mint_tokens,
    resolve_refresh_token,
    token_expiry,
    uid_from_token,
)
from tools.tt_ingest.tt_export import (
    INDEX_FILENAME,
    RetainedFile,
    build_index,
    endpoint_file,
    lake_root,
    relative_to_lake,
    session_lake_dir,
    write_immutable_json,
)
from tools.tt_ingest.tt_normalize import build_sessions_index, normalize_session
from tools.tt_ingest.tt_vulcan import iter_all_sessions, session_summary

SESSIONS_INDEX_FILENAME = "sessions_index.json"
RAW_SESSION_ENDPOINT = "session"


@dataclass(frozen=True)
class ExportSummary:
    """Outcome of a retention run."""

    total: int
    retained_new: int
    skipped_existing: int
    lake_root: Path

    def render(self) -> str:
        return (
            f"retained {self.total} session(s) to {self.lake_root} "
            f"({self.retained_new} new, {self.skipped_existing} already present)"
        )


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def retain_sessions(
    sessions: Sequence[Mapping[str, Any]],
    *,
    lake_base: Path | None = None,
    generated_at: str | None = None,
    overwrite: bool = False,
) -> ExportSummary:
    """Normalize, immutably retain, and index a batch of raw vulcan sessions.

    Each raw session is written write-once under
    ``journal/tt/{game}/{car}/{track}/{sessionKey}/session.json``; derived
    ``sessions_index.json`` + content-addressed ``index.json`` are (re)written at the
    lake root. Returns counts of new vs. already-present files.
    """
    root = lake_root(lake_base)
    stamp = generated_at or _iso_now()
    records: list[RetainedFile] = []
    normalized: list[dict[str, Any]] = []
    retained_new = 0

    for raw in sessions:
        row = normalize_session(raw)
        normalized.append(row)
        session_key = row.get("session_key") or row.get("session_id") or "unknown_session"
        target_dir = session_lake_dir(
            root,
            game=row.get("game_id"),
            car=row.get("car_id"),
            track=row.get("track_id"),
            session_key=session_key,
        )
        path = endpoint_file(target_dir, RAW_SESSION_ENDPOINT)
        result = write_immutable_json(path, dict(raw), overwrite=overwrite)
        if result.written:
            retained_new += 1
        records.append(
            RetainedFile(
                session_key=str(session_key),
                endpoint=RAW_SESSION_ENDPOINT,
                relative_path=relative_to_lake(result.path, root),
                sha256=result.sha256,
                bytes=result.bytes,
                written=result.written,
            )
        )

    root.mkdir(parents=True, exist_ok=True)
    write_immutable_json(
        root / SESSIONS_INDEX_FILENAME,
        build_sessions_index(normalized, generated_at=stamp),
        overwrite=True,
    )
    write_immutable_json(
        root / INDEX_FILENAME, build_index(records, generated_at=stamp), overwrite=True
    )
    return ExportSummary(
        total=len(records),
        retained_new=retained_new,
        skipped_existing=len(records) - retained_new,
        lake_root=root,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the ``tools.tt_ingest`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m tools.tt_ingest",
        description="Retain + index Track Titan post-race session data (issue #353).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser(
        "auth-check",
        help="Resolve the refresh token and mint access/id tokens (prints no secrets).",
    )
    auth.add_argument("--leveldb-dir", type=Path, default=None)

    export = sub.add_parser(
        "export", help="Paginate the sessions list and retain it immutably to the lake."
    )
    export.add_argument("--uid", default=None, help="User id; defaults to the token 'sub'.")
    export.add_argument("--limit", type=int, default=50, help="Page size (default 50).")
    export.add_argument(
        "--max-pages", type=int, default=None, help="Cap pages fetched (default: all)."
    )
    export.add_argument(
        "--lake-base",
        type=Path,
        default=None,
        help="Base dir for the journal/tt lake (default: cwd).",
    )
    export.add_argument("--leveldb-dir", type=Path, default=None)
    export.add_argument("--overwrite", action="store_true", help="Re-retain existing files.")
    export.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch page 1 and print a sanitized summary; write nothing.",
    )
    return parser


def _print(message: str) -> None:  # pragma: no cover - thin stdout shim
    print(message)


def cmd_auth_check(args: argparse.Namespace) -> int:  # pragma: no cover - network
    config = TTConfig.from_env()
    refresh = resolve_refresh_token(config, leveldb_dir=args.leveldb_dir)
    minted = mint_tokens(refresh, config)
    uid = uid_from_token(minted.access_token)
    expiry = token_expiry(minted.access_token)
    expired = is_token_expired(minted.access_token)
    _print(f"auth-check OK — uid={uid}")
    _print(f"  access token expires: {expiry.isoformat() if expiry else '?'} (expired={expired})")
    return 0


def cmd_export(args: argparse.Namespace) -> int:  # pragma: no cover - network
    config = TTConfig.from_env()
    refresh = resolve_refresh_token(config, leveldb_dir=args.leveldb_dir)
    minted = mint_tokens(refresh, config)
    uid = args.uid or uid_from_token(minted.access_token)

    if args.dry_run:
        from tools.tt_ingest.tt_vulcan import fetch_sessions_page

        page = fetch_sessions_page(minted.access_token, uid, limit=args.limit, page=1)
        _print(f"dry-run — uid={uid}, count={page.count}, page size={page.limit}")
        for session in page.sessions[:10]:
            _print(f"  {session_summary(session)}")
        return 0

    sessions = list(
        iter_all_sessions(minted.access_token, uid, limit=args.limit, max_pages=args.max_pages)
    )
    summary = retain_sessions(sessions, lake_base=args.lake_base, overwrite=args.overwrite)
    _print(summary.render())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "auth-check":
            return cmd_auth_check(args)
        if args.command == "export":
            return cmd_export(args)
    except TTAuthError as exc:  # pragma: no cover - surfaced live
        parser.exit(2, f"tt_ingest: {exc}\n")
    parser.error(f"unknown command: {args.command}")  # pragma: no cover - argparse guards
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
