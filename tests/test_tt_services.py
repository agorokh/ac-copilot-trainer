"""Unit tests for tools.tt_ingest.tt_services (issue #353, M-TT1).

Fixtures are SANITIZED captures from the live services API (CDP capture, 2026-06-29):
the operator's uid + reference-driver identity are replaced with stable fakes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.tt_ingest.tt_services import (
    SERVICES_BASE,
    THEORETICAL_BEST_REF,
    CoachingStory,
    TTServicesError,
    advice_segment_url,
    analysis_progress_url,
    dynamic_reference_lap_url,
    fetch_advice_segment,
    fetch_dynamic_reference_lap,
    fetch_last_session,
    find_session,
    is_enveloped,
    lap_reference_url,
    last_session_url,
    parse_advice,
    parse_last_session,
    parse_reference_lap,
    parse_services_sessions,
    reference_identity,
    reference_lap_segments,
    reference_lap_url,
    services_sessions_url,
    session_key_of,
    unwrap_envelope,
)

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# --- URL builders -----------------------------------------------------------------


def test_services_sessions_url() -> None:
    url = services_sessions_url("uid-1", page=2, limit=10, hide_limited=True)
    assert url == f"{SERVICES_BASE}/api/v2/users/uid-1/sessions?page=2&hideLimited=true&limit=10"


def test_last_session_url() -> None:
    assert last_session_url("uid-1") == f"{SERVICES_BASE}/api/v2/sessions/uid-1/last-session"


def test_lap_reference_url() -> None:
    url = lap_reference_url("uid-1", "20260629005756", 5)
    assert url == f"{SERVICES_BASE}/api/v2/sessions/uid-1/20260629005756/laps/5/reference"


def test_dynamic_reference_lap_url_default_segment_count() -> None:
    url = dynamic_reference_lap_url("uid-1", "sk-9", 4)
    assert url == (
        f"{SERVICES_BASE}/dynamic-reference-laps/sessions/uid-1/sk-9/laps/4?segmentCount=7"
    )


def test_reference_lap_url() -> None:
    url = reference_lap_url("u", "s", "refu", "refs", "theoreticalBestRef")
    assert url == (
        f"{SERVICES_BASE}/api/v2/sessions/u/s/reference/refu/refs/laps/theoreticalBestRef"
    )


def test_advice_segment_url_defaults_to_theoretical_best() -> None:
    url = advice_segment_url("u", "s", 5, "refu", "refs", 1)
    assert THEORETICAL_BEST_REF in url
    assert url.endswith("/segments/1")
    assert "/advice/sessions/u/s/laps/5/reference/refu/refs/laps/" in url


def test_analysis_progress_url_encodes_query() -> None:
    url = analysis_progress_url("u", game_id="assettoCorsa", track_id="magione", car_id="a/b")
    assert "gameId=assettoCorsa" in url and "trackId=magione" in url
    assert "carId=a%2Fb" in url  # the '/' in the car id is encoded, not a path break


def test_url_builders_encode_segments() -> None:
    # A uid containing '#'/'/' must never break out of its path segment.
    assert "%23" in last_session_url("uid#weird")
    assert "uid%2Fevil" in last_session_url("uid/evil")


# --- envelope ---------------------------------------------------------------------


def test_is_enveloped() -> None:
    assert is_enveloped({"success": True, "data": {}})
    assert not is_enveloped({"session": "x", "lap": {}})


def test_unwrap_envelope_enveloped() -> None:
    assert unwrap_envelope({"success": True, "data": {"k": 1}, "status": 200}) == {"k": 1}


def test_unwrap_envelope_bare_returns_self() -> None:
    bare = {"session": "x", "lap": {"lap_time": "1"}}
    assert unwrap_envelope(bare) is bare


def test_unwrap_envelope_failure_raises() -> None:
    with pytest.raises(TTServicesError):
        unwrap_envelope({"success": False, "data": None, "status": 500})


def test_unwrap_envelope_non_mapping_raises() -> None:
    with pytest.raises(TTServicesError):
        unwrap_envelope([1, 2, 3])  # type: ignore[arg-type]


# --- parse_advice -----------------------------------------------------------------


def test_parse_advice_from_fixture() -> None:
    stories = parse_advice(_load("tt_services_advice.json"))
    assert len(stories) == 1
    s = stories[0]
    assert isinstance(s, CoachingStory)
    assert s.diagnosis_key == "coaching.diagnosis.rotation_insufficient"
    assert s.diagnosis.startswith("You made a mistake")
    assert s.highlight is not None and len(s.highlight) == 2
    assert s.is_actionable  # timeLoss 0.001 > 0


def test_parse_advice_handles_no_stories() -> None:
    assert parse_advice({"success": True, "status": 200, "data": {"stories": None}}) == []


def test_coaching_story_not_actionable_when_zero_loss() -> None:
    assert not CoachingStory("d", "c", "dk", "ck", 0.0, "nfta", (0.0, 0.1)).is_actionable
    assert not CoachingStory("d", "c", "dk", "ck", None, None, None).is_actionable


# --- reference lap ----------------------------------------------------------------


def test_parse_reference_lap_bare_dynamic() -> None:
    lap = parse_reference_lap(_load("tt_services_dynamic_reference.json"))
    assert lap["name"] == "dynamicComparisonLap"
    assert lap["lap_time"] == "71035"


def test_parse_reference_lap_enveloped() -> None:
    lap = parse_reference_lap(_load("tt_services_lap_reference.json"))
    assert lap["name"] == "dynamicComparisonLap"


def test_reference_identity() -> None:
    lap = parse_reference_lap(_load("tt_services_dynamic_reference.json"))
    ref_uid, ref_sk = reference_identity(lap)
    assert ref_uid == "ref-uid-002"
    assert ref_sk == "20220611194228"


def test_reference_identity_missing_raises() -> None:
    with pytest.raises(TTServicesError):
        reference_identity({"user_id": "", "session_key": "x"})


def test_reference_lap_segments_sorted() -> None:
    lap = parse_reference_lap(_load("tt_services_dynamic_reference.json"))
    segs = reference_lap_segments(lap)
    assert [n for n, _ in segs] == sorted(n for n, _ in segs)
    assert segs[0] == (1, 11281.8)


# --- last session -----------------------------------------------------------------


def test_parse_last_session() -> None:
    out = parse_last_session(_load("tt_services_last_session.json"))
    assert out["session"]["game_id"] == "assettoCorsa"
    assert out["session"]["track_id"] == "magione"
    assert out["session"]["lap_number"] == 5
    assert out["reference_lap"] is not None


def test_parse_last_session_missing_session_raises() -> None:
    with pytest.raises(TTServicesError):
        parse_last_session({"success": True, "status": 200, "data": {"foo": 1}})


# --- network wiring with fake http ------------------------------------------------


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeHttp:
    def __init__(self, payload) -> None:
        self._payload = payload
        self.urls: list[str] = []
        self.headers: list[dict] = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        self.headers.append(headers or {})
        # services authenticates with the RAW access token (no 'Bearer ' prefix).
        assert headers is not None and not headers["Authorization"].startswith("Bearer ")
        return _FakeResponse(self._payload)


def test_fetch_last_session_wiring() -> None:
    http = _FakeHttp(_load("tt_services_last_session.json"))
    out = fetch_last_session("raw-access-token", "uid-1", http=http)
    assert out["session"]["track_id"] == "magione"
    assert "uid-1/last-session" in http.urls[0]
    assert http.headers[0]["Authorization"] == "raw-access-token"


def test_fetch_dynamic_reference_lap_wiring() -> None:
    http = _FakeHttp(_load("tt_services_dynamic_reference.json"))
    body = fetch_dynamic_reference_lap("tok", "uid-1", "sk-1", 4, segment_count=7, http=http)
    assert body["lap"]["name"] == "dynamicComparisonLap"
    assert "segmentCount=7" in http.urls[0]


def test_fetch_advice_segment_wiring() -> None:
    http = _FakeHttp(_load("tt_services_advice.json"))
    stories = fetch_advice_segment("tok", "u", "s", 5, "refu", "refs", 1, http=http)
    assert stories[0].diagnosis_key == "coaching.diagnosis.rotation_insufficient"
    assert "/segments/1" in http.urls[0]


def test_services_get_raises_on_http_error() -> None:
    class _ErrHttp:
        def get(self, url, headers=None, timeout=None):
            return _FakeResponse({}, status_code=403)

    with pytest.raises(TTServicesError):
        fetch_last_session("tok", "uid-1", http=_ErrHttp())


# --- services sessions list (parse + find) ----------------------------------------


def test_parse_services_sessions_from_fixture() -> None:
    rows = parse_services_sessions(_load("tt_services_sessions.json"))
    assert len(rows) == 2
    assert all(isinstance(r, dict) for r in rows)
    assert rows[0].get("game_id")


def test_parse_services_sessions_bare_list() -> None:
    rows = parse_services_sessions(
        {"success": True, "status": 200, "data": [{"id": "u#a"}, "junk", {"id": "u#b"}]}
    )
    assert [r["id"] for r in rows] == ["u#a", "u#b"]


def test_parse_services_sessions_missing_raises() -> None:
    with pytest.raises(TTServicesError):
        parse_services_sessions({"success": True, "status": 200, "data": {"count": 0}})


def test_session_key_of() -> None:
    assert session_key_of({"id": "uid-1#20260629005756"}) == "20260629005756"
    assert session_key_of({"session_id": "u#sk-2"}) == "sk-2"
    assert session_key_of({"session_key": "sk-3"}) == "sk-3"
    assert session_key_of({"id": "no-separator"}) is None


def test_find_session() -> None:
    rows = parse_services_sessions(_load("tt_services_sessions.json"))
    key = session_key_of(rows[0])
    found = find_session(rows, key)
    assert found is not None and session_key_of(found) == key
    assert find_session(rows, "does-not-exist") is None


def test_fetch_session_coaching_bundle_separates_references() -> None:
    # Build advice URLs against the operator's OWN theoreticalBestRef (observed renderer
    # behaviour) while recording the dynamic reference's identity distinctly — so the bundle
    # never mislabels the advice source (PR #370 review fix).
    from tools.tt_ingest.tt_services import fetch_session_coaching

    class _SeqHttp:
        """Returns the dynamic-reference payload first, then advice for each segment."""

        def __init__(self) -> None:
            self.urls: list[str] = []
            self._dyn = _load("tt_services_dynamic_reference.json")
            self._advice = _load("tt_services_advice.json")

        def get(self, url, headers=None, timeout=None):
            self.urls.append(url)
            payload = self._dyn if "dynamic-reference-laps" in url else self._advice
            return _FakeResponse(payload)

    http = _SeqHttp()
    bundle = fetch_session_coaching("tok", "own-uid", "own-sk", 5, segment_count=2, http=http)
    # dynamic_reference is the OTHER driver from the dynamic-reference-laps payload...
    assert bundle["dynamic_reference"] == ["ref-uid-002", "20220611194228"]
    # ...while advice was requested against the operator's OWN session + theoreticalBestRef.
    assert bundle["advice_reference"] == ["own-uid", "own-sk", THEORETICAL_BEST_REF]
    advice_urls = [u for u in http.urls if "/advice/" in u]
    assert advice_urls and all(
        "own-uid/own-sk" in u and THEORETICAL_BEST_REF in u for u in advice_urls
    )
