"""Track Titan **vulcan** API client — the sessions list + per-session metadata
(issue #353, milestone M-TT0).

vulcan (``https://api.tracktitan.io/api/v1``) authenticates with the raw access
token in the ``Authorization`` header (NO ``Bearer`` prefix) and serves the
operator's full session history with per-lap conditions. This alone is **lossless
retention** of every session across cars / tracks / setups (the per-corner traces
live on the *services* API, milestone M-TT1).

URL builders and the response parser are pure and unit-tested; the HTTP round-trips
are isolated and ``# pragma: no cover`` (proven live, issue #353).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from tools.tt_ingest.tt_auth import DEFAULT_REQUEST_TIMEOUT_S

VULCAN_BASE = "https://api.tracktitan.io/api/v1"

#: vulcan session ids are ``{uid}#{sessionKey}``; the ``#`` MUST be percent-encoded.
_SESSION_ID_SEP = "#"


class TTVulcanError(RuntimeError):
    """A vulcan response did not match the documented shape, or an HTTP error."""


@dataclass(frozen=True)
class SessionsPage:
    """One parsed page of ``/users/{uid}/sessions``."""

    count: int
    limit: int
    page: int
    sessions: list[dict[str, Any]]
    cars: dict[str, Any] = field(default_factory=dict)
    games: dict[str, Any] = field(default_factory=dict)
    tracks: dict[str, Any] = field(default_factory=dict)

    @property
    def total_pages(self) -> int:
        """Number of pages needed to retain ``count`` items at this ``limit``."""
        if self.limit <= 0:
            return 1
        return max(1, -(-self.count // self.limit))  # ceil division


def sessions_url(uid: str, *, limit: int = 50, page: int = 1, base: str = VULCAN_BASE) -> str:
    """Build the paginated sessions-list URL for a user id."""
    safe_uid = quote(uid, safe="")
    return f"{base}/users/{safe_uid}/sessions?limit={int(limit)}&page={int(page)}"


def session_detail_url(session_id: str, *, base: str = VULCAN_BASE) -> str:
    """Build the per-session detail URL, percent-encoding the ``#`` in the id."""
    return f"{base}/sessions/{quote(session_id, safe='')}"


def split_session_id(session_id: str) -> tuple[str, str]:
    """Split a ``{uid}#{sessionKey}`` id into ``(uid, session_key)``."""
    if _SESSION_ID_SEP not in session_id:
        raise TTVulcanError(f"session id is not '{{uid}}#{{sessionKey}}': {session_id!r}")
    uid, session_key = session_id.split(_SESSION_ID_SEP, 1)
    if not uid or not session_key:
        raise TTVulcanError(f"session id has empty uid or sessionKey: {session_id!r}")
    return uid, session_key


def parse_sessions_page(payload: Mapping[str, Any]) -> SessionsPage:
    """Parse a raw vulcan sessions-list response into a :class:`SessionsPage`.

    Shape (verified live, issue #353)::

        { "data": { "count", "limit", "page", "sessions": [...],
                    "cars": {...}, "games": {...}, "tracks": {...} },
          "message", "status", "success" }
    """
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise TTVulcanError("vulcan response missing 'data' object")
    sessions = data.get("sessions")
    if not isinstance(sessions, list):
        raise TTVulcanError("vulcan response missing 'data.sessions' list")
    rows = [dict(s) for s in sessions if isinstance(s, Mapping)]

    def _lookup(name: str) -> dict[str, Any]:
        value = data.get(name)
        return dict(value) if isinstance(value, Mapping) else {}

    def _int(name: str, default: int) -> int:
        raw = data.get(name, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            # Tolerate numeric-as-string variants (the API has shipped float-strings like
            # "26.0" for other fields) so a stringified count/limit never silently
            # collapses pagination to a single page.
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return default

    return SessionsPage(
        count=_int("count", len(rows)),
        limit=_int("limit", len(rows) or 1),
        page=_int("page", 1),
        sessions=rows,
        cars=_lookup("cars"),
        games=_lookup("games"),
        tracks=_lookup("tracks"),
    )


def session_summary(session: Mapping[str, Any]) -> str:
    """A single sanitized line for logs — car / track / best-lap, never tokens or PII."""
    car = session.get("carName") or session.get("car_id") or "?"
    track = session.get("trackName") or session.get("track_id") or "?"
    game = session.get("game_id") or "?"
    best = session.get("bestLapTime")
    laps = session.get("lapCount")
    laps_s = laps if laps is not None else "?"
    best_s = f"{best / 1000.0:.3f}s" if isinstance(best, (int, float)) and best > 0 else "—"
    return f"[{game}] {car} @ {track} — best {best_s}, {laps_s} lap(s)"


def _auth_headers(access_token: str) -> dict[str, str]:
    # vulcan expects the RAW access token (no 'Bearer ' prefix) — verified live.
    return {"Authorization": access_token, "Accept": "application/json"}


def _vulcan_get(
    url: str, access_token: str, *, http: Any, timeout: float
) -> dict[str, Any]:  # pragma: no cover - network round-trip, verified live (issue #353)
    response = http.get(url, headers=_auth_headers(access_token), timeout=timeout)
    status = getattr(response, "status_code", 200)
    if status >= 400:
        raise TTVulcanError(f"vulcan GET failed with HTTP {status}: {url}")
    body = response.json()
    if not isinstance(body, Mapping):
        raise TTVulcanError("vulcan response was not a JSON object")
    return dict(body)


def fetch_sessions_page(
    access_token: str,
    uid: str,
    *,
    limit: int = 50,
    page: int = 1,
    http: Any | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> SessionsPage:  # pragma: no cover - network round-trip, verified live (issue #353)
    """Fetch and parse one page of the user's sessions list."""
    client = http
    if client is None:
        import requests as requests_mod

        client = requests_mod
    body = _vulcan_get(
        sessions_url(uid, limit=limit, page=page), access_token, http=client, timeout=timeout
    )
    return parse_sessions_page(body)


def iter_all_sessions(
    access_token: str,
    uid: str,
    *,
    limit: int = 50,
    http: Any | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
    max_pages: int | None = None,
) -> Iterator[dict[str, Any]]:  # pragma: no cover - network round-trip, verified live (#353)
    """Yield every session across all pages (or up to ``max_pages``)."""
    client = http
    if client is None:
        import requests as requests_mod

        client = requests_mod
    first = fetch_sessions_page(
        access_token, uid, limit=limit, page=1, http=client, timeout=timeout
    )
    yield from first.sessions
    last_page = first.total_pages if max_pages is None else min(first.total_pages, max_pages)
    for page in range(2, last_page + 1):
        nxt = fetch_sessions_page(
            access_token, uid, limit=limit, page=page, http=client, timeout=timeout
        )
        yield from nxt.sessions


def fetch_session_detail(
    access_token: str,
    session_id: str,
    *,
    http: Any | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> dict[str, Any]:  # pragma: no cover - network round-trip, verified live (issue #353)
    """Fetch the per-session detail (metadata; traces live on the services API)."""
    client = http
    if client is None:
        import requests as requests_mod

        client = requests_mod
    return _vulcan_get(session_detail_url(session_id), access_token, http=client, timeout=timeout)
