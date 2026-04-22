---
type: decision
status: active
created: 2026-04-21
updated: 2026-04-21
supersedes: ""
relates_to:
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/_index.md
---

# Screen firmware lives in the trainer repo (monorepo)

## Context

The ESP32-S3 touchscreen firmware and the AC Copilot Trainer Lua/Python code share a WebSocket protocol. The first draft of the plan called the firmware project `ac-copilot-screen` and planned it as a sibling repo at `C:\Users\arsen\Projects\ac-copilot-screen`. Arseny corrected this on 2026-04-21 — the firmware should live in the **same** repo.

## Decision

Firmware is **co-located** inside `ac-copilot-trainer` at:

```
ac-copilot-trainer/
├── firmware/
│   └── screen/          # PlatformIO project (JC3248W535)
│       ├── platformio.ini
│       ├── src/
│       ├── include/
│       ├── lib/
│       ├── secrets/     # gitignored (wifi.h, token.h)
│       └── test/
├── src/ac_copilot_trainer/     # existing Lua + manifest
├── tools/ai_sidecar/           # existing Python sidecar
└── docs/01_Vault/              # existing knowledge graph
```

## Consequences

- **Atomic commits across protocol changes.** When we extend WebSocket protocol v1, the Lua side, sidecar side, and ESP32 side can land in a single PR.
- **Single CI, single version story.** GitHub issues, PRs, releases, vault notes — all in one place.
- **One knowledge graph.** No cross-repo vault navigation; everything under `docs/01_Vault/`.
- **Dev environment cost:** PlatformIO adds a non-Python toolchain to the repo. `.gitignore` needs `firmware/screen/.pio/`, `firmware/screen/.vscode/`, `firmware/screen/secrets/`.
- **Pre-commit hooks.** Existing ruff/pytest-based hooks won't cover C++. Either exempt `firmware/screen/` from those hooks or add `clang-format` / `platformio run --check` hooks as a separate step.

## Alternatives considered

- **Separate repo `ac-copilot-screen`** — original plan. Rejected because WS protocol changes would need two PRs and cross-repo version pinning; vault would fragment.
- **Firmware as a submodule** — rejected; adds Git complexity for a single-developer workflow with no external release cadence.

## Follow-ups

- Update `pyproject.toml` dev docs / `WARP.md` to describe the `firmware/screen/` subtree and its dev prerequisites (PlatformIO Core or PlatformIO extension in VS Code).
- Extend `.gitignore` before first commit in `firmware/screen/`.
- Decide CI scope: run `platformio run` on PRs that touch `firmware/screen/**` only.
