"""Issue #893: the Game Point EXE must not depend on which interpreter runs --build-exe."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.rig_launcher.app as app_module
import tools.rig_launcher.build as build_module
from tools.rig_launcher.build import (
    FrozenBuildError,
    ensure_sapi_speechlib,
    missing_frozen_modules,
    prepare_frozen_build,
    pyinstaller_command,
    run_build,
)
from tools.rig_launcher.build_info import BuildInfo
from tools.rig_launcher.supervisor import (
    FROZEN_EXCLUDED_MODULES,
    SAPI_SPEECHLIB_MODULE,
    build_pyinstaller_args,
)


def _option_values(args: list[str], option: str) -> list[str]:
    return [right for left, right in zip(args, args[1:], strict=False) if left == option]


def _args(tmp_path: Path) -> list[str]:
    return build_pyinstaller_args(
        tmp_path, build_info=BuildInfo("abc1234", "2026-10-18T00:00:00Z"), hook_dir=tmp_path
    )


def test_build_args_bundle_pregenerated_speechlib(tmp_path: Path) -> None:
    hidden = _option_values(_args(tmp_path), "--hidden-import")

    assert SAPI_SPEECHLIB_MODULE == "comtypes.gen.SpeechLib"
    assert "pyttsx3.drivers.sapi5" in hidden
    assert SAPI_SPEECHLIB_MODULE in hidden


def test_build_args_exclude_interpreter_optional_modules(tmp_path: Path) -> None:
    excluded = _option_values(_args(tmp_path), "--exclude-module")

    assert set(FROZEN_EXCLUDED_MODULES) == {
        "PIL",
        "defusedxml",
        "jinja2",
        "markupsafe",
        "threadpoolctl",
    }
    assert excluded == list(FROZEN_EXCLUDED_MODULES)
    # Excluding something the EXE needs would break it on the rig, not at build time.
    assert not set(excluded) & set(_option_values(_args(tmp_path), "--hidden-import"))


def test_missing_frozen_modules_requires_sapi_backend_only_on_windows() -> None:
    def nothing(_module: str) -> None:
        return None

    windows = missing_frozen_modules(platform="win32", find=nothing)
    linux = missing_frozen_modules(platform="linux", find=nothing)

    assert {"numpy", "sounddevice", "pyttsx3", "serial", "websockets"} <= set(linux)
    assert "comtypes" not in linux
    assert set(windows) - set(linux) == {"comtypes", "pythoncom"}
    assert missing_frozen_modules(platform="win32", find=lambda _m: object()) == []


def test_prepare_fails_loudly_on_missing_module_before_speechlib() -> None:
    calls: list[str] = []

    with pytest.raises(FrozenBuildError, match=r"missing pyttsx3.*\[launcher\]"):
        prepare_frozen_build(
            platform="win32",
            find=lambda m: None if m == "pyttsx3" else object(),
            speechlib=lambda: calls.append("speechlib") or Path("x"),
        )
    assert calls == []


@pytest.mark.parametrize(("platform", "expected"), [("win32", ["speechlib"]), ("linux", [])])
def test_prepare_generates_speechlib_on_windows_only(platform: str, expected: list[str]) -> None:
    calls: list[str] = []

    prepare_frozen_build(
        platform=platform,
        find=lambda _m: object(),
        speechlib=lambda: calls.append("speechlib") or Path("x"),
    )

    assert calls == expected


def _comtypes_spec(root: Path) -> SimpleNamespace:
    return SimpleNamespace(submodule_search_locations=[str(root / "comtypes")])


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_speechlib_generated_inside_comtypes_package_is_accepted(tmp_path: Path) -> None:
    target = tmp_path / "comtypes" / "gen" / "SpeechLib.py"
    seen: list[list[str]] = []

    def run(cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        seen.append(cmd)
        return _completed(0, stdout=f"{target}\n")

    result = ensure_sapi_speechlib(python="py", run=run, find=lambda _m: _comtypes_spec(tmp_path))

    assert result == target
    assert seen[0][:2] == ["py", "-c"]
    assert "pyttsx3.drivers.sapi5" in seen[0][2]


def test_speechlib_in_user_cache_fails_the_build(tmp_path: Path) -> None:
    # Read-only site-packages: comtypes falls back to %APPDATA% / %TEMP%, where Analysis
    # cannot find it and the module would silently drop out of the bundle.
    cached = tmp_path / "AppData" / "comtypes_cache" / "SpeechLib.py"

    with pytest.raises(FrozenBuildError, match="outside the comtypes package"):
        ensure_sapi_speechlib(
            python="py",
            run=lambda *_a, **_k: _completed(0, stdout=f"{cached}\n"),
            find=lambda _m: _comtypes_spec(tmp_path),
        )


def test_speechlib_generation_failure_reports_the_error(tmp_path: Path) -> None:
    stderr = "Traceback ...\nOSError: [WinError -2147221005] Invalid class string\n"

    with pytest.raises(FrozenBuildError, match="Invalid class string"):
        ensure_sapi_speechlib(
            python="py",
            run=lambda *_a, **_k: _completed(1, stderr=stderr),
            find=lambda _m: _comtypes_spec(tmp_path),
        )


def test_pyinstaller_command_prepares_before_analysis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(build_module, "build_pyinstaller_args", lambda root: ["--name", str(root)])
    order: list[str] = []

    cmd = pyinstaller_command(tmp_path, prepare=lambda: order.append("prepare"))

    assert order == ["prepare"]
    assert cmd[1:] == ["-m", "PyInstaller", "--name", str(tmp_path)]


def test_run_build_aborts_without_invoking_pyinstaller(tmp_path: Path, monkeypatch, capsys) -> None:
    def refuse(_root: Path) -> list[str]:
        raise FrozenBuildError("missing comtypes")

    def no_call(*_a: object, **_k: object) -> int:
        raise AssertionError("PyInstaller must not run")

    monkeypatch.setattr(build_module, "pyinstaller_command", refuse)
    monkeypatch.setattr(subprocess, "call", no_call)

    assert run_build(tmp_path) == 2
    assert "Game Point build aborted: missing comtypes" in capsys.readouterr().err


def test_app_build_exe_goes_through_run_build(monkeypatch) -> None:
    roots: list[Path] = []
    monkeypatch.setattr(app_module, "run_build", lambda root: roots.append(root) or 7)

    assert app_module.main(["--build-exe"]) == 7
    assert roots == [Path(app_module.__file__).resolve().parents[2]]
