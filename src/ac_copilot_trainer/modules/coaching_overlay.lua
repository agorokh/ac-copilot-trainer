-- Separate coaching overlay window -- transparent, top-right, large readable text.
-- Issue #35 Part C: coaching hints in their own Dear ImGui window, not buried in telemetry.
-- Auto-shows for configurable duration after lap completion, fades out.
-- Issue #37 Part C: added drawFallback for empty state.

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

  -- Window background is handled by manifest.ini FLAGS=NO_BACKGROUND.
  -- CSP calls Begin() before this function, so pushStyleColor(WindowBg)
  -- would be ineffective here (Bugbot #30). Text floats over the scene.

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

end

--- Fallback message when no coaching data is available yet.
--- Shows context-appropriate hint based on lap progress.
---@param lapsCompleted number|nil  Number of laps completed so far
function M.drawFallback(lapsCompleted)
  if not ui or type(ui.textColored) ~= "function" then return end
  local dimColor = rgbm(0.5, 0.5, 0.55, 0.6)
  if (lapsCompleted or 0) >= 1 then
    ui.textColored(dimColor, "Analyzing lap data...")
  else
    ui.textColored(dimColor, "Complete a lap for coaching hints")
  end
end

return M
