-- Separate coaching overlay window -- transparent, top-right, large readable text.
-- Issue #35 Part C: coaching hints in their own Dear ImGui window, not buried in telemetry.
-- Auto-shows for configurable duration after lap completion, fades out.

local M = {}

--- Draw the coaching overlay as a separate transparent window.
--- Called from drawUI (script.windowMainTransparent or a secondary window).
---@param coachingLines string[]|nil  Lines to display
---@param timeRemaining number  Seconds remaining before overlay hides (for fade)
---@param holdSeconds number  Total hold duration (for fade calculation)
function M.draw(coachingLines, timeRemaining, holdSeconds)
  if not coachingLines or #coachingLines == 0 then return end
  if timeRemaining <= 0 then return end

  -- Fade out over the last 5 seconds
  local fadeStart = 5.0
  local alpha = 1.0
  if timeRemaining < fadeStart then
    alpha = math.max(0, timeRemaining / fadeStart)
  end

  -- Set transparent window background (Dear ImGui style push)
  local stylePushed = false
  if type(ui.pushStyleColor) == "function" then
    local ok = pcall(ui.pushStyleColor, ui.StyleColor.WindowBg, rgbm(0.05, 0.05, 0.08, 0.65 * alpha))
    stylePushed = ok
  end

  -- Title bar
  local titleColor = rgbm(0.35, 0.82, 0.95, alpha)
  ui.textColored(titleColor, "COACHING")
  ui.separator()

  -- Coaching lines in large cyan text
  local lineColor = rgbm(0.35, 0.82, 0.95, alpha * 0.95)
  for i = 1, #coachingLines do
    local line = coachingLines[i]
    if line and line ~= "" then
      ui.textColored(lineColor, line)
    end
  end

  -- Fade indicator
  if timeRemaining < holdSeconds * 0.5 then
    local dimColor = rgbm(0.4, 0.4, 0.45, alpha * 0.5)
    ui.textColored(dimColor, string.format("(%.0fs)", timeRemaining))
  end

  -- Pop style only if push succeeded
  if stylePushed and type(ui.popStyleColor) == "function" then
    pcall(ui.popStyleColor)
  end
end

return M
