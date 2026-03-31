-- Per-wheel telemetry via car.wheels (pcall); lap summary + lockup timer (issue #8 Part G).

local M = {}

local LOCKUP_SLIP = 0.35
local LOCKUP_HOLD = 0.1

local Mon = {}
Mon.__index = Mon

function M.new()
  return setmetatable({
    slipT = 0,
    lockups = {},
    lapTemps = { fl = {}, fr = {}, rl = {}, rr = {} },
    lapPeakSlip = { 0, 0, 0, 0 },
  }, Mon)
end

function Mon:resetLap()
  self.lapTemps = { fl = {}, fr = {}, rl = {}, rr = {} }
  self.lapPeakSlip = { 0, 0, 0, 0 }
end

local function pushTemp(bucket, v)
  if type(v) == "number" and v == v then
    bucket[#bucket + 1] = v
  end
end

local function summarizeTemps(bucket)
  if #bucket == 0 then
    return nil, nil, nil
  end
  local mn, mx, sum = bucket[1], bucket[1], 0
  for i = 1, #bucket do
    local v = bucket[i]
    if v < mn then
      mn = v
    end
    if v > mx then
      mx = v
    end
    sum = sum + v
  end
  return sum / #bucket, mn, mx
end

---@param car ac.StateCar|nil
---@param dt number
---@param spline number|nil
function Mon:update(car, dt, spline)
  if not car then
    return
  end
  local d = dt or 0
  local wheels ---@type any
  local okW, wobj = pcall(function()
    return car.wheels
  end)
  if not okW or wobj == nil then
    return
  end
  wheels = wobj
  local n = 4
  local okN, nn = pcall(function()
    return #wheels
  end)
  if okN and type(nn) == "number" and nn > 0 then
    n = math.min(nn, 4)
  end
  local anySlip = false
  for i = 1, n do
    local wi ---@type any
    local oki, one = pcall(function()
      return wheels[i]
    end)
    if oki and type(one) == "table" then
      wi = one
      local temp = wi.temperature or wi.tyreTemperature or wi.tyreCoreTemperature
      if type(temp) == "table" and temp.average ~= nil then
        temp = temp.average
      end
      if i == 1 then
        pushTemp(self.lapTemps.fl, tonumber(temp))
      elseif i == 2 then
        pushTemp(self.lapTemps.fr, tonumber(temp))
      elseif i == 3 then
        pushTemp(self.lapTemps.rl, tonumber(temp))
      else
        pushTemp(self.lapTemps.rr, tonumber(temp))
      end
      local slip = wi.slipRatio or wi.slip or wi.ndSlip
      slip = tonumber(slip) or 0
      if math.abs(slip) > math.abs(self.lapPeakSlip[i] or 0) then
        self.lapPeakSlip[i] = slip
      end
      if math.abs(slip) >= LOCKUP_SLIP then
        anySlip = true
      end
    end
  end
  if anySlip then
    self.slipT = self.slipT + d
  else
    self.slipT = 0
  end
  if self.slipT >= LOCKUP_HOLD and spline then
    self.lockups[#self.lockups + 1] = { spline = spline }
    self.slipT = 0
    if #self.lockups > 32 then
      table.remove(self.lockups, 1)
    end
  end
end

---@return string|nil
function Mon:lapSummaryLine()
  local a, amin, amax = summarizeTemps(self.lapTemps.fl)
  local b, bmin, bmax = summarizeTemps(self.lapTemps.fr)
  if not a and not b then
    return nil
  end
  local function fmt(name, avg, lo, hi)
    if not avg then
      return name .. " —"
    end
    return string.format("%s %.0f (%.0f–%.0f)", name, avg, lo, hi)
  end
  return table.concat({
    fmt("FL", a, amin, amax),
    fmt("FR", b, bmin, bmax),
  }, "  ")
end

function Mon:lockupFlash()
  return self.slipT > 0 and self.slipT < LOCKUP_HOLD * 2
end

return M
