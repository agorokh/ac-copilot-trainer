# ruff: noqa: E402,F821
# PRE-phase script: runs BEFORE the platform/framework scripts so that when
# they clone env for FrameworkArduino and lib envs, our PATH setting is
# inherited by every cloned env.
#
# Purpose (pre-phase): PATH only.
#   Put the xtensa toolchain onto BOTH env['ENV']['PATH'] and os.environ['PATH']
#   so any SCons-spawned cmd.exe subprocess can resolve bare xtensa-esp32s3-elf-*
#   names. env['ENV'] is copied into every env.Clone(), and os.environ is the
#   ultimate parent of every subprocess we spawn, so patching both covers
#   FrameworkArduino + lib_builders + main env.
#
# CC/CXX/AR/LINK absolute-path replacement and TEMPFILE wrapping live in the
# POST-phase script (long_cmd_fix_post.py), because the platform script that
# runs AFTER this pre-phase will overwrite whatever Replace() we do here.
Import("env")
import os

if os.name != "nt":
    print("[long_cmd_fix:pre] skipped (Windows cmd.exe workaround)")
else:
    pio_home = os.environ.get(
        "PLATFORMIO_CORE_DIR",
        os.path.join(os.environ.get("USERPROFILE", ""), ".platformio"),
    )
    tc_bin = os.path.join(pio_home, "packages", "toolchain-xtensa-esp32s3", "bin")

    env.PrependENVPath("PATH", tc_bin)
    path_entries = [p.lower() for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if tc_bin.lower() not in path_entries:
        os.environ["PATH"] = tc_bin + os.pathsep + os.environ.get("PATH", "")

    print(f"[long_cmd_fix:pre] toolchain PATH prepended: {tc_bin}")
    print(f"[long_cmd_fix:pre] exists={os.path.isdir(tc_bin)}")
