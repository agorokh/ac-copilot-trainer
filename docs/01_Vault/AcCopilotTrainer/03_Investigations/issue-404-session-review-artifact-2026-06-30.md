---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-30
updated: 2026-06-30T22:24:25Z
issue: https://github.com/agorokh/ac-copilot-trainer/issues/404
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/coaching-lakehouse-duckdb-2026-06-28.md
  - AcCopilotTrainer/03_Investigations/pr-309-lap-archive-finalization.md
---

# Session review artifact - #404 Part A

## Summary

Branch `feat/issue-404-session-review` adds the first data-product layer on top of the lap archive
and #402 session foundation: a saved post-session debrief artifact that can also feed voice and
launcher surfaces.

The new `tools.session_review` package reads immutable `journal/laps/lap_*.json` files, chooses the
latest session by `exported_at` or a requested `--session`, compares valid laps with the fastest
valid same car/track/layout reference lap in the supplied corpus, and writes derived Markdown + JSON
reports under `journal/reports/`.

PR #423 review hardening connected the artifact to the live session-end path: after Lua drains
pending lap archive jobs, it sends `session.review.generate` to the loopback sidecar. The sidecar
writes the sibling `journal/reports` files, publishes `session.review` for screen clients, and emits
a `coaching.cue` carrying `spoken_summary` for the voice client.

Second review hardening keeps full report paths on the loopback ack only; external broadcasts expose
safe `markdown_file` / `json_file` basenames. Lua also has a one-shot `sessionReviewRequested` guard
so a failed persistence retry cannot regenerate the report or repeat the spoken summary every menu
frame.

## Output contract

- Markdown: driver-readable report with session stats, reference lap, ranked corner problem list,
  and next-session prep.
- JSON: machine-readable report with `problems`, `ranked_fixes`, `next_session_prep`,
  `spoken_summary`, `screen_summary`, selected lap files, skipped-source metadata, and reference
  metadata.
- CLI: `python -m tools.session_review --lap-dir journal/laps [--session <uuid>] [--json]`.
- Safety: report output is constrained to `journal/reports`; source lap archives are never mutated.

## Implementation notes

- Problem ranking reuses `tools.ai_sidecar.coach_report.build_structured_debrief` instead of
  inventing a parallel corner-analysis engine.
- Repeated corner issues are aggregated across valid laps, carrying top causes, symptoms, fixes, and
  up to three lap examples.
- The `spoken_summary` and `screen_summary` fields intentionally keep Part A ready for the existing
  voice / launcher pipeline without adding a new UI surface in this slice.
- Missing `exported_at` no longer breaks latest-session selection; unusable fastest reference laps
  fall back to lap-only analysis; sessions with no usable trace fail closed instead of reporting a
  misleading empty problem list.
- Sidecar generation returns a structured `session.review.result` error for unexpected generator
  exceptions, matching the setup-experiment handler style.
- `Makefile` policy targets now call Python wrappers for tracked-file secret scanning and canonical
  policy-doc existence checks. This preserves the existing checks while making `make ci-fast
  PYTHON=python` work under Windows PowerShell.

## Verification

- Artifact smoke: from a scratch corpus, `python -m tools.session_review --lap-dir journal/laps
  --json` generated both report files through the unmodified CLI path. The JSON output contained
  `screen_summary=["T1: 0.74s - technique"]`; the spoken summary was `Session debrief for
  ks_porsche_911_gt3_r_2016 at magione: best lap 5.079s. Next session, focus T1.` The Markdown named
  session `sess-latest`, best lap `5.079s`, reference `lap_ref.json (4.773s)`, the T1 problem list,
  and next-session prep.
- Focused checks: `python -m ruff format --check ...`, `python -m ruff check ...`, and
  `python -m pytest -q tests/test_session_review.py tests/test_ai_sidecar_external.py
  tests/test_ws_topic_allowlist.py tests/test_lap_archive_source_structure.py
  tests/test_coach_report.py tests/test_coaching_lake.py tests/test_voice_wiring.py` passed
  (`80 passed, 1 skipped`; DuckDB optional skip).
- Full parity: `FLEET_GOVERNANCE_ROOT=C:\Users\arsen\Projects\governance-hub make ci-fast
  PYTHON=python` passed on Windows (`1958 passed, 117 skipped`, coverage 85.40%, `ci-fast: OK`).
  The only warnings were existing root-file allowlist warnings for `.copier-answers.yml` and
  `doppler.yaml`.

## Live-state reconciliation

`gh issue view 404 --json number,title,state,url` on 2026-06-30 returned issue #404 as **OPEN**:
`[EPIC] Session review, trends & data products`.

This branch covers Part A only. The epic still owns Parts B-D unless the operator explicitly
re-scopes them after the PR: history/replay browser, trend dashboards, and shareable session report.

## Memory note

The exact `mcp__agentic-memory__query_knowledge_graph` tool was not exposed in this Codex tool
surface. The repo prefetch fallback was run before implementation and returned no relevant context;
the configured governance hub also lacked `hooks/forward_capture.py`. This node records the vault
SAVE so the next cold session does not have to infer the #404 state from the branch alone.
