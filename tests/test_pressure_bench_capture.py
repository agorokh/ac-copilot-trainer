"""Execute production Lua promotion/persistence boundaries under capture isolation."""

import re
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
APP = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/ac_copilot_trainer.lua"


def function_source(name):
    source = APP.read_text(encoding="utf-8")
    start = source.index(f"local function {name}(")
    following = re.search(r"^end\s*$", source[start:], re.MULTILINE)
    assert following
    return source[start : start + following.end()]


@pytest.mark.parametrize("name", ["persistSnapshotLive", "persistSnapshotCached"])
def test_capture_never_saves_human_state_but_normal_mode_still_saves(name):
    rt = lupa.LuaRuntime()
    rt.execute("""
      config={};pressureBenchCapture=true;car={};sim={};lastDriveCar={};lastDriveSim={}
      saves=0; persistence={save=function() saves=saves+1;return true end}
      persistPayload=function() return {} end
    """)
    rt.execute(function_source(name) + f"\n tested={name}")
    assert rt.globals().tested() is False
    assert rt.globals().saves == 0
    rt.globals().pressureBenchCapture = False
    assert rt.globals().tested() is True
    assert rt.globals().saves == 1


def test_capture_cannot_be_cleared_and_later_saved_in_the_same_session():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute("config={};pressureBenchCapture=false")
    rt.execute(function_source("applyExternalConfigSet") + "\n tested=applyExternalConfigSet")
    assert rt.globals().tested("pressureBenchCapture", True)[0] is True
    assert rt.globals().tested("pressureBenchCapture", False)[0] is False
    assert rt.globals().pressureBenchCapture is True


@pytest.mark.parametrize("isolated,expected", [(True, 100), (False, 90)])
def test_ai_pb_does_not_replace_the_loaded_human_reference(isolated, expected):
    source = APP.read_text(encoding="utf-8")
    start = source.index("    local isPbThisLap =")
    end = source.index("    state.brakingPoints.last =", start)
    rt = lupa.LuaRuntime()
    rt.execute("""
      config={};lastMs=90;completedTrace={};traceAnalyticsOk=false;feats={}
      state={bestLapMs=100,brakingPoints={best={},session={}}}
      rebuilds=0;copyBpList=function(x)return x end
      rebuildBestReference=function()rebuilds=rebuilds+1 end
      cacheLocalReferenceState=function()end;refreshActiveReference=function()end
    """)
    rt.globals().pressureBenchCapture = isolated
    rt.execute(source[start:end])
    assert rt.globals().state.bestLapMs == expected
    assert rt.globals().rebuilds == (0 if isolated else 1)


def test_actual_native_read_handlers_echo_the_requested_nonce():
    source = APP.read_text(encoding="utf-8")
    start = source.index('  wsBridge.registerRequestHandler("setup.spinner.list"')
    end = source.index('  wsBridge.registerRequestHandler("setup.spinner.set"', start)
    rt = lupa.LuaRuntime()
    rt.execute("""
      handlers={};SESSION_UUID='session'
      wsBridge={registerRequestHandler=function(k,t,f)handlers[k]=f end}
      setupLibrary={listSpinners=function()return {ok=true,spinners={}} end,
       spinnerAudit=function(s)return {session_id=s,attempts=0,writes=0} end}
    """)
    rt.execute(source[start:end])
    for kind in ("setup.spinner.list", "setup.spinner.audit"):
        reply = rt.globals().handlers[kind](rt.table_from({"request_id": "actual-nonce"}))
        assert reply["request_id"] == "actual-nonce"
