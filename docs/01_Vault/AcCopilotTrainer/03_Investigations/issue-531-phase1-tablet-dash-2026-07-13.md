---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-13
updated: 2026-07-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/531
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-511-partd-tablet-voice-endpoint-2026-07-11.md
  - AcCopilotTrainer/01_Decisions/usb-serial-screen-transport-2026-07-02.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# #531 Phase 1 — tablet GT dashboard live on the P7 (/tablet/dash)

## What shipped (PR #547, squash `9265521`, 2026-07-13)

The 7" PRITOM P7 renders the modal Racing-Atelier GT dashboard, served by the sidecar at
`/tablet/dash` over USB `adb reverse tcp:8765` (same trust model as `/tablet/voice`). The
frozen design artifacts (`DESIGN_SPEC.md` + `reference_mock.html`) landed on main with it.

- **Part A** — self-contained DOM/CSS/JS port of the reference mock: RACE 5 fixed bands +
  COACH/MAP/STINT sweep (dots + swipe), vendored TTFs from an exact-name allow-list
  (`/dash/fonts/*`), change-gated <=15 Hz DOM writes via `setInterval` (NOT rAF — a hidden
  WebView freezes rAF), LIVE/STALE/WAITING at a 3 s freshness threshold on every stream.
- **Part B** — `telemetry_tick` routes to `browser`-class peers
  (`TELEMETRY_TICK_CLIENT_CLASSES`; a peripheral frame, not a state topic). Sidecar caches
  `setup.active`/`session`/`connection` snapshots per producing peer, replays them on
  `state.subscribe`, and drops them when the producer disconnects. Trainer Lua broadcasts
  `setup.active` on WS (re)connect AND on every `session` re-emit, with cleared-on-confirmed
  no-setup, cleared-on-unresolved at the session-change edge, readable-file-only paths
  (`setup_reader.activeSetupState`), and a bounded per-frame retry until the send settles.
- **Part C-min** — `telemetry_tick` carries `rpm_max` (`car.rpmLimiter`, must be positive)
  + `lap_time_ms` (`car.lapTimeMs`), optional + validator-checked.

## Durable findings

- **P7 viewport**: 186 dpi → ~1.16 devicePixelRatio → `width=device-width` yields ~881x516
  CSS px and CLIPS a fixed 1024x600 design. Fix: `width=1024, user-scalable=no` (1:1
  physical mapping). Found only via on-device screencap.
- **rAF freezes in hidden WebViews** — kiosk dashes must render off `setInterval`.
- **Identity-replay ordering**: the cache replays `setup.active` BEFORE `session`; a
  first-session "identity change" clear wiped the just-replayed name (caught on the live P7
  soak mid-review, fixed same hour). Client clears identity-scoped state only when a PRIOR
  identity existed.
- **Fully Kiosk on Android Go**: Kiosk Mode unavailable (Android Go 10+), fullscreen works;
  Start URL persists only via Settings → Web Content Settings (the Quick Start field does
  NOT persist); adb `input tap` + screencap drives it (the #511 recipe). Start URL is now
  configured to `http://127.0.0.1:8765/tablet/dash`.
- **Feeder harness**: `.scratch/dash_feeder.py` plays the Lua peer with the real checked-in
  911 GT3 R schema — full dash verification without AC; reusable for Part F.

## Verified (observed)

- On the P7 in Fully Kiosk fullscreen: all 5 bands edge-to-edge, zero clipping; the
  car-adaptive board renders the REAL 911 ranges (BIAS 63.0%, TC 3/12, ABS 7/12, no
  TC-CUT/MAP tile); braking-zone BRAKE takeover with countdown + ABS pip; MAP page sweep
  with live spline/delta; STALE state (unlit ribbon, `— / —`) on producer stop; fuel-as-
  a-decision (18.4 laps left · 2.61 L/lap from client-measured burn). Screencaps on PR #547.
- `make ci-fast` green; 14 new tests (endpoint/protocol/lupa).
- Review: 6 rounds — 16 Codex P2s fixed, Qodo 3 bugs fixed, daemon MEDIUM fixed; daemon
  CRITICAL + HIGH replied-invalid with pasted evidence (`lap_time_ms` pre-existing at
  `external_protocol.py:484` since `e5103be`; no `_process_subscription` symbol exists —
  fan-out is broadcast/class-based); 2 WONTFIX-with-rationale (burn survives same-identity
  stint resets; page sweep follows the pixel-faithful mock).

## Remaining on #531 (Phase 2+)

Parts D (live pressures/brake-temps/wear + `tc_active`/`abs_active` + fuel-per-lap fields),
E (shift cue + `audio_routing`), F (COACH/MAP/STINT depth — incl. reconciling spec-prose
"boards never swept" vs the mock's full-region sweep), G (native-audio latency gate),
H (SimHub fusion, optional), I (mic upstream). Water/oil temp stays DATA-GATED. The live
in-sim acceptance pass (car swap on the rig, real `rpm_max` from CSP) rides on the next rig
session — the AC app junction serves the primary checkout, which must be on merged main
first (it was parked on `feat/issue-479-simhub-launch-toggle` at delivery time, with `main`
pinned by the `codex-issue-381-voice-bank-timing` worktree).
