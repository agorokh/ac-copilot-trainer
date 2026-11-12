-- #955 bounded shadow collector. No wheels, coaching decisions, or vehicle control.
-- Timestamps belong to the caller's clock; never subtract them from a Python clock.
local M = {}
local MAX_CARS = 128

local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end

local function field(obj, key)
  local ok, value = pcall(function() return obj[key] end)
  if ok then return value end
  return nil
end

function M.sample(sim, getCar, now)
  local out = { schema_version = 1, sampled_at_s = now, cars = {} }
  if not finite(now) or now < 0 then
    out.error = "traffic_clock_invalid"
    out.sampled_at_s = nil
    return out
  end
  local count = field(sim, "carsCount")
  local length = field(sim, "trackLengthM")
  if not finite(count) or count < 1 or count > MAX_CARS or count ~= math.floor(count) then
    out.error = "traffic_car_count_invalid"
    return out
  end
  out.cars_count = count
  if not finite(length) or length <= 0 then
    out.error = "traffic_track_length_invalid"
    return out
  end
  out.track_length_m = length
  for i = 0, count - 1 do
    local ok, car = pcall(getCar, i)
    if not ok or car == nil or field(car, "index") ~= i then
      out.error = "traffic_car_index_invalid"
      return out
    end
    local p = field(car, "position")
    local x, y, z = field(p, "x"), field(p, "y"), field(p, "z")
    local spline = field(car, "splinePosition")
    local speed = field(car, "speedKmh")
    local connected = field(car, "isConnected")
    local pit = field(car, "isInPitlane")
    if not finite(x) or not finite(y) or not finite(z)
        or not finite(spline) or spline < 0 or spline >= 1
        or not finite(speed) or speed < 0
        or type(connected) ~= "boolean" or type(pit) ~= "boolean" then
      out.error = "traffic_car_fields_invalid"
      return out
    end
    out.cars[#out.cars + 1] = {
      index = i, position = { x, y, z }, spline = spline, speed_kmh = speed,
      is_connected = connected, is_in_pitlane = pit,
    }
  end
  return out
end

function M.new(hz)
  assert(hz == 10 or hz == 20, "traffic sampling supports 10 or 20 Hz")
  local self = { interval = 1 / hz, last = nil, next_at = nil, snapshot = nil,
    frames = {}, started = nil, complete = false }
  function self:reset()
    self.last, self.next_at, self.snapshot, self.started = nil, nil, nil, nil
    self.frames, self.complete = {}, false
  end
  function self:update(now, sim, getCar)
    local regressed = finite(now) and self.last ~= nil and now < self.last
    if not finite(now) or self.next_at == nil or regressed
        or now >= self.next_at - 0.000001 then
      self.snapshot = M.sample(sim, getCar, now)
      if regressed then self.snapshot.error = "traffic_clock_regressed" end
      self.last = finite(now) and now or nil
      if self.last == nil then
        self.next_at = nil
      elseif self.next_at == nil or regressed then
        self.next_at = now + self.interval
      else
        -- Keep phase across render-frame jitter. A hitch skips missed deadlines:
        -- capture one real observation now, never manufacture catch-up frames.
        local periods = math.max(1, math.floor((now - self.next_at) / self.interval + 0.000001) + 1)
        self.next_at = self.next_at + periods * self.interval
      end
      if self.started == nil then self.started = self.last end
      if #self.frames < 12000 then
        self.frames[#self.frames + 1] = self.snapshot
      else
        self.complete = false
      end
      return self.snapshot, true
    end
    return self.snapshot, false
  end
  function self:finishLap(now)
    local capture = { schema_version = 1, frames = self.frames,
      started_at_s = self.started, ended_at_s = now, complete = self.complete }
    self.frames, self.started, self.complete = {}, now, true
    return capture
  end
  return self
end

return M
