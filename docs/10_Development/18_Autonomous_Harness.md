# Autonomous harness — the one way to launch, drive, and prove (EPIC #154 / #459)

**Status:** Active
**Category:** Development

This is the **single documented path** for any agent (or human) that needs Assetto Corsa
driven autonomously and evidence collected — testing car setups, verifying a dashboard,
exercising voice coaching, capturing telemetry. Do **not** write throwaway `.scratch` drivers;
compose on this harness. (Repo skill pointer: `.claude/skills/ac-harness/SKILL.md`.)

## The one command

```bash
python -m tools.ac_harness.auto_drive \
    --car ks_porsche_911_gt3_r_2016 --track spa \
    --setup Realistic_BB_v3 --driver ggv --wait-lap
```

That single command owns the whole loop:

1. **Preflight** — content installed, CSP `[CUSTOM_AI] ENABLED=1`, Content Manager present,
   setup resolvable, preset↔CLI combo consistency. Fails fast with an actionable message
   (`--preflight-only` runs just this gate).
2. **Sidecar** — reuses a listening sidecar (e.g. the Game Point launcher's supervised child on
   `:8765`); auto-starts a loopback `tools.ai_sidecar` otherwise (`--no-sidecar-autostart` to
   forbid; `--keep-sidecar` to leave it running).
3. **Deterministic launch** — with `--car`, a pinned practice `.cmpreset` is generated (clear
   weather, 26 °C, 12:00, optimum track — the #154 determinism-lock preset) and launched via the
   de-elevated Content Manager URL, with relaunch retries on the menu-skip race.
   Hand-authored presets: `--cm-preset <file>` (the preflight cross-checks its CarId/TrackId).
4. **Setup applied AND verified at launch** — `--setup <name>` resolves under
   `Documents/Assetto Corsa/setups/<car>/<track|layout|generic>/`. AC applies a car setup **only at
   car spawn, from `race.ini`** — the in-sim WS `setup.load` path is gated by
   `ac.isCarResetAllowed()`, which stays false for a freshly-spawned autonomous car (live-found
   "must be in pits", Spa 2026-07-02, even before any hijack). So the harness **bakes the setup into
   `race.ini`** (`_EXT_SETUP_FILENAME` — Content Manager's own key — plus vanilla `SETUP=`) and
   direct-relaunches acs so the car respawns with it, then **verifies** by reading
   `acpmf_physics.fuel` back against the setup's `[FUEL] VALUE`. A match (±2.5 L default) confirms
   it (live-verified: fuel 45.0 L == Realistic_BB_v3 `FUEL=45`); a mismatch **fails the run at
   `stage="setup"`**. A direct relaunch skips AC's pre-drive menu via CSP `gui.ini [GUI]
   FORCE_START=1` (set for the relaunch, restored after — OS input injection to the menu is blocked,
   so this is the only headless way past it). A setup with no `[FUEL]` section is reported
   baked-but-unconfirmed rather than failing.
5. **Drive** — `--driver ggv` (flat-out friction-circle min-time), `racing` (AI-line pace,
   default), or `cruise` (slow lane-keeper). Guards: sim-death detection, a **no-progress
   watchdog** (recovers stalls regardless of throttle), a **recovery cap** (default 6) that fails
   honestly with the stall location, and spawn-to-line teleport for pit-box starts
   (`--no-spawn-line` to disable).
6. **Assert** — taps the sidecar WS and asserts the live producer contract
   (`connection`/`tire_temps`/`coaching.snapshot`; `--wait-lap` additionally requires a completed
   lap; `--strict` enforces session→lap ordering).
7. **Evidence bundle** — everything a downstream task needs to *prove* its outcome.

## Evidence contract

Default bundle: `.scratch/harness-evidence/<utc>_<car>_<track>/` (override `--evidence-dir`):

| Artifact | Content |
|---|---|
| `report.json` | Full `AutoDriveReport` (pass/fail + stage, combo, `setup_requested/applied` + in-sim ack, drive stats incl. `recoveries`/`spawn_teleport`, WS frame counts) plus run extras: preset used, sidecar provenance, HUD verdict, lap-archive paths |
| `generated.cmpreset` | The exact preset launched (when generated) |
| `hud.png` | Post-run HUD capture (`--hud-region full|left|coaching`) with liveness verdict |
| `lap_archives` (in report.json) | Paths of `journal/laps/lap_*.json` written during the run — full telemetry traces for session review / setup comparison |

Bundles live under `.scratch/` — **session ephemera**. A consuming task promotes what it must
keep (reference archives, curated comparisons) to a durable location; never treat the bundle as
long-term storage (scratch-dir disposability pitfall).

## Composing downstream tasks (don't reinvent)

- **Setup A/B**: run twice with different `--setup` names; compare the runs' lap archives with
  `python -m tools.session_review` (see `17_Session_Review.md`) or `setup.compare` frames.
- **Dashboard / HUD verification**: use the drive as the live signal source; assert on
  `hud.png` + your own captures while the run holds the car on track.
- **Voice coaching**: run with the sidecar voice enabled; the WS tap counts in `report.json`
  prove the advisory stream flowed while the car drove.
- **Reference laps / TT comparison**: `--wait-lap` guarantees at least one archived lap;
  feed it to `tools.tt_ingest` / session review with `--reference-source tt`.

## Known limitation — setup runs vs. the autonomous drive (tracked)

The setup path (bake + fuel-verify) and the autonomous drive **do not yet compose in one command**,
because they need different launch modes:

- The **drive** needs a **CM launch from the start line** (grid): CM skips the pre-drive menu and
  arms CSP Custom-AI, and the car has open track ahead. This is live-proven (multi-track: Spa + BMW
  Z4 GT3 flat-out, 211 km/h).
- The **setup** needs a **direct acs relaunch** (to bake `race.ini` — CM regenerates it and its
  Quick-Drive preset carries no setup). But the direct relaunch's spawn states each block the drive:
  a **`START` spawn freezes the Car0 (Custom-AI) mmap** so the hijack never lands, and a **`PIT`
  spawn** hijacks fine but the car can't escape Spa's pit box (the custom-teleport offsets that
  would jump it to the racing line are unverified).

So today: `--setup` **applies + verifies** the setup (proven) but the drive leg then fails to move
the car; and a plain `--driver` run drives (proven) without a chosen setup. Resolving the
composition — CM setup-carry, or fixing the `START`-spawn Custom-AI freeze, or verifying the
custom-teleport offsets — is tracked as a follow-up on #154. Use `--setup` today to **prove a setup
loads** (fuel-verified evidence bundle); use a no-setup run to **prove the drive**.

## Troubleshooting (hard-won rig lore — read before debugging)

| Symptom | Cause / fix |
|---|---|
| Preflight `custom_ai` failure | Set `[CUSTOM_AI] ENABLED=1` in `<AC root>/extension/config/new_behaviour.ini` (user `cfg/extension/new_behaviour.ini` overrides when it carries the key) |
| `stage=setup`, `applied=False`, fuel mismatch | The launch bake didn't take — check `race.ini [CAR_0] _EXT_SETUP_FILENAME` points at the setup and the direct relaunch reached LIVE; the setup's `[FUEL] VALUE` is the expected number |
| `--setup` run: setup `applied=True` but drive fails (`stage=hijack` or `recovery cap ... at 0m`) | Known limitation (see above) — the direct-launch spawn can't compose with the drive yet. The setup IS applied/verified; the drive needs a no-setup CM run |
| CM clicks/launch do nothing | **Foreground steal**: minimize the agent/terminal window; AC's fullscreen menu covers CM — the harness kills stale `acs.exe` before each launch |
| "Steam API failed to initialize" | Steam elevation mismatch — restart Steam **non-elevated** (`steam -shutdown`, relaunch via `explorer.exe`) |
| `setup.load` error "no loopback Lua peer connected" | The trainer app isn't (yet) connected to the sidecar — the harness retries for `setup_timeout`; persistent = app not installed/enabled in CSP |
| Run FAILS with `recovery cap exceeded at <N>m` | Real stall: the car repeatedly stopped at the same spot. Inspect `hud.png` + the stall distance; do **not** raise the cap to make it "pass" |
| Two agents, one rig | **Yield**: a single AC instance cannot serve two autonomous sessions (see the issue-277 investigation). Check for a running `acs.exe`/peer sidecar before launching |
| Sidecar port already in use | That's usually the Game Point launcher's supervised sidecar — the harness reuses it; don't spawn a second |

## Layers underneath (when you need less than the full loop)

`auto_drive` composes the primitives; they remain individually usable:
`entry_launcher` (launch only) · `custom_ai` (carcsw actuation) · `sequence_probe` (WS assert
only, `--skip-launch` style) · `hud_capture` (render liveness) · `self_test` (producer contract
without motion) · `daemon` (persistent rig service with `/session/start`).
Architecture decision record: vault `01_Decisions/autonomous-self-test-harness.md`.
