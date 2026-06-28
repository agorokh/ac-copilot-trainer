"""Track Titan ingest — retain + parse the operator's own post-race analysis data.

Milestone M-TT0 (this package's first slice, issue #353): **vulcan** retention —
discover the operator's personal refresh token, mint short-lived Cognito tokens,
paginate the sessions list, and retain every session immutably to the lake keyed by
car + track + setup. The services per-corner traces (M-TT1) and the reference-lap →
``lap_archive`` bridge that feeds M0 voice coaching (M-TT2) build on this foundation.

SECURITY: tokens are personal secrets — never logged, never committed. Only public
Cognito identifiers are hardcoded (env-overridable). See :mod:`tools.tt_ingest.tt_auth`.
"""

from __future__ import annotations

from tools.tt_ingest.cli import ExportSummary, build_arg_parser, main, retain_sessions
from tools.tt_ingest.tt_auth import (
    MintedTokens,
    TTAuthError,
    TTConfig,
    build_initiate_auth_request,
    decode_jwt_payload,
    extract_refresh_token_from_text,
    extract_uid_from_text,
    is_token_expired,
    parse_initiate_auth_response,
    resolve_refresh_token,
    token_expiry,
    uid_from_token,
)
from tools.tt_ingest.tt_export import (
    RetainedFile,
    TTExportError,
    WriteResult,
    build_index,
    lake_root,
    sanitize_segment,
    session_lake_dir,
    write_immutable_json,
)
from tools.tt_ingest.tt_normalize import (
    build_sessions_index,
    normalize_session,
    normalize_sessions,
)
from tools.tt_ingest.tt_vulcan import (
    SessionsPage,
    TTVulcanError,
    parse_sessions_page,
    session_summary,
    sessions_url,
    split_session_id,
)

__all__ = [
    "ExportSummary",
    "MintedTokens",
    "RetainedFile",
    "SessionsPage",
    "TTAuthError",
    "TTConfig",
    "TTExportError",
    "TTVulcanError",
    "WriteResult",
    "build_arg_parser",
    "build_index",
    "build_initiate_auth_request",
    "build_sessions_index",
    "decode_jwt_payload",
    "extract_refresh_token_from_text",
    "extract_uid_from_text",
    "is_token_expired",
    "lake_root",
    "main",
    "normalize_session",
    "normalize_sessions",
    "parse_initiate_auth_response",
    "parse_sessions_page",
    "resolve_refresh_token",
    "retain_sessions",
    "sanitize_segment",
    "session_lake_dir",
    "session_summary",
    "sessions_url",
    "split_session_id",
    "token_expiry",
    "uid_from_token",
    "write_immutable_json",
]
