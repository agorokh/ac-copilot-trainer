---
type: investigation
status: resolved
memory_tier: project
last_updated: 2026-06-30T08:36:35Z
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/01_Decisions/voice-coach-architecture-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/pr-365-game-point-launcher-2026-06-29.md
---

# PR #394 voice reliability (#392)

Issue [#392](https://github.com/agorokh/ac-copilot-trainer/issues/392) asked for the packaged Game
Point launcher to include voice sidecar audio deps and for the launcher status to reflect the real
sidecar voice runtime state.

## Shipped

- Sidecar `/health` includes `voice` runtime state with `configured`, `enabled`, `state`,
  `disabled_reason`, `backend`, `bank_configured`, `reference_configured`, and `tts_enabled`.
- Public health responses use `public_voice_runtime_status()` so path-shaped disabled reasons are
  sanitized before they leave the unauthenticated health endpoint.
- Game Point launcher derives the voice row from sidecar `/health`, including stale bank disabled
  reasons, adopted no-voice sidecars, old sidecars with no `voice` key, and observer-only sidecars
  when playback was requested.
- PyInstaller collection now includes the installable voice floor (`numpy`, `sounddevice`, `pyttsx3`)
  and uses `--collect-binaries` for `sounddevice` plus opt-in `rtmixer` / `pa_ringbuffer` when present.
- TTS fallback waits for pyttsx3 worker startup before reporting `state=tts`.

## Verification

- Final local CI on head `be2fb50`: `make ci-fast PYTHON=/Users/arseny_gorokh/Projects/ac-copilot-trainer/.venv/bin/python`
  passed (`1893 passed, 75 skipped`, coverage 85.43%, `ci-fast: OK`).
- Focused tests passed: `tests/test_rig_launcher.py`, `tests/test_ai_sidecar_observability.py`,
  `tests/test_server_observer_wiring.py`, `tests/test_voice_engine.py`, `tests/test_voice_client.py`
  (`96 passed`).
- GitHub checks on `be2fb50` passed (`build`, `Canonical docs exist`, `conformance`; vault automerge
  skipped). Required bot-review cooldowns were observed through 2026-06-30T08:24:15Z; remaining
  current Codex threads were resolved after their fixes were present in the branch.
- Final-head local runtime smoke started real sidecar processes and ran the real launcher CLI:
  stale schema-v1 bank -> sidecar disabled + launcher `voice.state=DISABLED`; no-voice sidecar
  adopted by voice-requesting launcher -> `DISABLED`; missing reference path -> public health reason
  `failed to load reference: No such file or directory` with no path leak.

## Windows packaged proof

On the rig `pc` before later review-fix commits, throwaway worktree
`C:\Users\arsen\Projects\ac-copilot-trainer-issue392` built `dist\AC-Copilot-Game-Point.exe` with
PyInstaller 6.21.0. The frozen exe loaded a temporary schema-v2 tone bank:

- `/health.voice={"backend":"sounddevice","enabled":true,"state":"enabled","bank_configured":true,"reference_configured":true}`
- no `ModuleNotFoundError` / `No module named` in the frozen sidecar log
- stale schema-v1 bank surfaced `state=disabled` through both frozen sidecar and frozen launcher,
  with the schema-v2 re-bake reason

After the review-fix commits, the Windows host `pc` (`100.75.251.87`) was offline in Tailscale and SSH
timed out, so the final Windows packaged smoke could not be rerun before merge. The final commits did
not change PyInstaller collection flags; the changed runtime behavior was re-smoked locally as above.
