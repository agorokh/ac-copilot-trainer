# WARP.md

Long-form **operator guide** for humans and agents (Warp terminal and others). Keep `README.md` short; put depth here.

## Project intent

_Describe what this software does after you specialize the template._

## Environment

- Python version: see `pyproject.toml` classifiers / CI.
- Create venv or use `uv` per team preference.
- Copy `.env.example` → `.env` for local secrets.
- **Copier** (optional, for bootstrapping or updating from this template): `pip install copier` or `pip install -e ".[bootstrap]"` from a clone. See [BOOTSTRAP_NEW_PROJECT.md](docs/00_Core/BOOTSTRAP_NEW_PROJECT.md).

## Common commands

```bash
make ci-fast          # format, lint, tests (pytest + coverage floor), bandit, policy checks
make test             # pytest (same as ci-test: includes coverage gate)
make lint             # ruff check
make format           # ruff format
make hooks-install    # pre-commit install
```

## Layout

- Application code: `src/project_template/` (rename on bootstrap).
- Tests: `tests/`.
- Docs: `docs/`; durable architecture memory: `docs/01_Vault/ProjectTemplate/`.
- Automation: `scripts/`, `.github/workflows/`.

## Branching and memory

- Branch from `main`; open PRs early.
- **Tooling:** [docs/00_Core/TOOLCHAIN.md](docs/00_Core/TOOLCHAIN.md) (Cursor, Claude Code, Desktop, MCP).
- Update vault handoff notes when ending a session that will resume later.
- Optional: maintain a short tail in `CLAUDE.md` between `SESSION` markers for Claude Code; keep detailed narrative in archived session files under `docs/90_Archive/sessions/` if you use that pattern.

## Security and data

- No secrets in the repo; use secret managers in deployment.
- If the project handles PII or evidence files, document allowed paths and **agent write bans** in the vault invariants and enforce with hooks.

## Local ML / heavy dependencies

_If applicable: document HF cache dirs, GPU/MPS usage, air-gapped constraints._

## Troubleshooting

_Add project-specific debugging tips as you learn them._

### AC Copilot Trainer (CSP Lua app)

- **Render API diagnostics:** In `src/ac_copilot_trainer/ac_copilot_trainer.lua`, set `config.enableRenderDiagnostics = true` and reload the app to restore the 60s `render_diag` run (API probe logs, red/green/blue debug shapes, `[DIAG]` UI). Default is `false` so normal driving sessions stay clean (issue #41).
- **Coaching HUD (issue #43):** In the same `config` table, `coachingHoldSeconds` sets how long post-lap hints stay on screen (fade uses the last few seconds of that window). `coachingMaxVisibleHints` is an integer **1–3** limiting how many `buildAfterLap` lines appear in the Coaching window and how the main-window strip counts “+N more” (invalid values are clamped into **1–3**). Reload the CSP app after edits. Telemetry-only mode (`wsSidecarUrl` empty) is unchanged.
- **WebSocket sidecar (issue #45):** Install optional deps `pip install -e ".[coaching]"` (adds `websockets`). Start the server with `python -m tools.ai_sidecar` (default `ws://127.0.0.1:8765`). Set `config.wsSidecarUrl = "ws://127.0.0.1:8765"` in `ac_copilot_trainer.lua` and reload the CSP app. On connect the sidecar logs `protocol=1`; each client connection logs the same. Use `--no-reply` for log-only mode (no `coaching_response` frames). **Message examples (v1):** Lua → Python after a lap: `{"protocol":1,"event":"lap_complete","lap":3,"lapTimeMs":95000,"coachingHints":["…"]}`. Python → Lua (default dev reply): `{"protocol":1,"event":"coaching_response","lap":3,"hints":[{"kind":"general","text":"Sidecar v1: ack lap 3"}]}`. Malformed JSON receives `{"protocol":1,"event":"analysis_error","message":"invalid json"}`. Full field list: `docs/10_Development/12_WS_Sidecar_Protocol.md`.
