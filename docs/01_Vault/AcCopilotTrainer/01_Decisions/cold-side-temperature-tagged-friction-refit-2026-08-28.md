---
type: decision
status: accepted
memory_tier: canonical
created: 2026-08-28
updated: 2026-08-29
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-746-749-repeatability-and-thermal-gate-2026-08-10.md
---

# Cold-side temperature-tagged friction refit

## Decision

Adopt issue #749's temperature-tagged friction-row approach for monotonically warming laps while
preserving the existing thermally stable cohort path unchanged.

A non-stationary lap is eligible only when it is valid, has a known compound and setup, meets the
existing channel-coverage and cross-wheel-spread gates, and every retained friction row has four
finite non-zero core-temperature measurements. The complete observed trajectory must remain at or
below the car's declared `optimalTempC`, and each wheel's trajectory must independently avoid a
cooling reversal greater than 0.5 C. Evidence that crosses the optimum or hides one cooling wheel
behind the other wheels' rising mean fails closed because the archive does not persist a trustworthy
post-peak tyre curve.

The static QSS runtime has no live tyre-temperature input. Therefore it never consumes the hotter
part of a warming lap as a cold-start assumption. The fitter tags every usable row with all four
wheel temperatures, identifies the globally coldest observed hottest-wheel value from every
four-wheel thermal observation (including samples without usable friction channels), and fits the
runtime projection only from friction rows within the existing 5 C stability half-width of that
value. Hotter rows remain diagnostic evidence. A speed bin without enough cold-band support stays
on its prior. Cold-band pressure cohorting uses that same retained-friction row set: thermal-only
or friction-invalid samples can set the temperature anchor, but they cannot equalize cohort
pressure across incompatible usable-grip regimes.

The normal raise-only self-play merge remains the only route by which this conservative projection
can lift an already-refined plant. Adoption counters therefore continue to describe bins that the
runtime actually consumes, not merely internal thermal observations.

## Alternatives

1. **Adopted: temperature-tagged friction rows with a cold-band runtime projection.** This admits
   repeatable cold-side drift without assigning warm grip to a cold tyre.
2. **Rejected: weighting all rows by thermal consistency.** Weighting still mixes incomparable tyre
   states and can let numerous warm samples dominate sparse cold evidence.
3. **Refuted: wait for a later settling window.** The measured Huracan/Spa trajectory repeats its
   warming cycle on each lap, so a settling budget does not create a stationary cohort.
4. **Rejected: lower the whole-lap stability threshold.** This removes the diagnostic guard without
   adding the row-level attribution needed for a safe runtime projection.

## Fail-closed conditions

- missing, zero, or non-finite core-temperature attribution on a retained row;
- unknown tyre compound, setup, or optimum;
- inadequate archive coverage or excessive cross-wheel spread;
- any observed core temperature above the declared optimum;
- fewer than the existing minimum friction-row count inside the cold reference band.

These conditions preserve the last valid plant. They do not lower thresholds or synthesize a tyre
performance curve that Assetto Corsa did not report.
