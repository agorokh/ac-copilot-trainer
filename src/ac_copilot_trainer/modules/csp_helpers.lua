-- Shared CSP global API helpers: pcall guards, id sanitization (issue #24 follow-up).

local M = {}

--- Monotonic sim clock for HUD timers that compare absolute deadlines (sector, post-lap).
--- Prefer `sim.gameTime`; fallback `sim.time`. **Units vary by CSP build** (see vault ADR);
--- coaching **display duration** uses `state.coachingRemainSec` decremented by `script.update(dt)`
--- instead of this clock — issue #9.
---@param sim ac.StateSim|nil
---@return number
function M.simSeconds(sim)
  if not sim then
    return 0
  end
  local okg, g = pcall(function()
    return sim.gameTime
  end)
  if okg and type(g) == "number" then
    return g
  end
  local okt, t = pcall(function()
    return sim.time
  end)
  if okt and type(t) == "number" then
    return t
  end
  return 0
end

--- Mutate a CSP vec3 in place (supports :set or .x/.y/.z).
---@param v userdata|table|nil
function M.setV3(v, x, y, z)
  if not v then
    return
  end
  if v.set then
    local ok = pcall(v.set, v, x, y, z)
    if not ok then
      v.x, v.y, v.z = x, y, z
    end
  else
    v.x, v.y, v.z = x, y, z
  end
end

--- Set shader quad rgbm field (`values.gColor`, `values.gCol`, …): try `:set` then replace.
---@param values table|nil
---@param key string|number
function M.setRgbmField(values, key, r, g, b, a)
  if not values or not rgbm then
    return
  end
  local c = values[key]
  if c and c.set then
    local ok = pcall(c.set, c, r, g, b, a)
    if ok then
      return
    end
  end
  values[key] = rgbm(r, g, b, a)
end

function M.sanitizeId(s, fallback)
  s = tostring(s or fallback or "unknown"):gsub("[^%w%.%-_]+", "_")
  if s == "" then
    s = fallback or "unknown"
  end
  return s
end

function M.safeCarIdRaw()
  if not ac or type(ac.getCarID) ~= "function" then
    return nil
  end
  local ok, v = pcall(ac.getCarID, 0)
  if not ok then
    return nil
  end
  return v
end

function M.safeTrackIdRaw()
  if not ac or type(ac.getTrackID) ~= "function" then
    return nil
  end
  local ok, v = pcall(ac.getTrackID)
  if not ok then
    return nil
  end
  return v
end

function M.safeTrackLayoutRaw()
  if not ac or type(ac.getTrackLayout) ~= "function" then
    return nil
  end
  local ok, v = pcall(ac.getTrackLayout)
  if not ok then
    return nil
  end
  return v
end

--- Best-effort track label from globals: `getTrackFullID("/")` then `getTrackID()`; returns string or nil.
function M.trackIdRawFromGlobals()
  if ac and type(ac.getTrackFullID) == "function" then
    local ok, full = pcall(ac.getTrackFullID, "/")
    if ok and type(full) == "string" and full ~= "" then
      return full
    end
  end
  local tid = M.safeTrackIdRaw()
  if tid ~= nil and tostring(tid) ~= "" then
    return tostring(tid)
  end
  return nil
end

--- Best-effort player car id from `ac.getCarID(0)`; returns string or nil.
function M.carIdRawFromGlobals()
  local cid = M.safeCarIdRaw()
  if cid ~= nil and tostring(cid) ~= "" then
    return tostring(cid)
  end
  return nil
end

--- Reset CSP render state after each Draw3D overlay module (issue #33).
--- Overlay draws set ReadOnlyLessEqual at their start; restore depth to Normal so we do not
--- leave the same mode as the draw (no-op) or leak overlay state to other Draw3D users.
--- Match caller guards (`if not render`): render may be userdata with __index, not a plain table.
function M.restoreRenderDefaults()
  if not render then
    return
  end
  if type(render.setDepthMode) == "function" and render.DepthMode then
    local n = render.DepthMode.Normal
    if n ~= nil then
      pcall(render.setDepthMode, n)
    end
  end
  if type(render.setBlendMode) == "function" and render.BlendMode then
    local o = render.BlendMode.Opaque
    if o ~= nil then
      pcall(render.setBlendMode, o)
    end
  end
  if type(render.setCullMode) == "function" and render.CullMode then
    local b = render.CullMode.Back
    if b ~= nil then
      pcall(render.setCullMode, b)
    end
  end
end

return M
