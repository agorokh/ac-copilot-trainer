---
type: investigation
status: completed
created: 2026-07-03
updated: 2026-07-03
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/pr-365-game-point-launcher-2026-06-29.md
  - AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md
source_path: "AcCopilotTrainer/03_Investigations/pr-480-simhub-launcher-toggle-2026-07-03.md"
---

# PR #480 — Game Point SimHub auto-start toggle (#479)

## Summary

PR [#480](https://github.com/agorokh/ac-copilot-trainer/pull/480) **MERGED** as squash
[`d15dd28`](https://github.com/agorokh/ac-copilot-trainer/commit/d15dd28) (2026-07-03T20:01Z),
closing [#479](https://github.com/agorokh/ac-copilot-trainer/issues/479). Surfaces **AUTO-START
SIMHUB** as a themed launcher checkbox instead of a `settings.json`-only flag, so one launch of Game
Point can bring up the whole rig (sidecar + screen + voice + **SimHub haptics**).

**Convenience, not datapoints:** SimHub reads the same AC shared memory the sidecar reads — it is a
haptics/ShakeIt peer, not a coach data source (see
[[track-titan-telemetry-extraction-feasibility-2026-06-27]] for the same "reads our shared memory,
adds no new raw signal" finding applied to Track Titan). Same conclusion drove #479's scoping: this
is a one-icon-everything convenience.

## What shipped

- **Decision:** packaged default stays `start_simhub=False` (opt-in), matching the house pattern
  (PR #207 `useImportedReference=false`). Enabling is one persisted click.
- `tools/rig_launcher/view.py` — themed `AUTO-START SIMHUB` `Checkbutton`; **UI is the source of
  truth** (the checkbox's value drives the model via `on_toggle_simhub(enabled: bool)`).
- `tools/rig_launcher/supervisor.py` — `set_start_simhub` persists + applies to the live config
  (`dataclasses.replace`) so the next poll starts/adopts SimHub; a persist failure surfaces on stderr
  (not silent) and preserves the file.
- `tools/rig_launcher/settings.py` — `update_settings` hardened to three guarantees:
  **no-secrets** (only the non-secret template schema is written — a stray `token` can never
  round-trip); **preserve-manual-work** (a present-but-malformed/unreadable/non-object settings.json
  is left untouched and raises, never overwritten with defaults); **atomic + concurrency-safe**
  (unique `tempfile.mkstemp` + `os.replace`, not a shared fixed `.tmp`).
- Docs: `docs/10_Development/14_Game_Point_Launcher.md` (new *SimHub auto-start* section) + the
  `AGENTS.md` launcher bullet. 15 launcher tests (incl. secret-strip, preserve-malformed/non-object,
  toggle→autostart, non-blocking guarantee).

## Verification (operator-grade)

Built the **real** `LauncherView` against a real `GamePointSupervisor` + temp `settings.json`, walked
the widget tree to confirm the `AUTO-START SIMHUB` checkbox exists + is wired, invoked its real
command, and observed `settings.json` flip `start_simhub` True→False bidirectionally with other keys
preserved — **PASS**. Real launcher (`python -m tools.rig_launcher`) also launched clean on the rig
(no construction error). Note: a headed cross-session screenshot was skipped (background-launched GUI
is session-isolated from the interactive desktop, and `request_access` was avoided on the unattended
run); the widget-introspection + real-file-write proof stands in for it.

## Review hardening (4 rounds — cursor / antigravity / Qodo)

Self-hosted daemon (EPIC #818) was the primary reviewer; Gemini/Codex were quota-limited, Qodo
endorsed the approach then raised a no-secrets gap. Rounds: (1) cursor MEDIUM settings-merge + UI/model
coupling; (2) antigravity HIGH preserve-manual-work + MEDIUM temp-race + Qodo token thread; (3) cursor
MEDIUM non-object root. All fixed with tests; cursor (gate) ended clean, Qodo thread resolved, no
unresolved threads, CI green.

## Follow-up

- [#481](https://github.com/agorokh/ac-copilot-trainer/issues/481) — hermetic test: `tests/test_ai_sidecar_external.py::test_external_bind_accepts_env_token`
  reads the rig's `AC_COPILOT_SIDECAR_SERIAL_PORT` (=COM6) from the real env; passes with it unset
  (CI is clean), so it only reds local `make ci-fast` on a configured rig. Separable (different
  subsystem, from #463); surfaced during this run.
