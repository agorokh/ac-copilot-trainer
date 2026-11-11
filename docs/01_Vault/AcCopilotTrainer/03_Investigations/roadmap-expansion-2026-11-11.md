---
type: investigation
status: active
memory_tier: canonical
created: 2026-11-11
updated: 2026-11-11
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/10_Rig/external-racing-controls.md
  - AcCopilotTrainer/03_Investigations/issue-86-device-acceptance-2026-11-10.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-10-24.md
---

# Roadmap Expansion Investigation & Decision Slate (`2026-11-11`)

- **Repository:** `agorokh/ac-copilot-trainer` (base `HEAD` `bcf3878c55722fe70705a12682d86ed049356672`)
- **Umbrella / Tracker:** [#401](https://github.com/agorokh/ac-copilot-trainer/issues/401) ([summary comment](https://github.com/agorokh/ac-copilot-trainer/issues/401#issuecomment-6801783432)) · Finalist issues: [#955](https://github.com/agorokh/ac-copilot-trainer/issues/955) (`REX-20261111-01`), [#956](https://github.com/agorokh/ac-copilot-trainer/issues/956) (`REX-20261111-02`), [#957](https://github.com/agorokh/ac-copilot-trainer/issues/957) (`REX-20261111-03`)
- **Prior Baseline:** Post-`2026-10-24` closures landed `#938` (`REX-20261024-02` condition-indexed thermal capability gate), `#815` (MOZA R9/CRP2 + live acoustic & HUD acceptance), `#534` (SimHub car enrichment), `#813` (display/MAP), and `#86` (`COM6` ESP32 touchscreen live device acceptance on `2026-11-10`). Prior to filing `#955`–`#957`, only three issues remained open: `#529` (Alien Lap Platform, already holding `REX-20261024-01` G1 and `REX-20261024-03` G3), `#401` (Roadmap umbrella), and `#117` (parked `not-this-cycle` Arduino fan/OLED).
- **Council Qualification Cap:** `explore` (`provisional` council coverage: 2 of 5 model families active in session — OpenAI `gpt:chatgpt_ask` and Mistral `mistral:mistral_second_opinion` completed strictly independent locked Pass 1 + Pass 2 Source-Checker & Adversarial Cross-Examination passes; Google `gemini:gemini_second_opinion` failed web-cookie auth with `guest_session` and 0 further retries; `perplexity`, `kimi`, and `grok` MCP servers were not mounted in this host environment).

---

## 1. Grounded Code, Vault & External Evidence Records

### 1A. Repository & Vault Evidence (`E-001` .. `E-010`)

```yaml
- id: E-001
  claim: "Every CSP Lua module in src/ac_copilot_trainer/ reads exclusively ac.getCar(0) (ac_copilot_trainer.lua:1838,2012,2122,2168,2351,3187; telemetry.lua:227-285; track_markers.lua; racing_line.lua). Zero opponent spatial or spline telemetry is sampled when sim.carsCount > 1."
  source_kind: repo_file
  locator: "src/ac_copilot_trainer/ac_copilot_trainer.lua#L1838-L3187"
  date: "2026-11-11"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-01]
  notes: "Verified via git grep 'ac\\.getCar' across src/ac_copilot_trainer/ at bcf3878."

- id: E-002
  claim: "tools/ac_harness/dump_schema.lua:45 already lists carsCount on ac.getSim(), and ac.getCar(i) returns a lightweight FFI C-struct pointer (position, splinePosition, speedKmh, isInPitlane, isConnected), enabling 10-20 Hz scalar opponent occupancy checks without 46-column wheel serialization."
  source_kind: repo_file
  locator: "tools/ac_harness/dump_schema.lua#L44-L47"
  date: "2026-11-11"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-01]
  notes: "Verified in Pass 2 Source Check; ac_schema.json gates trace_replay.py mock fields."

- id: E-003
  claim: "tools/lap_qualification.py defines the single-source-of-truth archive boundary policy qualify_archive(record, use=...) across USES={'analysis','map','live_reference','reference_comparison','human_progression','plant_fit'}, isolating authority != 'human' (#815) without touching #529-owned driver_progression.py."
  source_kind: repo_file
  locator: "tools/lap_qualification.py#L25-L60"
  date: "2026-11-11"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-01, REX-20261111-03]
  notes: "Verified in Pass 2 seam check to prevent file collision with #529 REX-20261024-03."

- id: E-004
  claim: "Python setup intelligence is implemented and tested — setup_advisor.py (668 LOC), setup_optimizer.py (1,143 LOC experiments.jsonl, A/B compare, Gaussian surrogate), corner_attribution.py (1,635 LOC), tyre_model.py — and server.py:2218-2479 exposes TYPE_SETUP_ADVICE, TYPE_SETUP_COMPARE, TYPE_SETUP_SUGGEST, and TYPE_SETUP_CLOSED_LOOP, yet git grep shows ZERO non-test callers across firmware/, tablet_dash.html, rig_launcher, or Lua."
  source_kind: repo_file
  locator: "tools/ai_sidecar/server.py#L2218-L2479"
  date: "2026-11-11"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-02]
  notes: "Producer/protocol half is shipped; cockpit consumer half is completely absent."

- id: E-005
  claim: "Issue #86 closed on 2026-11-10 with live hardware acceptance on ESP32 COM6 across Launcher, AC Copilot live, Pocket Technician (screen_pocket_technician.cpp pit-box is_in_pit spinner +/- and preset load/save), and Setup Exchange install/load."
  source_kind: repo_file
  locator: "docs/01_Vault/AcCopilotTrainer/03_Investigations/issue-86-device-acceptance-2026-11-10.md#L1-L80"
  date: "2026-11-10"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-02]
  notes: "Unlocks a live, pit-gated physical touchscreen surface for telemetry prescriptions."

- id: E-006
  claim: "Issue #938 (REX-20261024-02) shipped condition-indexed capability envelope and cold/overheated tyre thermal grip gating in tools/ai_sidecar/coaching_runtime.py (PR #940), removing the stated blocker on Oct 24 Parked R2 (Vertical 9 long-horizon progression)."
  source_kind: repo_file
  locator: "tools/ai_sidecar/coaching_runtime.py#L1-L160"
  date: "2026-11-11"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-02, REX-20261111-03]
  notes: "Provides thermal regime gating, though multi-session corpus overlap remains unaudited."

- id: E-007
  claim: "tools/coaching_lake/build_analytics.py materializes DuckDB/Parquet lap_features, stint_deg (fuel-corrected tyre deg), setup-vs-dynamic, and dynamic-static-delta, whereas tools/session_review/report.py evaluates one session at a time without multi-session strata matching or confounder abstention."
  source_kind: repo_file
  locator: "tools/coaching_lake/build_analytics.py#L1-L180"
  date: "2026-11-11"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-03]
  notes: "Analytical tables exist; longitudinal common-support density is unproven."

- id: E-008
  claim: "server.py:3038-3093 transports loopback-guarded PCM16 microphone chunks (MIC_CHUNK for CLIENT_CLASS_VOICE), while AGENTS.md (#672) documents that the rig ships deliberately pinned to a shared AC FMOD speaker endpoint without acoustic echo cancellation (AEC), and external-racing-controls.md documents three unassigned physical rig buttons (Button 2, Button 3, Encoder press)."
  source_kind: repo_file
  locator: "tools/ai_sidecar/server.py#L3038-L3093"
  date: "2026-11-11"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-R1]
  notes: "Key architectural counterevidence against cockpit speech pit radio."

- id: E-009
  claim: "src/ac_copilot_trainer/modules/track_markers.lua orients 3D quads perpendicular to instantaneous car.look from local best/last lists, and racing_line.lua uses static 80/150 km/h speed colors without consuming CoachRuntime capability envelopes."
  source_kind: repo_file
  locator: "src/ac_copilot_trainer/modules/track_markers.lua#L115-L155"
  date: "2026-11-11"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-R2]
  notes: "Verified local Lua implementation; no HMD/AR hardware target is active on rig."

- id: E-010
  claim: "Open issue #529 owns REX-20261024-01 (G1 ggv_profile.py, auto_alien.py, corner_refine.py) and REX-20261024-03 (G3 coachable_frontier.py, driver_progression.py, coaching_ledger.py, coaching/between_lap.py)."
  source_kind: issue
  locator: "https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388379995"
  date: "2026-10-24"
  retrieved_at: "2026-11-11"
  confidence: high
  supports: [REX-20261111-01, REX-20261111-02, REX-20261111-03]
  notes: "Explicit non-duplication and file-seam boundary check."
```

### 1B. Fresh External 4-Lens Search Log (`2026-11-11`, `8/8` cap)

| ID | Lens | Query (`2026-11-11`) | Sources & Pub Window | Extracted Claim & Support Limit |
|---|---|---|---|---|
| `W-001` | Frontier mechanism | `Bayesian optimization vehicle setup telemetry tire pressure motorsport sim racing 2024 2025 2026` | `mdpi.com`, `arxiv.org` (TUM Autonomous Motorsport), `coachdaveacademy.com`, `tracktitan.io` (`2024–2026`) | Telemetry-conditioned setup loops target physical response channels (stabilized hot psi window, I-M-O tread thermal gradient, local slip) rather than raw black-box lap time alone. *Limit:* Multi-parameter BO still needs tens of clean laps unless scoped to direct physical invariants like cold-to-hot psi error. |
| `W-002` | Frontier mechanism | `racecraft coaching overtake defense sim racing AI coach telemetry 2024 2025 2026` | `trophi.ai`, `coachdaveacademy.com`, `tracktitan.io`, `apexsimapps.com` (`2024–2026`) | Commercial AI coaches optimize solo braking/apex traces well, whereas wheel-to-wheel racecraft/defense remains largely manual replay/human coaching because automated coaches lack multi-car tactical intent models. *Limit:* Supports occupancy-based cue gating, NOT automated overtake planning. |
| `W-003` | Nearest prior art | `Coach Dave Delta Trophi.ai Track Titan AI setup engineer auto tire pressure telemetry` | `coachdaveacademy.com` (`Setup IQ`), `trophi.ai` (`Mansell`), `tracktitan.io` (`2024–2026`) | `Coach Dave Delta` (`Setup IQ`) adapts setup files post-stint on desktop; `Trophi.ai` (`Mansell`) delivers live solo voice cues; neither runs a pit-gated cockpit hardware prescription card tied to an auditable local experiment ledger on AC1 + CSP. |
| `W-004` | Nearest prior art | `Digital Race Engineer DRE CrewChief voice commands pit engineer setup tire pressure spotter` | `thedigitalraceengineer.com`, `gitlab.io` (CrewChief v4), `simracingcockpit.gg` (`2023–2026`) | `DRE` (iRacing) and `CrewChief` combine spotter proximity calls with push-to-talk pit fuel/tyre voice macros, strongly recommending headset isolation or echo cancellation to avoid speaker bleed false triggers. |
| `W-005` | Practitioner provocation | `sim racing AI coach in traffic race mode problem OR adjusting cold tire pressure pit stop reddit` | `reddit.com` (`r/simracing`, `r/iRacing`, `r/assettocorsa`, `2023–2026`) | Two recurring practitioner complaints: (1) drivers mute real-time AI voice coaches in races/traffic because solo `"brake 15 m later"` cues fire blindly when fighting side-by-side; (2) pit-stop cold-pressure offsets (`~0.1 psi per 1°C` temp shift) require tedious mental math under pit-lane time pressure. |
| `W-006` | Counterevidence | `race car setup A/B testing driver variance track temperature confounding statistical significance` | Motorsport engineering & sim-testing synthesis (`2023–2026`) | Amateur/pro-am driver lap-time variance (`±0.4 s`) and `5°C` track temperature shifts completely swamp `0.2 s` setup or skill deltas in small-sample `p < 0.05` lap-time comparisons unless ABBA pairing, physical proxy channels, and explicit confounder matching are enforced. |
| `W-007` | Counterevidence | `Assetto Corsa Custom Shaders Patch Lua ac.getCar multi car performance OR speech recognition cockpit noise WER` | Combined query boundary check (`2026-11-11`) | Confirmed need to split CSP Lua FFI verification (resolved directly against repo `dump_schema.lua` in `E-002`) from cabin ASR noise counterevidence (`W-008`). |
| `W-008` | Counterevidence | `Whisper speech recognition word error rate noisy vehicle engine cabin speaker bleed SNR` | `arxiv.org`, `forasoft.com`, `openwhispr.com` (`2024–2026`) | Low-frequency engine rumble (`100–500 Hz`) overlaps male speech fundamentals, and cabin speaker bleed without hardware/DSP AEC triggers severe Whisper decoder hallucinations and repetition loops at low/negative SNR. |

---

## 2. Council Deliberation & Non-Overlap Verification

### 2A. Seat Roster & Independence Protocol

- **Pass 1A — Mechanism Designer (`gpt:chatgpt_ask`, extended reasoning):** Prompted with sanitized raw evidence packet only (`E-001`..`E-010`, `W-001`..`W-008`, zero cross-seat text). Proposed 4 candidates: (1) Pit-box prescription cards on Pocket Technician (`advance`), (2) Traffic-aware coaching eligibility & evidence quarantine (`advance`, #1 priority), (3) Condition-matched multi-session progression with `"cannot identify"` abstention (`hold`), and (4) Button-gated closed-vocabulary pit radio (`hold` pending shared-speaker acoustic test).
- **Pass 1B — Independent Adversarial Challenger (`mistral:mistral_second_opinion`):** Prompted in parallel from the **exact same raw evidence packet only** (zero exposure to Pass 1A). Independently selected the **exact same two `advance` winners** (`[E-001]` Pit-wall setup intelligence on `COM6` and `[E-002]` Multi-car traffic isolation), independently placed `[E-004]` (Vertical 9 progression) on **`hold`** over multi-session confounder noise, and **`reject`ed** both `[E-003]` (Cockpit speech radio — killed by `#672` shared-speaker FMOD bleed + zero AEC while physical buttons beat speech) and `[E-005]` (3D Spatial AR markers — no HMD/AR demand; static markers + 2D HUD/voice suffice).
- **Pass 1C — Systems Challenger (`gemini:gemini_second_opinion`):** Returned hard authentication error (`guest_session`: stale Chrome cookie on `gemini-sub`). Per protocol, 0 blind retries wasted on an auth wall; seat absence disclosed. Unmounted seats: `perplexity`, `kimi`, `grok`. Run marked **`provisional`**; all qualifications capped at **`explore`**.
- **Pass 2 — Source Checker, Cross-Examination & Convener Adjudication (`gpt:chatgpt_ask` high reasoning + `mistral:mistral_second_opinion` test-gaming attack):**
  - **Source Check (`bcf3878`):** Verified `dump_schema.lua:45` (`sim.carsCount` + FFI `ac.getCar(i)`), `lap_qualification.py` boundary isolation (`#815`), `server.py:3041` loopback mic transport vs `#672` shared speaker endpoint, and `#529` file ownership (`REX-20261024-01`/`03`).
  - **Test-Gaming Hardening (`mistral` Pass 2 critique adopted):**
    1. On `REX-20261111-01` (`#955`), added 5 adversarial multi-car controls (cars in pit lane, disconnected, start/finish spline wraparound, and spatially adjacent track segments where spline delta is large/small vs 3D Euclidean distance) plus a `250 ms` staleness fail-closed `"unknown"` rule so naive `sim.carsCount > 1` or spline-only gates fail immediately.
    2. On `REX-20261111-02` (`#956`), closed the all-abstention and micro-nudge (`+0.1 psi`) gaming loopholes by requiring **both** `>= 5/6` actionable prescriptions (`|delta| >= 0.5 psi`) on sustained hot-psi deviations **and** `>= 5/6` explicit abstentions on out-lap/lockup/short-stint traps, `0` wrong-direction prescriptions, pit-exit recheck at the write boundary, and `verified_applied` state gated on actual setup readback.
    3. On `REX-20261111-03` (`#957`), required blind negative permutations (`>= 1,000` session-clustered replicates, `<= 5%` false improvement) and synthetic offsets across `+0.2 s` to `+0.5 s` (not a single memorizable `+0.3 s` constant).
  - **Adjudication of `[E-003]` Split:** Seat 1B's **`reject`** prevailed over Seat 1A's **`hold`** because three unassigned physical buttons (`Button 2`, `Button 3`, `Encoder press`) already provide zero-latency, zero-hallucination cockpit triggers for fixed-vocabulary status/complaint actions on a shared-speaker rig without AEC. Seat 1A's `hold` is preserved as explicit dissent with a quantitative reopening gate in §4.

### 2B. Scope & File-Seam Non-Overlap Matrix

| Item / Epic | Exclusive File Seam | Overlap Check |
|---|---|---|
| `#529` (`REX-20261024-01` & `-03`) | `tools/ac_harness/{ggv_profile,auto_alien,corner_refine}.py`, `tools/ai_sidecar/{coachable_frontier,driver_progression,coaching_ledger}.py`, `coaching/between_lap.py` | **0 overlap** — `REX-20261111-01` routes progression/plant isolation through `tools/lap_qualification.py`. |
| `REX-20261111-01` ([#955](https://github.com/agorokh/ac-copilot-trainer/issues/955)) | `src/ac_copilot_trainer/{ac_copilot_trainer.lua,modules/traffic_context.lua}`, `tools/ac_harness/{ac_schema.json,trace_replay.py}`, `tools/ai_sidecar/{traffic_eligibility,coaching_runtime}.py`, `tools/lap_qualification.py` | **Disjoint** from `#956`, `#957`, `#529`, `#117`. |
| `REX-20261111-02` ([#956](https://github.com/agorokh/ac-copilot-trainer/issues/956)) | `tools/ai_sidecar/{setup_prescription,tyre_model,external_protocol,server}.py`, `firmware/screen/src/ui/screen_pocket_technician.cpp`, `firmware/screen/simulator/` | **Disjoint** from `#955`, `#957`, `#529`, `#117`. |
| `REX-20261111-03` ([#957](https://github.com/agorokh/ac-copilot-trainer/issues/957)) | `tools/coaching_lake/{progression_audit,build_analytics}.py`, `tools/session_review/report.py` | **Disjoint** from `#955`, `#956`, `#529`, `#117`. |

---

## 3. Finalist Decision Cards (`REX-20261111-01` .. `03`)

### Card 1 — `REX-20261111-01`: Traffic-Aware Coaching Eligibility & Evidence Quarantine

```yaml
id: REX-20261111-01
title: "Traffic-aware coaching eligibility and multi-car evidence quarantine"
decision: advance
qualification: explore
council_status: provisional
missing_coverage: "gemini (guest_session auth expired), perplexity/kimi/grok (MCP unmounted); 2/5 families (gpt, mistral) converged independently."
beneficiary: "Solo MOZA rig driver running AI races, trackdays, and multi-car stints."
changed_outcome: "CoachRuntime suppresses dangerous solo pace-increasing voice cues ('Brake later', higher apex speed) when braking/apex space is occupied by traffic while retaining clean-air coaching, and lap_qualification.py prevents traffic-compromised laps from polluting human_progression, live_reference, and plant_fit cohorts."
repo_anchors:
  - "src/ac_copilot_trainer/ac_copilot_trainer.lua#L1838-L3187"
  - "tools/ac_harness/dump_schema.lua#L44-L47"
  - "tools/ai_sidecar/coaching_runtime.py#L1-L160"
  - "tools/lap_qualification.py#L25-L60"
prior_art:
  - "CrewChief v4 / Digital Race Engineer (DRE) spotter proximity alerts; Trophi.ai Mansell solo live voice coaching (W-002, W-004)."
external_provocation:
  - "Sim racers routinely mute live AI coaches in race/traffic modes because solo braking cues fire blindly when side-by-side or following closely (W-005)."
residual_difference: "Gates live corner-phase coaching cues and downstream telemetry qualification using 3D + spline occupancy without attempting spotter chatter or overtake planning."
mundane_substitute: "Blanket-mute CoachRuntime and exclude the entire session whenever sim.carsCount > 1."
hardest_assumption: "Scalar opponent state (position, splinePosition, speedKmh, isInPitlane, isConnected) sampled at 10-20 Hz distinguishes constrained from clear corner approaches accurately enough to beat blanket multi-car muting within <= 1.0 ms p99 Lua step overhead."
rival_explanation_or_dissent: "Pass 2 Challenger (mistral) warned that spline-only or carsCount thresholds can look accurate on simple fixtures while false-firing across adjacent track loops or pit-lane cars; fixed via 5 mandatory adversarial geometry/pit controls and 250 ms fail-closed staleness."
discriminating_test:
  inputs: "45 frozen replay-labeled multi-car corner approaches (20 occupied braking/apex, 20 clear-air, 5 pit-lane/wraparound/adjacent-loop controls) labeled before tuning + 20-car grid frame-time benchmark."
  comparator: "Current ac.getCar(0)-only policy and blanket sim.carsCount > 1 session mute."
  prediction: ">= 19/20 constrained approaches suppressed, >= 16/20 clear approaches retained, 5/5 adversarial controls clean, 0 constrained/unknown archives admitted to clean progression/plant cohorts, Lua p99 overhead <= 1.0 ms."
  pass_if: "All five thresholds hold on the held-out replay set and lap_qualification.py preserves 'analysis' access while blocking clean-pace uses."
  fail_if: "Constrained suppression < 19/20, clear retention < 16/20, any spline-adjacent false fire, lost quarantine tag, or Lua p99 > 1.0 ms."
  inconclusive_if: "< 40 valid multi-car corner approaches captured or CSP opponent state unavailable in replay."
  resource_cap: "Max 2 engineering days + 90 minutes shadow/replay rig capture; no learned classifier."
  stop_rule: "Shadow-only first; halt immediately if Lua step cost > 1.0 ms p99 at 20 cars."
  allowed_actions: "Feature-branch Lua/Python/schema/test changes and replay fixture capture only."
  retained_evidence: "Frozen 45-approach evaluation JSON + 20-car Lua frame-time distribution."
next_action: "Await operator approval on #955 / #401 to execute the bounded explore experiment."
issue: https://github.com/agorokh/ac-copilot-trainer/issues/955
evidence_ids: [E-001, E-002, E-003, E-010, W-002, W-004, W-005]
```

### Card 2 — `REX-20261111-02`: Pit-Box Telemetry Prescription Cards on Pocket Technician

```yaml
id: REX-20261111-02
title: "Pit-box telemetry prescription cards with verified readback on Pocket Technician"
decision: advance
qualification: explore
council_status: provisional
missing_coverage: "gemini (guest_session auth expired), perplexity/kimi/grok (MCP unmounted); 2/5 families (gpt, mistral) converged independently."
beneficiary: "Solo MOZA rig driver returning to the pit box with the live COM6 ESP32 touchscreen (#86)."
changed_outcome: "Driver receives a pit-gated cold-pressure / thermal-window prescription card ('symptom -> stabilized stint evidence -> bounded cold-psi delta -> Accept/Reject') on COM6 and logs a verified-readback intervention in experiments.jsonl in one tap instead of leaving the cockpit to mentally invert hot-to-cold psi."
repo_anchors:
  - "tools/ai_sidecar/server.py#L2218-L2479"
  - "tools/ai_sidecar/setup_advisor.py#L1-L120"
  - "tools/ai_sidecar/setup_optimizer.py#L1-L140"
  - "tools/ai_sidecar/tyre_model.py#L1-L120"
  - "firmware/screen/src/ui/screen_pocket_technician.cpp#L1-L140"
prior_art:
  - "Coach Dave Delta Setup IQ (desktop post-stint setup tuner); ACC/iRacing external tyre-pressure calculators (W-001, W-003, W-005)."
external_provocation:
  - "Telemetry-conditioned tyre-pressure loops outperform raw lap-time A/B guessing under ±0.4 s driver variance, while manual pit-stop cold-psi offset math (~0.1 psi/°C) is error-prone in-cockpit (W-001, W-005, W-006)."
residual_difference: "Wires already-tested sidecar diagnostics directly to a pit-rechecked physical COM6 touchscreen card with explicit human consent and readback-verified experiment logging."
mundane_substitute: "Read post-stint session.review text and manually tap raw PRESSURE_* +/- spinners in Pocket Technician."
hardest_assumption: "Stabilized flying-lap telemetry (tyre_model.py + #938 thermal state) yields >= 0.5 psi cold-pressure prescriptions in the right direction while abstaining on cold out-laps, lockup spikes, and < 2 flying-lap stints."
rival_explanation_or_dissent: "Pass 2 Challenger (mistral) showed an all-abstention or +0.1 psi micro-nudge policy could game a naive '>= 10/12' rule; fixed by requiring >= 5/6 actionable (>= 0.5 psi) prescriptions on real deviations AND >= 5/6 abstentions on confounded traps."
discriminating_test:
  inputs: "12 frozen adjudicated pit-return snapshots (6 sustained hot-psi deviations >= 0.6 psi off window; 6 cold-out-lap / lockup / short-stint / unknown-compound traps)."
  comparator: "Existing session.review report + manual raw Pocket Technician spinners (counterbalanced order)."
  prediction: "0 wrong-direction prescriptions, >= 5/6 real deviations prescribed (|delta| >= 0.5 psi), >= 5/6 traps abstained, >= 30% faster median operator decision-to-apply time, 0 writes when is_in_pit flips false."
  pass_if: "All accuracy, abstention, pit-recheck, readback-verification, simulator PNG, and decision-time gates pass."
  fail_if: "Any wrong-direction actionable prescription, < 5/6 real actions, < 5/6 trap abstentions, or any write outside pit."
  inconclusive_if: "< 12 adjudicated snapshots available."
  resource_cap: "Max 1.5 engineering days + native tools.screen_simulator run + 60 minutes bench/pit check; cold-pressure scope only."
  stop_rule: "Halt live pit application immediately on first wrong-direction actionable prescription."
  allowed_actions: "Feature-branch sidecar/screen code, simulator PNGs (per #86 rule), and controlled pit-box readback check."
  retained_evidence: "12-case adjudication scorecard, simulator PNGs, and deduplicated experiments.jsonl readback log."
next_action: "Await operator approval on #956 / #401 to execute the bounded explore experiment."
issue: https://github.com/agorokh/ac-copilot-trainer/issues/956
evidence_ids: [E-004, E-005, E-006, E-010, W-001, W-003, W-005, W-006]
```

### Card 3 — `REX-20261111-03`: Condition-Matched Multi-Session Progression & Confounder Abstention

```yaml
id: REX-20261111-03
title: "Condition-matched multi-session progression overlap audit and confounder abstention"
decision: hold
qualification: explore
council_status: provisional
missing_coverage: "gemini (guest_session auth expired), perplexity/kimi/grok (MCP unmounted); 2/5 families (gpt, mistral) converged independently on HOLD."
beneficiary: "Solo driver reviewing multi-week practice progression across sessions."
changed_outcome: "Cross-session review reports either a strata-matched pace delta with uncertainty bounds or an explicit 'cannot_identify (reason)' abstention instead of mistaking cooler track temps, lower fuel, or setup changes for skill improvement."
repo_anchors:
  - "tools/coaching_lake/build_analytics.py#L1-L180"
  - "tools/session_review/report.py#L1-L120"
  - "tools/lap_qualification.py#L25-L60"
prior_art:
  - "Track Titan / Garage61 session history leaderboards; motorsport paired/regression environmental normalization (W-003, W-006)."
external_provocation:
  - "5°C track-temperature shifts and fuel/setup changes easily exceed 0.3 s, invalidating unstratified cross-session PB trend lines (W-006)."
residual_difference: "Enforces strict common-support strata matching across thermal_band, setup_hash, fuel_band, assists, and traffic_eligibility with a mandatory 'cannot_identify' outcome when < 3 independent sessions per period overlap."
mundane_substitute: "Filtering coaching_lake best laps to identical (car, track, layout, setup_hash) in a static summary table."
hardest_assumption: "Retained human-qualified sessions contain >= 3 independent overlapping sessions per comparison period on at least one primary combo so stratified matching holds null false-positive rate <= 5% while detecting 0.3 s shifts at >= 80% power."
rival_explanation_or_dissent: "Both Seat 1A (gpt) and Seat 1B (mistral) held this card because #938 provides per-lap thermal regime tags but does NOT prove longitudinal common support exists in the current archive corpus."
discriminating_test:
  inputs: "Retained human-qualified (use='human_progression') coaching_lake corpus + >= 1,000 session-clustered blind null permutations + synthetic +0.2 s..+0.5 s pace offsets and nuisance-only temp/fuel shifts."
  comparator: "Raw session-PB trend slope and identical-setup median filter."
  prediction: "Common-support audit identifies >= 3 independent matched sessions per period on primary combo; null false-improvement <= 5%; nuisance-only skill claims <= 5%; >= 80% recovery at +0.3 s."
  pass_if: "Corpus overlap >= 3 independent sessions/period AND blind null/synthetic calibration passes all bounds."
  fail_if: "Adequate session overlap exists (>= 3/period) but null false-positive > 5% or +0.3 s detection power < 80%."
  inconclusive_if: "< 3 independent matched sessions per period exist (remain on Hold)."
  resource_cap: "0.5 day offline corpus overlap audit (max 2 days total with calibration); 0 UI work and 0 driving campaigns while on Hold."
  stop_rule: "Stop after the half-day audit and stay on Hold if < 3 independent matched sessions per period exist."
  allowed_actions: "Offline DuckDB/Parquet audit + calibration tests only after promotion condition is met."
  retained_evidence: "Common-support coverage matrix JSON + 1,000-replicate calibration scorecard."
next_action: "Hold until >= 6 human-qualified traffic-clean sessions accumulate on one (car, track, layout) combo AND operator promotes #957."
issue: https://github.com/agorokh/ac-copilot-trainer/issues/957
evidence_ids: [E-003, E-006, E-007, E-010, W-003, W-006]
```

---

## 4. Rejected & Parked Candidates Annex (with Reopening Conditions)

1. **`REX-20261111-R1` — Push-to-Talk Cockpit Speech Pit Radio (`[E-003]`) — Decision: `reject`**
   - **Candidate mechanism:** Bind an unassigned rig button (`Button 2` / `Button 3` in `external-racing-controls.md`) to push-to-talk over `microphone.py` / `tablet_audio.js` (`MIC_CHUNK`), routing closed-vocabulary speech queries/complaints to `setup_advisor.py` and `RaceStatusTracker`.
   - **Why rejected:** `#672` documents that the rig ships deliberately pinned to a shared AC FMOD speaker endpoint with **zero AEC**, where `100–500 Hz` engine/exhaust bleed overlaps speech fundamentals and drives severe ASR hallucinations (`W-008`), while three unassigned physical buttons already deliver deterministic, zero-latency status/complaint triggers (`E-008`).
   - **Preserved dissent:** Seat 1A (`gpt`) favored `hold` pending a 90-utterance + 30-engine-window stationary acoustic benchmark; Seat 1B (`mistral`) and Pass 2 adjudication rejected speech for the current cycle because no required cockpit action exceeds what the three physical buttons + `COM6` touchscreen already express cleanly.
   - **Reopening condition:** Reopen **only** if (a) the rig moves AC FMOD audio off the shared speaker onto an isolated headset (`voice_endpoint: distinct` in Game Point `#672`) or adds verified DSP AEC, **and** (b) a required driver query cannot be mapped to `Button 2`/`Button 3`/`Encoder press`, **and** (c) bench testing proves `>= 95%` intent accuracy with `0` unintended actions across `1,000` engine-noise negative windows.

2. **`REX-20261111-R2` — Capability-Conditioned 3D Spatial AR Track Markers (`[E-005]`) — Decision: `reject`**
   - **Candidate mechanism:** Rewire `src/ac_copilot_trainer/modules/track_markers.lua` (fixing `car.look` yaw wobble to spline tangent) and `racing_line.lua` (replacing static `80/150 km/h` colors) to render `CoachRuntime`'s `#938` thermal-gated capability envelope in 3D world space.
   - **Why rejected:** Both Seat 1A and Seat 1B prioritized pit prescriptions (`#956`) and multi-car coaching safety (`#955`) ahead of 3D world overlays; live voice cues (`#815` Run 07) plus the 2D HUD/tablet already deliver anticipatory braking targets without screen clutter, and no VR/AR HMD target is active on the rig (`E-009`).
   - **Reopening condition:** Reopen only if VR/HMD cockpit operation enters scope or operator live sessions demonstrate persistent spatial braking-point ambiguity despite calibrated voice cues (`#522` / `#815`).
