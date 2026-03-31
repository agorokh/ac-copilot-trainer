-- Rules-based coaching strings (issue #9 Part A). ML/LLM deferred to sidecar Phase 3 later parts.

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

--- Parse "T3 62%" -> "T3"
local function labelFromConsistencyEntry(s)
  if type(s) ~= "string" then
    return nil
  end
  return s:match("^(%S+)")
end

---@param lastFeats table[]|nil
---@param bestFeats table[]|nil
---@param cons table|nil consistencySummary()
---@param throttleAnalysis table|nil from throttle_detection.analyzeTrace (fullThrottlePct, coastingMs, reversals, …)
---@return string[] up to 3 lines
function M.buildAfterLap(lastFeats, bestFeats, cons, throttleAnalysis)
  local out = {}
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
            out[#out + 1] = string.format("%s: entry %.0f vs ref %.0f km/h — try braking slightly earlier", lab, en, bn)
          elseif mn and mb and mn + 4 < mb then
            out[#out + 1] = string.format("%s: min speed %.0f vs ref %.0f km/h — carry more mid-corner", lab, mn, mb)
          elseif mn and mb and mn > mb + 6 then
            out[#out + 1] = string.format("%s: min speed %.0f vs ref %.0f km/h — you may be overdriving", lab, mn, mb)
          end
        end
        if #out < 3 and c and b then
          local tb, tt = tonumber(c.trailBrakeRatio), tonumber(b.trailBrakeRatio)
          if tb and tt and math.abs(tb - tt) > 0.15 then
            if tb < tt - 0.15 then
              out[#out + 1] = string.format("%s: less trail braking than ref — try easing off brakes more gradually", lab)
            elseif tb > tt + 0.15 then
              out[#out + 1] = string.format("%s: more trail braking than ref — try releasing brakes earlier into turn-in", lab)
            end
          end
        end
      end
    end
  end
  if #out < 3 and throttleAnalysis and type(throttleAnalysis) == "table" then
    local coastSec = (tonumber(throttleAnalysis.coastingMs) or 0) / 1000
    if coastSec >= 1.2 then
      out[#out + 1] = string.format("Coasting %.1fs last lap — shorten gaps to throttle", coastSec)
    end
    local ft = tonumber(throttleAnalysis.fullThrottlePct)
    if #out < 3 and ft and ft < 40 then
      out[#out + 1] = string.format("Full throttle only %d%% of lap — focus on earlier power application", math.floor(ft + 0.5))
    end
    local rev = tonumber(throttleAnalysis.reversals)
    if #out < 3 and rev and rev > 8 then
      out[#out + 1] = string.format("Throttle reversals: %d — try smoother inputs", rev)
    end
  end
  -- Fallback: when no corner-vs-reference hints and no throttle hints generated, give a status line
  if #out == 0 then
    if not bestFeats or #(bestFeats or {}) == 0 then
      out[#out + 1] = "Building reference — complete more laps for corner-by-corner coaching"
    else
      out[#out + 1] = "Lap matched reference well — keep it consistent"
    end
  end
  while #out > 3 do
    table.remove(out)
  end
  return out
end

return M
