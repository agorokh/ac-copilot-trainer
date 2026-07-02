-- Coaching overlay: panel + per-hint colors (issue #39 Part F); font + HUD strip (issue #41).
-- Approach telemetry panel: polished structured data display (issue #57 Part C).

local fontMod = require("coaching_font")
local T = require("design_tokens")

local M = {}

-- ---------------------------------------------------------------------------
-- Design tokens (Figma design brief, issue #57 Part C)
-- ---------------------------------------------------------------------------

-- Racing Atelier palette (epic #432 Part A) — sourced from design_tokens.lua (single source of
-- truth, validated against the design colors.css). Carbon ground, brass accent, signal fields.
local COLOR_BG           = T.color("carbon", 0.86)  -- carbon card ground (glass-fill alpha, blur waived)
local COLOR_BG_BORDER    = T.color("edge", 0.60)    -- structural edge
local COLOR_LABEL        = T.color("mute")          -- muted labels
local COLOR_LABEL_GREY   = T.color("mute")          -- small-caps labels
local COLOR_BRAND_GREY   = T.color("dim")           -- footer branding
local COLOR_TITLE        = T.color("brass")         -- house accent (was legacy cyan)
local COLOR_WHITE        = T.color("chalk")         -- primary text
local COLOR_GREEN        = T.color("clear")         -- on line / faster
local COLOR_RED          = T.color("brake")         -- danger / warning
local COLOR_AMBER        = T.color("lift")          -- caution / approaching
local COLOR_BAR_BG       = T.color("raise", 0.85)   -- delta bar trough
local COLOR_BRAND        = T.color("dim")           -- branding

local PANEL_ROUNDING = 0  -- Racing Atelier: square corners (--r: 0px)
local PANEL_PAD_X    = 24
local PANEL_PAD_Y    = 20

-- Shared token table consumed by hud.lua (single source of truth)
M.tokens = {
  COLOR_BG         = COLOR_BG,
  COLOR_BG_BORDER  = COLOR_BG_BORDER,
  COLOR_LABEL_GREY = COLOR_LABEL_GREY,
  COLOR_BRAND_GREY = COLOR_BRAND_GREY,
  COLOR_WHITE      = COLOR_WHITE,
  COLOR_RED        = COLOR_RED,
  COLOR_AMBER      = COLOR_AMBER,
  COLOR_GREEN      = COLOR_GREEN,
  PANEL_ROUNDING   = PANEL_ROUNDING,
  PANEL_PAD_X      = PANEL_PAD_X,
  PANEL_PAD_Y      = PANEL_PAD_Y,
}

-- ---------------------------------------------------------------------------
-- Speed color logic: green <= target, red > target+8, white in between
-- ---------------------------------------------------------------------------

---@param currentSpd number
---@param targetSpd number
---@return table @rgbm color
local function speedColor(currentSpd, targetSpd)
  local delta = currentSpd - targetSpd
  if delta > 8 then
    return COLOR_RED
  elseif delta <= 0 then
    return COLOR_GREEN
  end
  return COLOR_WHITE
end

-- ---------------------------------------------------------------------------
-- Approach instrument card (issue #432 Part A2 — photo-identical rebuild)
-- One unified 560px card mirroring templates/ingame-hud/InGameHud.dc.html:
-- header (corner badge + name + gear/speed columns) → CommandVerb + brake-point
-- readout → 12-cell SegmentBar → entry-delta DeltaBar. Fixed offsets from one
-- origin; all px values are the design's own (no scaling).
-- ---------------------------------------------------------------------------

--- Helper: measure DWrite text safely (returns vec2). CSP cdata-safe:
--- measureDWriteText can be an FFI cdata callable (type() == "cdata"), so
--- presence-check + pcall, never type() == "function". Fallback counts UTF-8
--- codepoints (not bytes) so "—" measures as one glyph.
local function _measureDW(text, fontPx)
  if ui ~= nil and ui.measureDWriteText ~= nil then
    local ok, sz = pcall(function() return ui.measureDWriteText(text, fontPx) end)
    if ok and sz and sz.x and sz.x > 0 then return sz end
  end
  local _, n = string.gsub(text or "", "[^\128-\191]", "")
  return vec2(n * fontPx * 0.55, fontPx)
end

--- Helper: draw DWrite text safely (same cdata-safe pattern as hud.dwriteSafe)
local function _drawDW(text, fontPx, position, color)
  if ui == nil or ui.dwriteDrawText == nil then return end
  pcall(function()
    ui.dwriteDrawText(text, fontPx, position, color)
  end)
end

--- ASCII-only uppercase. Lua's string.upper is locale/byte-wise and MANGLES
--- UTF-8 (0xE2 of "—" gets "uppercased" to 0xC2 under Windows locales),
--- corrupting em-dash placeholders and any unicode corner name.
local function asciiUpper(s)
  return (string.gsub(tostring(s), "[a-z]", function(c)
    return string.char(string.byte(c) - 32)
  end))
end

-- Card geometry (design canvas 560x338; template padding 22px 26px)
local CARD_PAD_X = 26
local CARD_PAD_Y = 22
local BRACKET_ARM = 14   -- --bracket: 14px
local BRACKET_W   = 2    -- --bracket-w: 2px

--- Brass corner brackets: four L-shapes overlapping the card border
--- (two filled rects per corner — keeps to the proven drawRectFilled surface).
local function drawBrackets(w, h)
  local arm, s = BRACKET_ARM, BRACKET_W
  local brass = T.color("brass")
  -- top-left
  ui.drawRectFilled(vec2(0, 0), vec2(arm, s), brass, 0)
  ui.drawRectFilled(vec2(0, 0), vec2(s, arm), brass, 0)
  -- top-right
  ui.drawRectFilled(vec2(w - arm, 0), vec2(w, s), brass, 0)
  ui.drawRectFilled(vec2(w - s, 0), vec2(w, arm), brass, 0)
  -- bottom-left
  ui.drawRectFilled(vec2(0, h - s), vec2(arm, h), brass, 0)
  ui.drawRectFilled(vec2(0, h - arm), vec2(s, h), brass, 0)
  -- bottom-right
  ui.drawRectFilled(vec2(w - arm, h - s), vec2(w, h), brass, 0)
  ui.drawRectFilled(vec2(w - s, h - arm), vec2(w, h), brass, 0)
end

--- CommandVerb arrow: crisp filled triangle from 1px rect slices (no glyph /
--- font-fallback risk — the LVGL port hit tofu on subset fonts, PR #430).
local function drawDownTriangle(cx, topY, triW, triH, color)
  local rows = math.max(4, math.floor(triH + 0.5))
  for i = 0, rows - 1 do
    local t = i / rows
    local halfW = (triW * 0.5) * (1 - t)
    if halfW < 0.5 then break end
    ui.drawRectFilled(
      vec2(cx - halfW, topY + i),
      vec2(cx + halfW, topY + i + 1),
      color, 0)
  end
end

local function drawUpTriangle(cx, topY, triW, triH, color)
  local rows = math.max(4, math.floor(triH + 0.5))
  for i = 0, rows - 1 do
    local t = i / rows
    local halfW = (triW * 0.5) * t
    if halfW >= 0.5 then
      ui.drawRectFilled(
        vec2(cx - halfW, topY + i),
        vec2(cx + halfW, topY + i + 1),
        color, 0)
    end
  end
end

--- Map the realtime engine's primary line to the design's CommandVerb
--- (one loud word + tone + optional arrow). The full engine vocabulary is
--- preserved: every primaryLine value maps to a distinct verb/tone and the
--- detailed line keeps rendering on WINDOW_0 (substance preservation, #432).
---@return string word, table toneColor, string|nil arrow
local function verbFor(kind, primaryLine, subState)
  local p = type(primaryLine) == "string" and primaryLine or ""
  -- Explicit verbs FIRST: the shift cue also fires in the no-reference state
  -- (it needs no lap), so the placeholder fallback must not shadow it.
  if p == "BRAKE NOW" then return "BRAKE", COLOR_RED, "down" end
  if p == "PREPARE TO BRAKE" then return "PREPARE", COLOR_AMBER, "down" end
  if p == "EASE OFF" then return "LIFT", COLOR_AMBER, "up" end
  if p == "CARRY MORE SPEED" then return "PUSH", COLOR_GREEN, "up" end
  if p == "SHIFT UP" then return "SHIFT", COLOR_AMBER, "up" end
  if p == "APPROACHING" then return "READY", COLOR_GREEN, nil end
  if p == "ON PACE" then return "ON PACE", COLOR_GREEN, nil end
  if subState == "no_reference" or p == "" or p == "DRIVE A LAP" then
    return "DRIVE", COLOR_LABEL, nil
  end
  local tone = COLOR_GREEN
  if kind == "brake" then
    tone = COLOR_RED
  elseif kind == "line" then
    tone = COLOR_AMBER
  end
  return p, tone, nil
end

--- Entry-delta status label (right side of the delta header). Replaces the
--- old WAITING/APPROACHING state word; tones follow DeltaBar.jsx (slack=4).
--- The imperative wording + signal tone only fire INSIDE the approach window
--- (mirroring the verb ladder) — the reference target always points at the
--- NEXT brake point, so flat-out on a straight being "+20 over" is normal
--- and must read as neutral reference data, not a red LIFT command.
local function deltaStatus(v, hasRef, inWindow)
  if not hasRef then
    return "WAITING", COLOR_LABEL
  end
  if v > 4 then
    if inWindow then return "TOO HOT — LIFT", COLOR_RED end
    return "ABOVE REF", COLOR_LABEL
  end
  if v < -4 then
    if inWindow then return "TOO SLOW", COLOR_AMBER end
    return "BELOW REF", COLOR_LABEL
  end
  return "ON LINE", COLOR_GREEN
end

--- Bottom tile: structured approach telemetry panel.
--- Renders panel chrome + footer + section labels when the required imgui
--- APIs are available, with `—` placeholders for any missing telemetry.
--- Returns `false` ONLY when the imgui primitives needed to draw the panel
--- (`ui.drawRectFilled`, `vec2`, etc.) are not present on this CSP build —
--- callers can treat that as "skip this frame, no panel drawn".
---@param approachData table|nil  ApproachHudPayload, or nil for placeholder render
---@return boolean @true if the panel was drawn; false if UI APIs unavailable
local _ovDiagLogged = false
function M.drawApproachPanel(approachData)
  if not _ovDiagLogged and ac and type(ac.log) == "function" then
    _ovDiagLogged = true
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
      "[COPILOT][OV-DIAG] win1 winSize=%s ui=%s vec2=%s rgbm=%s drawRectFilled=%s drawRect=%s dwriteDrawText=%s measureDWriteText=%s payload=%s",
      szStr,
      type(ui),
      type(vec2),
      type(rgbm),
      tt(ui, "drawRectFilled"), tt(ui, "drawRect"),
      tt(ui, "dwriteDrawText"), tt(ui, "measureDWriteText"),
      (type(approachData) == "table") and "y" or "N"
    ))
  end
  -- CSP cdata-callable safe check: vec2/ui.drawRectFilled are cdata, not "function"
  if not ui or vec2 == nil then
    return false
  end
  if ui.drawRectFilled == nil then
    return false
  end

  -- Resolve fields with placeholders so the layout NEVER collapses on empty state.
  local hasData       = type(approachData) == "table"
  local turnLabelRaw  = hasData and approachData.turnLabel or nil
  local turnLabel     = (type(turnLabelRaw) == "string" and turnLabelRaw ~= "") and turnLabelRaw or "—"
  local targetSpd     = hasData and tonumber(approachData.targetSpeedKmh) or nil
  local currentSpd    = hasData and tonumber(approachData.currentSpeedKmh) or nil
  local distanceM     = hasData and tonumber(approachData.distanceToBrakeM) or nil
  local progressPct   = hasData and tonumber(approachData.progressPct) or 0
  local subState      = hasData and tostring(approachData.subState or approachData.status or "no_reference") or "no_reference"
  local gear          = hasData and tonumber(approachData.gear) or nil
  local trackName     = hasData and approachData.trackName or nil
  local zonePct       = hasData and tonumber(approachData.zonePct) or 0.25
  local kind          = hasData and approachData.kind or nil
  local primaryLine   = hasData and approachData.primaryLine or nil
  local approachM     = hasData and tonumber(approachData.approachMeters) or 200
  local inWindow      = (distanceM ~= nil) and (distanceM <= approachM)
  local rpm           = hasData and tonumber(approachData.rpm) or nil
  local rpmLimiter    = hasData and tonumber(approachData.rpmLimiter) or nil
  local shiftZonePct  = hasData and tonumber(approachData.shiftZonePct) or 0.92
  local redZonePct    = hasData and tonumber(approachData.redZonePct) or 0.97

  -- Window dimensions (from manifest FIXED_SIZE 560x480 — the card IS the
  -- window). pcall like hud.safeWindowSize: windowSize is an FFI cdata
  -- callable on some CSP builds and must not crash the frame.
  local w, h = 560, 480
  if ui.windowSize ~= nil then
    local ok, sz = pcall(function() return ui.windowSize() end)
    if ok and sz and sz.x and sz.x > 0 and sz.y and sz.y > 0 then
      w, h = sz.x, sz.y
    end
  end

  -- Card ground — glass waived per council (CSP has no backdrop blur):
  -- flat carbon at the glass-fill alpha, 1px edge border, square corners.
  ui.drawRectFilled(vec2(0, 0), vec2(w, h), COLOR_BG, PANEL_ROUNDING)
  if type(ui.drawRect) == "function" then
    ui.drawRect(vec2(0, 0), vec2(w, h), COLOR_BG_BORDER, PANEL_ROUNDING, nil, 1)
  end
  drawBrackets(w, h)

  local padX = CARD_PAD_X
  local padY = CARD_PAD_Y
  local contentW = w - padX * 2

  ------------------------------------------------------------------
  -- HEADER: [T4] MAGIONE (corner badge + name — context, kept small)
  ------------------------------------------------------------------
  local hairY = padY + 37 + 14  -- header block 37 tall + 14 padding-bottom

  do
    local badgeText, nameText
    local digits = string.match(turnLabel, "^[Tt]?(%d+)")
    if digits then
      badgeText = "T" .. digits
      nameText = trackName and tostring(trackName) or turnLabel
    else
      badgeText = "T—"
      nameText = turnLabel
    end
    if not hasData then
      badgeText, nameText = "T—", trackName and tostring(trackName) or "—"
    end
    local nameY = padY + 10
    local bk = fontMod.pushNamed("disp", 14)
    local bSize = _measureDW(badgeText, 14)
    local badgeW = bSize.x + 12
    local badgeH = 20
    local badgeY = nameY + 3
    ui.drawRectFilled(vec2(padX, badgeY), vec2(padX + badgeW, badgeY + badgeH), COLOR_TITLE, 0)
    _drawDW(badgeText, 14, vec2(padX + 6, badgeY + 2), T.color("carbon"))
    fontMod.pop(bk)
    local nk = fontMod.pushNamed("disp", 22)
    _drawDW(asciiUpper(nameText), 22, vec2(padX + badgeW + 9, nameY), COLOR_WHITE)
    fontMod.pop(nk)
  end

  -- Header hairline (--line at reduced alpha over carbon ≈ chalk @ 0.07)
  ui.drawRectFilled(vec2(padX, hairY), vec2(w - padX, hairY + 1), T.color("chalk", 0.07), 0)

  ------------------------------------------------------------------
  -- VITALS ROW (main-dashboard evolution, operator-signed #432 Part A2):
  -- GEAR + KM/H as the loudest data on the card, LEFT-anchored, so this
  -- card replaces the stock dashboards. Hierarchy: vitals ≥ verb > context.
  ------------------------------------------------------------------
  local vitY = hairY + 1 + 16
  do
    local gearStr
    if gear == nil then
      gearStr = "—"
    elseif gear < 0 then
      gearStr = "R"
    elseif gear == 0 then
      gearStr = "N"
    else
      gearStr = string.format("%d", gear)
    end
    local spdStr = currentSpd and string.format("%.0f", currentSpd) or "—"
    local spdCol = (currentSpd and targetSpd) and speedColor(currentSpd, targetSpd) or COLOR_WHITE

    local lk = fontMod.pushNamed("label", 10)
    local gearLblW = _measureDW("GEAR", 10).x
    _drawDW("GEAR", 10, vec2(padX, vitY), COLOR_BRAND_GREY)
    fontMod.pop(lk)
    local vk = fontMod.pushNamed("read", 62)
    local gearW = _measureDW(gearStr, 62).x
    _drawDW(gearStr, 62, vec2(padX, vitY + 14), COLOR_WHITE)
    fontMod.pop(vk)

    local col2X = padX + math.max(gearW, gearLblW) + 44
    local lk2 = fontMod.pushNamed("label", 10)
    _drawDW("KM/H", 10, vec2(col2X, vitY), COLOR_BRAND_GREY)
    fontMod.pop(lk2)
    local vk2 = fontMod.pushNamed("read", 62)
    _drawDW(spdStr, 62, vec2(col2X, vitY + 14), spdCol)
    fontMod.pop(vk2)
  end
  local vitBottom = vitY + 14 + 62

  ------------------------------------------------------------------
  -- RPM STRIP with standing shift/redline zones (gear-shift coaching):
  -- 20 cells; filled cells chalk until the shift zone (solid lift) and
  -- redline band (solid brake); unfilled zone cells keep the standing
  -- tint so the driver SEES the target zone ahead — same zone language
  -- as the braking SegmentBar.
  ------------------------------------------------------------------
  local rpmCapY = vitBottom + 12
  local rpmY = rpmCapY + 11 + 7
  local RPM_H = 18
  do
    local lk = fontMod.pushNamed("label", 11)
    local rpmLbl = rpm and string.format("RPM · %d", math.floor(rpm + 0.5)) or "RPM · —"
    _drawDW(rpmLbl, 11, vec2(padX, rpmCapY), COLOR_BRAND_GREY)
    local zoneLbl = "SHIFT ZONE"
    local zlW = _measureDW(zoneLbl, 11).x
    local zoneActive = rpm and rpmLimiter and rpmLimiter > 0 and rpm >= rpmLimiter * shiftZonePct
    _drawDW(zoneLbl, 11, vec2(w - padX - zlW, rpmCapY), zoneActive and COLOR_AMBER or COLOR_BRAND_GREY)
    fontMod.pop(lk)

    local count = 20
    local gap = 2
    local cellW = (contentW - gap * (count - 1)) / count
    local frac = 0
    if rpm and rpmLimiter and rpmLimiter > 0 then
      frac = math.max(0, math.min(1, rpm / rpmLimiter))
    end
    local filledCount = math.floor(frac * count + 0.5)
    local shiftStart = math.floor(shiftZonePct * count + 0.5)
    local redStart = math.floor(redZonePct * count + 0.5)
    for i = 0, count - 1 do
      local filled = i < filledCount
      local cellColor
      if i >= redStart then
        cellColor = filled and COLOR_RED or T.color("brake", 0.16)
      elseif i >= shiftStart then
        cellColor = filled and COLOR_AMBER or T.color("lift", 0.16)
      else
        cellColor = filled and COLOR_WHITE or T.color("raise")
      end
      local x0 = padX + i * (cellW + gap)
      ui.drawRectFilled(vec2(x0, rpmY), vec2(x0 + cellW, rpmY + RPM_H), cellColor, 0)
    end
  end

  ------------------------------------------------------------------
  -- COMMAND ROW: giant verb (+ arrow) left, brake-point readout right
  ------------------------------------------------------------------
  local cmdY = rpmY + RPM_H + 18
  do
    local word, tone, arrow = verbFor(kind, primaryLine, subState)
    local vk = fontMod.pushNamed("verb", 66)
    local wordU = asciiUpper(word)
    local verbPx = 66
    local wordW = _measureDW(wordU, verbPx).x
    if wordW > 188 and wordW > 0 then
      verbPx = math.max(30, math.floor(66 * 188 / wordW))
      wordW = _measureDW(wordU, verbPx).x
    end
    _drawDW(wordU, verbPx, vec2(padX, cmdY), tone)
    fontMod.pop(vk)
    -- Arrow sits clearly BELOW the word (live capture showed it touching the
    -- glyph baseline at +0.92; the render has a visible gap under the B).
    if arrow == "down" then
      drawDownTriangle(padX + verbPx * 0.21 + 4, cmdY + verbPx + 6, verbPx * 0.30, verbPx * 0.24, tone)
    elseif arrow == "up" then
      drawUpTriangle(padX + verbPx * 0.21 + 4, cmdY + verbPx + 6, verbPx * 0.30, verbPx * 0.24, tone)
    end
  end

  -- Brake-point readout (right-aligned): label 11px, number 58px, unit mono 15px
  do
    local lk = fontMod.pushNamed("label", 11)
    local lblW = _measureDW("BRAKE POINT", 11).x
    _drawDW("BRAKE POINT", 11, vec2(w - padX - lblW, cmdY), COLOR_BRAND_GREY)
    fontMod.pop(lk)

    local distStr = distanceM and string.format("%d", math.floor(distanceM + 0.5)) or "—"
    local mk = fontMod.pushNamed("mono", 15)
    local unitW = _measureDW("m", 15).x
    fontMod.pop(mk)
    local nk = fontMod.pushNamed("read", 58)
    local numW = _measureDW(distStr, 58).x
    local numX = w - padX - unitW - 4 - numW
    _drawDW(distStr, 58, vec2(numX, cmdY + 16), COLOR_WHITE)
    fontMod.pop(nk)
    local mk2 = fontMod.pushNamed("mono", 15)
    _drawDW("m", 15, vec2(numX + numW + 4, cmdY + 16 + 58 - 20), COLOR_LABEL)
    fontMod.pop(mk2)
  end

  ------------------------------------------------------------------
  -- SEGMENT BAR: 12 cells, SegmentBar.jsx algorithm verbatim
  ------------------------------------------------------------------
  local segY = cmdY + 80 + 16
  local SEG_H = 26
  do
    local count = 12
    local gap = 3
    local cellW = (contentW - gap * (count - 1)) / count
    local f = math.max(0, math.min(1, progressPct or 0))
    local z = math.max(0, math.min(1, zonePct or 0))
    local filledCount = math.floor(f * count + 0.5)
    local zoneStart = count - math.floor(z * count + 0.5)
    for i = 0, count - 1 do
      local inZone = i >= zoneStart
      local filled = i < filledCount
      local leading = i == filledCount - 1
      local cellColor
      if filled and inZone then
        cellColor = COLOR_RED                    -- --seg-red
      elseif filled and leading then
        cellColor = COLOR_AMBER                  -- --seg-amb
      elseif filled then
        cellColor = COLOR_WHITE                  -- --seg-lit
      elseif inZone then
        cellColor = T.color("brake", 0.16)       -- --seg-zone
      else
        cellColor = T.color("raise")             -- --seg-off
      end
      local x0 = padX + i * (cellW + gap)
      ui.drawRectFilled(vec2(x0, segY), vec2(x0 + cellW, segY + SEG_H), cellColor, 0)
    end
  end

  -- Segment captions: NOW (dim) / BRAKE ZONE (brake)
  local capY = segY + SEG_H + 7
  do
    local lk = fontMod.pushNamed("label", 11)
    _drawDW("NOW", 11, vec2(padX, capY), COLOR_BRAND_GREY)
    local bzW = _measureDW("BRAKE ZONE", 11).x
    _drawDW("BRAKE ZONE", 11, vec2(w - padX - bzW, capY), COLOR_RED)
    fontMod.pop(lk)
  end

  ------------------------------------------------------------------
  -- ENTRY DELTA: header row, center-anchored DeltaBar, big signed number
  -- Design decision (#432 Part A2, recorded for the substance-preservation
  -- review): the pre-restyle 26px TARGET ENTRY readout is intentionally
  -- demoted to the 12px REF header + 10px scale caption per
  -- InGameHud.dc.html / ELEMENTS.md "one decision, sized to matter" — the
  -- 40px signed delta is the primary coaching cue now.
  ------------------------------------------------------------------
  local dltHdrY = capY + 11 + 22
  local troughY = dltHdrY + 12 + 10
  local TROUGH_H = 24
  local hasRef = (currentSpd ~= nil and targetSpd ~= nil)
  local vRaw = hasRef and (currentSpd - targetSpd) or 0
  local vMax = 20
  local v = math.max(-vMax, math.min(vMax, vRaw))
  do
    local hdrLeft = targetSpd
      and string.format("ENTRY Δ · REF %.0f KM/H", targetSpd)
      or "ENTRY Δ"
    local lk = fontMod.pushNamed("label", 12)
    _drawDW(hdrLeft, 12, vec2(padX, dltHdrY), COLOR_LABEL)
    local statusText, statusColor = deltaStatus(v, hasRef, inWindow)
    local stW = _measureDW(statusText, 12).x
    _drawDW(statusText, 12, vec2(w - padX - stW, dltHdrY), statusColor)
    fontMod.pop(lk)
  end

  do
    -- DeltaBar.jsx: tone by slack, fill grows from the center tick.
    -- Signal tones only inside the approach window (same gate as the
    -- status label); outside it the bar shows neutral reference data.
    local tone = COLOR_GREEN
    if v > 4 then
      tone = inWindow and COLOR_RED or COLOR_LABEL
    elseif v < -4 then
      tone = inWindow and COLOR_AMBER or COLOR_LABEL
    end
    if not hasRef then tone = COLOR_LABEL end

    local numMinW = 84
    local rowGap = 14
    local troughX = padX
    local troughW = contentW - rowGap - numMinW
    ui.drawRectFilled(vec2(troughX, troughY), vec2(troughX + troughW, troughY + TROUGH_H), COLOR_BAR_BG, 0)
    -- center tick (2px, overhangs 3px top/bottom)
    local tickX = troughX + troughW * 0.5 - 1
    ui.drawRectFilled(vec2(tickX, troughY - 3), vec2(tickX + 2, troughY + TROUGH_H + 3), COLOR_LABEL, 0)
    -- tone fill from center (neutral reference fill stays QUIET outside the
    -- approach window — full-alpha mute dominated the row in the live capture)
    if hasRef and math.abs(v) > 0.01 then
      local halfFrac = math.abs(v) / vMax * 0.5
      local fillW = troughW * halfFrac
      local fillColor = tone
      if tone == COLOR_LABEL then
        fillColor = T.color("mute", 0.40)
      end
      if v >= 0 then
        ui.drawRectFilled(vec2(troughX + troughW * 0.5, troughY), vec2(troughX + troughW * 0.5 + fillW, troughY + TROUGH_H), fillColor, 0)
      else
        ui.drawRectFilled(vec2(troughX + troughW * 0.5 - fillW, troughY), vec2(troughX + troughW * 0.5, troughY + TROUGH_H), fillColor, 0)
      end
    end
    -- big signed number, right-aligned, vertically centered on the trough.
    -- Round half-away-from-zero WITHOUT overshooting the ±vMax clamp
    -- (floor(v - 0.5) turned a clamped -20.0 into -21 in the live capture).
    local numStr = "—"
    if hasRef then
      local vInt
      if v >= 0 then
        vInt = math.floor(v + 0.5)
      else
        vInt = -math.floor(-v + 0.5)
      end
      numStr = (vInt > 0 and "+" or "") .. string.format("%d", vInt)
    end
    local nk = fontMod.pushNamed("read", 40)
    local numW = _measureDW(numStr, 40).x
    _drawDW(numStr, 40, vec2(w - padX - numW, troughY - 6), tone)
    fontMod.pop(nk)

    -- scale row: −20 / ref (mono) / +20. Dropped a few px below the design's
    -- +6 so the DWrite glyph box of the 40px number clears the "+20" label
    -- (they collided in the live capture).
    local scaleY = troughY + TROUGH_H + 10
    local lk = fontMod.pushNamed("label", 9)
    _drawDW("-20", 9, vec2(padX, scaleY), COLOR_BRAND_GREY)
    local p20W = _measureDW("+20", 9).x
    _drawDW("+20", 9, vec2(w - padX - p20W, scaleY), COLOR_BRAND_GREY)
    fontMod.pop(lk)
    if targetSpd then
      -- Centered on the FULL content row (DeltaBar.jsx scale row is a
      -- space-between flex across trough + gap + number column), not on
      -- the trough midline — the render shows it right of the center tick.
      local refStr = string.format("%.0f km/h", targetSpd)
      local mk = fontMod.pushNamed("mono", 10)
      local refW = _measureDW(refStr, 10).x
      _drawDW(refStr, 10, vec2(padX + contentW * 0.5 - refW * 0.5, scaleY), COLOR_BRAND_GREY)
      fontMod.pop(mk)
    end
  end

  return true
end

local function accentForKind(kind)
  local k = type(kind) == "string" and kind or "general"
  if k == "brake" then
    return rgbm(0.95, 0.30, 0.25, 1)
  end
  if k == "throttle" then
    return rgbm(0.25, 0.85, 0.35, 1)
  end
  if k == "line" then
    return rgbm(0.30, 0.70, 0.95, 1)
  end
  if k == "positive" then
    return rgbm(0.40, 0.90, 0.70, 1)
  end
  return rgbm(0.85, 0.85, 0.40, 1)
end

local function hintText(entry)
  if type(entry) == "table" and type(entry.text) == "string" then
    return entry.text
  end
  if type(entry) == "string" then
    return entry
  end
  return ""
end

local function hintKind(entry)
  if type(entry) == "table" and type(entry.kind) == "string" then
    return entry.kind
  end
  return "general"
end

--- Single clamp for `config.coachingMaxVisibleHints` (issue #43). Used by the entry script and both draw paths.
---@param raw any
---@return integer
function M.normalizedCoachingMaxVisibleHints(raw)
  local n = tonumber(raw)
  if not n or n ~= n then
    return 3
  end
  n = math.floor(n + 0.5)
  if n < 1 then
    return 1
  end
  if n > 3 then
    return 3
  end
  return n
end

--- Fade out in the last min(5s, hold) seconds so short `coachingHoldSeconds` stays at full opacity
--- until its own tail (CodeRabbit PR #50).
local function computeAlpha(timeRemaining, holdSeconds)
  local rem = math.max(0, timeRemaining or 0)
  local hold = tonumber(holdSeconds)
  if not hold or hold ~= hold or hold <= 0 then
    hold = 30
  end
  local fadeWindow = math.min(5.0, hold)
  if fadeWindow < 0.001 then
    fadeWindow = 0.001
  end
  if rem >= fadeWindow then
    return 1.0
  end
  return math.max(0, rem / fadeWindow)
end

--- Shared panel chrome for Coaching window idle / fallback states (PR #50 review).
local function drawStandardCoachingPanel(defaultW, defaultH, minH)
  local w, h = defaultW or 400, defaultH or 140
  local minHeight = minH or 100
  if ui.windowSize then
    local sz = ui.windowSize()
    if sz and sz.x and sz.y then
      w, h = sz.x, math.max(minHeight, sz.y)
    end
  end
  if ui.drawRectFilled and vec2 then
    ui.drawRectFilled(vec2(0, 0), vec2(w, h), rgbm(0.04, 0.04, 0.07, 0.78), 12)
  end
  if ui.drawRect and vec2 then
    ui.drawRect(vec2(0, 0), vec2(w, h), rgbm(0.4, 0.43, 0.5, 0.45), 12, nil, 1)
  end
end

---@param coachingLines table[]|string[]|nil
---@param timeRemaining number
---@param holdSeconds number
---@param maxVisibleHints integer|nil
function M.draw(coachingLines, timeRemaining, holdSeconds, maxVisibleHints)
  if not coachingLines or #coachingLines == 0 or timeRemaining <= 0 then
    return
  end
  if not ui or ui.textColored == nil then
    return
  end

  local alpha = computeAlpha(timeRemaining, holdSeconds)
  local hold = holdSeconds or 30

  local w, h = 400, 300
  if ui.windowSize then
    local sz = ui.windowSize()
    if sz and sz.x and sz.y then
      w, h = sz.x, sz.y
    end
  end
  if ui.drawRectFilled and vec2 then
    ui.drawRectFilled(vec2(0, 0), vec2(w, h), rgbm(0.05, 0.05, 0.08, 0.82 * alpha), 12)
  end
  if ui.drawRect and vec2 then
    ui.drawRect(vec2(0, 0), vec2(w, h), rgbm(0.45, 0.48, 0.55, 0.55 * alpha), 12, nil, 1)
  end

  local fk = fontMod.push()
  local titleColor = rgbm(0.35, 0.82, 0.95, alpha)
  ui.textColored("COACHING", titleColor)
  if ui.separator then
    ui.separator()
  end

  local cap = M.normalizedCoachingMaxVisibleHints(maxVisibleHints)
  local showN = math.min(cap, #coachingLines)
  for i = 1, showN do
    local body = hintText(coachingLines[i])
    if body ~= "" then
      local a = accentForKind(hintKind(coachingLines[i]))
      local col = rgbm(a.r, a.g, a.b, a.mult * alpha * 0.98)
      if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
        ui.pushStyleColor(ui.StyleColor.Text, col)
        ui.textWrapped(body)
        ui.popStyleColor()
      else
        ui.textColored(body, col)
      end
    end
  end

  fontMod.pop(fk)

  if timeRemaining < hold * 0.5 then
    ui.textColored(string.format("(%.0fs)", timeRemaining), rgbm(0.55, 0.58, 0.62, alpha * 0.65))
  end
end

function M.drawFallback()
  if not ui or ui.textColored == nil then
    return
  end
  drawStandardCoachingPanel(400, 120, 100)
  local fk = fontMod.push()
  ui.textColored("Complete a lap for coaching hints", rgbm(0.92, 0.93, 0.95, 0.95))
  fontMod.pop(fk)
  local sub = "Open the Coaching window (second app icon) for the full overlay after your first lap."
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, rgbm(0.65, 0.68, 0.74, 0.85))
    ui.textWrapped(sub)
    ui.popStyleColor()
  else
    ui.textColored(sub, rgbm(0.65, 0.68, 0.74, 0.85))
  end
end

--- Coaching window when session has started but no tip is active (timer expired or empty hints).
function M.drawBetweenLapsIdle(holdSeconds)
  if not ui or ui.textColored == nil then
    return
  end
  drawStandardCoachingPanel(400, 140, 120)
  local fk = fontMod.push()
  ui.textColored("COACHING", rgbm(0.35, 0.82, 0.95, 0.95))
  if ui.separator then
    ui.separator()
  end
  local hs = holdSeconds or 30
  local body = string.format(
    "No active tip right now. After each completed lap, hints show here for ~%ds. "
      .. "Complete another lap for fresh coaching, or check the main app window for telemetry.",
    math.floor(hs + 0.5)
  )
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, rgbm(0.72, 0.74, 0.78, 0.9))
    ui.textWrapped(body)
    ui.popStyleColor()
  else
    ui.textColored(body, rgbm(0.72, 0.74, 0.78, 0.9))
  end
  fontMod.pop(fk)
end

--- Lap completed and hold timer running, but `buildAfterLap` produced no lines (trace quality / first lap).
function M.drawHoldNoHints(remainingSec)
  if not ui or ui.textColored == nil then
    return
  end
  drawStandardCoachingPanel(400, 120, 100)
  local fk = fontMod.push()
  ui.textColored("COACHING", rgbm(0.35, 0.82, 0.95, 0.95))
  if ui.separator then
    ui.separator()
  end
  local r = math.max(0, remainingSec or 0)
  local body = string.format(
    "No hints for the last lap (needs a cleaner full lap or more data). Timer ~%.0fs — complete another lap to try again.",
    r
  )
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, rgbm(0.78, 0.72, 0.55, 0.92))
    ui.textWrapped(body)
    ui.popStyleColor()
  else
    ui.textColored(body, rgbm(0.78, 0.72, 0.55, 0.92))
  end
  fontMod.pop(fk)
end

--- Main telemetry window: primer or primary coaching line (issue #41).
---@class CoachingHudStrip
---@field coachingLines (string|{ kind: string, text: string })[]|nil
---@field coachingRemaining number|nil
---@field coachingHoldSeconds number|nil
---@field coachingMaxVisibleHints integer|nil
---@field coachingShowPrimer boolean|nil

---@param vm CoachingHudStrip
---@return boolean @true if anything was drawn (caller may add spacing only then)
function M.drawMainWindowStrip(vm)
  if not ui or ui.textColored == nil or vec2 == nil then
    return false
  end
  local lines = vm.coachingLines
  local rem = vm.coachingRemaining
  local hold = vm.coachingHoldSeconds or 30
  local maxVis = vm.coachingMaxVisibleHints
  local primer = vm.coachingShowPrimer

  local showActive = lines and #lines > 0 and rem and rem > 0
  local showPrimerBand = primer and not showActive
  if not showActive and not showPrimerBand then
    return false
  end

  if ui.separator then
    ui.separator()
  end

  local alpha = 1.0
  local title = "COACHING"
  local body
  local detail = ""
  local accent

  if showActive then
    alpha = computeAlpha(rem, hold)
    local cap = M.normalizedCoachingMaxVisibleHints(maxVis)
    local vis = math.min(#lines, cap)
    body = hintText(lines[1])
    accent = accentForKind(hintKind(lines[1]))
    if vis > 1 then
      detail = string.format("+%d more in Coaching window", vis - 1)
    end
  else
    title = "COACHING"
    body = "Complete a lap for coaching hints"
    detail = "Full hints appear here and in the Coaching window."
    accent = rgbm(0.88, 0.9, 0.94, 1)
  end

  local pad = vec2(10, 8)
  local region = vec2(0, 0)
  if type(ui.getCursor) == "function" then
    local ok, cur = pcall(ui.getCursor)
    if ok and cur and type(cur.x) == "number" and type(cur.y) == "number" then
      region = cur
    end
  end
  local rw = 360
  if type(ui.availableSpaceX) == "function" then
    rw = ui.availableSpaceX() or rw
  end
  -- Taller band so wrapped coaching lines do not clip the panel edges.
  local boxH = showPrimerBand and 92 or 118
  local p0 = vec2(region.x, region.y)
  local p1 = vec2(region.x + rw, region.y + boxH)
  if ui.drawRectFilled then
    ui.drawRectFilled(p0, p1, rgbm(0.04, 0.04, 0.07, 0.78 * alpha), 8)
  end
  if ui.drawRect then
    ui.drawRect(p0, p1, rgbm(0.42, 0.45, 0.52, 0.5 * alpha), 8, nil, 1)
  end

  if ui.setCursor then
    ui.setCursor(vec2(region.x + pad.x, region.y + pad.y))
  end

  local fk = fontMod.push()
  ui.textColored(title, rgbm(0.35, 0.82, 0.95, alpha))
  if ui.spacing then
    ui.spacing()
  end
  local colBody = rgbm(accent.r, accent.g, accent.b, accent.mult * alpha * 0.98)
  if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
    ui.pushStyleColor(ui.StyleColor.Text, colBody)
    ui.textWrapped(body)
    ui.popStyleColor()
  else
    ui.textColored(body, colBody)
  end
  if detail ~= "" then
    if ui.spacing then
      ui.spacing()
    end
    local colDet = rgbm(0.62, 0.65, 0.7, alpha * 0.85)
    if ui.textWrapped and ui.StyleColor and ui.pushStyleColor and ui.popStyleColor then
      ui.pushStyleColor(ui.StyleColor.Text, colDet)
      ui.textWrapped(detail)
      ui.popStyleColor()
    else
      ui.textColored(detail, colDet)
    end
  end
  fontMod.pop(fk)

  if ui.setCursor then
    ui.setCursor(vec2(region.x, region.y + boxH + 6))
  elseif ui.dummy then
    ui.dummy(vec2(1, 6))
  end
  return true
end

return M
