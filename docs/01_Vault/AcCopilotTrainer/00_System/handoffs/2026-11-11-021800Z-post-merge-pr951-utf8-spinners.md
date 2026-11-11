---
type: handoff
status: active
created: 2026-11-11
updated: 2026-11-11
memory_tier: canonical
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-86-device-capture-2026-10-19.md
  - AcCopilotTrainer/03_Investigations/issue-86-pt-long-names-2026-10-18.md
  - AcCopilotTrainer/00_System/Roadmap.md
---

# Post-merge PR #951 — screen UTF-8 ASCII folding & bounded serial spinner lists (`#86`)

## Delivered (`PR #951` -> `main` `3c746a3`)

- **Firmware & LVGL simulator (`firmware/screen/`):**
  - Added UTF-8 -> printable ASCII display folding (`ascii_fold.h` / `ascii_fold.cpp`) wired across Setup Exchange, Pocket Technician, AC Copilot, and toast labels while keeping wire/filesystem setup identifiers lossless.
  - Added auto-fitting single-line spinner value labels (`set_spinner_value_label` + `g_spinner_value_labels`) in `screen_pocket_technician.cpp`, refreshing immediately on `setup.spinner.set.ack`.
  - Promoted `PT_MAX_SPINNERS = 12` to `screen_pocket_technician.h` and raised `SERIAL_RX_RING_BYTES` / `SERIAL_MAX_LINE_BYTES` to `16384` in `main.cpp` with `serial_rx_overflowing` discard-until-newline recovery and `serial_last_rx_ms` keepalive refresh.
  - Added `assert_no_missing_glyphs` inside simulator `capture()` plus UTF-8 Setup Exchange and Pocket Technician spinner scenarios (`511` assertions passing).
- **Sidecar & Lua (`tools/ai_sidecar/`, `src/ac_copilot_trainer/`):**
  - Bounded screen/serial `setup.spinner.list.result` to `SCREEN_PEER_MAX_SPINNERS = 12` (`<= 2600` B) and `setup.list.result` to `<= 4800` B (preserving active setup) so Pocket Technician's dual-list burst plus a 10 Hz `coaching.snapshot` fits `<= 8192` B on un-reflashed boards and `<= 16384` B on reflashed boards, while keeping full spinner payloads for WebSocket/browser peers.
  - Folded Setup Exchange display strings (`name`, `author`, `created_at`) to printable ASCII in `csp_setup_exchange.py` while keeping `car_id` / `track_id` wire identifiers lossless; disambiguated per-corner CSP spinner labels (`_LF`/`_RF`/`_LR`/`_RR`) in `setup_library.lua`.
- **Post-merge classification (`scripts/post_merge_classify.py --pr 951`):** no migration/env/deps flags.

## Remaining (`#86` — continuing immediately in active `/autonomous-deliver 86` session)

1. Pull `main` (`3c746a3`) on `pc`, flash `jc3248w535_serial` to `COM6`, rebuild packaged `dist\AC-Copilot-Game-Point.exe` (`--build-exe --install-shortcut` + `--self-test`), and verify live `/health` `build_commit`.
2. Execute all 4 legs of live Spa Practice pit verification (`ks_porsche_911_gt3_r_2016` @ `spa`, `StartType="PIT"`) directly on `pc` + physical `COM6` (`screen_capture` + touch actuation), commit the clean PNG receipts + investigation note + `Roadmap.md` update (`Closes #86`, `Refs #401`), and reconcile `#401` and `#86` to `CLOSED`.
