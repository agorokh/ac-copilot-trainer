"""Exercise the actual Lua prescription boundary; no real setup/hardware writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
MODULES = Path(__file__).resolve().parents[1] / "src/ac_copilot_trainer/modules"


@pytest.fixture
def lua():
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(f'package.path = "{MODULES.as_posix()}/?.lua;" .. package.path')
    rt.execute(
        """
        pit, writes, pressure, compound = true, 0, 24, 0
        ac = {
          getCar = function() return { isInPit = pit, compoundIndex = compound } end,
          getSim = function() return {} end,
          isCarResetAllowed = function() return true end,
          getSetupSpinners = function()
            return {{name='PRESSURE_LF', value=pressure,min=20,max=35,step=0.5,units='psi'}}
          end,
          setSetupSpinnerValue = function(_, value) writes=writes+1; pressure=value; return true end
        }
        local ch = require('csp_helpers')
        ch.safeCarIdRaw=function() return 'car' end
        ch.safeTrackIdRaw=function() return 'track' end
        ch.safeTrackLayoutRaw=function() return '' end
        local meta = require('ac_content_meta')
        meta.carUI=function() return nil end
        meta.trackUI=function() return nil end
        require('setup_reader').activeSetupIniPath=function() return 'C:/setup.ini' end
        require('persistence').lapArchiveDir=function() return 'C:/trainer/journal/laps' end
        rpc=require('setup_prescription')
        ctx=rpc.handle({request_id=string.rep('a',32),operation='context'}, 'session')
        function apply(id, value)
          return rpc.handle({request_id=string.rep('b',32),operation='apply',
            prescription_id=id or 'card',context_id=ctx.context_id,identity=ctx.identity,
            changes={{section='PRESSURE_LF',from=24,to=value or 23}}}, 'session')
        end
        """
    )
    return rt


def test_context_reports_actual_pit_not_broad_reset_permission(lua):
    lua.execute("pit=false; ctx=rpc.handle({request_id='new',operation='context'},'session')")
    assert lua.globals().ctx["is_in_pit"] is False
    assert lua.globals().ctx["reset_allowed"] is True


def test_manual_pressure_comparator_survives_actual_screen_payload_budget(lua):
    from tools.ai_sidecar.server import _fit_screen_peer_payload

    lua.execute("""
      ac.getSetupSpinners = function()
        local rows = {}
        for i=1,40 do
          rows[#rows+1]={name='DAMP_BUMP_'..i,value=7,min=0,max=20,step=1,units=''}
        end
        for _,name in ipairs({'FRONT_BIAS','ABS','TRACTION_CONTROL','WING_1','WING_2'}) do
          rows[#rows+1]={name=name,value=5,min=0,max=70,step=1,units=''}
        end
        for _,corner in ipairs({'LF','RF','LR','RR'}) do
          rows[#rows+1]={name='PRESSURE_'..corner,value=17,min=12,max=40,step=1,units='psi'}
        end
        return rows
      end
      comparator = require('setup_library').listSpinners()
    """)
    result = lua.globals().comparator
    rows = [dict(row.items()) for row in result["spinners"].values()]
    frame = {"v": 1, "type": "setup.spinner.list.result", "ok": True, "spinners": rows}
    payload = _fit_screen_peer_payload(frame, json.dumps(frame))
    visible = json.loads(payload)["spinners"]
    pressures = [r for r in visible if r["section"].startswith("PRESSURE_")]
    assert len(payload.encode()) <= 2600
    assert len(visible) <= 12
    assert [r["section"] for r in pressures] == [
        "PRESSURE_LF",
        "PRESSURE_RF",
        "PRESSURE_LR",
        "PRESSURE_RR",
    ]
    assert all(r["range_known"] and r["unit"] == "psi" and r["min"] == 12 for r in pressures)
    assert lua.globals().writes == 0


def test_exit_before_accept_performs_zero_writes_and_retry_stays_zero(lua):
    lua.execute("pit=false")
    for _ in range(2):
        result = lua.eval("apply()")
        assert result["ok"] is False
        assert "pit box" in result["error"]
    assert lua.globals().writes == 0


def test_applied_value_requires_readback_and_duplicate_never_writes(lua):
    result = lua.eval("apply()")
    assert result["ok"] is True
    assert result["readback"]["PRESSURE_LF"] == 23
    assert lua.globals().writes == 1
    duplicate = lua.eval("apply()")
    assert duplicate["ok"] is False
    assert lua.globals().writes == 1


def test_setter_acceptance_without_readback_stays_unverified(lua):
    lua.execute("ac.setSetupSpinnerValue=function() writes=writes+1; return true end")
    result = lua.eval("apply()")
    assert result["ok"] is False
    assert "readback" in result["error"] or "confirmed" in result["error"]
    assert lua.globals().writes == 1
    lua.eval("apply()")
    assert lua.globals().writes == 1


@pytest.mark.parametrize("value", [23.2, 17, 26, float("nan")])
def test_invalid_or_oversized_pressure_change_never_writes(lua, value):
    result = lua.globals().apply("bad", value)
    assert result["ok"] is False
    assert lua.globals().writes == 0


def test_compound_session_and_value_change_invalidate_proposal(lua):
    lua.execute("compound=1")
    assert lua.eval("apply()")["ok"] is False
    assert lua.globals().writes == 0


def test_pit_is_rechecked_after_spinner_lookup_at_setter(lua):
    # The batch precheck succeeds; the setter's own subsequent lookup makes
    # pit=false. Its final authoritative check must catch that transition.
    lua.execute(
        """
        original=ac.getSetupSpinners
        lookups=0
        ac.getSetupSpinners=function()
          lookups=lookups+1
          if lookups>=2 then pit=false end
          return original()
        end
        """
    )
    result = lua.eval("apply()")
    assert result["ok"] is False
    assert lua.globals().writes == 0


def test_batch_validation_is_complete_before_first_write(lua):
    result = lua.execute(
        """
        return rpc.handle({operation='apply',prescription_id='batch',context_id=ctx.context_id,
          identity=ctx.identity,changes={{section='PRESSURE_LF',from=24,to=23},
            {section='WING_1',from=1,to=2}}},'session')
        """
    )
    assert result["ok"] is False
    assert lua.globals().writes == 0


def test_generic_spinner_path_without_prescription_retains_behavior(lua):
    lua.execute("pit=false")
    result = lua.execute(
        "return require('setup_library').setSpinner({section='PRESSURE_LF',value=23})"
    )
    assert result["ok"] is True
    assert lua.globals().writes == 1


@pytest.mark.parametrize("field,value", [("units", "bar"), ("displayMultiplier", 2)])
def test_authoritative_boundary_refuses_non_psi_or_scaled_values(lua, field, value):
    lua.globals().field, lua.globals().invalid = field, value
    lua.execute(
        """
        original=ac.getSetupSpinners
        ac.getSetupSpinners=function()
          local rows=original(); rows[1][field]=invalid; return rows
        end
        """
    )
    assert lua.eval("apply()")["ok"] is False
    assert lua.globals().writes == 0


def test_final_full_readback_detects_later_coupled_change(lua):
    lua.execute(
        """
        rf=24
        ac.getSetupSpinners=function()
          return {{name='PRESSURE_LF',value=pressure,min=20,max=35,step=0.5,units='psi'},
            {name='PRESSURE_RF',value=rf,min=20,max=35,step=0.5,units='psi'}}
        end
        ac.setSetupSpinnerValue=function(section,value)
          writes=writes+1
          if section=='PRESSURE_LF' then pressure=value
          else rf=value; pressure=25 end
          return true
        end
        """
    )
    result = lua.execute(
        """
        return rpc.handle({operation='apply',prescription_id='coupled',context_id=ctx.context_id,
          identity=ctx.identity,changes={{section='PRESSURE_LF',from=24,to=23},
            {section='PRESSURE_RF',from=24,to=23}}},'session')
        """
    )
    assert result["ok"] is False
    assert result["error"] == "Awaiting complete cold-pressure readback"
    assert lua.globals().writes == 2
