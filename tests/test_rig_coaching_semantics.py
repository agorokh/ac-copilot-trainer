"""Execute the firmware action contract with a native C++ compiler."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _compiler(tmp_path: Path) -> tuple[str, dict[str, str]]:
    env = dict(os.environ)
    for name in ("g++", "clang++"):
        compiler = shutil.which(name)
        if compiler:
            return compiler, env
    if os.name == "nt":
        vswhere = Path(os.environ.get("ProgramFiles(x86)", "")) / (
            "Microsoft Visual Studio/Installer/vswhere.exe"
        )
        if vswhere.is_file():
            result = subprocess.run(
                [str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
                capture_output=True,
                text=True,
                check=True,
            )
            devcmd = Path(result.stdout.strip()) / "Common7/Tools/VsDevCmd.bat"
            if devcmd.is_file():
                env_script = tmp_path / "compiler_env.cmd"
                env_script.write_text(
                    f'@call "{devcmd}" -no_logo -arch=x64 >nul\n@set\n', encoding="utf-8"
                )
                result = subprocess.run(
                    ["cmd.exe", "/d", "/c", str(env_script)],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                env.update(
                    line.split("=", 1)
                    for line in result.stdout.splitlines()
                    if "=" in line and not line.startswith("=")
                )
                compiler = shutil.which("cl.exe", path=env.get("Path", env.get("PATH")))
                if compiler:
                    return compiler, env
    pytest.skip("native C++ compiler unavailable; PlatformIO build still required")


def test_native_coaching_actions_and_unavailable_states(tmp_path: Path) -> None:
    compiler, env = _compiler(tmp_path)
    source = tmp_path / "coaching.cpp"
    source.write_text(
        r"""
#include "ui/coaching_semantics.h"
#include <cassert>
#include <cstdio>
int main() {
    const char* actions[] = {"BRAKE", "LIFT", "UPSHIFT", "HOLD", "CLEAR", "UNAVAILABLE"};
    for (const char* action : actions) {
        assert(strcmp(coaching_command(action, "legacy text", true, false), action) == 0);
    }
    assert(strcmp(coaching_command("CARRY_MORE_SPEED", "", true, false), "CARRY MORE SPEED") == 0);
    assert(strcmp(coaching_command("bogus", "BRAKE NOW", true, false), "UNAVAILABLE") == 0);
    assert(strcmp(coaching_command("BRAKE", "", false, false), "WAIT") == 0);
    assert(strcmp(coaching_command("UPSHIFT", "", true, true), "STALE") == 0);
    assert(strcmp(coaching_command("", "SHIFT UP", true, false), "UPSHIFT") == 0);
    assert(strcmp(coaching_command("", "CARRY MORE SPEED", true, false), "CARRY MORE SPEED") == 0);
    assert(strcmp(coaching_command("", "LIFT", true, false), "LIFT") == 0);
    assert(strcmp(coaching_command("", "BRAKE NOW", true, false), "BRAKE") == 0);
    assert(strcmp(coaching_command("", "KEEP YOUR LINE", true, false), "UNAVAILABLE") == 0);
    assert(strcmp(coaching_command("", "TARGET 230 KM/H", true, false), "UNAVAILABLE") == 0);
    puts("explicit, legacy, stale and unavailable coaching actions passed");
}
""",
        encoding="utf-8",
    )
    output = tmp_path / ("coaching.exe" if os.name == "nt" else "coaching")
    include = REPO / "firmware/screen/include"
    if Path(compiler).name.lower() == "cl.exe":
        command = [
            compiler,
            "/nologo",
            "/EHsc",
            "/std:c++17",
            f"/I{include}",
            str(source),
            f"/Fe:{output}",
        ]
    else:
        command = [compiler, "-std=c++17", "-I", str(include), str(source), "-o", str(output)]
    subprocess.run(command, env=env, cwd=tmp_path, capture_output=True, text=True, check=True)
    result = subprocess.run([str(output)], capture_output=True, text=True, check=True)
    assert "actions passed" in result.stdout
