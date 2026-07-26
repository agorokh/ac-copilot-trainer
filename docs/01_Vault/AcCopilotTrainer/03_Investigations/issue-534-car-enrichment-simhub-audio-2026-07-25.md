---
type: investigation
status: active
created: 2026-07-25
updated: 2026-07-25
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/10_Rig/audio-5.1-positional-engine-2026-07-12.md
  - AcCopilotTrainer/03_Investigations/pr-480-simhub-launcher-toggle-2026-07-03.md
source_path: "AcCopilotTrainer/03_Investigations/issue-534-car-enrichment-simhub-audio-2026-07-25.md"
---

# Issue #534 — car enrichment, SimHub, and rear-engine audio

## Live reconciliation

Issue [#534](https://github.com/agorokh/ac-copilot-trainer/issues/534) was still
zero-delivered on `origin/main` (`01fd235`) at LOAD on 2026-07-25. The local
rig has 217 installed car directories: 215 readable UI records after tolerating
AC's invalid multiline-description JSON, plus two missing records. Raw classes
are not a usable authority (`street`/`race` plus inconsistent mod strings), and
GT metadata does not encode engine placement.

Live dependencies:

- [#117](https://github.com/agorokh/ac-copilot-trainer/issues/117) remains open
  and owns the not-yet-built Arduino fan/OLED prerequisite.
- [#119](https://github.com/agorokh/ac-copilot-trainer/issues/119) is closed and
  was explicitly dropped.
- The installed SimHub profile state has evolved since the older vault premise:
  the active profile names a dual-transducer Phase 2A layout with a TT25 pedal.
  Therefore “no pedal hardware” is stale, but it does **not** authorize reviving
  #119 or enabling a new class-gated pedal effect.

## Architecture and prepared delivery

The branch `feat/issue-534-car-class-enrichment` establishes:

- a stdlib-only, override-first Python resolver with a versioned,
  JSON-compatible YAML authority;
- the existing replayable `session` snapshot as the one identity stream,
  enriched before race-status consumption, caching, and fan-out;
- direct tablet consumption in the header;
- a supported .NET Framework 4.8 SimHub SDK plugin exposing class/id/provenance
  properties while keeping all network work off `DataUpdate`;
- heartbeat-based fail-closed `unknown` state, so a disconnected trainer cannot
  leave a stale class live in SimHub.

The actual installed fleet resolved totally: 197 metadata classifications,
18 curated engine-layout overrides, and two safe defaults. The plugin compiled
against installed SimHub 9.11 assemblies with zero warnings. Full `make
ci-fast` passed 3,503 tests / 73 skips at 87.1% coverage.

The repository does not auto-install the plugin or modify
`ShakeITBassShakersSettingsV2.json`. SimHub is an optional haptics peer, and
operator-created profiles remain operator-owned.

## Part E option matrix

| Option | Benefit | Cost/risk | Disposition |
| --- | --- | --- | --- |
| Keep AC/FMOD 5.1 | Already live-proven: 911 surround/front 0.959 vs M3 0.803 (~1.5 dB relative shift) | Subtle rather than theatrical | **Default. Preserve.** |
| Per-car sound mods | Can change emitter/content mix strongly | Manual per-car content, update drift, outside the enrichment authority | Optional manual content only. |
| Class-gated ShakeIt seat effect | One central class property; physical emphasis without changing game audio | Must stay low-gain and seat-only until TT25 pedal/channel/thermal state is reconciled | Recommended first experiment, not auto-enabled. |
| Voicemeeter split | Flexible channel remap/EQ | Adds a second persistent routing authority and failure surface | Not the default path. |

The safe recommendation is to leave AC/FMOD untouched. If the operator later
wants more rear-engine drama, bench one low-gain **seat-only** NCalc effect
using `[AcCopilotDataPlugin.CarClass]`. Do not route that experiment to the
TT25 pedal or enable pedal actuation without an explicit hardware/thermal
decision.

## Remaining gates

- Part C can consume the published class once #117 supplies real fan hardware;
  no absent actuator is simulated.
- Part D remains operator-gated. The operator must decide whether the live
  SimHub TT25 supersedes the dropped Arduino concept or whether a distinct
  per-class pedal successor is wanted.
- The plugin DLL can be built and wire-tested in-repo, but repo policy forbids
  automatic writes into SimHub's Program Files tree. Final property-picker/NCalc
  verification therefore requires the documented operator install/enable step.
