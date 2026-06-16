# Setup Experiment Tracking

Issue **#114** adds an offline setup-optimization layer on top of the PR #78
lap archive.

## Data Location

The trainer writes lap archives under:

```text
<AC ScriptConfig>/ac_copilot_trainer/journal/laps/lap_*.json
```

The sidecar derives setup experiments from those files and stores compact JSONL
rows under:

```text
<AC ScriptConfig>/ac_copilot_trainer/journal/setup_experiments/experiments.jsonl
```

Each row contains the source lap path, car/track ids, conditions, lap time,
setup hash/path/name, and numeric setup parameters from `setup.snapshot`.

## Live Recording

After a lap archive is written, Lua sends a best-effort v1 sidecar message:

```json
{"v":1,"type":"setup.experiment.record","archive_path":".../journal/laps/lap_...json"}
```

After the v1 sidecar handshake, Lua also registers the canonical store path:

```json
{"v":1,"type":"setup.experiment.store","store_path":".../journal/setup_experiments/experiments.jsonl"}
```

The sidecar reads archived laps and upserts experiment rows. If the sidecar was
disconnected, no lap data is lost; rebuild from `journal/laps`. The store
registration lets WebSocket compare/suggest requests use rebuilt rows
immediately after sidecar restart.

## Rebuild And Reset

Rebuild the experiment store from lap archives:

```bash
python -m tools.ai_sidecar --setup-rebuild-experiments "<...>/journal/laps"
```

Use a custom store path for tests or exports:

```bash
python -m tools.ai_sidecar --setup-rebuild-experiments "<...>/journal/laps" \
  --setup-store /tmp/ac-copilot-experiments.jsonl
```

Manual server launches can seed WebSocket compare/suggest from an existing
store:

```bash
python -m tools.ai_sidecar --setup-store "<...>/experiments.jsonl"
```

Reset experiments by deleting `journal/setup_experiments/experiments.jsonl`, or
rebuild it from the current lap archive directory.

## A/B Comparison

Compare two setup identifiers. The identifier can be a setup hash, setup name,
or setup path:

```bash
python -m tools.ai_sidecar --setup-store "<...>/experiments.jsonl" \
  --setup-compare baseline aggressive
```

The report includes per-setup sample counts, mean/stdev lap time, improvement
in ms and percent, confidence, one-sided p-value, and a significance flag.

## Next Suggestion

Ask for the next candidate:

```bash
python -m tools.ai_sidecar --setup-store "<...>/experiments.jsonl" \
  --setup-suggest --setup-car-id ks_porsche_911_gt3_r_2016 --setup-track-id magione
```

The suggestion uses a deterministic Gaussian-kernel surrogate over observed
numeric setup params and selects the one- or two-parameter move with the highest
expected improvement. It returns the base setup, changed params, predicted lap
time, uncertainty, expected improvement, and rationale.
