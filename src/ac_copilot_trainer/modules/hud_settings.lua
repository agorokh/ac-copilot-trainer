-- Settings / admin window (issue #57 Part B): `ac.storage` controls + telemetry stats moved from main HUD.

local M = {}

---@class HudSettingsStats
---@field telemetrySamples integer|nil
---@field brakeBest integer|nil
---@field brakeLast integer|nil
---@field brakeSession integer|nil
---@field refAiDistanceM number|nil
---@field segmentCount integer|nil
---@field throttleLapHint string|nil
---@field consistencyHud string|nil
---@field styleHud string|nil
---@field tireHud string|nil

---@class HudSettingsViewModel
---@field config table
---@field stats HudSettingsStats
---@field focusPracticeUi table|nil

local function checkbox(config, key, label)
  local cur = config[key] == true
  pcall(function()
    local nv = ui.checkbox(label, cur)
    if type(nv) == "boolean" then
      config[key] = nv
    end
  end)
end

local function drawStats(st)
  if st.throttleLapHint and st.throttleLapHint ~= "" then
    ui.textColored(rgbm(0.75, 0.78, 0.85, 1), "Throttle (last lap)")
    ui.textWrapped(st.throttleLapHint)
  end
  if st.consistencyHud and st.consistencyHud ~= "" then
    ui.textColored(rgbm(0.75, 0.78, 0.85, 1), "Consistency")
    ui.textWrapped(st.consistencyHud)
  end
  if st.styleHud and st.styleHud ~= "" then
    ui.textColored(rgbm(0.75, 0.78, 0.85, 1), "Style vs reference")
    ui.textWrapped(st.styleHud)
  end
  if st.tireHud and st.tireHud ~= "" then
    ui.textColored(rgbm(0.75, 0.78, 0.85, 1), "Tires (last lap)")
    ui.textWrapped(st.tireHud)
  end
  if st.refAiDistanceM ~= nil and st.refAiDistanceM == st.refAiDistanceM then
    ui.text(string.format("AI line lateral (XZ): ~%.1f m", st.refAiDistanceM))
  end
  if st.segmentCount ~= nil and st.segmentCount > 0 then
    ui.text(string.format("Track segments: %d", st.segmentCount))
  end
  if st.telemetrySamples ~= nil then
    ui.text(string.format("Telemetry buffer: %d samples", st.telemetrySamples))
  end
  ui.text(string.format(
    "Brake points — best: %d  last lap: %d  session: %d",
    st.brakeBest or 0,
    st.brakeLast or 0,
    st.brakeSession or 0
  ))
end

---@param vm HudSettingsViewModel
function M.draw(vm)
  local cfg = vm.config
  if type(cfg) ~= "table" then
    return
  end

  ui.textColored(rgbm(0.55, 0.6, 0.68, 1), "AC Copilot Trainer — Settings")
  ui.separator()

  ui.textColored(rgbm(0.78, 0.8, 0.88, 1), "Display")
  checkbox(cfg, "hudEnabled", "Show main HUD window")
  checkbox(cfg, "racingLineEnabled", "Show racing line (3D)")
  checkbox(cfg, "brakeMarkersEnabled", "Show brake markers (3D)")

  ui.separator()
  ui.textColored(rgbm(0.78, 0.8, 0.88, 1), "Coaching")
  if type(ui.slider) == "function" then
    pcall(function()
      local curA = math.max(50, math.min(500, tonumber(cfg.approachMeters) or 200))
      local nvA, chA = ui.slider("Approach distance (m)", curA, 50, 500, "%.0f", true)
      if chA and nvA == nvA then
        cfg.approachMeters = nvA
      end
    end)
    pcall(function()
      local curH = math.max(5, math.min(120, tonumber(cfg.coachingHoldSeconds) or 30))
      local nvH, chH = ui.slider("Post-lap coaching hold (s)", curH, 5, 120, "%.0f", true)
      if chH and nvH == nvH then
        cfg.coachingHoldSeconds = nvH
      end
    end)
  end

  local mode = tostring(cfg.racingLineMode or "best")
  local modePreview = (mode == "last" and "Last lap") or (mode == "both" and "Both") or "Best lap"
  pcall(function()
    if type(ui.combo) == "function" then
      ui.combo("Racing line source###cpt_rlmode", modePreview, nil, function()
        if ui.selectable("Best lap", mode == "best") then
          cfg.racingLineMode = "best"
        end
        if ui.selectable("Last lap", mode == "last") then
          cfg.racingLineMode = "last"
        end
        if ui.selectable("Both", mode == "both") then
          cfg.racingLineMode = "both"
        end
      end)
    end
  end)

  local style = tostring(cfg.lineStyle or "tilt")
  local stylePreview = (style == "flat" and "Flat") or "Tilt"
  pcall(function()
    if type(ui.combo) == "function" then
      ui.combo("Racing line style###cpt_rlstyle", stylePreview, nil, function()
        if ui.selectable("Flat", style == "flat") then
          cfg.lineStyle = "flat"
        end
        if ui.selectable("Tilt", style == "tilt") then
          cfg.lineStyle = "tilt"
        end
      end)
    end
  end)

  ui.separator()
  ui.textColored(rgbm(0.78, 0.8, 0.88, 1), "Focus practice (#44)")
  local stf = vm.focusPracticeUi
  if stf and type(stf) == "table" then
    local cur = stf.focusPracticeActive == true
    pcall(function()
      local nv = ui.checkbox("Enable focus practice (this session)", cur)
      if type(nv) == "boolean" then
        stf.focusPracticeActive = nv
      end
    end)
    if stf.focusPracticeHudSummary and stf.focusPracticeHudSummary ~= "" then
      ui.textWrapped(stf.focusPracticeHudSummary)
    end
  end

  ui.separator()
  ui.textColored(rgbm(0.78, 0.8, 0.88, 1), "Diagnostics")
  checkbox(cfg, "enableRenderDiagnostics", "Render diagnostics ([DIAG] UI + 3D probes)")
  checkbox(cfg, "enableDraw3DDiagnostics", "Verbose Draw3D logging (~2s interval)")

  ui.separator()
  ui.textColored(rgbm(0.78, 0.8, 0.88, 1), "Telemetry & stats")
  if vm.stats and type(vm.stats) == "table" then
    drawStats(vm.stats)
  end
end

return M
