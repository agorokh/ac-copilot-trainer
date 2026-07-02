# Session Review Reports

Issue #404 adds a saved post-session review surface over the immutable lap
archive corpus. The artifact is derived and regenerable: source laps stay under
`journal/laps/lap_*.json`, while review products are written under
`journal/reports/`.

Generate the latest session report:

```bash
python -m tools.session_review --lap-dir journal/laps
```

The command writes three derived files under `journal/reports/`:

- `session_<session>_<car>_<track>.md` - driver-readable Markdown.
- `session_<session>_<car>_<track>.json` - machine-readable report with
  `spoken_summary`, `screen_summary`, ranked corner problems, next-session prep
  items, history/trend rows, and downsampled comparison traces.
- `session_<session>_<car>_<track>.html` - self-contained local report for
  browsing session history, lap-time trends, corner-speed trends, and lap A/B
  telemetry traces without SQL or a running server.

Review a specific session:

```bash
python -m tools.session_review --lap-dir journal/laps --session <session_uuid>
```

Choose the comparison reference source:

```bash
python -m tools.session_review --lap-dir journal/laps --reference-source tt
python -m tools.session_review --lap-dir journal/laps --reference-source none
python -m tools.session_review --lap-dir journal/laps --reference-path journal/laps/lap_reference.json
```

Reference sources are `auto`, `your-best`, `pro`, `tt`, `generated`,
`imported`, or `none`. `auto` picks the fastest valid same-car/track/layout
lap in the corpus. Specific sources filter to that reference kind; `none`
keeps trend/history output but disables reference comparison. `--reference-path`
pins one same-car/track/layout `lap_*.json` archive when the operator wants an
exact library entry instead of the fastest candidate.

The report compares the selected session against the fastest known valid lap for
the same car/track/layout in the supplied corpus. If the selected session owns
the fastest lap, the compare picker falls back to the next fastest same-combo
lap. It never mutates `journal/laps/lap_*.json`; reports are derived products
and may be regenerated.

Use JSON output when a launcher or rig surface needs the paths:

```bash
python -m tools.session_review --lap-dir journal/laps --json
```

Runtime integration:

- When the Lua trainer reaches the main menu after a driven session, it drains
  pending lap archive jobs, then sends `session.review.generate` to the loopback
  sidecar with the current lap archive directory and session UUID.
- The loopback request may include `reference_source` and `reference_file`
  (`reference_file` is a basename under the same `journal/laps` directory) to
  select an exact reference-library entry for the generated report.
- The sidecar writes the same Markdown, JSON, and HTML reports to the sibling
  `journal/reports/` directory, publishes a `session.review` state snapshot for
  screens, and emits a `coaching.cue` with the `spoken_summary` for the voice
  client.
- Generation is loopback-only. External screens subscribe to the derived
  `session.review` / `coaching.cue` topics; they do not request report writes
  directly.
- Loopback acks include full local `markdown_path`, `json_path`, and
  `html_path` values. External `session.review` and `coaching.cue` broadcasts
  expose only `markdown_file`, `json_file`, and `html_file` basenames.
