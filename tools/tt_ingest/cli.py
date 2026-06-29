"""CLI + orchestration for ``python -m tools.tt_ingest`` (issue #353, M-TT0).

The local retention pipeline (:func:`retain_sessions`) is pure-of-network and fully
unit-tested against ``tmp_path``: given already-fetched raw sessions it normalizes,
immutably retains, and indexes them. The network entrypoints (token mint + page
fetch) are thin and ``# pragma: no cover`` — they are proven live, not in CI.
"""

from __future__ import annotations

import argparse
import json
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
    TTExportError,
    build_index,
    endpoint_file,
    lake_root,
    relative_to_lake,
    session_lake_dir,
    sha256_hex,
    stable_fingerprint,
    write_immutable_json,
)
from tools.tt_ingest.tt_normalize import (
    build_sessions_index,
    normalize_session,
    split_session_id,
)
from tools.tt_ingest.tt_services import (
    TTServicesError,
    fetch_last_session_raw,
    fetch_session_coaching,
    parse_last_session,
)
from tools.tt_ingest.tt_vulcan import iter_all_sessions, session_summary

SESSIONS_INDEX_FILENAME = "sessions_index.json"
RAW_SESSION_ENDPOINT = "session"
# Both the raw /last-session payload AND the coaching bundle are retained one file PER LAP
# (``last_session_lap{N}.json`` / ``coaching_lap{N}.json``). The /last-session telemetry is
# lap-specific, so lap-keying it keeps each lap's raw evidence COHERENT with its coaching even
# when the same session later gains another lap (a single write-once ``last_session.json``
# would otherwise go stale against a newer lap's bundle).
LAST_SESSION_ENDPOINT_PREFIX = "last_session_lap"
LAST_SESSION_ENDPOINT_GLOB = f"{LAST_SESSION_ENDPOINT_PREFIX}*.json"
COACHING_ENDPOINT_PREFIX = "coaching_lap"
COACHING_ENDPOINT_GLOB = f"{COACHING_ENDPOINT_PREFIX}*.json"


def last_session_endpoint(lap: Any) -> str:
    """Endpoint (file stem) for a lap's raw /last-session payload: ``last_session_lap{lap}``."""
    return f"{LAST_SESSION_ENDPOINT_PREFIX}{lap}"


def coaching_endpoint(lap: Any) -> str:
    """Endpoint (file stem) for a lap's coaching bundle: ``coaching_lap{lap}``."""
    return f"{COACHING_ENDPOINT_PREFIX}{lap}"


@dataclass(frozen=True)
class ExportSummary:
    """Outcome of a retention run."""

    total: int
    retained_new: int
    skipped_existing: int
    lake_root: Path
    failed: int = 0
    indexed: int = 0

    def render(self) -> str:
        base = (
            f"retained {self.total} session(s) to {self.lake_root} "
            f"({self.retained_new} new, {self.skipped_existing} already present; "
            f"{self.indexed} total in lake)"
        )
        if self.failed:
            base += f"; {self.failed} session(s) skipped due to errors"
        return base


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# File-index globs (sessions_index is built from RAW_SESSION_ENDPOINT only — it normalizes
# vulcan sessions; the M-TT1 services endpoints are indexed for discovery/integrity but not
# normalized). Coaching is per-lap, so it is matched by glob, not a fixed name.
INDEXED_ENDPOINT_GLOBS = (
    f"{RAW_SESSION_ENDPOINT}.json",
    LAST_SESSION_ENDPOINT_GLOB,
    COACHING_ENDPOINT_GLOB,
)


def reindex_lake(root: Path, *, generated_at: str) -> int:
    """Rebuild both derived indexes from EVERY retained endpoint file in the lake.

    The indexes are a *derived view* of the immutable raw files — so they are rebuilt by
    scanning the whole lake on disk, never from one batch's records. A partial export can
    therefore never shrink the discovery index, and ``sessions_index.json`` always agrees
    with the raw files actually present (no batch-vs-disk divergence). The content-addressed
    file index covers vulcan ``session.json`` **and** the M-TT1 services endpoints
    (``last_session.json`` / ``coaching_lap{N}.json``); ``sessions_index.json`` is built from
    ``session.json`` only (it normalizes vulcan sessions). Returns the count of indexed files.
    """
    records: list[RetainedFile] = []
    normalized: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for pattern in INDEXED_ENDPOINT_GLOBS:
        for path in sorted(root.rglob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            try:
                data = path.read_bytes()
                raw = json.loads(data)
            except (OSError, ValueError):  # pragma: no cover - corrupt file skipped defensively
                continue
            endpoint = path.stem  # e.g. "session", "last_session", "coaching_lap5"
            records.append(
                RetainedFile(
                    session_key=path.parent.name,
                    endpoint=endpoint,
                    relative_path=relative_to_lake(path, root),
                    sha256=sha256_hex(data),
                    bytes=len(data),
                    written=False,
                )
            )
            if endpoint == RAW_SESSION_ENDPOINT and isinstance(raw, Mapping):
                normalized.append(normalize_session(raw))
    root.mkdir(parents=True, exist_ok=True)
    # sessions_index carries normalized telemetry conditions → allow_nan for lossless
    # round-trip; the file index (hashes/sizes/paths only) stays strict, portable JSON.
    write_immutable_json(
        root / SESSIONS_INDEX_FILENAME,
        build_sessions_index(normalized, generated_at=generated_at),
        overwrite=True,
        allow_nan=True,
    )
    write_immutable_json(
        root / INDEX_FILENAME, build_index(records, generated_at=generated_at), overwrite=True
    )
    return len(records)


def retain_sessions(
    sessions: Sequence[Mapping[str, Any]],
    *,
    lake_base: Path | None = None,
    generated_at: str | None = None,
) -> ExportSummary:
    """Normalize, immutably retain, and (re)index a batch of raw vulcan sessions.

    Each raw session is written **write-once** under
    ``journal/tt/{game}/{car}/{track}/{sessionKey}/session.json`` — raw evidence is never
    clobbered (data-immutability invariant). After the batch, both derived indexes are
    rebuilt from the *entire* lake on disk (see :func:`reindex_lake`), so a partial export
    never shrinks the index and the index always matches the immutable raw files.
    """
    root = lake_root(lake_base)
    stamp = generated_at or _iso_now()
    retained_new = 0
    processed = 0
    failed = 0

    for raw in sessions:
        try:
            row = normalize_session(raw)
            # Distinct sessions must never collapse onto one lake path. A real vulcan id
            # is unique per session; for a degraded session lacking one, key on a content
            # fingerprint so two different id-less payloads stay distinct (a true duplicate
            # still de-dupes) — never the single literal bucket that silently drops data.
            session_key = (
                row.get("session_key")
                or row.get("session_id")
                or f"nokey-{stable_fingerprint(raw)}"
            )
            target_dir = session_lake_dir(
                root,
                game=row.get("game_id"),
                car=row.get("car_id"),
                track=row.get("track_id"),
                session_key=session_key,
            )
            path = endpoint_file(target_dir, RAW_SESSION_ENDPOINT)
            # Raw retention is write-once (never overwrite) + lossless (allow_nan keeps
            # non-finite telemetry floats).
            result = write_immutable_json(path, dict(raw), allow_nan=True)
        except (OSError, ValueError, TypeError, TTExportError):
            # One malformed session must never abort the whole batch or the indexes.
            failed += 1
            continue
        processed += 1
        if result.written:
            retained_new += 1

    indexed = reindex_lake(root, generated_at=stamp)
    return ExportSummary(
        total=processed,
        retained_new=retained_new,
        skipped_existing=processed - retained_new,
        failed=failed,
        lake_root=root,
        indexed=indexed,
    )


@dataclass(frozen=True)
class CoachingSummary:
    """Outcome of retaining one session's coaching bundle (M-TT1)."""

    session_key: str
    segments: int
    actionable: int
    written: list[str]
    lake_root: Path
    indexed: int = 0

    def render(self) -> str:
        return (
            f"retained coaching for session {self.session_key} "
            f"({self.segments} segment(s), {self.actionable} actionable) to {self.lake_root} "
            f"[{', '.join(self.written) or 'nothing new'}; {self.indexed} file(s) indexed]"
        )


def _car_segment(session: Mapping[str, Any]) -> Any:
    """Resolve a STRING car id for the lake path.

    The last-session ``session`` stores ``car`` as a string id; other surfaces may carry a
    string ``car_id`` or a ``car`` object. Prefer a string id and unwrap an object so the
    lake path is ``…/{car_id}/…``, never a dict-repr (#353 review).
    """
    for value in (session.get("car_id"), session.get("car")):
        if isinstance(value, str) and value:
            return value
        if isinstance(value, Mapping):
            inner = value.get("car_id") or value.get("id")
            if isinstance(inner, str) and inner:
                return inner
    return None


def _session_lake_key(session: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the (game, car, track, session_key) lake key for a services session.

    The session key is the second half of the ``{uid}#{sessionKey}`` id (services has no
    standalone field). The car id is resolved to a string via :func:`_car_segment`.
    """
    raw_id = session.get("session_id") or session.get("id") or ""
    _, session_key = split_session_id(raw_id)
    return {
        "game": session.get("game_id"),
        "car": _car_segment(session),
        "track": session.get("track_id"),
        "session_key": session_key or f"nokey-{stable_fingerprint(dict(session))}",
    }


def _count_actionable(bundle: Mapping[str, Any]) -> int:
    """Count corner stories carrying a real (>0) time loss across the bundle."""
    total = 0
    for seg in bundle.get("segments", []) or []:
        for story in seg.get("stories", []) or []:
            loss = story.get("time_loss")
            if isinstance(loss, (int, float)) and loss > 0:
                total += 1
    return total


def retain_coaching(
    session: Mapping[str, Any],
    bundle: Mapping[str, Any],
    *,
    lap: Any,
    last_session_payload: Mapping[str, Any] | None = None,
    lake_base: Path | None = None,
    generated_at: str | None = None,
) -> CoachingSummary:
    """Immutably retain a session's last-session payload + per-lap coaching bundle, then reindex.

    Pure of network: given already-fetched payloads, writes ``last_session_lap{lap}.json`` and
    ``coaching_lap{lap}.json`` **write-once** under ``journal/tt/{game}/{car}/{track}/{sk}/``
    keyed by the given ``session``. BOTH files are **per-lap**: the /last-session telemetry is
    lap-specific, so lap-keying it keeps each lap's raw evidence coherent with its coaching even
    when the same session later gains another lap (#353 review). ``last_session_payload`` is the
    FULL raw services response (session + referenceLap + telemetry) — preserved so the lake
    reconstructs exactly what the endpoint returned (the M-TT2 reference-lap input); it defaults
    to ``session`` when not supplied.
    After writing, the lake indexes are rebuilt from disk (:func:`reindex_lake`) so the new
    services endpoints are discoverable and integrity-checkable. ``allow_nan`` keeps
    non-finite telemetry floats lossless, matching raw session retention.
    """
    root = lake_root(lake_base)
    stamp = generated_at or _iso_now()
    key = _session_lake_key(session)
    target_dir = session_lake_dir(
        root, game=key["game"], car=key["car"], track=key["track"], session_key=key["session_key"]
    )
    last_payload = dict(last_session_payload) if last_session_payload is not None else dict(session)
    written: list[str] = []
    for endpoint, payload in (
        (last_session_endpoint(lap), last_payload),
        (coaching_endpoint(lap), dict(bundle)),
    ):
        result = write_immutable_json(endpoint_file(target_dir, endpoint), payload, allow_nan=True)
        if result.written:
            written.append(endpoint)
    indexed = reindex_lake(root, generated_at=stamp)
    return CoachingSummary(
        session_key=key["session_key"],
        segments=len(bundle.get("segments", []) or []),
        actionable=_count_actionable(bundle),
        written=written,
        lake_root=root,
        indexed=indexed,
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
    export.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch page 1 and print a sanitized summary; write nothing.",
    )

    coaching = sub.add_parser(
        "coaching",
        help="Fetch + retain per-corner reference & advice for the last session (services, M-TT1).",
    )
    coaching.add_argument("--uid", default=None, help="User id; defaults to the token 'sub'.")
    coaching.add_argument(
        "--segment-count", type=int, default=7, help="Corners (segments) to pull (default 7)."
    )
    coaching.add_argument("--lake-base", type=Path, default=None)
    coaching.add_argument("--leveldb-dir", type=Path, default=None)
    coaching.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved session + a sanitized advice summary; write nothing.",
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
    summary = retain_sessions(sessions, lake_base=args.lake_base)
    _print(summary.render())
    return 0


def cmd_coaching(args: argparse.Namespace) -> int:  # pragma: no cover - network
    config = TTConfig.from_env()
    refresh = resolve_refresh_token(config, leveldb_dir=args.leveldb_dir)
    minted = mint_tokens(refresh, config)
    uid = args.uid or uid_from_token(minted.access_token)

    # M-TT1 scope: coach the LAST session's own lap. The /last-session endpoint returns the
    # full raw payload (session + referenceLap + telemetry) for exactly that lap, so the
    # retained last_session.json is COHERENT lap-specific evidence next to coaching_lap{N}.json.
    # Coaching an arbitrary lap (or older session) needs per-lap telemetry endpoints not in
    # M-TT1 scope — see the M-TT2+ follow-up — so it is intentionally not offered here (a
    # mismatched lap would pair lap-N coaching with the wrong lap's raw evidence).
    raw_last = fetch_last_session_raw(minted.access_token, uid)
    session = parse_last_session(raw_last)["session"]
    key = _session_lake_key(session)
    session_key = key["session_key"]
    lap = session.get("lap_number")
    if not session_key or lap is None:
        _print("coaching: could not resolve the last session's key/lap (no recent session?)")
        return 1

    bundle = fetch_session_coaching(
        minted.access_token, uid, session_key, lap, segment_count=args.segment_count
    )

    if args.dry_run:
        _print(f"dry-run — uid={uid}, session={session_key}, lap={lap}")
        _print(f"  dynamic reference: {bundle['reference_lap'].get('username', '?')}")
        for seg in bundle["segments"]:
            stories = seg.get("stories", [])
            head = stories[0]["diagnosis"] if stories else "(no advice)"
            _print(f"  corner {seg['segment']}: {head}")
        return 0

    summary = retain_coaching(
        session, bundle, lap=lap, last_session_payload=raw_last, lake_base=args.lake_base
    )
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
        if args.command == "coaching":
            return cmd_coaching(args)
    except (TTAuthError, TTServicesError) as exc:  # pragma: no cover - surfaced live
        parser.exit(2, f"tt_ingest: {exc}\n")
    parser.error(f"unknown command: {args.command}")  # pragma: no cover - argparse guards
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
