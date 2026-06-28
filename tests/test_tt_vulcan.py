"""Unit tests for tools.tt_ingest.tt_vulcan (issue #353)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.tt_ingest.tt_vulcan import (
    VULCAN_BASE,
    SessionsPage,
    TTVulcanError,
    fetch_sessions_page,
    iter_all_sessions,
    parse_sessions_page,
    session_detail_url,
    session_summary,
    sessions_url,
    split_session_id,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tt_sessions_page.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- URL builders -----------------------------------------------------------------


def test_sessions_url() -> None:
    url = sessions_url("uid-1", limit=25, page=3)
    assert url == f"{VULCAN_BASE}/users/uid-1/sessions?limit=25&page=3"


def test_sessions_url_encodes_uid() -> None:
    assert "uid%23weird" in sessions_url("uid#weird")


def test_session_detail_url_encodes_hash() -> None:
    url = session_detail_url("uid-1#sess-aaa")
    assert "%23" in url
    assert "#" not in url


def test_split_session_id() -> None:
    assert split_session_id("uid-1#sess-aaa") == ("uid-1", "sess-aaa")


def test_split_session_id_errors() -> None:
    with pytest.raises(TTVulcanError):
        split_session_id("no-separator")
    with pytest.raises(TTVulcanError):
        split_session_id("uid#")


# --- parse_sessions_page ----------------------------------------------------------


def test_parse_sessions_page_from_fixture() -> None:
    page = parse_sessions_page(_load_fixture())
    assert isinstance(page, SessionsPage)
    assert page.count == 3
    assert page.limit == 50
    assert len(page.sessions) == 3
    assert page.cars["syn_mercedes_w09"]["name"] == "Mercedes W09"
    assert "assettoCorsa" in page.games


def test_sessions_page_total_pages() -> None:
    page = SessionsPage(count=149, limit=50, page=1, sessions=[])
    assert page.total_pages == 3
    assert SessionsPage(count=0, limit=0, page=1, sessions=[]).total_pages == 1


def test_parse_sessions_page_missing_data() -> None:
    with pytest.raises(TTVulcanError):
        parse_sessions_page({"message": "no data"})


def test_parse_sessions_page_missing_sessions() -> None:
    with pytest.raises(TTVulcanError):
        parse_sessions_page({"data": {"count": 0}})


def test_parse_sessions_page_skips_non_mapping_rows() -> None:
    page = parse_sessions_page({"data": {"sessions": [{"id": "a#b"}, "garbage", 42]}})
    assert len(page.sessions) == 1


# --- session_summary --------------------------------------------------------------


def test_session_summary_full() -> None:
    page = parse_sessions_page(_load_fixture())
    summary = session_summary(page.sessions[0])
    assert "Mercedes W09" in summary
    assert "Red Bull Ring" in summary
    assert "64.321s" in summary


def test_session_summary_degrades_gracefully() -> None:
    summary = session_summary({"car_id": "x", "track_id": "y"})
    assert "best —" in summary


# --- network functions with fake http (wiring confidence) -------------------------


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _FakeHttp:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages
        self.urls: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        # Authorization must be the RAW token (no 'Bearer ' prefix).
        assert headers is not None and not headers["Authorization"].startswith("Bearer ")
        page_idx = len(self.urls) - 1
        return _FakeResponse(self._pages[min(page_idx, len(self._pages) - 1)])


def test_fetch_sessions_page_with_fake_http() -> None:
    http = _FakeHttp([_load_fixture()])
    page = fetch_sessions_page("raw-access-token", "uid-1", http=http)
    assert page.count == 3
    assert "uid-1/sessions" in http.urls[0]


def test_iter_all_sessions_paginates() -> None:
    full = _load_fixture()
    full["data"]["count"] = 6
    full["data"]["limit"] = 3
    page2 = json.loads(json.dumps(full))
    page2["data"]["page"] = 2
    http = _FakeHttp([full, page2])
    rows = list(iter_all_sessions("tok", "uid-1", limit=3, http=http))
    # 3 per page * 2 pages
    assert len(rows) == 6
    assert len(http.urls) == 2


def test_iter_all_sessions_respects_max_pages() -> None:
    full = _load_fixture()
    full["data"]["count"] = 9
    full["data"]["limit"] = 3
    http = _FakeHttp([full])
    rows = list(iter_all_sessions("tok", "uid-1", limit=3, http=http, max_pages=1))
    assert len(rows) == 3
    assert len(http.urls) == 1


def test_fetch_sessions_page_http_error() -> None:
    class _ErrHttp:
        def get(self, url, headers=None, timeout=None):
            return _FakeResponse({}, status_code=403)

    with pytest.raises(TTVulcanError):
        fetch_sessions_page("tok", "uid-1", http=_ErrHttp())


# --- regression tests for the PR-359 adversarial-review fixes ----------------------


def test_parse_sessions_page_coerces_numeric_strings() -> None:
    page = parse_sessions_page(
        {"data": {"count": "149", "limit": "50.0", "page": "1", "sessions": []}}
    )
    assert page.count == 149
    assert page.limit == 50  # float-string coerced → pagination not collapsed to a single page
    assert page.total_pages == 3


def test_session_summary_laps_fallback() -> None:
    summary = session_summary({"car_id": "c", "track_id": "t", "game_id": "g"})
    assert "? lap(s)" in summary
    assert "None" not in summary


def test_session_summary_excludes_pii() -> None:
    # Pin the documented "never tokens or PII" contract against a future regression that
    # might start interpolating user_id / driver_name into the operator-facing log line.
    out = session_summary(parse_sessions_page(_load_fixture()).sessions[0])
    assert "fake-uid-001" not in out
    assert "Operator" not in out
