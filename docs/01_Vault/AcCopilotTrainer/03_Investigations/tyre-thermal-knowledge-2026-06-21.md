---
type: investigation
status: active
created: 2026-06-21
updated: 2026-06-21
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/03_Investigations/setup-aware-coaching-2026-06-20.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
issue: https://github.com/agorokh/ac-copilot-trainer/issues/264
---

# Verified GT3 tyre-thermal knowledge (for tyre_model.py)

Adversarially-verified research (4 expert lenses → skeptical red-team that corrected 8 rules) for
the coaching tyre model. Inputs available: per-wheel **core** temp (CSP `tyreCoreTemperature`, now
persisted by #266), **cold** pressure (setup), derived per-corner g/slip. **Not** available: band
(inner/centre/outer) temps, surface temp, live hot pressure, compound/weather metadata.

## Verified parameters
- **Optimal core-temp window** (°C, bulk-average): soft **70–100**, medium **75–105**, hard
  **80–110**, wet 55–80. Cold-start grip onset ~**35–45**°C.
- **Degradation-onset warning 100–105**°C; **critical 115–140** (compound-dependent; soft fails
  earlier). Above critical → back off / box (a risk trigger, NOT a blistering diagnosis).
- **Pressure↔core coupling (CORRECTED):** ~**+1 psi per 10 °C** core rise (≈0.10–0.14 psi/°C at GT3
  pressures, ideal-gas at constant V). The red-team killed a physically-impossible 0.35–0.55 psi/°C
  claim. Hot pressure is **modelled** (cold + coupling), never measured.
- **GT3 target HOT pressure 26–29 psi**; nominal cold front 27–28.5, rear 26–27.5.
- **Warm-up:** 2–3 laps to steady core; rise 2–4 °C/lap early; warm-up-vs-steady split at ~0.15 °C
  per 100 m (or >2 °C/lap).
- **Imbalance thresholds (peak-to-peak, °C):** per-wheel >10 (single outlier >15); front−rear axle
  >6–10; left−right >6–8 (heavily confounded by track corner-direction bias).
- **Pressure→steady-core sensitivity:** −1 psi cold → roughly +2 to +5 °C steady core (DIRECTION
  only; verify next lap).

## Honest data limits (encode these as caveats, do not "simplify" away)
- Core is a **bulk average** — no edge-localized (camber/blistering) conclusions; surface temp (the
  grip-relevant layer) is unavailable, so window/onset calls are inferences.
- Thermal overheat and mechanical wear **both** raise core temp — core alone **cannot** separate
  them (needs a back-off recovery test + a reference-corner lat_g drop).
- Left-right / front-rear asymmetry is **confounded by track direction** — no balance call without a
  reference-lap comparison.
- Lap-time-vs-thermal framing is **qualitative** only (grip is ~flat inside the window); require a
  lap-time trend to claim degradation.
- Compound/wet windows fire **only** if compound+weather metadata is supplied out-of-band.

## Diagnostics computable from core temp alone (the Tier-A tyre set)
cold (all <70), never-reaches-window, warm-up-vs-steady classification, overheat (>105 sustained
3+ laps), critical (>115), axle/side/single-wheel imbalance (causes as ranked HYPOTHESES, check cold
pressure/camber first), balanced (<5 °C spread). Everything tying cause to lock/spin/pressure needs
the derived g/slip or live channels — emit as suspicions.

Full research output: session task `w7f01zb7z`. Build target: `tools/ai_sidecar/tyre_model.py`
(mirror `setup_knowledge.py` data + `corner_attribution.py` honest Tier-A/Tier-B split).
