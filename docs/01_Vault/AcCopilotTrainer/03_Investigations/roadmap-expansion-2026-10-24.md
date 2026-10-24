---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-24
updated: 2026-10-24
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/03_Investigations/issue-529-g1-mclaren-magione-2026-10-16.md
  - AcCopilotTrainer/03_Investigations/issue-746-749-repeatability-and-thermal-gate-2026-08-10.md
  - AcCopilotTrainer/03_Investigations/issue-854-agent-observed-acceptance-2026-10-17.md
---

# Roadmap Expansion Investigation & Decision Slate (`2026-10-24`)

- **Repository:** `agorokh/ac-copilot-trainer` (base `HEAD` `c5d1948b37ed3ff5060d882c202698168cdfef5c`)
- **Umbrella / Tracker:** [#401](https://github.com/agorokh/ac-copilot-trainer/issues/401) ([summary comment](https://github.com/agorokh/ac-copilot-trainer/issues/401#issuecomment-6388404529)), [#529](https://github.com/agorokh/ac-copilot-trainer/issues/529) ([G1/G3 test comment](https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388379995)), [#938](https://github.com/agorokh/ac-copilot-trainer/issues/938) (new issue for `REX-20261024-02`)
- **Council Qualification Cap:** `explore` (`provisional` council coverage: 2 of 5 model families active in session — OpenAI `gpt:chatgpt_ask` and Mistral `mistral:mistral_second_opinion` completed independent locked Pass 1 + Pass 2 Source Checker adjudication; Google `gemini:gemini_second_opinion` failed web-cookie authentication with `guest_session`, and `perplexity`, `kimi`, `grok` MCP servers were not mounted in this host environment).

---

## 1. Grounded Code & Vault Evidence Records (`E-001` .. `E-012`)

```yaml
- id: E-001
  claim: "Issue #529 Gate G1 (Cold-start alien pace) is blocked on McLaren MP4-12C GT3 @ Magione: QSS predicts 91.94 s and driven baseline is 97.378 s vs Track Titan P10 target <= 74.784 s; self-play iter1 (ggv_scale=1.0) yields 97.427 s (adopting only 1 lateral bin and reverting all 7 corners in corner_refine.py), and iter2 (global ggv_scale=1.15) crashes at 2906 m (recovery cap 6 exceeded)."
  source_kind: repo_file
  locator: "docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-529-g1-mclaren-magione-2026-10-16.md#L1-L95"
  date: "2026-10-16"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-01]
  notes: "Verified live rig run artifact on #529."

- id: E-002
  claim: "In tools/ac_harness/ggv_profile.py (lines 1362-1391), ggv_from_lap_archives empties thermal_probe_rows = [] whenever thermal_fit_mode == 'cold_side_temperature_tagged' OR complete_run_cohort is False (len(selected) != len(archives)). Because with_binned_uncertainty (lines 588-651) only marks brake and drive bins 'observed' from source == 'brake_probe'/'accel_sweep' rows, and merge_selfplay_model (lines 712-762) only updates lateral bins, all 30 longitudinal braking and acceleration bins remain permanently on the 70.6%-derated prior (safe_g = mean * (1 - 1.96 * 0.15)) across both cold-start and self-play."
  source_kind: repo_file
  locator: "tools/ac_harness/ggv_profile.py#L588-L762,L1362-L1391"
  date: "2026-10-24"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-01]
  notes: "Primary root cause of longitudinal bin starvation in #529 G1."

- id: E-003
  claim: "In tools/ac_harness/ggv_profile.py (line 643), passive cornering samples only mark a lateral bin 'observed' if _pct(lateral, 0.95) >= 0.9 g. Because the base QSS profile drives at the 70.6%-derated lateral prior (~0.847 g on a 1.2 g prior), passive cornering cannot clear 0.9 g, starving corner_refine.py:149-156 (which requires source == 'measured')."
  source_kind: repo_file
  locator: "tools/ac_harness/ggv_profile.py#L636-L655; tools/ac_harness/corner_refine.py#L149-L156"
  date: "2026-10-24"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-01]
  notes: "Explains the chicken-and-egg self-play deadlock on iter1."

- id: E-004
  claim: "Cold-side thermal tagging (#746/#749) was introduced because mixing cold out-lap telemetry with warmed flying laps contaminated GGV fits across runs; therefore reverting thermal_fit_mode to 'full_run' or forcing complete_run_cohort=True would re-introduce cross-thermal contamination."
  source_kind: repo_file
  locator: "docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-746-749-repeatability-and-thermal-gate-2026-08-10.md#L1-L85"
  date: "2026-08-10"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-01]
  notes: "Refutes Pass 1B's mundane substitute of forcing complete_run_cohort=True."

- id: E-005
  claim: "tools/ai_sidecar/coaching_runtime.py hardcodes _GRIP_CEILING_G = 1.55 and _GRIP_GATE_FRAC = 0.95 (lines 72-73). In _normalize (lines 635-638), grip is computed as abs(lat_g) / 1.55 (ignoring long_g, combo GGVModel, tyre_temps_c, brake_temps_c, and trackGripLevel), and _finalize_pass (line 431) only suppresses EARLY_BRAKE / SLOW_APEX when max_grip_used >= 0.95 (1.4725 g) at corner exit, never suppressing an already-armed PRIME cue in observe() (lines 366-373)."
  source_kind: repo_file
  locator: "tools/ai_sidecar/coaching_runtime.py#L72-L73,L366-L373,L431-L433,L635-L638"
  date: "2026-10-24"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-02]
  notes: "Causes false-positive 'Brake later / Carry more speed' cues on street cars (BMW E30 ~1.05 g) and cold/overheated tyres."

- id: E-006
  claim: "tools/ai_sidecar/tyre_model.py (lines 34-67, 129-140) and tools/ai_sidecar/conditions_model.py (lines 10-19, 61-75) already implement red-team-verified thermal window classification (cold < 40 C, warming, in_window centered on wheel.tyreOptimumTemperature from #488, overheat, critical) and dry/wet regime + trackGripLevel normalization, while tools/ai_sidecar/telemetry_source.py (lines 97-107, 176-185) omits tyre_temps_c and brake_temps_c on replay/shared-memory telemetry_tick frames."
  source_kind: repo_file
  locator: "tools/ai_sidecar/tyre_model.py#L34-L140; tools/ai_sidecar/conditions_model.py#L10-L75; tools/ai_sidecar/telemetry_source.py#L97-L185"
  date: "2026-10-24"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-02]
  notes: "Existing repo assets ready to wire into CoachRuntime and telemetry_source."

- id: E-007
  claim: "Roadmap #401 Vertical 5 explicitly states that wet/cold strategy coaching and brake-temp management logic remain shallow and unowned."
  source_kind: issue_or_pr
  locator: "https://github.com/agorokh/ac-copilot-trainer/issues/401; docs/01_Vault/AcCopilotTrainer/00_System/Roadmap.md#L44"
  date: "2026-10-22"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-02]
  notes: "Confirms Card 2 fills an unowned roadmap gap."

- id: E-008
  claim: "tools/ai_sidecar/coachable_frontier.py (lines 27-90) only steps min_speed_kmh (+2/+4/+6 km/h by skill level) on the human reference lap, leaving brake_point_spline, trail_brake_frac, and throttle_on_spline unchanged; tools/ai_sidecar/driver_progression.py (lines 101-138) defines a 4-stage CURRICULUM that only filters allowed_roots in DriverCuePolicy without multi-lap drill locking in CoachingLedger or between_lap.py, and between_lap.py:185 starves when canonical track.map corners are 0 (#854)."
  source_kind: repo_file
  locator: "tools/ai_sidecar/coachable_frontier.py#L27-L90; tools/ai_sidecar/driver_progression.py#L101-L138; tools/ai_sidecar/coaching/between_lap.py#L180-L201"
  date: "2026-10-24"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-03]
  notes: "Grounds Card 3 (#529 Gate G3)."

- id: E-009
  claim: "Autonomous racing literature (2024-2026, A2RL / PoliMi / ETH / MERL) combines online friction-circle (GGV) uncertainty bounds with forward-backward minimum-time speed profiling, shrinking or expanding local velocity targets only where active excitation reduces local variance."
  source_kind: paper
  locator: "search_web query 1: A2RL / PoliMi / arXiv / MERL stochastic MPC & adaptive velocity planning (2024-2026)"
  date: "2026-01-01"
  retrieved_at: "2026-10-24"
  confidence: medium
  supports: [REX-20261024-01]
  notes: "Lens 1 (Frontier mechanism)."

- id: E-010
  claim: "Pacejka Magic Formula counterevidence: in passive sub-limit driving (slip angle alpha < 3-4 deg), lateral force reduces to the linear slope F_y approx (B*C*D)*alpha, making peak friction D (mu) structurally unidentifiable without saturation/active excitation."
  source_kind: paper
  locator: "search_web query 4: Stanford / UW-Madison / MERL tire-road friction estimation identifiability limits"
  date: "2025-01-01"
  retrieved_at: "2026-10-24"
  confidence: high
  supports: [REX-20261024-01]
  notes: "Lens 4 (Counterevidence) — rules out pure passive slip-angle extrapolation for G1."

- id: E-011
  claim: "Commercial AI sim-racing coaches (Trophi.ai RTSA, Track Titan Coaching Flows, Driver61) structure trail-braking and cold-tyre mastery as multi-lap isolated drills (straight-line baseline -> split-pressure release -> progressive entry speed sweep)."
  source_kind: docs
  locator: "search_web query 2: trophi.ai / tracktitan.io / driver61.com / popometer.io"
  date: "2025-06-01"
  retrieved_at: "2026-10-24"
  confidence: medium
  supports: [REX-20261024-03]
  notes: "Lens 2 (Nearest prior art)."

- id: E-012
  claim: "Sim-racing practitioner consensus (r/iRacing, r/simracing, BoxThisLap, GitGud Racing Academy) identifies false-positive 'brake later' and 'carry more speed' voice cues on cold out-laps or heavier/low-grip setups as the top reason drivers mute real-time AI voice coaches."
  source_kind: social
  locator: "search_web query 3: reddit.com/r/iRacing, reddit.com/r/simracing, boxthislap.org, gitgudracingacademy.com"
  date: "2025-08-01"
  retrieved_at: "2026-10-24"
  confidence: medium
  supports: [REX-20261024-02]
  notes: "Lens 3 (Practitioner/social provocation)."
```

---

## 2. Four-Lens External Web Search Log (`2026-10-24`)

| Lens | Exact Query | Retrieved Date | Sources & Publication Window | Extracted Claim & Support Limit |
|---|---|---|---|---|
| **1. Frontier mechanism** | `"autonomous racing" online tire friction estimation "ggv" OR "friction circle" uncertainty minimum time speed profile 2024 2025 2026` | `2026-10-24` | arXiv / PoliMi (A2RL) / MERL / Semantic Scholar (`2024–2026`) | Online EKF/UKF & stochastic GGV planners decouple linear slip slope from peak $\mu$ and apply local stability-aware uncertainty shrinkage in forward-backward speed profiling. *Limit:* Requires active longitudinal/lateral excitation near saturation. |
| **2. Nearest prior art** | `"Track Titan" OR "trophi.ai" OR "Garage61" AI sim racing coach cold tires grip limit trail braking drill progression` | `2026-10-24` | `trophi.ai`, `tracktitan.io`, `driver61.com`, `popometer.io` (`2024–2026`) | Trophi.ai RTSA and Track Titan Coaching Flows isolate single-skill drills across 3–5 lap stints (brake-release slope before entry-speed increments). *Limit:* Commercial tools still rely heavily on user-selected drill modes rather than automatic thermal-gated progression. |
| **3. Practitioner / social provocation** | `sim racing AI voice coach "brake later" OR "carry more speed" false positive cold tyres setup differences reddit OR forum` | `2026-10-24` | `r/iRacing`, `r/simracing`, `boxthislap.org`, `gitgudracingacademy.com` (`2024–2026`) | Drivers disable live voice coaches because static hot-lap reference comparisons shout "brake later / carry more speed" on cold tyres (`30 °C` below optimal) or lower-grip setups where braking at the hot-lap marker guarantees a lockup/spin. *Limit:* Social/practitioner evidence motivates user pain and abstention design, not physics equations. |
| **4. Counterevidence** | `tire friction estimation passive driving data identifiability limit sub-limit slip angle Pacejka counterevidence` | `2026-10-24` | Stanford Dynamics Lab, UW-Madison, MERL, `edy.es` Pacejka reference (`2020–2026`) | In the sub-limit linear regime ($\alpha < 3^\circ\text{–}4^\circ$), Pacejka $F_y \approx (B \cdot C \cdot D)\alpha$ couples stiffness $B$ and peak $D$ ($\mu$); $\partial F_y / \partial D$ cannot be separated from $B$, proving passive sub-limit cornering cannot identify peak grip. *Limit:* Refutes pure passive slip-angle extrapolation; requires row-level active probe preservation + local envelope stepping. |

---

## 3. Council Deliberation & Adjudication Record

| Role | Model Family | Tool / Seat | Requested / Reported Model | Tool Access | Status & Scope |
|---|---|---|---|---|---|
| **Pass 1A: Mechanism Designer** | OpenAI (`gpt`) | `mcp__gpt__chatgpt_ask` | Default Codex/GPT seat | None (raw evidence packet supplied) | **Completed (Locked Pass 1A)** — designed 3 repo-anchored mechanisms & falsifiable tests. |
| **Pass 1B: Independent Challenger** | Mistral (`mistral`) | `mcp__mistral__mistral_second_opinion` | Default Mistral adversarial seat | None (raw evidence packet supplied) | **Completed (Locked Pass 1B)** — attacked all 3 candidates with mundane substitutes, AC/CSP failure assumptions, and rival explanations. |
| **Pass 2: Source Checker & Convener Adjudicator** | OpenAI (`gpt`) | `mcp__gpt__chatgpt_ask` | Default Codex/GPT seat | None (supplied Pass 1A + Pass 1B + repo/vault citations) | **Completed (Pass 2)** — audited Pass 1B substitutes against `#746/#749` thermal gate and `coaching_runtime.py:635`, adjudicated `Advance`/`Advance`/`Hold` slate. |
| *Unavailable Seat 1* | Google (`gemini`) | `mcp__gemini__gemini_second_opinion` | `gemini-4-argon` | N/A | **Failed auth (`guest_session`)** — cookies stale (`RuntimeError: Could not get Gemini AT token`). Disclosed per `roadmap-expansion` rules. |
| *Unavailable Seats 2–4* | Perplexity / Kimi / Grok | Not mounted in `<mcp_servers>` | N/A | N/A | **Not mounted in host session** — disclosed per `roadmap-expansion` rules; qualification capped at **`explore`** (`provisional`). |

### Key Points of Agreement & Dissent Across Passes
1. **Card 1 (`REX-20261024-01`, `#529` Gate G1):**
   - *Agreement:* Both Pass 1A (`gpt`) and Pass 1B (`mistral`) agreed that the `thermal_probe_rows = []` wipeout in `ggv_profile.py:1362-1391` and the `0.9 g` passive lateral gate (`ggv_profile.py:643`) are the primary bottleneck locking McLaren@Magione at `91.94 s` QSS / `97.378 s` driven.
   - *Dissent & Adjudication:* Pass 1B proposed forcing `thermal_fit_mode="full_run"` + `complete_run_cohort=True` as a mundane substitute. Pass 2 (Source Checker) + vault evidence `E-004` (`#746/#749`) refuted this substitute because forcing `complete_run_cohort=True` mixes cold out-lap samples into warmed flying-lap fits; row-level thermal eligibility + longitudinal self-play bin merging (`merge_selfplay_model`) + per-corner local envelope stepping is required. Pass 1B's critique against complex Pacejka slip-ratio extrapolation was upheld (aligned with Lens 4 counterevidence `E-010`).
2. **Card 2 (`REX-20261024-02`, Unowned Verticals 4 & 5 Live Coaching Grip Gate):**
   - *Agreement:* Both models agreed `_GRIP_CEILING_G = 1.55` in `coaching_runtime.py:72` is broken for non-GT3 cars (`BMW E30 ~1.05 g`) and cold/overheated tyres.
   - *Dissent & Adjudication:* Pass 1B proposed a denominator-only replacement (`GGVModel.ay_max(v)` dropping thermal/condition modifiers). Pass 2 (Source Checker) showed that a denominator-only patch fails on cold out-laps (`core < 40 °C`), overheated brakes/tyres, wet tracks, and `EARLY_BRAKE` corner entry (which is longitudinal/combined-slip limited, not pure `ay_max(v)`), and noted that `telemetry_source.py` omits thermal fields on replay/shared-memory ticks. Adjudicated as **Advance (`explore`)** with an explicit comparison against the denominator-only substitute in the discriminating test.
3. **Card 3 (`REX-20261024-03`, `#529` Gate G3 Multi-Lap Drill Sequencer):**
   - *Agreement & Adjudication:* Pass 1B argued Candidate C should be deferred/held until Candidates A and B land because locking multi-lap drills on top of an uncalibrated grip gate risks pushing the driver into thermal degradation or cold-tyre spins. Pass 2 concurred and adjudicated Card 3 as **Hold (`explore`)** with explicit promotion gates (`#815` live acoustic closure + `#938` merge).

---

## 4. Rejected & Parked Candidates (Considered and Cut)

1. **Rejected Candidate R1 — Passive Sub-Limit Pacejka Peak ($\mu$) Extrapolation from Linear Slip Slope:**
   - *Why cut:* Lens 4 counterevidence (`E-010`) and Pass 1A/1B both proved that in passive cornering below $3^\circ\text{–}4^\circ$ slip angle, $F_y \approx (B \cdot C \cdot D)\alpha$ structurally couples stiffness $B$ and peak $D$; fitting peak $\mu$ without saturation/probe excitation produces wild variance and unsafe QSS speed profiles.
2. **Parked Candidate R2 — Cross-Session Causal Setup vs Driver Progression Attribution in DuckDB (`tools/coaching_lake/`, Vertical 9):**
   - *Why parked:* While Vertical 9 ("long-horizon trend dashboards remain shallow") is open in `#401`, it is downstream of valid single-session capability envelopes (`REX-20261024-02`) and Gate G3 drill structure (`REX-20261024-03`).
3. **Excluded Scope — Parked Hardware/UI Tracks (`docs/PARKED.md`, `#117` Arduino fan/OLED):**
   - *Why excluded:* Explicitly off-roadmap or labeled `not-this-cycle`.

---

## 5. Finalist Decision Cards (`REX-20261024-01` .. `REX-20261024-03`)

### Card 1 (`REX-20261024-01`): Row-Level Thermal Probe Eligibility & Per-Corner Envelope Bracketing for Cold-Start GGV
- **Decision / Qualification:** **Advance** (`explore` — `provisional` council coverage)
- **Tracker Link:** `issue:` [https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388379995](https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388379995) (owns `#529` Gate G1)
- **Causal Chain (`asset → mechanism → changed outcome → beneficiary`):**
  `tools/ac_harness/ggv_profile.py::ggv_from_lap_archives`, `with_binned_uncertainty`, `merge_selfplay_model`, and `tools/ac_harness/auto_alien.py` → replace the blanket `thermal_probe_rows = []` wipeout with timestamp-aligned row-level 4-wheel thermal eligibility, extend `merge_selfplay_model` to merge qualified longitudinal `brake`/`drive` bins, separate lateral bin states into *Visited / Demonstrated capability / Peak-identified*, and replace global `ggv_scale=1.15` jumps with local per-corner curvature-window stepping (`+0.03 g` to `+0.05 g` with yaw/slip retreat) → unlocks the `70.6%` longitudinal prior floor and `0.9 g` lateral deadlock without crashing in unmeasured high-speed corners → closes the `#529` Gate G1 cold-start identification bottleneck.
- **Strongest Mundane Substitute:** Force `thermal_fit_mode="full_run"` and `complete_run_cohort=True` in `ggv_profile.py` with a smaller global `ggv_scale += 0.05` step (rejected by Pass 2 Source Checker because `E-004` `#746`/`#749` proved that mixing cold out-lap telemetry with flying laps contaminates the GGV fit).
- **External Provocation:** 2024–2026 A2RL/ETH/MERL stochastic velocity planners (`E-009`) shrink uncertainty locally via active excitation, while Pacejka identifiability proofs (`E-010`) show passive sub-limit cornering ($\alpha < 3^\circ\text{–}4^\circ$) couples stiffness $B$ and peak $D$ ($F_y \approx B C D \alpha$), ruling out passive slip-slope extrapolation.
- **Hardest Necessary Assumption:** Archive trace timestamps and 4-wheel core temperature tags (`tyreCoreTemperature`) align cleanly enough with active `brake_probe` and `accel_sweep` windows to filter out cold-out-lap probes at the row level without admitting noisy ABS transients.
- **Rival Explanation / Council Dissent:** Mistral (Pass 1B) argued that complex ABS/slip-ratio modeling is overkill and the core failure is simply longitudinal bin starvation (`thermal_probe_rows = []`) plus the jump to `ggv_scale=1.15`; Pass 2 adjudicated in favor of row-level thermal probe eligibility + local corner stepping without Pacejka slip extrapolation.
- **Discriminating Test:**
  - **Inputs & Comparator:** (1) Offline backtest on retained `#529` McLaren MP4-12C GT3 @ Magione (`2026-10-16`) and `#746`/`#749` BMW E30 archives comparing baseline (`thermal_probe_rows = []`) vs row-level probe eligibility; (2) Bounded rig test (`<= 2` sessions / `<= 10` laps on McLaren@Magione: Session A 5-lap baseline at `ggv_scale=1.0`; Session B 1 warm-up + 2 local-excitation laps + 2 evaluation laps with global `ggv_scale` frozen at `1.0`).
  - **Prediction:** Same-archive refit recovers `>= 8` temperature-qualified longitudinal `brake`/`drive` bins, and Session B completes both evaluation laps with `0` recoveries and `>= 2.0%` (`~1.9 s`) faster median lap time than Session A while `corner_refine.py` retains `>= 3/7` corners as measured.
  - **Pass / Fail / Inconclusive:**
    - *Pass:* `>= 8` longitudinal bins updated on retained archives without admitting out-of-window thermal rows; `0` recoveries in Session B; evaluation median improves `>= 2.0%`.
    - *Fail:* Out-of-window thermal rows admitted, OR local stepping triggers recovery/crash, OR `< 2` corners achieve measured status.
    - *Inconclusive:* Session thermal windows diverge by `> 5 °C` or fewer than 2 valid evaluation laps complete.
  - **Resource Cap, Stop Rule, Allowed Actions & Retained Evidence:** Max 1 PR + 2 rig sessions (`<= 10` laps); stop immediately on first recovery-cap breach or if offline backtest recovers `< 4` longitudinal bins; retain `ggv_profile.json`, `corner_refine_report.json`, and full lap archives.

---

### Card 2 (`REX-20261024-02`): Condition-Indexed Capability Envelope & Thermal Grip Gate for Live Coaching (`CoachRuntime`)
- **Decision / Qualification:** **Advance** (`explore` — `provisional` council coverage)
- **Tracker Link:** `issue:` [https://github.com/agorokh/ac-copilot-trainer/issues/938](https://github.com/agorokh/ac-copilot-trainer/issues/938) (new issue closing the unowned Vertical 4/5 seam in `#401`)
- **Causal Chain (`asset → mechanism → changed outcome → beneficiary`):**
  `tools/ai_sidecar/coaching_runtime.py::CoachRuntime`, `tools/ac_harness/ggv_profile.py::GGVModel`, `tools/ai_sidecar/tyre_model.py`, `tools/ai_sidecar/conditions_model.py`, `tools/ai_sidecar/race_management.py`, and `tools/ai_sidecar/telemetry_source.py` → replace hardcoded `_GRIP_CEILING_G = 1.55` with a condition-indexed capability gate that evaluates `EARLY_BRAKE` against longitudinal/combined entry envelope and `SLOW_APEX` against speed-binned `GGVModel.ay_max(v)`, abstains from demand-increasing `PRIME` and pass diagnoses when tyres/brakes are `cold`/`overheat`/`critical` or regime is `wet`, and forwards `tyre_temps_c`/`brake_temps_c` in `telemetry_source.py` → eliminates false-positive `"Brake later"` / `"Carry more speed"` cues on lower-grip cars (`BMW E30 ~1.05 g`), cold out-laps, and overheated tyres → human drivers receive trustworthy live voice coaching.
- **Strongest Mundane Substitute:** Replace `_GRIP_CEILING_G = 1.55` with a denominator-only lookup `GGVModel.ay_max(speed)` in `coaching_runtime.py:638` and ignore thermal/condition state (rejected by Pass 2 Source Checker because a warm-fit `ay_max(v)` still fires unsafe `"Brake later"` cues on `30 °C` cold out-laps, wet tracks, and brake-overheat laps, and ignores `long_g` entry saturation).
- **External Provocation:** Sim-racing practitioner consensus (`r/iRacing`, `r/simracing`, `BoxThisLap`, `GitGud Racing Academy` — `E-012`) identifies context-blind `"brake later / carry more speed"` prompts on cold tyres or heavier setups as the #1 reason drivers mute real-time AI voice coaches.
- **Hardest Necessary Assumption:** Live and replayed `telemetry_tick` streams consistently supply finite `lat_g`, `long_g`, and per-wheel `tyre_temps_c`/`brake_temps_c` (or the gate abstains cleanly when capability evidence is missing without silencing non-limit technique cues).
- **Rival Explanation / Council Dissent:** Pass 1B warned that over-constraining the gate with noisy thermal channels could suppress valid coaching; Pass 2 resolved this by using `tyre_model.py` discrete window statuses (`cold`, `in_window`, `overheat`, `critical`) as eligibility constraints rather than invented friction multipliers, and testing both recall (`>= 70%` valid cues kept) and precision (`>= 80%` unsupported cues suppressed).
- **Discriminating Test:**
  - **Inputs & Comparator:** Deterministic offline replay (`<= 2` sessions / `8` recorded laps across BMW E30 and McLaren MP4-12C GT3, covering cold out-laps, warmed flying laps, and overheat/wet fixtures) comparing (a) baseline `_GRIP_CEILING_G = 1.55`, (b) mundane substitute `GGVModel.ay_max(v)` denominator-only, and (c) the full condition-indexed capability gate.
  - **Prediction:** The condition-indexed gate suppresses `>= 80%` of independently pre-labeled unsupported demand-increasing cues (`EARLY_BRAKE`, `SLOW_APEX`) on cold/low-grip/overheat passes while retaining `>= 70%` of safe, actionable under-limit cues on in-window passes, outperforming the denominator-only substitute on cold out-laps.
  - **Pass / Fail / Inconclusive:**
    - *Pass:* `>= 80%` suppression of unsupported demand-increasing cues AND `>= 70%` retention of valid in-window cues; `make ci-fast` green.
    - *Fail:* Suppresses `< 50%` of unsupported cues OR suppresses `> 30%` of valid in-window cues.
    - *Inconclusive:* Fewer than 5 evaluable cue opportunities in either class across the 8-lap replay corpus.
  - **Resource Cap, Stop Rule, Allowed Actions & Retained Evidence:** Max 1 PR + 8-lap replay benchmark; stop and fall back to combo-scalar `GGVModel.ay_max(v)` if valid in-window cue retention drops below `70%`; retain replay JSON diff report and unit test suite in `tests/ai_sidecar/test_coaching_runtime.py`.

---

### Card 3 (`REX-20261024-03`): Closed-Loop Multi-Lap Drill Sequencer with Phase-Space Frontier Targets
- **Decision / Qualification:** **Hold** (`explore` — `provisional` council coverage; held behind `#815` live acoustic closure and [#938](https://github.com/agorokh/ac-copilot-trainer/issues/938))
- **Tracker Link:** `issue:` [https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388379995](https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388379995) (owns `#529` Gate G3 / Vertical 7)
- **Causal Chain (`asset → mechanism → changed outcome → beneficiary`):**
  `tools/ai_sidecar/coachable_frontier.py`, `tools/ai_sidecar/driver_progression.py::CURRICULUM`, `tools/ai_sidecar/coaching_ledger.py`, and `tools/ai_sidecar/coaching/between_lap.py` → extend the coachable frontier from apex `min_speed_kmh` alone to isolated phase-space control targets (`brake_point_spline`, `trail_brake_frac`, `min_speed_kmh`, `throttle_on_spline`), lock one corner + curriculum stage across $N=3$ consecutive valid laps followed by $2$ uncued retention laps in `CoachingLedger`, and add centerline-curvature corner-interval fallback when `track.map` reports `0` canonical corners (`#854`) → transforms lap-by-lap reactive voice reminders into measurable multi-lap deliberate practice → enables `#529` Gate G3 human learning validation.
- **Strongest Mundane Substitute:** Hardcode a 3-lap `min_speed_kmh` step (`+2`, `+4 km/h`) in `coachable_frontier.py` with a static corner list for Magione (attacked by Pass 1A/2 because apex-speed-only targets without brake-release or throttle-onset guards induce entry overslowing or exit scrubbing).
- **External Provocation:** Commercial coaching platforms (`Trophi.ai` RTSA drills, `Track Titan` Coaching Flows, `Driver61` — `E-011`) isolate a single phase variable (e.g., split-pressure trail-brake release) across consecutive laps before advancing entry speed.
- **Hardest Necessary Assumption:** A human driver's per-corner phase metric (`trail_brake_frac` or `throttle_on_spline`) exhibits small enough lap-to-lap variance across 3 baseline laps that a targeted drill shift is distinguishable from tyre warm-up drift within a 10-lap stint.
- **Rival Explanation / Council Dissent:** Both Pass 1B (Mistral) and Pass 2 (GPT Source Checker) adjudicated that Card 3 must be **Held** until [#938](https://github.com/agorokh/ac-copilot-trainer/issues/938) (`REX-20261024-02`) lands: locking multi-lap drills before `CoachRuntime` has a working thermal/capability gate risks drilling a driver to brake later on overheating rear tyres.
- **Promotion Condition (Hold → Advance):**
  1. Operator closes `#815` live acoustic acceptance clauses 36 & 38.
  2. [#938](https://github.com/agorokh/ac-copilot-trainer/issues/938) (`REX-20261024-02` condition-indexed grip gate) is merged on `main`.
- **Discriminating Test (once promoted):**
  - **Inputs & Comparator:** 1 human-driven session (`<= 10` laps: 2 warm-up, 3 valid baseline, 3 locked-drill on 1 target corner for `trail-brake-entry` or `throttle-to-apex`, 2 uncued retention laps) vs unlocked lap-by-lap `CoachRuntime`.
  - **Prediction:** `>= 2/3` drill laps and `2/2` uncued retention laps hit the target phase band without degrading whole-corner time or `exit_speed_kmh`.
  - **Pass / Fail / Inconclusive:**
    - *Pass:* Target metric shifts into the frontier band on `>= 2/3` drill laps and `2/2` uncued retention laps; `0` off-track events; `exit_speed_kmh` within baseline tolerance.
    - *Fail:* Effect vanishes on uncued retention laps (cue-following without retention) or exit speed degrades.
    - *Inconclusive:* Tyre core temperatures enter `overheat`/`critical` or corner identity is unstable across laps.
  - **Resource Cap, Stop Rule, Allowed Actions & Retained Evidence:** Max 1 session (`10` laps); abort drill immediately if tyre core temp enters `overheat`/`critical`; retain `CoachingLedger` drill trace and lap archives.
