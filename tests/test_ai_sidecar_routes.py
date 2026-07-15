"""HTTP route registry unit tests (issue #570).

``server._ROUTES`` is the single structure driving BOTH handler dispatch and the ``/health``
endpoint advertisement. These cover the registry's own invariants — validation, precedence,
and prefix stripping. The ``/health`` payload side (what the advertisement actually says over
the wire) lives in ``test_ai_sidecar_observability.py`` next to the other health assertions.
"""

from __future__ import annotations

from http import HTTPStatus

import pytest

from tools.ai_sidecar import server as srv
from tools.ai_sidecar.server import _Route


def test_match_route_prefers_exact_over_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """A prefix route must never shadow a more specific exact route. The old inline if-chain
    encoded that precedence by hand (``/voice/manifest.json`` was checked before the
    ``/voice/clips/`` prefix); the registry must enforce it structurally."""
    exact_route = _Route("/voice/special", srv._route_voice_echoes)
    prefix_route = _Route("/voice/", srv._route_voice_clip, prefix=True)
    exact, prefixes = srv._index_routes((exact_route, prefix_route))
    monkeypatch.setattr(srv, "_EXACT_ROUTES", exact)
    monkeypatch.setattr(srv, "_PREFIX_ROUTES", prefixes)

    assert srv._match_route("/voice/special") is exact_route
    assert srv._match_route("/voice/other") is prefix_route
    assert srv._match_route("/unrouted") is None


def test_prefix_handler_receives_stripped_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    """The router strips the matched route's own path before invoking the handler, so a
    prefix handler never restates its route string. Hardcoding ``path[len("/dash/fonts/"):]``
    inside the handler would duplicate registry state and silently mis-slice if the
    registry path changed — the very drift #570 removes (self-hosted reviewer, MEDIUM)."""
    seen: list[str] = []

    def _spy(connection: object, request: object, tail: str) -> object:
        seen.append(tail)
        return srv._http_response(connection, HTTPStatus.OK, "ok", "text/plain")

    prefix_route = _Route("/dash/fonts/", _spy, prefix=True)
    exact_route = _Route("/metrics", _spy)
    exact, prefixes = srv._index_routes((exact_route, prefix_route))
    monkeypatch.setattr(srv, "_EXACT_ROUTES", exact)
    monkeypatch.setattr(srv, "_PREFIX_ROUTES", prefixes)

    handler = srv.make_process_request(None)

    class _Conn:
        def respond(self, status: HTTPStatus, text: str) -> object:
            return type("R", (), {"status": status, "headers": {}, "body": text.encode()})()

    class _Req:
        def __init__(self, path: str) -> None:
            self.path = path
            self.headers: dict[str, str] = {}

    handler(_Conn(), _Req("/dash/fonts/Chakra%20Petch.ttf"))
    handler(_Conn(), _Req("/metrics"))

    # Prefix route -> its own path stripped; exact route -> nothing meaningful to pass.
    assert seen == ["Chakra%20Petch.ttf", ""]


@pytest.mark.parametrize(
    ("routes", "message"),
    [
        pytest.param(
            (_Route("/a", srv._route_health), _Route("/a", srv._route_metrics)),
            "duplicate route registration",
            id="duplicate-path",
        ),
        pytest.param(
            (_Route("/a", srv._route_health, aliases=("/b",)), _Route("/b", srv._route_metrics)),
            "duplicate route registration",
            id="alias-collides-with-path",
        ),
        pytest.param(
            (
                _Route("/a/", srv._route_health, prefix=True),
                _Route("/a/b/", srv._route_metrics, prefix=True),
            ),
            "ambiguous overlapping prefix",
            id="overlapping-prefixes",
        ),
        pytest.param(
            (_Route("/a/", srv._route_health, prefix=True, aliases=("/x",)),),
            "cannot declare aliases",
            id="alias-on-prefix-route",
        ),
    ],
)
def test_index_routes_rejects_ambiguous_registry(routes: tuple[_Route, ...], message: str) -> None:
    """The registry is indexed at import, so an ambiguous declaration is a startup error
    rather than a route that silently never fires (fail loud, per the governance base)."""
    with pytest.raises(ValueError, match=message):
        srv._index_routes(routes)
