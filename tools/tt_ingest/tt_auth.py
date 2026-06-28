"""Track Titan auth — discover the operator's personal refresh token and mint
short-lived Cognito tokens for the vulcan (and, later, services) APIs (issue #353).

SECURITY (issue #353 scope/ethics): this reads the **operator's own** Track Titan
refresh token from their **own** machine for **personal** coaching use. The refresh
token and any minted access/id tokens are **personal secrets** — this module never
logs them, never embeds them in raised error messages, and callers must never
persist them to tracked files (keep them in env / the gitignored lake only).

Only public Cognito *identifiers* (region, user-pool / app-client / identity-pool
ids) are hardcoded as defaults. Those are **not** credentials: the Electron app
sends them in every *unauthenticated* request and they identify the app + pools,
not the user. They are also env-overridable via ``TT_COGNITO_*`` so nothing is
pinned in source. The user's ``refreshToken`` is the only secret, and it is never
hardcoded.

Module shape mirrors the repo convention (e.g. ``tools/process_miner``): the
network round-trips are isolated and ``# pragma: no cover``; the request builders
and response parsers are pure and unit-tested.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Public Cognito identifiers reverse-engineered from the Track Titan Electron app
# config (``app.asar``) and verified live (issue #353). NOT secrets — see module
# docstring. ``# pragma: allowlist secret`` tells detect-secrets these high-entropy
# strings are public app identifiers, not credentials.
_DEFAULT_REGION = "us-east-1"
_DEFAULT_USER_POOL_ID = "us-east-1_fdm9kB5Wr"  # pragma: allowlist secret
_DEFAULT_APP_CLIENT_ID = "6qp755fd6379572i96kt1hvu55"  # pragma: allowlist secret
_DEFAULT_IDENTITY_POOL_ID = (
    "us-east-1:03459aca-683c-4cc1-b2af-86b86705dd67"  # pragma: allowlist secret
)

DEFAULT_REQUEST_TIMEOUT_S = 30.0

#: Local Storage LevelDB key the Electron app writes the refresh token under, e.g.
#: ``CognitoIdentityServiceProvider.<clientId>.<uid>.refreshToken``.
_REFRESH_TOKEN_KEY_RE_TEMPLATE = (
    r"CognitoIdentityServiceProvider\.{client}\.(?P<uid>[^.\x00-\x1f]+)\.refreshToken"
)
_LAST_AUTH_USER_KEY_RE_TEMPLATE = r"CognitoIdentityServiceProvider\.{client}\.LastAuthUser"

#: A Cognito refresh token is a 5-segment JWE (header.key.iv.ciphertext.tag), each
#: segment base64url. Access / id tokens are 3-segment JWS, so the *5-segment* shape
#: (four dots) — not the segment length — is what uniquely identifies the refresh
#: token on disk. We match it with a LINEAR scan, never a single backtracking regex:
#: ``_TOKEN_RUN_RE`` is one character class (so it scans a multi-MB LevelDB blob in
#: O(n) with no catastrophic backtracking), then each run is split on ``.`` and the
#: five-consecutive-segment window is validated in Python. The per-segment minimums
#: stay modest so synthetic/edge tokens match while the four-dot structure rejects any
#: 3-segment JWS substring.
_TOKEN_RUN_RE = re.compile(r"[A-Za-z0-9_.-]+")
_JWE_SEGMENTS = 5
_JWE_FIRST_MIN = 8
_JWE_REST_MIN = 6
#: A printable token value (e.g. a uid) as it sits next to its key in the LevelDB blob.
_TOKEN_VALUE_RE = re.compile(r"[A-Za-z0-9._-]{8,}")


def _jwe_in_run(run: str) -> str | None:
    """Return the first 5-segment JWE inside a dot-joined token run, else ``None``.

    Linear in ``len(run)``: a single ``str.split`` plus a sliding window over the
    resulting segments — no regex backtracking.
    """
    parts = run.split(".")
    if len(parts) < _JWE_SEGMENTS:
        return None
    for i in range(len(parts) - _JWE_SEGMENTS + 1):
        window = parts[i : i + _JWE_SEGMENTS]
        if len(window[0]) >= _JWE_FIRST_MIN and all(len(p) >= _JWE_REST_MIN for p in window[1:]):
            return ".".join(window)
    return None


def _iter_jwes(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(start_offset, jwe)`` for every 5-segment JWE in ``text`` (linear scan)."""
    for run in _TOKEN_RUN_RE.finditer(text):
        jwe = _jwe_in_run(run.group(0))
        if jwe is not None:
            yield run.start(), jwe


class TTAuthError(RuntimeError):
    """Auth problem the operator can correct (missing token, malformed JWT, mint failure).

    Never carries token material in its message — only the actionable cause.
    """


@dataclass(frozen=True)
class TTConfig:
    """Public Track Titan / Cognito configuration (no secrets)."""

    region: str = _DEFAULT_REGION
    user_pool_id: str = _DEFAULT_USER_POOL_ID
    app_client_id: str = _DEFAULT_APP_CLIENT_ID
    identity_pool_id: str = _DEFAULT_IDENTITY_POOL_ID

    @property
    def idp_url(self) -> str:
        """Cognito IDP endpoint used for ``InitiateAuth`` (refresh → access/id)."""
        return f"https://cognito-idp.{self.region}.amazonaws.com/"

    @property
    def identity_url(self) -> str:
        """Cognito Identity-Pool endpoint (``GetId`` / ``GetCredentialsForIdentity``)."""
        return f"https://cognito-identity.{self.region}.amazonaws.com/"

    @property
    def user_pool_provider(self) -> str:
        """The ``Logins`` provider key for federating the user-pool id token."""
        return f"cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TTConfig:
        """Build config, letting ``TT_COGNITO_*`` env vars override the public defaults."""
        e = os.environ if env is None else env
        return cls(
            region=e.get("TT_COGNITO_REGION", _DEFAULT_REGION),
            user_pool_id=e.get("TT_COGNITO_USER_POOL_ID", _DEFAULT_USER_POOL_ID),
            app_client_id=e.get("TT_COGNITO_CLIENT_ID", _DEFAULT_APP_CLIENT_ID),
            identity_pool_id=e.get("TT_COGNITO_IDENTITY_POOL_ID", _DEFAULT_IDENTITY_POOL_ID),
        )


@dataclass(frozen=True)
class MintedTokens:
    """Result of a refresh → access/id token mint. Treat as a personal secret."""

    access_token: str
    id_token: str
    expires_in: int
    token_type: str = "Bearer"


# --------------------------------------------------------------------------------------
# Pure JWT helpers (operate on access / id tokens — the 3-segment JWS, never the JWE).
# --------------------------------------------------------------------------------------


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + pad)
    except (binascii.Error, ValueError) as exc:  # pragma: no cover - defensive
        raise TTAuthError("malformed base64url in JWT segment") from exc


def decode_jwt_payload(token: str) -> dict[str, Any]:
    """Decode the (unverified) payload of a 3-segment JWS access/id token.

    We never *verify* the signature — these tokens were just minted by Cognito for
    our own request; we only read claims (``exp``, ``sub``) to schedule refresh and
    discover the user id. Refresh tokens are 5-segment JWEs and are NOT decodable
    here (their payload is encrypted) — that is intentional.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise TTAuthError(f"expected a 3-segment JWS, got {len(parts)} segments")
    payload = _b64url_decode(parts[1])
    try:
        claims = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TTAuthError("JWT payload is not valid JSON") from exc
    if not isinstance(claims, dict):
        raise TTAuthError("JWT payload is not a JSON object")
    return claims


def token_expiry(token: str) -> datetime | None:
    """Return the token's ``exp`` as a tz-aware UTC datetime, or ``None`` if absent."""
    exp = decode_jwt_payload(token).get("exp")
    if exp is None:
        return None
    try:
        return datetime.fromtimestamp(float(exp), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise TTAuthError("JWT exp claim is not a valid timestamp") from exc


def is_token_expired(token: str, *, skew_s: float = 60.0, now: datetime | None = None) -> bool:
    """True if the token is expired (or within ``skew_s`` of expiry). No ``exp`` → expired."""
    expiry = token_expiry(token)
    if expiry is None:
        return True
    current = datetime.now(UTC) if now is None else now
    return (expiry.timestamp() - current.timestamp()) <= skew_s


def uid_from_token(token: str) -> str:
    """Extract the Cognito user id (``sub``) from a decoded access/id token."""
    sub = decode_jwt_payload(token).get("sub")
    if not isinstance(sub, str) or not sub:
        raise TTAuthError("token has no usable 'sub' claim")
    return sub


# --------------------------------------------------------------------------------------
# Pure refresh-token discovery (operate on already-read LevelDB text).
# --------------------------------------------------------------------------------------


def extract_refresh_token_from_text(text: str, *, app_client_id: str) -> str | None:
    """Find the refresh-token JWE in a Local Storage LevelDB blob decoded as text.

    Strategy: locate the ``...<clientId>.<uid>.refreshToken`` key, then return the
    first 5-segment JWE that appears after it. Falls back to "the single 5-segment
    JWE anywhere in the blob" when the key marker is absent (LevelDB compaction can
    reorder key/value bytes). Returns ``None`` when no JWE is present.
    """
    key_re = re.compile(_REFRESH_TOKEN_KEY_RE_TEMPLATE.format(client=re.escape(app_client_id)))
    marker = key_re.search(text)
    # One linear pass collects every JWE with its offset (no backtracking on a multi-MB blob).
    candidates = list(_iter_jwes(text))
    if marker is not None:
        after = marker.end()
        for offset, jwe in candidates:
            if offset >= after:
                return jwe
    if not candidates:
        return None
    # Fallback: the refresh token is the only 5-segment JWE on disk; prefer the longest
    # (the real ~1778-char JWE dwarfs any incidental match).
    return max((jwe for _, jwe in candidates), key=len)


def extract_uid_from_text(text: str, *, app_client_id: str) -> str | None:
    """Extract the logged-in user id from the LevelDB blob, if present.

    Prefers the ``<clientId>.<uid>.refreshToken`` key (uid is the captured group);
    falls back to the value written next to the ``LastAuthUser`` key.
    """
    key_re = re.compile(_REFRESH_TOKEN_KEY_RE_TEMPLATE.format(client=re.escape(app_client_id)))
    marker = key_re.search(text)
    if marker is not None:
        uid = marker.group("uid").strip()
        if uid:
            return uid
    last_auth_re = re.compile(
        _LAST_AUTH_USER_KEY_RE_TEMPLATE.format(client=re.escape(app_client_id))
    )
    last = last_auth_re.search(text)
    if last is not None:
        value = _TOKEN_VALUE_RE.search(text[last.end() :])
        if value is not None:
            return value.group(0)
    return None


def default_leveldb_dir(env: Mapping[str, str] | None = None) -> Path | None:
    """Default path to the Track Titan Local Storage LevelDB directory on Windows."""
    e = os.environ if env is None else env
    appdata = e.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "track-titan-ghost-application" / "Local Storage" / "leveldb"


def _read_leveldb_text(leveldb_dir: Path) -> str:
    """Read every ``*.ldb`` / ``*.log`` file in the dir and decode leniently.

    Best-effort, file-IO only (``# pragma: no cover`` — exercised live, not in CI):
    Chromium holds the active ``.log`` open while the app runs; we read what we can
    and skip locked files so a running Track Titan never blocks discovery when other
    SSTables already hold the token.
    """
    chunks: list[str] = []
    for path in sorted(leveldb_dir.glob("*")):  # pragma: no cover - local file IO
        if path.suffix.lower() not in {".ldb", ".log"}:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        chunks.append(raw.decode("latin-1", errors="replace"))
    return "\n".join(chunks)


def resolve_refresh_token(
    config: TTConfig,
    *,
    leveldb_dir: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve the operator's refresh token: ``TT_REFRESH_TOKEN`` env first, then disk.

    Raises :class:`TTAuthError` (with no token material) when neither source yields a
    token, telling the operator how to provide one.
    """
    e = os.environ if env is None else env
    env_token = e.get("TT_REFRESH_TOKEN", "").strip()
    if env_token:
        return env_token
    search_dir = leveldb_dir if leveldb_dir is not None else default_leveldb_dir(e)
    if search_dir is not None and search_dir.is_dir():  # pragma: no cover - local file IO
        text = _read_leveldb_text(search_dir)
        token = extract_refresh_token_from_text(text, app_client_id=config.app_client_id)
        if token:
            return token
    raise TTAuthError(
        "no Track Titan refresh token found. Set TT_REFRESH_TOKEN (preferred; source "
        "from Doppler / your shell) or ensure the Track Titan desktop app has been "
        "signed in so its Local Storage LevelDB holds a refreshToken."
    )


# --------------------------------------------------------------------------------------
# Cognito InitiateAuth (refresh → access/id). Request builder + parser are pure; the
# HTTP round-trip is isolated and ``# pragma: no cover``.
# --------------------------------------------------------------------------------------


def build_initiate_auth_request(
    refresh_token: str, config: TTConfig
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the (url, headers, json-body) for a Cognito ``REFRESH_TOKEN_AUTH`` call."""
    headers = {
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        "Content-Type": "application/x-amz-json-1.1",
    }
    body = {
        "AuthFlow": "REFRESH_TOKEN_AUTH",
        "ClientId": config.app_client_id,
        "AuthParameters": {"REFRESH_TOKEN": refresh_token},
    }
    return config.idp_url, headers, body


def parse_initiate_auth_response(payload: Mapping[str, Any]) -> MintedTokens:
    """Parse Cognito's ``InitiateAuth`` response into :class:`MintedTokens`."""
    result = payload.get("AuthenticationResult")
    if not isinstance(result, Mapping):
        raise TTAuthError("InitiateAuth response missing AuthenticationResult")
    access_token = result.get("AccessToken")
    id_token = result.get("IdToken")
    if not isinstance(access_token, str) or not access_token:
        raise TTAuthError("InitiateAuth response missing AccessToken")
    if not isinstance(id_token, str) or not id_token:
        raise TTAuthError("InitiateAuth response missing IdToken")
    expires_in_raw = result.get("ExpiresIn", 3600)
    try:
        expires_in = int(expires_in_raw)
    except (TypeError, ValueError):
        expires_in = 3600
    token_type = result.get("TokenType")
    return MintedTokens(
        access_token=access_token,
        id_token=id_token,
        expires_in=expires_in,
        token_type=token_type if isinstance(token_type, str) and token_type else "Bearer",
    )


def mint_tokens(
    refresh_token: str,
    config: TTConfig | None = None,
    *,
    http: Any | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> MintedTokens:  # pragma: no cover - network round-trip, verified live (issue #353)
    """Exchange a refresh token for fresh access + id tokens via Cognito InitiateAuth.

    ``http`` may be any object exposing ``post(url, headers=, json=, timeout=)`` (a
    ``requests.Session``); defaults to a lazily imported ``requests``.
    """
    cfg = config or TTConfig.from_env()
    url, headers, body = build_initiate_auth_request(refresh_token, cfg)
    client = http
    if client is None:
        import requests as requests_mod

        client = requests_mod
    try:
        response = client.post(url, headers=headers, json=body, timeout=timeout)
    except Exception as exc:
        # Belt-and-suspenders for invariant (1): the request body carries the refresh
        # token, so re-raise transport failures with only the exception *type* name and
        # NO chained cause, so no library traceback (which could echo the request) escapes.
        raise TTAuthError(f"Cognito InitiateAuth request failed: {type(exc).__name__}") from None
    if getattr(response, "status_code", 200) >= 400:
        # Surface status only — never the response body, which can echo token material.
        raise TTAuthError(f"Cognito InitiateAuth failed with HTTP {response.status_code}")
    return parse_initiate_auth_response(response.json())
