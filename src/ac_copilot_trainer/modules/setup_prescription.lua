-- Cold-pressure experiment RPC. Only the sidecar sends this internal request;
-- each mutation rechecks actual pit-box state inside setup_library's setter.
local M = {}
local library = require("setup_library")
local reader = require("setup_reader")
local persistence = require("persistence")
local decisions, decisionCount = {}, 0
local latestContext = nil
local PRESSURES = { PRESSURE_LF = true, PRESSURE_RF = true, PRESSURE_LR = true, PRESSURE_RR = true }

local function finite(v)
  return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge
end

local function context(sessionId)
  local ok, car, sim = pcall(function() return ac.getCar(0), ac.getSim() end)
  if not ok or not car then return nil, "Car unavailable" end
  local okFields, pit, compound = pcall(function() return car.isInPit, car.compoundIndex end)
  if not okFields or type(pit) ~= "boolean" or not finite(compound) then
    return nil, "Pit or compound state unavailable"
  end
  local ident = library.activeIdentity()
  ident.session_id = sessionId
  ident.compound_index = compound
  ident.setup_path = reader.activeSetupIniPath(car, sim) or ""
  local spinners = library.listSpinners()
  if spinners.source ~= "csp" then return nil, "Live CSP spinners unavailable" end
  return { identity = ident, spinners = spinners.spinners, is_in_pit = pit,
    reset_allowed = library.capability().reset_allowed, lap_dir = persistence.lapArchiveDir() }
end

local function sameIdentity(a, b)
  if type(a) ~= "table" or type(b) ~= "table" then return false end
  for _, key in ipairs({ "car_id", "track_id", "layout_id", "compound_index", "session_id", "setup_path" }) do
    if a[key] ~= b[key] then return false end
  end
  return true
end

local function clock()
  return (os.preciseClock and os.preciseClock()) or os.clock()
end

function M.handle(payload, sessionId, captureIsolated)
  local out = { request_id = payload.request_id, operation = payload.operation, ok = false }
  local ctx, err = context(sessionId)
  if not ctx then out.error = err; return out end
  out.identity = ctx.identity
  if payload.operation == "context" then
    latestContext = { id = payload.request_id, at = clock(), identity = ctx.identity }
    out.ok, out.context_id = true, payload.request_id
    out.spinners, out.is_in_pit = ctx.spinners, ctx.is_in_pit
    out.reset_allowed, out.lap_dir = ctx.reset_allowed, ctx.lap_dir
    out.capture_isolated = captureIsolated == true
    return out
  end
  if not sameIdentity(payload.identity, ctx.identity) then
    out.error = "Session, compound or setup changed"; return out
  end
  if payload.operation == "readback" then
    out.ok, out.readback = true, {}
    for _, row in ipairs(ctx.spinners or {}) do
      if PRESSURES[row.section] then out.readback[row.section] = row.value end
    end
    return out
  end
  if payload.operation ~= "apply" then out.error = "Unknown prescription operation"; return out end
  local id = payload.prescription_id
  if type(id) ~= "string" or #id < 1 or #id > 64 or id:find("[^%w_-]") then
    out.error = "Invalid prescription id"; return out
  end
  if decisions[id] then out.error = "Prescription already attempted"; return out end
  if decisionCount >= 256 then out.error = "Prescription session capacity reached"; return out end
  if not latestContext or latestContext.id ~= payload.context_id
      or clock() - latestContext.at < 0 or clock() - latestContext.at > 5
      or not sameIdentity(latestContext.identity, ctx.identity) then
    out.error = "Prescription context expired"; return out
  end
  if ctx.is_in_pit ~= true or ctx.reset_allowed ~= true then
    out.error = "Prescription requires the pit box"; return out
  end
  local changes = payload.changes
  if type(changes) ~= "table" or #changes < 1 or #changes > 4 then
    out.error = "Invalid pressure changes"; return out
  end
  local bySection, seen = {}, {}
  for _, row in ipairs(ctx.spinners or {}) do bySection[row.section] = row end
  for _, change in ipairs(changes) do
    local row = bySection[change.section]
    local before, after = change.from, change.to
    if not PRESSURES[change.section] or seen[change.section] or not row
        or row.range_known ~= true or row.read_only == true
        or type(row.unit) ~= "string" or not row.unit:lower():match("^%s*psi%s*$")
        or row.display_multiplier ~= 1
        or not finite(before) or not finite(after) or not finite(row.value)
        or not finite(row.min) or not finite(row.max) or not finite(row.step) or row.step <= 0
        or math.abs(row.value - before) > 0.000001 or math.abs(after - before) > 1.5
        or math.abs(after - before) < 0.5 or after < row.min or after > row.max
        or math.abs((after - row.min) / row.step - math.floor((after - row.min) / row.step + 0.5)) > 0.000001 then
      out.error = "Pressure value, bounds or current setup changed"; return out
    end
    seen[change.section] = true
  end
  -- Mark before any setter. A partial or uncertain result is never retried.
  decisions[id], decisionCount = true, decisionCount + 1
  out.readback = {}
  for _, change in ipairs(changes) do
    local ack = library.setSpinner({ section = change.section, value = change.to,
      require_pit_box = true, prescription_id = id })
    if not ack.ok or not ack.confirmed then
      out.error = ack.error or "Awaiting setup readback"; return out
    end
  end
  -- A later setter can have a coupled effect on an earlier corner. Verify the
  -- entire resulting cold setup together, after all setters have completed.
  local final, finalError = context(sessionId)
  if not final or not sameIdentity(payload.identity, final.identity) then
    out.error = finalError or "Setup identity changed during application"; return out
  end
  local actual = {}
  for _, row in ipairs(final.spinners or {}) do actual[row.section] = row.value end
  for _, change in ipairs(changes) do
    if not finite(actual[change.section]) or math.abs(actual[change.section] - change.to) > 0.000001 then
      out.error = "Awaiting complete cold-pressure readback"; return out
    end
    out.readback[change.section] = actual[change.section]
  end
  out.ok = true
  return out
end

return M
