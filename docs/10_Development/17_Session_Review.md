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
