# CoachingOracle (Track Titan overlay OCR)

Issue **#333** — swappable external coaching source for the harness referee and human curriculum.

## Module

| Path | Role |
| ---- | ---- |
| `tools/ai_sidecar/coaching_oracle.py` | Pure parser + `TrackTitanScreenOracle` (Windows-only capture/OCR plumbing) |
| `tools/ai_sidecar/tt_overlay_ocr.ps1` | Bundled PowerShell helper: GDI capture, crop/upscale, `Windows.Media.Ocr` → JSON stdout |
| `tests/test_coaching_oracle.py` | Pure parser tests (runs on any OS; no Windows/OCR in CI) |

## Contract

- **`CoachingOracle.get_coaching() -> CoachingSnapshot | None`** — `None` when unavailable (off-Windows, helper failure, malformed helper JSON).
- **`parse_overlay_text(full_lines, debrief_lines?)`** — pure; maps OCR lines to `CoachingSnapshot` (3-decimal delta filter, post-lap debrief gate, technique-only advisories).
- **`debrief_to_advisories(snapshot)`** — emits `coach_handoff`-compatible rows; `suggested_setup_delta` is always `None`.

## Guardrails

- Reads the operator's **on-screen overlay** only (personal/local use).
- Never touches Track Titan cloud API or Cognito tokens.
- Captures land in `%LOCALAPPDATA%\ac-copilot-trainer\ocr` and are deleted in a `finally` block.

## Vault

Strategy ADR and live-verification investigation:

- `docs/01_Vault/AcCopilotTrainer/01_Decisions/track-titan-coaching-oracle-strategy-2026-06-27.md`
- `docs/01_Vault/AcCopilotTrainer/03_Investigations/track-titan-telemetry-extraction-feasibility-2026-06-27.md`

## Local checks

```bash
pytest tests/test_coaching_oracle.py -q
make ci-fast
```

Live smoke (Windows rig with Track Titan overlay visible): instantiate `TrackTitanScreenOracle()` and call `get_coaching()`.
