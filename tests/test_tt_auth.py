"""Unit tests for tools.tt_ingest.tt_auth (issue #353).

Covers the pure JWT helpers, refresh-token discovery, the InitiateAuth request
builder + response parser, and (for wiring confidence) the network mint with a fake
HTTP client. No real tokens or network are involved.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest

from tools.tt_ingest import tt_auth
from tools.tt_ingest.tt_auth import (
    MintedTokens,
    TTAuthError,
    TTConfig,
    build_initiate_auth_request,
    decode_jwt_payload,
    default_leveldb_dir,
    extract_refresh_token_from_text,
    extract_uid_from_text,
    is_token_expired,
    mint_tokens,
    parse_initiate_auth_response,
    resolve_refresh_token,
    token_expiry,
    uid_from_token,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_jws(payload: dict) -> str:
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    return f"{header}.{body}.signaturesig"


# A fake 5-segment JWE shape (header.key.iv.ciphertext.tag) — not a real token.
FAKE_JWE = "AAAAheaderseg.BBBBkeyseg11.CCCCivseg222.DDDDcipherseg3333.EEEEtagseg44"


# --- TTConfig ---------------------------------------------------------------------


def test_ttconfig_defaults_and_properties() -> None:
    cfg = TTConfig()
    assert cfg.region == "us-east-1"
    assert cfg.idp_url == "https://cognito-idp.us-east-1.amazonaws.com/"
    assert cfg.identity_url == "https://cognito-identity.us-east-1.amazonaws.com/"
    assert cfg.user_pool_provider == f"cognito-idp.us-east-1.amazonaws.com/{cfg.user_pool_id}"


def test_ttconfig_from_env_overrides() -> None:
    cfg = TTConfig.from_env({"TT_COGNITO_REGION": "eu-west-1", "TT_COGNITO_CLIENT_ID": "client123"})
    assert cfg.region == "eu-west-1"
    assert cfg.app_client_id == "client123"
    assert cfg.idp_url == "https://cognito-idp.eu-west-1.amazonaws.com/"


# --- JWT helpers ------------------------------------------------------------------


def test_decode_jwt_payload_roundtrip() -> None:
    token = _make_jws({"sub": "user-xyz", "exp": 1_900_000_000})
    claims = decode_jwt_payload(token)
    assert claims["sub"] == "user-xyz"
    assert claims["exp"] == 1_900_000_000


def test_decode_jwt_payload_rejects_non_three_segment() -> None:
    with pytest.raises(TTAuthError):
        decode_jwt_payload(FAKE_JWE)  # 5 segments


def test_decode_jwt_payload_rejects_non_json() -> None:
    bad = f"{_b64url(b'header')}.{_b64url(b'not-json')}.sig"
    with pytest.raises(TTAuthError):
        decode_jwt_payload(bad)


def test_token_expiry_returns_tz_aware() -> None:
    token = _make_jws({"exp": 1_900_000_000})
    expiry = token_expiry(token)
    assert expiry is not None
    assert expiry.tzinfo is not None
    assert expiry == datetime.fromtimestamp(1_900_000_000, tz=UTC)


def test_token_expiry_none_when_absent() -> None:
    assert token_expiry(_make_jws({"sub": "x"})) is None


def test_is_token_expired_with_injected_now() -> None:
    token = _make_jws({"exp": 1_900_000_000})
    before = datetime.fromtimestamp(1_800_000_000, tz=UTC)
    after = datetime.fromtimestamp(1_950_000_000, tz=UTC)
    assert is_token_expired(token, now=after) is True
    assert is_token_expired(token, now=before) is False


def test_is_token_expired_when_no_exp() -> None:
    assert is_token_expired(_make_jws({"sub": "x"})) is True


def test_uid_from_token() -> None:
    assert uid_from_token(_make_jws({"sub": "abc-123"})) == "abc-123"


def test_uid_from_token_requires_sub() -> None:
    with pytest.raises(TTAuthError):
        uid_from_token(_make_jws({"exp": 1}))


# --- refresh-token discovery ------------------------------------------------------


def test_extract_refresh_token_with_key_marker() -> None:
    client = "6qp755fd6379572i96kt1hvu55"
    text = (
        f"someprefix\x00CognitoIdentityServiceProvider.{client}.user-9.refreshToken\x01"
        f"{FAKE_JWE}\x00trailing"
    )
    assert extract_refresh_token_from_text(text, app_client_id=client) == FAKE_JWE


def test_extract_refresh_token_fallback_longest() -> None:
    short = "aa.bb.cc.dd.ee"
    text = f"noise {short} noise {FAKE_JWE} more"
    got = extract_refresh_token_from_text(text, app_client_id="whatever")
    assert got == FAKE_JWE


def test_extract_refresh_token_none_when_absent() -> None:
    assert extract_refresh_token_from_text("no jwe here", app_client_id="x") is None


def test_extract_uid_from_refresh_key() -> None:
    client = "client42"
    text = f"CognitoIdentityServiceProvider.{client}.cognito-user-77.refreshToken={FAKE_JWE}"
    assert extract_uid_from_text(text, app_client_id=client) == "cognito-user-77"


def test_extract_uid_from_last_auth_user() -> None:
    client = "client42"
    text = f"CognitoIdentityServiceProvider.{client}.LastAuthUser\x01last-user-value-001\x00"
    assert extract_uid_from_text(text, app_client_id=client) == "last-user-value-001"


def test_extract_uid_none() -> None:
    assert extract_uid_from_text("nothing relevant", app_client_id="x") is None


def test_default_leveldb_dir_with_appdata(tmp_path) -> None:
    got = default_leveldb_dir({"APPDATA": str(tmp_path)})
    assert got is not None
    assert got.parts[-3:] == ("track-titan-ghost-application", "Local Storage", "leveldb")


def test_default_leveldb_dir_without_appdata() -> None:
    assert default_leveldb_dir({}) is None


def test_resolve_refresh_token_env_wins() -> None:
    cfg = TTConfig()
    assert resolve_refresh_token(cfg, env={"TT_REFRESH_TOKEN": "  tok-abc  "}) == "tok-abc"


def test_resolve_refresh_token_from_leveldb(tmp_path) -> None:
    cfg = TTConfig()
    client = cfg.app_client_id
    ldb = tmp_path / "000003.ldb"
    ldb.write_bytes(
        f"CognitoIdentityServiceProvider.{client}.user-1.refreshToken={FAKE_JWE}".encode()
    )
    assert resolve_refresh_token(cfg, leveldb_dir=tmp_path, env={}) == FAKE_JWE


def test_resolve_refresh_token_missing_has_no_token_in_message(tmp_path) -> None:
    cfg = TTConfig()
    with pytest.raises(TTAuthError) as excinfo:
        resolve_refresh_token(cfg, leveldb_dir=tmp_path / "empty", env={})
    assert "TT_REFRESH_TOKEN" in str(excinfo.value)


# --- InitiateAuth builder + parser + mint -----------------------------------------


def test_build_initiate_auth_request() -> None:
    cfg = TTConfig()
    url, headers, body = build_initiate_auth_request("rt-secret", cfg)
    assert url == cfg.idp_url
    assert headers["X-Amz-Target"] == "AWSCognitoIdentityProviderService.InitiateAuth"
    assert headers["Content-Type"] == "application/x-amz-json-1.1"
    assert body["AuthFlow"] == "REFRESH_TOKEN_AUTH"
    assert body["ClientId"] == cfg.app_client_id
    assert body["AuthParameters"]["REFRESH_TOKEN"] == "rt-secret"


def test_parse_initiate_auth_response_success() -> None:
    payload = {
        "AuthenticationResult": {
            "AccessToken": "acc-tok",
            "IdToken": "id-tok",
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    }
    minted = parse_initiate_auth_response(payload)
    assert minted == MintedTokens("acc-tok", "id-tok", 3600, "Bearer")


def test_parse_initiate_auth_response_missing_result() -> None:
    with pytest.raises(TTAuthError):
        parse_initiate_auth_response({})


def test_parse_initiate_auth_response_missing_tokens() -> None:
    with pytest.raises(TTAuthError):
        parse_initiate_auth_response({"AuthenticationResult": {"AccessToken": "x"}})


def test_parse_initiate_auth_response_defaults_expires_in() -> None:
    payload = {"AuthenticationResult": {"AccessToken": "a", "IdToken": "b", "ExpiresIn": "bad"}}
    minted = parse_initiate_auth_response(payload)
    assert minted.expires_in == 3600
    assert minted.token_type == "Bearer"


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeHttp:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002 - mirror requests
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self._response


def test_mint_tokens_with_fake_http() -> None:
    response = _FakeResponse(
        {"AuthenticationResult": {"AccessToken": "acc", "IdToken": "idt", "ExpiresIn": 3600}}
    )
    http = _FakeHttp(response)
    minted = mint_tokens("rt", TTConfig(), http=http)
    assert minted.access_token == "acc"
    assert http.calls[0]["json"]["AuthParameters"]["REFRESH_TOKEN"] == "rt"


def test_mint_tokens_raises_on_http_error() -> None:
    http = _FakeHttp(_FakeResponse({}, status_code=400))
    with pytest.raises(TTAuthError) as excinfo:
        mint_tokens("rt", TTConfig(), http=http)
    assert "400" in str(excinfo.value)


def test_module_exposes_default_timeout() -> None:
    assert tt_auth.DEFAULT_REQUEST_TIMEOUT_S > 0


# --- regression tests for the PR-359 adversarial-review fixes ----------------------


def test_extract_refresh_token_is_linear_on_large_blob() -> None:
    # ReDoS regression: a several-hundred-KB run of token chars with NO 5-segment JWE must
    # resolve quickly. The previous single backtracking regex took ~minutes on this shape.
    import time

    client = "client-x"
    big = "A" * 300_000  # one long run, no dots → cannot be a JWE
    text = f"{big} CognitoIdentityServiceProvider.{client}.u.refreshToken {FAKE_JWE} {big}"
    start = time.monotonic()
    got = extract_refresh_token_from_text(text, app_client_id=client)
    assert time.monotonic() - start < 3.0
    assert got == FAKE_JWE


def test_extract_refresh_token_ignores_3segment_jws() -> None:
    # A long 3-segment access-token JWS (only 2 dots) must never be taken as the refresh JWE.
    jws = "a" * 800 + "." + "b" * 800 + "." + "c" * 64
    assert extract_refresh_token_from_text(jws, app_client_id="x") is None


def test_extract_refresh_token_same_run_marker_and_value() -> None:
    # When LevelDB stores the key and its JWE value in ONE token-run (no separating control
    # byte), the value must still be selected AFTER the marker, and a longer *incidental* JWE
    # before the marker must not win. Regression for the run-vs-JWE offset selection bug.
    client = "client9"
    real = "RRRRRRRR.rrrrrr.rrrrrr.rrrrrr.rrrrrr"
    incidental = "I" * 40 + ".iiiiiiiiii.iiiiiiiiii.iiiiiiiiii.iiiiiiiiii"  # longer than real
    text = f"{incidental} CognitoIdentityServiceProvider.{client}.uid7.refreshToken.{real}"
    assert extract_refresh_token_from_text(text, app_client_id=client) == real


def test_is_token_expired_skew_boundary() -> None:
    token = _make_jws({"exp": 1_000_000})
    near = datetime.fromtimestamp(1_000_000 - 30, tz=UTC)  # 30s before expiry, inside 60s skew
    far = datetime.fromtimestamp(1_000_000 - 90, tz=UTC)  # 90s before, outside skew
    assert is_token_expired(token, skew_s=60, now=near) is True
    assert is_token_expired(token, skew_s=60, now=far) is False
    # The 60s default skew is applied when skew_s is omitted.
    assert is_token_expired(token, now=near) is True


def test_resolve_refresh_token_env_precedes_populated_leveldb(tmp_path) -> None:
    cfg = TTConfig()
    ldb = tmp_path / "000003.ldb"
    ldb.write_bytes(
        f"CognitoIdentityServiceProvider.{cfg.app_client_id}.u.refreshToken={FAKE_JWE}".encode()
    )
    # Env token must win even when disk holds a (different) token.
    got = resolve_refresh_token(cfg, leveldb_dir=tmp_path, env={"TT_REFRESH_TOKEN": "env-token"})
    assert got == "env-token"


def test_resolve_refresh_token_blank_env_falls_through_to_disk(tmp_path) -> None:
    cfg = TTConfig()
    ldb = tmp_path / "000003.ldb"
    ldb.write_bytes(
        f"CognitoIdentityServiceProvider.{cfg.app_client_id}.u.refreshToken={FAKE_JWE}".encode()
    )
    got = resolve_refresh_token(cfg, leveldb_dir=tmp_path, env={"TT_REFRESH_TOKEN": "   "})
    assert got == FAKE_JWE


def test_parse_initiate_auth_rejects_empty_access_token() -> None:
    with pytest.raises(TTAuthError):
        parse_initiate_auth_response({"AuthenticationResult": {"AccessToken": "", "IdToken": "x"}})


def test_parse_initiate_auth_preserves_non_bearer_token_type() -> None:
    minted = parse_initiate_auth_response(
        {"AuthenticationResult": {"AccessToken": "a", "IdToken": "b", "TokenType": "Token"}}
    )
    assert minted.token_type == "Token"
