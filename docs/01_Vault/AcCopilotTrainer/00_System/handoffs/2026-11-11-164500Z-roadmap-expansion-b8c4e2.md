---
type: handoff
status: active
created: 2026-11-11
updated: 2026-11-11
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/401
relates_to:
  - AcCopilotTrainer/00_System/Roadmap.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-11-064600Z-issue401-roadmap-no-drift-4a7c90.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-10-24.md
  - AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md
---

# Session Handoff — Roadmap Expansion (`2026-11-11`)

## Summary

Executed `/roadmap-expansion` (v1.1) on `agorokh/ac-copilot-trainer` at `origin/main` `bcf3878c55722fe70705a12682d86ed049356672` following the `2026-11-10`/`2026-11-11` closures of `#938` (`REX-20261024-02`), `#815` (MOZA + live voice/HUD acceptance), `#534`, `#813`, and `#86` (ESP32 `COM6` Pocket Technician + Setup Exchange device acceptance).

Grounded 10 codebase/vault evidence records (`E-001`..`E-010`), ran 8 fresh 4-lens external web searches (`W-001`..`W-008`), and convened an independent 2-pass council (`gpt:chatgpt_ask` + `mistral:mistral_second_opinion`; `gemini` unauthenticated `guest_session`; `perplexity`/`kimi`/`grok` unmounted -> `provisional` council coverage, all candidates capped at `explore`). Verified zero file-seam overlap against `#529` (`REX-20261024-01` & `-03`) and `#117`, injected hub pitfalls from `agorokh/template-repo`, filed three tracker issues, and posted one operator summary comment on `#401`.

## Finalist Decision Slate (`explore` / `provisional`)

1. **`REX-20261111-01` — Advance:** [#955](https://github.com/agorokh/ac-copilot-trainer/issues/955) — *Explore traffic-aware coaching eligibility and evidence quarantine* (`src/ac_copilot_trainer/{ac_copilot_trainer.lua,modules/traffic_context.lua}`, `tools/ai_sidecar/{traffic_eligibility,coaching_runtime}.py`, `tools/lap_qualification.py`). Suppresses solo pace cues into occupied braking/apex space and quarantines traffic-compromised laps from clean progression/plant cohorts.
2. **`REX-20261111-02` — Advance:** [#956](https://github.com/agorokh/ac-copilot-trainer/issues/956) — *Explore pit-box telemetry prescription cards on Pocket Technician* (`tools/ai_sidecar/{setup_prescription,tyre_model,external_protocol,server}.py`, `firmware/screen/src/ui/screen_pocket_technician.cpp`, `firmware/screen/simulator/`). Wires uncalled sidecar setup/tyre intelligence to pit-rechecked cold-pressure prescription cards on `COM6` with readback-verified `experiments.jsonl` logging.
3. **`REX-20261111-03` — Hold:** [#957](https://github.com/agorokh/ac-copilot-trainer/issues/957) — *Hold: audit condition-matched multi-session progression overlap* (`tools/coaching_lake/{progression_audit,build_analytics}.py`, `tools/session_review/report.py`). Held until `>= 6` human-qualified traffic-clean sessions exist on one `(car, track, layout)` combo and the 0.5-day offline overlap + 1,000-replicate null/synthetic calibration audit passes.

## Rejected Candidates (Annex §4)

- **`REX-20261111-R1` (`reject`):** Push-to-talk cockpit speech pit radio (`#672` shared FMOD speaker bleed without AEC + 3 unassigned physical rig buttons beat speech; Seat 1A `hold` preserved as dissent with quantitative reopening gate).
- **`REX-20261111-R2` (`reject`):** Capability-conditioned 3D spatial AR markers (no active VR/HMD target; voice + 2D HUD suffice unless spatial braking ambiguity persists).

## Next Session Entrypoint

- Full annex: `docs/01_Vault/AcCopilotTrainer/03_Investigations/roadmap-expansion-2026-11-11.md`
- Await operator Go/No-Go on `#401` to run bounded `explore` experiments `#955` and/or `#956` (completely disjoint file seams), or continue `#529` (`REX-20261024-01` / `-03`). Do not start `#957` until its Hold promotion gate clears.
