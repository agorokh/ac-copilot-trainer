"""Build/test the real ESP32 LVGL screens on a PC; emit PNG evidence before flashing."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import uuid
import zlib
from datetime import UTC, datetime
from pathlib import Path


def find_cmake() -> Path:
    """Use PATH or the installed Visual Studio CMake, without changing host settings."""
    if executable := shutil.which("cmake"):
        return Path(executable)
    if os.name == "nt":
        installer = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
        vswhere = installer / "Microsoft Visual Studio/Installer/vswhere.exe"
        if vswhere.is_file():
            result = subprocess.run(
                [str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
                check=True,
                capture_output=True,
                text=True,
            )
            candidate = Path(result.stdout.strip()) / (
                "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
            )
            if candidate.is_file():
                return candidate
    raise RuntimeError("CMake 3.20+ and a native C/C++ compiler are required; upload refused")


def source_digest(root: Path) -> str:
    """Bind evidence to this checkout's sources, config, fonts, adapter and flash path."""
    firmware = root / "firmware/screen"
    files = [root / "tools/screen_simulator.py", firmware / "platformio.ini"]
    for directory in ("include", "src", "simulator", "tools"):
        files.extend(
            path
            for path in (firmware / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def firmware_lvgl_version(root: Path) -> str:
    text = (root / "firmware/screen/platformio.ini").read_text(encoding="utf-8")
    pins = re.findall(r"^\s*lvgl/lvgl\s*@\s*(\d+\.\d+\.\d+)\s*$", text, re.MULTILINE)
    if len(pins) != 1:
        raise RuntimeError("Firmware must pin exactly one LVGL version before simulation/upload")
    return pins[0]


def ppm_to_png(source: Path) -> Path:
    """Convert the simulator's exact RGB framebuffer without an imaging dependency."""
    header = b"P6\n320 480\n255\n"
    raw = source.read_bytes()
    if not raw.startswith(header) or len(raw) != len(header) + 320 * 480 * 3:
        raise RuntimeError(f"Invalid 320x480 simulator framebuffer: {source.name}")
    pixels = raw[len(header) :]
    if len(set(pixels)) < 8:
        raise RuntimeError(f"Blank or invalid rendered screen: {source.name}")

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    scanlines = b"".join(b"\0" + pixels[y * 960 : (y + 1) * 960] for y in range(480))
    png = source.with_suffix(".png")
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 480, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )
    return png


def run_command(command: list[str], log: Path) -> None:
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            command, stdout=stream, stderr=subprocess.STDOUT, check=False, timeout=300
        )
    if result.returncode:
        print(log.read_text(encoding="utf-8", errors="replace")[-16000:], file=sys.stderr)
        raise RuntimeError(f"Simulator command failed ({result.returncode}); see {log}")


def run(root: Path, build_dir: Path, firmware_binary: Path | None = None) -> Path:
    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    artifacts = build_dir / "runs" / run_id
    artifacts.mkdir(parents=True, exist_ok=False)
    before = source_digest(root)
    lvgl_version = firmware_lvgl_version(root)
    binary_hash = (
        hashlib.sha256(firmware_binary.read_bytes()).hexdigest() if firmware_binary else None
    )
    cmake = find_cmake()
    ctest = cmake.with_name("ctest.exe" if os.name == "nt" else "ctest")
    if not ctest.is_file():
        raise RuntimeError("CTest is required alongside CMake; upload refused")
    build = build_dir / "build"
    run_command(
        [
            str(cmake),
            "-S",
            str(root / "firmware/screen/simulator"),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            f"-DSIMULATOR_ARTIFACT_DIR={artifacts.as_posix()}",
        ],
        artifacts / "configure.log",
    )
    run_command(
        [str(cmake), "--build", str(build), "--config", "Release", "--parallel", "4"],
        artifacts / "build.log",
    )
    run_command(
        [str(ctest), "--test-dir", str(build), "-C", "Release", "--verbose"],
        artifacts / "test.log",
    )
    report_path = artifacts / "results.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("passed") is not True or not report.get("captures"):
        raise RuntimeError("Simulator produced no successful scenario evidence; upload refused")
    if report.get("lvgl") != lvgl_version:
        raise RuntimeError("Simulator and firmware LVGL versions differ; upload refused")
    images = []
    for name in report["captures"]:
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".ppm"):
            raise RuntimeError("Invalid capture manifest; upload refused")
        images.append(ppm_to_png(artifacts / name))
    if source_digest(root) != before:
        raise RuntimeError(
            "Firmware/simulator source changed during verification; rerun before upload"
        )
    if firmware_binary and hashlib.sha256(firmware_binary.read_bytes()).hexdigest() != binary_hash:
        raise RuntimeError("Firmware binary changed during verification; upload refused")
    report.update(
        source_sha256=before,
        firmware_sha256=binary_hash,
        started_at=started.isoformat(),
        finished_at=datetime.now(UTC).isoformat(),
        coverage="native UI only; physical panel/touch/transport/NVS/install not emulated",
    )
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    cards = "".join(
        f'<figure><img src="{html.escape(path.name)}"><figcaption>'
        f"{html.escape(path.stem)}</figcaption></figure>"
        for path in images
    )
    (artifacts / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Rig screen simulator</title>'
        "<style>body{background:#202020;color:white;font:14px sans-serif}"
        "main{display:flex;flex-wrap:wrap}figure{margin:10px}img{width:320px;height:480px}</style>"
        f"<h1>Rig screen simulator: {report['assertions']} assertions passed</h1>"
        f"<p>{html.escape(report['coverage'])}</p><main>{cards}</main>",
        encoding="utf-8",
    )
    print(f"Screen simulator PASS: {report['assertions']} assertions; evidence: {artifacts}")
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, help="Default: repo/.scratch/screen-simulator")
    parser.add_argument("--firmware", type=Path, help="Bind the fresh run to this upload binary")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    build_dir = (args.build_dir or root / ".scratch/screen-simulator").resolve()
    try:
        run(root, build_dir, args.firmware)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Screen simulator FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
