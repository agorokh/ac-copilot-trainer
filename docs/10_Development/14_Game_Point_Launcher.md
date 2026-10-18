# Game Point launcher

The Game Point launcher is the canonical Windows entrypoint for driver-facing rig
features. If a feature is something the operator should start, monitor, or tune
at the rig, it belongs in `tools/rig_launcher` unless the issue explicitly says
otherwise.

## User install path

Build the packaged exe from the repo root:

```powershell
pip install -e ".[launcher]"
python -m tools.rig_launcher --build-exe
```

The build extra includes the runtime voice floor (`numpy`, `sounddevice`,
`pyttsx3`, and PyInstaller collection for sounddevice's PortAudio binaries).
`rtmixer` remains opt-in via `pip install -e ".[voice-rtmixer]"`; when it is
installed, the build helper collects it opportunistically. Bake-time neural
voice prosody still requires a system `ffmpeg` on `PATH` before running
`python -m tools.ai_sidecar.voice.bake`.

Create or refresh the Desktop shortcut:

```powershell
python -m tools.rig_launcher --install-shortcut
```

The shortcut points at `dist\AC-Copilot-Game-Point.exe` and uses the repository
root as the working directory. The exe remains a local build artifact and is not
committed.

The launcher measures its fonts and controls on every start and uses that size
as its initial and minimum window size. The START and other action buttons stay
visible beneath all status rows without a manual resize. The window can still
be enlarged; live status updates can raise the minimum to fit longer messages
without shrinking a larger window chosen by the operator. Its visual preview
uses the same sizing path.

### Audio backend (rtmixer is opt-in)

`pip install -e ".[launcher]"` is **always installable on a clean Windows rig**:
its sidecar voice floor is `numpy` + `sounddevice`, which ship bundled-PortAudio
wheels. The lower-latency `rtmixer` backend is **not** part of the default
`launcher` / `voice` extras (issue #383) — it has no prebuilt Windows wheels and
needs a C/PortAudio build toolchain, so bundling it made the documented install
path hard-fail on the rig.

The voice engine auto-falls back to the `sounddevice` backend when `rtmixer` is
not importable (PR #387), so voice playback works with the floor alone. To opt
into the lower-latency backend **where a C/PortAudio toolchain can build it**,
add the best-effort extra:

```powershell
pip install -e ".[launcher,voice-rtmixer]"
```

`voice-rtmixer` self-references the `voice` extra, so `pip install -e ".[voice-rtmixer]"`
also installs the `numpy` + `sounddevice` floor. Select the backend at runtime
with `AC_COPILOT_VOICE_BACKEND` (`rtmixer` or `sounddevice`).

Set `voice_channel_map` in Game Point `settings.json` to a comma-separated list
of one-based output channels (for example, `"5,6"`) when the endpoint needs an
explicit speaker route. `AC_COPILOT_VOICE_CHANNEL_MAP` overrides that setting;
the sidecar also accepts `--voice-channel-map`. Omit the setting or use JSON
`null` to retain the existing layout defaults. An explicit blank, duplicate,
non-integer, non-positive, or unsupported channel fails closed. Mono speech is
duplicated to every listed channel; a multichannel bank needs one destination
per source channel. An explicit WASAPI map opens the endpoint's full advertised
channel count: changing stream width changes Windows speaker positions, so a
smaller accepted layout must not silently reroute the selected channel.
Both audio backends report the actual negotiated mapping
in `/health` as `voice.channel_map`; pyttsx3 cannot honor a channel map and is
disabled when one is supplied. For an audible calibration, pass the same map
to `tools.ai_sidecar.voice.audible_latency run --chirp-channel-map 5,6`.

## UI design handoff

Before changing launcher screens, rig screen UI, or cross-surface status
language, read [15_Claude_Design_UI_Package.md](15_Claude_Design_UI_Package.md).
It captures the current Tkinter launcher, LVGL rig screen, CSP HUD, protocol
state, and future UI scope for Claude Design or any implementation agent.

## Extension contract

When adding a new rig-facing function:

1. Add launch/status/config behavior to `tools/rig_launcher`, usually through
   `GamePointConfig`, `GamePointSupervisor`, and the Tk UI in `app.py`.
2. Add non-secret settings to the per-user Game Point `settings.json` contract.
   Keep tokens and credentials in environment variables such as
   `AC_COPILOT_SIDECAR_TOKEN`; do not persist them in `settings.json`.
3. Add or update tests in `tests/test_rig_launcher.py` for config precedence,
   status rendering, and any Windows shell integration through injected fakes.
4. Update this file and the `AGENTS.md` launcher bullet when a new operator
   setting or visible launcher section is added.
5. Keep runtime code stdlib-only where feasible. Optional build or audio
   dependencies stay behind `pyproject.toml` extras.

Settings precedence is:

1. CLI flags for the current launch.
2. Environment variables.
3. `%LOCALAPPDATA%\AC Copilot Trainer\GamePoint\settings.json`.
4. Built-in defaults.

`settings.json` is created by the launcher's **Settings** button, or can be
created ahead of time by calling `ensure_settings_file()` from
`tools.rig_launcher.settings`.

### Offline native / MOZA reports (#815 Part C)

Choose **OFFLINE REPORT** in Game Point, then select one native lap archive or
readable MOZA cache JSON. A matched native archive and an evaluation JSON are
optional separate selections. **Inspect MOZA advice availability** is off by
default. **SAVE SELECTIONS & GENERATE** runs the offline review on a worker;
**OPEN REPORT** opens the resulting HTML when available. Normal status polling
does not reread the selected files.

Selections use the existing per-user settings file: `moza_offline_file`,
`moza_offline_native_file`, `moza_offline_evaluation_file`, and
`moza_offline_oracle`. Relative selections resolve under the Game Point data
directory. Reports use the existing writer under that directory's
`journal/reports`; source files remain untouched. Reopening Game Point restores
the selections but does not generate a report automatically.

The Offline report row shows the last explicit result: analysis available,
inspection only, input unavailable, or error, with the qualification reason and
control authority. A native file without attribution remains `legacy_unknown`;
selecting it here does not establish MOZA or human control. Processed caches may
produce an inspection report while native channels, corner comparison, and
producer advice remain unavailable. Zero eligible evaluated laps do not become
coaching advice. Offline status is advisory and never blocks START.

These selections do not change `reference_archive`, Track Titan, alien-line or
voice settings, and never enter the live sidecar command or environment. This
action starts no AC session, sidecar, or speech playback. Part D owns any later
shadow voice evidence and activation decision.

Coach v2 can consume an issue #529 alien-line artifact through
`AC_COPILOT_ALIEN_LINE` or the non-secret `alien_line` settings key. The launcher
resolves relative paths against the Game Point data directory and passes the
absolute path to the sidecar. Configuring it also activates Coach v2; there is
no separate hidden prerequisite. The artifact supplies only a per-corner speed
ceiling: the demonstrated reference archive remains authoritative for braking,
throttle, steering, and cue timing. Missing driver history retains reference
targets; malformed, unverified, wrong-combo, unmatchable, or slower-than-driver
alien evidence fails closed and reports the reason under
`voice.coach_frontier` in `/health`.
Before activation, the sidecar recomputes the plant provenance from the same
filename under sibling `plant_id/`, hashes the current track `fast_lane.ai`, and
re-runs corridor plus plant-envelope verification over the cached line and speed
profile. Standard Steam and AC Documents locations need no extra settings.
Non-standard layouts can override the sources with
`AC_COPILOT_ALIEN_PLANT`, `AC_COPILOT_ALIEN_FAST_LANE`, or
`AC_COPILOT_AC_ROOT`. Public health exposes activation, source, and stable reason
codes only—never per-corner driver metrics, source hashes, paths, or exception text.
Personalized targets use each raw profile sample's `brake_point_spline` as the
corner identity; the per-lap ordinal is never trusted. Refresh older profiles
with `python -m tools.ai_sidecar.driver_profile --lap-dir <journal/laps>` so
their sample ledger carries this identity. Until then the frontier stays on the
reference target rather than guessing.

The launcher status row for `voice` is sourced from the sidecar `/health`
payload when the sidecar is reachable. A stale bank, missing reference archive,
or failed audio backend reports `voice: DISABLED - <reason>` and makes the
overall status `needs_attention`; the launcher does not treat the mere presence
of `AC_COPILOT_VOICE_BANK` as proof that audio initialized.

## Stable AC driver session

The **Stable AC** button is the operator-facing entrypoint for the resilient
Content Manager launch loop from issue #624. It retries the stochastic CSP
session-init livelock, proves continuous render progress for the configured
stability window plus the CSP Car0 drivability handshake, and then leaves the
successful session live for the driver.
The `AC Session` row reports `unconfigured`, `idle`, `running`, or the child
exit code; progress is appended to `logs/resilient-launch.log`. A failed child
makes the aggregate status non-green and the summary says **Press Stable AC**,
so the recovery action is unambiguous without conflating it with sidecar START.
Because the packaged child has no console, **Release AC** writes the shared
ownership-release signal; the child then drops the rig lock while deliberately
leaving AC live. The signal also works after Game Point is closed and reopened.
If the ownership file cannot be read or probed, the AC Session row reports
`unknown`, aggregate status stays non-green, and Stable AC refuses to spawn
until ownership can be determined.

Configure the non-secret car and circuit identifiers in the per-user
`settings.json`:

```json
{
  "ac_user_dir": "C:\\Users\\driver\\Documents\\Assetto Corsa",
  "resilient_car": "ks_porsche_911_gt3_r_2016",
  "resilient_track": "spa",
  "resilient_layout": "",
  "resilient_cm_exe": "D:\\Portable CM\\Content Manager.exe"
}
```

Stable AC on the supported CSP 0.2.11 runtime also requires
`[NEW_UI] REPLACE_MAIN_MENU=0` in `cfg\extension\gui.ini` under that AC
user-data directory. CSP 0.2.11's New UI ignores `ac.tryToStart`; Game Point
therefore reads this setting before launch and reports `menu_config_required`
with the exact remediation path instead of exhausting the launch budget at the
pre-drive screen. `ac_user_dir` is optional when the standard Documents or
OneDrive Documents path can be discovered.

After Stable AC presses Start, the session is already drivable, but AC's
render counter stops for several seconds while physics keeps running (about
10 s measured on the rig). The screen may look frozen during that time. Stable
AC treats a stopped render as a freeze only after it has stayed stopped for
20 s, the same limit Game Point uses while it holds a running session, and
waits out shorter pauses. It also retries the Car0 handshake up to three times
after Start, the same budget `auto_drive` uses. Launcher reports before
`resilient-launch-report/v6` scored that pause as `froze` and killed a
drivable session, so their freeze counts are not comparable (#627).

Stable AC currently requires the default `sidecar_port` of `8765`. Game Point
can pass another port to its Python children, but it cannot safely rewrite the
CSP app's persisted `wsSidecarUrl` before AC starts. It therefore reports
`sidecar_port_unsupported` and refuses to launch when these endpoints could
diverge, instead of claiming that the authenticated Lua start-control path is
armed. Custom ports remain supported for sidecar-only operation.

Environment variables `AC_COPILOT_RESILIENT_CAR`,
`AC_COPILOT_RESILIENT_TRACK`, `AC_COPILOT_RESILIENT_LAYOUT`, and
`AC_COPILOT_RESILIENT_CM_EXE` override those values;
`AC_COPILOT_AC_USER_DIR` overrides `ac_user_dir`. Leave `resilient_cm_exe`
blank for the standard Program Files install. For a one-shot command, use
`--resilient-launch` with optional `--resilient-car`, `--resilient-track`,
`--resilient-layout`, and `--resilient-cm-exe` CLI overrides.
The packaged executable dispatches the same child workflow, and closing Game
Point does not terminate a stable operator session. Embedders and tests that set
`GamePointConfig.rig_lock_path` pass that exact ownership path to the child; the
production launcher continues to use the machine-wide Harness LocalAppData path.
The matching release signal is stored beside that lock.

## SimHub auto-start

SimHub is the operator's haptics/dashboard app (e.g. ShakeIt bass-shaker
effects). The launcher treats it as an **optional peer, not a data source** — it
reads the same Assetto Corsa shared memory the sidecar reads, so starting it adds
tactile feedback, not telemetry.

By default the launcher only **detects** SimHub and shows its status
(`running` / `available` / `absent`); a missing SimHub is never a blocking row
(`GamePointStatus.ok` skips `absent`/`skipped` rows). To make one launch bring up
the whole rig, enable auto-start either way — the default is **off**, matching the
opt-in pattern used for other behavior-changing launcher features:

- **In the launcher UI** — tick **Auto-start SimHub**. The choice persists to
  `start_simhub` in the per-user `settings.json` and applies immediately: the next
  status poll starts SimHub, or adopts an already-running instance.
- **By environment / CLI** — `AC_COPILOT_START_SIMHUB=1`, or `--start-simhub` for
  a single run. Point `AC_COPILOT_SIMHUB_EXE` at `SimHubWPF.exe` if auto-discovery
  under `Program Files` / `Program Files (x86)` misses it.

The launcher never edits SimHub's own profiles and never double-launches a SimHub
the operator already started.

## Setup Exchange

The rig-screen Setup Exchange tile talks to the Python sidecar with
`se.search` / `se.download`. With an Assetto Corsa practice session and the trainer
app running, the sidecar routes these requests to the trainer's CSP client. It
uses the same signed `/session` flow and community service as the installed
Setup Exchange app. No separate proxy is required. Community authors and download
counts appear on the screen; downloaded `.ini` files are installed under the
Assetto Corsa user setups folder without overwriting existing files. Loading
continues through the existing pits/reset permission check.

The native route requires exactly one authenticated trainer connection. Missing
or ambiguous trainers, stale car/session context, timeouts and service failures
produce a visible error. Signing material and service session IDs stay inside
CSP. The installed third-party app is not modified.

Optional environment overrides:

- `AC_COPILOT_SE_ENDPOINT` points at an authenticated proxy or fake-service
  endpoint for local tests.
- `AC_COPILOT_USER_SETUPS_DIR` points at the Assetto Corsa `setups` directory
  when Windows Documents discovery cannot find it.
