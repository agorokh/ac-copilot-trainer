"""Tests for the Game Point app icon and native dark window chrome (issue #881).

The icon is generated from code, so the committed ``.ico`` is checked against a
fresh build (drift gate) and its structure is parsed independently of the
writer. DWM / shell32 / Tk are injected or faked — no test touches a real
window or the host's taskbar identity.
"""

from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

from tools.rig_launcher import chrome, icon, theme
from tools.rig_launcher.supervisor import build_pyinstaller_args

# -- the .ico -----------------------------------------------------------------


def _ico_entries(data: bytes) -> list[tuple[int, bytes]]:
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1)
    entries = []
    for index in range(count):
        width, height, _colors, _res, planes, bpp, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        assert width == height
        assert (planes, bpp) == (1, 32)
        entries.append((width or 256, data[offset : offset + length]))
    return entries


def _pixel(size: int, x: int, y: int) -> tuple[int, int, int, int]:
    rgba = icon.render_rgba(size)
    start = (y * size + x) * 4
    return tuple(rgba[start : start + 4])  # type: ignore[return-value]


def _rgba(hex_color: str) -> tuple[int, int, int, int]:
    value = hex_color.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


def test_committed_ico_matches_generator() -> None:
    assert icon.ICON_PATH.is_file(), "run: python -m tools.rig_launcher.icon --write"
    assert icon.ICON_PATH.read_bytes() == icon.build_ico(), (
        "assets/game_point.ico drifted from tools/rig_launcher/icon.py; "
        "rerun python -m tools.rig_launcher.icon --write"
    )


def test_ico_carries_every_shell_size_from_16_to_256() -> None:
    entries = _ico_entries(icon.ICON_PATH.read_bytes())
    sizes = [size for size, _ in entries]
    assert sizes == list(icon.ICO_SIZES)
    assert min(sizes) == 16 and max(sizes) == 256


def test_ico_payloads_are_valid_png_or_dib() -> None:
    for size, payload in _ico_entries(icon.build_ico()):
        if size >= 128:
            assert payload.startswith(b"\x89PNG\r\n\x1a\n")
            width, height, depth, color_type = struct.unpack_from(">IIBB", payload, 16)
            assert (width, height, depth, color_type) == (size, size, 8, 6)
            idat_len = struct.unpack_from(">I", payload, 33)[0]
            raw = zlib.decompress(payload[41 : 41 + idat_len])
            assert len(raw) == size * (size * 4 + 1)
        else:
            header_size, width, height, _planes, bpp = struct.unpack_from("<IiiHH", payload, 0)
            assert (header_size, width, height, bpp) == (40, size, size * 2, 32)
            mask = ((size + 31) // 32) * 4 * size
            assert len(payload) == 40 + size * size * 4 + mask


def test_dib_stores_rows_bottom_up_in_bgra() -> None:
    size = 32
    payload = dict(_ico_entries(icon.build_ico()))[size]
    # First stored row is the image's bottom row; its first pixel is a brass bracket.
    b, g, r, a = payload[40:44]
    assert (r, g, b, a) == _rgba(theme.BRASS) == _pixel(size, 0, size - 1)


@pytest.mark.parametrize("size", icon.ICO_SIZES)
def test_mark_is_framed_by_four_brass_brackets_on_carbon(size: int) -> None:
    brass, carbon = _rgba(theme.BRASS), _rgba(theme.CARBON)
    last = size - 1
    for x, y in ((0, 0), (last, 0), (0, last), (last, last)):
        assert _pixel(size, x, y) == brass
    # Between the brackets the tile edge is bare carbon: brackets, not a full border.
    assert _pixel(size, size // 2, 0) == carbon
    assert _pixel(size, 0, size // 2) == carbon


@pytest.mark.parametrize("size", icon.ICO_SIZES)
def test_mark_uses_only_house_tokens_and_is_opaque(size: int) -> None:
    rgba = icon.render_rgba(size)
    colors = {tuple(rgba[i : i + 4]) for i in range(0, len(rgba), 4)}
    assert colors == {_rgba(theme.CARBON), _rgba(theme.BRASS), _rgba(theme.CHALK)}


@pytest.mark.parametrize("size", icon.ICO_SIZES)
def test_lockup_stays_clear_of_the_brackets(size: int) -> None:
    rects = icon.mark_rects(size)
    brackets = [rect for rect, color in rects[1:9]]
    lockup = [rect for rect, _ in rects[9:]]
    assert all(color == icon._BRASS for _, color in rects[1:9])
    for x0, y0, x1, y1 in lockup:
        assert 0 <= x0 < x1 <= size and 0 <= y0 < y1 <= size
        for bx0, by0, bx1, by1 in brackets:
            assert x1 <= bx0 or bx1 <= x0 or y1 <= by0 or by1 <= y0


def test_icon_cli_reports_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stale = tmp_path / "game_point.ico"
    stale.write_bytes(b"not an icon")
    monkeypatch.setattr(icon, "ICON_PATH", stale)
    assert icon.main([]) == 1
    assert icon.main(["--write"]) == 0
    assert stale.read_bytes() == icon.build_ico()
    assert icon.main([]) == 0


# -- PyInstaller wiring ----------------------------------------------------------


def _has_option_value(args: list[str], option: str, value: str) -> bool:
    return any(a == option and b == value for a, b in zip(args, args[1:], strict=False))


def test_build_brands_exe_and_bundles_window_icon(tmp_path: Path) -> None:
    ico = tmp_path / "tools" / "rig_launcher" / "assets" / "game_point.ico"
    ico.parent.mkdir(parents=True)
    ico.write_bytes(icon.build_ico())

    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)

    assert _has_option_value(args, "--icon", str(ico))
    assert _has_option_value(args, "--add-data", f"{ico}{os.pathsep}tools/rig_launcher/assets")
    assert args[-1].endswith("__main__.py")


def test_build_without_icon_asset_still_builds(tmp_path: Path) -> None:
    args = build_pyinstaller_args(tmp_path, onefile=True, windowed=True)
    assert "--icon" not in args


def test_frozen_icon_path_matches_bundle_destination() -> None:
    # chrome resolves the icon beside the module; PyInstaller places the --add-data
    # copy at _MEIPASS/tools/rig_launcher/assets, which is the same relative spot.
    assert icon.ICON_PATH.parts[-4:] == ("tools", "rig_launcher", "assets", "game_point.ico")


# -- dark title bar --------------------------------------------------------------


class _RecordingSetter:
    def __init__(self, rejected: set[int] | None = None) -> None:
        self.calls: list[tuple[int, int, int]] = []
        self._rejected = rejected or set()

    def __call__(self, hwnd: int, attribute: int, value: int) -> bool:
        self.calls.append((hwnd, attribute, value))
        return attribute not in self._rejected


def test_colorref_is_bgr() -> None:
    assert chrome.colorref("#C8983E") == 0x3E98C8
    assert chrome.colorref(theme.CARBON) == 0x0D0C0B


def test_dark_title_bar_paints_caption_in_house_colors() -> None:
    setter, refreshed = _RecordingSetter(), []

    assert chrome.apply_dark_title_bar(
        object(), set_attribute=setter, hwnd=0x1234, refresh=refreshed.append
    )

    assert setter.calls[0] == (0x1234, chrome.DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
    applied = {attribute: value for _, attribute, value in setter.calls[1:]}
    assert applied == {
        chrome.DWMWA_CAPTION_COLOR: chrome.colorref(theme.CARBON),
        chrome.DWMWA_TEXT_COLOR: chrome.colorref(theme.CHALK),
        chrome.DWMWA_BORDER_COLOR: chrome.colorref(theme.EDGE),
    }
    assert refreshed == [0x1234]


def test_dark_title_bar_falls_back_to_pre_20h1_attribute() -> None:
    setter = _RecordingSetter(rejected={chrome.DWMWA_USE_IMMERSIVE_DARK_MODE})
    assert chrome.apply_dark_title_bar(
        object(), set_attribute=setter, hwnd=7, refresh=lambda _h: None
    )
    attributes = [attribute for _, attribute, _ in setter.calls]
    assert attributes[:2] == [
        chrome.DWMWA_USE_IMMERSIVE_DARK_MODE,
        chrome.DWMWA_USE_IMMERSIVE_DARK_MODE_LEGACY,
    ]


def test_dark_title_bar_tolerates_pre_windows_11_color_attributes() -> None:
    setter = _RecordingSetter(rejected={a for a, _ in chrome.CAPTION_COLORS})
    assert chrome.apply_dark_title_bar(
        object(), set_attribute=setter, hwnd=7, refresh=lambda _h: None
    )


def test_dark_title_bar_is_a_noop_without_a_window_handle() -> None:
    class _NoFrame:
        def update_idletasks(self) -> None:
            raise RuntimeError("window gone")

    setter = _RecordingSetter()
    assert not chrome.apply_dark_title_bar(_NoFrame(), set_attribute=setter)
    assert setter.calls == []


def test_window_handle_reads_tk_wrapper_frame() -> None:
    class _Window:
        def update_idletasks(self) -> None:
            pass

        def wm_frame(self) -> str:
            return "0x1a2b"

    assert chrome.window_handle(_Window()) == 0x1A2B


# -- window icon + taskbar identity ---------------------------------------------


class _FakeWindow:
    def __init__(self, master: object | None = None) -> None:
        self.master = master
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def winfo_toplevel(self) -> _FakeWindow:
        return self

    def iconbitmap(self, *args: str, **kwargs: str) -> None:
        self.calls.append((args, kwargs))


def test_root_icon_becomes_default_for_every_toplevel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    root = _FakeWindow()
    assert chrome.apply_window_icon(root)
    assert root.calls == [((), {"default": str(icon.ICON_PATH)})]

    child = _FakeWindow(master=root)
    assert chrome.apply_window_icon(child)
    assert child.calls == [((str(icon.ICON_PATH),), {})]


def test_window_icon_skips_missing_asset_and_non_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _FakeWindow()
    monkeypatch.setattr(sys, "platform", "win32")
    assert not chrome.apply_window_icon(window, tmp_path / "missing.ico")
    monkeypatch.setattr(sys, "platform", "linux")
    assert not chrome.apply_window_icon(window)
    assert window.calls == []


def test_frozen_exe_keeps_its_own_taskbar_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # A custom AppUserModelID would split the running EXE from its Desktop shortcut pin.
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert not chrome.set_app_user_model_id()


# -- startup ordering + preview capture (PR #882 review) ------------------------


def test_failed_view_build_never_leaves_launcher_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    import tkinter as tk
    from unittest.mock import Mock

    from tools.rig_launcher import app, view

    root = Mock()
    monkeypatch.setattr(tk, "Tk", Mock(return_value=root))
    monkeypatch.setattr(chrome, "set_app_user_model_id", Mock(return_value=False))
    monkeypatch.setattr(chrome, "apply_dark_title_bar", Mock(return_value=True))
    monkeypatch.setattr(view, "build_launcher_view", Mock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        app.run_gui(Mock())

    root.withdraw.assert_called_once()
    root.deiconify.assert_called_once()
    root.mainloop.assert_not_called()


def test_caption_is_recoloured_while_hidden_then_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    import tkinter as tk
    from unittest.mock import Mock

    from tools.rig_launcher import app, view

    events: list[str] = []
    root = Mock()
    root.withdraw.side_effect = lambda: events.append("withdraw")
    root.deiconify.side_effect = lambda: events.append("deiconify")
    root.mainloop.side_effect = lambda: events.append("mainloop")
    monkeypatch.setattr(tk, "Tk", Mock(return_value=root))
    monkeypatch.setattr(chrome, "set_app_user_model_id", Mock(return_value=False))
    monkeypatch.setattr(
        chrome, "apply_dark_title_bar", Mock(side_effect=lambda _w: events.append("dark"))
    )
    monkeypatch.setattr(view, "build_launcher_view", Mock(return_value=Mock()))
    monkeypatch.setattr(app.threading, "Thread", Mock())
    supervisor = Mock()
    supervisor.config.start_simhub = False

    assert app.run_gui(supervisor) == 0
    assert events == ["withdraw", "dark", "deiconify", "mainloop"]


def test_preview_frame_bounds_fall_back_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.rig_launcher import preview

    monkeypatch.setattr(sys, "platform", "linux")
    assert preview._frame_bounds(object()) is None
