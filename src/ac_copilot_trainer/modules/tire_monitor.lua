-- Per-wheel telemetry via car.wheels (pcall); lap summary + lockup edge + flash timer (issue #8 Part G).

local M = {}

local LOCKUP_SLIP = 0.35
local LOCKUP_HOLD = 0.1
local LOCKUP_FLASH = 0.35

local Mon = {}
Mon.__index = Mon

function M.new()
  return setmetatable({
    slipHoldPerWheel = { 0, 0, 0, 0 },
    lockupRearm = true,
    lockupFlashT = 0,
    lockups = {},
    lapTemps = { fl = {}, fr = {}, rl = {}, rr = {} },
    lapPeakSlip = { 0, 0, 0, 0 },
  }, Mon)
end

function Mon:resetLap()
  self.lapTemps = { fl = {}, fr = {}, rl = {}, rr = {} }
  self.lapPeakSlip = { 0, 0, 0, 0 }
  self.slipHoldPerWheel = { 0, 0, 0, 0 }
  self.lockupRearm = true
  self.lockupFlashT = 0
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

--- Read field from table or userdata wheel object.
local function wheelField(one, key)
  local ok, v = pcall(function()
    return one[key]
  end)
  if ok and v ~= nil then
    return v
  end
  return nil
end

local function readWheelTemp(one)
  local temp = wheelField(one, "temperature") or wheelField(one, "tyreTemperature") or wheelField(one, "tyreCoreTemperature")
  if type(temp) == "table" and temp.average ~= nil then
    temp = temp.average
  end
  return tonumber(temp)
end

local function readWheelSlip(one)
  return tonumber(wheelField(one, "slipRatio") or wheelField(one, "slip") or wheelField(one, "ndSlip")) or 0
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
  local anySlip = false
  local maxHold = 0
  local hold = self.slipHoldPerWheel
  -- CSP `car.wheels` is 0-indexed per `ac.Wheel` (0=FL,1=FR,2=RL,3=RR); shipped CSP apps iterate
  -- `for i=0,3`. Read at the 0-based wheel index `wi`, map to the 1-based internal state slot
  -- (lapTemps/lapPeakSlip/hold) so the lap aggregates stay labeled FL/FR/RL/RR correctly. A car
  -- always has exactly 4 wheels, so we cover all four slots (no `#wheels` probe — unreliable on a
  -- 0-indexed CSP array) and reset a slot's lockup hold when its wheel is unreadable this frame.
  local lapBuckets = { self.lapTemps.fl, self.lapTemps.fr, self.lapTemps.rl, self.lapTemps.rr }
  for wi = 0, 3 do
    local slot = wi + 1
    local oki, one = pcall(function()
      return wheels[wi]
    end)
    if oki and one ~= nil then
      pushTemp(lapBuckets[slot], readWheelTemp(one))
      local slip = readWheelSlip(one)
      if math.abs(slip) > math.abs(self.lapPeakSlip[slot] or 0) then
        self.lapPeakSlip[slot] = slip
      end
      if math.abs(slip) >= LOCKUP_SLIP then
        anySlip = true
        hold[slot] = hold[slot] + d
        if hold[slot] > maxHold then
          maxHold = hold[slot]
        end
      else
        hold[slot] = 0
      end
    else
      hold[slot] = 0
    end
  end
  if not anySlip then
    self.lockupRearm = true
  end
  if self.lockupFlashT > 0 then
    self.lockupFlashT = math.max(0, self.lockupFlashT - d)
  end
  -- One log per slip episode: lockupRearm false until all wheels drop below threshold. HUD uses lockupFlashT, not hold timers.
  if maxHold >= LOCKUP_HOLD and self.lockupRearm then
    if spline then
      self.lockups[#self.lockups + 1] = { spline = spline }
      if #self.lockups > 32 then
        table.remove(self.lockups, 1)
      end
    end
    for j = 1, 4 do
      hold[j] = 0
    end
    self.lockupRearm = false
    self.lockupFlashT = LOCKUP_FLASH
  end
end

--- Current per-wheel core temps {fl, fr, rl, rr}, read live from `car.wheels` (issue #180
--- `tire_temps` producer). Read-only; each value is a number or nil if unavailable. Reuses the
--- same `readWheelTemp` fallback chain and wheel order (0=fl,1=fr,2=rl,3=rr) as :update, so the
--- streamed temps agree with the lap aggregates. pcall-guards every `car.wheels` access.
---
--- CSP `car.wheels` is **0-indexed** per `ac.Wheel` (FrontLeft=0, FrontRight=1, RearLeft=2,
--- RearRight=3). Shipped CSP apps iterate `for i=0,3` (e.g. CMRT-Essential-HUD). The earlier
--- 1-based read (`wheels[1..4]`) shifted every corner by one and read an out-of-bounds zero-
--- struct for RR — the live `tire_temps.rr=0` regression confirmed against the AC physics oracle.
---@param car any
---@return table  {fl, fr, rl, rr}
function Mon:currentTemps(car)
  local out = { fl = nil, fr = nil, rl = nil, rr = nil }
  if not car then
    return out
  end
  local okW, wheels = pcall(function()
    return car.wheels
  end)
  if not okW or wheels == nil then
    return out
  end
  local keys = { [0] = "fl", [1] = "fr", [2] = "rl", [3] = "rr" }
  for i = 0, 3 do
    local oki, one = pcall(function()
      return wheels[i]
    end)
    if oki and one ~= nil then
      out[keys[i]] = readWheelTemp(one)
    end
  end
  return out
end

---@return string|nil
function Mon:lapSummaryLine()
  local a, amin, amax = summarizeTemps(self.lapTemps.fl)
  local b, bmin, bmax = summarizeTemps(self.lapTemps.fr)
  local c, cmin, cmax = summarizeTemps(self.lapTemps.rl)
  local dd, dmin, dmax = summarizeTemps(self.lapTemps.rr)
  if not a and not b and not c and not dd then
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
    fmt("RL", c, cmin, cmax),
    fmt("RR", dd, dmin, dmax),
  }, "  ")
end

function Mon:lockupFlash()
  return self.lockupFlashT > 0
end

return M
