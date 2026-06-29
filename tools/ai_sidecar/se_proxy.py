"""Setup Exchange proxy and safe installer for the Game Point sidecar (#363).

The original CSP Setup Exchange app talks to ``se.acstuff.club`` from Lua and
then writes downloaded ``.ini`` data into Assetto Corsa's user setups folder.
The rig screen cannot reach that endpoint directly, so the Python sidecar owns
the HTTP call and the filesystem write.
"""

from __future__ import annotations

import json
import math
import ntpath
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

DEFAULT_SETUP_EXCHANGE_ENDPOINT = "http://se.acstuff.club"
ENV_SETUP_EXCHANGE_ENDPOINT = "AC_COPILOT_SE_ENDPOINT"
ENV_USER_SETUPS_DIR = "AC_COPILOT_USER_SETUPS_DIR"
MAX_SEARCH_TEXT = 80
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_SETUP_BYTES = 512 * 1024
SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
AC_SETUPS_SUFFIX = ("assetto corsa", "setups")


class SetupExchangeError(RuntimeError):
    """User-facing Setup Exchange failure."""


def _normalize_endpoint(endpoint: str | None) -> str:
    raw = (endpoint or DEFAULT_SETUP_EXCHANGE_ENDPOINT).strip().rstrip("/")
    if not raw:
        raw = DEFAULT_SETUP_EXCHANGE_ENDPOINT
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SetupExchangeError("Setup Exchange endpoint must be an http(s) URL")
    return raw


def _safe_segment(value: str, field: str) -> str:
    if value in {".", ".."} or not SAFE_SEGMENT_RE.fullmatch(value):
        raise SetupExchangeError(
            f"{field} contains unsupported characters; expected Assetto Corsa id text"
        )
    return value


def _safe_search_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    out = value.strip()
    if len(out) > MAX_SEARCH_TEXT:
        raise SetupExchangeError(f"{field} is too long")
    return out or None


def _safe_int(
    value: int | None,
    field: str,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise SetupExchangeError(f"{field} must be an integer")
    if value < min_value or value > max_value:
        raise SetupExchangeError(f"{field} must be between {min_value} and {max_value}")
    return value


def _read_response_json(response: Any) -> Any:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if isinstance(raw, str):
        if len(raw.encode("utf-8", errors="replace")) > MAX_RESPONSE_BYTES:
            raise SetupExchangeError("Setup Exchange response is too large")
        text = raw
    else:
        raw_bytes = bytes(raw)
        if len(raw_bytes) > MAX_RESPONSE_BYTES:
            raise SetupExchangeError("Setup Exchange response is too large")
        text = raw_bytes.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SetupExchangeError(f"Setup Exchange returned invalid JSON: {e.msg}") from e


def _response_headers(response: Any) -> Mapping[str, str]:
    headers = getattr(response, "headers", {}) or {}
    if isinstance(headers, Mapping):
        return headers
    return {}


class SetupExchangeClient:
    """Small stdlib HTTP client for ``se.acstuff.club``."""

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        timeout_s: float = 8.0,
        urlopen: Callable[..., Any] | None = None,
    ) -> None:
        self.endpoint = _normalize_endpoint(endpoint or os.environ.get(ENV_SETUP_EXCHANGE_ENDPOINT))
        if self.endpoint == DEFAULT_SETUP_EXCHANGE_ENDPOINT:
            raise SetupExchangeError(
                "default Setup Exchange endpoint requires CSP session auth; "
                f"set {ENV_SETUP_EXCHANGE_ENDPOINT} to an authenticated proxy/test endpoint"
            )
        self.timeout_s = timeout_s
        self._urlopen = urlopen or urllib.request.urlopen

    def _json_request(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = "GET",
    ) -> tuple[Any, Mapping[str, str]]:
        query = urllib.parse.urlencode(
            {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        )
        url = f"{self.endpoint}{path}"
        if query:
            url = f"{url}?{query}"
        request = urllib.request.Request(
            url,
            method=method,
            headers={"Accept": "application/json", "User-Agent": "ac-copilot-trainer/1"},
        )
        try:
            with self._urlopen(request, timeout=self.timeout_s) as response:
                return _read_response_json(response), _response_headers(response)
        except urllib.error.HTTPError as e:
            raise SetupExchangeError(f"Setup Exchange HTTP {e.code}") from e
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise SetupExchangeError(f"Setup Exchange is unreachable: {reason}") from e
        except TimeoutError as e:
            raise SetupExchangeError("Setup Exchange request timed out") from e
        except OSError as e:
            raise SetupExchangeError(f"Setup Exchange request failed: {e}") from e

    def search(
        self,
        *,
        car_id: str | None = None,
        track_id: str | None = None,
        search: str | None = None,
        order_by: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        if car_id:
            car_id = _safe_segment(car_id, "car_id")
        if track_id:
            track_id = _safe_segment(track_id, "track_id")
        search = _safe_search_text(search, "search")
        order_by = _safe_search_text(order_by, "order_by")
        offset_value = _safe_int(offset, "offset", default=0, min_value=0, max_value=10_000)
        limit_value = _safe_int(limit, "limit", default=20, min_value=1, max_value=40)
        raw, headers = self._json_request(
            "/setups",
            params={
                "carID": car_id,
                "trackID": track_id,
                "search": search,
                "orderBy": order_by,
                "offset": offset_value,
                "limit": limit_value,
            },
        )
        setups = _normalize_setup_rows(raw)
        total = _total_from_payload(raw, headers, len(setups))
        return {
            "ok": True,
            "endpoint": self.endpoint,
            "car_id": car_id,
            "track_id": track_id,
            "offset": offset_value,
            "limit": limit_value,
            "count": len(setups),
            "total": total,
            "setups": setups,
        }

    def download_setup(self, setup_id: int) -> dict[str, Any]:
        if isinstance(setup_id, bool) or not isinstance(setup_id, int) or setup_id <= 0:
            raise SetupExchangeError("setup_id must be a positive integer")
        raw, _headers = self._json_request(f"/setups/{setup_id}")
        if isinstance(raw, dict):
            data = raw.get("data")
            name = raw.get("name") or raw.get("setupName") or raw.get("title")
        elif isinstance(raw, str):
            data = raw
            name = None
        else:
            data = None
            name = None
        if not isinstance(data, str) or not data.strip():
            raise SetupExchangeError("download did not include setup data")
        encoded = data.encode("utf-8")
        if len(encoded) > MAX_SETUP_BYTES:
            raise SetupExchangeError("downloaded setup is too large")
        return {"setup_id": setup_id, "name": name, "data": data}


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _normalize_setup_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("setups")
            or payload.get("items")
            or payload.get("results")
            or payload.get("data")
            or []
        )
    else:
        rows = []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        setup_id = row.get("id") or row.get("setupID") or row.get("setup_id")
        if isinstance(setup_id, bool):
            setup_id = None
        if isinstance(setup_id, str) and setup_id.isdigit():
            setup_id = int(setup_id)
        if not isinstance(setup_id, int) or setup_id <= 0:
            continue
        out.append(
            {
                "setup_id": setup_id,
                "name": str(row.get("name") or row.get("setupName") or f"setup-{setup_id}"),
                "author": str(row.get("userName") or row.get("author") or row.get("user") or ""),
                "car_id": str(row.get("carID") or row.get("car_id") or ""),
                "track_id": str(row.get("trackID") or row.get("track_id") or ""),
                "downloads": _coerce_int(
                    _row_value(row, "downloads", "downloadCount", "download_count")
                ),
                "rating": _coerce_float(_row_value(row, "rating", "score")),
                "created_at": str(row.get("createdAt") or row.get("created_at") or ""),
            }
        )
    return out


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    parsed: float
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return parsed if math.isfinite(parsed) else None


def _total_from_payload(payload: Any, headers: Mapping[str, str], fallback: int) -> int:
    if isinstance(payload, dict):
        for key in ("total", "totalCount", "count"):
            value = _coerce_int(payload.get(key))
            if value is not None:
                return value
    for key in ("x-total-count", "X-Total-Count"):
        value = _coerce_int(headers.get(key))
        if value is not None:
            return value
    return fallback


def discover_user_setups_root(env: Mapping[str, str] | None = None) -> Path | None:
    """Find Assetto Corsa's per-user setups directory without creating guesses."""

    env_map = env or os.environ
    explicit = (env_map.get(ENV_USER_SETUPS_DIR) or "").strip()
    if explicit:
        return validate_user_setups_root(Path(os.path.expandvars(explicit)).expanduser())
    home_text = env_map.get("USERPROFILE") or str(Path.home())
    home = Path(home_text).expanduser()
    candidates = [
        home / "OneDrive" / "Documents" / "Assetto Corsa" / "setups",
        home / "Documents" / "Assetto Corsa" / "setups",
        Path.home() / "OneDrive" / "Documents" / "Assetto Corsa" / "setups",
        Path.home() / "Documents" / "Assetto Corsa" / "setups",
    ]
    for candidate in candidates:
        if candidate.exists():
            return validate_user_setups_root(candidate)
    local_documents = home / "Documents"
    onedrive_documents = home / "OneDrive" / "Documents"
    local_setup = local_documents / "Assetto Corsa" / "setups"
    onedrive_setup = onedrive_documents / "Assetto Corsa" / "setups"
    if local_documents.exists():
        try:
            return validate_user_setups_root(local_setup)
        except SetupExchangeError:
            pass
    if onedrive_documents.exists() and not local_documents.exists():
        try:
            return validate_user_setups_root(onedrive_setup)
        except SetupExchangeError:
            pass
    return None


def validate_user_setups_root(root: str | Path) -> Path:
    """Accept only Assetto Corsa's per-user ``.../Assetto Corsa/setups`` root."""

    resolved = Path(os.path.expandvars(str(root))).expanduser().resolve(strict=False)
    parts = tuple(part.lower() for part in resolved.parts)
    if len(parts) < 2 or parts[-2:] != AC_SETUPS_SUFFIX:
        raise SetupExchangeError(
            f"{ENV_USER_SETUPS_DIR} must point to your Assetto Corsa 'setups' folder"
        )
    return resolved


def sanitize_setup_filename(name: str | None, setup_id: int) -> str:
    stem = (name or f"setup-{setup_id}").strip()
    stem = re.sub(r"[^\w .-]+", "_", stem, flags=re.ASCII).strip(" ._")
    if not stem:
        stem = f"setup-{setup_id}"
    stem = stem[:80].strip(" ._") or f"setup-{setup_id}"
    if stem.lower().endswith(".ini"):
        return stem
    return f"{stem}.ini"


def _resolve_inside(root: Path, *parts: str) -> Path:
    resolved_root = root.expanduser().resolve(strict=False)
    target = resolved_root.joinpath(*parts).resolve(strict=False)
    _ensure_inside(resolved_root, target)
    return target


def _ensure_inside(resolved_root: Path, target: Path) -> None:
    try:
        target.relative_to(resolved_root)
        return
    except ValueError as e:
        if _windows_casefolded_contains(resolved_root, target):
            return
        raise SetupExchangeError("resolved setup path escaped the user setups directory") from e


def _windows_path_key(path: Path) -> str | None:
    text = str(path)
    if os.name != "nt" and not re.match(r"^[A-Za-z]:[\\/]", text):
        return None
    return ntpath.normcase(ntpath.normpath(text)).rstrip("\\/")


def _windows_casefolded_contains(resolved_root: Path, target: Path) -> bool:
    root_key = _windows_path_key(resolved_root)
    target_key = _windows_path_key(target)
    if not root_key or not target_key:
        return False
    return target_key == root_key or target_key.startswith(f"{root_key}\\")


def install_setup(
    *,
    user_setups_root: Path,
    car_id: str,
    setup_id: int,
    setup_data: str,
    setup_name: str | None = None,
    track_id: str | None = None,
) -> dict[str, Any]:
    """Write a downloaded setup without overwriting existing user files."""

    safe_car = _safe_segment(car_id, "car_id")
    safe_track = _safe_segment(track_id, "track_id") if track_id else None
    if not isinstance(setup_data, str) or not setup_data.strip():
        raise SetupExchangeError("setup data is empty")
    if len(setup_data.encode("utf-8")) > MAX_SETUP_BYTES:
        raise SetupExchangeError("setup data is too large")
    filename = sanitize_setup_filename(setup_name, setup_id)
    resolved_root = validate_user_setups_root(user_setups_root)
    directory = (
        _resolve_inside(resolved_root, safe_car, safe_track)
        if safe_track
        else _resolve_inside(resolved_root, safe_car)
    )
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SetupExchangeError(f"failed to install setup: {e}") from e
    base = directory / filename
    stem = base.stem
    suffix = base.suffix or ".ini"
    for idx in range(1, 100):
        candidate = base if idx == 1 else directory / f"{stem}-{idx}{suffix}"
        candidate = candidate.resolve(strict=False)
        _ensure_inside(resolved_root, candidate)
        try:
            with candidate.open("x", encoding="utf-8", newline="\n") as fh:
                fh.write(setup_data)
                if not setup_data.endswith("\n"):
                    fh.write("\n")
        except FileExistsError:
            continue
        except OSError as e:
            raise SetupExchangeError(f"failed to install setup: {e}") from e
        return {
            "path": str(candidate),
            "name": candidate.name,
            "car_id": safe_car,
            "track_id": safe_track,
            "setup_id": setup_id,
        }
    raise SetupExchangeError("too many setup files with the same name already exist")


def download_and_install_setup(
    *,
    client: SetupExchangeClient,
    user_setups_root: Path | None,
    setup_id: int,
    car_id: str,
    track_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    root = user_setups_root or discover_user_setups_root()
    if root is None:
        raise SetupExchangeError(f"set {ENV_USER_SETUPS_DIR} to your Assetto Corsa setups folder")
    root = validate_user_setups_root(root)
    downloaded = client.download_setup(setup_id)
    install_name = name or downloaded.get("name")
    installed = install_setup(
        user_setups_root=root,
        car_id=car_id,
        track_id=track_id,
        setup_id=setup_id,
        setup_name=install_name if isinstance(install_name, str) else None,
        setup_data=str(downloaded["data"]),
    )
    return {"ok": True, "root": str(root), **installed}
