---
type: investigation
status: closed
created: 2026-07-25
updated: 2026-07-25
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/677
pr: https://github.com/agorokh/ac-copilot-trainer/pull/680
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/usb-serial-screen-transport-2026-07-02.md
  - AcCopilotTrainer/03_Investigations/backlog-reconcile-2026-07-24.md
---

# #677 ESP32 polish — NVS, backpressure proof, debug screen

Split from #86 Part F (operator decision 1C). Non-blocking; #86 still gates solely on
on-device smoke vs `esp32_rig.png`.

## Shipped (PR #680 → `e3e427c`)

- **Part A:** NVS `Preferences` namespace `acscreen` — last active screen + SE sort
  (`SORT: DL` / `SORT: NAME`), write-on-change, restore after launcher push.
- **Part B:** CDC drain counters + host probe
  `python -m tools.ai_sidecar.serial_backpressure_probe` (SerialPeer framing, no
  protocol change). Primed baseline → measured waves of 8 with host RX drain during
  waits; gates on `ok`/`drop`/`parse` deltas + peak `last_drain_ms`.
- **Part C:** Hidden debug screen (long-press **AC LAUNCHER**) — link, last-frame age,
  peers, free heap, BP counters.

## Live evidence (COM6 / JC3248W535)

```
PASS drop=0 ok=48 last_drain_ms=20 max_avail=2878 heap=239808
```

(prime 8 + measured 40 after flash of the #677 serial env). Firmware
`python -m platformio run -e jc3248w535_serial` SUCCESS; host unit tests 6 passed;
`make ci-fast` green on the merge SHA.

## Lessons

- A single host `write()` of ~14 KiB overfills the 8 KiB CDC RX ring → silent USB
  frame loss with `drop=0`/`parse=0`. Pace waves and drain device→host during waits
  so firmware `Serial.printf` cannot stall TX.
- All-time counters must not gate a burst: prime a baseline, evaluate deltas, emit
  `last_drain_ms` for the current drain.
