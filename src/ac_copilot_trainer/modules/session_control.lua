-- Authenticated harness control. A command result never proves arrival in pits.
local M = {}

function M.new()
  local seen, count = {}, 0
  local self = {}

  -- Read-only navigation geometry. This is not pit admission or actuation authority.
  function self.pitBox(sessionId)
    local ok, result = pcall(function()
      local c, s = ac.getCar(0), ac.getSim()
      if not c or not s or s.isOnlineRace ~= false then return nil end
      local transform = c.pitTransform
      local p, d = transform.position, transform.look
      return { session_id = sessionId, offline = true, car_id = ac.getCarID(0),
        track_id = ac.getTrackID(), layout_id = ac.getTrackLayout() or "",
        position = { p.x, p.y, p.z }, look = { d.x, d.y, d.z } }
    end)
    return ok and result or nil
  end

  function self.handle(payload, sessionId)
    payload = type(payload) == "table" and payload or {}
    local reply = { request_id = payload.request_id, operation = "return_to_pits",
      session_id = sessionId, ok = false, native_result = "refused" }
    local function deny(reason)
      reply.error = reason
      return reply
    end
    if type(sessionId) ~= "string" or sessionId == "" or payload.session_id ~= sessionId then
      return deny("Native session changed or unavailable")
    end
    if type(payload.command_id) ~= "string" or #payload.command_id < 1
        or #payload.command_id > 64 or not payload.command_id:match("^[%w_-]+$")
        or type(payload.rig_owner_pid) ~= "number" or payload.rig_owner_pid <= 0
        or payload.rig_owner_pid % 1 ~= 0 or type(payload.rig_owner_started_at) ~= "string" then
      return deny("Malformed native control identity")
    end
    -- Keep old-session reservations too: an app reload creates a new SESSION_UUID.
    -- A full cache fails closed, with no eviction that could replay an old command.
    local key = sessionId .. ":" .. payload.command_id
    local signature = tostring(payload.rig_owner_pid) .. ":" .. payload.rig_owner_started_at
    local previous = seen[key]
    if previous then
      if previous.signature ~= signature then return deny("Conflicting command identity") end
      reply.ok, reply.native_result, reply.error = previous.ok, previous.native_result, previous.error
      reply.duplicate = true
      return reply
    end
    if count >= 128 then return deny("Native control cache full; no retry") end
    count = count + 1
    local record = { signature = signature, ok = false, native_result = "unknown" }
    seen[key] = record -- Reserve before state/API calls, including exceptions.
    local function finish(result, reason)
      record.native_result, record.error, record.ok = result, reason, result == "accepted"
      reply.native_result, reply.error, reply.ok = result, reason, record.ok
      return reply
    end
    local okClock, now = pcall(function() return os.time() end)
    if not okClock or type(now) ~= "number" or type(payload.deadline_epoch) ~= "number"
        or payload.deadline_epoch < now or payload.deadline_epoch > now + 6 then
      return finish("refused", "Native control expired or clock unavailable")
    end
    local okSim, offline = pcall(function() return ac.getSim().isOnlineRace == false end)
    if not okSim or not offline then return finish("refused", "Explicit offline session required") end
    if not (ac and type(ac.tryToTeleportToPits) == "function") then
      return finish("unavailable", "ac.tryToTeleportToPits unavailable")
    end
    -- CSP SDK: preserveDamage=true; never restart a session or load a setup.
    local okCall, accepted = pcall(ac.tryToTeleportToPits, true)
    if not okCall then return finish("exception", "ac.tryToTeleportToPits raised; no retry") end
    if accepted ~= true then return finish("refused", "Native pit-return command refused") end
    return finish("accepted", nil)
  end
  return self
end

return M
