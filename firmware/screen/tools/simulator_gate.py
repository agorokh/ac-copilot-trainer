"""PlatformIO pre-upload gate: test current production screens before touching hardware."""

import subprocess
from pathlib import Path


def verify_before_upload(source, target, env):
    project = Path(env.subst("$PROJECT_DIR")).resolve()
    root = project.parents[1]
    command = [
        env.subst("$PYTHONEXE"),
        str(root / "tools/screen_simulator.py"),
        "--firmware",
        env.subst("$BUILD_DIR/${PROGNAME}.bin"),
    ]
    print("[screen simulator] Fresh native screen verification required before upload")
    subprocess.run(command, cwd=root, check=True)


Import("env")  # noqa: F821 -- supplied by PlatformIO/SCons
env.AddPreAction("upload", verify_before_upload)  # noqa: F821
