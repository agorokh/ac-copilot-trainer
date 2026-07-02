-- WINDOW_0 — COACHING tile (issue #72 rebuild; #432 Part A2 coaching voice).
--
-- Operator direction (#432): this tile is the qualitative COACHING voice —
-- LLM per-corner advisories, post-lap hints, debrief, sector deltas. The
-- command verb, corner id and target numbers live on the main instrument
-- card (WINDOW_1) and are deliberately NOT duplicated here. Racing Atelier
-- chrome (carbon, brass seg-mark header) keeps the two windows one family.
-- Absolute-positioned ui.dwriteDrawText / ui.drawRectFilled; NO ImGui
-- widgets. Always renders chrome + placeholder — never blank.

local fontMod = require("coaching_font")
local T = require("design_tokens")

local M = {}

-- ---------------------------------------------------------------------------
-- Design tokens (Figma CoachingHUD.tsx — see issue #72)
-- ---------------------------------------------------------------------------

-- Racing Atelier palette (epic #432 Part A) — sourced from design_tokens.lua (single source of
-- truth, validated against the design colors.css).
local COLOR_BG_DARK   = T.color("carbon", 0.78)  -- carbon panel ground
local COLOR_BG_BORDER = T.color("edge", 0.60)    -- structural edge
local COLOR_RED       = T.color("brake")         -- #F23B2C danger
local COLOR_RED_HARD  = COLOR_RED                -- back-compat alias
local COLOR_AMBER     = T.color("lift")          -- #F4A52C caution
local COLOR_GREEN     = T.color("clear")         -- #2FBE6E on line / faster
local COLOR_WHITE     = T.color("chalk")         -- #EEF1F3 primary text
local COLOR_TEXT_GREY = T.color("mute")          -- #9BA1A8 labels

local PANEL_ROUNDING = 0  -- Racing Atelier: square corners (--r: 0px)
local PANEL_PAD_Y    = 14

--- CSP: `ui.dwriteDrawText` is often a cdata callable, not `type(...) == "function"`.
local function dwriteSafe(text, px, pos, color)
  if ui == nil or ui.dwriteDrawText == nil then
    return
  end
  pcall(function()
    ui.dwriteDrawText(text, px, pos, color)
  end)
end

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
---@field sectorMessage string|nil
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
---@field gear integer|nil          @header GEAR column (#432 Part A2 card)
---@field trackName string|nil      @header name next to the corner badge
---@field zonePct number|nil        @SegmentBar brake-zone fraction 0..1
---@field approachMeters number|nil @approach window: gates delta signal tones
---@field kind string|nil           @realtime view kind (verb tone)
---@field primaryLine string|nil    @realtime view primary line (CommandVerb word)
---@field rpm number|nil            @vitals: live engine rpm (RPM strip)
---@field rpmLimiter number|nil     @vitals: rev limiter (strip scale + zones)
---@field shiftZonePct number|nil   @shift-zone start as a fraction of limiter
---@field redZonePct number|nil     @redline band start as a fraction of limiter

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

local function colorForSectorMessage(text)
  local s = string.lower(text or "")
  if string.find(s, "faster", 1, true) then return COLOR_GREEN end
  if string.find(s, "slower", 1, true) then return COLOR_RED_HARD end
  return COLOR_TEXT_GREY
end

local function measure(text, fontPx)
  -- CSP cdata-safe: measureDWriteText can be an FFI cdata callable
  -- (type() == "cdata") — presence-check + pcall, never type()=="function".
  if type(ui) == "table" and ui.measureDWriteText ~= nil then
    local ok, sz = pcall(function() return ui.measureDWriteText(text, fontPx) end)
    if ok and sz and sz.x and sz.x > 0 then return sz end
  end
  local _, n = string.gsub(text or "", "[^\128-\191]", "")
  return vec2(n * fontPx * 0.55, fontPx)
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

  -- Card ground — same Racing Atelier chrome family as the main card
  ui.drawRectFilled(vec2(0, 0), vec2(w, h), COLOR_BG_DARK, PANEL_ROUNDING)
  ui.drawRect(vec2(0, 0), vec2(w, h), COLOR_BG_BORDER, PANEL_ROUNDING, nil, 1)

  local padX = 16

  -- Header: brass seg-mark + COACHING wordmark (launcher/rig header idiom).
  -- This tile is the COACHING voice — qualitative advice only. The verb,
  -- corner id and target numbers live on the main card and are deliberately
  -- NOT repeated here (#432 operator direction: no duplication).
  do
    ui.drawRectFilled(vec2(padX, 14), vec2(padX + 6, 30), T.color("brass"), 0)
    local tk = fontMod.pushNamed("label", 12)
    dwriteSafe("COACHING", 12, vec2(padX + 12, 16), COLOR_TEXT_GREY)
    fontMod.pop(tk)
    ui.drawRectFilled(vec2(padX, 42), vec2(w - padX, 43), T.color("chalk", 0.07), 0)
  end

  --- Word-wrap helper: draw `raw` from yTop, capped at maxLines; returns next y.
  local function drawWrapped(raw, px, yTop, color, maxLines, role)
    local lines = {}
    local maxW = w - padX * 2
    local curLine = ""
    local capped = false
    for word in string.gmatch(raw, "%S+") do
      local trial = (curLine == "") and word or (curLine .. " " .. word)
      if measure(trial, px).x > maxW and curLine ~= "" then
        lines[#lines + 1] = curLine
        curLine = word
        if #lines >= maxLines then
          capped = true
          break
        end
      else
        curLine = trial
      end
    end
    if curLine ~= "" and #lines < maxLines then
      lines[#lines + 1] = curLine
    end
    local fk = fontMod.pushNamed(role or "disp", px)
    for li = 1, #lines do
      local ln = lines[li]
      if li == maxLines and capped then
        ln = ln .. "..."
      end
      dwriteSafe(ln, px, vec2(padX, yTop + (li - 1) * (px + 6)), color)
    end
    fontMod.pop(fk)
    return yTop + #lines * (px + 6)
  end

  -- Coaching content ladder (most valuable voice wins; never blank):
  --   1. Live per-corner LLM advisory (the coaching gold) — amber
  --   2. Post-lap coaching hints while their timer runs — kind-toned
  --   3. Post-lap LLM debrief — mute
  --   4. Placeholder guidance for a fresh session
  local contentY = 56
  local advisory = view.advisory
  local hints = vm.coachingLines
  local hintsActive = type(hints) == "table" and #hints > 0
    and tonumber(vm.coachingRemaining or 0) > 0

  if type(advisory) == "string" and advisory ~= "" then
    drawWrapped(string.upper(advisory), 19, contentY, COLOR_AMBER, 3, "disp")
  elseif hintsActive then
    local first = hints[1]
    local text = (type(first) == "table" and first.text) or tostring(first)
    local kind = (type(first) == "table" and first.kind) or "general"
    local tone = colorForKind(kind)
    if tone == COLOR_TEXT_GREY then tone = COLOR_WHITE end
    local yAfter = drawWrapped(string.upper(text or ""), 19, contentY, tone, 3, "disp")
    if #hints > 1 then
      local mk = fontMod.pushNamed("mono", 11)
      dwriteSafe(string.format("+%d more this lap", #hints - 1), 11,
        vec2(padX, yAfter + 6), COLOR_TEXT_GREY)
      fontMod.pop(mk)
    end
  elseif type(vm.debriefText) == "string" and vm.debriefText ~= "" then
    local raw = vm.debriefText
    if string.len(raw) > 160 then
      raw = string.sub(raw, 1, 157) .. "..."
    end
    drawWrapped(raw, 13, contentY, COLOR_TEXT_GREY, 4, "label")
  else
    local pk = fontMod.pushNamed("disp", 19)
    dwriteSafe("DRIVE A LAP", 19, vec2(padX, contentY), COLOR_WHITE)
    fontMod.pop(pk)
    local mk = fontMod.pushNamed("mono", 11)
    dwriteSafe("reference will appear", 11, vec2(padX, contentY + 28), COLOR_TEXT_GREY)
    fontMod.pop(mk)
  end

  -- Sector delta strip (bottom-anchored, mono, signal-toned) — the one piece
  -- of quantitative feedback that belongs to coaching, not the instrument.
  if type(vm.sectorMessage) == "string" and vm.sectorMessage ~= "" then
    local sectorStr = string.upper(vm.sectorMessage)
    local sk = fontMod.pushNamed("mono", 11)
    dwriteSafe(sectorStr, 11, vec2(padX, h - 26), colorForSectorMessage(vm.sectorMessage))
    fontMod.pop(sk)
  end
end

return M
