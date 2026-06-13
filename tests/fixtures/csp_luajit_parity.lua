-- LuaJIT (Lua 5.1) <-> lupa (Lua 5.5) parity shim for the L0 trace-replay harness.
--
-- WHY THIS EXISTS
-- ---------------
-- CSP runs the coaching modules under LuaJIT, which implements the Lua 5.1 API.
-- The off-sim trace-replay harness runs the SAME modules under lupa, which (as of
-- lupa 2.8) binds Lua 5.5. A handful of stdlib functions present in 5.1/LuaJIT
-- were removed in later Lua versions; calling them throws under lupa even though
-- they work fine in production. The runtime smoke test never caught this because
-- it only `require()`s the modules -- it never calls `:update`/`tick`, which is
-- where the missing functions are actually invoked.
--
-- This file installs the minimal set of 5.1-parity globals so the unmodified
-- modules behave identically under lupa as under CSP/LuaJIT. Keep it MINIMAL and
-- commented: every entry must correspond to a real call site in the modules.
--
-- VERIFIED GAPS (lupa 2.8 / Lua 5.5)
-- ----------------------------------
--   * math.atan2 -- removed in Lua 5.3+. brake_detection.lua:flatHeading() calls
--     math.atan2(y, x) for heading. Lua 5.5's two-arg math.atan(y, x) is the
--     direct equivalent (and is exactly what LuaJIT's math.atan2 computes).
--     Confirmed empirically: `math.atan2 ~= nil` is false under this lupa build,
--     and brake_detection:update() raised
--     "attempt to call a nil value (field 'atan2')" without this shim.
--
-- If you discover a module needs another 5.1-only function when you actually call
-- :update/tick under lupa, add it here (with a comment naming the call site) so
-- the harness and CSP stay in lockstep.

if not math.atan2 then
  -- LuaJIT/Lua 5.1: math.atan2(y, x). Lua 5.5: math.atan(y, x) is identical.
  math.atan2 = function(y, x)
    return math.atan(y, x)
  end
end

-- math.pow was removed in Lua 5.3 (use the ^ operator). The coaching modules do
-- not currently use it, but it is a common LuaJIT-ism; provide it defensively so
-- a future module edit that uses math.pow does not silently diverge between the
-- harness and CSP.
if not math.pow then
  math.pow = function(base, exp)
    return base ^ exp
  end
end

-- `unpack` was moved to table.unpack in Lua 5.2+. LuaJIT keeps the global
-- `unpack`. Alias it so any module that uses the bare global matches CSP.
if not unpack and table and table.unpack then
  unpack = table.unpack
end
