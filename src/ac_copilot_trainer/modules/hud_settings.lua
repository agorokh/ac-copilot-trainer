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

---@param mode "strictTrue"|"notFalse"
--- `strictTrue`: matches `if not config.k` / `if config.k then` (only explicit `true` is on).
--- `notFalse`: matches `config.k ~= false` (nil/missing counts as on).
local function checkbox(config, key, label, mode)
  mode = mode or "strictTrue"
  local cur = (mode == "notFalse") and (config[key] ~= false) or (config[key] == true)
  if type(ui.checkbox) ~= "function" then
    ui.text(string.format("%s: %s", label, cur and "on" or "off"))
    return
  end
  pcall(function()
    -- CSP ui.checkbox(label, currentValue) returns true when CLICKED (changed),
    -- not the new value. Flip cur on click.
    if ui.checkbox(label, cur) then
      config[key] = not cur
    end
  end)
end

local function textWrappedMaybe(s)
  if type(s) ~= "string" or s == "" then
    return
  end
  if type(ui.textWrapped) == "function" then
    ui.textWrapped(s)
  else
    ui.text(s)
  end
end

local function drawStats(st)
  if st.throttleLapHint and st.throttleLapHint ~= "" then
    ui.textColored("Throttle (last lap)", rgbm(0.75, 0.78, 0.85, 1))
    textWrappedMaybe(st.throttleLapHint)
  end
  if st.consistencyHud and st.consistencyHud ~= "" then
    ui.textColored("Consistency", rgbm(0.75, 0.78, 0.85, 1))
    textWrappedMaybe(st.consistencyHud)
  end
  if st.styleHud and st.styleHud ~= "" then
    ui.textColored("Style vs reference", rgbm(0.75, 0.78, 0.85, 1))
    textWrappedMaybe(st.styleHud)
  end
  if st.tireHud and st.tireHud ~= "" then
    ui.textColored("Tires (last lap)", rgbm(0.75, 0.78, 0.85, 1))
    textWrappedMaybe(st.tireHud)
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

  ui.textColored("AC Copilot Trainer — Settings", rgbm(0.55, 0.6, 0.68, 1))
  ui.separator()

  ui.textColored("Display", rgbm(0.78, 0.8, 0.88, 1))
  checkbox(cfg, "hudEnabled", "Show HUD/coaching windows", "strictTrue")
  checkbox(cfg, "racingLineEnabled", "Show racing line (3D)", "notFalse")
  checkbox(cfg, "brakeMarkersEnabled", "Show brake markers (3D)", "notFalse")

  ui.separator()
  ui.textColored("Coaching", rgbm(0.78, 0.8, 0.88, 1))
  if type(ui.slider) == "function" then
    pcall(function()
      local curA = math.max(50, math.min(500, tonumber(cfg.approachMeters) or 200))
      local nvA, chA = ui.slider("Approach distance (m)", curA, 50, 500, "%.0f", true)
      if chA and nvA == nvA then
        if type(vm.setApproachMeters) == "function" then
          vm.setApproachMeters(nvA)
        else
          cfg.approachMeters = nvA
        end
      end
    end)
    pcall(function()
      local curH = math.max(5, math.min(120, tonumber(cfg.coachingHoldSeconds) or 30))
      local nvH, chH = ui.slider("Post-lap coaching hold (s)", curH, 5, 120, "%.0f", true)
      if chH and nvH == nvH then
        cfg.coachingHoldSeconds = nvH
      end
    end)
  else
    local curA = math.max(50, math.min(500, tonumber(cfg.approachMeters) or 200))
    local curH = math.max(5, math.min(120, tonumber(cfg.coachingHoldSeconds) or 30))
    ui.text(string.format("Approach distance (m): %.0f", curA))
    ui.text(string.format("Post-lap coaching hold (s): %.0f", curH))
    ui.textColored("Sliders not available in this CSP build.", rgbm(0.65, 0.65, 0.7, 1))
  end

  local mode = tostring(cfg.racingLineMode or "best")
  local modePreview = (mode == "last" and "Last lap") or (mode == "both" and "Both") or "Best lap"
  if type(ui.combo) == "function" then
    pcall(function()
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
    end)
  else
    ui.text("Racing line source: " .. modePreview)
    ui.textColored("Combo not available — edit racingLineMode in storage if needed.", rgbm(0.65, 0.65, 0.7, 1))
  end

  local style = tostring(cfg.lineStyle or "tilt")
  local stylePreview = (style == "flat" and "Flat") or "Tilt"
  if type(ui.combo) == "function" then
    pcall(function()
      ui.combo("Racing line style###cpt_rlstyle", stylePreview, nil, function()
        if ui.selectable("Flat", style == "flat") then
          cfg.lineStyle = "flat"
        end
        if ui.selectable("Tilt", style == "tilt") then
          cfg.lineStyle = "tilt"
        end
      end)
    end)
  else
    ui.text("Racing line style: " .. stylePreview)
  end

  ui.separator()
  ui.textColored("Focus practice (#44)", rgbm(0.78, 0.8, 0.88, 1))
  local stf = vm.focusPracticeUi
  if stf and type(stf) == "table" then
    local cur = stf.focusPracticeActive == true
    if type(ui.checkbox) == "function" then
      pcall(function()
        -- CSP ui.checkbox returns true on click (changed), not the new value
        if ui.checkbox("Enable focus practice (this session)", cur) then
          stf.focusPracticeActive = not cur
        end
      end)
    else
      ui.text("Enable focus practice (this session): " .. (cur and "on" or "off"))
    end
    textWrappedMaybe(stf.focusPracticeHudSummary)
  end

  ui.separator()
  ui.textColored("AI sidecar", rgbm(0.78, 0.8, 0.88, 1))
  do
    local curUrl = tostring(cfg.wsSidecarUrl or "")
    -- Use the entry script's setter (per-key ac.storage) when provided so
    -- the URL persists across reloads. Falls back to direct cfg mutation
    -- if no setter was supplied (tests / older entry script versions).
    local setUrl = vm.setWsSidecarUrl
    local function applyUrl(newUrl)
      if type(setUrl) == "function" then
        setUrl(newUrl)
      else
        cfg.wsSidecarUrl = newUrl
      end
    end
    -- CSP: ui.inputText may be a cdata callable — use nil-checks, not type() == "function".
    if ui.inputText ~= nil then
      pcall(function()
        local nv, ch = ui.inputText("Sidecar URL###cpt_ws", curUrl, ui.InputTextFlags and ui.InputTextFlags.AutoSelectAll or 0)
        if ch and type(nv) == "string" then
          applyUrl(nv)
        end
      end)
    else
      ui.text("Sidecar URL: " .. (curUrl == "" and "<not set>" or curUrl))
      ui.textColored("inputText not available — set ws://127.0.0.1:8765 in storage.", rgbm(0.65, 0.65, 0.7, 1))
    end
    if ui.button ~= nil then
      pcall(function()
        if ui.button("Set ws://127.0.0.1:8765###cpt_ws_default") then
          applyUrl("ws://127.0.0.1:8765")
        end
      end)
      pcall(function()
        ui.sameLine()
        if ui.button("Clear###cpt_ws_clear") then
          applyUrl("")
        end
      end)
    end
    -- Status hint: shows whether the bridge has a URL configured.
    if curUrl ~= "" then
      ui.textColored("Configured. Bridge will dial on next tick.", rgbm(0.55, 0.85, 0.55, 1))
    else
      ui.textColored("URL empty — bridge is dormant.", rgbm(0.85, 0.65, 0.45, 1))
    end
  end

  ui.separator()
  ui.textColored("Diagnostics", rgbm(0.78, 0.8, 0.88, 1))
  checkbox(cfg, "enableRenderDiagnostics", "Render diagnostics ([DIAG] UI + 3D probes)", "strictTrue")
  checkbox(cfg, "enableDraw3DDiagnostics", "Verbose Draw3D logging (~2s interval)", "strictTrue")

  ui.separator()
  ui.textColored("Telemetry & stats", rgbm(0.78, 0.8, 0.88, 1))
  if vm.stats and type(vm.stats) == "table" then
    drawStats(vm.stats)
  end
end

return M
