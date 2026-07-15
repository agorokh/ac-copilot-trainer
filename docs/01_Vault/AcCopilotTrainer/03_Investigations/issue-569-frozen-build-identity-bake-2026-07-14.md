---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-14
updated: 2026-07-14
relates_to:
  - AcCopilotTrainer/03_Investigations/tablet-dash-connection-hardening-2026-07-14.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/invariants/entrypoint.md
---

# #569 — baking build identity into the frozen Game Point EXE (live-proven)

Completes **H1** of [[tablet-dash-connection-hardening-2026-07-14]] ("expose
`build_commit`/`build_time` … so a stale binary is detectable at a glance"). #567/PR #568
shipped the commit field + the served-`endpoints` set; a *packaged* build still reported
`build_commit: "unknown"` because the frozen EXE has no `.git`. PR
[#586](https://github.com/agorokh/ac-copilot-trainer/pull/586) bakes both identifiers at
package time.

## Decision — generated PyInstaller runtime hook (not a bundled `_build_info`)

#569 floated two options; the runtime hook won on two grounds, one of them web-grounded
against the [PyInstaller docs](https://pyinstaller.org/en/stable/hooks.html) and confirmed
live:

- **Hooks run before the entry script**, so the baked values are in `os.environ` before any
  sidecar code reads them. The frozen build then resolves identity through the **same
  env-first path** a dev checkout uses — no `sys.frozen` branch, no `_MEIPASS` in the reader.
- **The launcher re-spawns itself** (`sidecar_command` → `[sys.executable, "--sidecar-child"]`),
  so the hook runs in the child too — the bake needs no propagation logic.

The generated hook lands in the already-gitignored `build/`; nothing pollutes the source tree.
Council (architectural seat) independently reached the same call.

## Rig facts (verified, reusable)

- **`--clean` does NOT eat a `--runtime-hook` written into `build/`.** `build_pyinstaller_args`
  passes `--clean` and PyInstaller's default *workpath* is `./build` — the same dir. Probed
  directly with a minimal onefile build: the hook survives and is consumed. Worth knowing
  before anyone "fixes" the hook location.
- **`os.environ.setdefault` is the wrong primitive for this bake.** It will not replace a var
  that is **set but empty**, while `observability.build_commit()` strips and treats empty as
  unset — so `AC_COPILOT_BUILD_COMMIT=` in the launch env silently strands a packaged build
  back on `"unknown"`. The hook emits an explicit guard mirroring the reader's truthiness
  check instead. Found by accident on a real EXE; pinned by
  `test_runtime_hook_bakes_over_a_set_but_empty_env_var`.
- **`-dirty` suffix.** The EXE is packaged from the **working tree**, not from `HEAD`, and
  `--build-exe` is normally run from a dev checkout — so `resolve_build_info` appends `-dirty`
  when `git status --porcelain` is non-empty. A bare hash would claim an identity the bundle
  does not have.
- **PyInstaller 6.21.0 / Python 3.13.12** on this rig; a full Game Point onefile build takes
  **~2.7 min** and yields a **~69 MB** EXE.
- **Port collisions with sibling agent sessions are real.** A verification probe on `:8791`
  was answered by *another concurrent session's* sidecar (commit `50eb378`, issue #570), not
  by the EXE under test — the give-away was a missing `build_time` key. Pick a free port and
  **assert on a value you baked**, never just on "something answered".
- **`taskkill /F /IM AC-Copilot-Game-Point.exe` kills by image name** — it stops every Game
  Point EXE on the rig, not just the one under test. Kill by PID.

## Live evidence (2026-07-14)

Real frozen EXE, built via `python -m tools.rig_launcher.build`, `/health` read off it:

| Case | `build_commit` | `build_time` |
|---|---|---|
| Baked (no env) | `fd86787-dirty` | `2026-07-15T02:15:55Z` |
| Operator override | `operator-override` | `1999-01-01T00:00:00Z` |

Primary #567 stale-signal on the fresh EXE: `GET /tablet/dash` → **200**, `/tablet/voice` →
**200** (the previous Jul-2 `dist/` binary returned **426** — that was #567's root cause).
`make ci-fast` OK at head `b9db454`.

## Rig state left behind

`dist/AC-Copilot-Game-Point.exe` was **replaced** by this fresh build (gitignored; the prior
file was the stale Jul-2 binary #567 diagnosed). No Game Point EXE is running — the
image-name `taskkill` above stopped them. Restart the launcher if needed.

## Adjacent work in flight

PR [#585](https://github.com/agorokh/ac-copilot-trainer/pull/585) (issue #570) refactors
`/health` endpoint advertisement onto a route registry — it touches
`observability.build_health_json` / `SERVED_ENDPOINTS`, the same surface this PR extends with
`build_time`. Whichever merges second rebases; expect a small conflict in the payload builder.
