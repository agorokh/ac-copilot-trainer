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

Create or refresh the Desktop shortcut:

```powershell
python -m tools.rig_launcher --install-shortcut
```

The shortcut points at `dist\AC-Copilot-Game-Point.exe` and uses the repository
root as the working directory. The exe remains a local build artifact and is not
committed.

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

## Setup Exchange

The rig-screen Setup Exchange tile talks to the Python sidecar with
`se.search` / `se.download`. The sidecar proxies the public Setup Exchange
endpoint and installs downloaded `.ini` files under the Assetto Corsa user
setups folder without overwriting existing files.

Optional environment overrides:

- `AC_COPILOT_SE_ENDPOINT` changes the Setup Exchange HTTP endpoint, mainly for
  local proxy or fake-service tests.
- `AC_COPILOT_USER_SETUPS_DIR` points at the Assetto Corsa `setups` directory
  when Windows Documents discovery cannot find it.
