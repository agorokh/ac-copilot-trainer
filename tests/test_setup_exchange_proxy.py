from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.request import Request

import pytest

from tools.ai_sidecar.se_proxy import (
    SetupExchangeClient,
    SetupExchangeError,
    _coerce_float,
    _normalize_setup_rows,
    _windows_casefolded_contains,
    discover_user_setups_root,
    download_and_install_setup,
    install_setup,
)


def _approved_setups_root(tmp_path: Path) -> Path:
    return tmp_path / "Documents" / "Assetto Corsa" / "setups"


class _Response:
    def __init__(self, payload: object, headers: dict[str, str] | None = None) -> None:
        self._payload = payload
        self.headers = headers or {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_search_builds_setup_exchange_query_and_normalizes_rows() -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _Response(
            {
                "setups": [
                    {
                        "id": "42",
                        "name": "fast race",
                        "userName": "driver",
                        "downloadCount": "7",
                        "rating": "4.5",
                    }
                ],
                "total": 1,
            }
        )

    client = SetupExchangeClient("https://se.example.test", urlopen=fake_urlopen)
    result = client.search(
        car_id="ks_porsche_911_gt3_r_2016",
        track_id="magione",
        search="race",
        order_by="rating",
        limit=5,
    )

    assert result["ok"] is True
    assert result["total"] == 1
    assert result["setups"][0] == {
        "setup_id": 42,
        "name": "fast race",
        "author": "driver",
        "car_id": "",
        "track_id": "",
        "downloads": 7,
        "rating": 4.5,
        "created_at": "",
    }
    assert seen["timeout"] == pytest.approx(8.0)
    assert "carID=ks_porsche_911_gt3_r_2016" in seen["url"]
    assert "trackID=magione" in seen["url"]
    assert "orderBy=rating" in seen["url"]


def test_normalize_setup_rows_preserves_zero_downloads_and_rating() -> None:
    rows = _normalize_setup_rows(
        {
            "setups": [
                {
                    "id": 9,
                    "name": "zero stats",
                    "downloads": 0,
                    "rating": 0.0,
                }
            ]
        }
    )

    assert rows == [
        {
            "setup_id": 9,
            "name": "zero stats",
            "author": "",
            "car_id": "",
            "track_id": "",
            "downloads": 0,
            "rating": 0.0,
            "created_at": "",
        }
    ]


def test_default_public_endpoint_requires_authenticated_proxy() -> None:
    with pytest.raises(SetupExchangeError, match="requires CSP session auth"):
        SetupExchangeClient()


def test_search_rejects_oversized_json_response() -> None:
    class LargeResponse:
        headers: dict[str, str] = {}

        def __enter__(self) -> LargeResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return b"{" + (b" " * size)

    def fake_urlopen(_request: Request, *, timeout: float) -> LargeResponse:
        assert timeout == pytest.approx(8.0)
        return LargeResponse()

    client = SetupExchangeClient("https://se.example.test", urlopen=fake_urlopen)

    with pytest.raises(SetupExchangeError, match="too large"):
        client.search(limit=1)


def test_install_setup_rejects_path_traversal_segment(tmp_path: Path) -> None:
    with pytest.raises(SetupExchangeError, match="car_id"):
        install_setup(
            user_setups_root=_approved_setups_root(tmp_path),
            car_id="..",
            setup_id=9,
            setup_name="bad",
            setup_data="[HEADER]\nVERSION=1",
        )


def test_install_setup_never_overwrites_existing_user_file(tmp_path: Path) -> None:
    root = _approved_setups_root(tmp_path)
    existing = root / "ks_porsche_911_gt3_r_2016" / "magione" / "Fast.ini"
    existing.parent.mkdir(parents=True)
    existing.write_text("manual work\n", encoding="utf-8")

    out = install_setup(
        user_setups_root=root,
        car_id="ks_porsche_911_gt3_r_2016",
        track_id="magione",
        setup_id=42,
        setup_name="Fast.ini",
        setup_data="[HEADER]\nVERSION=1",
    )

    assert existing.read_text(encoding="utf-8") == "manual work\n"
    assert Path(out["path"]).name == "Fast-2.ini"
    assert Path(out["path"]).read_text(encoding="utf-8") == "[HEADER]\nVERSION=1\n"


def test_download_and_install_setup_uses_download_payload_name(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    root = _approved_setups_root(tmp_path)

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _Response({"name": "Quali baseline", "data": "[TYRES]\nPRESSURE=24"})

    client = SetupExchangeClient("https://se.example.test", urlopen=fake_urlopen)
    out = download_and_install_setup(
        client=client,
        user_setups_root=root,
        setup_id=77,
        car_id="ks_porsche_911_gt3_r_2016",
        track_id="magione",
    )

    assert out["ok"] is True
    assert out["setup_id"] == 77
    assert Path(out["path"]).name == "Quali baseline.ini"
    assert Path(out["path"]).read_text(encoding="utf-8") == "[TYRES]\nPRESSURE=24\n"
    assert seen["url"] == "https://se.example.test/setups/77"


def test_discover_user_setups_root_prefers_explicit_env(tmp_path: Path) -> None:
    root = _approved_setups_root(tmp_path)

    assert discover_user_setups_root({"AC_COPILOT_USER_SETUPS_DIR": str(root)}) == root.resolve(
        strict=False
    )


def test_discover_user_setups_root_rejects_non_ac_override(tmp_path: Path) -> None:
    with pytest.raises(SetupExchangeError, match="Assetto Corsa"):
        discover_user_setups_root({"AC_COPILOT_USER_SETUPS_DIR": str(tmp_path / "setups")})


def test_discover_user_setups_root_allows_fresh_install_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    documents = home / "Documents"
    documents.mkdir(parents=True)
    expected = documents / "Assetto Corsa" / "setups"
    monkeypatch.setenv("USERPROFILE", str(home))

    discovered = discover_user_setups_root({})

    assert discovered == expected.resolve(strict=False)
    assert not expected.exists()


def test_discover_user_setups_root_prefers_local_documents_over_onedrive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    local_documents = home / "Documents"
    onedrive_documents = home / "OneDrive" / "Documents"
    local_documents.mkdir(parents=True)
    onedrive_documents.mkdir(parents=True)
    expected = local_documents / "Assetto Corsa" / "setups"
    monkeypatch.setenv("USERPROFILE", str(home))

    discovered = discover_user_setups_root({})

    assert discovered == expected.resolve(strict=False)


def test_user_setups_root_from_config_ignores_invalid_path() -> None:
    from tools.ai_sidecar.server import _user_setups_root_from_config

    assert _user_setups_root_from_config(None) is None
    assert _user_setups_root_from_config("/tmp/not-ac-setups") is None


def test_install_setup_rejects_unapproved_root(tmp_path: Path) -> None:
    with pytest.raises(SetupExchangeError, match="Assetto Corsa"):
        install_setup(
            user_setups_root=tmp_path / "custom-setups",
            car_id="ks_porsche_911_gt3_r_2016",
            setup_id=42,
            setup_name="Fast.ini",
            setup_data="[HEADER]\nVERSION=1",
        )


def test_install_setup_converts_filesystem_errors(tmp_path: Path) -> None:
    root = _approved_setups_root(tmp_path)
    root.parent.mkdir(parents=True)
    root.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(SetupExchangeError, match="failed to install setup"):
        install_setup(
            user_setups_root=root,
            car_id="ks_porsche_911_gt3_r_2016",
            track_id="magione",
            setup_id=42,
            setup_name="Fast race",
            setup_data="[HEADER]\nVERSION=1",
        )


def test_windows_casefolded_containment_accepts_drive_letter_case_variants() -> None:
    root = PureWindowsPath("C:/Users/Driver/Documents/Assetto Corsa/setups")
    target = PureWindowsPath("c:/Users/Driver/Documents/Assetto Corsa/setups/car/file.ini")

    assert _windows_casefolded_contains(root, target) is True


def test_windows_casefolded_containment_rejects_sibling_prefix() -> None:
    root = PureWindowsPath("C:/Users/Driver/Documents/Assetto Corsa/setups")
    target = PureWindowsPath("c:/Users/Driver/Documents/Assetto Corsa/setups_backup/file.ini")

    assert _windows_casefolded_contains(root, target) is False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "-inf", "NaN"])
def test_coerce_float_rejects_non_finite_values(value: object) -> None:
    assert _coerce_float(value) is None
