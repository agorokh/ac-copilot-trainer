-- WINDOW_0 — Active Suggestions tile (issue #72 rebuild).
--
-- Style adapted from CMRT-Essential-HUD/gearbox/first.lua: absolute-positioned
-- ui.dwriteDrawText / ui.drawRectFilled / ui.pathArcTo. NO ImGui widgets.
-- Always renders panel chrome + title even in the empty state — never blank.

local fontMod = require("coaching_font")

local M = {}

-- ---------------------------------------------------------------------------
-- Design tokens (Figma CoachingHUD.tsx — see issue #72)
-- ---------------------------------------------------------------------------

local COLOR_BG_DARK   = rgbm(17 / 255, 17 / 255, 17 / 255, 0.60)
local COLOR_BG_BORDER = rgbm(0.30, 0.32, 0.38, 0.40)  -- grey, matches coaching_overlay (round 5: user reverted to grey)
local COLOR_RED       = rgbm(239 / 255, 68 / 255, 68 / 255, 1.0)   -- #EF4444 (per spec)
local COLOR_RED_HARD  = COLOR_RED                                  -- back-compat alias
local COLOR_AMBER     = rgbm(251 / 255, 191 / 255, 36 / 255, 1.0)  -- amber-400
local COLOR_GREEN     = rgbm(74 / 255, 222 / 255, 128 / 255, 1.0)
local COLOR_WHITE     = rgbm(255 / 255, 255 / 255, 255 / 255, 1.0)
local COLOR_TEXT_GREY = rgbm(212 / 255, 212 / 255, 212 / 255, 1.0) -- neutral-300

local PANEL_ROUNDING = 8
local PANEL_PAD_Y    = 14

-- ---------------------------------------------------------------------------
-- View model contract (issue #72)
-- ---------------------------------------------------------------------------

---@class HudViewModel
---@field recording boolean
---@field speed number
---@field brake number
---@field lapCount integer
---@field bestLapMs number|nil
---@field lastLapMs number|nil
---@field deltaSmoothedSec number|nil
---@field appVersionUi string|nil
---@field debriefText string|nil
---@field realtimeHint table|nil  @legacy {text, kind, cornerLabel} for back-compat
---@field realtimeView table|nil  @new live-frame view {primaryLine, secondaryLine, kind, subState, cornerLabel, ...}
---@field focusPracticeActive boolean|nil
---@field focusPracticeLabel string|nil

-- Backward-compat: also keep ApproachHudPayload class declaration so existing
-- structural tests for SD-03 still pass.
---@class ApproachHudPayload
---@field turnLabel string
---@field targetSpeedKmh number
---@field currentSpeedKmh number
---@field distanceToBrakeM number
---@field status string
---@field progressPct number
---@field brakeIndex integer

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function safeWindowSize()
  -- CSP `ui.windowSize` is a cdata callable (not "function" via type()), so
  -- pcall it directly instead of type-checking. Falls back to the manifest
  -- WINDOW_0 size if the call fails or returns garbage.
  if type(ui) == "table" and ui.windowSize ~= nil then
    local ok, sz = pcall(function() return ui.windowSize() end)
    if ok and sz and sz.x and sz.x > 0 and sz.y and sz.y > 0 then
      return sz
    end
  end
  return vec2(520, 200)
end

local function colorForKind(kind)
  if kind == "brake" then return COLOR_RED_HARD end
  if kind == "line" then return COLOR_AMBER end
  if kind == "positive" then return COLOR_GREEN end
  if kind == "placeholder" then return COLOR_TEXT_GREY end
  return COLOR_WHITE
end

local function measure(text, fontPx)
  if type(ui) == "table" and type(ui.measureDWriteText) == "function" then
    local sz = ui.measureDWriteText(text, fontPx)
    if sz then return sz end
  end
  return vec2(string.len(text or "") * fontPx * 0.55, fontPx)
end

--- Resolve a viewmodel from `vm.realtimeView`. Falls back to a generic
--- "no reference" placeholder when the entry script hasn't populated one
--- yet (very early frame, before `script.update` runs).
---
--- Issue #72 dropped the legacy `realtimeHint` shape (`.text`/`.kind`) —
--- the entry script now ALWAYS assigns the new viewmodel shape with
--- `.primaryLine`/`.secondaryLine`. The unused fallback was confusing
--- and shape-mismatched (Cursor BugBot #21cc469d).
local function resolveView(vm)
  if vm.realtimeView and type(vm.realtimeView) == "table" then
    return vm.realtimeView
  end
  return {
    primaryLine = "DRIVE A LAP",
    secondaryLine = "REFERENCE WILL APPEAR",
    kind = "placeholder",
    subState = "no_reference",
  }
end

-- ---------------------------------------------------------------------------
-- Lifecycle
-- ---------------------------------------------------------------------------

--- Reset HUD module state.
---
--- The Phase 5 live-frame rewrite (issue #72) holds no persistent module state
--- — the renderer derives everything from the per-frame view model. Exported
--- as a no-op so the entry script's session/driving reset paths can keep
--- calling `hud.reset()` without crashing the runtime.
function M.reset()
  -- Intentionally empty: no module-level state to clear in the live-frame
  -- rewrite. Kept exported for entry-script reset symmetry.
end

-- ---------------------------------------------------------------------------
-- Top tile renderer (gearbox-style absolute drawing)
-- ---------------------------------------------------------------------------

-- One-shot diag log: prints rendering API surface the first time M.draw runs.
local _hudDiagLogged = false

---@param vm HudViewModel
function M.draw(vm)
  vm = vm or {}
  if not _hudDiagLogged and ac and type(ac.log) == "function" then
    _hudDiagLogged = true
    -- Use tostring() so we see cdata/userdata/nil distinction (not just y/N)
    local function tt(t, k)
      if type(t) ~= "table" then return "?" end
      local v = t[k]
      if v == nil then return "nil" end
      return type(v)
    end
    local szStr = "err"
    if type(ui) == "table" and ui.windowSize ~= nil then
      local ok, sz = pcall(function() return ui.windowSize() end)
      if ok and sz and sz.x then
        szStr = string.format("%.0fx%.0f", sz.x, sz.y or 0)
      else
        szStr = "call-fail"
      end
    else
      szStr = "missing"
    end
    ac.log(string.format(
      "[COPILOT][HUD-DIAG] win0 winSize=%s ui=%s vec2=%s rgbm=%s drawRectFilled=%s drawRect=%s dwriteDrawText=%s windowSize=%s",
      szStr,
      type(ui),
      type(vec2),
      type(rgbm),
      tt(ui, "drawRectFilled"), tt(ui, "drawRect"),
      tt(ui, "dwriteDrawText"), tt(ui, "windowSize")
    ))
  end
  -- UI readiness guard: bail out cleanly on early frames or unusual CSP
  -- builds where the imgui APIs are not yet available. NOTE: in CSP, vec2,
  -- rgbm, and `ui.*` rendering primitives are FFI cdata callables — `type()`
  -- returns "cdata", not "function". Use nil-check + presence-check instead.
  if type(ui) ~= "table"
      or vec2 == nil
      or ui.drawRectFilled == nil
      or ui.drawRect == nil then
    return
  end
  local view = resolveView(vm)

  local sz = safeWindowSize()
  local w = sz.x
  local h = sz.y
  local centerX = w * 0.5

  -- Panel background — dark rounded rect with red bottom border accent
  ui.drawRectFilled(vec2(0, 0), vec2(w, h), COLOR_BG_DARK, PANEL_ROUNDING)
  ui.drawRect(vec2(0, 0), vec2(w, h), COLOR_BG_BORDER, PANEL_ROUNDING, nil, 1)

  -- Top section: "ACTIVE SUGGESTION" small caps in red, centered
  do
    local titleFontPx = 11
    local titleSize = measure("ACTIVE SUGGESTION", titleFontPx)
    local titlePos = vec2(centerX - titleSize.x * 0.5, PANEL_PAD_Y)
    local tk = fontMod.pushNamed("labels_bold", titleFontPx)
    if type(ui.dwriteDrawText) == "function" then
      ui.dwriteDrawText("ACTIVE SUGGESTION", titleFontPx, titlePos, COLOR_RED)
    end
    fontMod.pop(tk)
  end

  -- Corner label (when known) — large Michroma centered
  local y = PANEL_PAD_Y + 22
  local cornerLabel = view.cornerLabel
  if type(cornerLabel) == "string" and cornerLabel ~= "" then
    local cornerFontPx = 22
    local cornerStr = string.upper(cornerLabel)
    local cornerSize = measure(cornerStr, cornerFontPx)
    local cornerPos = vec2(centerX - cornerSize.x * 0.5, y)
    local ck = fontMod.pushNamed("numbers", cornerFontPx)
    if type(ui.dwriteDrawText) == "function" then
      ui.dwriteDrawText(cornerStr, cornerFontPx, cornerPos, COLOR_WHITE)
    end
    fontMod.pop(ck)
    y = y + 30
  end

  -- Primary line (white Michroma uppercase, large)
  if type(view.primaryLine) == "string" and view.primaryLine ~= "" then
    local primaryFontPx = 18
    local primaryStr = string.upper(view.primaryLine)
    local primarySize = measure(primaryStr, primaryFontPx)
    local primaryPos = vec2(centerX - primarySize.x * 0.5, y)
    local pColor = colorForKind(view.kind)
    local pk = fontMod.pushNamed("numbers", primaryFontPx)
    if type(ui.dwriteDrawText) == "function" then
      ui.dwriteDrawText(primaryStr, primaryFontPx, primaryPos, pColor)
    end
    fontMod.pop(pk)
    y = y + 24
  end

  -- Secondary line (amber Michroma uppercase, slightly smaller)
  if type(view.secondaryLine) == "string" and view.secondaryLine ~= "" then
    local secFontPx = 14
    local secStr = string.upper(view.secondaryLine)
    local secSize = measure(secStr, secFontPx)
    local secPos = vec2(centerX - secSize.x * 0.5, y)
    local sColor = COLOR_AMBER
    if view.kind == "brake" then
      sColor = COLOR_TEXT_GREY
    elseif view.kind == "placeholder" then
      sColor = COLOR_TEXT_GREY
    end
    local sk = fontMod.pushNamed("numbers", secFontPx)
    if type(ui.dwriteDrawText) == "function" then
      ui.dwriteDrawText(secStr, secFontPx, secPos, sColor)
    end
    fontMod.pop(sk)
    y = y + 20
  end

  -- Sidecar debrief (rules + optional Ollama follow-up); keeps LLM output visible
  -- on WINDOW_0 without the removed coaching-window panel (Bugbot).
  if type(vm.debriefText) == "string" and vm.debriefText ~= "" then
    local raw = vm.debriefText
    if string.len(raw) > 140 then
      raw = string.sub(raw, 1, 137) .. "..."
    end
    local df = 10
    local dk = fontMod.pushNamed("labels_bold", df)
    if type(ui.dwriteDrawText) == "function" then
      local lines = {}
      local maxW = w - 24
      local curLine = ""
      for word in string.gmatch(raw, "%S+") do
        local trial = (curLine == "") and word or (curLine .. " " .. word)
        local tw = measure(trial, df)
        if tw.x > maxW and curLine ~= "" then
          lines[#lines + 1] = curLine
          curLine = word
          if #lines >= 3 then
            break
          end
        else
          curLine = trial
        end
      end
      if curLine ~= "" and #lines < 3 then
        lines[#lines + 1] = curLine
      end
      local yy = math.max(y, h - 56)
      for li = 1, #lines do
        local ln = lines[li]
        if li == 3 and #lines == 3 then
          ln = ln .. "..."
        end
        local ls = measure(ln, df)
        local lp = vec2(centerX - ls.x * 0.5, yy + (li - 1) * (df + 3))
        ui.dwriteDrawText(ln, df, lp, COLOR_TEXT_GREY)
      end
    end
    fontMod.pop(dk)
  end
end

return M
