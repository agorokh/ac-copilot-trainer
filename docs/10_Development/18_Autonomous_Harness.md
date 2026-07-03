# Autonomous harness — the one way to launch, drive, and prove (EPIC #154 / #459)

**Status:** Active
**Category:** Development

This is the **single documented path** for any agent (or human) that needs Assetto Corsa
driven autonomously and evidence collected — testing car setups, verifying a dashboard,
exercising voice coaching, capturing telemetry. Do **not** write throwaway `.scratch` drivers;
compose on this harness. (Repo skill pointer: `.claude/skills/ac-harness/SKILL.md`.)

## The commands

Two working paths today — **prove the drive** (no setup), or **prove a setup applies and drives** in
one command.

```bash
# Prove the autonomous DRIVE (live-verified: Spa flat-out, gears 1→6, reference coaching):
python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016 --track spa \
    --driver ggv --wait-lap

# Prove a car SETUP applies + is verified, then complete an autonomous lap:
python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016 --track spa \
    --setup Realistic_BB_v3 --driver ggv --wait-lap
```

The full loop each command owns:

1. **Preflight** — content installed, CSP `[CUSTOM_AI] ENABLED=1`, Content Manager present,
   setup resolvable, preset↔CLI combo consistency. Fails fast with an actionable message
   (`--preflight-only` runs just this gate).
2. **Sidecar** — reuses a listening sidecar (e.g. the Game Point launcher's supervised child on
   `:8765`); auto-starts a loopback `tools.ai_sidecar` otherwise (`--no-sidecar-autostart` to
   forbid; `--keep-sidecar` to leave it running).
3. **Deterministic launch** — with `--car`, a pinned practice `.cmpreset` is generated (clear
   weather, 26 °C, 12:00, optimum track — the #154 determinism-lock preset) and launched via the
   de-elevated Content Manager URL, with relaunch retries on the CM auto-start race.
   Hand-authored presets: `--cm-preset <file>` (the preflight cross-checks its CarId/TrackId).
4. **Setup applied AND verified at launch** — `--setup <name>` resolves under
   `Documents/Assetto Corsa/setups/<car>/<track|layout|generic>/`. AC applies a car setup **only at
   car spawn, from `race.ini`** — the in-sim WS `setup.load` path is gated by
   `ac.isCarResetAllowed()`, which stays false for a freshly-spawned autonomous car (live-found
   "must be in pits", Spa 2026-07-02, even before any hijack). So the harness keeps CM's launch path
   and **continuously re-bakes the setup into `race.ini`** during CM startup (`_EXT_SETUP_FILENAME`
   — Content Manager's own key — plus vanilla `SETUP=`), then **verifies** by reading
   `acpmf_physics.fuel` (via the open-existing shared-memory reader, so a dead sim can't spoof a
   zero) back against the setup's `[FUEL] VALUE`. A match (±2.5 L default) confirms it (live-verified:
   fuel 45.0 L == Realistic_BB_v3 `FUEL=45`); a mismatch **fails the run at `stage="setup"`**. A
   setup with no `[FUEL]` section is reported baked-but-unconfirmed. The re-bake loop writes only
   under `Documents/Assetto Corsa/cfg`; it does not mutate the AC/CSP install tree.
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

## Setup + autonomous drive compose in one command (#461)

`--setup … --wait-lap` applies the setup AND drives. The compliant composition is:

- CM remains the only launch path. It supplies the reliable session auto-start behavior that a direct
  `acs.exe` relaunch does not.
- While CM is launching, the harness repeatedly re-bakes `Documents/Assetto Corsa/cfg/race.ini` with
  `CAR_0._EXT_SETUP_FILENAME=<setup.ini>`, `CAR_0.SETUP=<name>.ini`, and `SESSION_0.SPAWN_SET=START`.
  This races CM's own `race.ini` regeneration without writing outside AC Documents.
- Once AC reaches LIVE, `rig_apply_setup` verifies the setup via shared-memory fuel before the hijack
  and drive legs run.

### Overlay fast-fail + keypress nudge (#466)

`_wait_live` reports LIVE the instant `acpmf_graphics.status==LIVE` with advancing physics — but AC
can sit at the NEW-UI "0 seconds" pre-drive overlay **with LIVE status and advancing physics** when
CM's auto-start race loses (foreground steal, or degraded CSP state after many hard `acs.exe` kills).
LIVE but **not drivable**, and the carcsw hijack (CSP creating `Car0`) is the only deterministic
"session is actually drivable" signal. So the hijack is a sequence of **short `--hijack-probe-seconds`
probes** (default 5 s, recreating `CarControls0` each time to also beat the early-LIVE race): a
stalled overlay is detected in seconds and the run **recycles a fresh launch** instead of burning one
long dead-wait. An **opt-in** keypress nudge (`--overlay-nudge`) can try to clear the overlay in place
between probes: it focuses AC's own window (defeating Windows foreground-lock via `AttachThreadInput`,
then verifying focus before injecting) and presses Enter/Space. The per-cycle `[auto-drive HH:MM:SS] …`
log lines show each launch, probe outcome, re-bake stats, and nudge so a recycle's timing is visible.

> **Verified in-sim (2026-07-03, #466/#482).** The keypress nudge is **OFF by default** because it
> does **not** clear the overlay: with AC correctly focused (foreground-lock defeated via
> `AttachThreadInput`) and receiving real Enter/Space, the CSP "0 seconds" overlay does not dismiss —
> consistent with #465's finding that only the `FORCE_START` config skips it, no keypress does. The
> fast-fail relaunch is the real recovery. The
> **no-setup drive path is reliable** (CM auto-starts; fast-fail retries land the hijack — e.g. LIVE
> and hijacked on cycle 1). The **`--setup` path is not yet reliable**, and instrumentation
> (`--setup-rebake-interval`, re-bake stats) pinned *why*: the overlay stall is the setup re-bake
> itself. The write that injects the setup into `race.ini` races acs's spawn-read that CM's
> immediate-start depends on — baking aggressively (0.05 s default) applies the setup but **breaks**
> the auto-start (overlay stall); baking gently preserves the auto-start but **misses** the setup. No
> cadence resolves it (sharp transition ~0.05→0.1 s), and a post-hijack `SimState` restart does not
> re-read the setup. A reliable `--setup` run needs a different injection mechanism (candidate:
> PIT-spawn + pre-hijack in-sim `setup.load` while `ac.isCarResetAllowed()` is true in the pit box) —
> tracked on #466. Until then a `--setup` run may stall at the overlay; a plain no-setup drive is
> reliable.

## Troubleshooting (hard-won rig lore — read before debugging)

| Symptom | Cause / fix |
|---|---|
| Preflight `custom_ai` failure | Set `[CUSTOM_AI] ENABLED=1` in `<AC root>/extension/config/new_behaviour.ini` (user `cfg/extension/new_behaviour.ini` overrides when it carries the key) |
| `stage=setup`, `applied=False`, fuel mismatch | The launch bake didn't take — check `race.ini [CAR_0] _EXT_SETUP_FILENAME` points at the setup and the CM launch reached LIVE; the setup's `[FUEL] VALUE` is the expected number |
| `--setup` run: setup `applied=True` but `stage=hijack` | The car stalled at AC's non-hijackable "0 seconds" overlay through every launch cycle (the setup re-bake breaks CM's immediate-start, #466). The setup is applied/verified. The harness fast-fails each stalled cycle and **recycles a fresh launch**; if it still exhausts `max_launches`, reboot the rig (degraded from many hard `acs.exe` kills) and rerun. The optional `--overlay-nudge` keypress is **off by default** and verified NOT to clear the CSP overlay (#466) |
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
