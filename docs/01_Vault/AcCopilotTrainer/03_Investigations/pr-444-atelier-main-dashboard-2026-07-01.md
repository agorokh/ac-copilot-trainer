---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-01
updated: 2026-07-02
issue: https://github.com/agorokh/ac-copilot-trainer/issues/432
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/pr-410-racing-atelier-design-package-2026-06-30.md
  - AcCopilotTrainer/03_Investigations/csp-cdata-callable-guards.md
  - AcCopilotTrainer/01_Decisions/dashboard-visual-design-figma.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# PRs #444/#445/#446 — Racing Atelier runtime adoption: what review + live capture caught (#432)

**Merged 2026-07-02 UTC:** [#444](https://github.com/agorokh/ac-copilot-trainer/pull/444)
(`82ced33`, in-game main-dashboard card + COACHING tile), [#445](https://github.com/agorokh/ac-copilot-trainer/pull/445)
(`6f04755`, launcher photo-parity), [#446](https://github.com/agorokh/ac-copilot-trainer/pull/446)
(`91ca72a`, rig-screen badge/delta fixes — flashed to the device pre-merge). Epic #432 Parts A2+B
delivered; Part C conformance fix landed under #86.

## What shipped (operator-directed evolution)

WINDOW_1 = the **main instrument card** (560x480): header badge + name, 62px GEAR/KM-H vitals
left, 20-cell RPM strip with standing shift/redline zones (92%/97% of live `rpmLimiter`,
single-sourced from `realtime_coaching`), 66px CommandVerb (+ new reference-independent
`SHIFT UP` rung, top-gear-gated), brake-point hero, 12-cell approach SegmentBar, entry-delta
DeltaBar with approach-window-gated signal tones. WINDOW_0 = the **COACHING voice tile**
(advisory > post-lap hints > debrief > placeholder; no duplication of card data; anchored
0.60W right of the virtual mirror). Launcher: StatusField summary chip, hairline rows,
uppercase tones, weighted button grid, private GDI font loading.

## Reusable findings (will bite any future font/HUD work)

1. **DirectWrite family ≠ Google Fonts web name.** Bundled statics' name tables say
   `Saira SemiCondensed` (no space); the spaced web name silently misses `FindFamilyName`
   and CSP falls back at render time without an error. Lock:
   `tests/test_hud_atelier_card.py::test_bundled_font_family_names_match_specs`.
2. **Upstream font files can be mislabeled** — the firmware-source `Saira-Bold.ttf` was
   internally Saira *Thin* (name IDs Thin, OS/2 700). Verify ID1/ID2/usWeightClass before
   bundling; regenerate via fontTools instancer.
3. **`Weight=ExtraBold` is not a CSP DWriteFont token** — use numeric `Weight=800`.
4. **Locale `string.upper` mangles UTF-8** on Windows (0xE2 of `—` → 0xC2) — use
   `asciiUpper`; surfaced as a lupa UnicodeDecodeError, would be tofu in-game.
5. **Window growth must re-derive the autoPlace anchor** — the 480px card at the old
   0.78H anchor put the delta section off-screen at 1080p, re-forced every load. Anchor
   now derives from `MANIFEST_WINDOW_SIZES` + bottom clamp.
6. **CSP Lua `car.gear` is normalized** (-1/0/1+), unlike the raw shared-memory index
   (0=R/1=N/2=1st) used by `racing_telemetry.csv_display_gear`. Evidence: stock AC gauge
   showed the same numeral as the card in two live captures. Codex flagged this twice from
   the raw-probe doc; rebutted with the gauge-parity paste.
7. **Live capture beats review**: one in-sim frame caught 4 defects 15 review agents missed
   (negative-floor clamp overshoot rendering -21, 40px number vs scale-label collision,
   verb arrow touching the glyph, full-alpha neutral fill). All are lupa regressions now.
8. **Reference-delta semantics**: `+N` over the NEXT corner's entry speed on a straight is
   normal — imperatives/signal tones must gate on the approach window or the delta row
   contradicts the verb ladder.
9. **The tile title is an OCR anchor**: `coaching_oracle.py` keys on "reference will
   appear" — the COACHING tile keeps that placeholder line so the TT oracle still parses.

## Rig ops notes

- carcsw hijack landed only on auto_drive's own full launch cycle (1/4 attempts overall);
  `--skip-launch` on daemon-launched sessions failed 3x — CSP's CarControls0 scan window
  appears tied to session init. Retry full cycles.
- **Open flake:** both `racing` and `ggv` drivers stalled ~450-580m from the practice-mode
  pit start (car ends 0 km/h in gear). Coaching/reference still went live; needs its own
  investigation before long unattended sim runs.
- Screen captures grab whatever is frontmost — stop scraping the moment the operator uses
  the desktop (their windows land in the frames).
- AC app junction: temporarily pointed at the session worktree for live verification;
  **restored to the primary checkout** (post-ff-sync) at session end.
- Rig screen: #446 build flashed to COM6 (esptool hash verified) BEFORE merge; the device
  runs exactly the merged code. Operator-pending: on-glass photo vs `esp32_rig.png`.

## Follow-ups

- [#442](https://github.com/agorokh/ac-copilot-trainer/issues/442) telemetry-learned shift
  points (trace schema + per-corner exit gearing).
- Autonomous-driver pit-start stall (above) — not yet filed; next session should file
  against the harness after a repro with `--drive-seconds` logging.
- Operator visual sign-offs: rig screen photo (#86), in-sim BRAKE-state glance at the
  merged card (evidence so far: READY/PUSH states + all unit-locked geometry).
