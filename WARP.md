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

- **Sidecar coaching extra (issue #49):** `pip install -e ".[coaching]"` installs `websockets`, `numpy`, `scikit-learn`, and `shap` for the WebSocket sidecar and future ML-heavy paths. A plain `pip install -e .` or `pip install -e ".[dev]"` still works; ranking code in `tools/ai_sidecar` uses **pure Python** for the default delta-based ranking so tests and minimal installs do not import `sklearn`/`shap` at runtime. Use `shap` / `sklearn` when you add model-based explainers on top of the same feature vectors.
- _If applicable: document HF cache dirs, GPU/MPS usage, air-gapped constraints._

## Troubleshooting

_Add project-specific debugging tips as you learn them._

### AC Copilot Trainer (CSP Lua app)

- **Render API diagnostics:** In `src/ac_copilot_trainer/ac_copilot_trainer.lua`, set `config.enableRenderDiagnostics = true` and reload the app to restore the 60s `render_diag` run (API probe logs, red/green/blue debug shapes, `[DIAG]` UI). Default is `false` so normal driving sessions stay clean (issue #41).
- **Coaching HUD (issue #43):** In the same `config` table, `coachingHoldSeconds` sets how long post-lap hints stay on screen (fade uses the last few seconds of that window). `coachingMaxVisibleHints` is an integer **1–3** limiting how many `buildAfterLap` lines appear in the Coaching window and how the main-window strip counts “+N more” (invalid values are clamped into **1–3**). Reload the CSP app after edits. Telemetry-only mode (`wsSidecarUrl` empty) is unchanged.
- **WebSocket sidecar (issues #45, #49):** Install optional deps `pip install -e ".[coaching]"` (`websockets`, `numpy`, `scikit-learn`, `shap` — see **Local ML** above). Start the server with `python -m tools.ai_sidecar` (default `ws://127.0.0.1:8765`). Set `config.wsSidecarUrl = "ws://127.0.0.1:8765"` in `ac_copilot_trainer.lua` and reload the CSP app. On connect the sidecar logs `protocol=1`; each client connection logs the same. Use `--no-reply` for log-only mode (no `coaching_response` frames; `analysis_error` may still be sent for malformed JSON). **Ranking harness:** `python -m tools.ai_sidecar --compare-laps tests/fixtures/lap_sidecar_last.json tests/fixtures/lap_sidecar_ref.json` prints corner improvement JSON. **Message examples (v1):** Lua → Python after a lap: `{"protocol":1,"event":"lap_complete","lap":3,"lapTimeMs":95000,"coachingHints":["…"]}`. Python → Lua (default dev reply): `{"protocol":1,"event":"coaching_response","lap":3,"hints":[{"kind":"general","text":"Sidecar v1: ack lap 3"}]}`. When `lap_complete` includes optional `telemetry.corners`, responses may also include `improvementRanking` (see protocol doc). Malformed JSON receives `{"protocol":1,"event":"analysis_error","message":"invalid json"}`. Full field list: `docs/10_Development/12_WS_Sidecar_Protocol.md`.
- **Ollama debrief (issue #46):** Opt-in with `AC_COPILOT_OLLAMA_ENABLE=1` in the environment **before** starting `python -m tools.ai_sidecar`. Defaults: **model** `llama3.2`, **host** `http://127.0.0.1:11434`, **temperature** `0.35`, `num_predict` `320` (max new tokens), **`AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC`** `12` s for the post-lap HTTP call (keeps the coaching response inside the CSP hold window; rules fallback if it times out), and **`AC_COPILOT_OLLAMA_TIMEOUT_SEC`** `45` s as the generic upper bound for other tooling — override with `AC_COPILOT_OLLAMA_MODEL`, `AC_COPILOT_OLLAMA_HOST`, etc. (see `.env.example`). Run Ollama locally (`ollama pull llama3.2` or your chosen tag). If Ollama is unreachable, the sidecar still sends a **rules-based** `debrief` string (no crash). The CSP app shows it under **Session debrief (sidecar)** on the main HUD and **SESSION DEBRIEF** in the Coaching window; session journal JSON may include `sidecar_debrief_last` when present. **E2E:** sidecar + Ollama running + `wsSidecarUrl` set → complete a lap → expect ≥1 paragraph in the UI.
- **Focus practice mode (issue #44):** In `ac_copilot_trainer.lua` `config`, set **`focusPracticeCornerLabels`** to a comma list such as **`"T1,T2,T3"`** (labels match `corner_analysis` sector tags `T1`, `T2`, …). Leave it **empty** to auto-target the up-to-**`focusPracticeAutoCount`** worst corners from consistency (needs **≥2 laps** with valid telemetry so `consistencySummary` exists). Toggle **Enable (this session)** in the main HUD; the flag is **session/runtime** only and clears when you **leave the track** (`resetRuntimeAfterLeavingTrack`). **Rolling session reset** clears auto corner data but leaves the checkbox state as implemented today. With focus on, **brake marker walls** for matching corners use a **wider, taller, brighter** shader quad; other markers are **dimmed** when `focusPracticeDimNonFocus` is true and last-lap corner features exist. **Post-lap coaching text** is filtered to lines that mention the focus labels (or a single fallback line). **Racing line** emphasis is unchanged in this slice (markers + HUD + hints only).
