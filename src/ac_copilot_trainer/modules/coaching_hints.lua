-- Rules-based coaching strings (issue #9 Part A). Structured kinds for overlay (issue #39 Part F).
-- Hint order: weakest corners first (`consistencySummary().worstThree`), then throttle/coast fillers
-- up to three lines total. Display cap `config.coachingMaxVisibleHints` trims the UI only (issue #43).

local M = {}

local function cornerByLabel(corners, lab)
  if not corners or type(lab) ~= "string" then
    return nil
  end
  for i = 1, #corners do
    local c = corners[i]
    if type(c) == "table" and c.label == lab then
      return c
    end
  end
  return nil
end

local function labelFromConsistencyEntry(s)
  if type(s) ~= "string" then
    return nil
  end
  return s:match("^(%S+)")
end

--- Exported for `focus_practice` (issue #44) — first token of a `worstThree` row.
M.labelFromConsistencyEntry = labelFromConsistencyEntry

---@param text string
---@param kind "brake"|"throttle"|"line"|"positive"|"general"|nil
---@return table
local function hint(text, kind)
  return { kind = kind or "general", text = text }
end

--- Classify free-text hint for overlay accent colors.
local function kindForText(s)
  if type(s) ~= "string" then
    return "general"
  end
  local lower = s:lower()
  if lower:find("brak", 1, true) or lower:find("trail", 1, true) then
    return "brake"
  end
  if lower:find("throttle", 1, true) or lower:find("coasting", 1, true) or lower:find("reversals", 1, true) then
    return "throttle"
  end
  if lower:find("speed", 1, true) or lower:find("corner", 1, true) or lower:find("entry", 1, true) or lower:find("overdriving", 1, true) then
    return "line"
  end
  if lower:find("matched reference", 1, true)
      or (lower:find("well", 1, true) and lower:find("consistent", 1, true)) then
    return "positive"
  end
  return "general"
end

---@param lastFeats table[]|nil
---@param bestFeats table[]|nil
---@param cons table|nil consistencySummary()
---@param throttleAnalysis table|nil
---@param lapAnalysisOk boolean|nil
---@return table[] up to 3 hint tables { kind, text }
function M.buildAfterLap(lastFeats, bestFeats, cons, throttleAnalysis, lapAnalysisOk)
  local out = {}
  local function push(text, kind)
    if #out >= 3 or type(text) ~= "string" or text == "" then
      return
    end
    out[#out + 1] = hint(text, kind or kindForText(text))
  end

  local worst = cons and cons.worstThree
  if type(worst) == "table" then
    for i = 1, math.min(3, #worst) do
      if #out >= 3 then
        break
      end
      local lab = labelFromConsistencyEntry(worst[i])
      if lab then
        local c = cornerByLabel(lastFeats, lab)
        local b = cornerByLabel(bestFeats, lab)
        if c and b then
          local en, bn = tonumber(c.entrySpeed), tonumber(b.entrySpeed)
          local mn, mb = tonumber(c.minSpeed), tonumber(b.minSpeed)
          if en and bn and en > bn + 5 then
            push(string.format("%s: entry %.0f vs ref %.0f km/h — try braking slightly earlier", lab, en, bn), "brake")
          elseif mn and mb and mn + 4 < mb then
            push(string.format("%s: min speed %.0f vs ref %.0f km/h — carry more mid-corner", lab, mn, mb), "line")
          elseif mn and mb and mn > mb + 6 then
            push(string.format("%s: min speed %.0f vs ref %.0f km/h — you may be overdriving", lab, mn, mb), "line")
          end
        end
        if #out < 3 and c and b then
          local tb, tt = tonumber(c.trailBrakeRatio), tonumber(b.trailBrakeRatio)
          if tb and tt and math.abs(tb - tt) > 0.15 then
            if tb < tt - 0.15 then
              push(string.format("%s: less trail braking than ref — try easing off brakes more gradually", lab), "brake")
            elseif tb > tt + 0.15 then
              push(string.format("%s: more trail braking than ref — try releasing brakes earlier into turn-in", lab), "brake")
            end
          end
        end
      end
    end
  end
  if #out < 3 and throttleAnalysis and type(throttleAnalysis) == "table" then
    local coastSec = (tonumber(throttleAnalysis.coastingMs) or 0) / 1000
    if coastSec >= 1.2 then
      push(string.format("Coasting %.1fs last lap — shorten gaps to throttle", coastSec), "throttle")
    end
    local ft = tonumber(throttleAnalysis.fullThrottlePct)
    if #out < 3 and ft and ft < 40 then
      push(string.format("Full throttle only %d%% of lap — focus on earlier power application", math.floor(ft + 0.5)), "throttle")
    end
    local rev = tonumber(throttleAnalysis.reversals)
    if #out < 3 and rev and rev > 8 then
      push(string.format("Throttle reversals: %d — try smoother inputs", rev), "throttle")
    end
  end
  if #out == 0 then
    if not bestFeats or #bestFeats == 0 then
      push("Building reference — complete more laps for corner-by-corner coaching", "general")
    elseif lapAnalysisOk then
      push("Lap matched reference well — keep it consistent", "positive")
    else
      push("Lap recorded — need a full telemetry lap for corner-by-corner coaching", "general")
    end
  end
  return out
end

--- Real-time per-corner hint for a single corner (issue #57 Part D).
--- Compares last-lap features to best-lap features for the given corner label.
--- Returns a single {text, kind} hint or nil.
---@param cornerLabel string  e.g. "T5"
---@param lastFeats table[]|nil  last-lap corner features
---@param bestFeats table[]|nil  best-lap corner features
---@return table|nil  {text, kind}
function M.buildRealTime(cornerLabel, lastFeats, bestFeats)
  if type(cornerLabel) ~= "string" or cornerLabel == "" then
    return nil
  end
  local c = cornerByLabel(lastFeats, cornerLabel)
  local b = cornerByLabel(bestFeats, cornerLabel)
  if not c or not b then
    return nil
  end

  local en, bn = tonumber(c.entrySpeed), tonumber(b.entrySpeed)
  local mn, mb = tonumber(c.minSpeed), tonumber(b.minSpeed)

  -- Entry speed comparison
  if en and bn and en > bn + 5 then
    return hint(
      string.format("%s: entry %.0f vs ref %.0f km/h — brake earlier", cornerLabel, en, bn),
      "brake"
    )
  end

  -- Mid-corner: too slow
  if mn and mb and mn + 4 < mb then
    return hint(
      string.format("%s: carry more speed (%.0f vs ref %.0f km/h)", cornerLabel, mn, mb),
      "line"
    )
  end

  -- Mid-corner: overdriving
  if mn and mb and mn > mb + 6 then
    return hint(
      string.format("%s: you may be overdriving (%.0f vs ref %.0f km/h)", cornerLabel, mn, mb),
      "line"
    )
  end

  -- Trail braking
  local tb, tt = tonumber(c.trailBrakeRatio), tonumber(b.trailBrakeRatio)
  if tb and tt then
    if tb < tt - 0.15 then
      return hint(
        string.format("%s: try more trail braking into the turn", cornerLabel),
        "brake"
      )
    elseif tb > tt + 0.15 then
      return hint(
        string.format("%s: release brakes earlier into turn-in", cornerLabel),
        "brake"
      )
    end
  end

  -- Good approach
  if en and bn and math.abs(en - bn) <= 3 then
    return hint(
      string.format("%s: good approach speed", cornerLabel),
      "positive"
    )
  end

  return nil
end

return M
