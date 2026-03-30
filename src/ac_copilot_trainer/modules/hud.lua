-- Dear ImGui HUD: recording, speed, brake, lap count, best lap.

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

function M.draw(vm)
  ui.text("AC Copilot Trainer v0.1.0")
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
    local sec = vm.bestLapMs / 1000
    ui.text(string.format("Best: %.3f s", sec))
  else
    ui.text("Best: —")
  end
  if vm.lastLapMs and vm.lastLapMs > 0 then
    ui.text(string.format("Last: %.3f s", vm.lastLapMs / 1000))
  else
    ui.text("Last: —")
  end
  ui.separator()
  ui.text(string.format("Brake points — best: %d  last lap: %d  session: %d", vm.brakeBest or 0, vm.brakeLast or 0, vm.brakeSession or 0))
end

return M
