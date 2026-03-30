# AC Copilot Trainer

AI-powered driving trainer for Assetto Corsa — a CSP Lua app that provides real-time coaching through brake point detection, lap comparison, 3D track markers, and driving analysis.

## Features (Planned)

### Phase 1 — Foundation
- 3D brake point markers on track surface (best lap vs last lap)
- Real-time brake zone approach HUD with speed reference
- Per-corner brake point comparison after each lap
- Continuous telemetry recording per corner

### Phase 2 — Analysis
- Automatic corner classification and labeling
- Consistency scoring per corner across laps
- Driving style fingerprint (steering, braking, throttle patterns)

### Phase 3 — Coaching
- Corner-specific coaching prompts based on telemetry analysis
- Focus practice mode (highlight weakest corners)
- Session journal with training log

## Requirements

- Assetto Corsa (Steam)
- Custom Shaders Patch (CSP) v0.2.11+
- Content Manager (recommended)

## Installation

Copy `src/ac_copilot_trainer/` to:
```
{AC Install}/apps/lua/ac_copilot_trainer/
```

Enable in Content Manager → Settings → Apps.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
make ci-fast
```

## Architecture

See [docs/01_Vault/AcCopilotTrainer/00_System/Architecture Invariants.md](docs/01_Vault/AcCopilotTrainer/00_System/Architecture%20Invariants.md)

## License

MIT
