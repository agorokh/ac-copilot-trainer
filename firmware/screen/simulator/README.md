# Rig screen simulator and pre-flash verification

Run from the repository root:

```console
python -m tools.screen_simulator
# Same suite, run by the required CI build alongside make ci-fast:
make ci-screen
```

Requires Python 3.11+, CMake 3.20+ and a native C/C++17 compiler. On Windows,
install Visual Studio Build Tools with Desktop development with C++; the runner
finds its bundled CMake through `vswhere` if CMake is absent from PATH. Linux CI
installs CMake/G++. The first run downloads the SHA256-pinned LVGL 8.3.11 archive
with a 180-second timeout; subsequent builds reuse it. CI caches only the pinned
dependency archive (CMake rechecks its SHA256), never test results. Firmware and
simulator pin the same release.

The build compiles the **production** `src/ui/*.cpp`, generated fonts and
`include/lv_conf.h`, at 320x480 portrait resolution with the real RGB565 renderer.
The scenarios send pointer press/release coordinates through LVGL hit testing.
They cover Launcher/Back navigation, WAIT/BRAKE/UPSHIFT/STALE states, four-digit
distance fitting, Pocket Technician setup-load requests and offline gating,
Setup Exchange author attribution, search/download failures, install acknowledgments,
the installed setup's Pocket Technician load and permission gate, and disconnected state.

Each invocation creates fresh evidence under
`.scratch/screen-simulator/runs/<UTC>-<unique-id>/`:

- `results.json`: scenario assertions, LVGL version, source SHA256, timestamps and
  optional firmware binary SHA256.
- `index.html` and PNG/PPM framebuffers: actual rendered screens for inspection.
- `configure.log`, `build.log`, `test.log`: native toolchain and scenario output.

CI installs CMake/G++ explicitly and runs `make ci-screen` alongside `make ci-fast`
in the required `build` job, then uploads the
screenshots/results as `screen-simulator-<sha>`. A failed native scenario fails CI.
An earlier green run never substitutes for the current run. Changes during a run
invalidate its result. To isolate builds, pass `--build-dir <path>`.

## Before every flash

1. The agent runs the simulator for the proposed firmware and **opens/inspects the
   generated PNGs**, checking layout, glyphs and the states affected by its change.
   Repair software failures on the PC before asking the operator to touch hardware.
2. Use the normal PlatformIO upload from `firmware/screen` (`pio run -t upload`,
   or `pio run -e jc3248w535 -t upload` for the legacy WebSocket build).
   Both environments inherit `tools/simulator_gate.py`, a pre-upload/program action that
   rebuilds/runs this same simulator afresh and binds its result to the upload BIN.
   A missing compiler, failed test, missing/invalid capture or source/binary change
   **aborts before the uploader runs**. There is no skip flag or cached-pass switch.
3. Observe the actual device only for the physical checks described below. Keep
   rig ownership, serial-port ownership and backup rules from the parent README.

Direct `esptool write_flash` and other external uploaders are outside PlatformIO's
hook. Agents must not use them to bypass this prerequisite: run the same simulator
and inspect its images before **any** firmware write, including recovery flashes.
Read-only factory backups do not flash the device and need no simulator run.

## Coverage and operator involvement

This is a source-reusing **UI simulator**, not an emulator of the ESP32-S3 and
AXS15231B electronics. Its host adapters supply simulated time, pointer input,
framebuffer output, process-local Preferences and placeholder debug heap values.
Fixtures are synthetic inputs to the same screen APIs called by firmware dispatch.

Agents own routine navigation, fonts, numeric fitting, live/stale/empty/error UI,
request payload checks and rendered-image review. Agents also perform automated
backend/transport checks wherever existing tools permit them. Operator assistance
is reserved for physical panel visibility/colour/backlight, touch alignment and
feel, cable/reset/boot behavior, and acceptance that needs real hardware/driving.
The simulator does not prove real serial/WiFi delivery, MCU memory/timing, durable
NVS across power loss, actual setup installation or its in-game application.
Report those separately; do not ask the operator to repeat software tests already
settled here. Issue #86's retained physical acceptance is not waived by a PC pass.
