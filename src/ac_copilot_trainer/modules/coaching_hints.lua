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
---@param throttleHint string|nil
---@return string[] up to 3 lines
function M.buildAfterLap(lastFeats, bestFeats, cons, throttleHint)
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
            out[#out + 1] = string.format("%s: entry %.0f vs ref %.0f km/h — try braking slightly later", lab, en, bn)
          elseif mn and mb and mn + 4 < mb then
            out[#out + 1] = string.format("%s: min speed %.0f vs ref %.0f — carry more mid-corner", lab, mn, mb)
          elseif mn and mb and mn > mb + 6 then
            out[#out + 1] = string.format("%s: min speed %.0f vs ref %.0f — you may be overdriving", lab, mn, mb)
          end
        end
        if #out < 3 and c and b then
          local tb, tt = tonumber(c.trailBrakeRatio), tonumber(b.trailBrakeRatio)
          if tb and tt and math.abs(tb - tt) > 0.18 then
            if tb < tt - 0.12 then
              out[#out + 1] = string.format("%s: less trail braking than ref — try easing off brakes more gradually", lab)
            elseif tb > tt + 0.12 then
              out[#out + 1] = string.format("%s: more trail braking than ref — try releasing brakes earlier into turn-in", lab)
            end
          end
        end
      end
    end
  end
  if #out < 3 and throttleHint and throttleHint ~= "" then
    local coast = throttleHint:match("coast ([%d%.]+)s")
    if coast and tonumber(coast) and tonumber(coast) >= 1.2 then
      out[#out + 1] = string.format("Coasting %.1fs last lap — shorten gaps to throttle", tonumber(coast))
    end
  end
  while #out > 3 do
    table.remove(out)
  end
  return out
end

return M
