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

return M
