---
type: handoff
status: active
memory_tier: canonical
last_updated: 2026-04-21
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/Project State.md
  - AcCopilotTrainer/00_System/invariants/_index.md
  - AcCopilotTrainer/00_System/glossary/_index.md
  - AcCopilotTrainer/10_Rig/esp32-jc3248w535-screen-v1.md
  - AcCopilotTrainer/01_Decisions/external-ws-client-protocol-extension.md
  - AcCopilotTrainer/01_Decisions/screen-ui-stack-lvgl-touch.md
  - AcCopilotTrainer/03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md
  - AcCopilotTrainer/03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md
  - 00_Graph_Schema.md
---

# Next session handoff

## Resume here (2026-04-21, end of day)

**End-to-end rig screen ↔ sidecar is working.** PR [#83](https://github.com/agorokh/ac-copilot-trainer/pull/83)
landed the sidecar `--external-bind`/`--token`, protocol v1 `{v,type}`
extension, Lua `ws_bridge` action+config bridge, and the JC3248W535
display fix. Sidecar logs the device join with token; firmware emits
`{v:1,type:"action",name:"toggleFocusPractice"}` every 10 s.

User is doing a code review on PR #83 + designing visuals for the
real touchscreen UI. Next agent picks up at the **Phase-2 LVGL bring-up**
and the **Pocket Technician / Setup Exchange integration research**
(both are the user's stated next priorities — he wants to bridge the
rig touchscreen to those CSP apps too).

## Concrete next moves

1. **Start the sidecar with the hotspot config** before any device test:
   ```bash
   py -m tools.ai_sidecar --external-bind 0.0.0.0 \
                          --token replace-me-when-sidecar-auth-ships
   ```
   PC must have **Windows Mobile Hotspot `AG_PC 7933`** running so the
   device can reach `192.168.137.1`. See
   [`03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md`](../03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md).

2. **Phase-2 firmware: bring up LVGL 8.3 + touch.**
   - Add `lib_deps += lvgl/lvgl @ ~8.3.11` to `firmware/screen/platformio.ini`.
   - Add `firmware/screen/include/board/JC3248W535_Touch.h` with the 40-line
     I²C reader (full snippet in
     [`01_Decisions/screen-ui-stack-lvgl-touch.md`](../01_Decisions/screen-ui-stack-lvgl-touch.md)).
   - Wire `lv_disp_drv_t.flush_cb` to call `gfx->draw16bitBeRGBBitmap()`,
     then `((Arduino_Canvas*)gfx)->flush()` once per ~16 ms in `loop()`.
   - Drop a one-screen "tap → toggle focusPractice" button so we can see
     the round-trip on-panel.

3. **Pocket Technician + Setup Exchange research is in flight.** Look in
   `03_Investigations/` for the freshly-written node before re-doing the
   discovery — it should land alongside this handoff. The integration
   ADR (`01_Decisions/screen-and-csp-apps-integration.md`) will codify
   the strategy (read-only state scrape vs. cooperative same-VM call).

4. **Once PR #83 merges:** the orchestrator should run post-merge steward
   propagation against `main`; vault changes from this session are
   already on the feat branch.

## What was delivered today (2026-04-21)

- **PR #83** (`feat/issue-81-external-ws-client`): sidecar bind+token+401,
  `{v,type}` protocol extension, Lua action/config bridge, 9 new + 37
  regression tests passing.
- **JC3248W535 display fix** (commit d8d3d2e): `Arduino_AXS15231B` +
  `Arduino_Canvas` + `ips=false` + explicit `flush()`. Replaced the
  moononournation init table that was tuned for the 1.91" AMOLED variant.
- **Network workaround**: Windows Mobile Hotspot bypasses the AHOME5G
  mesh's per-AP subnet split.
- **Two new investigation nodes**:
  [`jc3248w535-display-canvas-flush-2026-04-21`](../03_Investigations/jc3248w535-display-canvas-flush-2026-04-21.md)
  and
  [`router-mesh-cross-ap-tcp-block-2026-04-21`](../03_Investigations/router-mesh-cross-ap-tcp-block-2026-04-21.md).
- **One new decision**: [`screen-ui-stack-lvgl-touch`](../01_Decisions/screen-ui-stack-lvgl-touch.md)
  — LVGL 8.3 + AXS15231B touch + SquareLine for Phase-2.

## What remains

**Phase-2 firmware (rig screen UI):**

- Touch bring-up + LVGL 8.3 + canvas-flush bridge.
- SquareLine project in `firmware/screen/squareline/` exporting to
  `firmware/screen/src/ui/`.
- Replace the 10-second auto-ping with a real tile.

**Trainer integration:**

- In-game smoke test of the full round-trip (AC running + Copilot Trainer
  loaded + screen tap toggling `focusPractice` live).

**CSP apps bridge (new epic):**

- Decide read-only-scrape vs cooperative-same-VM approach for Pocket
  Technician and Setup Exchange.
- Draft `01_Decisions/screen-and-csp-apps-integration.md`.

**PR #75 stream (still open from prior sessions):**

- Merge `origin/main` into PR #75, resolve conflicts, push, in-game
  smoke test on Vallelunga + Porsche 911 GT3 R.

## Blockers / dependencies

- **Hotspot must be on** for any live device test. If the PC reboots,
  re-enable via Settings → Network → Mobile hotspot, or the WinRT
  PowerShell snippet in the router-mesh investigation node.
- No router admin access to remove the cross-AP block, so the hotspot
  is the long-term dev path (acceptable, only impacts dev workstation).

## Key learnings (linked to investigation nodes)

1. AXS15231B QSPI panels need `Arduino_Canvas` + `flush()` — per-pixel
   writes garble the controller.
2. moononournation's `Arduino_AXS15231B` init table targets the 1.91"
   AMOLED, NOT the 320×480 LCD. Use `ips=false`.
3. JC3248W535 touch IS the AXS15231B at I²C 0x3B; no separate touch IC.
4. Mesh Wi-Fi networks may segregate per-AP subnets; ICMP routes but TCP
   may not. Mobile hotspot sidesteps it.
5. Existing CSP/ws_bridge insights from PR #75 still apply (web.socket
   callbacks, per-key ac.storage, sim-time staleness).
