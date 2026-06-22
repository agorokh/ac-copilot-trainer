# Lap Archive Export

Issue #115 adds an offline exporter for trainer lap archives. The source files
remain the schema-v1 JSON records written by the CSP app under:

```text
<AC Documents>/Assetto Corsa/cfg/extension/state/lua/ac_copilot_trainer/journal/laps/lap_*.json
```

The exact root comes from CSP `ac.FolderID.ScriptConfig`; the stable suffix is
`ac_copilot_trainer/journal/laps/lap_*.json`.

## Analysis CSV

Run from the repository root:

```bash
python -m tools.lap_archive_export --output exports/laps.csv /path/to/journal/laps
```

Directories are expanded to sorted `lap_*.json` files. Output paths are
relative to the current working directory; absolute paths and `..` escapes are
rejected. Laps with `lap.is_valid=false` are skipped by default; pass
`--include-invalid` when you want to inspect invalidated laps. Analysis CSV
exports stream archive files one at a time and replace the output only after
the export completes.

Stable columns:

```text
source_file, lap_uuid, session_uuid, car_id, track_id, lap_n, lap_ms,
is_valid, sample_index, time_s, elapsed_ms, spline, lap_distance_m,
speed_kmh, brake, throttle, steering, gear,
position_x_m, position_y_m, position_z_m,
wheelAngularSpeed_fl, wheelAngularSpeed_fr, wheelAngularSpeed_rl, wheelAngularSpeed_rr,
wheelSlip_fl, wheelSlip_fr, wheelSlip_rl, wheelSlip_rr,
tyreCoreTemp_fl, tyreCoreTemp_fr, tyreCoreTemp_rl, tyreCoreTemp_rr
```

`brake`, `throttle`, and `steering` preserve the normalized CSP values from the
archive trace. `lap_distance_m` is derived from `spline * track.lengthM` when
track length is present; otherwise it is blank. Missing trace fields export as
blank cells so downstream notebooks can distinguish "missing" from zero.

The **per-wheel channels** (issue #266) carry, per corner FL/FR/RL/RR:
`wheelAngularSpeed_*` (rad/s — the canonical longitudinal signal the analysis
layer derives slip from, to attribute which axle locks / exit wheelspin),
`wheelSlip_*` (AC `ndSlip`, secondary), and `tyreCoreTemp_*` (degC — feeds the
tyre thermal model). Archives written before #266 lack these and export blank.
The trace field set is a hard contract kept byte-identical between
`lap_archive.lua::TRACE_FIELDS` and `reference_lap.py::TRACE_FIELDS`.

### Optional Tier-B per-wheel channels (#266)

When present, the trace may also carry per-wheel channels named
`wheelAngularSpeed_{fl,fr,rl,rr}` (rad/s) and `wheelSlip_{fl,fr,rl,rr}` (AC's
combined Pacejka NDslip). These are **optional** — older laps omit them and the
loader degrades gracefully. The setup-coaching engine
(`tools/ai_sidecar/corner_attribution.py`) uses `wheelAngularSpeed` to compute
true longitudinal slip per wheel, which upgrades brake-lockup and exit-wheelspin
attributions from a *suspicion* to a *confirmed* axle-level verdict (which axle
locks → brake bias; rear wheelspin → traction/TC/diff). Order is `[FL, FR, RL, RR]`.

## MoTeC-Shaped CSV

Run:

```bash
python -m tools.lap_archive_export \
  --format motec-csv \
  --output exports/laps_motec.csv \
  /path/to/journal/laps
```

This writes a MoTeC-style CSV envelope: metadata rows, `Beacon Markers`, a
channel-name row, a units row, and quoted data fields. Supported channels:

```text
Time (s), Ground Speed (km/h), Brake Pos (%), Throttle Pos (%),
Steering (none), Gear (none), Spline (none), Lap Distance (m),
Position X/Y/Z (m), Lap Number (none), Lap Time (s), Valid Lap (none)
```

Compatibility limits:

- The exporter does not write native MoTeC `.ld` files.
- `journal/laps` is an app-wide archive directory. `motec-csv` exports reject
  mixed `session_uuid`, car, track, or track-layout inputs because the output
  header describes one continuous outing. Export broad history with the
  analysis CSV format, or pass a narrowed set of lap files that belong to one
  compatible outing.
- MoTeC header stats are computed with a bounded pre-scan over the selected
  paths, then rows are streamed during the write. Beacon markers are based on
  emitted sample time so marker values stay inside the exported log range;
  the `Lap Time` channel still carries recorded `lap.lap_ms` when it is
  present.
- MoTeC's public support guidance says the CSV format is exacting rather than
  fully documented: every field should remain quoted, and beacon marker values
  are seconds from the start of the log separated by spaces. See MoTeC forum
  notes on [CSV formatting](https://forum.motec.com.au/viewtopic.php?f=26&t=3864)
  and [CSV import licensing / conversion](https://forum.motec.com.au/viewtopic.php?f=26&t=4317).
- i2 Pro CSV conversion/import may require the MoTeC CSV Dataset conversion
  path or a dealer/import license. Treat this output as a deterministic bridge
  file, not a guarantee that every i2 installation will import it without local
  licensing or workspace adjustments.
- `Steering` is the trainer's normalized CSP steer value, not a calibrated
  steering-wheel angle in degrees.
