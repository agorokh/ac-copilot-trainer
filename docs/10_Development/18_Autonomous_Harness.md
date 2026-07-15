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
| `report.json` | Final `AutoDriveReport` plus full `attempts` history (a recovered sim death remains measurable), combo/setup ack, drive stats incl. `recoveries`/`spawn_teleport` and bounded `control_trace`, WS frame counts, preset/sidecar provenance, HUD verdict, and lap-archive paths |
| `generated.cmpreset` | The exact preset launched (when generated) |
| `hud.png` | Post-run HUD capture (`--hud-region full|left|coaching`) with liveness verdict |
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
early-LIVE race): a stalled overlay is detected in seconds and the run **recycles a fresh launch**
instead of burning one long dead-wait. The per-cycle `[auto-drive HH:MM:SS] …` log lines show each
launch, probe outcome, and re-bake stats so a recycle's timing is visible.

> **Verified in-sim (2026-07-03, #466/#482).** A keypress nudge to clear the overlay in place was
> implemented and tested — with AC correctly focused (foreground-lock defeated via `AttachThreadInput`)
> and receiving real Enter/Space, the CSP "0 seconds" overlay does **not** dismiss (consistent with
> #465: only the `FORCE_START` config skips it, no keypress) — so it was **removed**; the fast-fail
> relaunch is the recovery. The
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
| `--setup` run: setup `applied=True` but `stage=hijack` | The car stalled at AC's non-hijackable "0 seconds" overlay through every launch cycle (the setup re-bake breaks CM's immediate-start, #466). The setup is applied/verified. The harness fast-fails each stalled cycle and **recycles a fresh launch**; if it still exhausts `max_launches`, reboot the rig (degraded from many hard `acs.exe` kills) and rerun. (A keypress nudge to clear the overlay was tried in-sim and verified NOT to dismiss it, #466 — the relaunch is the only recovery.) |
| CM clicks/launch do nothing | **Foreground steal**: minimize the agent/terminal window; AC's fullscreen menu covers CM — the harness kills stale `acs.exe` before each launch |
| "Steam API failed to initialize" | Steam elevation mismatch — restart Steam **non-elevated** (`steam -shutdown`, relaunch via `explorer.exe`) |
| `setup.load` error "no loopback Lua peer connected" | The trainer app isn't (yet) connected to the sidecar — the harness retries for `setup_timeout`; persistent = app not installed/enabled in CSP |
| Run FAILS with `recovery cap exceeded at <N>m` | Real stall: the car repeatedly stopped at the same spot. Inspect `hud.png` plus `report.drive.control_trace` (especially the forced `recovery:*` rows); do **not** raise the cap to make it "pass" |
| `acs.exe` dies mid-drive | The main physics packet watchdog fails that attempt and the CLI automatically runs one fresh full launch (bounded by `--sim-death-retries`). Inspect `report.attempts`: every failed attempt, reason, and control trace is retained even when the final attempt passes. |
| Two agents, one rig | **Yield**: a single AC instance cannot serve two autonomous sessions (see the issue-277 investigation). Check for a running `acs.exe`/peer sidecar before launching |
| Sidecar port already in use | That's usually the Game Point launcher's supervised sidecar — the harness reuses it; don't spawn a second |

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
