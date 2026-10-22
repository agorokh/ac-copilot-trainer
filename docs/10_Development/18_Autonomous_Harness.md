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
python -m tools.ac_harness.auto_drive --car bmw_m3_gt2 --track magione \
    --driver ggv --wait-lap

# Prove a car SETUP applies + is verified, then complete an autonomous lap:
python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016 --track spa \
    --setup Realistic_BB_v3 --driver ggv --wait-lap
```

The full loop each command owns:

1. **Preflight** — content installed, CSP `[CUSTOM_AI] ENABLED=1`, Content Manager present,
   setup resolvable, preset↔CLI combo consistency. Fails fast with an actionable message
   (`--preflight-only` runs just this gate). Selected-car validation follows AC's complete
   read-only launch chain: a readable packed `data.acd` or unpacked `data/` source must expose
   `lods.ini`, and every `[LOD_n] FILE=` must name a present, non-empty `.kn5`. A content failure
   stops before launch.
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
   default), or `cruise` (slow lane-keeper). Guards: sim-death detection plus one bounded fresh
   full-launch retry by default (`--sim-death-retries 0` disables), a **no-progress
   watchdog** (recovers stalls regardless of throttle), a **recovery cap** (default 6) that fails
   honestly with the stall location, a bounded 2 Hz **control trace** (gear/RPM/controls/position +
   forced recovery events), and spawn-to-line teleport for pit-box starts
   (`--no-spawn-line` to disable).
6. **Assert** — taps the sidecar WS and asserts the live producer contract
   (`connection`/`tire_temps`/`coaching.snapshot`; `--wait-lap` additionally requires a completed
   lap; `--strict` enforces session→lap ordering).
7. **Evidence bundle** — everything a downstream task needs to *prove* its outcome.

## Evidence contract

Default bundle: `.scratch/harness-evidence/<utc>_<car>_<track>/` (override `--evidence-dir`):

| Artifact | Content |
|---|---|
| `report.json` | Final `AutoDriveReport` plus full `attempts` history (a recovered sim death remains measurable), combo/setup ack, drive stats incl. `recoveries`/`spawn_teleport` and bounded `control_trace`, WS frame counts, preset/sidecar provenance, HUD verdict, and lap-archive paths. A fatal preflight also writes this artifact with `stage=preflight`, `launched=false`, no drive/attempt, and `preflight.classification=non_drive_preflight_failure`, explicitly excluded from drive and sim-death denominators. |
| `generated.cmpreset` | The exact preset launched (when generated) |
| `hud.png` | Post-run HUD capture (`--hud-region full|left|coaching`) with liveness verdict |
| `hud-frames/` | Opt-in (`--hud-every N`, N ≥ 1 s): a timestamped frame every N seconds for the whole run plus `index.jsonl` (`epoch`, `done_epoch`, liveness or `error`), summarised as `hud_frames` in `report.json`. Captured by a child process in the run's console session so the per-pixel conversion never stalls the driver; capped at 600 frames; a failed grab is recorded, never fatal. Lets an observing agent check what the screen showed, and when. |
| `lap_archives` (in report.json) | Paths of `journal/laps/lap_*.json` written during the run — full telemetry traces for session review / setup comparison |

Bundles live under `.scratch/` — **session ephemera**. A consuming task promotes what it must
keep (reference archives, curated comparisons) to a durable location; never treat the bundle as
long-term storage (scratch-dir disposability pitfall).

## Plant-ID handshake (#529 P1 / #532 / #543 — measure constants and uncertainty)

The GGV driver's constants (`ff_sign`, `ff_c1/ff_c2`, shift points, `r_eff`) used to be
hand-tuned per combo. The **handshake** measures them from designed in-sim probes in ≤2 laps
and persists a per-combo artifact:

```bash
# 1) Measure the plant (guided probes: steer pulses, WOT sweep, coast, corner mining):
python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016 --track magione \
    --driver handshake --drive-seconds 600

# 2) Drive with the measured constants (shift points by default; measured steering with full):
python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016 --track magione \
    --driver ggv --use-plant full --wait-lap
```

- Artifacts persist under `<AC user data>/plant_id/<car>__<track>.json` — a **durable** path,
  never `.scratch` (the original offline `model_id.py` was lost to scratch disposal).
- Every measured constant carries a quality metric + provenance in `report.json`
  (`extras.handshake`); a probe that fails its gate **FAILs the run at `stage="handshake"`**
  naming the probe and the observed values — no silent fallback to hand constants.
- `--use-plant auto` (default) applies measured shift points when an artifact exists;
  `full` also enables the measured curvature-feedforward steering; `off` forces the generic
  GT3 plant. `full` without an artifact fails fast — run the handshake first.
- Schema v3 promotes the GGV fit only after the run's immutable lap archive supplies all four
  tyre-core temperatures, all four hot pressures, the car-true optimum, a setup identity, at least 80%
  channel coverage, and at least 80% per-wheel stability within ±5 °C of each wheel's median. The
  four wheel medians must remain within 15 °C of one another. Stable `cold`, `optimal`, and `hot`
  laps are explicit, separate cohorts; residence within ±10 °C of the optimum is recorded but is not
  an eligibility gate. This permits conservative identification on tyres that stabilize below the
  declared optimum without mixing thermal regimes. When CSP writes the default setup as an empty
  snapshot/hash, the harness derives its deterministic identity from that snapshot. Only valid laps
  in one compound/setup/tag cohort
  and within ±5 °C / ±2 psi of that cohort are fitted. The per-lap tag and selected UUIDs remain in
  `report.json` under `extras.handshake.ggv.tyre_states`.
- A below-optimum non-stationary lap may use the temperature-tagged cold-side path without
  weakening that stable-lap gate. It must retain complete four-wheel core-temperature
  attribution, stay entirely at or below `optimalTempC`, and satisfy the same identity, coverage,
  validity, and median-center wheel-spread gates. Intra-lap cooling from a track-load cycle is
  allowed while the optimum ceiling holds; a 0.5 C per-wheel reversal veto is not applied
  (it refused the measured 2026-08-10 huracan@spa it1 cycle). Pressure-incomplete rows that hide
  a larger wheel split than the existing 15 C cap fail closed. The fitter records every row's
  thermal state but builds the static runtime envelope only from the globally coldest observed
  5 C band, anchored by every complete four-wheel thermal observation even when a sample lacks
  usable friction channels. Hotter rows cannot raise a cold-start assumption; crossing the
  optimum or lacking enough cold-band rows fails closed and preserves the prior plant.
  The accepted rationale and rejected alternatives are recorded in
  `docs/01_Vault/AcCopilotTrainer/01_Decisions/cold-side-temperature-tagged-friction-refit-2026-08-28.md`.
- The promoted model carries 10 km/h bins from 0–300 km/h. Each lateral/brake/drive bin records a
  Bayesian posterior mean, epistemic standard deviation, lower confidence bound, sample count, and
  `measured`/`prior` provenance. The QSS always consumes `min(point estimate, lower bound)`.
  Unmeasured bins use the lower bound of the generic prior; there is no neighbour or upward
  extrapolation, and speeds above the map retain the last conservative bound.
- Schema-v1/v2 constants remain backward-compatible. Their missing or point-estimate-only GGV data
  is deliberately ignored at runtime until a fresh schema-v3 handshake establishes uncertainty.

The uncertainty policy follows friction-adaptive stochastic control work that propagates Bayesian
friction uncertainty into safe control, while the thermal gate follows measured tyre evidence that
core/surface temperature changes lateral behaviour and pressure tracks temperature:
[friction-adaptive SNMPC](https://arxiv.org/abs/2305.03798),
[peak-friction estimation under sparse/noisy excitation](https://arxiv.org/abs/2603.09073),
[SAE tyre core/surface temperature study](https://saemobilus.sae.org/articles/influence-tire-core-surface-temperature-lateral-tire-characteristics-2014-01-0074), and
[SAE tyre temperature/pressure study](https://saemobilus.sae.org/papers/estimating-tire-pressure-based-different-tire-temperature-measurement-points-2024-01-5002).

## One-button alien pipeline (#529 P2 / #572 — plant-ID → optimized line → QSS → drive)

`auto_alien` composes the handshake and the drive into one command: it ensures the combo's
identified plant (running the handshake+ID session first when the artifact is missing, forced,
or lacks the uncertainty-aware friction fit), then drives the **min-curvature optimized line**
with the QSS min-time profile computed against that plant:

```bash
# Nothing pre-existing needed — identifies the plant if absent, then drives the optimized line:
python -m tools.ac_harness.auto_alien --car ks_porsche_911_gt3_r_2016 --track magione

# The drive stage alone (requires the plant artifact; builds/reuses the line cache):
python -m tools.ac_harness.auto_drive --car ks_porsche_911_gt3_r_2016 --track magione \
    --driver alien --wait-lap
```

- The optimized line + profile persist as a per-combo artifact under
  `<AC user data>/alien_line/<car>__<track>[__layout-…][__setup-…].json` — the **same identity
  stem as the plant artifact** (car+track+layout+setup content hash), plus two provenance gates:
  the exact plant-fit content hash and the `fast_lane.ai` content hash. A re-identified plant, a
  re-baked AI line, or changed build params rejects the cache and rebuilds; a stale line is never
  silently driven.
- The corridor (`sideLeft`/`sideRight` from the AiPointExtra block) is validated before the QP —
  a drifted binary layout fails loudly instead of producing an off-track "optimized" line — and
  the built profile is re-verified against the plant's lateral envelope.
- Stage failures abort the pipeline honestly (`alien_report.json` names the failed stage and its
  evidence bundle). There is no fallback to the stock line or the generic plant anywhere in the
  alien path; `--driver alien` without a usable plant exits with instructions, it never degrades.
- `--force-identify` re-runs identification; `--rebuild-line` (or `--alien-rebuild-line` on
  `auto_drive`) rebuilds the line cache from the current plant.

### Beyond-QSS per-corner refinement (#529 L3 / #582)

The QSS profile consumes the uncertainty-safe LCB grip (`mean − 1.96·std` per 10 km/h bin), which
the #577 runs proved binds the lap-time floor. `auto_alien` therefore enables **L3** on every
alien stage by default (`--no-l3` disables; on `auto_drive` it is the opt-in `--l3` flag): corners
of the optimized line whose speed range crosses **measured, low-variance** lateral bins get their
interior re-solved between QSS-pinned entry/exit speeds against grip relaxed toward the posterior
mean — never above the stability barrier `mean − 1.0·std`, never in prior-dominated bins, and
never silently: the artifact's `l3` report names every corner as `refined` (chosen z, relaxed
bins, predicted gain) or `reverted` (reason). The refined profile rides the same artifact,
provenance gates, and cache revalidation (a tampered refined profile fails the barrier re-check
and rebuilds); `--no-l3` artifacts are byte-identical to pre-#582 builds. Reality remains the
judge: the #577 keep-last-valid oracle falsifies a refined profile the car cannot hold.

### Evidence-gated setup scientist (#529 P4 / #654)

The optional scientist composes the self-play and setup-intelligence paths; it does not give model
text write access to setup files:

```bash
python -m tools.ac_harness.auto_alien \
  --car ks_porsche_911_gt3_r_2016 --track magione \
  --setup Copilot_Balanced_Fast --laps 3 --iterations 2 \
  --scientist --scientist-trigger pace_plateau
```

- `--scientist` requires a resolved baseline setup, at least one self-play iteration, and at least
  three timed laps per arm. The lowest `lap_n` in each arm is its out-lap and is excluded from the
  setup comparison, leaving at least two flying laps per arm for the uncertainty test. It starts
  only from the newest batch that passes the normal auto-alien validity oracle (timed, archived,
  AC-valid, zero recoveries).
- A proposal is at most three physical hypotheses. The deterministic planner validates bounded
  identifiers, a named mechanism, direction, current setup value, checked-in per-car spinner schema,
  range, step, and read-only status. Each experiment changes exactly one `SECTION.VALUE`. Optional
  `--scientist-proposals FILE` accepts a JSON array with `id`, `mechanism`, `parameter`, and
  `direction` (`-1` or `1`); unsafe prose/data fails the stage and retains its traceback in
  `alien_report.json`.
- Candidates are immutable new `.ini` files beside the baseline under AC Documents; the baseline is
  never overwritten. Each candidate goes through a nested normal auto-alien pipeline, including
  identification, line/profile verification, and the same lap-validity oracle.
- Promotion requires a single-parameter, unconfounded candidate batch that is faster with the
  setup optimizer's measured uncertainty test. If either arm has fewer than two flying laps after
  removing its out-lap, the run records an explicit `no_verdict` for audit but appends no durable
  promotion, falsification, or suppression row. Invalid, confounded, or inconclusive batches keep
  the previous setup. Only falsifications whose ledger rows prove at least two flying laps in both
  arms and the same verified safe grip margin can suppress a later retry; older under-evidenced
  rows stay untouched and are ignored. The
  report names the rejection and only a promoted result exposes
  `recommended_setup`.
- The candidate uses the baseline drive's recorded `ggv_scale`, including a validated ladder
  step, and its actual drive report must confirm the same margin before a verdict is recorded.
  Missing margin provenance refuses the experiment. A baseline above `1.0` also refuses it:
  the candidate's own identified plant has not validated that overspeed rung. Use a ladder
  capped at `--max-scale 1.0` for scientist experiments; the existing overspeed gate stays intact.
- Completed plan, outcomes, and verdict persist under
  `<AC user data>/journal/alien_scientist/runs/`; the append-only
  `journal/alien_scientist/experiments.jsonl` ledger suppresses a falsified constraint for the same
  mechanical platform, aero platform, tyre family, and track archetype. The four
  `--scientist-*-platform` flags override conservative car/track-derived scope identities when the
  operator has a better taxonomy.

The existing `--setup` launch caveats still apply: a candidate that cannot reach a complete measured
batch is an explicit scientist-stage failure, never a promotion or a plausible default.

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

### Overlay fast-fail (#466)

`_wait_live` reports LIVE the instant `acpmf_graphics.status==LIVE` with advancing physics — but AC
can sit at the NEW-UI "0 seconds" pre-drive overlay **with LIVE status and advancing physics** when
CM's auto-start race loses. LIVE but **not drivable**, and the carcsw hijack (CSP creating `Car0`) is
the only deterministic "session is actually drivable" signal. So the hijack is a sequence of **short
`--hijack-probe-seconds` probes** (default 5 s, recreating `CarControls0` each time to also beat the
early-LIVE race): a stalled overlay is detected in seconds, then the harness sends an authenticated
`session.start` request through the sidecar to the trainer Lua peer. Lua calls `ac.tryToStart`, and
the harness performs another bounded `Car0` probe even if the WebSocket acknowledgement is lost.
Only an unsuccessful relay/re-probe falls through to recycling a fresh launch. The per-cycle
`[auto-drive HH:MM:SS] …` log lines show each launch, probe outcome, relay result, and re-bake stats.

> **Verified in-sim (2026-07-03, #466/#482).** A keypress nudge to clear the overlay in place was
> implemented and tested — with AC correctly focused (foreground-lock defeated via `AttachThreadInput`)
> and receiving real Enter/Space, the CSP "0 seconds" overlay does **not** dismiss — so it was
> **removed**. That result rules out keyboard nudging; it does not supersede the authenticated
> `session.start` relay added by #726.
>
> **Correction (2026-07-29): `FORCE_START` does NOT skip this overlay — do not go and try it.**
> An earlier revision of this paragraph said "only the `FORCE_START` config skips it", which reads
> as a working lever and is wrong. The #466 investigation
> ([`issue-466-setup-drive-rebake-race-2026-07-03.md`](../01_Vault/AcCopilotTrainer/03_Investigations/issue-466-setup-drive-rebake-race-2026-07-03.md))
> measured `gui.ini [GUI] FORCE_START=1` failing **0/8+** across both the CM-launch and the
> direct-`acs`-relaunch paths, with `FORCE_START=1` confirmed present through acs startup and the
> setup applied (fuel=45) — overlay still stalled. #465 removed the mechanism for exactly that
> reason, and the repo-wide rule is **no `force_start` / `gui.ini` writes**. On this rig
> `gui.ini` currently reads `FORCE_START=0`; setting it to 1 is a refuted dead end, not a fix.
>
> The **no-setup drive path is reliable** (CM auto-starts; fast-fail retries land the hijack — e.g.
> LIVE and hijacked on cycle 1), **but it is not unconditional** — see the pre-drive-menu row in
> the troubleshooting table for the 2026-07-29 observation of it failing every cycle. The **`--setup` path is not yet reliable**, and instrumentation
> (`--setup-rebake-interval`, re-bake stats) pinned *why*: the overlay stall is the setup re-bake
> itself. The write that injects the setup into `race.ini` races acs's spawn-read that CM's
> immediate-start depends on — baking aggressively (0.05 s default) applies the setup but **breaks**
> the auto-start (overlay stall); baking gently preserves the auto-start but **misses** the setup. No
> cadence resolves it (sharp transition ~0.05→0.1 s), and a post-hijack `SimState` restart does not
> re-read the setup. A reliable `--setup` run needs a different injection mechanism (candidate:
> PIT-spawn + pre-hijack in-sim `setup.load` while `ac.isCarResetAllowed()` is true in the pit box) —
> tracked on #466. Until then a `--setup` run may stall at the overlay; a plain no-setup drive is
> reliable.

## Driving the harness from off-rig (the Windows session-0 trap)

An agent working from another host (macOS laptop, another Mac, CI) reaches the rig over SSH. **A
command run directly in that SSH session can never drive AC**, for two independent reasons — fix the
transport, not the harness:

1. **The app junction is untraversable from session 0.** An OpenSSH logon is a *network* logon and
   lands in Windows **session 0**, where the redirection-trust policy is enforced. `apps/lua/ac_copilot_trainer`
   is a junction created by a non-admin user, so session 0 refuses to follow it. The #575
   app-provenance preflight is the first code to touch it, so the run dies there:

   ```text
   OSError: [WinError 448] The path cannot be traversed because it contains an untrusted mount point:
     'C:\Program Files (x86)\Steam\steamapps\common\assettocorsa\apps\lua\ac_copilot_trainer'
     at auto_drive.app_install_provenance -> installed.is_dir()
   ```

2. **Session 0 has no interactive desktop.** AC renders on the console session. Even with traversal
   working, a session-0 launch could not produce a real drive.

> **Do not "fix" this by relaxing the provenance preflight or the junction.** The preflight is what
> catches a stale app (#543/#575); the junction is how the rig serves the checkout. Both are correct —
> the SSH session is the wrong place to run from.

### Confirm which session you are in

```powershell
(Get-Process -Id $PID).SessionId                 # SSH session reports 0
Get-Process explorer | Select-Object Id,SessionId # the console session (typically 1)
```

### Run in the console session: `tools.ac_harness.remote_launcher` (#697)

The transport is owned by a harness entrypoint — do **not** hand-run `schtasks` any more. PR #694
shipped this as a copy/paste runbook and five review rounds then found six real Windows defects in
it (`<`/`>` parsed as redirection inside the generated `.cmd`; a fixed `/st` that fails once local
time passes it; `/st` without `/sd` rolling to "earlier today" overnight; a space anywhere in the
path making Task Scheduler report `create=0`/`run=0` and then never launch; buffered Python leaving
the poll surface empty on a healthy run; an 8.3 `ShortPath` lookup that *fails open*). Every one of
those is now a guard that asserts its own precondition in
[`tools/ac_harness/remote_launcher.py`](../../tools/ac_harness/remote_launcher.py), with the pure
half unit-tested off-rig in `tests/test_ac_harness_remote_launcher.py`.

Start a run — everything after `--` is the harness argv, minus the interpreter:

```bash
python -m tools.ac_harness.remote_launcher start --label alien-529-911-magione -- \
    -m tools.ac_harness.auto_alien --car ks_porsche_911_gt3_r_2016 --track magione \
    --evidence-dir .scratch/harness-evidence/{run_id} \
    --laps 3 --ggv-scale 1.0 --scale-step 0.15 --iterations 4 --max-scale 1.2
```

`--iterations` counts **drives, not rungs**. Since [#703](https://github.com/agorokh/ac-copilot-trainer/issues/703)
the ladder alternates a **plant** step (refit from the last valid batch, ggv-scale held) with an
**envelope** step (next rung, plant untouched) so that a falsification names which knob it
falsified — and a falsified rung no longer discards a refit whose evidence was valid. Budget
**~2 iterations per rung**: reaching the second rung (1.2 here) when both refits land needs 4, not
2. With `--iterations 2` and successful refits you get one plant step at 1.0 and one envelope step
at 1.15, and the `--max-scale 1.2` cap is never probed. A plant step whose refit is a no-op falls
through to the rung, so a converged plant costs no extra drives.

It prints a JSON handle (`run_id`, `task`, `run_dir`) and returns immediately. Transport logs live
under `.scratch/harness-remote/<run id>/` (`stdout.log`, `stderr.log`, `run.json`) — deliberately
*beside* the harness's own `--evidence-dir` tree, which the harness keeps owning. The control file
and exit sentinel are **not** there; they live under
`%LOCALAPPDATA%\AC Copilot Trainer\Harness\remote\<run id>\` (one unbroken path — copy it whole).

Then live in `poll` (read-only — it never touches AC and never deletes the task), and reap at the
end:

```bash
python -m tools.ac_harness.remote_launcher poll <run id> --tail 40
python -m tools.ac_harness.remote_launcher wait <run id> --timeout-s 10800
python -m tools.ac_harness.remote_launcher cleanup <run id>
python -m tools.ac_harness.remote_launcher list        # report tasks a dead session left behind
python -m tools.ac_harness.remote_launcher reap        # ...and actually delete them
```

`poll` reports the task `Status`/`Last Result`, whether the wrapper has written its exit sentinel,
`acs.exe` liveness, the current **rig-lock owner** (arbitration stays in `rig_lock` — the launcher
does not duplicate it), and tails of both streams. `start --wait-timeout-s <s>` composes start +
bounded wait + cleanup in one call for an unattended run.

Behaviours worth knowing before you debug something:

- **It refuses to run in the console session.** There the task hop is pure overhead, so run the
  harness directly. It also fails loudly when nobody is logged on at the rig, because a `/IT` task
  can never run then and AC has no desktop to render on.
- **`cleanup` refuses an unfinished run** (use `--force` only deliberately). `schtasks /run` is
  asynchronous: deleting the task definition early can cancel a start that has not spawned yet, and
  it removes the only `Status` handle while the run is still launching. The exit sentinel
  (`[wrapper] exit=<rc>` in `wrapper.log`), not `Status: Ready`, is what says a run finished.
- **The `/sc once` trigger really fires** — earlier runbook text claimed it never does, which only
  held for runs *longer* than the start delay. `/create` insists on a start time and Task Scheduler
  honours it, so a run that finished first would be executed a second time. The trigger is therefore
  **disabled immediately after `/run`** succeeds; a running instance is unaffected. This is done in
  the scheduler rather than with a marker file, because every marker lives somewhere a peer agent
  can write.
- **Nothing peer-writable is ever executed.** `/tr` points at the repo's own interpreter running the
  version-controlled `tools/ac_harness/_remote_exec.py`, not at a generated script in `.scratch`.
  That shim reads a control file, **re-validates every argv token**, recomputes the interpreter, cwd,
  log paths and sentinel from the validated run id, and spawns with `shell=False`. The control file
  and exit sentinel live beside the rig lock under `%LOCALAPPDATA%`, not in the shared scratch tree.
  *Residual, stated plainly:* every agent on this rig runs as the same Windows account, so no
  filesystem location is beyond a peer's reach — this removes command **injection** and makes
  tampering fail closed, it does not create isolation.
- **Task names are per-run** (`ac-harness-<label>-<stamp>-<pid>-<nonce>`). The threat model is two
  agents on the one physical rig: a fixed name lets each clobber the other's registration.
- **`wait` is bounded.** If the run never starts, the sentinel never appears; an unbounded wait
  would hang for hours with no diagnosis.
- **`cleanup` and `reap` share one deletion rule, and it is the strict one.** A task is deleted
  only when *all three* hold: its run wrote the **exit sentinel**; the task reports a known non-live
  status; and `Last Result` shows it has actually executed. `Status: Ready` is *not* completion —
  `/run` is asynchronous, so `Ready` covers both the pre-spawn window and the finished state, which
  is why the result code is checked too (a sentinel planted in the writable scratch tree would
  otherwise authorise deleting a peer's task before it ever ran). Anything unreadable **fails
  closed**, with the reason reported; `--force` overrides. `cleanup` exits non-zero when it refuses
  or the delete fails, so automation can see it.
- **Correlate payload with transport.** `{run_id}` and `{run_dir}` in the harness argv are
  substituted before validation, so `--evidence-dir .scratch/harness-evidence/{run_id}` makes the
  in-sim evidence share the transport's run id. The wrapper also exports
  `AC_HARNESS_REMOTE_RUN_ID`.
- **The run id you pass is authoritative.** `run.json` lives in a writable scratch tree, so
  `poll` / `wait` / `cleanup` bind the payload to the run id you asked for and **recompute** its
  directory; a forged or stale payload cannot redirect `cleanup` onto a peer's task. (There is no
  `load` subcommand — that binding happens inside every command that takes a run id.)

You landed in the right session when the run's own first lines report the provenance gate passing:

```text
auto-drive: installed app provenance: match
auto-drive: preflight ok
auto-drive: rig lock acquired -> ...\AC Copilot Trainer\Harness\rig-session.lock
```

`installed app provenance: match` is the machine-checkable signal — it means the junction was
traversed *and* the served tree matches the checkout the harness is running from.

### Pre-run rig invariants (check these before starting a remote run)

- **The AC app junction serves the primary checkout**, which must sit at the merged `main` tip
  (#575/#543 — a stale checkout serves stale Lua and the run fails in confusing ways).
- **`main` may be checked out by another worktree**, in which case `git switch main` fails with
  `fatal: 'main' is already used by worktree at …`. Detach instead — `git switch --detach origin/main`
  — which leaves every branch ref and peer worktree untouched.
- **One rig, one session.** The harness takes a cross-worktree lock at
  `%LOCALAPPDATA%\AC Copilot Trainer\Harness\rig-session.lock`; check for a live `acs.exe` or a peer
  sidecar before starting, and let the lock arbitrate rather than killing processes.

## Troubleshooting (hard-won rig lore — read before debugging)

| Symptom | Cause / fix |
|---|---|
| Preflight `car_data` / `car_lods` / `car_lod_file` failure | The selected car is locally damaged even if its folder and some `.kn5` models remain. For a stock/Kunos car, use Steam **Assetto Corsa > Properties > Installed Files > Verify integrity**; for a mod, reinstall its original package through Content Manager. Do not borrow another car's `data.acd` (the archive key depends on the folder name). Re-run `python -m tools.ac_harness.auto_drive --car <id> --track <id> --preflight-only`; it must report `preflight ok` before a matrix drive. |
| Preflight `custom_ai` failure | Set `[CUSTOM_AI] ENABLED=1` in `<AC root>/extension/config/new_behaviour.ini` (user `cfg/extension/new_behaviour.ini` overrides when it carries the key) |
| `stage=setup`, `applied=False`, fuel mismatch | The launch bake didn't take — check `race.ini [CAR_0] _EXT_SETUP_FILENAME` points at the setup and the CM launch reached LIVE; the setup's `[FUEL] VALUE` is the expected number |
| `--setup` run: setup `applied=True` but `stage=hijack` | The setup is applied/verified, but AC remained at the rendering "0 seconds" pre-drive menu. The harness now requests `session.start` through the authenticated sidecar→Lua control path and performs a bounded `Car0` re-probe before recycling. Check the log for `session.start`: `no authenticated loopback Lua peer connected` means the trainer app/bridge is absent or on the wrong endpoint; `skipped` identifies a missing WebSocket extra or invalid port; a negative/timeout result means Lua did not confirm `ac.tryToStart`. On CSP 0.2.11 verify `[NEW_UI] REPLACE_MAIN_MENU=0`, and use the default sidecar port `8765` for Stable AC. If the relay is healthy but `max_launches` still exhausts, record the denominator and relay evidence on #627. **Do not borrow the #627 freeze-accumulator reboot advice for this rendering/menu-park shape.** |
| CM clicks/launch do nothing | **Foreground steal**: minimize the agent/terminal window; AC's fullscreen menu covers CM — the harness kills stale `acs.exe` before each launch |
| "Steam API failed to initialize" | Steam elevation mismatch — restart Steam **non-elevated** (`steam -shutdown`, relaunch via `explorer.exe`) |
| `setup.load` error "no loopback Lua peer connected" | The trainer app isn't (yet) connected to the sidecar — the harness retries for `setup_timeout`; persistent = app not installed/enabled in CSP |
| Run FAILS with `recovery cap exceeded at <N>m` | Real stall: the car repeatedly stopped at the same spot. Inspect `hud.png` plus `report.drive.control_trace` (especially the forced `recovery:*` rows); do **not** raise the cap to make it "pass" |
| `acs.exe` dies mid-drive | The main physics packet watchdog fails that attempt and the CLI automatically runs one fresh full launch (bounded by `--sim-death-retries`). Inspect `report.attempts`: every failed attempt, reason, and control trace is retained even when the final attempt passes. |
| `OSError: [WinError 448] … untrusted mount point` on the app junction | You are running in Windows **session 0** (an SSH logon), which cannot traverse the user-created junction and has no desktop for AC to render on. Not a harness bug and **not** a reason to relax the provenance preflight — re-run through `python -m tools.ac_harness.remote_launcher start` (see *Driving the harness from off-rig*) |
| `stage=hijack` on EVERY cycle, and `resilient_launch` reports `not_drivable` (before 2026-07-29: `froze`) | AC reached LIVE and is **rendering normally** but parked at AC's pre-drive session menu (Drive/Setup/Exit sidebar, "Practice — 0 seconds"), so CSP never exposes `Car0`. **This is the historical #466 shape, NOT the #627 render wedge** — a wedge pins `acpmf_graphics.packetId`; a menu park keeps it advancing. The current recovery is the authenticated `session.start` relay followed by a bounded `Car0` re-probe, not blind relaunch alone. First verify Game Point accepted the prerequisites: CSP 0.2.11 needs `[NEW_UI] REPLACE_MAIN_MENU=0`, and Stable AC requires `sidecar_port=8765` (`menu_config_required` and `sidecar_port_unsupported` are actionable preflight failures). Then inspect the harness/sidecar log: the Lua peer must connect as `client_class=lua`; `no authenticated loopback Lua peer connected`, a negative ack, a timeout, or a WebSocket-extra/port `skipped` message identifies which relay stage failed. A lost positive ack is safe because the harness still re-probes `Car0`. `FORCE_START`, `[TWEAKS] USE_THROTTLE_TO_START`, keyboard nudging, and rebooting are refuted or unrelated dead ends for this rendering shape. If the authenticated relay is healthy but all bounded attempts still miss `Car0`, record the launch denominator plus relay/re-probe evidence on **#627**; #466 is closed. |
| CM launch silently does nothing — `acs.exe` never appears, yet a reader still sees `status=LIVE` with static packets | The `acmanager://` URL is IPC to an already-running CM (trap §7.7) and a CM in a stale/cached-session state ignores it. What you are reading is a **corpse**: `acpmf_*` outlives `acs.exe` — measured 2026-07-29 holding `status=LIVE` with both packets frozen for **74 s** after exit, far longer than the ~14 s in #628. Never trust any `acpmf` field until the packet id **advances**. Recovery: cold-restart CM (kill `Content Manager.exe`, relaunch, wait ~12 s for single-instance IPC) before re-firing the URL |
| Two agents, one rig | **Yield**: a single AC instance cannot serve two autonomous sessions (see the issue-277 investigation). Check for a running `acs.exe`/peer sidecar before launching |
| Sidecar port already in use | That's usually the Game Point launcher's supervised sidecar — the harness reuses it; don't spawn a second |

## Independent bounded-run guardian (#815)

For an operator-owned acceptance run, arm `tools.ac_harness.rig_watchdog` before enabling
AI driving. The guardian is a separate Windows process with a fixed, nonrenewable deadline:
600 seconds by default and at most 600 seconds. It does not depend on an agent heartbeat,
UI polling, or the launching command remaining alive. This is an explicit harness step;
ordinary Game Point launches do not automatically arm it.

Keep the canonical rig-lock owner running. Read the exact identity of the AC process that
owner launched, using its known PID (never choose a process by image name). `inspect` is
read-only and returns the PID, executable path, and integer creation FILETIME in 100 ns ticks.
Do not convert that creation value through a floating-point timestamp. With an existing,
owned run directory and the two verified PIDs, the PowerShell sequence is:

```powershell
$ownedAc = python -m tools.ac_harness.rig_watchdog inspect --pid $ownedAcPid | ConvertFrom-Json
python -m tools.ac_harness.remote_launcher start --label bounded-voice -- -m tools.ac_harness.rig_watchdog scheduled-run --owner-pid $rigOwnerPid --run-dir $runDir --ac-pid $ownedAc.pid --ac-created-filetime $ownedAc.created_filetime --ac-exe $ownedAc.exe --max-runtime-s 600
```

The remote launcher returns its exact task/run identity and disables the one-shot trigger.
Before enabling driving, require `watchdog/armed.json` with `status=armed`, the matching
`lifetime_basis.run_id`, a future monotonic deadline, and no final receipt. Starting a task
alone is not arming. A failed or unconfirmed start means driving must remain disabled.
The receipt is published only after exact process handles and canonical ownership have been
verified; its deadline has already started. A later UI or capture failure does not cancel it.
The run directory must not already contain a `watchdog` directory: restarting cannot reset
the timer.

This is the one supported same-console exception in the remote launcher, limited to
`rig_watchdog scheduled-run`. The guardian is the task's action process, directly parented
by the running Windows Schedule service. It verifies that parent PID, its exact canonical
action/arguments, single unelevated interactive principal, and task execution limit before
arming. The task has a fixed 660-second execution limit; the ordinary driving deadline stays
at most 600 seconds. No credentials, elevation, or machine policy changes are requested.
The receipt calls this `task_scheduler_owned_job`: it is independent of the agent's job,
not outside every Windows Job. Direct `rig_watchdog start` remains available only from a
host where detached breakaway and absence of a remaining Job can actually be proved.

At the deadline the guardian posts `WM_CLOSE` only to windows belonging to the retained AC
process. It gives healthy AC up to 15 seconds to close, then uses `TerminateProcess` on that
same retained handle and waits at most another 5 seconds. It never targets an image name,
a process tree, the owner, or unlisted peers. Optional explicit `--sidecar-pid`,
`--sidecar-created-filetime`, `--sidecar-exe`, and `--sidecar-stop-file` bind the instrumented
sidecar to the same cleanup. The fresh stop path must be directly inside the run directory;
its graceful wait runs concurrently with AC's, followed by the same bounded handle fallback.
Normal AC exit triggers sidecar cleanup immediately.

If the original owner process exits after arming, the guardian immediately attempts a
zero-timeout acquisition of the now-idle canonical lock. This grants only cleanup of the
already pinned targets. It holds that lock through shutdown and handle release so a new
owner cannot adopt the process midway through cleanup. An active replacement owner, a race
lost acquiring the lock, a living owner releasing its lock, or an identity mismatch blocks
actuation and produces an explicit failed receipt requiring operator intervention. The
guardian never rediscovers or follows a replacement process.

`watchdog/events.jsonl`, `watchdog/receipt.json`, and the remote launcher's per-run logs retain
arming, deadline, ownership takeover, graceful/forced shutdown, and failure evidence. Keep
the scheduled task until the guardian writes its final receipt and the wrapper writes its
exit sentinel. Use `remote_launcher cleanup <run_id>` without `--force`; its existing
sentinel/status/result checks refuse to delete a running guardian. Check the final receipt;
an old arm receipt alone does not establish a currently protected run.

The native disposable-fixture proof rejected the agent's nested kill-on-close jobs and a
Task Scheduler child breakaway attempt. The task-owned implementation then stopped only
the pinned sleeping fixture after a two-second deadline, preserved its same-name peer,
retained canonical owner 51316, and passed checked task cleanup. These are synthetic native
process-lifecycle results, not driving or audible acceptance. Focused tests also cover
owner-death takeover, takeover races, PID reuse, shutdown failures, and live-task retention.

## Live voice acceptance capture (#815)

`tools.ac_harness.live_voice` opens the **existing Game Point UI** with its normal
`GamePointConfig`, `GamePointSupervisor`, and sidecar arguments. The only sidecar substitution
is `python -B -m tools.ai_sidecar.voice.instrumented_sidecar`: it runs the ordinary
`tools.ai_sidecar` entrypoint with diagnostic taps around the actual producer, resolver,
scheduler, and dispatch. It does not generate coaching cues, launch AC automatically, or
activate AI. This source-checkout harness is not a separate packaged product launcher.

An already-running canonical rig-lock owner must authorize the run. Supply that owner's
positive PID; the helper verifies it before creating files and on Game Point preflight. It
never reacquires or bypasses the lock. The new `--run-dir` must not exist and must be independent
of the production Game Point root. The helper copies the effective production configuration
into `<run>/GamePoint/settings.json`, preserving other settings and inherited environment
entries, including secrets only in the environment. Production settings are never written.
Run overrides pin the reference, bank, output endpoint and channel map, turn TTS and SimHub
autostart off, and select `producer_mode` (`coach_v2`, the default, or `observer`). Observer mode
rejects an inherited `alien_line`, because the production launcher would force Coach v2 for it.

Prepare a private JSON configuration using absolute paths and exact enumerated endpoint names.
This example is a shape, not a calibrated rig preset; substitute measured values and valid
inputs. Neither channel 5 nor 48 kHz is assumed to be correct for another endpoint.

```json
{
  "producer_mode": "coach_v2",
  "reference_archive": "C:/owned/reference.json",
  "bank_dir": "C:/owned/voice-bank",
  "attribution_ledger": "C:/owned/lap-attributions.jsonl",
  "car_id": "ks_porsche_911_gt3_r_2016",
  "track_id": "spa",
  "layout": null,
  "track_length_m": 7004.0,
  "seconds": 180,
  "sidecar_url": "ws://127.0.0.1:8765",
  "http_url": "http://127.0.0.1:8765",
  "output_device": "EXACT PortAudio output name",
  "output_host_api": "Windows WASAPI",
  "output_channel_map": [5],
  "microphone": {
    "name": "EXACT PortAudio microphone name",
    "host_api": "Windows WASAPI",
    "channels": 2,
    "samplerate": 48000,
    "analysis_channel": 0
  },
  "loopback": {
    "speaker_name": "EXACT SoundCard speaker name",
    "samplerate": 48000
  },
  "protected_files": []
}
```

`reference_archive`, `bank_dir`, and the explicit nonempty output route are required by the
launcher. `output_channel_map` is one-based and follows the normal voice configuration guards.
The recorder additionally requires the ledger, exact combo, positive measured track length,
physical microphone specification, and explicit credential-free loopback WS/HTTP URLs matching
the sidecar's port. `seconds` must be finite in `[5,600]`; budget startup, two chirps, and teardown
inside the guardian deadline rather than setting both durations to 600. Input `instrument_tap`
is replaced with the owned `<run>/sidecar-tap.jsonl` in `<run>/capture-config.json`. The selected
reference must pass existing live-reference qualification. If the production sidecar uses an
attribution-ledger override, it must designate this same ledger. `protected_files` adds immutable
input receipts. Do not put tokens in JSON or URLs.

The rig needs the normal voice/sidecar dependencies (`numpy`, `sounddevice`, `websockets`) plus
`psutil` for listener identity; optional WASAPI loopback uses `soundcard`. Loopback may be omitted
for diagnostics, but the analyzer then cannot pass its digital-output proof gate. An optional
`loopback.speaker_id` disambiguates speakers sharing a name. `microphone.analysis_channel` is
zero-based. Endpoint matching must be unique; backend/import/capture failures remain failures.
The recorder emits real calibration chirps and opens recording devices; `analyze` is offline.

With driving disabled, run this from the source checkout in the owning desktop session:

```powershell
python -m tools.ac_harness.live_voice --run-dir "$runDir" --capture-config "$captureConfig" --owner-pid $rigOwnerPid --start-sidecar
```

This command owns the canonical UI until it closes. In another terminal, check
`<run>/launcher-receipt.json`, the instrumented sidecar's health and tap PID, and arm the guardian
from the preceding section **before AI driving**. Include the owned sidecar identity and its
stop file so the independent deadline also stops capture instrumentation:

```powershell
$tapStart = Get-Content -LiteralPath "$runDir/sidecar-tap.jsonl" -TotalCount 1 | ConvertFrom-Json
$ownedSidecar = python -m tools.ac_harness.rig_watchdog inspect --pid $tapStart.pid | ConvertFrom-Json
$ownedAc = python -m tools.ac_harness.rig_watchdog inspect --pid $ownedAcPid | ConvertFrom-Json
python -m tools.ac_harness.remote_launcher start --label live-voice -- -m tools.ac_harness.rig_watchdog scheduled-run --owner-pid $rigOwnerPid --run-dir "$runDir" --ac-pid $ownedAc.pid --ac-created-filetime $ownedAc.created_filetime --ac-exe $ownedAc.exe --sidecar-pid $ownedSidecar.pid --sidecar-created-filetime $ownedSidecar.created_filetime --sidecar-exe $ownedSidecar.exe --sidecar-stop-file "$runDir/sidecar.stop" --max-runtime-s 600
```

Require the matching fresh `watchdog/armed.json` and future deadline as described above. A
successful launcher call or healthy voice endpoint alone is insufficient. AI remains an
explicit action through the existing rig controls; neither capture command enables it. Use a
fresh capture directory for every recording:

```powershell
python -m tools.ai_sidecar.voice.live_acceptance record --config "$runDir/capture-config.json" --out "$runDir/capture" --owner-pid $rigOwnerPid
```

After recording finishes, stop driving and close the owned sidecar through Game Point (or let
the guardian reach its fixed deadline). The stop request writes only the fresh owned
`sidecar.stop`; the wrapper delivers SIGINT on the actual server loop so its normal cleanup
flushes `tap_end`. A timeout is reported and falls back to the supervisor's existing cleanup
of its own child. A peer sidecar is never signalled: `--start-sidecar` refuses an adopted peer
as an instrumented capture. Reusing a run/tap/stop path is rejected; start a fresh run instead.
Then analyze, after verifying the tap footer and guardian cleanup receipts:

```powershell
python -m tools.ai_sidecar.voice.live_acceptance analyze --capture "$runDir/capture" --out "$runDir/analysis.json"
```

### Composing the capture with the autonomous driver (off-rig)

When `auto_drive` drives instead of a human or MOZA AI, one holder owns the rig for the whole
run. The capture, guardian and driver all bind to that owner. Each step runs in the console
session through `remote_launcher start --label <name> -- <argv>`:

1. `-m tools.ac_harness.rig_lock hold --stop-file <run>/rig-owner.stop --max-hold-s 3600
   --car <car> --track <track>` takes the canonical lock. Its stdout `held` line names the
   owner PID. The stop path must not exist yet, and the hold ends at the stop file or its
   fixed bound.
2. `-m tools.ac_harness.live_voice --run-dir <run> --capture-config <cfg> --owner-pid <owner>
   --start-sidecar` opens Game Point with the instrumented sidecar.
3. `-m tools.ac_harness.auto_drive … --rig-owner-pid <owner> --no-sidecar-autostart` verifies
   that owner instead of acquiring the lock, and reuses the listening instrumented sidecar.
   Every launch and sim-death relaunch re-verifies the owner first. A lost owner refuses
   the launch. A peer that takes a released rig replaces AC, which ends the drive as sim-death.
4. As soon as `acs.exe` exists, arm the guardian with the same owner and the AC and sidecar
   identities. The driver drives right after launch and hijack. Record this short unguarded
   window rather than claiming the guardian preceded motion.
5. Run `live_acceptance record --owner-pid <owner>`, then close Game Point and write the stop
   file to release the rig.

The analyzer locates both microphone chirps inside their sweep band. Room reverberation caps
a microphone chirp's normalized correlation below the near-field 0.20 floor, so an acoustic
anchor is accepted at score ≥ 0.10 with prominence ≥ 10. Anchors qualify the timebase only
when their slope agrees with the independently fitted monotonic callback clock. PortAudio's
WASAPI `inputBufferAdcTime` is the callback stream time plus a whole-buffer estimate, not a
hardware clock. Its steps are reported as `adc_time_diagnostic` but are not fitted.

The tap records exact advisory/utterance identities, producer timestamps, scheduler drops,
actual output mapping, source hashes, and any writer loss. Captures retain microphone WAV,
separate digital loopback WAV, wire events, and immutable-input receipts. Keep them private in
ignored run storage; do not commit recordings or personal lap data. A completed recording is
not an acceptance pass. Missing cues, source changes, lost tap rows, incomplete clocks or audio,
and insufficient timing evidence remain explicit failed gates. Anticipatory coverage counts
submitted brake targets, including scheduler drops; non-emitting eligible opportunities remain
`NOT_ESTABLISHED`. Reactive SAVE cues cannot establish anticipatory brake timing. Acoustic
waveform evidence does not establish human intelligibility, reference expertise, or permission
to teach from an unproved reference. Offline parity tests are synthetic engineering evidence;
physical rig/audio acceptance still requires the bounded measured run.

## Trusting the harness — the false-green KPI (EPIC #154 Part G)

A harness is only worth its PASS if that PASS is *honest*. The ADR bar is **false-green rate vs
human reality < 5%** — a false green is the harness reporting the pipeline healthy when a human at
the wheel would see it broken. Two arms measure it:

- **Live arm (rig-gated):** the `self_test` / `auto_drive` run itself, live-verified with no human
  at the wheel — the ground truth against real physics.
- **CI arm (off-sim, deterministic):** `python -m tools.ac_harness.false_green_kpi` — a shadow-mode
  report that runs a **labeled corpus** of the real failure classes tied to historical bugs
  (#170 missing peer, #180 tire-temps, #182 lap-before-session, #191 lap-timeout, #459/#460
  sim-death, schema-gate, HUD blank/frozen, envelope spoof, **report-path swallowing**) through the
  **real** production oracles (`evaluate_sequence`, `load_schema`, `PhysicsStallDetector`,
  `liveness_score`, and the full `run_self_test` report path). It prints per-class results and
  `false_green_rate`, exits non-zero if any broken class leaks (`--json OUT` for the full report).
  It is honest about its boundary: an `out_of_scope` list names the human-perceptible classes it
  cannot see (semantic coaching validity, audio, render correctness, long-run perf, persistence) —
  those stay the live arm's job.

**Fold real failures into the corpus.** When a live drive surfaces a false green, dump the WS tap to
JSONL and load it with `sequence_probe.frames_from_jsonl(path)` as a new corpus scenario — that
anchors the CI arm to observed reality and turns every escape into a permanent regression guard.

## Layers underneath (when you need less than the full loop)

`auto_drive` composes the primitives; they remain individually usable:
`entry_launcher` (launch only) · `custom_ai` (carcsw actuation) · `sequence_probe` (WS assert
only, `--skip-launch` style) · `hud_capture` (render liveness) · `self_test` (producer contract
without motion) · `false_green_kpi` (off-sim discrimination KPI) · `daemon` (persistent rig service
with `/session/start`).
Architecture decision record: vault `01_Decisions/autonomous-self-test-harness.md`.
