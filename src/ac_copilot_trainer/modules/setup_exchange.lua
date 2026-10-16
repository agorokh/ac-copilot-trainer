-- #86: use the same supported CSP signing/session flow as the bundled Setup Exchange app.
-- This provider only reads the community service. The sidecar owns safe installation,
-- and setup_library owns the existing pits/reset-allowed apply gate.
local M = {}
-- Keep signed session headers and downloaded data encrypted in transit.
local ENDPOINT = "https://se.acstuff.club"
local MAX_PENDING, TIMEOUT = 8, 20
local pending, clock, contextKey = {}, 0, nil
local sessionID, authenticating, authGeneration = nil, false, 0

local function context()
  local ok, value = pcall(function()
    local sim = ac.getSim()
    return tostring(ac.getCarID(0)) .. "\n" .. tostring(ac.getTrackID())
      .. "\n" .. tostring(sim and sim.currentSessionIndex)
  end)
  return ok and value or nil
end

local function finish(job, response, err, total)
  if pending[job.id] ~= job then return end
  pending[job.id] = nil
  local result = {request_id = job.id, operation = job.operation, ok = err == nil}
  if err then result.error = err else result.response, result.total_count = response, total end
  job.complete(result)
end

local function active(job)
  if pending[job.id] ~= job then return false end
  if context() ~= job.context then
    finish(job, nil, "Setup Exchange context changed; search again")
    return false
  end
  if clock >= job.deadline then
    finish(job, nil, "Setup Exchange request timed out")
    return false
  end
  return true
end

local function parse(response, limit)
  if type(response) ~= "table" or type(response.body) ~= "string" or #response.body > limit then return nil end
  local ok, parsed = pcall(JSON.parse, response.body)
  return ok and type(parsed) == "table" and parsed or nil
end

local function responseStatus(response)
  return type(response) == "table" and tonumber(response.status) or 0
end

local function request(method, path, headers, body, callback)
  local ok = pcall(function()
    web.request(method, ENDPOINT .. path, headers, body, callback)
  end)
  if not ok then callback(true) end
end

local function encode(value)
  local ok, result = pcall(JSON.stringify, value)
  return ok and result or nil
end

local function validID(value)
  return type(value) == "string" and #value > 0 and #value <= 128 and value:match("^[%w_%-%.]+$") ~= nil
end

local function escape(value)
  return tostring(value):gsub("([^%w%.%-%_])", function(c) return string.format("%%%02X", string.byte(c)) end)
end

-- Public fields only: never forward arbitrary service objects, auth headers or errors.
local ROW_FIELDS = {"setupID", "carID", "trackID", "name", "userName", "createdDate",
  "statDownloads", "statLikes", "statDislikes", "statComments"}
local function publicRow(row)
  if type(row) ~= "table" then return nil end
  local out = {}
  for _, key in ipairs(ROW_FIELDS) do
    local value = row[key]
    if type(value) == "string" then
      if #value > 512 then return nil end
      out[key] = value
    elseif type(value) == "number" and value == value and math.abs(value) < math.huge then out[key] = value end
  end
  return out
end

local run, ensureSession
local function authDone(generation, id)
  if generation ~= authGeneration then return end
  authenticating, sessionID = false, id
  -- Snapshot: synchronous CSP mocks and failures may finish a job while iterating.
  local waiting = {}
  for _, job in pairs(pending) do if job.waiting then waiting[#waiting + 1] = job end end
  for _, job in ipairs(waiting) do
    job.waiting = false
    if active(job) then
      if id then run(job) else finish(job, nil, "Setup Exchange authentication failed") end
    end
  end
end

ensureSession = function(job)
  if not active(job) then return end
  if sessionID then run(job); return end
  job.waiting = true
  if authenticating then return end
  authenticating = true
  authGeneration = authGeneration + 1
  local generation = authGeneration
  local function current() return generation == authGeneration and context() == job.context end
  local function fail() authDone(generation, nil) end
  local ok = pcall(function()
    if ac.getPatchVersionCode() < 3050 then fail(); return end
    ac.uniqueMachineKeyAsync(function(err, machineKey)
      if not current() then return end
      if err or type(machineKey) ~= "string" then fail(); return end
      -- Public service namespace from the official CSP app, not a credential.
      local hashOK, userID = pcall(ac.checksumSHA256, "LB83XurHhTPhpmTc" .. machineKey) -- pragma: allowlist secret
      if not hashOK or type(userID) ~= "string" then fail(); return end
      request("POST", "/session", {["X-Session-ID"] = "0"}, encode({userID = userID}), function(postErr, response)
        if not current() then return end
        local parsed = not postErr and parse(response, 16384)
        local status = responseStatus(response)
        if not parsed or status < 200 or status >= 300 or type(parsed.key) ~= "string" then fail(); return end
        local signOK = pcall(function()
          require("shared/utils/signing").blob("{UniqueMachineKeyChecksum}", parsed.key, function(signature, header)
            if not current() then return end
            if type(signature) ~= "string" or type(header) ~= "string" then fail(); return end
            local bodyOK, body = pcall(function()
              return encode({userID = userID, header = ac.encodeBase64(header),
                signature = ac.encodeBase64(signature), carID = ac.getCarID(0), carName = ac.getCarName(0),
                trackID = ac.getTrackID(), trackName = ac.getTrackName()})
            end)
            if not bodyOK or not body then fail(); return end
            request("PATCH", "/session", {["X-Session-ID"] = "0"}, body, function(patchErr, patched)
              if not current() then return end
              local data = not patchErr and parse(patched, 16384)
              local status = responseStatus(patched)
              if not data or status < 200 or status >= 300 or type(data.sessionID) ~= "string"
                  or #data.sessionID == 0 or #data.sessionID > 1024 then fail(); return end
              authDone(generation, data.sessionID)
            end)
          end)
        end)
        if not signOK then fail() end
      end)
    end)
  end)
  if not ok then fail() end
end

run = function(job)
  if not active(job) then return end
  local path = "/setups/" .. tostring(job.setupID or "")
  if job.operation == "search" then
    path = "/setups?carID=" .. escape(job.carID) .. "&offset=" .. job.offset .. "&limit=" .. job.limit
      .. "&orderBy=" .. escape(job.orderBy)
    if job.trackID then path = path .. "&trackID=" .. escape(job.trackID) end
    if job.search then path = path .. "&search=" .. escape(job.search) end
  end
  local usedSession = sessionID
  request("GET", path, {["X-Session-ID"] = usedSession, ["Content-Type"] = "application/json"}, nil,
    function(err, response)
      if not active(job) then return end
      local parsed = not err and parse(response, job.operation == "search" and 2097152 or 1048576)
      local status = responseStatus(response)
      local invalid = status == 401 or status == 403
        or (parsed and (parsed.error == "Invalid session ID" or parsed.error == "Error: Invalid session ID"))
      if invalid and not job.retried then
        job.retried = true
        if sessionID == usedSession then sessionID = nil end
        ensureSession(job)
        return
      end
      if err or status < 200 or status >= 300 or not parsed then
        finish(job, nil, "Setup Exchange service request failed"); return
      end
      if job.operation == "download" then
        if (parsed.carID ~= nil and parsed.carID ~= job.carID)
            or (parsed.trackID ~= nil and job.trackID ~= nil and parsed.trackID ~= job.trackID) then
          finish(job, nil, "Setup Exchange returned a different car or track"); return
        end
        if type(parsed.data) ~= "string" or #parsed.data > 524288 then
          finish(job, nil, "Setup Exchange setup data is invalid or too large"); return
        end
        local row = publicRow(parsed)
        if not row then finish(job, nil, "Setup Exchange returned invalid setup metadata"); return end
        row.data = parsed.data
        finish(job, row)
      else
        if #parsed > job.limit then finish(job, nil, "Setup Exchange returned too many setups"); return end
        for key in pairs(parsed) do
          if type(key) ~= "number" or key < 1 or key > #parsed or key % 1 ~= 0 then
            finish(job, nil, "Setup Exchange returned invalid setups"); return
          end
        end
        local rows = {}
        for i = 1, #parsed do
          local row = publicRow(parsed[i])
          if not row then finish(job, nil, "Setup Exchange returned invalid setups"); return end
          if row.carID ~= nil and row.carID ~= job.carID then
            finish(job, nil, "Setup Exchange returned a different car"); return
          end
          rows[i] = row
        end
        local headers = response.headers or {}
        local total = tonumber(headers["x-total-count"] or headers["X-Total-Count"])
        if not total or total ~= total or total < #rows or total >= math.huge then total = #rows end
        finish(job, rows, nil, math.floor(total))
      end
    end)
end

function M.handle(payload, complete)
  payload = type(payload) == "table" and payload or {}
  local id, operation = payload.request_id, payload.operation
  local function reject(message)
    complete({request_id = id, operation = operation, ok = false, error = message})
  end
  if type(id) ~= "string" or #id ~= 32 or not id:match("^[0-9a-f]+$") then reject("Invalid request ID"); return end
  if operation ~= "search" and operation ~= "download" then reject("Invalid Setup Exchange operation"); return end
  if not validID(payload.car_id) then reject("Invalid car ID"); return end
  local current = context()
  if not current or payload.car_id ~= ac.getCarID(0) then reject("Requested car is not active"); return end
  if pending[id] then reject("Duplicate Setup Exchange request"); return end
  local count = 0
  for _ in pairs(pending) do count = count + 1 end
  if count >= MAX_PENDING then reject("Setup Exchange is busy"); return end
  local job = {id = id, operation = operation, carID = payload.car_id, context = current,
    deadline = clock + TIMEOUT, complete = complete}
  if payload.track_id ~= nil and not validID(payload.track_id) then reject("Invalid track ID"); return end
  job.trackID = payload.track_id
  if operation == "search" then
    local offset, limit = tonumber(payload.offset or 0), tonumber(payload.limit or 40)
    if not offset or offset < 0 or offset > 100000 or offset % 1 ~= 0
        or not limit or limit < 1 or limit > 40 or limit % 1 ~= 0 then reject("Invalid search page"); return end
    if payload.search ~= nil and (type(payload.search) ~= "string" or #payload.search > 200) then reject("Invalid search text"); return end
    local sorts = { ["-statDownloads"] = true, ["name"] = true, ["-createdDate"] = true }
    local order = payload.order_by or "-statDownloads"
    if not sorts[order] then reject("Invalid search order"); return end
    job.offset, job.limit, job.trackID, job.search, job.orderBy = offset, limit, payload.track_id, payload.search, order
  else
    local setupID = tonumber(payload.setup_id)
    if not setupID or setupID <= 0 or setupID > 2147483647 or setupID % 1 ~= 0 then reject("Invalid setup ID"); return end
    job.setupID = setupID
  end
  pending[id] = job
  if contextKey ~= current then
    contextKey, sessionID, authenticating = current, nil, false
    authGeneration = authGeneration + 1
  end
  ensureSession(job)
end

-- Frame delta advances in paused pit menus; simulated session time does not.
function M.tick(dt)
  if type(dt) == "number" and dt == dt and dt >= 0 and dt < math.huge then clock = clock + dt end
  local current = context()
  if current ~= contextKey then
    contextKey, sessionID, authenticating = current, nil, false
    authGeneration = authGeneration + 1
  end
  local jobs = {}
  for _, job in pairs(pending) do jobs[#jobs + 1] = job end
  for _, job in ipairs(jobs) do active(job) end
  if authenticating and next(pending) == nil then
    authenticating = false
    authGeneration = authGeneration + 1
  end
end

return M
