"""Tests for the launcher's private (FR_PRIVATE) design-font loading (epic #432).

All GDI interaction is injected — no test touches the real gdi32, so the suite
is deterministic on any platform and never mutates the host's font table.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools.rig_launcher import fonts


class _RecordingAddFont:
    """Fake gdi32.AddFontResourceExW registrar recording (path, flags) calls."""

    def __init__(self, result: bool = True) -> None:
        self.calls: list[tuple[str, int]] = []
        self._result = result

    def __call__(self, path: str, flags: int) -> bool:
        self.calls.append((path, flags))
        return self._result


def _make_fonts(directory: Path, names: tuple[str, ...]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"\x00")


def test_loads_every_design_face_with_fr_private_flag(tmp_path: Path) -> None:
    _make_fonts(tmp_path, fonts.FONT_FILES)
    add = _RecordingAddFont()

    loaded = fonts.load_private_fonts(font_dirs=[tmp_path], add_font=add)

    assert sorted(loaded) == sorted(fonts.FONT_FILES)
    assert fonts.FR_PRIVATE == 0x10
    assert {flags for _path, flags in add.calls} == {fonts.FR_PRIVATE}


def test_missing_files_are_tolerated_silently(tmp_path: Path) -> None:
    present = fonts.FONT_FILES[:2]
    _make_fonts(tmp_path, present)

    loaded = fonts.load_private_fonts(font_dirs=[tmp_path], add_font=_RecordingAddFont())

    assert loaded == list(present)


def test_no_fonts_anywhere_returns_empty_list(tmp_path: Path) -> None:
    add = _RecordingAddFont()

    loaded = fonts.load_private_fonts(
        font_dirs=[tmp_path, tmp_path / "does-not-exist"], add_font=add
    )

    assert loaded == []
    assert add.calls == []


def test_first_directory_with_fonts_wins(tmp_path: Path) -> None:
    frozen = tmp_path / "frozen" / "fonts"
    repo = tmp_path / "repo" / "fonts"
    _make_fonts(frozen, fonts.FONT_FILES[:1])
    _make_fonts(repo, fonts.FONT_FILES)
    add = _RecordingAddFont()

    loaded = fonts.load_private_fonts(font_dirs=[frozen, repo], add_font=add)

    assert loaded == [fonts.FONT_FILES[0]]
    assert all(path.startswith(str(frozen)) for path, _flags in add.calls)


def test_failed_gdi_registration_is_dropped_from_result(tmp_path: Path) -> None:
    _make_fonts(tmp_path, fonts.FONT_FILES)

    loaded = fonts.load_private_fonts(
        font_dirs=[tmp_path], add_font=_RecordingAddFont(result=False)
    )

    assert loaded == []


def test_noop_when_gdi_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_fonts(tmp_path, fonts.FONT_FILES)
    monkeypatch.setattr(fonts, "_resolve_gdi_add_font", lambda: None)

    assert fonts.load_private_fonts(font_dirs=[tmp_path]) == []


def test_gdi_resolution_is_none_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fonts.sys, "platform", "linux")

    assert fonts._resolve_gdi_add_font() is None


def test_default_font_dirs_prefer_frozen_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(Path("C:/frozen/bundle")), raising=False)

    dirs = fonts._font_dirs()

    assert dirs[0] == Path("C:/frozen/bundle") / "fonts"
    assert dirs[1].as_posix().endswith("src/ac_copilot_trainer/content/fonts")


def test_default_font_dirs_without_frozen_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    dirs = fonts._font_dirs()

    assert len(dirs) == 1
    assert dirs[0].as_posix().endswith("src/ac_copilot_trainer/content/fonts")
