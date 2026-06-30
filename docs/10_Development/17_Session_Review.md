# Session Review Reports

Issue #404 Part A adds a saved post-session debrief artifact over the immutable
lap archive corpus.

Generate the latest session report:

```bash
python -m tools.session_review --lap-dir journal/laps
```

The command writes two derived files under `journal/reports/`:

- `session_<session>_<car>_<track>.md` - driver-readable Markdown.
- `session_<session>_<car>_<track>.json` - machine-readable report with
  `spoken_summary`, `screen_summary`, ranked corner problems, and next-session
  prep items.

Review a specific session:

```bash
python -m tools.session_review --lap-dir journal/laps --session <session_uuid>
```

The report compares the selected session against the fastest known valid lap for
the same car/track/layout in the supplied corpus. It never mutates
`journal/laps/lap_*.json`; reports are derived products and may be regenerated.

Use JSON output when a launcher or rig surface needs the paths:

```bash
python -m tools.session_review --lap-dir journal/laps --json
```

Runtime integration:

- When the Lua trainer reaches the main menu after a driven session, it drains
  pending lap archive jobs, then sends `session.review.generate` to the loopback
  sidecar with the current lap archive directory and session UUID.
- The sidecar writes the same Markdown and JSON reports to the sibling
  `journal/reports/` directory, publishes a `session.review` state snapshot for
  screens, and emits a `coaching.cue` with the `spoken_summary` for the voice
  client.
- Generation is loopback-only. External screens subscribe to the derived
  `session.review` / `coaching.cue` topics; they do not request report writes
  directly.
