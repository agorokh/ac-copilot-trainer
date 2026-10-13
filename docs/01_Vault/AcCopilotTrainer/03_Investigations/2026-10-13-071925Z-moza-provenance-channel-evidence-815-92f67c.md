---
type: investigation
status: active
created: 2026-10-13
updated: 2026-10-13
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/03_Investigations/2026-10-13-024319Z-moza-passive-qualification-815-2e7b78.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# MOZA Part A2: controller attribution does not transfer through a similar trace

GPT-6 Astra Extra High agents investigated provenance, channel semantics and consumer eligibility,
then independently reviewed the synthesis. The four historical MOZA views still qualify only for
passive inspection and the specified offline numeric comparison. No importer or voice is activated.

## New provenance evidence

The native Magione/Porsche 101.956-second archive is explicitly named in the successful saved
`87ff/.scratch/issue764/scientist/iter02/report.json`, with its exact session identity and
`run.driver=alien`. This is autonomous-run attribution for that native archive; it does not establish
exclusive control at every sample or identify the similar MOZA cache. The native Spa/Huracan
191.116-second out-lap has weaker dated command/handoff association with an interrupted autonomous
run, without the same completed-report archive/session linkage.

The scoped 29 experiment receipts name 36 native archives: 34 in alien-driver reports and two in
handshake-driver reports. Do not classify all 185 archives from that subset. The full A2 acquisition
has 226 distinct files: 193 baseline inputs, 29 receipts and four source/handoff documents; 15
supplemental reads recheck already counted inputs. All captured files passed per-file stability and
end checks. This is not an atomic application snapshot. No raw sample arrays are published.

The operator recalls MOZA driving the green Porsche at Spa, and thinks earlier laps were probably
our controller. Thirteen native Porsche/Spa archives exist; five recent same-session candidates have
times 171.438, 160.847, 159.568, 165.722 and 145.510 seconds. No selected MOZA cache is Porsche/Spa.
The native headers lack livery and controller identity, so this is an unresolved recollection lead.
A native PB flag or hardcoded `source=in_game` cannot prove a human achievement.

## Channel and representation evidence

- Installed CSP documents `car.steer` as steering-wheel degrees; native archives copy it unchanged.
  MOZA's installed chart also displays degrees, but its physical input/scaling remains unproved.
  The earlier roughly 2.5/1.25 car-specific fits are not qualified conversions.
- Current H5 code displays speed in km/h, pedals in percent, reverse as -1 and neutral as 0.
  These are chart conventions; they do not establish raw hardware or post-assist equivalence.
- Native elapsed time is recorder-relative; official lap duration comes from a separate field.
  This supplies a possible start-window mechanism, not a proven historical cause of the Spa offset.
- MOZA uses a map-distance axis with piecewise progress mapping. Its presentation code interpolates
  cursor values, including gear. Initial steering chart bounds are not clipping thresholds.
- The H5 normalizer can default bad/missing values to zero and reconstruct time/distance/progress.
  Those display defaults must never certify measured source channels. Preserve strict unavailable
  states and the original missing/repeated/backward samples in future adapters.
- Native live steering is clamped differently from archive steering. This is a Part B contract
  concern to investigate across consumers, not a correction made or a proven regression here.

The richer record UI includes record/session/lap IDs, source roles and an AI-intervened badge, plus
condition/default metadata. These fields are absent from the four selected views. The readable
cache adapter uses a record/version tuple; source role is separate and the host filename mapping
was not inspected. Neither installed resources nor an AI Best selector identifies a cached trace.
Absence of an AI badge is not human-control proof. Protected assets and account stores were untouched.

## Voice reuse and acceptance

All four views remain unqualified for canonical import, reference coaching, silent voice shadow
stimulus, human PB/progression, plant fitting, production AI speed targets and diagnostic-event use.
Future channel-qualified unknown/AI stimulus could test silent scheduler plumbing against a separately
qualified reference. That would not demonstrate human improvement or correct teaching. Existing
verified plant/spline-backed AI apex targets preserve human-reference technique; current MOZA views
cannot be relabelled into that evidence contract. Parts B-D have not started.

Part A clauses are accounted for in the local report: bounded reader and prior candidate method are
evidenced; supported units and unsupported relations are explicit; machine decisions retain the two
offline uses; no faster cache is proved official. A bounded unqualified historical endpoint is valid.
No checkbox advances in this continuation, and the additionally requested observed session is pending.

## Authorized runtime attempt and resume

The user additionally authorized screen control: start AC first, then MOZA AI assist. The stable
baseline preceded this attempt. The observed assistant had no car/track selected, disabled AI master,
Professional/direct-steering preferences and existing brake-point sound enabled. No AC launch or
AI activation occurred: Windows rejected clicks because `PickerHost.exe` covered the target, including
after refocus/retry. User completion/dismissal of the capture picker is pending; no barrier was bypassed.

After the picker clears, use the observed UI to select Porsche/Spa, establish our controller is not
active, capture actual conditions/control transitions and collect one bounded completed lap if possible.
Keep partial/out-lap intervals separate, then disengage AI and leave the simulator stationary/paused.
The official guide warns of abrupt wheel torque when switching; do not infer settings from defaults.
[MOZA settings](https://support.mozaracing.com/en/support/solutions/articles/70000686033-game-settings-required-for-ai-driving).

Local report/decisions: `.scratch/moza-qualification/part-a2/report.md` and `qualification.json`.
Detailed hashed evidence is under `provenance/`, `semantics/` and `consumer-audit/`; `ui-evidence.json`
retains the exact failed actions, and `runtime-plan.md`/`provenance/capture_delta.py` define new collection.
Fresh delegated Tier-3 succeeded with truncated context. The Council grounder hit its upstream auth
wall; official primary-source browsing and independent Astra review were used, with no quorum claim.
