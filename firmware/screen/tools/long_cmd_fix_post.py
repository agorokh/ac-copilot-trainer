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

pio_home = os.environ.get('PLATFORMIO_CORE_DIR',
    os.path.join(os.environ.get('USERPROFILE',''), '.platformio'))
tc_bin = os.path.join(pio_home, 'packages', 'toolchain-xtensa-esp32s3', 'bin')

cc  = os.path.join(tc_bin, 'xtensa-esp32s3-elf-gcc.exe')
cxx = os.path.join(tc_bin, 'xtensa-esp32s3-elf-g++.exe')
ar  = os.path.join(tc_bin, 'xtensa-esp32s3-elf-gcc-ar.exe')

ccq  = f'"{cc}"'
cxxq = f'"{cxx}"'
arq  = f'"{ar}"'

TEMPFILE_REPLACE = dict(
    CC   = ccq,
    CXX  = cxxq,
    AR   = arq,
    LINK = cxxq,
    ARCOM   = "${TEMPFILE('$AR $ARFLAGS $TARGET $SOURCES', '$ARCOMSTR')}",
    LINKCOM = "${TEMPFILE('$LINK -o $TARGET $LINKFLAGS $__RPATH $SOURCES $_LIBDIRFLAGS $_LIBFLAGS', '$LINKCOMSTR')}",
    CCCOM   = "${TEMPFILE('$CC -o $TARGET -c $CFLAGS $CCFLAGS $_CCCOMCOM $SOURCES', '$CCCOMSTR')}",
    CXXCOM  = "${TEMPFILE('$CXX -o $TARGET -c $CXXFLAGS $CCFLAGS $_CCCOMCOM $SOURCES', '$CXXCOMSTR')}",
)

def patch(e, label):
    e.Replace(**TEMPFILE_REPLACE)
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
