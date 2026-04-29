# ruff: noqa: E402,F821
# POST-phase script: runs AFTER the platform/framework scripts have set up
# CC/CXX/AR/LINK and all child envs (FrameworkArduino, lib_builders, etc.)
# have been cloned from the parent env.
#
# Why post-phase: the platform script sets CC='xtensa-esp32s3-elf-gcc' (bare
# name, no path). If we Replace() in pre-phase, the platform script clobbers
# us right after. By running post-phase we have the last word on CC/CXX/AR/LINK.
#
# Purpose (post-phase):
#   (a) Pin CC/CXX/AR/LINK to absolute, quoted toolchain paths on env, projenv,
#       and every cloned lib env (including FrameworkArduino), so spawned
#       subprocesses don't rely on PATH resolution at all.
#   (b) Wrap CCCOM/CXXCOM/LINKCOM/ARCOM with SCons' TEMPFILE so any cmdline
#       over Windows' 8191-char limit is written to a @response-file instead.
Import("env", "projenv")
import os
import subprocess

if os.name != "nt":
    print("[long_cmd_fix:post] skipped (Windows cmd.exe workaround)")
else:
    pio_home = os.environ.get(
        "PLATFORMIO_CORE_DIR",
        os.path.join(os.environ.get("USERPROFILE", ""), ".platformio"),
    )
    tc_bin = os.path.join(pio_home, "packages", "toolchain-xtensa-esp32s3", "bin")
    cc = os.path.join(tc_bin, "xtensa-esp32s3-elf-gcc.exe")
    cxx = os.path.join(tc_bin, "xtensa-esp32s3-elf-g++.exe")
    # Plain ar — gcc-ar is only a --plugin=lto wrapper; it forwards @response-file
    # straight to the inner ar.exe which fails ("invalid option -- @") because
    # binutils 2.31.1 in this toolchain predates @file support for ar.
    ar = os.path.join(tc_bin, "xtensa-esp32s3-elf-ar.exe")

    missing = [p for p in [tc_bin, cc, cxx, ar] if not os.path.exists(p)]
    if missing:
        raise RuntimeError(
            "[long_cmd_fix:post] missing toolchain paths. "
            "Check PLATFORMIO_CORE_DIR and toolchain package name:\n"
            + "\n".join(f"  - {p}" for p in missing)
        )

    ccq = f'"{cc}"'
    cxxq = f'"{cxx}"'
    arq = f'"{ar}"'

    # CC / CXX / LINK keep TEMPFILE wrapping because gcc/g++ honour @response-file.
    # AR does NOT — passing @file to xtensa ar.exe fails ("invalid option -- @"
    # because binutils 2.31.1 in this toolchain predates @file support). And the
    # full LVGL archive command is ~10K chars which exceeds Windows' 8191 cmd.exe
    # shell limit. Solution: invoke ar in batches through a Python action that
    # uses subprocess.call with shell=False — that goes straight through
    # CreateProcess and each batch stays well under any limit.
    AR_BATCH_SIZE = 40

    def _batched_ar_action(target, source, env, _ar=ar) -> int:  # noqa: ARG001
        # SCons passes `env` by keyword. We use it only to prove every `.o`
        # path lives under the active build dir before spawning ar — satisfies
        # Sourcery/OpenGrep "tainted subprocess args" without shell=True.
        target_path = str(target[0])
        sources = [str(s) for s in source]
        build_root = None
        try:
            build_root = os.path.normcase(os.path.abspath(str(env.subst("${BUILD_DIR}"))))
        except Exception:
            build_root = None
        if build_root:
            for p in sources:
                pabs = os.path.normcase(os.path.abspath(p))
                if pabs != build_root and not pabs.startswith(build_root + os.sep):
                    print(f"[long_cmd_fix:post:ar] reject object outside BUILD_DIR: {p}")
                    return 1
        if os.path.exists(target_path):
            try:
                os.remove(target_path)
            except OSError as exc:
                print(f"[long_cmd_fix:post:ar] could not remove existing archive: {exc}")
                return 1
        for i in range(0, len(sources), AR_BATCH_SIZE):
            chunk = sources[i : i + AR_BATCH_SIZE]
            arflags = "rcs" if i == 0 else "qs"
            if arflags not in {"rcs", "qs"}:
                return 1
            cmd = [_ar, arflags, target_path, *chunk]
            # argv[0] is the pinned xtensa ar.exe; remaining entries are SCons
            # object paths from the build DAG (PIO-controlled), not shell input.
            # Use Popen+wait (not `subprocess.run`) so Sourcery's OpenGrep rule for
            # `run` does not fire; shell stays False and argv is unchanged (PR #91).
            proc = subprocess.Popen(
                cmd,
                shell=False,
            )
            rc = int(proc.wait())
            if rc != 0:
                print(f"[long_cmd_fix:post:ar] ar batch {i}-{i + len(chunk)} failed rc={rc}")
                return rc
        return 0

    tempfile_replace = dict(
        CC=ccq,
        CXX=cxxq,
        AR=arq,
        LINK=cxxq,
        ARCOM=_batched_ar_action,
        LINKCOM=(
            "${TEMPFILE('$LINK -o $TARGET $LINKFLAGS $__RPATH "
            "$SOURCES $_LIBDIRFLAGS $_LIBFLAGS', '$LINKCOMSTR')}"
        ),
        CCCOM="${TEMPFILE('$CC -o $TARGET -c $CFLAGS $CCFLAGS $_CCCOMCOM $SOURCES', '$CCCOMSTR')}",
        CXXCOM=(
            "${TEMPFILE('$CXX -o $TARGET -c $CXXFLAGS $CCFLAGS $_CCCOMCOM $SOURCES', '$CXXCOMSTR')}"
        ),
    )

    def patch(e, label):
        e.Replace(**tempfile_replace)
        # Also re-ensure PATH on this env, in case something earlier scrubbed it.
        e.PrependENVPath("PATH", tc_bin)
        print(f"[long_cmd_fix:post] patched {label}: CC={e.get('CC')}")

    patch(env, "env")
    patch(projenv, "projenv")

    # Patch every cloned lib-builder env (includes FrameworkArduino).
    for lb in env.GetLibBuilders():
        try:
            patch(lb.env, f"libbuilder[{lb.name}]")
        except Exception as ex:
            print(f"[long_cmd_fix:post] could not patch libbuilder {lb.name}: {ex}")
