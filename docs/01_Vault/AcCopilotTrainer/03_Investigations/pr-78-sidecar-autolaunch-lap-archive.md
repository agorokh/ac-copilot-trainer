---
type: investigation
status: active
created: 2026-04-22
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-and-csp-apps-integration.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
---

# PR #78 — Sidecar auto-launch + per-lap archive with setup capture

Closed issue #77 on 2026-04-21. Two initiatives landed together because they touched overlapping files. This is surface-level reference; the PR body has the canonical details.

## Initiative A — Sidecar auto-launch

**Motivation:** removed the old Settings "Set ws://127.0.0.1:8765" button and the requirement to manually run `python -m tools.ai_sidecar`. The trainer Lua now spawns the sidecar itself at module load.

**Mechanism:** CSP's `os.runConsoleProcess` with `terminateWithScript=true` (mirrors the shipped CSP `joypad-assist/mobile` pattern). Launch target is `src/ac_copilot_trainer/start_sidecar.bat` which walks parent directories until it finds `tools/ai_sidecar/`. Honours `AC_COPILOT_REPO_ROOT` env-var override for non-standard layouts.

**Health monitoring:** new `ws_bridge` helpers:
- `M.startSidecarIfNeeded()`
- `M.sidecarSpawnedAlive()`
- `M.sidecarConnected()`

Re-launches within ~5 s if the sidecar dies.

**Settings UI:** sidecar URL section is now **status-only** (URL is baked to `ws://127.0.0.1:8765/` by the launcher). Removed the editable field that used to let users point elsewhere.

**Relevance for rig-screen / EPIC #59:** the screen can assume the sidecar is running whenever the trainer is loaded. No "please launch the sidecar first" step in the onboarding flow.

## Initiative C — Per-lap archive

**Motivation:** stop discarding 99% of telemetry. Every completed lap now writes one JSON file containing the full per-sample trace + active car setup snapshot + corner features + coaching context. This builds the dataset for future RAG / classifier / fine-tune work without any extra capture step.

**File location:** `journal/laps/lap_*.json` under the trainer data root. New per-session UUID is generated at app load for grouping.

**Disk policy:** default enabled, 500 MB cap, oldest-first rotation. Settings UI exposes toggle + cap + current usage.

## Schema v1

Forward-compatible with imported MoTeC CSV reference laps (Initiative B is future scope). Columnar trace samples (array-of-arrays) saves ~50% disk vs array-of-objects.

```json
{
  "schema_version": 1,
  "source": "in_game",
  "import_format": null,
  "lap_uuid": "...",
  "session_uuid": "...",
  "exported_at": "2026-04-11T18:30:00Z",
  "car": {"id": "...", "displayName": null},
  "track": {"id": "...", "layout": null, "lengthM": 1700},
  "conditions": {
    "trackGripLevel": 0.95,
    "ambientTempC": 22,
    "trackTempC": null,
    "weatherType": null
  },
  "lap": {"lap_n": 5, "lap_ms": 58000, "is_pb": false, "is_valid": true},
  "setup": {
    "hash": "abc123de",
    "snapshot": {"TYRES.PRESSURE_FRONT": "27.5", "WING.REAR": "5"}
  },
  "trace": {
    "samples_count": 2000,
    "fields": ["spline","speed","eMs","throttle","brake","steer","gear","px","py","pz"],
    "samples": [[0.001,200.5,0,1.0,0,0.05,5]]
  },
  "corners": [{"label":"T1","entrySpeed":211,"minSpeed":84}],
  "coaching": {
    "rules_hints": ["..."],
    "sidecar_debrief": "...",
    "corner_advice_used": {"T1":"BRAKE HARD NOW."}
  }
}
```

## Setup capture — reuses the same API PT uses

`setup.snapshot` is flattened `{"SECTION.KEY": "value"}` pulled from `setup_reader.snapshotActive()`, which wraps `ac.INIConfig.carData(0, 'setup.ini')` (same mechanism Pocket Technician uses — see [`csp-app-pocket-tech-setup-exchange-2026-04-21`](csp-app-pocket-tech-setup-exchange-2026-04-21.md)).

Hash is SHA-1 prefix of the normalised key-value string so we can detect "same setup, different laps" without diffing the whole dict.

## Files changed (5)

| File | Lines | Purpose |
|------|-------|---------|
| `src/ac_copilot_trainer/start_sidecar.bat` (new) | ~60 | Repo-root walk-up + `AC_COPILOT_REPO_ROOT` override + Ollama env defaults + `py -3` fallback |
| `src/ac_copilot_trainer/modules/ws_bridge.lua` | +100 | `startSidecarIfNeeded`, `sidecarSpawnedAlive`, `sidecarConnected` |
| `src/ac_copilot_trainer/modules/lap_archive.lua` (new) | 290 | Schema v1, `buildRecord`, `write`, `rotate`, `stats` |
| `src/ac_copilot_trainer/modules/hud_settings.lua` | ±37 | Sidecar URL = status-only; new lap archive section |
| `src/ac_copilot_trainer/ac_copilot_trainer.lua` | +81 | Wire archive at lap completion + auto-launch + session UUID + Settings VM |

## Relevance for rig-screen + future ingestion

- **Touch screen coaching-summary tile** can read this archive directly. No new network path needed; next session can implement `lap_list_request` / `lap_detail` protocol on top.
- **Setup selector** on the rig screen (per EPIC #59) can show the active setup snapshot from the latest lap record without running its own polling against AC.
- **Dataset for future ML**: ~250 KB per lap → 500 MB cap holds ~2000 laps. Enough to build a reference-lap DB per (car, track) pair for RAG-based coaching.

## Open

- In-game manual smoke: drive a lap, confirm `journal/laps/lap_*.json` exists + Settings shows count.
- In-game resilience smoke: kill the auto-launched sidecar, verify it relaunches within 5 s.
- Phase-2 screen tile: "Latest Lap" card reading the newest file + scaling down the trace for small-screen rendering.
