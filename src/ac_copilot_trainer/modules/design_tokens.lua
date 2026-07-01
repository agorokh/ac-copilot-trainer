-- Racing Atelier design tokens for the in-game HUD (CSP Lua) — epic #432 Part A.
--
-- Canonical source of truth: docs/10_Development/design/racing-atelier/project/tokens/colors.css.
-- tests/test_hud_design_tokens.py parses both this file and colors.css and asserts the hex
-- values match, so this adapter cannot silently drift from the design of record (fleet pitfall:
-- redundant-code-drift — do not hand-copy tokens into N runtimes without a conformance check).
--
-- HEX is kept as plain strings so the conformance test needs no Lua runtime; M.color() builds a
-- CSP rgbm on demand (rgbm is a CSP global, only referenced at render time, never at require).

local M = {}

--- Canonical hex, mirroring colors.css :root.
M.HEX = {
  carbon = "#0B0C0D",   -- base ground (near-black; OLED off)
  graphite = "#141618", -- panel
  slab = "#191C1F",     -- raised band
  raise = "#20242A",    -- control trough / inactive
  edge = "#2A2F35",     -- structural border
  chalk = "#EEF1F3",    -- primary text / lit
  mute = "#9BA1A8",     -- labels
  dim = "#79808A",      -- meta / demoted
  faint = "#4A4E55",    -- disabled
  brass = "#C8983E",    -- house accent / structure
  brake = "#F23B2C",    -- danger / too hot / loss
  lift = "#F4A52C",     -- caution / approaching
  clear = "#2FBE6E",    -- on line / faster / gain
  data = "#49B6C9",     -- neutral telemetry highlight
}

local function _rgb(hexstr, a)
  local r = tonumber(hexstr:sub(2, 3), 16)
  local g = tonumber(hexstr:sub(4, 5), 16)
  local b = tonumber(hexstr:sub(6, 7), 16)
  return rgbm(r / 255, g / 255, b / 255, a or 1.0)
end

--- Build a CSP rgbm from a token name at the given alpha (default opaque).
---@param name string  a key in M.HEX
---@param a number|nil  alpha 0..1 (default 1.0)
function M.color(name, a)
  local hex = M.HEX[name]
  if hex == nil then
    error("Unknown design token: " .. tostring(name))
  end
  return _rgb(hex, a)
end

return M
