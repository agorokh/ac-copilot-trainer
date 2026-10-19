---
type: investigation
status: active
memory_tier: canonical
created: 2026-10-19
updated: 2026-10-19
issue: https://github.com/agorokh/ac-copilot-trainer/issues/86
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-86-pt-long-names-2026-10-18.md
  - AcCopilotTrainer/03_Investigations/issue-897-setup-list-journal-scan-2026-10-18.md
---

# #86 on-device screen capture and the render comparison (2026-10-19)

The closure gate asks for a photo or capture of the device compared with `esp32_rig.png`. Until
now nothing could read the panel's pixels; the PPM tool only reads the desktop simulator.

## Delivered — PR #904 (`5e88fe9`)

- **Screen:** `screen.capture` copies the LVGL canvas (the pixels flushed to the glass) into PSRAM
  and streams it as base64 `screen.capture.chunk` frames (RGB565 little-endian, 320×480).
- **Sidecar:** routes the request to screen peers only, and the chunks back to the requester
  only. One capture at a time. Expires after 60 s with no chunk, or when the requester disconnects.
- **CLI:** `python -m tools.screen_capture --out x.png` assembles and writes the PNG.
- **Firmware flashed to COM6** with hashes verified; the rig runs the merged code.
- **Packaged Game Point (`16068f3`) has no capture route** until the EXE is rebuilt. Until then,
  run the source sidecar on COM6 instead of Game Point to capture.

## Pitfalls found live

- **HWCDC drops the whole link.** In the ESP32 core's `HWCDC::write`, if the TX ring is full and
  the host does not read for 100 ms, the core marks the CDC disconnected and silently discards all
  later output: no reboot, no heartbeat, the screen just goes dark on the wire. Four 4 KB
  frames per loop through the default 256 B ring triggered it during a live session.
  Rule: never write a big frame unless `availableForWrite()` covers all of it, and use an 8 KB TX
  ring (`Serial.setTxBufferSize` before `begin`).
- **`mbedtls_base64_encode` needs room for a trailing NUL.** Passing `dlen-1` failed every full
  chunk. The diagnostic that only counted offsets looked clean; check the payload too.
- **The memory-gate stamp is shared.** It lives in the primary checkout's `.scratch`, and a
  parallel session overwrites it. Query and write back to back.

## Comparison (Copilot screen captured mid-drive at Spa)

The layout, palette and type match the render. Differences, recorded on #86 for an operator
decision:
1. The header shows the raw state enum instead of SECTOR · LAP.
2. The corner chip shows `T1 T1` (Spa has no corner names), or `T- --` while cruising.
3. The arrow renders as a letter `V`, not ▼.
4. The delta compares against the next corner's reference entry speed, even on a straight; the
   render's scale labels are missing.
5. A `< BACK` footer button instead of tabs.

## Remaining on #86 (needs someone at the rig)

1. Pocket Technician load.
2. Setup Exchange download → install.
3. The installed setup appears in Pocket Technician and loads.

Do these at Spa, in the pits, with captures running. Two remote attempts recorded nothing: no AC
session or tap reached the sidecar.
