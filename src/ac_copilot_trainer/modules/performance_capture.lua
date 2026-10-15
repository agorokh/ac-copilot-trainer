-- Opt-in, bounded CSP render/UI intervals. These are not OS presentation timings.
local M = {}

local function finite(v)
  return type(v) == "number" and v == v and v > -math.huge and v < math.huge
end

local function scalar(v)
  if type(v) == "cdata" then
    local ok, number = pcall(tonumber, v)
    return ok and number or nil
  end
  return v
end

function M.new()
  local self = { active = false }

  function self:start(args, now)
    args = type(args) == "table" and args or {}
    local seconds = args.seconds == nil and 60 or scalar(args.seconds)
    local id = args.capture_id
    if self.active then return false, "capture already active" end
    if type(id) ~= "string" or #id < 1 or #id > 64 or not id:match("^[%w_-]+$") then
      return false, "capture_id must be 1-64 letters/digits/underscore/hyphen"
    end
    if not finite(seconds) or seconds < 1 or seconds > 120 or not finite(now) then
      return false, "capture duration must be 1-120 seconds"
    end
    self.active, self.id, self.started, self.seconds = true, id, now, seconds
    self.rows, self.count, self.duplicates, self.gaps, self.invalid = {}, 0, 0, 0, 0
    self.lastFrame, self.lastClock, self.chunk = nil, now, 0
    self.lastSampleClock = nil
    self.rawFrameType, self.rawFrameValue, self.rawDtType = nil, nil, nil
    return true, "CSP UI/render interval capture armed"
  end

  function self:flush(now, publish, reason)
    self.chunk = self.chunk + 1
    publish("performance.frames", {
      capture_id = self.id, source = "csp_ui_dt", units = "ms", chunk = self.chunk,
      rows = self.rows, complete = reason ~= nil, reason = reason,
      elapsed_s = math.max(0, now - self.started), sample_count = self.count,
      duplicates = self.duplicates, gaps = self.gaps, invalid_dt = self.invalid,
      raw_frame_type = self.rawFrameType, raw_frame_value = self.rawFrameValue,
      raw_dt_type = self.rawDtType,
      callback_clock = "os.preciseClock",
    })
    self.rows = {}
    if reason then self.active = false end
  end

  function self:tick(frame, dt, paused, now, publish)
    if not self.active then return end
    if self.rawFrameType == nil then
      self.rawFrameType, self.rawFrameValue = type(frame), tostring(frame):sub(1, 64)
      self.rawDtType = type(dt)
    end
    frame, dt = scalar(frame), scalar(dt)
    if not finite(now) or now < self.lastClock then
      self:flush(self.lastClock, publish, "clock_reset")
      return
    end
    self.lastClock = now
    local expired = now - self.started >= self.seconds
    if not finite(frame) or frame < 0 or frame > 9007199254740991 or frame % 1 ~= 0 then
      self:flush(now, publish, "invalid_frame")
      return
    end
    if self.lastFrame ~= nil then
      if frame < self.lastFrame then self:flush(now, publish, "frame_reset"); return end
      if frame == self.lastFrame then
        self.duplicates = self.duplicates + 1
        if expired then self:flush(now, publish, "duration") end
        return
      end
      if frame > self.lastFrame + 1 then self.gaps = self.gaps + frame - self.lastFrame - 1 end
    end
    self.lastFrame = frame
    if not finite(dt) or dt <= 0 or dt > 10 then
      self.invalid = self.invalid + 1
      if expired then self:flush(now, publish, "duration") end
      return
    end
    self.count = self.count + 1
    self.rows[#self.rows + 1] = {frame = frame, dt_ms = dt * 1000, paused = paused == true,
      callback_ms = self.lastSampleClock and (now - self.lastSampleClock) * 1000 or nil,
      clock_offset_s = now - self.started}
    self.lastSampleClock = now
    if expired then self:flush(now, publish, "duration")
    elseif self.count >= 20000 then self:flush(now, publish, "sample_limit")
    elseif #self.rows >= 128 then self:flush(now, publish, nil) end
  end

  return self
end

return M
