-- Dear ImGui HUD: main driving window (issue #33). Tier-3 stats + focus toggle → Settings window (#57 Part B).

local coachingOverlay = require("coaching_overlay")

local M = {}

---@class ApproachHudPayload
---@field turnLabel string @always set by `approachHudData` (`corner_names.resolveApproachLabel`)
---@field targetSpeedKmh number
---@field currentSpeedKmh number
---@field distanceToBrakeM number
---@field status string
---@field progressPct number
---@field brakeIndex integer

--- UTF-8 FULL BLOCK (U+2588) for delta bar segments.
local BLK = string.char(226, 150, 136)

---@class HudViewModel
---@field recording boolean
---@field speed number
---@field brake number
---@field lapCount integer
---@field bestLapMs number|nil
---@field lastLapMs number|nil
---@field deltaSmoothedSec number|nil
---@field sectorMessage string|nil
---@field approachData ApproachHudPayload|nil @Producer `approachHudData`; fields match `ApproachHudPayload` (incl. brakeIndex).
---@field postLapLines string[]|nil
---@field coastWarn boolean|nil
---@field tireLockupFlash boolean|nil
---@field setupChangeMsg string|nil
---@field autoSetupLine string|nil
---@field coachingLines (string|{ kind: string, text: string })[]|nil
---@field coachingRemaining number|nil
---@field coachingHoldSeconds number|nil
---@field coachingMaxVisibleHints integer|nil
---@field coachingShowPrimer boolean|nil
---@field appVersionUi string|nil @e.g. "v0.4.2" — must match `APP_VERSION_UI` in entry script
---@field debriefText string|nil @sidecar post-lap paragraph when Ollama/rules debrief enabled (issue #46)
---@field realtimeHint table|nil @{text, kind, cornerLabel} from realtime_coaching (issue #57 Part D)

local function formatLapMs(ms)
  if not ms or ms ~= ms or ms <= 0 then
    return "—"
  end
  return string.format("%.3f s", ms / 1000)
end

--- Graphical delta bar: center = neutral, left green = faster, right red = slower.
local function drawDeltaBar(d)
  local n = 28
  local center = (n + 1) / 2
  local mag = math.min(1, math.abs(d) / 0.12)
  local spread = math.floor(mag * (n / 2) + 0.5)
  for i = 1, n do
    if i > 1 then
      ui.sameLine(0, 0)
    end
    local c = rgbm(0.22, 0.22, 0.24, 1)
    if math.abs(i - center) < 0.51 then
      c = rgbm(0.92, 0.92, 0.95, 1)
    elseif d > 0.015 and i > center and i <= center + spread then
      c = rgbm(0.92, 0.22, 0.22, 1)
    elseif d < -0.015 and i < center and i >= center - spread then
      c = rgbm(0.2, 0.78, 0.3, 1)
    end
    ui.textColored(c, BLK)
  end
end

function M.draw(vm)
  -- Tier 1 — always visible, top
  ui.textColored(
    rgbm(0.5, 0.55, 0.62, 1),
    "AC Copilot Trainer " .. (type(vm.appVersionUi) == "string" and vm.appVersionUi ~= "" and vm.appVersionUi or "v?.?.?")
  )
  if vm.recording then
    ui.sameLine(0, 12)
    ui.textColored(rgbm(0, 1, 0, 1), "REC")
  else
    ui.sameLine(0, 12)
    ui.textColored(rgbm(0.65, 0.65, 0.65, 1), "PAUSED")
  end

  ui.separator()
  ui.text(string.format("%.0f km/h", vm.speed or 0))
  if (vm.brake or 0) > 0.05 then
    ui.text(string.format("Brake %.0f%%", (vm.brake or 0) * 100))
  end

  ui.textColored(rgbm(0.7, 0.72, 0.78, 1), "Delta vs best")
  local dSmooth = vm.deltaSmoothedSec
  if dSmooth == nil or dSmooth ~= dSmooth then
    ui.textColored(rgbm(0.55, 0.55, 0.58, 1), "No reference")
  else
    local d = dSmooth
    local col = rgbm(0.25, 0.9, 0.35, 1)
    if d > 0.02 then
      col = rgbm(0.92, 0.28, 0.25, 1)
    elseif d < -0.02 then
      col = rgbm(0.35, 0.6, 0.95, 1)
    end
    ui.textColored(col, string.format("%+.2f s", d))
    drawDeltaBar(d)
  end

  ui.text(string.format(
    "Lap %d   Best %s   Last %s",
    vm.lapCount or 0,
    formatLapMs(vm.bestLapMs),
    formatLapMs(vm.lastLapMs)
  ))

  -- Tier 2 — context-sensitive
  if vm.sectorMessage and vm.sectorMessage ~= "" then
    ui.separator()
    ui.textColored(rgbm(0.85, 0.88, 0.95, 1), "Sector")
    ui.textWrapped(vm.sectorMessage)
  end

  if vm.approachData and type(vm.approachData) == "table" then
    local a = vm.approachData
    ui.separator()
    ui.textColored(rgbm(0.85, 0.88, 0.95, 1), "Approach (brake)")
    ui.text(string.format("%s  ·  %.0f m", tostring(a.turnLabel or "?"), tonumber(a.distanceToBrakeM) or 0))
    ui.text(string.format(
      "Ref speed: %.0f  Current: %.0f (%s)",
      tonumber(a.targetSpeedKmh) or 0,
      tonumber(a.currentSpeedKmh) or 0,
      tostring(a.status or "")
    ))
  end

  if vm.realtimeHint and type(vm.realtimeHint) == "table" and type(vm.realtimeHint.text) == "string" and vm.realtimeHint.text ~= "" then
    ui.separator()
    local hintCol = rgbm(0.35, 0.82, 0.95, 1)
    local k = vm.realtimeHint.kind
    if k == "brake" then hintCol = rgbm(0.95, 0.55, 0.2, 1)
    elseif k == "line" then hintCol = rgbm(0.85, 0.75, 0.3, 1)
    elseif k == "positive" then hintCol = rgbm(0.2, 0.85, 0.35, 1)
    end
    ui.textColored(hintCol, vm.realtimeHint.text)
  end

  if vm.coastWarn then
    ui.separator()
    ui.textColored(rgbm(0.95, 0.75, 0.2, 1), "Coasting — roll to throttle")
  end

  if vm.postLapLines and #vm.postLapLines > 0 then
    ui.separator()
    ui.textColored(rgbm(0.85, 0.88, 0.95, 1), "Post-lap")
    for i = 1, #vm.postLapLines do
      ui.text(vm.postLapLines[i])
    end
  end

  if vm.setupChangeMsg and vm.setupChangeMsg ~= "" then
    ui.separator()
    ui.textColored(rgbm(0.95, 0.75, 0.35, 1), vm.setupChangeMsg)
  end
  if vm.autoSetupLine and vm.autoSetupLine ~= "" then
    if not vm.setupChangeMsg or vm.setupChangeMsg == "" then
      ui.separator()
    end
    ui.textColored(rgbm(0.85, 0.82, 0.7, 1), "Setup")
    ui.textWrapped(vm.autoSetupLine)
  end

  if vm.tireLockupFlash then
    ui.separator()
    ui.textColored(rgbm(0.95, 0.35, 0.2, 1), "Wheel slip spike")
  end

  if vm.debriefText and vm.debriefText ~= "" then
    ui.separator()
    ui.textColored(rgbm(0.55, 0.82, 0.95, 1), "Session debrief (sidecar)")
    if ui.textWrapped then
      ui.textWrapped(vm.debriefText)
    else
      ui.text(vm.debriefText)
    end
  end

  ui.separator()
  ui.textColored(rgbm(0.45, 0.48, 0.52, 1), "Telemetry & stats → Settings window")

  -- Coaching strip (issue #9 UX); separator only when strip draws.
  coachingOverlay.drawMainWindowStrip(vm)
end

return M
