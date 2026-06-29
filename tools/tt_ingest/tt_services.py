"""Track Titan **services** API client — the turn-by-turn coaching plane
(issue #353, milestone M-TT1).

The services API (``https://services.tracktitan.io``) serves the rich post-race
analysis the operator wants: per-corner reference laps, the personalised /
community reference, and natural-language coaching **advice** per corner. The
desktop app's renderer was captured live (CDP) to pin both the auth model and the
exact paths — see ``track-titan-services-auth-2026-06-29`` in the vault.

Auth model (VERIFIED LIVE, issue #353): every services route authenticates with
the **raw Cognito access token** in the ``Authorization`` header (NO ``Bearer``
prefix) — the *same* access token vulcan uses (:func:`tools.tt_ingest.tt_auth.mint_tokens`
already returns it). The M-TT1 research checkpoint's "needs SigV4 / Identity-Pool
IAM" was a red herring: it had probed *old* cached path shapes (``data-analysis/…``)
with the **id** token, which 403s. The current API is RESTful ``/api/v2/…`` and the
access token is accepted (200). The Cognito Identity-Pool ``GetCredentialsForIdentity``
calls the app also makes are for analytics, not these data routes.

Two response shapes:
  * **Enveloped** (``/api/v2/*`` and ``/advice/*``): ``{success, status, data, message}``.
  * **Bare** (``/dynamic-reference-laps/*``): the object itself (``{session, lap, …}``).
:func:`unwrap_envelope` normalises both.

URL builders + parsers are pure and unit-tested against sanitized fixtures; the
HTTP round-trips are isolated and ``# pragma: no cover`` (proven live, issue #353).

SECURITY (issue #353 scope/ethics): personal own-account coaching data. The access
token is a personal secret — this module never logs it, never embeds it in error
messages, and callers must keep it in env / the gitignored lake only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from tools.tt_ingest.tt_auth import DEFAULT_REQUEST_TIMEOUT_S

SERVICES_BASE = "https://services.tracktitan.io"

#: The reference-lap identifier the app uses for the personalised theoretical best.
THEORETICAL_BEST_REF = "theoreticalBestRef"
#: Default number of segments (corners) the renderer requests per reference lap.
DEFAULT_SEGMENT_COUNT = 7


class TTServicesError(RuntimeError):
    """A services response did not match the documented shape, or an HTTP error.

    Never carries token material — only the actionable cause + sanitized URL path.
    """


# ----------------------------------------------------------------------------------
# Pure URL builders. Every path segment is percent-encoded so an id containing a
# ``#``/``/`` can never break out of its segment (the vulcan id form is
# ``{uid}#{sessionKey}``; services takes uid and sessionKey as SEPARATE segments).
# ----------------------------------------------------------------------------------


def _seg(value: Any) -> str:
    """Percent-encode one path segment (encode everything, incl. ``/`` and ``#``)."""
    return quote(str(value), safe="")


def services_sessions_url(
    uid: str,
    *,
    page: int = 1,
    limit: int = 5,
    hide_limited: bool = False,
    base: str = SERVICES_BASE,
) -> str:
    """The services view of a user's sessions list (richer than vulcan's)."""
    hl = "true" if hide_limited else "false"
    return (
        f"{base}/api/v2/users/{_seg(uid)}/sessions"
        f"?page={int(page)}&hideLimited={hl}&limit={int(limit)}"
    )


def last_session_url(uid: str, *, base: str = SERVICES_BASE) -> str:
    """The user's most recent session + its reference lap."""
    return f"{base}/api/v2/sessions/{_seg(uid)}/last-session"


def lap_reference_url(uid: str, session_key: str, lap: Any, *, base: str = SERVICES_BASE) -> str:
    """The reference (``dynamicComparisonLap``) for one lap of a session."""
    return f"{base}/api/v2/sessions/{_seg(uid)}/{_seg(session_key)}/laps/{_seg(lap)}/reference"


def dynamic_reference_lap_url(
    uid: str,
    session_key: str,
    lap: Any,
    *,
    segment_count: int = DEFAULT_SEGMENT_COUNT,
    base: str = SERVICES_BASE,
) -> str:
    """The dynamic reference lap (per-corner segments) for one lap. **Bare** response."""
    return (
        f"{base}/dynamic-reference-laps/sessions/{_seg(uid)}/{_seg(session_key)}"
        f"/laps/{_seg(lap)}?segmentCount={int(segment_count)}"
    )


def reference_lap_url(
    uid: str,
    session_key: str,
    ref_uid: str,
    ref_session_key: str,
    ref_lap: Any,
    *,
    base: str = SERVICES_BASE,
) -> str:
    """A specific reference lap (another user/session, or the user's theoretical best)."""
    return (
        f"{base}/api/v2/sessions/{_seg(uid)}/{_seg(session_key)}"
        f"/reference/{_seg(ref_uid)}/{_seg(ref_session_key)}/laps/{_seg(ref_lap)}"
    )


def advice_segment_url(
    uid: str,
    session_key: str,
    lap: Any,
    ref_uid: str,
    ref_session_key: str,
    segment: Any,
    *,
    ref_lap: Any = THEORETICAL_BEST_REF,
    base: str = SERVICES_BASE,
) -> str:
    """Natural-language coaching advice for one corner (segment) vs a reference lap."""
    return (
        f"{base}/advice/sessions/{_seg(uid)}/{_seg(session_key)}/laps/{_seg(lap)}"
        f"/reference/{_seg(ref_uid)}/{_seg(ref_session_key)}/laps/{_seg(ref_lap)}"
        f"/segments/{_seg(segment)}"
    )


def analysis_progress_url(
    uid: str,
    *,
    game_id: str,
    track_id: str,
    car_id: str,
    base: str = SERVICES_BASE,
) -> str:
    """Per car/track analysis-progress summary."""
    return (
        f"{base}/api/v2/users/{_seg(uid)}/analysis/progress/"
        f"?gameId={_seg(game_id)}&trackId={_seg(track_id)}&carId={_seg(car_id)}"
    )


# ----------------------------------------------------------------------------------
# Pure parsers / envelope handling.
# ----------------------------------------------------------------------------------


def is_enveloped(payload: Mapping[str, Any]) -> bool:
    """True for the ``{success, status, data, message}`` envelope (vs a bare object)."""
    return "success" in payload and "data" in payload


def unwrap_envelope(payload: Mapping[str, Any]) -> Any:
    """Return ``data`` for an enveloped response, or the payload itself when bare.

    Raises :class:`TTServicesError` if the envelope reports failure, so a
    ``{"success": false}`` body never silently parses as empty data.
    """
    if not isinstance(payload, Mapping):
        raise TTServicesError("services response was not a JSON object")
    if is_enveloped(payload):
        if not payload.get("success", False):
            status = payload.get("status")
            raise TTServicesError(f"services response reported failure (status={status})")
        return payload.get("data")
    return payload


@dataclass(frozen=True)
class CoachingStory:
    """One natural-language coaching insight for a corner (from ``/advice``)."""

    diagnosis: str
    consequence: str
    diagnosis_key: str
    consequence_key: str
    time_loss: float | None
    phase_mistake: str | None
    highlight: tuple[float, float] | None

    @property
    def is_actionable(self) -> bool:
        """True when there is a real, non-trivial time loss to coach on."""
        return self.time_loss is not None and self.time_loss > 0.0


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _highlight(raw: Any) -> tuple[float, float] | None:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        a, b = _as_float(raw[0]), _as_float(raw[1])
        if a is not None and b is not None:
            return (a, b)
    return None


def parse_advice(payload: Mapping[str, Any]) -> list[CoachingStory]:
    """Extract the coaching stories from an ``/advice`` response."""
    data = unwrap_envelope(payload)
    if not isinstance(data, Mapping):
        raise TTServicesError("advice response missing 'data' object")
    stories = data.get("stories")
    if not isinstance(stories, list):
        return []
    out: list[CoachingStory] = []
    for s in stories:
        if not isinstance(s, Mapping):
            continue
        out.append(
            CoachingStory(
                diagnosis=str(s.get("diagnosis", "")),
                consequence=str(s.get("consequence", "")),
                diagnosis_key=str(s.get("diagnosisKey", "")),
                consequence_key=str(s.get("consequenceKey", "")),
                time_loss=_as_float(s.get("timeLoss")),
                phase_mistake=s.get("phase_mistake")
                if isinstance(s.get("phase_mistake"), str)
                else None,
                highlight=_highlight(s.get("highlight")),
            )
        )
    return out


def parse_reference_lap(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the reference lap object from either response shape.

    ``/api/v2/.../laps/{lap}/reference`` → enveloped, the lap IS ``data``.
    ``/dynamic-reference-laps/...`` → bare ``{session, lap: {...}, ...}`` — the lap
    is the nested ``lap`` object.
    """
    data = unwrap_envelope(payload)
    if isinstance(data, Mapping) and isinstance(data.get("lap"), Mapping):
        # Bare dynamic-reference-laps shape.
        return dict(data["lap"])
    if isinstance(data, Mapping):
        return dict(data)
    raise TTServicesError("reference-lap response missing lap object")


def reference_identity(reference_lap: Mapping[str, Any]) -> tuple[str, str]:
    """Pull ``(ref_uid, ref_session_key)`` from a parsed reference lap.

    Needed to build the advice URL, which references the lap by uid + session key.
    """
    uid = reference_lap.get("user_id")
    session_key = reference_lap.get("session_key")
    if not isinstance(uid, str) or not uid or not isinstance(session_key, str) or not session_key:
        raise TTServicesError("reference lap has no usable user_id / session_key")
    return uid, session_key


def reference_lap_segments(reference_lap: Mapping[str, Any]) -> list[tuple[int, float]]:
    """Return ``[(segment_number, segment_time_ms), …]`` sorted by segment number."""
    segs = reference_lap.get("segments")
    if not isinstance(segs, list):
        return []
    out: list[tuple[int, float]] = []
    for s in segs:
        if not isinstance(s, Mapping):
            continue
        num = s.get("segment_number")
        t = _as_float(s.get("segment_time"))
        if isinstance(num, int) and t is not None:
            out.append((num, t))
    return sorted(out, key=lambda x: x[0])


def parse_last_session(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``{"session": {...}, "reference_lap": {...} | None}`` from last-session."""
    data = unwrap_envelope(payload)
    if not isinstance(data, Mapping):
        raise TTServicesError("last-session response missing 'data' object")
    session = data.get("session")
    if not isinstance(session, Mapping):
        raise TTServicesError("last-session response missing 'data.session'")
    ref = data.get("referenceLap")
    return {
        "session": dict(session),
        "reference_lap": dict(ref) if isinstance(ref, Mapping) else None,
    }


# ----------------------------------------------------------------------------------
# Network round-trips — thin, isolated, ``# pragma: no cover`` (verified live, #353).
# ----------------------------------------------------------------------------------


def _auth_headers(access_token: str) -> dict[str, str]:
    # services expects the RAW access token (no 'Bearer ' prefix) — verified live #353.
    return {"Authorization": access_token, "Accept": "application/json"}


def _services_get(
    url: str, access_token: str, *, http: Any, timeout: float
) -> Any:  # pragma: no cover - network round-trip, verified live (issue #353)
    response = http.get(url, headers=_auth_headers(access_token), timeout=timeout)
    status = getattr(response, "status_code", 200)
    if status >= 400:
        # Surface the path (not the query, which is safe here) but never the token.
        raise TTServicesError(f"services GET failed with HTTP {status}: {url.split('?')[0]}")
    body = response.json()
    if not isinstance(body, (Mapping, list)):
        raise TTServicesError("services response was not a JSON object/array")
    return body


def _client(http: Any | None) -> Any:  # pragma: no cover - trivial import shim
    if http is not None:
        return http
    import requests as requests_mod

    return requests_mod


def fetch_last_session(
    access_token: str,
    uid: str,
    *,
    http: Any | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> dict[str, Any]:  # pragma: no cover - network round-trip, verified live (#353)
    """Fetch + parse the user's last session (session + reference lap)."""
    body = _services_get(last_session_url(uid), access_token, http=_client(http), timeout=timeout)
    return parse_last_session(body)


def fetch_dynamic_reference_lap(
    access_token: str,
    uid: str,
    session_key: str,
    lap: Any,
    *,
    segment_count: int = DEFAULT_SEGMENT_COUNT,
    http: Any | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> dict[str, Any]:  # pragma: no cover - network round-trip, verified live (#353)
    """Fetch the raw (bare) dynamic-reference-lap payload for a lap."""
    url = dynamic_reference_lap_url(uid, session_key, lap, segment_count=segment_count)
    body = _services_get(url, access_token, http=_client(http), timeout=timeout)
    if not isinstance(body, Mapping):
        raise TTServicesError("dynamic-reference-lap response was not an object")
    return dict(body)


def fetch_advice_segment(
    access_token: str,
    uid: str,
    session_key: str,
    lap: Any,
    ref_uid: str,
    ref_session_key: str,
    segment: Any,
    *,
    ref_lap: Any = THEORETICAL_BEST_REF,
    http: Any | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> list[CoachingStory]:  # pragma: no cover - network round-trip, verified live (#353)
    """Fetch + parse coaching advice for one corner (segment)."""
    url = advice_segment_url(
        uid, session_key, lap, ref_uid, ref_session_key, segment, ref_lap=ref_lap
    )
    body = _services_get(url, access_token, http=_client(http), timeout=timeout)
    if not isinstance(body, Mapping):
        raise TTServicesError("advice response was not an object")
    return parse_advice(body)


def fetch_session_coaching(
    access_token: str,
    uid: str,
    session_key: str,
    lap: Any,
    *,
    segment_count: int = DEFAULT_SEGMENT_COUNT,
    ref_lap: Any = THEORETICAL_BEST_REF,
    http: Any | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_S,
) -> dict[str, Any]:  # pragma: no cover - network round-trip, verified live (#353)
    """Pull the full per-corner coaching bundle for one lap.

    Returns ``{"reference_lap": {...}, "segments": [{segment, stories: [...]}]}``.
    The reference lap's identity (uid + session key) drives the advice requests; the
    advice itself compares the lap against the operator's ``theoreticalBestRef`` by
    default (matching the renderer's own behaviour).
    """
    client = _client(http)
    raw_ref = _services_get(
        dynamic_reference_lap_url(uid, session_key, lap, segment_count=segment_count),
        access_token,
        http=client,
        timeout=timeout,
    )
    reference_lap = parse_reference_lap(raw_ref)
    ref_uid, ref_sk = reference_identity(reference_lap)
    segments: list[dict[str, Any]] = []
    for seg_num, _ in reference_lap_segments(reference_lap) or [
        (i, 0.0) for i in range(1, segment_count + 1)
    ]:
        stories = fetch_advice_segment(
            access_token,
            uid,
            session_key,
            lap,
            uid,  # advice references the operator's OWN session for theoreticalBestRef
            session_key,
            seg_num,
            ref_lap=ref_lap,
            http=client,
            timeout=timeout,
        )
        segments.append({"segment": seg_num, "stories": [s.__dict__ for s in stories]})
    return {"reference_lap": reference_lap, "reference_id": [ref_uid, ref_sk], "segments": segments}
