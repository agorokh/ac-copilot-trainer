-- tools/ac_harness/dump_schema.lua
--
-- SCHEMA REFLECTION (EPIC #154 Part B) -- source-of-truth refresh for ac_schema.json.
--
-- REQUIRES THE ASSETTO CORSA PC. This is a tiny CSP app, NOT run in CI and NOT
-- run by the off-sim harness. It must execute inside a live Assetto Corsa + CSP
-- session, where `ac.getCar(0)` and `ac.getSim()` return the real C-struct
-- StateCar / StateSim. It dumps the field names and value-types those structs
-- actually expose to tools/ac_harness/ac_schema.json, which the off-sim mock in
-- trace_replay.py is gated against.
--
-- The bootstrap ac_schema.json shipped in this repo is CODE-DERIVED (grep of the
-- modules for the fields the trainer reads). It is a SUBSET of the real API. Run
-- this on the AC box when you want to widen/validate the schema against the
-- genuine CSP surface, or after a CSP update that may have changed field names.
--
-- HOW TO USE (on the AC PC)
-- -------------------------
--   1. Drop this folder where CSP can load it as a Lua app (or paste the body
--      into an existing app's update()), enter a session, and put a car on track.
--   2. The script writes ac_schema.json next to itself on the first frame that
--      both ac.getCar(0) and ac.getSim() are non-nil, then logs and stops.
--   3. Copy the produced ac_schema.json back into tools/ac_harness/ in the repo
--      (review the diff -- it should ADD fields, rarely remove them).
--
-- The list of fields we probe is intentionally the union of what the trainer
-- reads today (see ac_schema.json) plus a few neighbors, because the CSP
-- StateCar/StateSim C-structs do not support generic key iteration with pairs()
-- -- you can only read named fields, and reading a non-existent field can THROW
-- rather than return nil. So we pcall each candidate name and record only the
-- ones that resolve to a value.

local CAR_CANDIDATES = {
  -- fields the trainer reads today
  "speedKmh", "brake", "gas", "steer", "gear", "splinePosition",
  "look", "velocity", "position",
  -- neighbors worth recording if present (do not add to the gated set without
  -- a corresponding module read; recording is harmless, gating is not)
  "rpm", "drivetrainSpeed", "acceleration", "angularVelocity",
}

local SIM_CANDIDATES = {
  "isInMainMenu", "gameTime", "time",
  "trackLengthM", "trackGripLevel", "ambientTemperature", "trackTemperature",
  "isReplayActive", "isPaused", "carsCount",
}

local VEC3_SUBFIELDS = { "x", "y", "z" }

local function luaType(v)
  local t = type(v)
  if t == "userdata" or t == "cdata" then
    -- Probe for a vec3-shaped value (CSP returns vec3 userdata for look/pos/vel).
    local ok = pcall(function()
      return v.x + v.y + v.z
    end)
    if ok then
      return "vec3"
    end
  end
  return t
end

--- Probe one named field on a CSP C-struct. Returns (present, typeString).
local function probeField(struct, name)
  local ok, val = pcall(function()
    return struct[name]
  end)
  if not ok or val == nil then
    return false, nil
  end
  return true, luaType(val)
end

--- Escape a string for JSON: backslash first, then quote and the common control chars,
--- so a description/path containing `"` or `\` cannot produce malformed JSON (gemini).
local function escapeStr(s)
  s = tostring(s)
  s = s:gsub("\\", "\\\\")
  s = s:gsub('"', '\\"')
  s = s:gsub("\n", "\\n")
  s = s:gsub("\r", "\\r")
  s = s:gsub("\t", "\\t")
  return s
end

--- Encode a scalar (non-table) value with the correct JSON type — numbers, booleans, and
--- nil are NOT quoted (quoting them would emit `"true"` / `"123"`, which is wrong JSON).
local function encodeScalar(v)
  local tv = type(v)
  if tv == "number" then
    return tostring(v)
  elseif tv == "boolean" then
    return v and "true" or "false"
  elseif v == nil then
    return "null"
  end
  return '"' .. escapeStr(v) .. '"'
end

--- Minimal pretty-printing JSON serializer (CSP has no json.encode guarantee across
--- builds). Type-aware scalars + escaped string keys/values; stable key order for a
--- clean diff.
local function encode(tbl, indent)
  indent = indent or ""
  local nextIndent = indent .. "  "
  local parts = {}
  -- Stable key order for a clean diff.
  local keys = {}
  for k in pairs(tbl) do
    keys[#keys + 1] = k
  end
  table.sort(keys)
  for _, k in ipairs(keys) do
    local v = tbl[k]
    local encoded
    if type(v) == "table" then
      encoded = encode(v, nextIndent)
    else
      encoded = encodeScalar(v)
    end
    parts[#parts + 1] = nextIndent .. '"' .. escapeStr(k) .. '": ' .. encoded
  end
  return "{\n" .. table.concat(parts, ",\n") .. "\n" .. indent .. "}"
end

local _done = false
-- Bounded retry on write failure: retry a few frames (the app-data folder may not be ready
-- on the very first frame) then give up, so a permanently-bad path neither marks done with
-- no file nor spams ac.log every frame forever (Cursor).
local MAX_WRITE_ATTEMPTS = 30
local _writeAttempts = 0

local function dumpSchema()
  local car = ac.getCar(0)
  local sim = ac.getSim()
  if not car or not sim then
    return
  end

  local schema = {
    _note = "ON-BOX DUMP from a live AC session via tools/ac_harness/dump_schema.lua. "
      .. "Overwrites the code-derived bootstrap. Review the diff before committing.",
    car = {},
    sim = {},
  }

  for _, name in ipairs(CAR_CANDIDATES) do
    local present, t = probeField(car, name)
    if present then
      local entry = { type = t }
      if t == "vec3" then
        local subs = {}
        for _, s in ipairs(VEC3_SUBFIELDS) do
          subs[s] = "number"
        end
        entry.fields = subs
      end
      schema.car[name] = entry
    end
  end

  for _, name in ipairs(SIM_CANDIDATES) do
    local present, t = probeField(sim, name)
    if present then
      schema.sim[name] = { type = t }
    end
  end

  -- Write next to this script. ac.getFolder(ac.FolderID.AppLuaRoot) resolves the
  -- app's own directory in CSP.
  local out
  if ac and type(ac.getFolder) == "function" and ac.FolderID then
    out = ac.getFolder(ac.FolderID.AppLuaRoot) .. "/ac_schema.json"
  else
    out = "ac_schema.json"
  end
  local fh = io.open(out, "w")
  if fh then
    fh:write(encode(schema))
    fh:close()
    _done = true
    if ac and ac.log then
      ac.log("[ac_harness] wrote schema to " .. out)
    end
    return
  end
  -- Write failed: leave _done false so script.update retries on later frames, but stop after
  -- MAX_WRITE_ATTEMPTS so a permanently-bad path gives up cleanly instead of looping (Cursor).
  _writeAttempts = _writeAttempts + 1
  if _writeAttempts >= MAX_WRITE_ATTEMPTS then
    _done = true
    if ac and ac.log then
      ac.log(string.format(
        "[ac_harness] FAILED to open %s for writing after %d attempts", out, _writeAttempts))
    end
  end
end

-- CSP app entry points. update() is called each frame; we run once.
function script.update(_dt)
  if not _done then
    dumpSchema()
  end
end

-- Allow manual one-shot invocation from a console/REPL too.
return { dump = dumpSchema }
