"""Exercise the real authoritative Lua catalogue with synthetic authored boundaries."""

from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

MODULES = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"


@pytest.fixture
def lua():
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(f'package.path = package.path .. ";{MODULES.as_posix()}/?.lua"')
    runtime.execute(
        """
        function vec3(x,y,z) return {x=x,y=y,z=z} end
        geometryCalls = 0
        trackID, trackLayout, geometryOffset = "synthetic-stadium", "", 0
        -- Two 50-metre-radius hairpins joined by 200-metre straights.
        local radius, straight = 50, 200
        trackLength = 2*straight + 2*math.pi*radius
        ac = {
          getTrackID=function() return trackID end,
          getTrackLayout=function() return trackLayout end,
          getSim=function() return {trackLengthM=trackLength} end,
          getTrackAISplineSides=function() return {x=5,y=5} end,
          trackCoordinateToWorld=function(v)
            geometryCalls = geometryCalls+1
            local d = ((v.z+geometryOffset) % 1)*trackLength
            local x,z,tx,tz
            if d < straight then
              x,z,tx,tz = d,0,1,0
            elseif d < straight+math.pi*radius then
              local a = -math.pi/2+(d-straight)/radius
              x,z,tx,tz = straight+radius*math.cos(a),radius+radius*math.sin(a),
                -math.sin(a),math.cos(a)
            elseif d < 2*straight+math.pi*radius then
              x,z,tx,tz = 2*straight+math.pi*radius-d,2*radius,-1,0
            else
              local a = math.pi/2+(d-2*straight-math.pi*radius)/radius
              x,z,tx,tz = radius*math.cos(a),radius+radius*math.sin(a),
                -math.sin(a),math.cos(a)
            end
            return {x=x-v.x*tz*5,y=0,z=z+v.x*tx*5}
          end,
        }
        function module(name) local m = require(name); return m end
        """
    )
    return runtime


def test_authored_midpoint_is_distinct_from_ai_racing_line_and_cached_by_track(lua):
    parser = lua.globals().module("spline_parser")
    # The racing line is offset inside the authored corridor. Neither those
    # unequal distances nor a legacy fast_lane parser become centerline points.
    lua.execute("ac.getTrackAISplineSides=function() return {x=3,y=7} end")
    parser.loadFastLane = lua.eval('function() error("racing-line reader must not be used") end')
    geometry = parser.loadTrackCenterline()
    assert geometry.source == "csp_authored_boundaries_midpoint"
    assert geometry.derived is True and geometry.closed is True
    assert 96 <= len(geometry.points) <= 2048
    assert geometry.points[1].width_m == pytest.approx(10)
    calls = lua.globals().geometryCalls
    parser.loadTrackCenterline()
    assert lua.globals().geometryCalls == calls
    lua.globals().trackID = "different-track"
    assert parser.loadTrackCenterline().track_id == "different-track"
    assert lua.globals().geometryCalls > calls
    calls = lua.globals().geometryCalls
    lua.globals().trackLayout = "different-layout"
    assert parser.loadTrackCenterline().layout == "different-layout"
    assert lua.globals().geometryCalls > calls


def test_curvature_catalogue_exists_without_brake_events_or_speed_minima(lua):
    geometry = lua.globals().module("spline_parser").loadTrackCenterline()
    rtc = lua.globals().module("realtime_coaching")
    rows, available, reason = rtc.buildCornerCatalog(lua.table(), geometry)
    assert available is True and len(rows) == 2
    assert [rows[i].corner_id for i in (1, 2)] == ["T1", "T2"]
    assert all(
        rows[i].derived and rows[i].anchor_source == "geometry_entry_boundary" for i in (1, 2)
    )
    assert all(rows[i].geometry_source == geometry.source for i in (1, 2))
    assert "identity only" in reason
    # Existing canonical labels always win, even when geometry is invalid.
    segments = lua.table_from(
        [lua.table_from(dict(kind="corner", label="T7", s0=0.2, s1=0.4, brakeSpline=0.19))]
    )
    rows, available, reason = rtc.buildCornerCatalog(segments, lua.table())
    assert available is True and len(rows) == 1 and rows[1].corner_id == "T7"
    assert reason == "active Lua reference segments"


def test_lua_fallback_binds_through_unchanged_python_geometry_guard(lua):
    from tools.ai_sidecar.track_map import bind_reference_corners
    from tools.ai_sidecar.track_reference import CornerReference

    rows, available, _reason = (
        lua.globals().module("realtime_coaching").buildCornerCatalog(lua.table())
    )
    assert available
    corner = rows[1]
    lo, hi = corner.s0, corner.s1
    assert lo < hi
    reference = CornerReference(0, (lo + hi) / 2, lo + 0.01, hi - 0.01, 100)
    catalog = [
        {name: rows[i][name] for name in ("corner_id", "s0", "s1", "brake_spline")}
        for i in range(1, len(rows) + 1)
    ]
    binding = bind_reference_corners(
        {"car": {"id": "synthetic-car"}, "track": {"id": "synthetic-stadium"}},
        [reference],
        {
            "available": True,
            "combo": ("synthetic-car", "synthetic-stadium", ""),
            "corners": catalog,
        },
    )
    assert binding["labels"] == {0: "T1"} and binding["eligible_count"] == 1


def test_normal_tick_publishes_catalogue_without_inventing_braking_targets(lua):
    rtc = lua.globals().module("realtime_coaching")
    view = rtc.tick(
        lua.table_from(
            dict(
                splinePos=0.1,
                currentSpeedKmh=100,
                trackLengthM=lua.globals().trackLength,
                bestSortedTrace=lua.table_from(
                    [
                        lua.table_from(dict(spline=0, speed=100)),
                        lua.table_from(dict(spline=1, speed=100)),
                    ]
                ),
                segments=lua.table(),
                brakingPoints=lua.table(),
            )
        )
    )
    assert view.cornerCatalogAvailable is True and len(view.cornerCatalog) == 2
    assert view.distToBrakeM is None and view.targetSpeedKmh is None
    assert view.selectedTargetAvailable is False


def test_start_finish_curve_keeps_one_wrapping_region(lua):
    lua.globals().geometryOffset = 0.35
    geometry = lua.globals().module("spline_parser").loadTrackCenterline()
    segments, _reason = lua.globals().module("corner_analysis").segmentsFromCenterline(geometry)
    assert len(segments) == 2
    assert sum(segments[i].s0 > segments[i].s1 for i in (1, 2)) == 1


@pytest.mark.parametrize("defect", ["zero_width", "nonfinite", "open", "missing_api"])
def test_invalid_authored_geometry_fails_closed(lua, defect):
    changes = {
        "zero_width": "ac.getTrackAISplineSides=function() return {x=0,y=5} end",
        "nonfinite": "ac.trackCoordinateToWorld=function() return {x=0/0,y=0,z=0} end",
        "open": "ac.trackCoordinateToWorld=function(v) return {x=v.z*1000,y=0,z=v.x*5} end",
        "missing_api": "ac.trackCoordinateToWorld=nil",
    }
    lua.execute(changes[defect])
    rows, available, reason = (
        lua.globals().module("realtime_coaching").buildCornerCatalog(lua.table())
    )
    assert rows is None and available is False and reason


def test_wrong_geometry_source_and_noise_never_create_corner_names(lua):
    parser = lua.globals().module("spline_parser")
    geometry = parser.loadTrackCenterline()
    geometry.source = "ai_racing_line"
    rows, available, _reason = (
        lua.globals().module("realtime_coaching").buildCornerCatalog(lua.table(), geometry)
    )
    assert rows is None and available is False
    # A huge-radius circle with tiny positional noise is below the curvature floor.
    lua.execute(
        """
        trackLength=2*math.pi*1000
        ac.trackCoordinateToWorld=function(v)
          local a=v.z*2*math.pi
          local r=1000+v.x*5+0.0001*math.sin(a*50)
          return {x=r*math.cos(a),y=0,z=r*math.sin(a)}
        end
        """
    )
    parser.clearTrackCenterlineCache()
    rows, available, reason = (
        lua.globals().module("realtime_coaching").buildCornerCatalog(lua.table())
    )
    assert rows is None and available is False and "no distinct" in reason


def test_malformed_existing_catalogue_cannot_use_fallback_to_hide_error(lua):
    segments = lua.table_from([lua.table_from(dict(kind="corner", label="T1", s0=0.2, s1=0.2))])
    rows, available, reason = lua.globals().module("realtime_coaching").buildCornerCatalog(segments)
    assert rows is None and available is False and "malformed" in reason
    assert lua.globals().geometryCalls == 0


@pytest.mark.parametrize("defect", ["sparse", "duplicate", "infinite_length", "zero_width"])
def test_malformed_centerline_cannot_manufacture_names(lua, defect):
    geometry = lua.globals().module("spline_parser").loadTrackCenterline()
    if defect == "sparse":
        geometry.points[3] = None
    elif defect == "duplicate":
        geometry.points[3] = geometry.points[2]
    elif defect == "infinite_length":
        geometry.length_m = float("inf")
    else:
        geometry.points[3].width_m = 0
    rows, available, reason = (
        lua.globals().module("realtime_coaching").buildCornerCatalog(lua.table(), geometry)
    )
    assert rows is None and available is False and reason
