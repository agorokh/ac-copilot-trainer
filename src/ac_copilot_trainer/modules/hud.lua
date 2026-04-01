-- Dear ImGui HUD: tiered layout (glance / context / collapsible detail) — issue #33.

local M = {}

--- UTF-8 FULL BLOCK (U+2588) for delta bar segments.
local BLK = string.char(226, 150, 136)

---@class HudViewModel
---@field recording boolean
---@field speed number
---@field brake number
---@field lapCount integer
---@field bestLapMs number|nil
---@field lastLapMs number|nil
---@field brakeBest integer
---@field brakeLast integer
---@field brakeSession integer
---@field telemetrySamples integer|nil
---@field deltaSmoothedSec number|nil
---@field sectorMessage string|nil
---@field approachLines string[]|nil
---@field postLapLines string[]|nil
---@field coastWarn boolean|nil
---@field throttleLapHint string|nil
---@field consistencyHud string|nil
---@field styleHud string|nil
---@field tireHud string|nil
---@field tireLockupFlash boolean|nil
---@field setupChangeMsg string|nil
---@field autoSetupLine string|nil
---@field refAiDistanceM number|nil
---@field segmentCount integer|nil
---@field coachingLines string[]|nil

local function formatLapMs(ms)
  if not ms or ms <= 0 then
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

--- Throttle / consistency / tires / buffer / brake counts (tier 3).
local function drawTelemetryDetail(vm)
  if vm.throttleLapHint and vm.throttleLapHint ~= "" then
    ui.textColored(rgbm(0.75, 0.78, 0.85, 1), "Throttle (last lap)")
    ui.textWrapped(vm.throttleLapHint)
  end
  if vm.consistencyHud and vm.consistencyHud ~= "" then
    ui.textColored(rgbm(0.75, 0.78, 0.85, 1), "Consistency")
    ui.textWrapped(vm.consistencyHud)
  end
  if vm.styleHud and vm.styleHud ~= "" then
    ui.textColored(rgbm(0.75, 0.78, 0.85, 1), "Style vs reference")
    ui.textWrapped(vm.styleHud)
  end
  if vm.tireHud and vm.tireHud ~= "" then
    ui.textColored(rgbm(0.75, 0.78, 0.85, 1), "Tires (last lap)")
    ui.textWrapped(vm.tireHud)
  end
  if vm.refAiDistanceM ~= nil and vm.refAiDistanceM == vm.refAiDistanceM then
    ui.text(string.format("AI line lateral (XZ): ~%.1f m", vm.refAiDistanceM))
  end
  if vm.segmentCount ~= nil and vm.segmentCount > 0 then
    ui.text(string.format("Track segments: %d", vm.segmentCount))
  end
  if vm.telemetrySamples ~= nil then
    ui.text(string.format("Telemetry buffer: %d samples", vm.telemetrySamples))
  end
  ui.text(string.format(
    "Brake points — best: %d  last lap: %d  session: %d",
    vm.brakeBest or 0,
    vm.brakeLast or 0,
    vm.brakeSession or 0
  ))
end

function M.draw(vm)
  -- Tier 1 — always visible, top
  ui.textColored(rgbm(0.5, 0.55, 0.62, 1), "AC Copilot Trainer v0.4.0")
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
  if vm.deltaSmoothedSec == nil then
    ui.textColored(rgbm(0.55, 0.55, 0.58, 1), "No reference")
  else
    local d = vm.deltaSmoothedSec
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

  if vm.approachLines and #vm.approachLines > 0 then
    ui.separator()
    ui.textColored(rgbm(0.85, 0.88, 0.95, 1), "Approach (brake)")
    for i = 1, #vm.approachLines do
      ui.text(vm.approachLines[i])
    end
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

  if vm.coachingLines and #vm.coachingLines > 0 then
    ui.separator()
    ui.textColored(rgbm(0.35, 0.82, 0.95, 1), "Coaching")
    for i = 1, #vm.coachingLines do
      ui.textWrapped(vm.coachingLines[i])
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

  -- Tier 3 — detail (tree when supported; same fields flat on older CSP)
  local flags = ui.TreeNodeFlags
  local framed = flags and flags.Framed or nil
  ui.separator()
  if framed ~= nil then
    ui.treeNode("Telemetry & stats", framed, function()
      drawTelemetryDetail(vm)
    end)
  else
    ui.textColored(rgbm(0.55, 0.55, 0.58, 1), "Telemetry & stats (no collapsible UI — showing flat)")
    drawTelemetryDetail(vm)
  end
end

return M
