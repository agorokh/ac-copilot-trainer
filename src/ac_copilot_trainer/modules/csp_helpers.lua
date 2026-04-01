-- Shared CSP global API helpers: pcall guards, id sanitization (issue #24 follow-up).

local M = {}

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

--- Reset CSP render state after Draw3D overlay draws (issue #33).
--- Depth: ReadOnlyLessEqual (AC::DepthMode = 4, acc-lua-sdk common/ac_render_enums.lua).
--- Match caller guards (`if not render`): render may be userdata with __index, not a plain table.
function M.restoreRenderDefaults()
  if not render then
    return
  end
  if type(render.setDepthMode) == "function" and render.DepthMode then
    local dm = render.DepthMode.ReadOnlyLessEqual
    if dm ~= nil then
      pcall(render.setDepthMode, dm)
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
