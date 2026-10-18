-- Frame-hitch watchdog. AC physics runs on its own thread while rendering and every CSP Lua app
-- share the main thread, so a multi-second main-thread job shows up as a frozen picture over a
-- car that keeps moving. This measures the wall time between `script.update` calls and how much
-- of it the trainer's own callbacks spent, by named section, so one log line says whether a
-- freeze is ours (and where) or something else on the main thread (CSP, Python apps, AC).
local M = {}

local TOP_SECTIONS = 6

function M.new(opts)
  opts = type(opts) == "table" and opts or {}
  local self = {
    threshold = opts.threshold or 0.25,
    maxLogs = opts.maxLogs or 40,
    clock = opts.clock,
    log = opts.log,
    sections = {},
    order = {},
    lastUpdate = nil,
    markT = nil,
    logged = 0,
  }

  function self:add(name, seconds)
    if type(seconds) ~= "number" or seconds ~= seconds or seconds < 0 then return end
    if self.sections[name] == nil then
      self.order[#self.order + 1] = name
      self.sections[name] = 0
    end
    self.sections[name] = self.sections[name] + seconds
  end

  --- Time one callback under `name`. An error inside `fn` propagates unchanged (CSP reports it
  --- as before); only that call's time is lost.
  function self:wrap(name, fn)
    return function(...)
      local t0 = self.clock()
      fn(...)
      self:add(name, self.clock() - t0)
    end
  end

  --- Sub-section of `script.update` (names start with "u:"): charges the time since the previous
  --- mark, or since the update started, to `name`. Excluded from the `ours` total, which already
  --- counts the whole update.
  function self:mark(name)
    if self.markT == nil then return end
    local now = self.clock()
    self:add(name, now - self.markT)
    self.markT = now
  end

  function self:summary()
    local total, rows = 0, {}
    for _, name in ipairs(self.order) do
      local s = self.sections[name]
      if name:sub(1, 2) ~= "u:" then total = total + s end
      rows[#rows + 1] = { name = name, s = s }
    end
    table.sort(rows, function(a, b) return a.s > b.s end)
    local parts = {}
    for i = 1, math.min(TOP_SECTIONS, #rows) do
      parts[#parts + 1] = string.format("%s=%.0fms", rows[i].name, rows[i].s * 1000)
    end
    return total, table.concat(parts, " ")
  end

  --- Call first thing in `script.update`. `context` (a string, or a function returning one, called
  --- only when a hitch is logged) is appended to the line. Returns the logged line or nil.
  function self:frame(context)
    local now = self.clock()
    local line
    if self.lastUpdate ~= nil then
      local gap = now - self.lastUpdate
      if gap >= self.threshold and self.logged < self.maxLogs then
        self.logged = self.logged + 1
        local ours, top = self:summary()
        if type(context) == "function" then
          local ok, text = pcall(context)
          context = ok and text or nil
        end
        line = string.format("[COPILOT][HITCH] gap=%.2fs ours=%.0fms %s%s",
          gap, ours * 1000, top, context and (" " .. context) or "")
        if self.log then self.log(line) end
      end
    end
    self.sections, self.order = {}, {}
    self.lastUpdate, self.markT = now, now
    return line
  end

  return self
end

return M
