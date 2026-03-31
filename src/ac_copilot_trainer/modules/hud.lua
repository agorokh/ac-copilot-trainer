-- Dear ImGui HUD: delta bar, sectors, throttle/coast, approach, post-lap summary.

local M = {}

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

function M.draw(vm)
  ui.text("AC Copilot Trainer v0.4.0")
  ui.separator()
  if vm.recording then
    ui.textColored(rgbm(0, 1, 0, 1), "REC")
  else
    ui.textColored(rgbm(0.7, 0.7, 0.7, 1), "PAUSED")
  end
  ui.text(string.format("Speed: %.0f km/h", vm.speed or 0))
  ui.text(string.format("Brake: %.0f%%", (vm.brake or 0) * 100))
  ui.text(string.format("Lap: %d", vm.lapCount or 0))
  if vm.bestLapMs and vm.bestLapMs > 0 then
    ui.text(string.format("Best: %.3f s", vm.bestLapMs / 1000))
  else
    ui.text("Best: —")
  end
  if vm.lastLapMs and vm.lastLapMs > 0 then
    ui.text(string.format("Last: %.3f s", vm.lastLapMs / 1000))
  else
    ui.text("Last: —")
  end

  ui.separator()
  ui.text("Delta vs best (smoothed)")
  if vm.deltaSmoothedSec == nil then
    ui.textColored(rgbm(0.65, 0.65, 0.65, 1), "No reference")
  else
    local d = vm.deltaSmoothedSec
    local col = rgbm(0.3, 0.95, 0.35, 1)
    if d > 0.02 then
      col = rgbm(0.95, 0.25, 0.25, 1)
    elseif d < -0.02 then
      col = rgbm(0.35, 0.55, 0.95, 1)
    end
    ui.textColored(col, string.format("%+.2f s", d))
    local width = 21
    local mid = math.floor(width / 2) + 1
    local ad = math.abs(d or 0)
    local off = math.floor(ad / 0.04 + 0.5) * (d >= 0 and 1 or -1)
    local pos = math.max(1, math.min(width, mid + off))
    local parts = {}
    for i = 1, width do
      parts[i] = i == pos and "|" or "-"
    end
    ui.textColored(col, table.concat(parts))
  end

  if vm.sectorMessage and vm.sectorMessage ~= "" then
    ui.separator()
    ui.text("Sector")
    ui.textWrapped(vm.sectorMessage)
  end

  if vm.approachLines and #vm.approachLines > 0 then
    ui.separator()
    ui.text("Approach (brake)")
    for i = 1, #vm.approachLines do
      ui.text(vm.approachLines[i])
    end
  end

  if vm.coastWarn then
    ui.textColored(rgbm(0.95, 0.75, 0.2, 1), "Coasting — roll to throttle")
  end

  if vm.throttleLapHint and vm.throttleLapHint ~= "" then
    ui.separator()
    ui.text("Throttle (last lap)")
    ui.textWrapped(vm.throttleLapHint)
  end

  if vm.postLapLines and #vm.postLapLines > 0 then
    ui.separator()
    ui.text("Post-lap")
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

  if vm.consistencyHud and vm.consistencyHud ~= "" then
    ui.separator()
    ui.text("Consistency (last laps)")
    ui.textWrapped(vm.consistencyHud)
  end
  if vm.styleHud and vm.styleHud ~= "" then
    if not vm.consistencyHud or vm.consistencyHud == "" then
      ui.separator()
      ui.text("Style vs reference")
    end
    ui.textWrapped(vm.styleHud)
  end

  if vm.tireHud and vm.tireHud ~= "" then
    ui.separator()
    ui.text("Tires (last lap)")
    ui.textWrapped(vm.tireHud)
  end
  if vm.tireLockupFlash then
    ui.textColored(rgbm(0.95, 0.35, 0.2, 1), "Wheel slip spike")
  end

  if vm.setupChangeMsg and vm.setupChangeMsg ~= "" then
    ui.separator()
    ui.textColored(rgbm(0.95, 0.75, 0.35, 1), vm.setupChangeMsg)
  end
  if vm.autoSetupLine and vm.autoSetupLine ~= "" then
    if not vm.setupChangeMsg or vm.setupChangeMsg == "" then
      ui.separator()
      ui.text("Setup")
    end
    ui.textWrapped(vm.autoSetupLine)
  end

  if vm.refAiDistanceM ~= nil and vm.refAiDistanceM == vm.refAiDistanceM then
    ui.separator()
    ui.text(string.format("AI line lateral (XZ, ground): ~%.1f m", vm.refAiDistanceM))
  end
  if vm.segmentCount ~= nil and vm.segmentCount > 0 then
    ui.text(string.format("Track segments: %d", vm.segmentCount))
  end

  ui.separator()
  if vm.telemetrySamples ~= nil then
    ui.text(string.format("Telemetry buffer: %d samples", vm.telemetrySamples))
  end
  ui.text(string.format("Brake points — best: %d  last lap: %d  session: %d", vm.brakeBest or 0, vm.brakeLast or 0, vm.brakeSession or 0))
end

return M
