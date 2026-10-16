"""Safety boundaries for simulator evidence and the actual PlatformIO upload action."""

from __future__ import annotations

import json
import runpy
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from tools import screen_simulator as simulator


def test_png_preserves_framebuffer_pixels(tmp_path):
    pixels = bytes(range(256)) * 1800
    source = tmp_path / "screen.ppm"
    source.write_bytes(b"P6\n320 480\n255\n" + pixels)
    png = simulator.ppm_to_png(source).read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    compressed = b""
    while offset < len(png):
        size = struct.unpack(">I", png[offset : offset + 4])[0]
        kind = png[offset + 4 : offset + 8]
        body = png[offset + 8 : offset + 8 + size]
        crc = struct.unpack(">I", png[offset + 8 + size : offset + 12 + size])[0]
        assert crc == zlib.crc32(kind + body)
        if kind == b"IDAT":
            compressed += body
        offset += size + 12
    scanlines = zlib.decompress(compressed)
    assert b"".join(scanlines[y * 961 + 1 : (y + 1) * 961] for y in range(480)) == pixels


@pytest.mark.parametrize("data", [b"", b"P6\n320 480\n255\n", b"P6\n1 1\n255\nabc"])
def test_invalid_framebuffer_cannot_be_evidence(tmp_path, data):
    source = tmp_path / "screen.ppm"
    source.write_bytes(data)
    with pytest.raises(RuntimeError, match="Invalid"):
        simulator.ppm_to_png(source)


def test_failed_native_command_is_fatal(tmp_path):
    with pytest.raises(RuntimeError, match="failed"):
        simulator.run_command([sys.executable, "-c", "raise SystemExit(7)"], tmp_path / "test.log")


def test_successful_run_needs_fresh_artifacts_and_unchanged_source(tmp_path, monkeypatch):
    """A prior green run cannot certify a changed tree or an empty current test run."""
    tool = tmp_path / ("cmake.exe" if simulator.os.name == "nt" else "cmake")
    tool.touch()
    tool.with_name("ctest.exe" if simulator.os.name == "nt" else "ctest").touch()
    monkeypatch.setattr(simulator, "find_cmake", lambda: tool)
    digest = ["before"]
    monkeypatch.setattr(simulator, "source_digest", lambda _: digest[0])
    monkeypatch.setattr(simulator, "firmware_lvgl_version", lambda _: "8.3.11")
    build_dir = tmp_path / "build"
    artifact_directory = []

    def fake_native(command, log):
        log.write_text("executed", encoding="utf-8")
        artifact_directory[:] = [log.parent]
        if log.name == "test.log":
            (log.parent / "results.json").write_text(
                json.dumps(
                    {"passed": True, "assertions": 1, "lvgl": "8.3.11", "captures": ["screen.ppm"]}
                )
            )
            (log.parent / "screen.ppm").write_bytes(
                b"P6\n320 480\n255\n" + bytes(range(256)) * 1800
            )

    monkeypatch.setattr(simulator, "run_command", fake_native)
    first = simulator.run(tmp_path, build_dir)
    assert (first / "index.html").is_file()
    assert json.loads((first / "results.json").read_text())["source_sha256"] == "before"

    def no_new_artifacts(command, log):
        log.write_text("no tests ran", encoding="utf-8")

    monkeypatch.setattr(simulator, "run_command", no_new_artifacts)
    with pytest.raises(FileNotFoundError):
        simulator.run(tmp_path, build_dir)

    def changes_source(command, log):
        fake_native(command, log)
        if log.name == "test.log":
            digest[0] = "changed"

    monkeypatch.setattr(simulator, "run_command", changes_source)
    with pytest.raises(RuntimeError, match="source changed"):
        simulator.run(tmp_path, build_dir)
    assert artifact_directory[0] != first


@pytest.mark.parametrize("pin", ["~8.3.11", "^8.3.11", "", "8.3.11\nlvgl/lvgl @ 8.4.0"])
def test_firmware_needs_unambiguous_exact_lvgl_pin(tmp_path, pin):
    project = tmp_path / "firmware/screen"
    project.mkdir(parents=True)
    (project / "platformio.ini").write_text(f"[env:screen]\nlib_deps=\n lvgl/lvgl @ {pin}\n")
    with pytest.raises(RuntimeError, match="pin exactly one"):
        simulator.firmware_lvgl_version(tmp_path)


@pytest.mark.parametrize("fault", ["version", "binary", "missing_capture", "capture_escape"])
def test_current_run_cannot_admit_incomplete_or_mismatched_evidence(tmp_path, monkeypatch, fault):
    tool = tmp_path / ("cmake.exe" if simulator.os.name == "nt" else "cmake")
    tool.touch()
    tool.with_name("ctest.exe" if simulator.os.name == "nt" else "ctest").touch()
    binary = tmp_path / "firmware.bin"
    binary.write_bytes(b"original binary")
    monkeypatch.setattr(simulator, "find_cmake", lambda: tool)
    monkeypatch.setattr(simulator, "source_digest", lambda _: "stable source")
    monkeypatch.setattr(simulator, "firmware_lvgl_version", lambda _: "8.3.11")

    def fake_native(command, log):
        log.write_text("ran", encoding="utf-8")
        if log.name != "test.log":
            return
        report = {"passed": True, "assertions": 1, "lvgl": "8.3.11", "captures": ["screen.ppm"]}
        if fault == "version":
            report["lvgl"] = "9.0.0"
        if fault == "capture_escape":
            report["captures"] = ["../screen.ppm"]
        (log.parent / "results.json").write_text(json.dumps(report))
        if fault != "missing_capture":
            (log.parent / "screen.ppm").write_bytes(
                b"P6\n320 480\n255\n" + bytes(range(256)) * 1800
            )
        if fault == "binary":
            binary.write_bytes(b"a different binary")

    monkeypatch.setattr(simulator, "run_command", fake_native)
    with pytest.raises((RuntimeError, FileNotFoundError)):
        simulator.run(tmp_path, tmp_path / "build", binary)


def test_upload_action_runs_gate_every_time_and_blocks_on_failure(tmp_path, monkeypatch):
    """Load the real extra script and call its registered pre-upload action."""
    root = Path(__file__).resolve().parents[1]
    registered = {}
    calls = []

    class ConstructionEnvironment:
        def subst(self, value):
            return {
                "$PROJECT_DIR": str(root / "firmware/screen"),
                "$PYTHONEXE": sys.executable,
                "$BUILD_DIR/${PROGNAME}.bin": str(tmp_path / "firmware.bin"),
            }[value]

        def AddPreAction(self, target, action):
            registered[target] = action

    env = ConstructionEnvironment()
    module = runpy.run_path(
        str(root / "firmware/screen/tools/simulator_gate.py"),
        init_globals={"Import": lambda _: None, "env": env},
    )

    def succeed(command, **kwargs):
        assert kwargs["check"] is True
        assert kwargs["cwd"] == root
        assert command[0] == sys.executable
        assert Path(command[1]) == root / "tools/screen_simulator.py"
        assert command[2:] == ["--firmware", str(tmp_path / "firmware.bin")]
        calls.append(command)

    monkeypatch.setattr(module["subprocess"], "run", succeed)
    for target in ("upload", "program", "upload"):
        registered[target]([], [], env)
    assert len(calls) == 3

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(module["subprocess"], "run", fail)
    uploaded = False
    with pytest.raises(subprocess.CalledProcessError):
        registered["upload"]([], [], env)
        uploaded = True
    assert not uploaded
